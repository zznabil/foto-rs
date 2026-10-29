# SPDX-License-Identifier: GPL-3.0-or-later
"""Canonical Win32 CPU and lifetime-peak readers for decoder calibration."""

from __future__ import annotations

if not __debug__:
    raise RuntimeError("decoder calibration refuses optimized Python")

import ctypes as C
from ctypes import wintypes as W
import hashlib
import json
import os
from pathlib import Path
import platform
import sys
import time

if __name__ == '__main__':
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import stress_test as t

s = t.s
cycle = s.api(s.kernel, 'QueryProcessCycleTime', W.BOOL, W.HANDLE, C.POINTER(C.c_ulonglong))


def ticks(v):
    return (v.dwHighDateTime << 32) + v.dwLowDateTime


def raw_cpu(p):
    created, exited, kernel, user = (W.FILETIME() for _ in range(4))
    value = C.c_ulonglong()
    C.set_last_error(0)
    ok = bool(s.process_times(p._handle, C.byref(created), C.byref(exited), C.byref(kernel), C.byref(user)))
    error = C.get_last_error() if not ok else None
    C.set_last_error(0)
    cyc = bool(cycle(p._handle, C.byref(value)))
    cyc_error = C.get_last_error() if not cyc else None
    return {'pid': p.pid, 'times_ok': ok, 'times_error': error, 'cycles_ok': cyc,
            'cycles_error': cyc_error, 'cycles': value.value, 'creation_100ns': ticks(created),
            'kernel_100ns': ticks(kernel), 'user_100ns': ticks(user),
            'cpu_ms': (ticks(kernel) + ticks(user)) / 10000,
            'observed_ns': time.perf_counter_ns()}


def snapshot(handle):
    memory = t.MemoryInfo(t.C.sizeof(t.MemoryInfo))
    assert t.get_memory(handle, t.C.byref(memory), t.C.sizeof(memory))
    assert memory.peak_ws >= memory.ws and memory.peak_pagefile >= memory.pagefile
    return {'rss': memory.ws, 'private': memory.private, 'commit': memory.pagefile,
            'peak_rss': memory.peak_ws, 'peak_commit': memory.peak_pagefile}


def calibrate_peaks(output):
    """Run the original reserve/commit/touch/free counter calibration once."""
    output = Path(output)
    metadata = {'source_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                'helper_sha256': {name: hashlib.sha256((Path(t.__file__).resolve().parent / name).read_bytes()).hexdigest()
                                 for name in ('stress_test.py', 'smoke_test.py')},
                'api': 'K32GetProcessMemoryInfo/PROCESS_MEMORY_COUNTERS_EX',
                'pointer_bytes': t.C.sizeof(t.C.c_void_p), 'counter_bytes': t.C.sizeof(t.MemoryInfo),
                'pagefile_offset': t.MemoryInfo.pagefile.offset,
                'peak_pagefile_offset': t.MemoryInfo.peak_pagefile.offset,
                'private_offset': t.MemoryInfo.private.offset}
    metadata.update(pid=os.getpid(), host=platform.platform(), python=sys.version,
                    definitions='https://learn.microsoft.com/en-us/windows/win32/api/psapi/ns-psapi-process_memory_counters_ex',
                    limits='Windows x64; kernel lifetime peaks for the whole process. Priming can mask later smaller peaks.')
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({**metadata, 'status': 'PEAK_CALIBRATION_STARTED', 'records': {}}) + '\n', encoding='utf-8')
    current = s.api(s.kernel, 'GetCurrentProcess', W.HANDLE)()
    allocate = s.api(s.kernel, 'VirtualAlloc', t.C.c_void_p,
                     t.C.c_void_p, t.C.c_size_t, W.DWORD, W.DWORD)
    release = s.api(s.kernel, 'VirtualFree', W.BOOL,
                    t.C.c_void_p, t.C.c_size_t, W.DWORD)
    size = 96 * 1024**2
    records = {}
    address = None
    primary = None
    cleanup_only = False
    phase = 'layout-and-initial-snapshot'
    try:
        assert t.C.sizeof(t.C.c_void_p) == 8 and t.C.sizeof(t.MemoryInfo) == 80
        assert t.MemoryInfo.pagefile.offset == 56 and t.MemoryInfo.peak_pagefile.offset == 64
        assert t.MemoryInfo.private.offset == 72
        records['before'] = snapshot(current)
        phase = 'reserve'
        address = allocate(None, size, 0x2000, 0x04)
        assert address
        records['reserved'] = snapshot(current)
        assert abs(records['reserved']['private'] - records['before']['private']) < 8 * 1024**2
        phase = 'commit-without-touch'
        assert allocate(address, size, 0x1000, 0x04) == address
        records['committed_untouched'] = snapshot(current)
        assert records['committed_untouched']['private'] - records['reserved']['private'] >= .99 * size
        assert records['committed_untouched']['peak_commit'] - records['before']['peak_commit'] >= .95 * size
        assert records['committed_untouched']['rss'] - records['reserved']['rss'] < 8 * 1024**2
        phase = 'touch'
        t.C.memset(address, 0x5a, size)
        records['touched'] = snapshot(current)
        assert records['touched']['peak_rss'] - records['before']['peak_rss'] >= .9 * size
        phase = 'free-and-check-persistent-peak'
        assert release(address, 0, 0x8000)
        address = None
        records['freed'] = snapshot(current)
        assert abs(records['freed']['private'] - records['before']['private']) < 8 * 1024**2
        assert records['freed']['peak_commit'] >= records['touched']['peak_commit']
        assert records['freed']['peak_commit'] - records['before']['peak_commit'] >= .95 * size
        # A current-private-as-peak reader loses the released allocation and fails.
        assert records['freed']['private'] - records['before']['peak_commit'] < .1 * size
        assert all(r['private'] == r['commit'] for r in records.values())
    except BaseException as error:
        primary = error
        raise
    finally:
        if address:
            try:
                assert release(address, 0, 0x8000)
            except BaseException as error:
                if primary is None:
                    primary = error
                    cleanup_only = True
                else:
                    primary.add_note('peak calibration release: ' + repr(error))
        if primary is not None:
            failure = {**metadata, 'status': 'PEAK_CALIBRATION_FAILURE_PRESERVED', 'records': records,
                       'allocation_bytes': size, 'failure': repr(primary),
                       'phase': phase, 'allocation_address': address,
                       'notes': getattr(primary, '__notes__', [])}
            try:
                output.write_text(json.dumps(failure, indent=2) + '\n', encoding='utf-8')
            except BaseException as error:
                primary.add_note('peak calibration failure record: ' + repr(error))
            if cleanup_only:
                raise primary
    report = {**metadata, 'status': 'PEAK_COMMIT_RSS_READER_CALIBRATION_PASS', 'allocation_bytes': size,
              'records': records,
              'controls': 'Reservewithoutcommit doesnotraiseprivate;commitwithouttouch raisesprivatebutnotRSS;touch raisesRSS;free reducesprivatewhilekernelpeak persists. Broken current-private-as-peak derivation is rejected.',
              'phase': 'complete', 'allocation_address': address}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    return report


if __name__ == '__main__':
    if len(sys.argv) != 2:
        raise ValueError('expected one peak-calibration report path')
    assert Path(t.__file__).resolve() == Path(__file__).resolve().parents[1] / 'stress_test.py'
    calibrate_peaks(sys.argv[1])
    print('PEAK_COMMIT_RSS_READER_POSITIVE_AND_BROKEN_CONTROLS_PASS', flush=True)
