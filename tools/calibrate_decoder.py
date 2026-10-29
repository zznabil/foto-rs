# SPDX-License-Identifier: GPL-3.0-or-later
"""One fresh baseline-only decoder protocol calibration; never candidate data."""
from __future__ import annotations

if not __debug__:
    raise RuntimeError("decoder calibration refuses optimized Python")

import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import traceback

from decoder_calibration import guards, protocol, supervisor as s

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "artifacts/decoder-calibration-v1"
EXAMPLE = ROOT / "examples/decoder_calibration_probe.rs"
FIXTURE_SHA = "3e66d9bcbade9ae52c832e4cdeb0b75abd48a85bfcde945fe3eefd04adbba9ab"
PIXEL_SHA = "33e9b5b811e2c42b2586f2a341cf489e004d0a965e8371edf567c32fb048e65e"


def utf16_hex(text):
    s.require(isinstance(text, str) and "\0" not in text, "invalid launch string")
    return text.encode("utf-16le").hex()


def units(text):
    return len(utf16_hex(text)) // 4


def raw_paths(base):
    """Keep the final argument lengths fixed when the checkout root changes."""
    base = str(base)
    s.require("/" not in base and base[1:3] == ":\\", "expected an absolute Windows root")
    remaining = 360 - units(base + "\\photo.png")
    s.require(remaining >= 4, "run root is too long for fixed path cases")
    parts = []
    while remaining:
        width = min(120, remaining - 1)
        if remaining - width - 1 == 1:
            width -= 1
        s.require(width > 0, "cannot construct a bounded path component")
        parts.append("c" * width)
        remaining -= width + 1
    normal = base + "\\" + "\\".join(parts) + "\\photo.png"
    short = base + "\\short.png"
    if (287 - units(short)) % 2:
        short = base + "\\short_.png"
    prefix, name = short.rsplit("\\", 1)
    count = (287 - units(short)) // 2
    s.require(count > 0, "run root is too long for normalizing path case")
    syntactic = prefix + "\\" + ".\\" * count + name
    paths = {"long-normal": normal, "long-verbatim": "\\\\?\\" + normal,
             "long-normalizes-short": syntactic}
    s.require([units(value) for value in paths.values()] == [360, 364, 287], "raw path lengths differ")
    return paths, short


def expected_pixels():
    # Independently authored opaque PBGRA quadrants, without invoking WIC.
    colors = [(0, 0, 255, 255), (0, 255, 0, 255), (255, 0, 0, 255), (0, 255, 255, 255)]
    return b"".join(bytes(colors[(y >= 24) * 2 + (x >= 32)]) for y in range(48) for x in range(64))


def make_cases(output):
    fixture = ROOT / "tests/fixtures/colors.png"
    s.require(s.digest(fixture) == FIXTURE_SHA, "synthetic fixture changed")
    pixels = expected_pixels()
    s.require(len(pixels) == 12288 and hashlib.sha256(pixels).hexdigest() == PIXEL_SHA, "pixel oracle changed")
    reference = output / "expected.pixels"
    reference.write_bytes(pixels)
    base = output / "inputs"
    base.mkdir()
    paths, short = raw_paths(base)
    for target in (paths["long-verbatim"], short):
        path = Path(target)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(fixture.read_bytes())
    cases = {}
    for name, raw in paths.items():
        encoded = utf16_hex(raw)
        s.require(s.digest(Path(raw)) == FIXTURE_SHA, "copied input differs")
        cases[name] = {"id": name, "path": raw, "input_sha256": FIXTURE_SHA,
                       "input_argument_utf16_units": len(encoded) // 4,
                       "input_argument_utf16_hex": encoded,
                       "raw_utf16_units": [int.from_bytes(bytes.fromhex(encoded[i:i + 4]), "little")
                                           for i in range(0, len(encoded), 4)],
                       "reference": str(reference), "pixels_sha256": PIXEL_SHA,
                       "decoded_metadata": [64, 48, [64, 48], 12288]}
    return cases


def stage_probe(template, source):
    marker = b'#[path = "__DECODE__"]'
    s.require(template.count(marker) == 1, "probe attribute marker must be unique")
    replacement = ('#[path = "' + source.as_posix() + '"]').encode()
    return template.replace(marker, replacement, 1)


