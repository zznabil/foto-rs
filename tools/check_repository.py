# SPDX-License-Identifier: GPL-3.0-or-later
"""Repository release-contract checks; workflow syntax is checked separately by actionlint."""
import json
from pathlib import Path
import re
import subprocess
import tomllib

ROOT=Path(__file__).resolve().parents[1]


def main():
    package=tomllib.loads((ROOT/'Cargo.toml').read_text(encoding='utf-8'))['package']
    assert package['license']=='GPL-3.0-or-later' and package['publish'] is False
    version=package['version']
    assert re.fullmatch(r'\d+\.\d+\.\d+',version)
    for name in ['LICENSE','COPYRIGHT','THIRD_PARTY.md','CONTRIBUTING.md','SECURITY.md',f'docs/releases/v{version}.md']:
        assert (ROOT/name).is_file(),name
    assert b'GNU GENERAL PUBLIC LICENSE' in (ROOT/'LICENSE').read_bytes()
    lock=tomllib.loads((ROOT/'Cargo.lock').read_text(encoding='utf-8'))
    assert next(x for x in lock['package'] if x['name']=='foto')['version']==version
    paths=subprocess.check_output(['git','ls-files','-z'],cwd=ROOT).decode().split('\0')
    paths=[p for p in paths if p]
    forbidden=('.agent-state/','target/','dist/','artifacts/','baselines/','release-out/','.env')
    assert not [p for p in paths if p.startswith(forbidden)],'Internal/generated files tracked'
    patterns=[rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----',rb'\bgh[pousr]_[A-Za-z0-9]{30,}',rb'\bgithub_pat_[A-Za-z0-9_]{50,}',rb'\bAKIA[A-Z0-9]{16}\b']
    for name in paths:
        data=(ROOT/name).read_bytes()
        assert not any(re.search(pattern,data) for pattern in patterns),f'Credential pattern in {name}'
    for path in (ROOT/'.github/workflows').glob('*.yml'):
        value=path.read_text(encoding='utf-8')
        assert 'pull_request_target' not in value,'Do not execute PR source with privileged tokens'
        for action in re.findall(r'uses:\s*([^\s#]+)',value):
            assert action.startswith('./') or re.fullmatch(r'[\w.-]+/[\w./-]+@[a-f0-9]{40}',action),f'Unpinned action: {action}'
    pins=json.loads((ROOT/'tools/tool-pins.json').read_text(encoding='utf-8'))
    for hosts in pins.values():
        for pin in hosts.values():assert re.fullmatch(r'[a-f0-9]{64}',pin['sha256']) and pin['url'].startswith('https://github.com/')
    print('FOTO_REPOSITORY_CONTRACT_PASS')


if __name__=='__main__':main()
