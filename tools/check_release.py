# SPDX-License-Identifier: GPL-3.0-or-later
"""Independently check release file sets, ZIP contents, hashes, source and inventory."""
import argparse
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import tomllib
import tarfile
import subprocess
import zipfile


def require(condition,message):
    if not condition:raise ValueError(message)


def check_checksums(directory):
    entries={}
    for line in (directory/'SHA256SUMS.txt').read_text(encoding='utf-8').splitlines():
        match=re.fullmatch(r'([a-f0-9]{64})  ([A-Za-z0-9_.-]+)',line)
        require(match is not None,'Malformed or unsafe checksum entry')
        digest,name=match.groups()
        require(name not in entries and name!='SHA256SUMS.txt','Duplicate or self-referencing checksum entry')
        require((directory/name).is_file(),f'Missing release file: {name}')
        require(hashlib.sha256((directory/name).read_bytes()).hexdigest()==digest,f'Checksum mismatch: {name}')
        entries[name]=digest
    actual={p.name for p in directory.iterdir() if p.is_file() and p.name!='SHA256SUMS.txt'}
    require(set(entries)==actual,'Unlisted or missing release assets')
    return entries


def safe_members(archive):
    names=archive.namelist()
    require(all(info.orig_filename==info.filename for info in archive.infolist()),'Unsafe ZIP path normalization')
    require(len(names)==len({name.casefold() for name in names}),'Duplicate ZIP entry on Windows')
    require(len(names)<=100000,'Too many ZIP entries')
    require(sum(x.file_size for x in archive.infolist())<=1024**3,'ZIP exceeds 1 GiB unpacked guard')
    for name in names:
        path=PurePosixPath(name)
        require(not path.is_absolute() and '..' not in path.parts and '\\' not in name and ':' not in name,'Unsafe ZIP path')
        mode=(archive.getinfo(name).external_attr>>16)&0o170000
        require(mode not in (0o120000,), 'Symlinks are not permitted in release ZIPs')
    require(archive.testzip() is None,'ZIP CRC failure')
    return names


