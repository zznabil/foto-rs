# SPDX-License-Identifier: GPL-3.0-or-later
"""Download a pinned verification tool, check its archive hash, extract one file, run it."""
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tarfile
import time
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    name, *arguments = sys.argv[1:]
    host = 'windows' if sys.platform == 'win32' else 'linux'
    assert platform.machine().lower() in ('amd64', 'x86_64'), 'Only x64 tool pins exist'
    pin = json.loads((ROOT/'tools/tool-pins.json').read_text(encoding='utf-8'))[name][host]
    target = ROOT/'artifacts/tools'/name/pin['version']/pin['binary']
    target.parent.mkdir(parents=True, exist_ok=True)
    # Always validate the download, not an unverified PATH executable or cache.
    for attempt in range(3):
        try:
            request = urllib.request.Request(pin['url'], headers={'User-Agent':'foto-verifier'})
            with urllib.request.urlopen(request, timeout=30) as response:
                archive = response.read()
            break
        except OSError:
            if attempt == 2:raise
            time.sleep(2)
    assert hashlib.sha256(archive).hexdigest() == pin['sha256'], 'Tool archive checksum mismatch'
    if pin['url'].endswith('.zip'):
        with zipfile.ZipFile(io.BytesIO(archive)) as source:
            matches = [n for n in source.namelist() if Path(n).name == pin['binary']]
            assert len(matches) == 1
            payload = source.read(matches[0])
    else:
        with tarfile.open(fileobj=io.BytesIO(archive), mode='r:gz') as source:
            matches = [m for m in source.getmembers() if m.isfile() and Path(m.name).name == pin['binary']]
            assert len(matches) == 1
            payload = source.extractfile(matches[0]).read()
    target.write_bytes(payload)
    if host != 'windows':target.chmod(0o700)
    subprocess.run([str(target), *arguments], cwd=ROOT, check=True)
    print('PINNED_TOOL_PASS', name, pin['version'])


if __name__ == '__main__':main()
