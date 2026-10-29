# SPDX-License-Identifier: GPL-3.0-or-later
"""Portable, pure-contract checks for the decoder calibration package.

These tests intentionally exercise only protocol and guard dictionaries.  They
do not import native counters, launch a child, read repository fixtures, or
make a performance observation.
"""

import copy
import hashlib
from pathlib import Path
import tempfile
import unittest

from decoder_calibration import base_guards, guards, protocol


INNER = 512
BATCHES = 16
PIXEL_BYTES = 64 * 48 * 4
EXE_HASH = "exe-hash"
WORKER_HASH = "worker-hash"
MIB = 1024 * 1024

CONTROLS = (
    {"name": "normal", "repeats": 1, "delay_ms": 0, "extra_bytes": 0, "corrupt": False},
    {"name": "delay1000once", "repeats": 1, "delay_ms": 1000, "extra_bytes": 0, "corrupt": False},
    {"name": "triple", "repeats": 3, "delay_ms": 0, "extra_bytes": 0, "corrupt": False},
    {"name": "extra32MiB", "repeats": 1, "delay_ms": 0, "extra_bytes": 32 * MIB, "corrupt": False},
    {"name": "onebyte", "repeats": 1, "delay_ms": 0, "extra_bytes": 0, "corrupt": True},
)


def _write_case(root: Path, index: int) -> dict:
    input_path = root / f"case-{index}-input.bin"
    reference_path = root / f"case-{index}-reference.bin"
    input_bytes = f"synthetic-input-{index}".encode("ascii")
    reference_bytes = bytes((index * 17 + offset * 37 + 11) % 256 for offset in range(PIXEL_BYTES))
    input_path.write_bytes(input_bytes)
    reference_path.write_bytes(reference_bytes)
    raw_path = str(input_path)
    raw_utf16 = raw_path.encode("utf-16le", errors="surrogatepass")
    return {
        "id": f"case-{index}",
        "path": raw_path,
        "reference": str(reference_path),
        "input_sha256": hashlib.sha256(input_bytes).hexdigest(),
        "pixels_sha256": hashlib.sha256(reference_bytes).hexdigest(),
        "decoded_metadata": [64, 48, [64, 48], PIXEL_BYTES],
        "raw_utf16_units": [
            int.from_bytes(raw_utf16[offset : offset + 2], "little")
            for offset in range(0, len(raw_utf16), 2)
        ],
        "input_argument_utf16_units": len(raw_utf16) // 2,
        "input_argument_utf16_hex": raw_utf16.hex(),
    }


def _raw_cpu(cpu_ms: float, cycles: int = 2_000) -> list[dict]:
    ticks = int(round(cpu_ms * 10_000))
    first = {
        "times_ok": True,
        "cycles_ok": True,
        "creation_100ns": 111,
        "kernel_100ns": ticks // 2,
        "user_100ns": ticks - ticks // 2,
        "cycles": cycles,
        "cpu_ms": cpu_ms,
    }
    second = dict(first)
    second.update(
        creation_100ns=111,
        kernel_100ns=first["kernel_100ns"] + ticks // 2,
        user_100ns=first["user_100ns"] + ticks - ticks // 2,
        cycles=cycles + 1,
        cpu_ms=cpu_ms * 2,
    )
    return [first, second]


def _ranges(times: list[int]) -> list[list[int]]:
    current = 0
    result = []
    for duration in times:
        result.append([current, current + duration])
        current += duration
    return result


