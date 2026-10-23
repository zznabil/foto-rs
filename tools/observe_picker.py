# SPDX-License-Identifier: GPL-3.0-or-later
"""One observed smoke-picker attempt; never a smoke, performance or release pass."""
from __future__ import annotations

if not __debug__:
    raise RuntimeError("picker observer requires Python assertions")

import hashlib
import json
import os
from pathlib import Path
import platform
import struct
import subprocess
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "artifacts/picker-observer-v1"
SMOKE_SHA = "2404bcbe784f914e2bcf14a84174811ac0f008410e15447fde345eac305a9e2b"
STRESS_SHA = "2ddd150e2516c65452cff535eb86c5c656298c58b154b888725052109a2a3827"


class PickerObserved(Exception):
    """Stop after the original cancellation oracle, allowing its finally cleanup."""


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Native:
    def __init__(self, smoke, stress):
        self.s, self.t = smoke, stress
        c, w, api, user = smoke.C, smoke.W, smoke.api, smoke.user
        self.exists = api(user, "IsWindow", w.BOOL, w.HWND)
        self.visible = api(user, "IsWindowVisible", w.BOOL, w.HWND)
        self.owner = api(user, "GetWindow", w.HWND, w.HWND, w.UINT)
        self.foreground = api(user, "GetForegroundWindow", w.HWND)
        self.create = api(user, "CreateDialogIndirectParamW", w.HWND, w.HINSTANCE,
                          c.c_void_p, w.HWND, c.c_void_p, w.LPARAM)
        self.destroy = api(user, "DestroyWindow", w.BOOL, w.HWND)
        self.show = api(user, "ShowWindow", w.BOOL, w.HWND, c.c_int)

    def state(self, hwnd, pid):
        s = self.s
        exists = bool(hwnd and self.exists(hwnd))
        owner_pid = s.W.DWORD()
        s.C.set_last_error(0)
        thread = s.get_pid(hwnd, s.C.byref(owner_pid)) if hwnd else 0
        query_error = s.C.get_last_error() if not thread else None
        owned = exists and owner_pid.value == pid
        row = {"hwnd": int(hwnd or 0), "exists": exists, "pid_query_error": query_error,
               "pid": owner_pid.value, "thread": thread, "owned": owned}
        if owned:
            s.C.set_last_error(0)
            title = s.text(hwnd)
            title_error = s.C.get_last_error()
            s.C.set_last_error(0)
            window_class = s.text(hwnd, s.get_class)
            class_error = s.C.get_last_error()
            row.update(visible=bool(self.visible(hwnd)), enabled=bool(s.enabled(hwnd)),
                       owner=int(self.owner(hwnd, 4) or 0), title=title, window_class=window_class,
                       title_query_error=title_error, class_query_error=class_error)
            info = self.t.ThreadInfo(s.C.sizeof(self.t.ThreadInfo))
            s.C.set_last_error(0)
            ok = bool(self.t.get_thread_info(thread, s.C.byref(info)))
            error = s.C.get_last_error()
            row["gui"] = {"ok": ok, "error": error if not ok else None,
                          "active": int(info.active or 0), "focus": int(info.focus or 0), "flags": info.flags}
        row["exists_after"] = bool(hwnd and self.exists(hwnd))
        return row

    def owned(self, process, hwnd):
        pid = self.s.W.DWORD()
        return (process.poll() is None and bool(hwnd and self.exists(hwnd))
                and bool(self.s.get_pid(hwnd, self.s.C.byref(pid))) and pid.value == process.pid)

    def snapshot(self, process, main, dialog, log):
        start = time.perf_counter_ns()
        exited = process.poll()
        matches = self.s.windows(process.pid, "#32770") if exited is None else []
        row = {"start_ns": start, "process_exit_start": exited, "foreground": int(self.foreground() or 0),
               "main": self.state(main, process.pid) if exited is None else None,
               "target": self.state(dialog, process.pid) if exited is None else None,
               "matches": [self.state(hwnd, process.pid) for hwnd in matches]}
        row["process_exit_end"] = process.poll()
        row["process_stable"] = exited == row["process_exit_end"]
        row["end_ns"] = time.perf_counter_ns()
        return row

    def post(self, original, *args):
        self.s.C.set_last_error(0)
        result = original(*args)
        error = self.s.C.get_last_error()
        return result, error

    def calibrate(self, result):
        s = self.s
        assert s.C.sizeof(s.C.c_void_p) == 8 and s.C.sizeof(self.t.ThreadInfo) == 72
        before = set(s.windows(os.getpid(), "#32770"))
        callback_type = s.C.WINFUNCTYPE(s.C.c_ssize_t, s.W.HWND, s.W.UINT, s.W.WPARAM, s.W.LPARAM)
        callback = callback_type(lambda hwnd, message, wp, lp: 0)
        # A modeless, non-activating diagnostic dialog with no controls or user data.
        template = s.C.create_string_buffer(struct.pack("<IIHhhhhHHH", 0x80C00000, 0x08000080,
                                                       0, -32000, -32000, 5, 5, 0, 0, 0))
        hwnd = self.create(None, template, None, callback, 0)
        assert hwnd, "observer calibration dialog creation failed"
        result["hwnd"] = int(hwnd)
        primary = None
        try:
            result["hidden"] = self.state(hwnd, os.getpid())
            assert hwnd in s.windows(os.getpid(), "#32770")
            assert result["hidden"]["exists"] and result["hidden"]["visible"] is False
            self.show(hwnd, 4)  # SW_SHOWNOACTIVATE; only our synthetic window.
            result["shown"] = self.state(hwnd, os.getpid())
            assert result["shown"]["visible"] is True and int(self.foreground() or 0) != int(hwnd)
        except BaseException as error:
            primary = error
            raise
        finally:
            try:
                assert self.destroy(hwnd), "observer calibration dialog cleanup failed"
                assert not self.exists(hwnd) and set(s.windows(os.getpid(), "#32770")) == before
            except BaseException as error:
                if primary is None:
                    raise
                primary.add_note("observer calibration cleanup: " + repr(error))
        result["destroyed"] = self.state(hwnd, os.getpid())
        result["status"] = "NATIVE_HIDDEN_VISIBLE_DESTROYED_OBSERVER_CONTROLS_PASS"


