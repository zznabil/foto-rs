# SPDX-License-Identifier: GPL-3.0-or-later
"""Check picker selection against real, non-activating Win32 dialog states."""

import os
import struct
import sys
import unittest

if sys.platform == "win32":
    import smoke_test as s


@unittest.skipUnless(sys.platform == "win32", "Native Windows dialog controls")
class PickerReadinessTests(unittest.TestCase):
    def setUp(self):
        c, w = s.C, s.W
        self.create_window = s.api(
            s.user,
            "CreateWindowExW",
            w.HWND,
            w.DWORD,
            w.LPCWSTR,
            w.LPCWSTR,
            w.DWORD,
            c.c_int,
            c.c_int,
            c.c_int,
            c.c_int,
            w.HWND,
            w.HMENU,
            w.HINSTANCE,
            c.c_void_p,
        )
        self.create_dialog = s.api(
            s.user,
            "CreateDialogIndirectParamW",
            w.HWND,
            w.HINSTANCE,
            c.c_void_p,
            w.HWND,
            c.c_void_p,
            w.LPARAM,
        )
        self.show = s.api(s.user, "ShowWindow", w.BOOL, w.HWND, c.c_int)
        self.enable = s.api(s.user, "EnableWindow", w.BOOL, w.HWND, w.BOOL)
        self.set_title = s.api(s.user, "SetWindowTextW", w.BOOL, w.HWND, w.LPCWSTR)
        self.destroy = s.api(s.user, "DestroyWindow", w.BOOL, w.HWND)
        self.exists = s.api(s.user, "IsWindow", w.BOOL, w.HWND)
        callback_type = c.WINFUNCTYPE(c.c_ssize_t, w.HWND, w.UINT, w.WPARAM, w.LPARAM)
        self.callback = callback_type(lambda hwnd, message, wp, lp: 0)
        self.owned = []
        self.addCleanup(self.close_windows)
        self.owner = self.window("STATIC", "picker readiness owner", 0, None, None)
        self.other_owner = self.window("STATIC", "other owner", 0, None, None)

    def window(self, window_class, title, style, parent, control):
        hwnd = self.create_window(
            0x08000080,
            window_class,
            title,
            style,
            -32000,
            -32000,
            8,
            8,
            parent,
            control,
            None,
            None,
        )
        self.assertTrue(hwnd, f"Native {window_class} creation failed")
        self.owned.append(hwnd)
        return hwnd

    def dialog(self, owner=None, title="Open a photo", cancel=True):
        template = s.C.create_string_buffer(
            struct.pack(
                "<IIHhhhhHHH", 0x80C00000, 0x08000080, 0, -32000, -32000, 8, 8, 0, 0, 0
            )
        )
        hwnd = self.create_dialog(None, template, owner or self.owner, self.callback, 0)
        self.assertTrue(hwnd, "Native modeless dialog creation failed")
        self.owned.append(hwnd)
        self.assertTrue(self.set_title(hwnd, title))
        button = (
            self.window("BUTTON", "Cancel", 0x50000000, hwnd, 2) if cancel else None
        )
        return hwnd, button

    def close_windows(self):
        for hwnd in reversed(self.owned):
            if self.exists(hwnd):
                self.assertTrue(self.destroy(hwnd), "Native fixture cleanup failed")
        self.assertTrue(all(not self.exists(hwnd) for hwnd in self.owned))

    def test_hidden_disabled_and_incomplete_dialogs_are_not_ready(self):
        dialog, cancel = self.dialog()
        # Positive enumeration control: the old broad selector already finds this hidden HWND.
        self.assertIn(dialog, s.windows(os.getpid(), "#32770"))
        self.assertIsNone(s.file_picker(os.getpid(), self.owner))
        self.show(dialog, 4)
        self.assertEqual(s.file_picker(os.getpid(), self.owner), dialog)
        self.enable(cancel, False)
        self.assertIsNone(s.file_picker(os.getpid(), self.owner))
        self.enable(cancel, True)
        self.enable(dialog, False)
        self.assertIsNone(s.file_picker(os.getpid(), self.owner))
        self.enable(dialog, True)
        self.show(cancel, 0)
        self.assertIsNone(s.file_picker(os.getpid(), self.owner))
        self.show(cancel, 4)
        self.assertEqual(s.file_picker(os.getpid(), self.owner), dialog)
        self.assertTrue(self.destroy(cancel))
        self.assertIsNone(s.file_picker(os.getpid(), self.owner))

    def test_other_owner_title_or_process_cannot_supply_the_picker(self):
        dialog, _ = self.dialog()
        self.show(dialog, 4)
        self.assertEqual(s.file_picker(os.getpid(), self.owner), dialog)
        self.assertIsNone(s.file_picker(os.getpid(), self.other_owner))
        self.assertIsNone(s.file_picker(0, self.owner))
        self.assertTrue(self.set_title(dialog, "Unrelated message"))
        self.assertIsNone(s.file_picker(os.getpid(), self.owner))

    def test_multiple_ready_pickers_fail_instead_of_choosing_arbitrarily(self):
        first, _ = self.dialog()
        second, _ = self.dialog()
        self.show(first, 4)
        self.show(second, 4)
        with self.assertRaisesRegex(AssertionError, "More than one ready file picker"):
            s.file_picker(os.getpid(), self.owner)


if __name__ == "__main__":
    unittest.main()
