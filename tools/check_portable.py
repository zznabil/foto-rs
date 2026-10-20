# SPDX-License-Identifier: GPL-3.0-or-later
"""Verify a Windows x64 GUI executable imports only Windows system libraries."""
import hashlib
from pathlib import Path
import struct
import sys


def check(path):
    data = path.read_bytes()
    assert data[:2] == b"MZ", "Not a PE executable"
    header = struct.unpack_from("<I", data, 0x3C)[0]
    assert data[header:header+4] == b"PE\0\0", "Invalid PE signature"
    assert struct.unpack_from("<H", data, header+4)[0] == 0x8664, "Expected x64"
    count = struct.unpack_from("<H", data, header+6)[0]
    optional = header+24
    optional_size = struct.unpack_from("<H", data, header+20)[0]
    assert struct.unpack_from("<H", data, optional)[0] == 0x20B, "Expected PE32+"
    assert struct.unpack_from("<H", data, optional+68)[0] == 2, "Expected Windows GUI subsystem"
    sections = [struct.unpack_from("<8sIIII", data, optional+optional_size+i*40) for i in range(count)]

    def offset(address):
        for _, size, virtual, raw_size, raw in sections:
            if virtual <= address < virtual+max(size, raw_size):
                return raw+address-virtual
        raise AssertionError(f"Unmapped import address {address:#x}")

    imports = offset(struct.unpack_from("<I", data, optional+112+8)[0])
    libraries = []
    while any(data[imports:imports+20]):
        name = offset(struct.unpack_from("<I", data, imports+12)[0])
        libraries.append(data[name:data.index(0, name)].decode("ascii"))
        imports += 20
    system = {"advapi32.dll", "bcrypt.dll", "comdlg32.dll", "d2d1.dll", "dwrite.dll", "dwmapi.dll",
              "gdi32.dll", "kernel32.dll", "ntdll.dll", "ole32.dll", "oleaut32.dll", "propsys.dll",
              "rpcrt4.dll", "shell32.dll", "shlwapi.dll", "user32.dll", "userenv.dll", "ws2_32.dll"}
    unexpected = [name for name in libraries if name.lower() not in system
                  and not name.lower().startswith("api-ms-win-")]
    assert not unexpected, f"Non-system runtime dependencies: {unexpected}"
    print(f"Executable: {path}")
    print(f"Bytes: {len(data)}")
    print(f"SHA256: {hashlib.sha256(data).hexdigest()}")
    print(f"System libraries: {', '.join(libraries)}")
    print("PORTABLE_DEPENDENCIES_PASS")


if __name__ == "__main__":
    check(Path(sys.argv[1]) if len(sys.argv) > 1 else Path("dist/foto.exe"))
