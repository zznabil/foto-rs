# SPDX-License-Identifier: GPL-3.0-or-later
"""Rebuild the distributed vendored source offline with an empty Cargo home, then smoke-test it."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import tomllib
import zipfile
from check_release import safe_members, require

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('archive',type=Path)
    parser.add_argument('--expected-commit',required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    parent=ROOT/'artifacts/source-rebuild'
    parent.mkdir(parents=True,exist_ok=True)
    report={'verdict':'IN_PROGRESS','source_commit':args.expected_commit,'archive_sha256':hashlib.sha256(args.archive.read_bytes()).hexdigest(),
            'offline':True,'empty_cargo_home':True,'byte_identical_build_claim':False,'gates':[]}
    def save():args.output.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    save()
    with tempfile.TemporaryDirectory(prefix='source-',dir=parent) as directory:
        temporary=Path(directory).resolve()
        require(temporary.is_relative_to(parent.resolve()),'Source sandbox escaped workspace')
        with zipfile.ZipFile(args.archive) as archive:
            names=safe_members(archive)
            roots={name.split('/')[0] for name in names}
            require(len(roots)==1,'Expected one source root')
            archive.extractall(temporary)
        source=temporary/roots.pop()
        require((source/'SOURCE_COMMIT.txt').read_text().strip()==args.expected_commit,'Wrong source revision')
        config=tomllib.loads((source/'Cargo.toml').read_text(encoding='utf-8'))
        env=os.environ.copy()
        env['CARGO_HOME']=str(temporary/'empty-cargo-home')
        env['CARGO_TARGET_DIR']=str(temporary/'target')
        for name,command,cwd,marker in [
            ('offline-build',['cargo','build','--release','--offline','--locked'],source,None),
            ('offline-unit',['cargo','test','--offline','--locked'],source,None),
            ('portable',[sys.executable,str(ROOT/'tools/check_portable.py'),str(temporary/'target/release/foto.exe')],ROOT,'PORTABLE_DEPENDENCIES_PASS'),
            ('version-info',[sys.executable,str(ROOT/'tools/check_version.py'),str(temporary/'target/release/foto.exe'),'--version',config['package']['version']],ROOT,'VERSION_METADATA_PASS'),
            ('smoke',[sys.executable,str(ROOT/'tools/smoke_test.py'),'--exe',str(temporary/'target/release/foto.exe'),'--runs','3'],ROOT,'FOTO_SMOKE_PASS'),
        ]:
            result=subprocess.run(command,cwd=cwd,env=env,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=1800)
            (parent/f'{args.expected_commit}-{name}.txt').write_text(result.stdout+'\n'+result.stderr,encoding='utf-8')
            passed=result.returncode==0 and (marker is None or marker in result.stdout.splitlines())
            report['gates'].append({'id':name,'exit_code':result.returncode,'verdict':'PASS' if passed else 'FAIL'})
            save()
            if not passed:
                print(result.stdout,result.stderr)
                raise RuntimeError(f'Offline source {name} failed')
        report.update(verdict='PASS',version=config['package']['version'],rebuilt_exe_sha256=hashlib.sha256((temporary/'target/release/foto.exe').read_bytes()).hexdigest())
        save()
    print('FOTO_SOURCE_REBUILD_PASS')


if __name__=='__main__':main()