def observe(s, native, report, save):
    """Route the unchanged smoke flow; sidecar samples never decide its oracle."""
    original = {name: getattr(s, name) for name in ("wait", "post", "launch", "close")}
    popen = s.subprocess.Popen
    processes = []
    active = None
    primary = None
    closing = None
    report.update(samples=[], observation_errors=[], cleanup_errors=[], posts=[], closes=[], owned=[], oracle="NOT_REACHED")

    def persist(error=None):
        try:
            save()
        except BaseException as failure:
            if error is None:
                raise
            error.add_note("observer report write: " + repr(failure))

    def capture(phase, result=None):
        try:
            assert active is not None, "no active viewer context"
            process, hwnd, log = active
            row = native.snapshot(process, hwnd, report.get("dialog", 0), log)
            if phase == "before_cleanup":
                rows = s.rows(log)
                row["timing"] = {"path": str(log), "sha256": digest(log), "rows": len(rows),
                                 "errors": [item for item in rows if item.get("event") in ("error", "graphics_error")]}
            report["samples"].append({"phase": phase, "oracle_result": result, **row})
        except Exception as error:
            report["observation_errors"].append({"phase": phase, "error": repr(error)})

    def tracked_popen(*args, **kwargs):
        assert len(processes) < 2, "observer must stop before later smoke launches"
        process = popen(*args, **kwargs)
        processes.append(process)
        report["owned"].append({"pid": process.pid, "command": args[0]})
        persist()
        return process

    def launch(exe, photo, log):
        nonlocal active
        value = original["launch"](exe, photo, log)
        active = (value[0], value[1], log)
        return value

    def post(hwnd, message, wp, lp):
        if closing is not None and message == 0x10:
            value, error = native.post(original["post"], hwnd, message, wp, lp)
            closing["post"] = {"result": bool(value), "last_error": error}
            return value
        if hwnd != report.get("dialog") or message != 0x10:
            return original["post"](hwnd, message, wp, lp)
        assert not report["posts"], "more than one picker-close post"
        capture("before_post")
        assert native.owned(active[0], hwnd), "picker HWND ownership lost; no close sent"
        started = time.perf_counter_ns()
        value, error = native.post(original["post"], hwnd, message, wp, lp)
        report["posts"].append({"hwnd": int(hwnd), "message": message, "result": bool(value),
                                "last_error": error, "start_ns": started, "end_ns": time.perf_counter_ns()})
        return value

    def wait(condition, label, timeout=8):
        nonlocal primary
        if label == "native file picker":
            value = original["wait"](condition, label, timeout)
            report["dialog"] = int(value[0])
            capture("picker_found")
            return value
        if label != "file picker cancellation":
            return original["wait"](condition, label, timeout)
        assert timeout == 8 and len(report["posts"]) == 1
        report["oracle"] = "RUNNING"

        def observed_condition():
            value = condition()
            capture("cancellation_poll", bool(value))
            return value

        try:
            original["wait"](observed_condition, label, timeout)
        except BaseException as error:
            primary = error
            report.update(oracle="FAIL", failure=repr(error), traceback=traceback.format_exc())
            capture("before_cleanup")
            persist(error)
            raise
        report["oracle"] = "PASS_DIAGNOSTIC_ONLY"
        capture("before_cleanup")
        raise PickerObserved()

    def close(process, hwnd):
        nonlocal closing
        body_error = sys.exception()
        if body_error is not None and not isinstance(body_error, PickerObserved):
            report.setdefault("failure", repr(body_error))
            report.setdefault("traceback", traceback.format_exc())
            if report["oracle"] == "NOT_REACHED":
                capture("before_cleanup")
                persist(body_error)
        event = {"pid": process.pid, "hwnd": int(hwnd), "start_ns": time.perf_counter_ns(),
                 "exit_before": process.poll()}
        report["closes"].append(event)
        try:
            if event["exit_before"] is not None:
                event["status"] = "SKIPPED_ALREADY_TERMINAL"
                assert event["exit_before"] == 0, "viewer already exited abnormally"
            else:
                assert native.owned(process, hwnd), "owner HWND ownership lost; no close sent"
                closing = event
                original["close"](process, hwnd)
                event["status"] = "CANONICAL_CLOSE_RETURNED_ZERO"
        except BaseException as error:
            event.update(status="CANONICAL_CLOSE_FAILED", error=repr(error))
            report["cleanup_errors"].append({"pid": process.pid, "error": repr(error)})
            if body_error is None:
                raise
            body_error.add_note("smoke cleanup: " + repr(error))
        finally:
            closing = None
            event.update(exit_after=process.poll(), end_ns=time.perf_counter_ns())

    s.wait, s.post, s.launch, s.close = wait, post, launch, close
    s.subprocess.Popen = tracked_popen
    try:
        s.main()
        raise AssertionError("observer failed to stop after picker")
    except PickerObserved:
        pass
    except BaseException as error:
        primary = error
        report.setdefault("failure", repr(error))
        report.setdefault("traceback", traceback.format_exc())
        raise
    finally:
        for name, value in original.items():
            setattr(s, name, value)
        s.subprocess.Popen = popen
        # The canonical close may kill without waiting. Reap only our tracked children.
        for process, record in zip(processes, report["owned"]):
            try:
                record["forced_kill_attempted"] = False
                if process.poll() is None:
                    record["forced_kill_attempted"] = True
                    process.kill()
                    record["wait_after_kill"] = process.wait(timeout=4)
                record.update(exit_code=process.poll(), terminal=process.poll() is not None)
            except BaseException as error:
                record.update(terminal=False, cleanup_error=repr(error))
                report["cleanup_errors"].append({"pid": process.pid, "error": repr(error)})
        report["terminal"] = all(row.get("terminal") is True for row in report["owned"])
        valid = report["terminal"] and not report["cleanup_errors"] and not report["observation_errors"]
        valid = valid and all(event.get("status") == "CANONICAL_CLOSE_RETURNED_ZERO" and
                              event.get("post", {}).get("result") is True for event in report["closes"])
        final = next((row for row in reversed(report["samples"]) if row["phase"] == "before_cleanup"), {})
        report["viewer_alive_at_oracle_end"] = (final.get("process_stable") is True and
                                                final.get("process_exit_start") is None and
                                                final.get("process_exit_end") is None)
        valid = valid and report["viewer_alive_at_oracle_end"]
        report["status"] = ("PICKER_OBSERVED_DIAGNOSTIC_ONLY" if valid and report["oracle"] == "PASS_DIAGNOSTIC_ONLY"
                            else "PICKER_DIAGNOSTIC_FAILURE_PRESERVED")
        persist(primary)
        if primary is None and report["status"] != "PICKER_OBSERVED_DIAGNOSTIC_ONLY":
            raise RuntimeError("picker diagnostic invalid; inspect preserved report")


