# SPDX-License-Identifier: GPL-3.0-or-later
"""Portable path/build checks and simulated worker failure controls; no native child."""
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock

import calibrate_decoder as runner
import decoder_calibration
from decoder_calibration import supervisor


class PortableWiringTests(unittest.TestCase):
    def test_fixed_raw_paths_across_ascii_bmp_supplementary_and_space_roots(self):
        for base in [r"C:\cal", "C:\\folder with spaces\\café\\猫", "C:\\🧪\\cal"]:
            with self.subTest(base=base):
                paths, short = runner.raw_paths(base)
                self.assertEqual([len(p.encode("utf-16le")) // 2 for p in paths.values()], [360, 364, 287])
                self.assertEqual(paths["long-verbatim"], "\\\\?\\" + paths["long-normal"])
                self.assertIn("\\.\\", paths["long-normalizes-short"])
                self.assertLess(len(short.encode("utf-16le")) // 2, 260)
                self.assertTrue(paths["long-normalizes-short"].endswith(short.rsplit("\\", 1)[1]))

    def test_unsupported_arguments_fail_before_any_process_or_filesystem_use(self):
        for text in ["\0file", "fi\0le", "file\0", "\ud800", "a\udfffz"]:
            with self.subTest(text=repr(text)):
                with self.assertRaises((AssertionError, UnicodeEncodeError)):
                    runner.utf16_hex(text)
        self.assertEqual(runner.utf16_hex("A🧪"), "41003ed8eadd")
        with self.assertRaises(AssertionError):
            runner.utf16_hex(Path("file"))

    def test_probe_substitution_requires_one_attribute_and_preserves_comment(self):
        template = b'// __DECODE__ stays here\n#[path = "__DECODE__"]\nmod decode;\n'
        result = runner.stage_probe(template, Path("C:/synthetic/decode.rs"))
        self.assertEqual(result, b'// __DECODE__ stays here\n#[path = "C:/synthetic/decode.rs"]\nmod decode;\n')
        for broken in [b"// __DECODE__", template + template]:
            with self.assertRaises(AssertionError):
                runner.stage_probe(broken, Path("C:/synthetic/decode.rs"))

    def test_independently_authored_complete_pixel_reference(self):
        pixels = runner.expected_pixels()
        self.assertEqual(len(pixels), 12288)
        self.assertEqual(hashlib.sha256(pixels).hexdigest(),
                         "33e9b5b811e2c42b2586f2a341cf489e004d0a965e8371edf567c32fb048e65e")
        for x, y, expected in [(0, 0, b"\0\0\xff\xff"), (63, 0, b"\0\xff\0\xff"),
                               (0, 47, b"\xff\0\0\xff"), (63, 47, b"\0\xff\xff\xff")]:
            offset = (y * 64 + x) * 4
            self.assertEqual(pixels[offset:offset + 4], expected)

    def test_build_timeout_keeps_primary_and_records_cleanup_error(self):
        primary = subprocess.TimeoutExpired(["simulated-build"], 1200)

        class Child:
            pid = 123
            calls = 0

            def wait(self, timeout):
                self.calls += 1
                if self.calls == 1:
                    raise primary
                return -9

            def kill(self):
                raise OSError("simulated kill failure")

            def poll(self):
                return -9

        with tempfile.TemporaryDirectory() as directory:
            report = {}
            with mock.patch.object(supervisor.subprocess, "Popen", return_value=Child()):
                with self.assertRaises(subprocess.TimeoutExpired) as caught:
                    supervisor.run_build(["simulated-build"], Path(directory), {},
                                         Path(directory) / "build.log", report, lambda: None)
            self.assertIs(caught.exception, primary)
            self.assertTrue(report["build"]["terminal"])
            self.assertIsNone(report["build"]["pid"])
            self.assertIn("simulated kill failure", str(report["build"]["cleanup_errors"]))
            self.assertIn("simulated kill failure", str(primary.__notes__))

    def test_setup_process_uses_its_separate_sixty_second_bound(self):
        child = types.SimpleNamespace(pid=789, wait=mock.Mock(return_value=0))
        with tempfile.TemporaryDirectory() as directory:
            report = {}
            with mock.patch.object(supervisor.subprocess, "Popen", return_value=child):
                supervisor.run_build(["simulated-setup"], Path(directory), {},
                                     Path(directory) / "setup.log", report, lambda: None, timeout=60)
            child.wait.assert_called_once_with(timeout=60)
            self.assertEqual(report["build"]["exit_code"], 0)
            self.assertTrue(report["build"]["terminal"])


class SimulatedWorkerTests(unittest.TestCase):
    def test_monitor_failure_restores_hooks_and_environment_and_rejects_cleanup(self):
        resources = lambda process: {}
        cpu = lambda process: 1.0
        popen = lambda *args, **kwargs: types.SimpleNamespace(_handle=123)
        support = types.SimpleNamespace(resources=resources, s=types.SimpleNamespace(cpu_ms=cpu))
        worker = types.SimpleNamespace(t=support, subprocess=types.SimpleNamespace(Popen=popen))

        def sample(exe, image, output):
            output.mkdir()
            process = worker.subprocess.Popen()
            worker.t.resources(process)

        worker.sample = sample

        class ImmediateThread:
            def __init__(self, target, daemon):
                self.target = target

            def start(self):
                self.target()

            def join(self, timeout):
                pass

            def is_alive(self):
                return False

        native = types.SimpleNamespace(snapshot=mock.Mock(side_effect=OSError("simulated counter failure")))
        path = Path(__file__).parent / "decoder_calibration/measure.py"
        spec = importlib.util.spec_from_file_location("decoder_calibration._simulated_measure", path)
        measure = importlib.util.module_from_spec(spec)
        with mock.patch.dict(sys.modules, {"decoder_calibration.worker": worker, "decoder_calibration.native": native}), \
             mock.patch.object(decoder_calibration, "worker", worker, create=True), \
             mock.patch.object(decoder_calibration, "native", native, create=True):
            spec.loader.exec_module(measure)
        with tempfile.TemporaryDirectory() as directory, \
             mock.patch.dict(os.environ, {"FOTO_E057_INNER": "prior", "FOTO_E057_CORRUPT": "prior"}), \
             mock.patch.object(measure.threading, "Thread", ImmediateThread):
            before = dict(os.environ)
            output = Path(directory) / "result"
            with self.assertRaisesRegex(AssertionError, "simulated counter failure"):
                measure.sample(None, None, output, 512)
            self.assertEqual(dict(os.environ), before)
            self.assertIs(worker.t.resources, resources)
            self.assertIs(worker.t.s.cpu_ms, cpu)
            self.assertIs(worker.subprocess.Popen, popen)
            with self.assertRaisesRegex(AssertionError, "monitor sample errors"):
                supervisor.cleanup_report(output)

    def test_payload_failure_preserves_primary_cleanup_notes_and_terminal_report(self):
        class BrokenClose(io.BytesIO):
            def close(self):
                raise OSError("simulated stdout close failure")

        class Child:
            pid = 456
            returncode = 0

            def __init__(self, payload):
                self.stdin = io.BytesIO()
                self.stdout = BrokenClose(b"DECODE 2 1 2 1 8 1000000\n" + payload)
                self.stderr = io.BytesIO()

            def poll(self):
                return 0

            def wait(self, timeout):
                return 0

        support = types.SimpleNamespace(resources=lambda child: {"simulated": True},
                                        s=types.SimpleNamespace(cpu_ms=lambda child: 1.0))
        path = Path(__file__).parent / "decoder_calibration/worker.py"
        spec = importlib.util.spec_from_file_location("decoder_calibration._simulated_worker", path)
        worker = importlib.util.module_from_spec(spec)
        with mock.patch.dict(sys.modules, {"stress_test": support}):
            spec.loader.exec_module(worker)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            exe, image = root / "simulated.exe", root / "input.bin"
            exe.write_bytes(b"not executed")
            image.write_bytes(b"not decoded")
            child = Child(b"1234567")
            with mock.patch.object(worker.subprocess, "Popen", return_value=child), \
                 mock.patch.object(worker.subprocess, "CREATE_NO_WINDOW", 0, create=True):
                with self.assertRaisesRegex(AssertionError, "pixel payload ended early") as caught:
                    worker.sample(exe, str(image), root / "result")
            report = json.loads((root / "result/report.json").read_text())
            self.assertEqual(report["verdict"], "MEASUREMENT_FAILED")
            self.assertTrue(report["child_cleanup_terminal"])
            self.assertTrue(report["reader_cleanup_terminal"])
            self.assertIn("simulated stdout close failure", str(report["cleanup_errors"]))
            self.assertIn("simulated stdout close failure", str(caught.exception.__notes__))
            io.BytesIO.close(child.stdout)


if __name__ == "__main__":
    unittest.main()
