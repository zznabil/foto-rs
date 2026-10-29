# SPDX-License-Identifier: GPL-3.0-or-later
"""Serial decoder sampling with raw counters and resource monitoring."""
if not __debug__:
    raise RuntimeError("decoder calibration refuses optimized Python")
import json
import os
from pathlib import Path
import threading
import traceback
from . import worker as w
from . import native
from .protocol import parse_probe_timing


def sample(exe, image, output, inner, repeats=1, delay=0, extra=0, corrupt=False):
    assert inner in [1, 8, 64, 512, 4096] and repeats in [1, 3]
    assert delay in [0, 1000] and extra in [0, 32 * 1024**2]
    settings = {'FOTO_E057_INNER': str(inner), 'FOTO_E057_REPEATS': str(repeats),
                'FOTO_E057_DELAY_MS': str(delay), 'FOTO_E057_EXTRA_BYTES': str(extra),
                'FOTO_E057_CORRUPT': '1' if corrupt else None}
    previous = {key: os.environ.get(key) for key in settings}
    original_resources = w.t.resources
    original_cpu = w.t.s.cpu_ms
    original_popen = w.subprocess.Popen
    stopped = threading.Event()
    observed = []
    errors = []
    monitors = []

    def capture(process):
        return {**original_resources(process), **native.snapshot(process._handle)}

    def monitored_popen(*args, **kwargs):
        process = original_popen(*args, **kwargs)

        def monitor():
            while not stopped.is_set():
                try:
                    observed.append(capture(process))
                except Exception as error:
                    errors.append(error)
                    break
                stopped.wait(0.002)

        thread = threading.Thread(target=monitor, daemon=True)
        monitors.append(thread)
        thread.start()
        return process

    def resources(process):
        stopped.set()
        for thread in monitors:
            thread.join(2)
            assert not thread.is_alive(), 'Resource monitor failed to stop'
        if errors:
            raise errors[0]
        final = capture(process)
        observed.append(final)
        assert observed
        (output / 'resource-observations.json').write_text(json.dumps(observed) + '\n', encoding='utf-8')
        return {**final, **{'sampled_max_' + key: max(row[key] for row in observed)
                            for key in ['rss', 'private', 'handles', 'gdi', 'user']}}

    def cpu_ms(process):
        first, second = native.raw_cpu(process), native.raw_cpu(process)
        (output / 'raw-cpu.json').write_text(json.dumps([first, second], indent=2) + '\n', encoding='utf-8')
        assert all(row['times_ok'] and row['cycles_ok'] for row in [first, second])
        assert first['creation_100ns'] == second['creation_100ns'] > 0
        assert second['kernel_100ns'] >= first['kernel_100ns'] >= 0
        assert second['user_100ns'] >= first['user_100ns'] >= 0
        assert second['cycles'] >= first['cycles'] > 0 and second['cpu_ms'] >= first['cpu_ms'] > 0
        return first['cpu_ms']

    primary_error = None
    try:
        for key, value in settings.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        w.t.resources = resources
        w.t.s.cpu_ms = cpu_ms
        w.subprocess.Popen = monitored_popen
        row = w.sample(exe, image, output)
        (ranges, times, sleep, count, delay_events, delay_batch,
         delay_completed, argument_count, argument_hex) = parse_probe_timing(
            row['stderr'], inner, repeats, delay, row['decode_ms']
        )
        assert row['exit_code'] == 0 and row['verdict'] == 'MEASUREMENT_PASS' and row['decode_ms'] > 0
        assert argument_count == row['input_argument_utf16_units'], 'child argument length differs from worker text'
        assert argument_hex == row['input_argument_utf16_hex'], 'child argument differs from worker text'
        assert row['resources_before_transport']['peak_commit'] < 1024**3
        assert row['resources_before_transport']['peak_rss'] < 1024**3
        raw = json.loads((output / 'raw-cpu.json').read_text())
        row.update(loop_count=count, times_ns=times, batch_times_ns=times,
                   batch_ranges_ns=ranges, observed_sleep_ns=sleep,
                   delay_event_count=delay_events, delay_batch_index=delay_batch,
                   delay_completed_loads=delay_completed, raw_cpu=raw,
                   argument_utf16_units=argument_count, argument_utf16_hex=argument_hex,
                   user_cpu_ms=raw[0]['user_100ns'] / 10000,
                   kernel_cpu_ms=raw[0]['kernel_100ns'] / 10000,
                   observed_resource_samples=len(observed))
        (output / 'extended-report.json').write_text(json.dumps(row, indent=2) + '\n', encoding='utf-8')
        return row
    except BaseException as error:
        primary_error = error
        raise
    finally:
        stopped.set()
        cleanup_errors = []
        for thread in monitors:
            thread.join(2)
            if thread.is_alive():
                cleanup_errors.append('Resource monitor still alive after stop/join')
        w.t.resources = original_resources
        w.t.s.cpu_ms = original_cpu
        w.subprocess.Popen = original_popen
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        if output.exists():
            try:
                (output / 'monitor-cleanup.json').write_text(json.dumps({
                    'cleanup_errors': cleanup_errors,
                    'sample_errors': [repr(error) for error in errors],
                    'sample_error_tracebacks': [traceback.format_exception(error) for error in errors],
                    'samples': len(observed), 'all_monitors_terminal': not cleanup_errors}) + '\n', encoding='utf-8')
            except BaseException as error:
                cleanup_errors.append('monitor cleanup report write failed: ' + repr(error))
        if cleanup_errors:
            if primary_error is not None:
                primary_error.add_note('E057 monitor cleanup errors: ' + repr(cleanup_errors))
            else:
                raise RuntimeError('E057 monitor cleanup errors: ' + repr(cleanup_errors))
