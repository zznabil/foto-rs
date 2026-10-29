# SPDX-License-Identifier: GPL-3.0-or-later
"""Canonical E056 control guards, relocated without the historical runner."""

from __future__ import annotations

if not __debug__:
    raise RuntimeError("decoder calibration refuses optimized Python")

import hashlib
from pathlib import Path
import statistics

INNER = 512
BATCHES = 16
MIB = 1024 * 1024

CONTROL_DEFINITIONS = (
    {"name": "normal", "repeats": 1, "delay_ms": 0, "extra_bytes": 0, "corrupt": False},
    {"name": "delay1000once", "repeats": 1, "delay_ms": 1000, "extra_bytes": 0, "corrupt": False},
    {"name": "triple", "repeats": 3, "delay_ms": 0, "extra_bytes": 0, "corrupt": False},
    {"name": "extra32MiB", "repeats": 1, "delay_ms": 0, "extra_bytes": 33_554_432, "corrupt": False},
    {"name": "onebyte", "repeats": 1, "delay_ms": 0, "extra_bytes": 0, "corrupt": True},
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def mutated_digest(reference: Path) -> str:
    data = bytearray(reference.read_bytes())
    require(data, f"reference payload is empty: {reference}")
    data[0] ^= 1
    return hashlib.sha256(data).hexdigest()


def raw_cpu_guard(row: dict) -> None:
    raw = row.get("raw_cpu")
    require(isinstance(raw, list) and len(raw) == 2, "raw CPU must contain two samples")
    first, second = raw
    for sample in raw:
        require(sample.get("times_ok") is True, "GetProcessTimes failed")
        require(sample.get("cycles_ok") is True, "QueryProcessCycleTime failed")
        require(sample.get("creation_100ns", 0) > 0, "missing process creation timestamp")
        require(sample.get("cycles", 0) > 0, "non-positive process cycle count")
        require(sample.get("kernel_100ns", -1) >= 0, "invalid kernel process time")
        require(sample.get("user_100ns", -1) >= 0, "invalid user process time")
        require(sample.get("cpu_ms", 0) > 0, "non-positive process CPU time")
        require(sample["cpu_ms"] == (sample["kernel_100ns"] + sample["user_100ns"]) / 10000,
                "CPU time differs from raw process ticks")
    require(first["creation_100ns"] == second["creation_100ns"], "process identity changed")
    require(first["kernel_100ns"] <= second["kernel_100ns"], "kernel process time regressed")
    require(first["user_100ns"] <= second["user_100ns"], "user process time regressed")
    require(first["cycles"] <= second["cycles"], "process cycles regressed")


def common_row_guard(row: dict, case: dict, expected_pixels: str, exe_hash: str,
                     worker_hash: str, control: dict) -> None:
    require(row.get("exe_sha256") == exe_hash, "control executable hash changed")
    require(row.get("harness_sha256") == worker_hash, "worker helper hash changed")
    require(Path(row.get("input", "")).resolve() == Path(case["path"]).resolve(),
            "worker input path changed")
    require(row.get("input_sha256") == case["input_sha256"], "input hash mismatch")
    require(row.get("pixel_sha256") == expected_pixels, "complete payload hash mismatch")
    require(row.get("verdict") == "MEASUREMENT_PASS", "worker did not report measurement pass")
    require(row.get("exit_code") == 0, "control child did not exit normally")
    require(row.get("received_bytes") == row.get("bytes"), "payload was incomplete")
    require(row.get("bytes", 0) > 0, "empty decoded payload")
    require([row.get(field) for field in ("width", "height", "original", "bytes")] == case["decoded_metadata"],
            "decoded metadata differs from original full-output reference")
    require(row.get("decode_ms", 0) > 0, "non-positive reported decode duration")

    times = row.get("times_ns")
    require(isinstance(times, list) and len(times) == BATCHES, "expected 16 batch timings")
    require(all(isinstance(value, int) and value > 0 for value in times), "invalid batch timing")
    require(row.get("loop_count") == BATCHES * INNER * control["repeats"], "loop count mismatch")
    require(abs(row["decode_ms"] * 1_000_000 * row["loop_count"] - sum(times)) <= row["loop_count"] + 1,
            "header mean differs from batch durations beyond integer rounding")

    resources = row.get("resources_before_transport")
    require(isinstance(resources, dict), "missing resource snapshot")
    for field in ("rss", "private", "peak_rss", "peak_commit", "handles", "gdi", "user",
                  "sampled_max_rss", "sampled_max_private", "sampled_max_handles", "sampled_max_gdi", "sampled_max_user"):
        short = field.removeprefix("sampled_max_")
        require(isinstance(resources.get(field), int) and
                (resources[field] >= 0 if short in ("gdi", "user") else resources[field] > 0),
                f"invalid resource field: {field}")
    require(resources["peak_commit"] < 1024**3, "peak commit exceeds existing guard")
    require(resources["peak_rss"] < 1024**3, "peak RSS exceeds existing guard")
    raw_cpu_guard(row)
    require(row["cpu_ms_before_transport"] == row["raw_cpu"][0]["cpu_ms"], "CPU scalar differs from raw ticks")


def total_ms(row: dict) -> float:
    return sum(row["times_ns"]) / 1_000_000


def validate_control(row: dict, control: dict, case: dict, by_name: dict) -> dict:
    expected = case["pixels_sha256"] if not control["corrupt"] else mutated_digest(Path(case["reference"]))
    common_row_guard(row, case, expected, by_name["exe_hash"], by_name["worker_hash"], control)
    if control["name"] != "normal":
        normal = by_name["normal"]
        for field in ("width", "height", "original", "bytes"):
            require(row.get(field) == normal.get(field), f"{control['name']} shape differs from normal: {field}")
    total = total_ms(row)
    checks = {"batch_total_ms": total}
    if control["name"] == "normal":
        require(50 <= total <= 5000, f"normal work outside 50..5000ms: {total}")
    elif control["name"] == "triple":
        normal = by_name["normal"]
        normal_total = total_ms(normal)
        wall_total_ratio = total / normal_total
        median_ratio = statistics.median(row["times_ns"]) / statistics.median(normal["times_ns"])
        cpu_ratio = row["cpu_ms_before_transport"] / normal["cpu_ms_before_transport"]
        require(wall_total_ratio >= 1.5, f"triple total wall ratio below 1.5: {wall_total_ratio}")
        require(median_ratio >= 1.5, f"triple median-batch ratio below 1.5: {median_ratio}")
        require(cpu_ratio >= 1.5, f"triple CPU ratio below 1.5: {cpu_ratio}")
        checks.update(wall_total_ratio=wall_total_ratio, median_batch_ratio=median_ratio, cpu_ratio=cpu_ratio)
    elif control["name"] == "delay1000once":
        delta = total - total_ms(by_name["normal"])
        require(delta >= 750, f"one-time delay delta below 750ms: {delta}")
        checks["total_delta_ms"] = delta
    elif control["name"] == "extra32MiB":
        normal_resources = by_name["normal"]["resources_before_transport"]
        resources = row["resources_before_transport"]
        deltas = {
            field: resources[field] - normal_resources[field]
            for field in ("peak_commit", "private", "peak_rss")
        }
        require(all(value >= 24 * MIB for value in deltas.values()),
                f"extra-memory resource deltas below 24MiB: {deltas}")
        checks["resource_deltas"] = deltas
    elif control["name"] == "onebyte":
        require(row["pixel_sha256"] == expected, "one-byte payload is not the exact reference mutation")
        checks["expected_mutated_pixel_sha256"] = expected
    return checks
