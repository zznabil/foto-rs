# SPDX-License-Identifier: GPL-3.0-or-later
"""Check fullscreen readiness across separate style and geometry observations."""

from pathlib import Path
from types import SimpleNamespace
import unittest
from test_journey_reporting import load_definitions


ROOT = Path(__file__).resolve().parents[1]
MONITOR = (0, 0, 2880, 1620)
MAXIMISED = (-8, -8, 2888, 1580)


class FullscreenReadinessTests(unittest.TestCase):
    def setUp(self):
        self.elapsed = 0.0
        self.style = 0
        self.bounds = MAXIMISED
        self.transition = lambda: None
        clock = SimpleNamespace(monotonic=lambda: self.elapsed, sleep=self.advance)
        smoke = load_definitions(
            ROOT / "tools/smoke_test.py", {"wait"}, {"time": clock}
        )
        service = SimpleNamespace(
            wait=smoke["wait"],
            get_style=lambda hwnd, index: self.style,
        )
        stress = load_definitions(
            ROOT / "tools/stress_test.py",
            {"_wait_fullscreen"},
            {"s": service, "rect": lambda hwnd: self.bounds},
        )
        self.wait_fullscreen = stress["_wait_fullscreen"]

    def advance(self, seconds):
        self.elapsed += seconds
        self.transition()

    def test_style_change_does_not_finish_before_monitor_bounds(self):
        def finish_position():
            if self.elapsed >= 0.03:
                self.bounds = MONITOR

        self.transition = finish_position
        self.wait_fullscreen(1, MONITOR)
        self.assertEqual(self.bounds, MONITOR)

    def test_permanently_wrong_bounds_still_fail(self):
        with self.assertRaises(AssertionError):
            self.wait_fullscreen(1, MONITOR)

    def test_matching_bounds_with_a_caption_still_fail(self):
        self.style = 0xC00000
        self.bounds = MONITOR
        with self.assertRaises(AssertionError):
            self.wait_fullscreen(1, MONITOR)


if __name__ == "__main__":
    unittest.main()
