# SPDX-License-Identifier: GPL-3.0-or-later
"""Validate inventories against a hash-pinned official SPDX 2.3 JSON schema."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import time
import urllib.request
from jsonschema import Draft7Validator

ROOT = Path(__file__).resolve().parents[1]


def validator():
    pin = json.loads((ROOT/'tools/spdx-schema-pin.json').read_text(encoding='utf-8'))
    cache = ROOT/'artifacts/schema'/pin['sha256']
    if cache.is_file():
        data = cache.read_bytes()
    else:
        for attempt in range(3):
            try:
                with urllib.request.urlopen(pin['url'], timeout=30) as response:
                    data = response.read(2_000_001)
                break
            except OSError:
                if attempt == 2:
                    raise
                time.sleep(2)
        if len(data) > 2_000_000:
            raise ValueError('Unexpected SPDX schema size')
    if hashlib.sha256(data).hexdigest() != pin['sha256']:
        raise ValueError('SPDX schema hash mismatch')
    schema = json.loads(data)
    Draft7Validator.check_schema(schema)
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_bytes(data)
    return Draft7Validator(schema)


def check(document):
    errors = list(validator().iter_errors(document))
    if errors:
        messages = ['/'.join(map(str, e.absolute_path))+': '+e.message for e in errors[:10]]
        raise ValueError('SPDX schema validation failed: '+'; '.join(messages))
    print('FOTO_SPDX_SCHEMA_PASS')


def self_test():
    valid = {'spdxVersion':'SPDX-2.3', 'dataLicense':'CC0-1.0',
             'SPDXID':'SPDXRef-DOCUMENT', 'name':'Schema control',
             'documentNamespace':'https://example.org/spdx/control',
             'creationInfo':{'created':'2026-10-21T00:00:00Z','creators':['Tool: Foto schema control']}}
    check(valid)
    broken = copy.deepcopy(valid)
    broken['documentComment'] = 'Invalid root field'
    try:
        check(broken)
    except ValueError as error:
        if 'documentComment' not in str(error):
            raise
    else:
        raise AssertionError('SPDX control accepted an invalid root field')
    print('FOTO_SPDX_CONTROLS_PASS')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('inventory', type=Path, nargs='?')
    parser.add_argument('--self-test', action='store_true')
    args = parser.parse_args()
    if args.self_test:
        self_test()
    else:
        if args.inventory is None:
            parser.error('inventory is required unless --self-test is used')
        check(json.loads(args.inventory.read_text(encoding='utf-8')))
