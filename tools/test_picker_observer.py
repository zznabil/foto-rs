# SPDX-License-Identifier: GPL-3.0-or-later
"""Portable routing/lifecycle controls; native HWND calibration is separate."""
import ast
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest import mock

import observe_picker as observer


class Clock:
    def __init__(self):
        self.now = 0

    def monotonic(self):
        return self.now

    def sleep(self, duration):
        self.now += duration


class Child:
    def __init__(self, pid):
        self.pid, self.code, self.kills = pid, None, 0

    def poll(self):
        return self.code

    def kill(self):
        self.kills += 1
        self.code = -9

    def wait(self, timeout):
        return self.code


class Smoke:
    def __init__(self, root, *, residual=False, close_error=False, setup_error=False, duplicate=False):
        self.root, self.residual, self.close_error = root, residual, close_error
        self.setup_error, self.duplicate = setup_error, duplicate
        self.children, self.matches, self.sent, self.later = [], [81], [], False
        self.subprocess = types.SimpleNamespace(Popen=self.spawn)
        path = Path(__file__).with_name("smoke_test.py")
        node = next(n for n in ast.parse(path.read_text(encoding="utf-8")).body
                    if isinstance(n, ast.FunctionDef) and n.name == "wait")
        namespace = {"time": Clock()}
        exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), "exec"), namespace)
        self.wait = namespace["wait"]

    def spawn(self, command):
        child = Child(100 + len(self.children))
        self.children.append(child)
        return child

    def launch(self, exe, photo, log):
        child = self.subprocess.Popen([str(exe), str(photo)])
        self.wait(lambda: not self.setup_error, "native viewer window")
        log.write_bytes(b"event\n")
        return child, child.pid * 10, 0

    def post(self, hwnd, message, wp, lp):
        self.sent.append((hwnd, message))
        if hwnd == 81:
            self.matches = [99] if self.residual else []
        return 1

    def rows(self, log):
        return []

    def close(self, process, hwnd):
        self.post(hwnd, 0x10, 0, 0)
        if self.close_error and process is self.children[-1] and len(self.children) == 2:
            raise OSError("simulated close failure")
        process.code = 0

    def main(self):
        process, hwnd, _ = self.launch("synthetic.exe", None, self.root / "empty.csv")
        self.close(process, hwnd)
        process, hwnd, _ = self.launch("synthetic.exe", "synthetic.jpg", self.root / "interactive.csv")
        try:
            dialog = self.wait(lambda: self.matches, "native file picker")[0]
            assert self.post(dialog, 0x10, 0, 0)
            if self.duplicate:
                self.post(dialog, 0x10, 0, 0)
            self.wait(lambda: not self.matches, "file picker cancellation")
            self.later = True
        finally:
            self.close(process, hwnd)


class Native:
    def __init__(self, smoke, broken=False):
        self.smoke, self.broken = smoke, broken
        self.ownership = True

    def snapshot(self, process, main, dialog, log):
        if self.broken:
            raise OSError("simulated observer failure")
        return {"target": {"hwnd": dialog, "exists": dialog in self.smoke.matches},
                "matches": [{"hwnd": hwnd} for hwnd in self.smoke.matches],
                "process_exit_start": process.poll(), "process_exit_end": process.poll(), "process_stable": True}

    def owned(self, process, hwnd):
        return self.ownership

    def post(self, original, *args):
        return original(*args), 0


