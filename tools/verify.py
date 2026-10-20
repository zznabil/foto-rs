# SPDX-License-Identifier: GPL-3.0-or-later
"""Observe every Windows release gate and retain success-only, source-bound evidence."""
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import time
import tomllib

ROOT = Path(__file__).resolve().parents[1]


def main():
    assert sys.platform == 'win32', 'Native Windows desktop tests require Windows'
    output = ROOT/'artifacts/ci'
    assert not output.exists(), 'Use a fresh checkout, or archive artifacts/ci before a new run'
    (output/'reports').mkdir(parents=True)
    (output/'logs').mkdir()
    sha = subprocess.check_output(['git','rev-parse','HEAD'], cwd=ROOT, text=True).strip()
    dirty = bool(subprocess.check_output(['git','status','--porcelain','--untracked-files=no'], cwd=ROOT, text=True).strip())
    report = {'verdict':'IN_PROGRESS','source_commit':sha,'tracked_tree_dirty':dirty,
              'host':platform.platform(),'python':platform.python_version(),
              'rustc':subprocess.check_output(['rustc','--version'],text=True).strip(),
              'runner_image':os.environ.get('ImageVersion'),
              'workflow_ref':os.environ.get('GITHUB_WORKFLOW_REF'),
              'run_url':('https://github.com/'+os.environ['GITHUB_REPOSITORY']+'/actions/runs/'+os.environ['GITHUB_RUN_ID']) if os.environ.get('GITHUB_RUN_ID') else None,
              'gates':[]}
    def save():
        (output/'reports/checks.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    def run(label, command, marker=None):
        started = time.monotonic()
        print('GATE_START',label,flush=True)
        result = subprocess.run(command,cwd=ROOT,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=1800)
        (output/f'logs/{label}.txt').write_text(result.stdout+'\n'+result.stderr,encoding='utf-8')
        passed = result.returncode == 0 and (marker is None or marker in result.stdout.splitlines())
        report['gates'].append({'id':label,'exit_code':result.returncode,'verdict':'PASS' if passed else 'FAIL',
                                'seconds':round(time.monotonic()-started,2),'marker':marker})
        save()
        if not passed:
            print(result.stdout,result.stderr)
            raise RuntimeError(f'{label} failed; see artifacts/ci/logs/{label}.txt')
        print('GATE_PASS',label,flush=True)
        return result.stdout
    try:
        run('format',['cargo','fmt','--all','--','--check'])
        run('clippy',['cargo','clippy','--locked','--all-targets','--','-D','warnings'])
        unit=run('unit',['cargo','test','--locked'])
        assert any(int(count)>=15 for count in re.findall(r'test result: ok\. (\d+) passed; 0 failed',unit)), 'Expected the complete Rust unit suite'
        run('release-build',['cargo','build','--locked','--release'])
        run('uia-build',['cargo','build','--locked','--release','--example','uia_probe'])
        run('fixtures',[sys.executable,'tools/generate_fixtures.py','--bench-only'])
        exe = ROOT/'target/release/foto.exe'
        run('portable',[sys.executable,'tools/check_portable.py',str(exe)],'PORTABLE_DEPENDENCIES_PASS')
        version=tomllib.loads((ROOT/'Cargo.toml').read_text(encoding='utf-8'))['package']['version']
        run('version-info',[sys.executable,'tools/check_version.py',str(exe),'--version',version],'VERSION_METADATA_PASS')
        run('smoke',[sys.executable,'tools/smoke_test.py','--exe',str(exe),'--runs','10'],'FOTO_SMOKE_PASS')
        shutil.copyfile(ROOT/'artifacts/verification.json',output/'reports/smoke.json')
        stress = run('stress',[sys.executable,'tools/stress_test.py','--exe',str(exe)],'FOTO_STRESS_PASS')
        malformed = run('malformed',[sys.executable,'tools/malformed_test.py','--exe',str(exe),'--samples','200'],'FOTO_MALFORMED_PASS')
        for label, text in [('stress',stress),('malformed',malformed)]:
            paths = [Path(line[7:]) for line in text.splitlines() if line.startswith('REPORT ')]
            assert len(paths) == 1
            shutil.copyfile(paths[0],output/f'reports/{label}.json')
        run('source-integrity',['git','diff','--exit-code'])
        report.update(verdict='PASS',exe_sha256=hashlib.sha256(exe.read_bytes()).hexdigest())
        shutil.copyfile(exe,output/'foto.exe')
        save()
        print('FOTO_WINDOWS_VERIFICATION_PASS')
    except BaseException:
        report['verdict']='FAIL'
        save()
        raise


if __name__ == '__main__':main()
