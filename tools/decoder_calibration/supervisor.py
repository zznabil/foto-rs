# SPDX-License-Identifier: GPL-3.0-or-later
"""Owned-child build supervision and preserved failure evidence."""
from __future__ import annotations
if not __debug__:
    raise RuntimeError("decoder calibration refuses optimized Python")
import hashlib
import json
from pathlib import Path
import subprocess


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def load_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    require(isinstance(value, dict), f"expected object JSON: {path}")
    return value


def freeze_paths(paths: list[Path]) -> dict[str, str]:
    frozen = {}
    # Freeze backing bytes; cases and argument_guard bind exact raw spelling.
    for path in sorted({Path(path) for path in paths}, key=str):
        require(path.is_file(), f"frozen input is missing: {path}")
        frozen[str(path)] = digest(path)
    return frozen


def assert_frozen(frozen: dict[str, str], protected: dict[str, str]) -> None:
    for raw_path, expected in frozen.items():
        require(digest(Path(raw_path)) == expected, f"feasibility input changed: {raw_path}")
    for raw_path, expected in protected.items():
        require(digest(Path(raw_path)) == expected, f"protected root changed: {raw_path}")


def child_report(output: Path) -> dict | None:
    for name in ("extended-report.json", "report.json"):
        path = output / name
        if path.exists():
            try:
                return load_json(path)
            except BaseException as error:
                return {"report_read_error": repr(error), "report_path": str(path)}
    return None


def child_failure_evidence(output: Path) -> dict:
    evidence = {"raw_report": child_report(output)}
    raw_report = output / "extended-report.json"
    if raw_report.exists():
        try:
            evidence["raw_report_path"] = str(raw_report)
            evidence["raw_report_sha256"] = digest(raw_report)
        except BaseException as error:
            evidence["raw_report_hash_error"] = repr(error)
    cleanup = output / "monitor-cleanup.json"
    if cleanup.exists():
        try:
            evidence["cleanup"] = load_json(cleanup)
        except BaseException as error:
            evidence["cleanup_read_error"] = repr(error)
    else:
        evidence["cleanup"] = None
    return evidence


def cleanup_report(output: Path) -> dict:
    path = output / "monitor-cleanup.json"
    require(path.exists(), f"missing monitor cleanup evidence: {path}")
    details = load_json(path)
    require(details.get("cleanup_errors") == [], f"monitor cleanup errors: {path}")
    require(details.get("sample_errors") == [], f"monitor sample errors: {path}")
    require(details.get("all_monitors_terminal") is True, f"monitor did not terminate: {path}")
    return details


def record_child_failure(report: dict, save, base: dict, output: Path, error: BaseException) -> None:
    failure = dict(base)
    try:
        failure.update(child_failure_evidence(output))
    except BaseException as evidence_error:
        error.add_note("failed-child evidence collection failed: " + repr(evidence_error))
    report["failed_child"] = failure
    try:
        save()
    except BaseException as save_error:
        error.add_note("failed-child report write failed: " + repr(save_error))


def run_build(command: list[str], cwd: Path, env: dict[str, str], log: Path,
              report: dict, save, *, timeout: int = 1200) -> None:
    report["build"] = {"status": "STARTING", "pid": None, "command": command, "log": str(log)}
    save()
    process = None
    try:
        with log.open("x", encoding="utf-8") as stream:
            try:
                process = subprocess.Popen(command, cwd=cwd, env=env, stdout=stream,
                                           stderr=subprocess.STDOUT)
            except BaseException as error:
                report["build"].update(status="SPAWN_FAILED", error=repr(error))
                try:
                    save()
                except BaseException as save_error:
                    error.add_note("build failure report write failed: " + repr(save_error))
                raise
            report["build"].update(status="RUNNING", pid=process.pid)
            save()
            try:
                code = process.wait(timeout=timeout)
            except BaseException as error:
                report["build"].update(status="TIMEOUT_OR_ABORT", error=repr(error))
                try:
                    save()
                except BaseException as save_error:
                    error.add_note("build timeout report write failed: " + repr(save_error))
                cleanup_errors = []
                try:
                    process.kill()
                except BaseException as cleanup_error:
                    cleanup_errors.append("kill: " + repr(cleanup_error))
                try:
                    process.wait(timeout=30)
                except BaseException as cleanup_error:
                    cleanup_errors.append("wait-after-kill: " + repr(cleanup_error))
                try:
                    terminal = process.poll() is not None
                except BaseException as cleanup_error:
                    terminal = False
                    cleanup_errors.append("final-poll: " + repr(cleanup_error))
                if cleanup_errors:
                    error.add_note("build cleanup errors: " + repr(cleanup_errors))
                report["build"]["cleanup_errors"] = cleanup_errors
                report["build"]["terminal"] = terminal
                report["build"]["cleanup_complete"] = True
                if terminal:
                    report["build"]["pid"] = None
                else:
                    error.add_note("build child remained non-terminal; PID preserved")
                try:
                    save()
                except BaseException as save_error:
                    error.add_note("build cleanup report write failed: " + repr(save_error))
                raise
    except BaseException as error:
        if process is not None and not report["build"].get("cleanup_complete"):
            cleanup_errors = []
            try:
                terminal = process.poll() is not None
            except BaseException as cleanup_error:
                terminal = False
                cleanup_errors.append("poll: " + repr(cleanup_error))
            if not terminal:
                try:
                    process.kill()
                except BaseException as cleanup_error:
                    cleanup_errors.append("kill: " + repr(cleanup_error))
                try:
                    process.wait(timeout=30)
                except BaseException as cleanup_error:
                    cleanup_errors.append("wait-after-failure: " + repr(cleanup_error))
                try:
                    terminal = process.poll() is not None
                except BaseException as cleanup_error:
                    cleanup_errors.append("final-poll: " + repr(cleanup_error))
            report["build"]["cleanup_errors"] = cleanup_errors
            if cleanup_errors:
                error.add_note("build cleanup errors: " + repr(cleanup_errors))
            report["build"]["terminal"] = terminal
            report["build"]["cleanup_complete"] = True
            if terminal:
                report["build"]["pid"] = None
            else:
                error.add_note("build child remained non-terminal; PID preserved")
            try:
                save()
            except BaseException as save_error:
                error.add_note("build failure cleanup report write failed: " + repr(save_error))
        raise
    report["build"].update(status="PASS" if code == 0 else "FAIL", exit_code=code,
                            log_sha256=digest(log), terminal=True)
    report["build"]["pid"] = None
    save()
    require(code == 0, f"baseline probe build failed: {log}")