class PickerObserverTests(unittest.TestCase):
    def run_case(self, directory, **settings):
        smoke = Smoke(Path(directory), **settings)
        saved = []
        return smoke, Native(smoke), {}, lambda report: saved.append(json.loads(json.dumps(report)))

    def test_original_oracle_pass_stops_before_later_smoke_and_restores_hooks(self):
        with tempfile.TemporaryDirectory() as directory:
            s, native, report, save = self.run_case(directory)
            originals = {name: getattr(s, name) for name in ("wait", "post", "launch", "close")}
            popen = s.subprocess.Popen
            observer.observe(s, native, report, lambda: save(report))
            self.assertEqual(report["oracle"], "PASS_DIAGNOSTIC_ONLY")
            self.assertEqual(report["status"], "PICKER_OBSERVED_DIAGNOSTIC_ONLY")
            self.assertEqual(len(report["posts"]), 1)
            self.assertEqual(len(s.children), 2)
            self.assertFalse(s.later)
            self.assertTrue(report["terminal"])
            self.assertEqual([p.code for p in s.children], [0, 0])
            self.assertEqual(report["samples"][-1]["timing"]["errors"], [])
            self.assertIs(s.subprocess.Popen, popen)
            for name, value in originals.items():
                self.assertEqual(getattr(s, name), value)

    def test_destroyed_target_with_residual_window_still_fails_original_oracle(self):
        with tempfile.TemporaryDirectory() as directory:
            s, native, report, save = self.run_case(directory, residual=True)
            with self.assertRaisesRegex(AssertionError, "Timed out: file picker cancellation"):
                observer.observe(s, native, report, lambda: save(report))
            self.assertEqual(report["oracle"], "FAIL")
            polls = [row for row in report["samples"] if row["phase"] == "cancellation_poll"]
            self.assertGreater(len(polls), 1)
            self.assertTrue(all(not row["target"]["exists"] and row["matches"] for row in polls))
            self.assertFalse(any(row["oracle_result"] for row in polls))
            self.assertEqual(len(report["posts"]), 1)
            self.assertTrue(report["terminal"])
            self.assertFalse(s.later)

    def test_timeout_survives_close_and_report_errors_and_owned_child_is_reaped(self):
        with tempfile.TemporaryDirectory() as directory:
            s, native, report, _ = self.run_case(directory, residual=True, close_error=True)

            def broken_save():
                if report["oracle"] == "FAIL":
                    raise OSError("simulated report failure")

            with self.assertRaisesRegex(AssertionError, "Timed out: file picker cancellation") as caught:
                observer.observe(s, native, report, broken_save)
            self.assertIn("simulated close failure", str(caught.exception.__notes__))
            self.assertIn("simulated report failure", str(caught.exception.__notes__))
            self.assertTrue(report["terminal"])
            self.assertEqual(s.children[-1].kills, 1)
            self.assertEqual(len(report["cleanup_errors"]), 1)
            self.assertTrue(report["owned"][-1]["forced_kill_attempted"])
            self.assertEqual(report["closes"][-1]["status"], "CANONICAL_CLOSE_FAILED")

    def test_setup_failure_does_not_reach_picker_and_reaps_the_only_child(self):
        with tempfile.TemporaryDirectory() as directory:
            s, native, report, save = self.run_case(directory, setup_error=True)
            with self.assertRaisesRegex(AssertionError, "native viewer window"):
                observer.observe(s, native, report, lambda: save(report))
            self.assertEqual(report["oracle"], "NOT_REACHED")
            self.assertEqual(report["posts"], [])
            self.assertEqual(len(s.children), 1)
            self.assertTrue(report["terminal"])

    def test_observer_error_cannot_be_reported_as_valid_diagnostic(self):
        with tempfile.TemporaryDirectory() as directory:
            s, native, report, save = self.run_case(directory)
            native.broken = True
            with self.assertRaisesRegex(RuntimeError, "diagnostic invalid"):
                observer.observe(s, native, report, lambda: save(report))
            self.assertEqual(report["oracle"], "PASS_DIAGNOSTIC_ONLY")
            self.assertEqual(report["status"], "PICKER_DIAGNOSTIC_FAILURE_PRESERVED")
            self.assertTrue(report["observation_errors"])

    def add_query_state(self, native, changes, destroyed=False):
        snapshot = native.snapshot

        def changed(*args):
            row = snapshot(*args)
            state = {"hwnd": 123, "exists": True, "exists_after": True, "owned": True,
                     "pid_query_error": None, "title_query_error": 0, "class_query_error": 0,
                     "gui": {"ok": True, "error": None}}
            if destroyed:
                state["hwnd"] = row["target"]["hwnd"]
                if not row["target"]["exists"]:
                    state.update(changes, exists=False, exists_after=False, owned=False)
            else:
                state.update(changes)
            row["main" if not destroyed else "target"] = state
            return row

        native.snapshot = changed

    def test_failed_live_native_queries_invalidate_diagnostic(self):
        failures = ({"gui": {"ok": False, "error": 5}}, {"title_query_error": 5},
                    {"class_query_error": 5}, {"pid_query_error": 5, "owned": False}, {"owned": False})
        for failure in failures:
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as directory:
                s, native, report, save = self.run_case(directory)
                self.add_query_state(native, failure)
                with self.assertRaisesRegex(RuntimeError, "diagnostic invalid"):
                    observer.observe(s, native, report, lambda: save(report))
                self.assertEqual(report["oracle"], "PASS_DIAGNOSTIC_ONLY")
                self.assertTrue(report["observation_errors"])
                self.assertTrue(report["terminal"])

    def test_destroyed_picker_query_failure_is_expected(self):
        with tempfile.TemporaryDirectory() as directory:
            s, native, report, save = self.run_case(directory)
            self.add_query_state(native, {"pid_query_error": 1400}, destroyed=True)
            observer.observe(s, native, report, lambda: save(report))
            self.assertEqual(report["status"], "PICKER_OBSERVED_DIAGNOSTIC_ONLY")
            self.assertFalse(report["observation_errors"])
            before = next(row for row in report["samples"] if row["phase"] == "before_post")
            self.assertTrue(before["target"]["exists"] and before["target"]["owned"])
            self.assertFalse(report["samples"][-1]["target"]["exists"])
            self.assertEqual(report["samples"][-1]["target"]["pid_query_error"], 1400)
            self.assertEqual(len(report["posts"]), 1)

    def test_live_query_failure_does_not_mask_original_timeout(self):
        with tempfile.TemporaryDirectory() as directory:
            s, native, report, save = self.run_case(directory, residual=True)
            self.add_query_state(native, {"gui": {"ok": False, "error": 5}})
            with self.assertRaisesRegex(AssertionError, "Timed out: file picker cancellation"):
                observer.observe(s, native, report, lambda: save(report))
            self.assertEqual(report["oracle"], "FAIL")
            self.assertTrue(report["observation_errors"])
            self.assertTrue(report["terminal"])

    def test_second_close_post_is_rejected_before_sending(self):
        with tempfile.TemporaryDirectory() as directory:
            s, native, report, save = self.run_case(directory, duplicate=True)
            with self.assertRaisesRegex(AssertionError, "more than one picker-close"):
                observer.observe(s, native, report, lambda: save(report))
            self.assertEqual([item for item in s.sent if item[0] == 81], [(81, 0x10)])
            self.assertTrue(report["terminal"])

    def test_lost_window_ownership_prevents_picker_close_post(self):
        with tempfile.TemporaryDirectory() as directory:
            s, native, report, save = self.run_case(directory)
            original_owned = native.owned
            native.owned = lambda process, hwnd: original_owned(process, hwnd) and hwnd != 81
            with self.assertRaisesRegex(AssertionError, "picker HWND ownership lost"):
                observer.observe(s, native, report, lambda: save(report))
            self.assertFalse(any(hwnd == 81 for hwnd, _ in s.sent))
            self.assertEqual(report["posts"], [])
            self.assertTrue(report["terminal"])

    def test_process_disappearance_cannot_be_a_valid_picker_diagnostic(self):
        with tempfile.TemporaryDirectory() as directory:
            s, native, report, save = self.run_case(directory)
            post = s.post

            def exits_instead_of_cancel(*args):
                result = post(*args)
                s.children[-1].code = 0
                return result

            s.post = exits_instead_of_cancel
            with self.assertRaisesRegex(RuntimeError, "diagnostic invalid"):
                observer.observe(s, native, report, lambda: save(report))
            self.assertEqual(report["oracle"], "PASS_DIAGNOSTIC_ONLY")
            self.assertFalse(report["viewer_alive_at_oracle_end"])
            self.assertEqual(report["closes"][-1]["status"], "SKIPPED_ALREADY_TERMINAL")
            self.assertEqual(report["status"], "PICKER_DIAGNOSTIC_FAILURE_PRESERVED")

    def test_lost_owner_window_skips_canonical_close_and_reaps_owned_child(self):
        with tempfile.TemporaryDirectory() as directory:
            s, native, report, save = self.run_case(directory)
            native.ownership = False
            with self.assertRaisesRegex(AssertionError, "owner HWND ownership lost"):
                observer.observe(s, native, report, lambda: save(report))
            self.assertEqual(s.sent, [])
            self.assertTrue(report["owned"][0]["forced_kill_attempted"])
            self.assertTrue(report["terminal"])

    def test_snapshot_marks_exit_during_collection_and_avoids_terminal_pid_queries(self):
        native = object.__new__(observer.Native)
        native.s = types.SimpleNamespace(windows=mock.Mock(return_value=[]))
        native.foreground = lambda: 0
        native.state = lambda hwnd, pid: {"hwnd": hwnd}
        process = types.SimpleNamespace(pid=123, poll=mock.Mock(side_effect=[None, 0]))
        row = native.snapshot(process, 10, 20, None)
        self.assertFalse(row["process_stable"])
        self.assertIsNone(row["process_exit_start"])
        self.assertEqual(row["process_exit_end"], 0)
        native.s.windows.reset_mock()
        process.poll = lambda: 0
        row = native.snapshot(process, 10, 20, None)
        native.s.windows.assert_not_called()
        self.assertIsNone(row["main"])
        self.assertIsNone(row["target"])

    def test_initial_report_failure_reaps_child_even_before_launch_returns(self):
        with tempfile.TemporaryDirectory() as directory:
            s, native, report, _ = self.run_case(directory)

            def broken_save():
                raise OSError("initial report failure")

            with self.assertRaisesRegex(OSError, "initial report failure"):
                observer.observe(s, native, report, broken_save)
            self.assertEqual(len(s.children), 1)
            self.assertTrue(report["terminal"])
            self.assertTrue(report["owned"][0]["forced_kill_attempted"])


if __name__ == "__main__":
    unittest.main()
