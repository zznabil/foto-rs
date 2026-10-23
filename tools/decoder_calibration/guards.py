# SPDX-License-Identifier: GPL-3.0-or-later
"""Canonical E057 path, timing, and child evidence guards."""

from __future__ import annotations

if not __debug__:
    raise RuntimeError("decoder calibration refuses optimized Python")

from pathlib import Path
import statistics

from . import base_guards as base
from .base_guards import require

INNER = 512
BATCHES = 16
MIB = 1024 * 1024
CONTROL_DEFINITIONS = base.CONTROL_DEFINITIONS


def load_guards():
    """Compatibility shim for the original E057 call sites."""
    return base


def argument_guard(row: dict, case: dict) -> None:
    require(row.get("input") == case["path"], "worker input path changed")
    require(row.get("input_sha256") == case["input_sha256"], "input hash mismatch")
    require(row.get("input_argument_utf16_units") == case["input_argument_utf16_units"],
            "worker UTF-16 argument count changed")
    require(row.get("input_argument_utf16_hex") == case["input_argument_utf16_hex"],
            "worker UTF-16 argument spelling changed")
    require(row.get("argument_utf16_units") == case["input_argument_utf16_units"],
            "probe UTF-16 argument count changed")
    require(row.get("argument_utf16_hex") == case["input_argument_utf16_hex"],
            "probe UTF-16 argument spelling changed")


def delay_guard(row: dict, control: dict) -> None:
    ranges = row.get("batch_ranges_ns")
    times = row.get("times_ns")
    require(isinstance(ranges, list) and len(ranges) == BATCHES, "expected 16 batch ranges")
    require(isinstance(times, list) and len(times) == BATCHES and
            all(type(value) is int and value > 0 for value in times),
            "invalid batch timing")
    require(all(isinstance(pair, list) and len(pair) == 2 for pair in ranges),
            "invalid batch range shape")
    require(all(type(value) is int and value >= 0 for pair in ranges for value in pair),
            "invalid batch range timestamp")
    require(all(current[0] >= previous[1] for previous, current in zip(ranges, ranges[1:])),
            "batch ranges overlap or regress")
    require(all(end - start == duration for duration, (start, end) in zip(times, ranges)),
            "batch range/timing mismatch")
    require(row.get("batch_times_ns") == times, "batch timing rows differ")
    sleep = row.get("observed_sleep_ns")
    require(isinstance(sleep, list) and len(sleep) == 2 and
            all(type(value) is int and value >= 0 for value in sleep),
            "invalid observed sleep interval")
    if control["delay_ms"]:
        require(row.get("delay_event_count") == 1 and row.get("delay_batch_index") == 8,
                "delay event count/index mismatch")
        require(row.get("delay_completed_loads") == INNER * control["repeats"],
                "delay completed load count mismatch")
        require(sleep[1] > sleep[0] and 900_000_000 <= sleep[1] - sleep[0] <= 1_500_000_000,
                "delay sleep interval outside 900..1500ms")
        require(ranges[8][0] <= sleep[0] <= sleep[1] <= ranges[8][1],
                "delay interval not contained in batch 8")
    else:
        require(row.get("delay_event_count") == 0 and row.get("delay_batch_index") == -1 and
                row.get("delay_completed_loads") == 0 and sleep == [0, 0],
                "unexpected delay event in no-delay control")


def common_row_guard(row: dict, case: dict, expected_pixels: str, exe_hash: str,
                     worker_hash: str, control: dict) -> None:
    argument_guard(row, case)
    load_guards().common_row_guard(row, case, expected_pixels, exe_hash, worker_hash, control)
    delay_guard(row, control)


def total_ns(row: dict) -> int:
    return sum(row["times_ns"])


def validate_control(row: dict, control: dict, case: dict, by_name: dict) -> dict:
    guards = load_guards()
    expected = case["pixels_sha256"] if not control["corrupt"] else guards.mutated_digest(Path(case["reference"]))
    if control["name"] == "delay1000once":
        common_row_guard(row, case, expected, by_name["exe_hash"], by_name["worker_hash"], control)
        other = row["times_ns"][:8] + row["times_ns"][9:]
        delta = row["times_ns"][8] - statistics.median(other)
        require(delta >= 750_000_000,
                f"batch-8 minus median(other 15) below 750ms: {delta / 1_000_000}")
        return {"batch_total_ns": total_ns(row), "batch8_minus_median_other15_ns": delta}

    checks = guards.validate_control(row, control, case, by_name)
    argument_guard(row, case)
    delay_guard(row, control)
    if control["name"] == "normal":
        total = total_ns(row)
        require(250_000_000 <= total <= 5_000_000_000,
                f"normal work outside 250..5000ms: {total / 1_000_000}")
        checks["batch_total_ns"] = total
    return checks
