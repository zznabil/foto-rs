# SPDX-License-Identifier: GPL-3.0-or-later
"""Exercise the portable dependency gate with non-executed PE data fixtures."""

from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest


CHECKER = Path(__file__).with_name("check_portable.py")


def pe_import_fixture(libraries):
    """Build only the PE headers and import names consumed by the checker."""
    data = bytearray(1024)
    header, optional, raw, virtual = 0x80, 0x98, 0x200, 0x1000
    data[:2] = b"MZ"
    struct.pack_into("<I", data, 0x3C, header)
    data[header : header + 4] = b"PE\0\0"
    struct.pack_into("<HH", data, header + 4, 0x8664, 1)
    struct.pack_into("<H", data, header + 20, 240)
    struct.pack_into("<H", data, optional, 0x20B)
    struct.pack_into("<H", data, optional + 68, 2)
    struct.pack_into("<II", data, optional + 120, virtual, 20 * (len(libraries) + 1))
    struct.pack_into(
        "<8sIIII", data, optional + 240, b".rdata\0\0", 512, virtual, 512, raw
    )
    cursor = raw + 20 * (len(libraries) + 1)
    for index, library in enumerate(libraries):
        name = library.encode("ascii") + b"\0"
        struct.pack_into("<I", data, raw + index * 20 + 12, virtual + cursor - raw)
        data[cursor : cursor + len(name)] = name
        cursor += len(name)
    return data


class PortableDependencyControls(unittest.TestCase):
    def run_checker(self, libraries):
        with tempfile.TemporaryDirectory() as directory:
            fixture = Path(directory) / "imports.bin"
            fixture.write_bytes(pe_import_fixture(libraries))
            return subprocess.run(
                [sys.executable, str(CHECKER), str(fixture)],
                capture_output=True,
                text=True,
                timeout=15,
            )

    def test_windows_combase_is_a_system_dependency(self):
        result = self.run_checker(["KERNEL32.dll", "COMBASE.dll"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("PORTABLE_DEPENDENCIES_PASS", result.stdout)

    def test_third_party_runtime_still_fails_with_system_dependencies(self):
        result = self.run_checker(["KERNEL32.dll", "VCRUNTIME140.dll"])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("VCRUNTIME140.dll", result.stderr)
        self.assertNotIn("PORTABLE_DEPENDENCIES_PASS", result.stdout)


if __name__ == "__main__":
    unittest.main()
