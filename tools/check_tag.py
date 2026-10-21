# SPDX-License-Identifier: GPL-3.0-or-later
"""Release hold point: exact version, main ancestry and successful merged-main CI."""
import json
import os
from pathlib import Path
import re
import subprocess
import tomllib

ROOT=Path(__file__).resolve().parents[1]
tag=os.environ['GITHUB_REF_NAME']
assert os.environ['GITHUB_REF_TYPE']=='tag' and re.fullmatch(r'v\d+\.\d+\.\d+',tag)
version=tomllib.loads((ROOT/'Cargo.toml').read_text(encoding='utf-8'))['package']['version']
assert tag=='v'+version,'Tag does not match Cargo version'
sha=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()
assert sha==os.environ['GITHUB_SHA']
subprocess.run(['git','merge-base','--is-ancestor',sha,'origin/main'],check=True)
repo=os.environ['GITHUB_REPOSITORY']
runs=json.loads(subprocess.check_output(['gh','api',f'repos/{repo}/actions/runs?head_sha={sha}&status=success&per_page=100'],text=True))['workflow_runs']
assert any(r['path']=='.github/workflows/ci.yml' and r['event']=='push' and r['head_branch']=='main' and r['conclusion']=='success' for r in runs),'Exact merged-main CI must pass before tagging'
assert (ROOT/f'docs/releases/{tag}.md').is_file()
print('FOTO_TAG_GATE_PASS')