def main():
    assert sys.platform == "win32" and platform.machine().lower() in ("amd64", "x86_64")
    assert sys.version_info[:3] == (3, 14, 7)
    assert OUT.resolve().is_relative_to(ROOT.resolve())
    assert not OUT.exists(), "preserve the prior diagnostic; no unchanged retry"
    assert not subprocess.check_output(["git", "-c", "core.excludesFile=", "status", "--porcelain"], cwd=ROOT)
    OUT.mkdir(parents=True)
    report = {"status": "SETUP", "performance_count": False, "full_smoke_pass": False,
              "original_failure_cleared": False}

    def save():
        (OUT / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    frozen = {}
    primary = None
    try:
        import smoke_test as s
        import stress_test as t
        assert s is t.s and Path(s.__file__).resolve() == ROOT / "tools/smoke_test.py"
        assert Path(t.__file__).resolve() == ROOT / "tools/stress_test.py"
        assert digest(Path(s.__file__)) == SMOKE_SHA and digest(Path(t.__file__)) == STRESS_SHA, "review the changed helper contract"
        exe = ROOT / "target/release/foto.exe"
        paths = [ROOT / name for name in subprocess.check_output(["git", "ls-files"], cwd=ROOT, text=True).splitlines()]
        paths += [exe, Path(sys.executable), *sorted((ROOT / "artifacts/photos").glob("*.jpg"))]
        assert len(list((ROOT / "artifacts/photos").glob("*.jpg"))) == 3
        frozen = {str(path): digest(path) for path in paths}
        plan = {"revision": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
                "tree": subprocess.check_output(["git", "rev-parse", "HEAD^{tree}"], cwd=ROOT, text=True).strip(),
                "host": platform.platform(), "python": sys.version, "frozen_inputs": frozen,
                "original_oracle": "not windows(process.pid, '#32770')", "timeout_seconds": 8,
                "picker_close_posts": 1, "maximum_viewer_launches": 2,
                "limits": "Observer overhead may affect readiness. No reproduction does not refute prior failure. No full smoke/performance/UAT/release claim."}
        (OUT / "plan.json").write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
        frozen[str(OUT / "plan.json")] = digest(OUT / "plan.json")
        report.update(status="CALIBRATING_OBSERVER", frozen_inputs=frozen)
        save()
        native = Native(s, t)
        calibration = {"status": "NATIVE_OBSERVER_CONTROLS_STARTED"}
        calibration_error = None
        try:
            native.calibrate(calibration)
        except BaseException as error:
            calibration_error = error
            calibration.update(status="NATIVE_OBSERVER_CONTROLS_FAILURE_PRESERVED", failure=repr(error),
                               failure_notes=getattr(error, "__notes__", []))
            raise
        finally:
            try:
                (OUT / "calibration.json").write_text(json.dumps(calibration, indent=2) + "\n", encoding="utf-8")
            except BaseException as error:
                if calibration_error is None:
                    raise
                calibration_error.add_note("observer calibration report: " + repr(error))
        frozen[str(OUT / "calibration.json")] = digest(OUT / "calibration.json")
        report.update(status="OBSERVING", frozen_inputs=frozen)
        save()
        previous = sys.argv
        sys.argv = [s.__file__, "--exe", str(exe), "--runs", "1"]
        try:
            observe(s, native, report, save)
        finally:
            sys.argv = previous
    except BaseException as error:
        primary = error
        report.update(status="PICKER_DIAGNOSTIC_FAILURE_PRESERVED", failure=repr(error), traceback=traceback.format_exc())
        raise
    finally:
        try:
            assert all(digest(Path(path)) == expected for path, expected in frozen.items()), "diagnostic input changed"
            report["frozen_unchanged"] = True
        except BaseException as error:
            report.update(status="PICKER_DIAGNOSTIC_FAILURE_PRESERVED", frozen_unchanged=False)
            if primary is None:
                primary = error
                report["failure"] = repr(error)
            else:
                primary.add_note("observer integrity: " + repr(error))
        report["failure_notes"] = getattr(primary, "__notes__", [])
        try:
            save()
        except BaseException as error:
            if primary is None:
                raise
            primary.add_note("observer final report write: " + repr(error))
        if primary is not None and report.get("frozen_unchanged") is False:
            raise primary
    print("PICKER_OBSERVED_DIAGNOSTIC_ONLY", flush=True)


if __name__ == "__main__":
    main()
