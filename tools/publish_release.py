# SPDX-License-Identifier: GPL-3.0-or-later
"""Download a draft release, verify every asset and provenance, smoke-test it, then publish."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import zipfile
from check_release import check, safe_members, require

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--tag',required=True)
    parser.add_argument('--repo',default='zznabil/foto-rs')
    parser.add_argument('--expected-commit',required=True)
    parser.add_argument('--publish',action='store_true')
    args=parser.parse_args()
    require(re.fullmatch(r'v\d+\.\d+\.\d+',args.tag) is not None,'Invalid release tag')
    require(re.fullmatch(r'[\w.-]+/[\w.-]+',args.repo) is not None,'Invalid repository')
    def api(path):return json.loads(subprocess.check_output(['gh','api',f'repos/{args.repo}/{path}'],text=True))
    release=api('releases/tags/'+args.tag)
    if args.publish:require(release['draft'],'Refuse to modify an already-published release')
    ref=api('git/ref/tags/'+args.tag)['object']
    if ref['type']=='tag':ref=api('git/tags/'+ref['sha'])['object']
    require(ref['sha']==args.expected_commit,'Remote tag source mismatch')
    directory=ROOT/'artifacts/downloaded'/f'{args.tag}-{time.time_ns()}'
    directory.mkdir(parents=True)
    subprocess.run(['gh','release','download',args.tag,'--repo',args.repo,'--dir',str(directory)],check=True)
    assets={a['name']:a for a in release['assets']}
    actual={p.name for p in directory.iterdir() if p.is_file()}
    require(actual==set(assets),'Downloaded asset set differs from GitHub metadata')
    for path in directory.iterdir():
        digest=hashlib.sha256(path.read_bytes()).hexdigest()
        require(assets[path.name]['digest']=='sha256:'+digest,'GitHub asset digest mismatch: '+path.name)
        require(assets[path.name]['size']==path.stat().st_size,'GitHub asset size mismatch')
    build=check(directory,args.expected_commit)
    for path in sorted(directory.iterdir()):
        if path.suffix in ('.zip','.json'):
            command=['gh','attestation','verify',str(path),'--repo',args.repo,
                     '--signer-workflow',args.repo+'/.github/workflows/release.yml',
                     '--source-ref','refs/tags/'+args.tag,'--source-digest',args.expected_commit,
                     '--deny-self-hosted-runners','--format','json']
            for attempt in range(3):
                result=subprocess.run(command,capture_output=True,text=True,encoding='utf-8',errors='replace')
                if result.returncode==0:break
                if attempt==2:raise RuntimeError('Provenance verification failed: '+path.name+'\n'+result.stderr)
                time.sleep(5)
            (directory/(path.name+'.verification.txt')).write_text(result.stdout+'\n'+result.stderr,encoding='utf-8')
    archive=directory/f'Foto-{build["version"]}-windows-x64.zip'
    unpacked=directory/'unpacked'
    with zipfile.ZipFile(archive) as source:
        safe_members(source)
        source.extractall(unpacked)
    exe=unpacked/f'Foto-{build["version"]}/foto.exe'
    for command,marker in [
        ([sys.executable,str(ROOT/'tools/check_defender.py'),str(exe),'--output',str(directory/'defender-scan.json')],'FOTO_DEFENDER_SCAN_PASS'),
        ([sys.executable,str(ROOT/'tools/check_portable.py'),str(exe)],'PORTABLE_DEPENDENCIES_PASS'),
        ([sys.executable,str(ROOT/'tools/check_version.py'),str(exe),'--version',build['version']],'VERSION_METADATA_PASS'),
        ([sys.executable,str(ROOT/'tools/smoke_test.py'),'--exe',str(exe),'--runs','3'],'FOTO_SMOKE_PASS'),
    ]:
        result=subprocess.run(command,cwd=ROOT,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=300)
        require(result.returncode==0 and marker in result.stdout.splitlines(),'Downloaded binary validation failed\n'+result.stdout+'\n'+result.stderr)
    receipt={'verdict':'PASS','tag':args.tag,'source_commit':args.expected_commit,'release_id':release['id'],
             'assets':{name:assets[name]['digest'] for name in sorted(assets)},
             'provenance':'GitHub-hosted release.yml; exact source tag/digest; verified for ZIP and JSON assets',
             'downloaded_binary_smoke':'PASS','published':False}
    if args.publish:
        subprocess.run(['gh','release','edit',args.tag,'--repo',args.repo,'--draft=false','--latest'],check=True)
        public=api('releases/tags/'+args.tag)
        require(not public['draft'] and not public['prerelease'],'Release is not publicly stable')
        require({a['name']:a['digest'] for a in public['assets']}=={name:assets[name]['digest'] for name in assets},'Assets changed during publication')
        receipt['published']=True
    (directory/'publication-receipt.json').write_text(json.dumps(receipt,indent=2)+'\n',encoding='utf-8')
    print('PUBLICATION_RECEIPT',directory/'publication-receipt.json')
    print('FOTO_PUBLISHED_RELEASE_PASS' if args.publish else 'FOTO_PUBLIC_RELEASE_READBACK_PASS')


if __name__=='__main__':main()
