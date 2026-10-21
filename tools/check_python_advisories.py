# SPDX-License-Identifier: GPL-3.0-or-later
"""Check every exact development pin against PyPI's version-specific advisory feed."""
import argparse
import json
from pathlib import Path
import re
import time
import urllib.parse
import urllib.request


def check(path):
    pins=[]
    for line in path.read_text(encoding='utf-8').splitlines():
        line=line.strip().removesuffix('\\').strip()
        if not line or line.startswith('#'):
            continue
        if re.fullmatch(r'--hash=sha256:[a-f0-9]{64}',line):
            continue
        match=re.fullmatch(r'([A-Za-z0-9_.-]+)==([A-Za-z0-9.+!-]+)',line)
        if not match:
            raise ValueError('Expected an exact Python dependency pin: '+line)
        pins.append(match.groups())
    if not pins:
        raise ValueError('No Python dependencies were checked')
    affected=[]
    for name,version in pins:
        url='https://pypi.org/pypi/'+urllib.parse.quote(name,safe='')+'/'+urllib.parse.quote(version,safe='')+'/json'
        for attempt in range(3):
            try:
                with urllib.request.urlopen(url,timeout=30) as response:
                    data=json.load(response)
                break
            except OSError:
                if attempt==2:
                    raise
                time.sleep(2)
        canonical=lambda value:re.sub(r'[-_.]+','-',value).lower()
        if canonical(data['info']['name'])!=canonical(name) or data['info']['version']!=version:
            raise ValueError('Python advisory response identifies different package bytes')
        if not isinstance(data['vulnerabilities'],list):
            raise ValueError('Invalid Python advisory response')
        active=[v['id'] for v in data['vulnerabilities'] if not v.get('withdrawn')]
        print(json.dumps({'package':name,'version':version,'active_advisories':active}))
        if active:
            affected.append(name+'=='+version)
    if affected:
        raise ValueError('Known Python advisories: '+', '.join(affected))
    print('FOTO_PYTHON_ADVISORIES_PASS')


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--requirements',type=Path,default=Path(__file__).resolve().parents[1]/'requirements-dev.txt')
    check(parser.parse_args().requirements)