def check(directory,expected_commit):
    entries=check_checksums(directory)
    build=json.loads((directory/'build-info.json').read_text(encoding='utf-8'))
    version=build['version']
    require(re.fullmatch(r'\d+\.\d+\.\d+',version) is not None,'Invalid release version')
    require(build['source_commit']==expected_commit,'Release source commit mismatch')
    require(build['authenticode_signed'] is False,'Unexpected signing claim')
    required={f'Foto-{version}-windows-x64.zip',f'Foto-{version}-source.zip','build-info.json','sbom.spdx.json','source-verification.json'}
    require(required<=set(entries),'Missing required release assets')
    require(set(entries)<=required|{'provenance.jsonl'},'Unexpected release assets')
    proof=json.loads((directory/'source-verification.json').read_text(encoding='utf-8'))
    require(proof['verdict']=='PASS' and proof['source_commit']==expected_commit,'Offline source rebuild proof missing or stale')
    require(proof['version']==version and proof['offline'] and proof['empty_cargo_home'],'Source rebuild was not isolated/offline')
    require(proof['archive_sha256']==entries[f'Foto-{version}-source.zip'],'Source rebuild proof names different archive bytes')
    require({g['id'] for g in proof['gates']}=={'offline-build','offline-unit','portable','version-info','smoke'} and all(g['exit_code']==0 and g['verdict']=='PASS' for g in proof['gates']),'Incomplete source rebuild gates')
    with zipfile.ZipFile(directory/f'Foto-{version}-windows-x64.zip') as archive:
        names=safe_members(archive);prefix=f'Foto-{version}/'
        required_inside={'foto.exe','LICENSE','COPYRIGHT','THIRD_PARTY.md','README.txt','build-info.json','sbom.spdx.json','SHA256SUMS.txt','evidence/checks.json','evidence/smoke.json','evidence/stress.json','evidence/malformed.json','evidence/defender.json','licenses/rust/COPYRIGHT-library.html'}
        require({prefix+x for x in required_inside}<=set(names),'Incomplete portable ZIP')
        executable=archive.read(prefix+'foto.exe')
        require(hashlib.sha256(executable).hexdigest()==build['exe_sha256'],'Packaged executable differs from tested build')
        require(archive.read(prefix+'build-info.json')==(directory/'build-info.json').read_bytes(),'Build metadata mismatch')
        require(archive.read(prefix+'sbom.spdx.json')==(directory/'sbom.spdx.json').read_bytes(),'Inventory mismatch')
        internal={}
        for line in archive.read(prefix+'SHA256SUMS.txt').decode().splitlines():
            digest,name=line.split('  ',1)
            require(name not in internal,'Duplicate internal checksum entry')
            require(hashlib.sha256(archive.read(prefix+name)).hexdigest()==digest,'Portable ZIP internal checksum mismatch')
            internal[name]=digest
        require({prefix+name for name in internal}==set(names)-{prefix+'SHA256SUMS.txt'},'Unlisted portable ZIP members')
        for name in ['checks','smoke','stress','malformed','defender']:
            report=json.loads(archive.read(prefix+f'evidence/{name}.json'))
            require(report['exe_sha256']==build['exe_sha256'],'Stale runtime evidence')
            if name=='defender':
                require(report['post_scan_sha256']==build['exe_sha256'] and report['exit_code']==0
                        and 'found no threats.' in report['stdout']
                        and report['status']['AntivirusEnabled'] and report['status']['RealTimeProtectionEnabled'],
                        'Defender did not establish a clean result for these bytes')
            if name=='checks':require(report['source_commit']==expected_commit and not report['tracked_tree_dirty'],'Tested source mismatch')
            if name=='stress':require(len(report['results'])==12 and all(x['verdict']=='PASS' for x in report['results']),'Journey failure')
            else:require(report['verdict']=='PASS','Failed runtime evidence')
    with zipfile.ZipFile(directory/f'Foto-{version}-source.zip') as archive:
        names=safe_members(archive);prefix=f'Foto-{version}-source/'
        require(archive.read(prefix+'SOURCE_COMMIT.txt').decode().strip()==expected_commit,'Source archive commit mismatch')
        manifest=tomllib.loads(archive.read(prefix+'Cargo.toml').decode())
        require(manifest['package']['version']==version and manifest['package']['license']=='GPL-3.0-or-later','Source version/license mismatch')
        require(b'vendored-sources' in archive.read(prefix+'.cargo/config.toml'),'Missing vendored source configuration')
        require(not any(n.startswith(prefix+'.agent-state/') or n.startswith(prefix+'target/') for n in names),'Internal or build residue in source ZIP')
        checkout=Path(__file__).resolve().parents[1]
        committed=subprocess.check_output(['git','archive','--format=tar',expected_commit],cwd=checkout)
        with tarfile.open(fileobj=io.BytesIO(committed)) as reference:
            for member in reference.getmembers():
                if not member.isfile():continue
                expected_bytes=reference.extractfile(member).read()
                actual_bytes=archive.read(prefix+member.name)
                if member.name=='.cargo/config.toml':
                    require(actual_bytes.startswith(expected_bytes),'Source Cargo configuration lost committed settings')
                else:require(actual_bytes==expected_bytes,'Source ZIP differs from committed file: '+member.name)
        lock=tomllib.loads(archive.read(prefix+'Cargo.lock').decode())
        for package in lock['package']:
            if 'source' in package:
                require(prefix+f'vendor/{package["name"]}-{package["version"]}/Cargo.toml' in names,'Incomplete vendored dependency closure')
    inventory=json.loads((directory/'sbom.spdx.json').read_text(encoding='utf-8'))
    from check_sbom import check as check_sbom
    check_sbom(inventory)
    require(inventory['spdxVersion']=='SPDX-2.3','Unexpected inventory format')
    actual={(x['name'],x['versionInfo']) for x in inventory['packages'] if x['SPDXID']!='SPDXRef-RustToolchain'}
    expected={(x['name'],x['version']) for x in lock['package']}
    require(actual==expected,'Inventory does not match Cargo.lock')
    require(sum(x['SPDXID']=='SPDXRef-RustToolchain' for x in inventory['packages'])==1,'Missing build tool inventory')
    print('FOTO_RELEASE_INTEGRITY_PASS')
    return build


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('directory',type=Path)
    parser.add_argument('--expected-commit',required=True)
    args=parser.parse_args()
    check(args.directory,args.expected_commit)