def depfile_has_source(text, source):
    # Pinned rustc emits an empty rule for each source, escaping only spaces.
    return source.as_posix() in {line[:-1].replace(r"\ ", " ").replace("\\", "/")
                                 for line in text.splitlines() if line.endswith(":")}


def git(*args):
    return subprocess.check_output(["git", "-c", "core.excludesFile=", *args], cwd=ROOT, text=True).strip()


def main():
    s.require(sys.platform == "win32" and platform.machine().lower() in ("amd64", "x86_64"), "Windows x64 required")
    s.require(sys.version_info[:3] == (3, 14, 7), "Python 3.14.7 required")
    artifact_root = (ROOT / "artifacts").resolve()
    s.require(artifact_root.is_relative_to(ROOT.resolve()) and OUT.resolve().is_relative_to(artifact_root), "output escaped checkout")
    s.require(not OUT.exists() and not EXAMPLE.exists(), "calibration already attempted; preserve prior output")
    s.require(not git("status", "--porcelain"), "commit calibration source before native verification")
    OUT.mkdir(parents=True)
    report = {"status": "SETUP", "controller_pid": os.getpid(), "rows": [],
              "candidate_executed": False, "candidate_n_frozen": False, "performance_count": False}

    def save():
        s.write_json(OUT / "report.json", report)

    primary = None
    example_bytes = None
    frozen = {}
    try:
        from decoder_calibration import measure, native, worker

        for module, expected in ((worker.t, ROOT / "tools/stress_test.py"),
                                 (native.t, ROOT / "tools/stress_test.py"),
                                 (native.s, ROOT / "tools/smoke_test.py")):
            s.require(Path(module.__file__).resolve() == expected.resolve(), "unexpected support module")
        s.require(native.t is worker.t and native.s is worker.t.s and measure.w is worker
                  and measure.native is native, "measurement module identity differs")
        s.require(guards.INNER == guards.base.INNER == 512
                  and guards.BATCHES == guards.base.BATCHES == 16
                  and guards.MIB == guards.base.MIB == 1048576
                  and guards.CONTROL_DEFINITIONS is guards.base.CONTROL_DEFINITIONS
                  and guards.require is guards.base.require, "formal guard owner differs")
        protocol.self_test()
        rustc = Path(subprocess.check_output(["rustup", "which", "rustc"], text=True).strip())
        cargo = rustc.with_name("cargo.exe")
        rust_version = subprocess.check_output([str(rustc), "--version"], text=True).strip()
        s.require(rust_version.startswith("rustc 1.98.1 "), "Rust 1.98.1 required")
        cases = make_cases(OUT)
        paths = [ROOT / name for name in git("ls-files").splitlines()]
        tracked = {path.resolve() for path in paths}
        canonical = {"decoder_calibration": sys.modules[measure.__package__],
                     "protocol": protocol, "worker": worker, "measure": measure,
                     "native": native, "guards": guards, "base_guards": guards.base, "supervisor": s}
        module_proof = {}
        for name, module in canonical.items():
            path = Path(module.__file__).resolve()
            expected = ROOT / "tools/decoder_calibration" / ("__init__.py" if name == "decoder_calibration" else name + ".py")
            s.require(path == expected.resolve() and path in tracked, "canonical module path is untracked or changed")
            module_proof[name] = {"path": str(path.relative_to(ROOT)), "sha256": s.digest(path)}
        paths += [Path(sys.executable), rustc, cargo, OUT / "expected.pixels"]
        paths += [Path(case["path"]) for case in cases.values()]
        frozen = s.freeze_paths(paths)
        plan = {"status": "FROZEN_BEFORE_PORTABLE_BASELINE_CALIBRATION", "revision": git("rev-parse", "HEAD"),
                "tree": git("rev-parse", "HEAD^{tree}"), "platform": platform.platform(),
                "machine": platform.machine(), "logical_cpus": os.cpu_count(),
                "python": sys.version, "rustc": rust_version, "frozen_inputs": frozen, "canonical_modules": module_proof,
                "cases": cases, "controls": guards.CONTROL_DEFINITIONS, "inner": 512, "batches": 16,
                "expected_children": 15, "expected_peak_setup_children": 1,
                "build_timeout_seconds": 1200, "peak_setup_timeout_seconds": 60,
                "candidate": False, "AA_AB": False,
                "limits": "Protocol portability only; no host-stability, performance, plateau or UAT claim."}
        s.write_json(OUT / "plan.json", plan)
        s.require(s.load_json(OUT / "plan.json") == json.loads(json.dumps(plan)), "saved plan differs")
        frozen[str(OUT / "plan.json")] = s.digest(OUT / "plan.json")
        s.write_json(OUT / "attempt.json", {"plan_sha256": s.digest(OUT / "plan.json"), "expected_children": 15})
        frozen[str(OUT / "attempt.json")] = s.digest(OUT / "attempt.json")
        report.update(status="BUILDING_BASELINE", frozen_inputs=frozen)
        save()
        template = ROOT / "tools/decoder_calibration/probe.rs"
        example_bytes = stage_probe(template.read_bytes(), ROOT / "src/decode.rs")
        EXAMPLE.write_bytes(example_bytes)
        (OUT / "staged-probe.rs").write_bytes(example_bytes)
        frozen[str(OUT / "staged-probe.rs")] = s.digest(OUT / "staged-probe.rs")
        env = os.environ.copy()
        target = OUT / "target"
        env["CARGO_TARGET_DIR"] = str(target)
        env["RUSTC"] = str(rustc)
        for name in ("RUSTFLAGS", "CARGO_ENCODED_RUSTFLAGS", "RUSTC_WRAPPER", "RUSTC_WORKSPACE_WRAPPER"):
            env.pop(name, None)
        env["PATH"] = str(rustc.parent) + os.pathsep + env["PATH"]
        s.run_build([str(cargo), "build", "--release", "--locked", "--example", EXAMPLE.stem,
                     "--message-format=json"], ROOT, env, OUT / "build.log", report, save)
        report["baseline_build_process"] = dict(report["build"])
        frozen[str(OUT / "build.log")] = s.digest(OUT / "build.log")
        events = [json.loads(line) for line in (OUT / "build.log").read_text().splitlines() if line.startswith("{")]
        executables = [Path(e["executable"]) for e in events if e.get("reason") == "compiler-artifact"
                       and e.get("target", {}).get("name") == EXAMPLE.stem and e.get("executable")]
        s.require(len(executables) == 1 and executables[0].is_file(), "ambiguous baseline Cargo executable")
        exe = OUT / "probe.exe"
        shutil.copy2(executables[0], exe)
        depfile = executables[0].with_suffix(".d")
        dependencies = depfile.read_text(encoding="utf-8")
        s.require(depfile_has_source(dependencies, ROOT / "src/decode.rs"), "baseline source missing from Cargo depfile")
        shutil.copy2(depfile, OUT / "probe.d")
        report["baseline_build"] = {"exe_sha256": s.digest(exe), "depfile_sha256": s.digest(OUT / "probe.d"),
                                    "staged_probe_sha256": s.digest(OUT / "staged-probe.rs"),
                                    "source_sha256": s.digest(ROOT / "src/decode.rs")}
        frozen.update(s.freeze_paths([exe, OUT / "probe.d"]))
        s.require(EXAMPLE.read_bytes() == example_bytes, "staged example changed")
        EXAMPLE.unlink()
        s.assert_frozen(frozen, {})
        report["status"] = "CALIBRATING_KERNEL_PEAK_COUNTERS"
        save()
        # Hashing large build tools can prime this controller's lifetime peaks.
        s.run_build([sys.executable, str(Path(native.__file__)), str(OUT / "peak-calibration.json")],
                    ROOT, os.environ.copy(), OUT / "peak-calibration.log", report, save, timeout=60)
        s.require("PEAK_COMMIT_RSS_READER_POSITIVE_AND_BROKEN_CONTROLS_PASS" in
                  (OUT / "peak-calibration.log").read_text(), "peak calibration success marker missing")
        s.require(s.load_json(OUT / "peak-calibration.json")["status"] == "PEAK_COMMIT_RSS_READER_CALIBRATION_PASS",
                  "kernel peak calibration did not pass")
        report["peak_setup_process"] = dict(report["build"])
        frozen[str(OUT / "peak-calibration.log")] = s.digest(OUT / "peak-calibration.log")
        frozen[str(OUT / "peak-calibration.json")] = s.digest(OUT / "peak-calibration.json")
        worker_hash = s.digest(Path(worker.__file__))
        report["status"] = "CALIBRATING_FIFTEEN_BASELINE_CONTROLS"
        for case_name, case in cases.items():
            by_name = {"exe_hash": s.digest(exe), "worker_hash": worker_hash}
            for control in guards.CONTROL_DEFINITIONS:
                s.assert_frozen(frozen, {})
                output = OUT / (case_name + "-" + control["name"])
                context = {"case": case_name, "control": control["name"], "output": str(output)}
                report["active_child"] = context
                save()
                try:
                    row = measure.sample(exe, case["path"], output, 512, repeats=control["repeats"],
                                         delay=control["delay_ms"], extra=control["extra_bytes"], corrupt=control["corrupt"])
                    s.require(s.load_json(output / "extended-report.json") == row, "saved raw row differs")
                    entry = {**context, "raw": row, "raw_sha256": s.digest(output / "extended-report.json")}
                    report["rows"].append(entry)
                    save()
                    entry["checks"] = guards.validate_control(row, control, case, by_name)
                    entry["cleanup"] = s.cleanup_report(output)
                    s.require(row.get("child_cleanup_terminal") is True and row.get("reader_cleanup_terminal") is True
                              and row.get("cleanup_errors") == [], "worker cleanup is incomplete")
                    by_name[control["name"]] = row
                    frozen.update(s.freeze_paths(list(output.glob("*.json"))))
                    report["active_child"] = None
                    save()
                    print("DECODER_CONTROL_PASS", case_name, control["name"], flush=True)
                except BaseException as error:
                    s.record_child_failure(report, save, context, output, error)
                    raise
        s.require(len(report["rows"]) == 15, "not all fifteen controls completed")
        s.assert_frozen(frozen, {})
        s.require(not git("status", "--porcelain"), "tracked source or unexpected files changed")
        report["status"] = "DECODER_CALIBRATION_PASS_15_BASELINE_ONLY"
    except BaseException as error:
        primary = error
        report.update(status="DECODER_CALIBRATION_FAILURE_PRESERVED", failure=repr(error), traceback=traceback.format_exc())
        peak = OUT / "peak-calibration.json"
        try:
            if peak.is_file():
                report["peak_calibration_artifact"] = {"path": str(peak.relative_to(OUT)), "sha256": s.digest(peak)}
        except BaseException as evidence_error:
            error.add_note("peak failure evidence: " + repr(evidence_error))
        raise
    finally:
        errors = []
        try:
            if EXAMPLE.exists():
                s.require(EXAMPLE.read_bytes() == example_bytes, "temporary example changed")
                EXAMPLE.unlink()
            s.assert_frozen(frozen, {})
        except BaseException as error:
            errors.append(repr(error))
            if primary is None:
                primary = error
            else:
                primary.add_note("calibration cleanup: " + repr(error))
        workers = [entry["raw"] for entry in report["rows"]]
        failed = report.get("failed_child")
        if failed:
            workers.append(failed.get("raw_report") or {})
        children_terminal = all(row.get("child_cleanup_terminal") is True and
                                row.get("reader_cleanup_terminal") is True for row in workers)
        process_records = {name: report[name] for name in ("baseline_build_process", "peak_setup_process", "build")
                           if name in report}
        children_terminal = children_terminal and all(record.get("terminal") is True or
                            record.get("status") in ("STARTING", "SPAWN_FAILED")
                            for record in process_records.values())
        children_terminal = children_terminal and not (report.get("active_child") and not failed)
        if not children_terminal:
            errors.append("owned child or reader terminal state is unproven; retain failure evidence and PID")
        report.update(controller_terminal=True, terminal=children_terminal, process_records=process_records,
                      decoder_reports=len(workers), cleanup_errors=errors,
                      failure_notes=getattr(primary, "__notes__", []))
        if errors:
            report["status"] = "DECODER_CALIBRATION_CLEANUP_FAILURE_PRESERVED"
            if primary is None:
                primary = RuntimeError("calibration cleanup: " + repr(errors))
                report["failure"] = repr(primary)
        try:
            save()
        except BaseException as error:
            if primary is None:
                raise
            primary.add_note("calibration final report: " + repr(error))
        if primary is not None and errors:
            raise primary
    print("DECODER_CALIBRATION_PASS_15_BASELINE_ONLY", flush=True)


if __name__ == "__main__":
    main()
