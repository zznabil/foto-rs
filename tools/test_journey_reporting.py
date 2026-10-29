# SPDX-License-Identifier: GPL-3.0-or-later
"""Portable checks for journey failure reporting.

The production helpers load WinDLLs at module import time, so these tests
extract only the unchanged helper definitions with ``ast`` and execute them
against deterministic fakes.  This keeps the reporting checks runnable on a
non-Windows test host without replacing the code under test.
"""
import ast
import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import time
import traceback
import unittest


ROOT = Path(__file__).resolve().parents[1]


def load_definitions(path, names, namespace):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    nodes = [node for node in tree.body
             if isinstance(node, (ast.ClassDef, ast.FunctionDef)) and node.name in names]
    assert {node.name for node in nodes} == set(names), (path, names)
    module = ast.Module(body=nodes, type_ignores=[])
    ast.fix_missing_locations(module)
    exec(compile(module, str(path), "exec"), namespace)
    return namespace


class FakePost:
    def __init__(self):
        self.calls = []

    def __call__(self, hwnd, message, wparam, lparam):
        self.calls.append((hwnd, message, wparam, lparam))


class FakeProcess:
    def __init__(self, exit_code=0, timeout=False, poll_code=None):
        self.exit_code = exit_code
        self.timeout = timeout
        self.poll_code = poll_code
        self.poll_calls = 0
        self.wait_calls = []
        self.kill_calls = 0

    def poll(self):
        self.poll_calls += 1
        return self.poll_code

    def wait(self, timeout=None):
        self.wait_calls.append(timeout)
        if self.timeout:
            raise subprocess.TimeoutExpired(["foto"], timeout)
        return self.exit_code

    def kill(self):
        self.kill_calls += 1


class JourneyReportingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        smoke_namespace = {
            "__name__": "portable_smoke_helpers",
            "post": None,
            "subprocess": subprocess,
        }
        load_definitions(ROOT / "tools/smoke_test.py", {"close"}, smoke_namespace)
        cls.smoke_namespace = smoke_namespace
        cls.smoke_close = smoke_namespace["close"]

        service = SimpleNamespace(close=cls.smoke_close)
        stress_namespace = {
            "__name__": "portable_stress_helpers",
            "s": service,
            "sys": sys,
            "time": time,
            "traceback": traceback,
            "json": json,
        }
        load_definitions(ROOT / "tools/stress_test.py", {"Session", "Suite"}, stress_namespace)
        cls.session_type = stress_namespace["Session"]
        cls.suite_type = stress_namespace["Suite"]

    def setUp(self):
        self.post = FakePost()
        self.smoke_namespace["post"] = self.post
        self.suite = self.suite_type.__new__(self.suite_type)
        self.suite.sessions = []
        self.suite.results = []
        self.suite.metrics = {}
        self.saved_reports = []
        self.suite.save = lambda: self.saved_reports.append(
            json.loads(json.dumps(self.suite.results))
        )

    def add_session(self, exit_code=0, timeout=False, poll_code=None, name="session.csv"):
        process = FakeProcess(exit_code, timeout, poll_code)
        session = self.session_type.__new__(self.session_type)
        session.process = process
        session.hwnd = 91
        session.suite = self.suite
        session.log = Path(name)
        self.suite.sessions.append(session)
        return session, process

    def run_case(self, name, function):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.suite.case(name, function)
        self.assertEqual(len(self.saved_reports), 1)
        self.assertEqual(len(self.suite.results), 1)
        printed = json.loads(output.getvalue())
        self.assertEqual(printed, self.suite.results[-1])
        return self.suite.results[-1]

    def test_clean_pass_is_saved_after_successful_cleanup(self):
        session, process = self.add_session()
        result = self.run_case("clean", lambda: None)
        self.assertEqual(result["verdict"], "PASS")
        self.assertEqual(process.wait_calls, [4])
        self.assertEqual(self.suite.sessions, [])
        self.assertEqual(self.post.calls, [(91, 0x10, 0, 0)])
        self.assertNotIn("cleanup_errors", result)
        self.assertEqual(process.poll_calls, 1)

    def test_body_only_failure_retains_body_error_and_saves(self):
        self.add_session()

        def body():
            raise ValueError("body failure")

        result = self.run_case("body-only", body)
        self.assertEqual(result["verdict"], "FAIL")
        self.assertEqual(result["error"], "ValueError: body failure")
        self.assertEqual(result["body_error"]["message"], "body failure")
        self.assertEqual(result["cleanup_errors"], [])
        self.assertEqual(self.suite.sessions, [])

    def test_cleanup_only_failure_retains_exact_nonzero_exit_code(self):
        self.add_session(exit_code=0xC0000005)
        result = self.run_case("cleanup-only", lambda: None)
        self.assertEqual(result["verdict"], "FAIL")
        self.assertIsNone(result["body_error"])
        self.assertEqual(len(result["cleanup_errors"]), 1)
        cleanup = result["cleanup_errors"][0]
        self.assertEqual(cleanup["session"], "session.csv")
        self.assertIn(str(0xC0000005), cleanup["message"])
        self.assertIn("cleanup: AssertionError:", result["error"])
        self.assertEqual(self.suite.sessions, [])

    def test_body_and_cleanup_failures_are_saved_together(self):
        self.add_session(exit_code=23)

        def body():
            raise RuntimeError("body failure")

        result = self.run_case("body-and-cleanup", body)
        self.assertEqual(result["verdict"], "FAIL")
        self.assertEqual(result["body_error"]["type"], "RuntimeError")
        self.assertEqual(result["body_error"]["message"], "body failure")
        self.assertEqual(len(result["cleanup_errors"]), 1)
        self.assertIn("RuntimeError: body failure", result["error"])
        self.assertIn("cleanup: AssertionError:", result["error"])
        self.assertEqual(self.suite.sessions, [])

    def test_inline_cleanup_cannot_replace_the_original_journey_failure(self):
        session, _ = self.add_session(exit_code=23)

        def body():
            try:
                raise ValueError("original image assertion")
            finally:
                session.close()

        result = self.run_case("inline-cleanup", body)
        self.assertEqual(result["verdict"], "FAIL")
        self.assertEqual(result["body_error"]["type"], "ValueError")
        self.assertEqual(result["body_error"]["message"], "original image assertion")
        self.assertEqual(len(result["cleanup_errors"]), 1)
        self.assertIn("code 23", result["cleanup_errors"][0]["message"])
        self.assertEqual(self.suite.sessions, [])

    def test_all_cleanup_attempts_run_after_one_failure(self):
        sessions = [self.add_session(exit_code=code, name=f"session-{code}.csv")
                    for code in (7, 0, 9)]
        result = self.run_case("multiple-cleanups", lambda: None)
        self.assertEqual(result["verdict"], "FAIL")
        self.assertEqual(len(result["cleanup_errors"]), 2)
        self.assertEqual([process.wait_calls for _, process in sessions], [[4], [4], [4]])
        self.assertEqual(self.suite.sessions, [])

    def test_nonzero_exit_is_an_actionable_direct_close_failure(self):
        process = FakeProcess(exit_code=37)
        with self.assertRaisesRegex(AssertionError, r"code 37"):
            type(self).smoke_close(process, 91)
        self.assertEqual(process.wait_calls, [4])
        self.assertEqual(process.kill_calls, 0)
        self.assertEqual(self.post.calls, [(91, 0x10, 0, 0)])

    def test_timeout_remains_a_single_failure_with_kill(self):
        process = FakeProcess(timeout=True)
        with self.assertRaisesRegex(AssertionError, "Viewer did not close promptly"):
            type(self).smoke_close(process, 91)
        self.assertEqual(process.wait_calls, [4])
        self.assertEqual(process.kill_calls, 1)
        self.assertEqual(self.post.calls, [(91, 0x10, 0, 0)])

    def test_already_exited_success_is_waited_without_posting(self):
        _, process = self.add_session(poll_code=0)
        result = self.run_case("already-exited-success", lambda: None)
        self.assertEqual(result["verdict"], "PASS")
        self.assertEqual(process.poll_calls, 1)
        self.assertEqual(process.wait_calls, [4])
        self.assertEqual(self.post.calls, [])
        self.assertEqual(self.suite.sessions, [])

    def test_already_exited_failure_is_reported_without_posting(self):
        _, process = self.add_session(exit_code=37, poll_code=37)
        result = self.run_case("already-exited-failure", lambda: None)
        self.assertEqual(result["verdict"], "FAIL")
        self.assertIn("code 37", result["cleanup_errors"][0]["message"])
        self.assertEqual(process.poll_calls, 1)
        self.assertEqual(process.wait_calls, [4])
        self.assertEqual(self.post.calls, [])
        self.assertEqual(self.suite.sessions, [])

    def test_keyboard_interrupt_runs_cleanup_then_propagates(self):
        _, process = self.add_session()

        def body():
            raise KeyboardInterrupt()

        with self.assertRaises(KeyboardInterrupt):
            self.suite.case("keyboard-interrupt", body)
        self.assertEqual(process.wait_calls, [4])
        self.assertEqual(self.post.calls, [(91, 0x10, 0, 0)])
        self.assertEqual(self.suite.sessions, [])
        self.assertEqual(self.suite.results, [])
        self.assertEqual(self.saved_reports, [])


if __name__ == "__main__":
    unittest.main()