def _row(case: dict, control: dict, *, batch_ns: int = 20_000_000,
         cpu_ms: float = 2.0, resource_delta: int = 0) -> dict:
    times = [batch_ns] * BATCHES
    if control["name"] == "delay1000once":
        times[8] = batch_ns + 750_000_000
    ranges = _ranges(times)
    reference = Path(case["reference"]).read_bytes()
    expected_pixels = bytearray(reference)
    if control["corrupt"]:
        expected_pixels[0] ^= 1
    resources = {
        "rss": 70_000_000 + resource_delta,
        "private": 80_000_000 + resource_delta,
        "peak_rss": 90_000_000 + resource_delta,
        "peak_commit": 100_000_000 + resource_delta,
        "handles": 10,
        "gdi": 2,
        "user": 3,
    }
    resources.update({f"sampled_max_{key}": value for key, value in resources.items()})
    loop_count = BATCHES * INNER * control["repeats"]
    decode_ms = sum(times) / (1_000_000 * loop_count)
    raw_cpu = _raw_cpu(cpu_ms)
    return {
        "exe_sha256": EXE_HASH,
        "harness_sha256": WORKER_HASH,
        "input": case["path"],
        "input_sha256": case["input_sha256"],
        "input_argument_utf16_units": case["input_argument_utf16_units"],
        "input_argument_utf16_hex": case["input_argument_utf16_hex"],
        "argument_utf16_units": case["input_argument_utf16_units"],
        "argument_utf16_hex": case["input_argument_utf16_hex"],
        "width": 64,
        "height": 48,
        "original": [64, 48],
        "bytes": PIXEL_BYTES,
        "decode_ms": decode_ms,
        "pixel_sha256": hashlib.sha256(expected_pixels).hexdigest(),
        "received_bytes": PIXEL_BYTES,
        "exit_code": 0,
        "verdict": "MEASUREMENT_PASS",
        "loop_count": loop_count,
        "times_ns": times,
        "batch_times_ns": times,
        "batch_ranges_ns": ranges,
        "observed_sleep_ns": (
            [ranges[8][0] + 50_000_000, ranges[8][0] + 950_000_000]
            if control["name"] == "delay1000once" else [0, 0]
        ),
        "delay_event_count": 1 if control["name"] == "delay1000once" else 0,
        "delay_batch_index": 8 if control["name"] == "delay1000once" else -1,
        "delay_completed_loads": INNER * control["repeats"] if control["name"] == "delay1000once" else 0,
        "raw_cpu": raw_cpu,
        "cpu_ms_before_transport": raw_cpu[0]["cpu_ms"],
        "resources_before_transport": resources,
    }


def _by_name(normal: dict) -> dict:
    return {"exe_hash": EXE_HASH, "worker_hash": WORKER_HASH, "normal": normal}


