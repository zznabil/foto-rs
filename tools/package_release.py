# SPDX-License-Identifier: GPL-3.0-or-later
"""Package the tested executable, complete vendored project source, notices and inventory."""
import argparse
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import tarfile
import tomllib
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def write_zip(path, files, prefix):
    with zipfile.ZipFile(path,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as archive:
        for name,data in sorted(files.items()):
            entry=zipfile.ZipInfo(prefix+'/'+name,(2020,1,1,0,0,0))
            entry.compress_type=zipfile.ZIP_DEFLATED
            entry.external_attr=0o100644 << 16
            archive.writestr(entry,data)
    with zipfile.ZipFile(path) as archive:assert archive.testzip() is None


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,default=ROOT/'release-out')
    args=parser.parse_args()
    output=args.output.resolve()
    assert not output.exists(), 'Refuse to mix a new release with existing output'
    assert not subprocess.check_output(['git','status','--porcelain','--untracked-files=no'],cwd=ROOT,text=True).strip(), 'Commit source changes before packaging'
    source_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    config=tomllib.loads((ROOT/'Cargo.toml').read_text(encoding='utf-8'))
    version=config['package']['version']
    evidence=ROOT/'artifacts/ci'
    checks=json.loads((evidence/'reports/checks.json').read_text(encoding='utf-8'))
    exe=evidence/'foto.exe'
    assert checks['verdict']=='PASS' and not checks['tracked_tree_dirty']
    assert checks['source_commit']==source_commit and checks['exe_sha256']==digest(exe)
    expected={'format','clippy','unit','release-build','uia-build','fixtures','portable','version-info','smoke','stress','malformed','source-integrity'}
    assert {g['id'] for g in checks['gates']}==expected and all(g['verdict']=='PASS' for g in checks['gates'])
    for name in ['smoke','stress','malformed']:
        report=json.loads((evidence/f'reports/{name}.json').read_text(encoding='utf-8'))
        assert report['exe_sha256']==digest(exe)
        if name=='stress':assert len(report['results'])==12 and all(x['verdict']=='PASS' for x in report['results'])
        else:assert report['verdict']=='PASS'
    metadata=json.loads(subprocess.check_output(['cargo','metadata','--locked','--format-version','1'],cwd=ROOT,text=True))
    lock=tomllib.loads((ROOT/'Cargo.lock').read_text(encoding='utf-8'))
    sums={(x['name'],x['version']):x.get('checksum') for x in lock['package']}
    output.mkdir(parents=True)
    stage=ROOT/'artifacts/package'/source_commit
    assert not stage.exists(), 'Archive previous package work before retrying the same source'
    stage.mkdir(parents=True)
    vendor=stage/'vendor'
    subprocess.run(['cargo','vendor','--locked','--versioned-dirs',str(vendor)],cwd=ROOT,check=True)
    notices={}
    packages=[]
    identities={p['id']:'SPDXRef-'+p['name']+'-'+p['version'] for p in metadata['packages']}
    for package in metadata['packages']:
        name,release=package['name'],package['version']
        item={'name':name,'SPDXID':identities[package['id']],'versionInfo':release,'filesAnalyzed':False,
              'downloadLocation':f'https://crates.io/api/v1/crates/{name}/{release}/download' if package['source'] else f'https://github.com/zznabil/foto-rs/tree/{source_commit}',
              'licenseDeclared':package['license'] or 'NOASSERTION','licenseConcluded':'NOASSERTION',
              'copyrightText':'NOASSERTION', 'externalRefs':[{'referenceCategory':'PACKAGE-MANAGER','referenceType':'purl','referenceLocator':f'pkg:cargo/{name}@{release}'}]}
        if sums[(name,release)]:item['checksums']=[{'algorithm':'SHA256','checksumValue':sums[(name,release)]}]
        packages.append(item)
        if package['source']:
            directory=Path(package['manifest_path']).parent
            found=[p for p in directory.iterdir() if p.is_file() and p.name.lower().startswith(('license','copying','notice','copyright'))]
            assert found, f'Missing upstream notices for {name}'
            for path in found:notices[f'licenses/cargo/{name}-{release}/{path.name}']=path.read_bytes()
    root_id=identities[metadata['resolve']['root']]
    relationships=[{'spdxElementId':'SPDXRef-DOCUMENT','relationshipType':'DESCRIBES','relatedSpdxElement':root_id}]
    for node in metadata['resolve']['nodes']:
        for dependency in node['dependencies']:
            relationships.append({'spdxElementId':identities[node['id']],'relationshipType':'DEPENDS_ON','relatedSpdxElement':identities[dependency]})
    packages.append({'name':'rust-toolchain','SPDXID':'SPDXRef-RustToolchain','versionInfo':checks['rustc'].split()[1],
                     'filesAnalyzed':False,'downloadLocation':'https://static.rust-lang.org/dist/channel-rust-'+checks['rustc'].split()[1]+'.toml',
                     'licenseDeclared':'NOASSERTION','licenseConcluded':'NOASSERTION','copyrightText':'NOASSERTION'})
    relationships.append({'spdxElementId':'SPDXRef-RustToolchain','relationshipType':'BUILD_TOOL_OF','relatedSpdxElement':root_id})
    sbom={'spdxVersion':'SPDX-2.3','dataLicense':'CC0-1.0','SPDXID':'SPDXRef-DOCUMENT',
          'name':f'Foto-{version}-Cargo-inventory','documentNamespace':f'https://github.com/zznabil/foto-rs/spdx/{source_commit}',
          'creationInfo':{'created':datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),'creators':['Tool: Foto package_release.py']},
          'documentComment':'Cargo dependency closure, including build-time proc-macros. Rust toolchain is a build tool; bundled standard-library component notices are separate. Windows system DLL internals are outside scope.',
          'packages':packages,'relationships':relationships}
    build={'version':version,'source_commit':source_commit,'exe_sha256':digest(exe),'exe_bytes':exe.stat().st_size,
           'rustc':checks['rustc'],'host':checks['host'],'runner_image':checks['runner_image'],
           'workflow_ref':checks.get('workflow_ref'),'run_url':checks.get('run_url'),
           'recipe':'python tools/verify.py; python tools/package_release.py; python tools/verify_source.py',
           'authenticode_signed':False,'reproducible_build_claim':False,'dependency_lock_sha256':digest(ROOT/'Cargo.lock'),
           'inventory_scope':'Cargo lockfile dependency closure; Rust library notices separate; Windows system DLL internals excluded',
           'gates':checks['gates']}
    sysroot=Path(subprocess.check_output(['rustc','--print','sysroot'],text=True).strip())
    copyright_file=sysroot/'share/doc/rust/COPYRIGHT-library.html'
    assert copyright_file.is_file(), 'Install rust-docs for the pinned toolchain; complete Rust library notices are required'
    notices['licenses/rust/COPYRIGHT-library.html']=copyright_file.read_bytes()
    rust_licenses=sysroot/'share/doc/rust/licenses'
    assert rust_licenses.is_dir()
    for path in rust_licenses.iterdir():
        if path.is_file():notices['licenses/rust/licenses/'+path.name]=path.read_bytes()
    portable={'foto.exe':exe.read_bytes(),'LICENSE':(ROOT/'LICENSE').read_bytes(),
              'COPYRIGHT':(ROOT/'COPYRIGHT').read_bytes(),'THIRD_PARTY.md':(ROOT/'THIRD_PARTY.md').read_bytes(),
              'build-info.json':(json.dumps(build,indent=2)+'\n').encode(),
              'sbom.spdx.json':(json.dumps(sbom,indent=2)+'\n').encode(),**notices}
    portable['README.txt']=f'''Foto {version} - portable Windows x64 photo viewer

Run foto.exe. Drop a photo into the window or press Ctrl+O.
Left/Right: browse. Wheel: zoom. Drag: pan. R: rotate. 0: fit. 1: actual pixels.
F11: full screen. Escape: leave full screen or close. F1: help.
Photos are read only. No installation or separate VC++ runtime is required.

GPL-3.0-or-later; see LICENSE, COPYRIGHT and THIRD_PARTY.md.
Corresponding source, including vendored Cargo dependencies and build scripts:
https://github.com/zznabil/foto-rs/releases/tag/v{version}
Choose Foto-{version}-source.zip on that page.

The executable is not Authenticode-signed. GitHub provenance is separate from
Windows code signing. Verify checksums and provenance before running it.
Windows 11 local testing and Windows Server CI are recorded in evidence/.
Windows 10 and real multi-monitor transfers remain independently unverified.
Build details and dependency inventory: build-info.json and sbom.spdx.json.
'''.encode()
    for path in (evidence/'reports').glob('*.json'):portable['evidence/'+path.name]=path.read_bytes()
    portable['SHA256SUMS.txt']=''.join(hashlib.sha256(data).hexdigest()+'  '+name+'\n' for name,data in sorted(portable.items())).encode()
    write_zip(output/f'Foto-{version}-windows-x64.zip',portable,f'Foto-{version}')
    source={}
    archive_bytes=subprocess.check_output(['git','archive','--format=tar',source_commit],cwd=ROOT)
    with tarfile.open(fileobj=io.BytesIO(archive_bytes)) as archive:
        for member in archive.getmembers():
            if member.isfile():source[member.name]=archive.extractfile(member).read()
            elif not member.isdir():raise RuntimeError('Unexpected non-regular tracked source member')
    source['.cargo/config.toml']+=b'\n[source.crates-io]\nreplace-with = "vendored-sources"\n\n[source.vendored-sources]\ndirectory = "vendor"\n'
    for path in vendor.rglob('*'):
        if path.is_file():source['vendor/'+path.relative_to(vendor).as_posix()]=path.read_bytes()
    source['SOURCE_COMMIT.txt']=(source_commit+'\n').encode()
    write_zip(output/f'Foto-{version}-source.zip',source,f'Foto-{version}-source')
    (output/'sbom.spdx.json').write_text(json.dumps(sbom,indent=2)+'\n',encoding='utf-8')
    (output/'build-info.json').write_text(json.dumps(build,indent=2)+'\n',encoding='utf-8')
    print('FOTO_PACKAGE_PASS')


if __name__=='__main__':main()
