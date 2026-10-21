# SPDX-License-Identifier: GPL-3.0-or-later
"""Scan exact executable bytes without changing Defender policy or quarantine."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess


def check(executable, output):
    executable = executable.resolve(strict=True)
    before = hashlib.sha256(executable.read_bytes()).hexdigest()
    status = json.loads(subprocess.check_output([
        'powershell.exe', '-NoProfile', '-NonInteractive', '-Command',
        '$ErrorActionPreference="Stop"; Get-MpComputerStatus | Select-Object '
        'AMProductVersion,AMEngineVersion,AntivirusSignatureVersion,'
        'AntivirusSignatureLastUpdated,AntivirusEnabled,RealTimeProtectionEnabled | ConvertTo-Json'
    ], text=True, timeout=60))
    platform = Path(os.environ['ProgramData'])/'Microsoft/Windows Defender/Platform'
    candidates = [p/'MpCmdRun.exe' for p in platform.iterdir()
                  if p.is_dir() and p.name[:1].isdigit() and (p/'MpCmdRun.exe').is_file()]
    scanner = max(candidates, key=lambda p: tuple(int(n) for n in p.parent.name.replace('-', '.').split('.')))
    result = subprocess.run([str(scanner), '-Scan', '-ScanType', '3', '-File',
                             str(executable), '-DisableRemediation'],
                            capture_output=True, text=True, errors='replace', timeout=300)
    after = hashlib.sha256(executable.read_bytes()).hexdigest() if executable.is_file() else None
    # Exit zero alone can mean successful remediation. Require the explicit clean result too.
    passed = (result.returncode == 0 and 'found no threats.' in result.stdout
              and before == after and status['AntivirusEnabled']
              and status['RealTimeProtectionEnabled'])
    report = {'verdict': 'PASS' if passed else 'FAIL', 'exe_sha256': before,
              'post_scan_sha256': after, 'scanner': str(scanner), 'status': status,
              'exit_code': result.returncode, 'stdout': result.stdout, 'stderr': result.stderr}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    if not passed:
        raise RuntimeError('Defender scan did not establish a clean result; see '+str(output))
    print('FOTO_DEFENDER_SCAN_PASS')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('executable', type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    check(args.executable, args.output)