class DecoderCalibrationProtocolTests(unittest.TestCase):
    def test_header_accepts_complete_metadata_and_rejects_malformed_headers(self):
        good = protocol.header(b"DECODE 64 48 64 48 12288 1000000\n")
        self.assertEqual(good, {
            "width": 64,
            "height": 48,
            "original": [64, 48],
            "bytes": PIXEL_BYTES,
            "decode_ms": 1.0,
        })
        malformed = (
            b"DECODE 64 48 64 48 12288 1000000",
            b"DECODE 64 48 64 48 12288 1000000 extra\n",
            b"DECODE 0 48 64 48 12288 1000000\n",
            b"DECODE 8193 48 8193 48 12288 1000000\n",
            b"DECODE 64 48 63 48 12288 1000000\n",
            b"DECODE 64 48 64 48 12287 1000000\n",
            b"DECODE 64 48 64 48 12288 -1\n",
        )
        for value in malformed:
            with self.subTest(value=value):
                with self.assertRaises((AssertionError, ValueError)):
                    protocol.header(value)

    def test_timing_parser_accepts_normal_and_delay_and_rejects_protocol_shapes(self):
        argument_hex = "4100" * 12

        def stderr(times, *, count=8192, event=0, batch=-1, completed=0,
                   sleep=(0, 0), argument_count=12, argument=argument_hex):
            ranges = _ranges(times)
            return "\n".join((
                f"BATCH_RANGES_NS {ranges!r}",
                f"BATCH_TIMES_NS {times!r}",
                f"OBSERVED_SLEEP_NS {list(sleep)!r}",
                f"LOOP_COUNT {count}",
                f"DELAY_EVENT_COUNT {event}",
                f"DELAY_BATCH_INDEX {batch}",
                f"DELAY_COMPLETED_LOADS {completed}",
                f"ARGUMENT_UTF16_COUNT {argument_count}",
                f"ARGUMENT_UTF16_HEX {argument}",
            ))

        normal = [20_000_000] * BATCHES
        parsed = protocol.parse_probe_timing(stderr(normal), INNER, 1, 0, 0.0390625)
        self.assertEqual(parsed[3], INNER * BATCHES)
        self.assertEqual(parsed[5:7], (-1, 0))

        delay = [250_000_000] * BATCHES
        delay[8] = 1_000_000_000
        delay_ranges = _ranges(delay)
        parsed = protocol.parse_probe_timing(
            stderr(delay, event=1, batch=8, completed=INNER,
                   sleep=(delay_ranges[8][0] + 50_000_000,
                          delay_ranges[8][0] + 950_000_000)),
            INNER, 1, 1000, sum(delay) / (1_000_000 * INNER * BATCHES),
        )
        self.assertEqual(parsed[4:7], (1, 8, INNER))

        invalid = (
            stderr(normal[:-1]),
            stderr(normal, count=8191),
            stderr(normal, argument_count=13),
            stderr(normal, argument="zz00"),
            stderr(normal, event=1, batch=7, completed=INNER,
                   sleep=(1_000_000_000, 2_000_000_000)),
        )
        for value in invalid:
            with self.subTest(value=value):
                with self.assertRaises((AssertionError, ValueError)):
                    protocol.parse_probe_timing(value, INNER, 1, 0, 0.0390625)

    def test_all_five_modes_pass_pure_guard_contract(self):
        with tempfile.TemporaryDirectory(prefix="decoder-calibration-unit-") as directory:
            for index in (1, 2, 3):
                case = _write_case(Path(directory), index)
                normal = _row(case, CONTROLS[0])
                by_name = _by_name(normal)
                for control in CONTROLS:
                    with self.subTest(case=index, mode=control["name"]):
                        resource_delta = 24 * MIB if control["name"] == "extra32MiB" else 0
                        cpu_ms = 3.0 if control["name"] == "triple" else 2.0
                        batch_ns = (30_000_000 if control["name"] == "triple" else
                                    250_000_000 if control["name"] == "delay1000once" else
                                    20_000_000)
                        row = _row(case, control, batch_ns=batch_ns, cpu_ms=cpu_ms,
                                   resource_delta=resource_delta)
                        result = guards.validate_control(row, control, case, by_name)
                        self.assertIsInstance(result, dict)

    def test_exact_work_delay_triple_and_memory_boundaries(self):
        with tempfile.TemporaryDirectory(prefix="decoder-calibration-boundary-") as directory:
            case = _write_case(Path(directory), 2)
            normal_control = CONTROLS[0]
            normal = _row(case, normal_control)
            by_name = _by_name(normal)

            for total_ns, expected in ((250_000_000, True), (5_000_000_000, True),
                                       (249_999_999, False), (5_000_000_001, False)):
                control = dict(normal_control)
                row = _row(case, control, batch_ns=total_ns // BATCHES)
                remainder = total_ns - sum(row["times_ns"])
                row["times_ns"][-1] += remainder
                row["batch_times_ns"] = row["times_ns"]
                row["batch_ranges_ns"] = _ranges(row["times_ns"])
                row["decode_ms"] = total_ns / (1_000_000 * row["loop_count"])
                with self.subTest(kind="normal", total_ns=total_ns):
                    if expected:
                        guards.validate_control(row, control, case, by_name)
                    else:
                        with self.assertRaises(AssertionError):
                            guards.validate_control(row, control, case, by_name)

            delay_control = CONTROLS[1]
            for extra_ns, expected in ((750_000_000, True), (749_999_999, False)):
                row = _row(case, delay_control, batch_ns=250_000_000)
                row["times_ns"][8] = 250_000_000 + extra_ns
                row["batch_times_ns"] = row["times_ns"]
                row["batch_ranges_ns"] = _ranges(row["times_ns"])
                row["observed_sleep_ns"] = [
                    row["batch_ranges_ns"][8][0] + 50_000_000,
                    row["batch_ranges_ns"][8][0] + 950_000_000,
                ]
                row["decode_ms"] = sum(row["times_ns"]) / (1_000_000 * row["loop_count"])
                with self.subTest(kind="delay", delta_ns=extra_ns):
                    if expected:
                        guards.validate_control(row, delay_control, case, by_name)
                    else:
                        with self.assertRaises(AssertionError):
                            guards.validate_control(row, delay_control, case, by_name)

            triple_control = CONTROLS[2]
            for batch_ns, cpu_ms, expected in ((30_000_000, 3.0, True),
                                               (29_999_999, 3.0, False),
                                               (30_000_000, 2.999, False)):
                row = _row(case, triple_control, batch_ns=batch_ns, cpu_ms=cpu_ms)
                with self.subTest(kind="triple", batch_ns=batch_ns):
                    if expected:
                        base_guards.validate_control(row, triple_control, case, by_name)
                    else:
                        with self.assertRaises(AssertionError):
                            base_guards.validate_control(row, triple_control, case, by_name)

            extra_control = CONTROLS[3]
            for delta, expected in ((24 * MIB, True), (24 * MIB - 1, False)):
                row = _row(case, extra_control, resource_delta=delta)
                with self.subTest(kind="extra32MiB", delta=delta):
                    if expected:
                        base_guards.validate_control(row, extra_control, case, by_name)
                    else:
                        with self.assertRaises(AssertionError):
                            base_guards.validate_control(row, extra_control, case, by_name)

    def test_payload_metadata_identity_and_argument_negatives(self):
        with tempfile.TemporaryDirectory(prefix="decoder-calibration-negative-") as directory:
            case = _write_case(Path(directory), 3)
            control = CONTROLS[0]
            row = _row(case, control)
            by_name = _by_name(row)

            bad_rows = {
                "wrong payload": {"pixel_sha256": "0" * 64},
                "wrong metadata": {"width": 63},
                "wrong executable": {"exe_sha256": "different"},
                "wrong worker": {"harness_sha256": "different"},
                "wrong input": {"input": case["path"] + ".different"},
                "wrong input hash": {"input_sha256": "0" * 64},
                "wrong worker UTF16 count": {"input_argument_utf16_units": 1},
                "wrong worker UTF16 hex": {"input_argument_utf16_hex": "4100"},
                "wrong probe UTF16 count": {"argument_utf16_units": 1},
                "wrong probe UTF16 hex": {"argument_utf16_hex": "4100"},
            }
            for label, changes in bad_rows.items():
                invalid = dict(row)
                invalid.update(changes)
                with self.subTest(label=label):
                    with self.assertRaises(AssertionError):
                        guards.common_row_guard(invalid, case, case["pixels_sha256"], EXE_HASH,
                                                WORKER_HASH, control)

            mutated = copy.deepcopy(row)
            mutated["bytes"] = PIXEL_BYTES - 1
            with self.assertRaises(AssertionError):
                guards.common_row_guard(mutated, case, case["pixels_sha256"], EXE_HASH,
                                        WORKER_HASH, control)

    def test_cpu_creation_cycle_and_resource_schema_negatives(self):
        with tempfile.TemporaryDirectory(prefix="decoder-calibration-fields-") as directory:
            case = _write_case(Path(directory), 4)
            control = CONTROLS[0]
            row = _row(case, control)

            mutations = {
                "GetProcessTimes false": lambda value: value["raw_cpu"][0].update(times_ok=False),
                "cycles false": lambda value: value["raw_cpu"][0].update(cycles_ok=False),
                "cycles zero": lambda value: value["raw_cpu"][0].update(cycles=0),
                "creation identity": lambda value: value["raw_cpu"][1].update(creation_100ns=112),
                "kernel ticks regress": lambda value: value["raw_cpu"][1].update(
                    kernel_100ns=9_999, user_100ns=10_000, cpu_ms=1.9999),
                "cycles regress": lambda value: value["raw_cpu"][1].update(cycles=1_999),
                "CPU scalar differs": lambda value: value.update(cpu_ms_before_transport=2.1),
                "sampled resource negative": lambda value: value["resources_before_transport"].update(sampled_max_private=-1),
                "peak commit limit": lambda value: value["resources_before_transport"].update(peak_commit=1 * 1024**3),
            }
            for label, mutate in mutations.items():
                invalid = copy.deepcopy(row)
                mutate(invalid)
                with self.subTest(label=label):
                    with self.assertRaises(AssertionError):
                        base_guards.common_row_guard(invalid, case, case["pixels_sha256"], EXE_HASH,
                                                     WORKER_HASH, control)

    def test_reference_mutation_is_exact_single_byte_and_not_a_native_claim(self):
        with tempfile.TemporaryDirectory(prefix="decoder-calibration-reference-") as directory:
            case = _write_case(Path(directory), 5)
            control = CONTROLS[4]
            row = _row(case, control)
            self.assertEqual(row["pixel_sha256"], base_guards.mutated_digest(Path(case["reference"])))
            base_guards.validate_control(row, control, case, _by_name(_row(case, CONTROLS[0])))


if __name__ == "__main__":
    unittest.main()
