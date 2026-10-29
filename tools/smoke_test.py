# SPDX-License-Identifier: GPL-3.0-or-later
"""Exercise the real Windows executable and write measured timings. Uses only Python's standard library."""
import argparse
from timing_log import rows
from contextlib import contextmanager
import ctypes as C
from ctypes import wintypes as W
import hashlib
import json
import os
from pathlib import Path
import statistics
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
user = C.WinDLL("user32", use_last_error=True)
kernel = C.WinDLL("kernel32", use_last_error=True)
gdi = C.WinDLL("gdi32", use_last_error=True)
CALLBACK = C.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)


def api(dll, name, restype, *args):
    fn = getattr(dll, name)
    fn.restype, fn.argtypes = restype, args
    return fn


enum_windows = api(user, "EnumWindows", W.BOOL, CALLBACK, W.LPARAM)
get_pid = api(user, "GetWindowThreadProcessId", W.DWORD, W.HWND, C.POINTER(W.DWORD))
get_title = api(user, "GetWindowTextW", C.c_int, W.HWND, W.LPWSTR, C.c_int)
get_class = api(user, "GetClassNameW", C.c_int, W.HWND, W.LPWSTR, C.c_int)
post = api(user, "PostMessageW", W.BOOL, W.HWND, W.UINT, W.WPARAM, W.LPARAM)
get_item = api(user, "GetDlgItem", W.HWND, W.HWND, C.c_int)
enabled = api(user, "IsWindowEnabled", W.BOOL, W.HWND)
visible = api(user, "IsWindowVisible", W.BOOL, W.HWND)
owner_window = api(user, "GetWindow", W.HWND, W.HWND, W.UINT)
get_rect = api(user, "GetClientRect", W.BOOL, W.HWND, C.POINTER(W.RECT))
get_window_rect = api(user, "GetWindowRect", W.BOOL, W.HWND, C.POINTER(W.RECT))
get_style = api(user, "GetWindowLongPtrW", C.c_ssize_t, W.HWND, C.c_int)
set_pos = api(user, "SetWindowPos", W.BOOL, W.HWND, W.HWND, C.c_int, C.c_int, C.c_int, C.c_int, W.UINT)
get_dpi = api(user, "GetDpiForWindow", W.UINT, W.HWND)
to_screen = api(user, "ClientToScreen", W.BOOL, W.HWND, C.POINTER(W.POINT))
get_dc = api(user, "GetDC", W.HDC, W.HWND)
release_dc = api(user, "ReleaseDC", C.c_int, W.HWND, W.HDC)
get_pixel = api(gdi, "GetPixel", W.DWORD, W.HDC, C.c_int, C.c_int)
create_dc = api(gdi, "CreateCompatibleDC", W.HDC, W.HDC)
create_bitmap = api(gdi, "CreateCompatibleBitmap", W.HBITMAP, W.HDC, C.c_int, C.c_int)
select_object = api(gdi, "SelectObject", W.HANDLE, W.HDC, W.HANDLE)
delete_object = api(gdi, "DeleteObject", W.BOOL, W.HANDLE)
delete_dc = api(gdi, "DeleteDC", W.BOOL, W.HDC)
print_window = api(user, "PrintWindow", W.BOOL, W.HWND, W.HDC, W.UINT)
global_alloc = api(kernel, "GlobalAlloc", W.HGLOBAL, W.UINT, C.c_size_t)
global_lock = api(kernel, "GlobalLock", C.c_void_p, W.HGLOBAL)
global_unlock = api(kernel, "GlobalUnlock", W.BOOL, W.HGLOBAL)
send = api(user, "SendMessageW", C.c_ssize_t, W.HWND, W.UINT, W.WPARAM, W.LPARAM)
process_times = api(kernel, "GetProcessTimes", W.BOOL, W.HANDLE,
                    C.POINTER(W.FILETIME), C.POINTER(W.FILETIME), C.POINTER(W.FILETIME), C.POINTER(W.FILETIME))
api(user, "SetProcessDpiAwarenessContext", W.BOOL, C.c_void_p)(C.c_void_p(-4))


def wait(condition, label, timeout=8):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        value = condition()
        if value:
            return value
        time.sleep(0.01)
    raise AssertionError(f"Timed out: {label}")


def text(hwnd, function=get_title):
    result = C.create_unicode_buffer(512)
    function(hwnd, result, len(result))
    return result.value


def windows(pid, window_class):
    result = []
    @CALLBACK
    def visit(hwnd, _):
        owner = W.DWORD()
        get_pid(hwnd, C.byref(owner))
        if owner.value == pid and text(hwnd, get_class) == window_class:
            result.append(hwnd)
        return True
    enum_windows(visit, 0)
    return result


def file_picker(pid, owner):
    # Enumeration also finds hidden shell setup windows, before a user can cancel.
    ready = []
    for dialog in windows(pid, "#32770"):
        cancel = get_item(dialog, 2)
        if (owner_window(dialog, 4) == owner and text(dialog) == "Open a photo"
                and visible(dialog) and enabled(dialog)
                and cancel and visible(cancel) and enabled(cancel)):
            ready.append(dialog)
    assert len(ready) <= 1, "More than one ready file picker belongs to the viewer"
    return ready[0] if ready else None


def events(path, name):
    return [r for r in rows(path) if r.get("event") == name]


def key(hwnd, code):
    assert post(hwnd, 0x100, code, 1)


def command(hwnd, code):
    assert post(hwnd, 0x111, code, 0)


def drop_file(hwnd, path):
    import struct
    data = struct.pack("<IiiII", 20, 0, 0, 0, 1) + (str(path) + "\0\0").encode("utf-16-le")
    memory = global_alloc(0x42, len(data))
    assert memory
    pointer = global_lock(memory)
    assert pointer
    C.memmove(pointer, data, len(data))
    global_unlock(memory)
    # Ownership passes to the viewer; DragFinish releases the block.
    assert post(hwnd, 0x233, memory, 0)


def close(process, hwnd):
    post(hwnd, 0x10, 0, 0)
    try:
        assert process.wait(timeout=4) == 0
    except subprocess.TimeoutExpired:
        process.kill()
        raise AssertionError("Viewer did not close promptly")


def launch(exe, photo, log):
    started = time.perf_counter()
    args = [str(exe)] + ([str(photo)] if photo else []) + ["--timings", str(log)]
    process = subprocess.Popen(args, creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        hwnd = wait(lambda: windows(process.pid, "Foto.Native.Viewer"), "native viewer window")[0]
        wait(lambda: events(log, "window"), "successful window presentation")
        return process, hwnd, started
    except BaseException:
        process.kill()
        process.wait()
        raise


@contextmanager
def client_dc(hwnd):
    """Capture only the real native window, even when another app is above it."""
    rect = W.RECT()
    assert get_rect(hwnd, C.byref(rect))
    screen = get_dc(None)
    memory = create_dc(screen)
    bitmap = create_bitmap(screen, rect.right, rect.bottom)
    assert memory and bitmap
    previous = select_object(memory, bitmap)
    try:
        assert print_window(hwnd, memory, 1), "PrintWindow could not capture the client"
        yield memory, rect.right, rect.bottom
    finally:
        select_object(memory, previous)
        delete_object(bitmap)
        delete_dc(memory)
        release_dc(None, screen)


def pixel_corners(hwnd, rotated=False):
    # Observe native window pixels independently of the app's success log.
    rect = W.RECT()
    assert get_rect(hwnd, C.byref(rect))
    dpi = get_dpi(hwnd) / 96
    top, height = 52 * dpi, rect.bottom - 86 * dpi
    iw, ih = (4000, 6000) if rotated else (6000, 4000)
    scale = min(rect.right / iw, height / ih, 1)
    left, upper = (rect.right - iw * scale) / 2, top + (height - ih * scale) / 2
    expected = [(0, 0, 255), (255, 0, 0), (255, 255, 0), (0, 255, 0)] if rotated else [
        (255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0)]
    with client_dc(hwnd) as (dc, _, _):
        for (x, y), target in zip([(0.125, 0.125), (0.875, 0.125), (0.125, 0.875), (0.875, 0.875)], expected):
            point = W.POINT(round(left + iw * scale * x), round(upper + ih * scale * y))
            value = get_pixel(dc, point.x, point.y)
            actual = (value & 255, value >> 8 & 255, value >> 16 & 255)
            assert all(abs(a-b) < 15 for a, b in zip(actual, target)), ("screen pixel", actual, target)


def cpu_ms(process):
    creation, exit_time, system, user_time = (W.FILETIME() for _ in range(4))
    assert process_times(process._handle, C.byref(creation), C.byref(exit_time), C.byref(system), C.byref(user_time))
    return ((system.dwHighDateTime << 32) + system.dwLowDateTime +
            (user_time.dwHighDateTime << 32) + user_time.dwLowDateTime) / 10000


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--exe", type=Path, default=ROOT / "target/release/foto.exe")
    parser.add_argument("--runs", type=int, default=10)
    options = parser.parse_args()
    output = ROOT / "artifacts/runs" / f"{time.strftime('%Y%m%d-%H%M%S')}-{os.getpid()}"
    output.mkdir(parents=True)
    photo = ROOT / "artifacts/photos/photo1.jpg"
    assert photo.is_file(), "Run tools/generate_fixtures.py first"
    hashes = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in photo.parent.glob("*.jpg")}
    checks = []
    empty_log = output / "empty.csv"
    process, hwnd, _ = launch(options.exe, None, empty_log)
    try:
        assert text(hwnd) == "Foto"
        assert all(not enabled(get_item(hwnd, i)) for i in [101, 102, 103, 104, 105])
        assert all(enabled(get_item(hwnd, i)) for i in [100, 106, 107])
        assert not events(empty_log, "error") and not events(empty_log, "graphics_error")
        checks.append("empty window disables image actions and keeps Open available")
    finally:
        close(process, hwnd)
    log = output / "interactive.csv"
    process, hwnd, _ = launch(options.exe, photo, log)
    try:
        first = wait(lambda: events(log, "image"), "first image")[0]
        assert (int(first["width"]), int(first["height"])) == (6000, 4000)
        wait(lambda: enabled(get_item(hwnd, 102)), "directory scan complete")
        time.sleep(0.15)
        pixel_corners(hwnd)
        checks.append("24 MP image rendered with correct corner pixels")
        assert [text(get_item(hwnd, i)) for i in range(100, 108)] == [
            "Open", "Previous", "Next", "Fit", "100%", "Rotate", "Full screen", "Help"]
        checks.append("eight labelled native toolbar buttons")
        time.sleep(0.5)
        key(hwnd, 0x27)
        second = wait(lambda: events(log, "image")[1:] or None, "next image")[0]
        assert second["cached"] == "true"
        assert text(hwnd) == "photo2.jpg — Foto"
        key(hwnd, 0x23)
        wait(lambda: text(hwnd) == "photo10.jpg — Foto", "natural numeric ordering")
        key(hwnd, 0x24)
        wait(lambda: text(hwnd) == "photo1.jpg — Foto", "first image shortcut")
        time.sleep(0.1)
        pixel_corners(hwnd)
        checks.append("keyboard navigation, numeric ordering, prefetch cache")
        key(hwnd, 0x52)
        time.sleep(0.1)
        pixel_corners(hwnd, rotated=True)
        checks.append("rotation changes the displayed pixels correctly")
        command(hwnd, 105)
        command(hwnd, 105)
        command(hwnd, 105)
        command(hwnd, 104)
        key(hwnd, 0x6b)
        key(hwnd, 0x6d)
        command(hwnd, 103)
        time.sleep(0.1)
        pixel_corners(hwnd)
        checks.append("actual pixels, zoom shortcuts, fit recovery")
        original_style = get_style(hwnd, -16)
        key(hwnd, 0x7a)
        wait(lambda: get_style(hwnd, -16) & 0x00c00000 == 0, "full screen")
        key(hwnd, 0x1b)
        wait(lambda: get_style(hwnd, -16) == original_style, "full screen restoration")
        assert process.poll() is None
        checks.append("F11 and Escape restore the window")
        assert set_pos(hwnd, None, 50, 50, 840, 560, 0x14)
        time.sleep(0.1)
        pixel_corners(hwnd)
        checks.append("resize preserves fit and painted image")
        for _ in range(20):
            key(hwnd, 0x27)
            key(hwnd, 0x25)
        key(hwnd, 0x23)
        wait(lambda: text(hwnd) == "photo10.jpg — Foto", "latest rapid-navigation request")
        checks.append("rapid requests finish on the selected photo")
        unicode_photo = output / "café 猫 photo.jpg"
        unicode_photo.write_bytes(photo.read_bytes())
        drop_file(hwnd, unicode_photo)
        wait(lambda: text(hwnd) == "café 猫 photo.jpg — Foto", "Unicode drag-and-drop filename")
        time.sleep(0.1)
        pixel_corners(hwnd)
        checks.append("native file drop accepts spaces and Unicode paths")
        command(hwnd, 100)
        dialog = wait(lambda: file_picker(process.pid, hwnd), "native file picker")
        assert post(dialog, 0x10, 0, 0)
        wait(lambda: not windows(process.pid, "#32770"), "file picker cancellation")
        assert text(hwnd) == "café 猫 photo.jpg — Foto"
        time.sleep(0.1)
        pixel_corners(hwnd)
        checks.append("native file picker opens and cancels without losing the image")
        time.sleep(0.8)
        before = cpu_ms(process)
        time.sleep(1)
        idle_cpu = cpu_ms(process) - before
        assert idle_cpu <= 50, f"Unexpected idle CPU: {idle_cpu} ms"
        checks.append("idle window consumes <=50 ms CPU over one second")
        assert not events(log, "error") and not events(log, "graphics_error")
    finally:
        close(process, hwnd)

    # A diagnostics path must never truncate an existing photo.
    protected = output / "protected.jpg"
    protected.write_bytes(photo.read_bytes())
    digest = hashlib.sha256(protected.read_bytes()).digest()
    rejected = subprocess.Popen([str(options.exe), str(protected), "--timings", str(protected)],
                                creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        dialog = wait(lambda: windows(rejected.pid, "#32770"), "existing-log rejection")[0]
        assert post(dialog, 0x10, 0, 0)
        assert rejected.wait(timeout=4) == 1
        assert hashlib.sha256(protected.read_bytes()).digest() == digest
        checks.append("existing diagnostics output is rejected without modifying the file")
    finally:
        if rejected.poll() is None:
            rejected.kill()
            rejected.wait()

    # Repeat navigation in a two-photo folder so both neighbours fit in the cache.
    pair = output / "pair"
    pair.mkdir()
    for name in ["photo1.jpg", "photo2.jpg"]:
        (pair / name).write_bytes((photo.parent / name).read_bytes())
    nav_log = output / "navigation.csv"
    process, hwnd, _ = launch(options.exe, pair / "photo1.jpg", nav_log)
    navigation_samples = []
    try:
        wait(lambda: events(nav_log, "image"), "navigation benchmark image")
        wait(lambda: enabled(get_item(hwnd, 102)), "navigation benchmark directory")
        time.sleep(0.5)
        for iteration in range(10):
            count = len(events(nav_log, "image"))
            key(hwnd, 0x27 if iteration % 2 == 0 else 0x25)
            wait(lambda: len(events(nav_log, "image")) > count, "cached navigation presentation")
            row = events(nav_log, "image")[-1]
            assert row["cached"] == "true"
            navigation_samples.append(float(row["request_ms"]))
        time.sleep(0.1)
        pixel_corners(hwnd)
        assert not events(nav_log, "graphics_error")
        checks.append("ten cached navigation draws and final native window pixels")
    finally:
        close(process, hwnd)

    bad_log = output / "broken.csv"
    process, hwnd, _ = launch(options.exe, ROOT / "tests/fixtures/broken.jpg", bad_log)
    try:
        wait(lambda: events(bad_log, "error"), "corrupt image rejection")
        assert not events(bad_log, "image"), "Corrupt input incorrectly logged a successful image"
        wait(lambda: enabled(get_item(hwnd, 101)), "error navigation remains available")
        key(hwnd, 0x24)
        wait(lambda: events(bad_log, "image"), "recovery by opening first valid image")
        assert not events(bad_log, "graphics_error")
        checks.append("corrupt file is rejected; valid input still opens afterwards")
    finally:
        close(process, hwnd)

    samples, windows_ms = [], []
    for run in range(options.runs):
        sample_log = output / f"launch-{run}.csv"
        process, hwnd, started = launch(options.exe, photo, sample_log)
        try:
            image = wait(lambda: events(sample_log, "image"), "benchmark first image")[0]
            assert image["cached"] == "false"
            assert not events(sample_log, "graphics_error") and not events(sample_log, "error")
            samples.append({"internal_ms": float(image["elapsed_ms"]),
                            "external_observed_ms": (time.perf_counter()-started)*1000})
            windows_ms.append(float(events(sample_log, "window")[0]["elapsed_ms"]))
        finally:
            close(process, hwnd)
    assert all(hashlib.sha256(p.read_bytes()).hexdigest() == digest for p, digest in hashes.items())
    checks.append("original photo bytes are unchanged")
    report = {"verdict": "PASS", "checks": checks, "runs": options.runs,
              "exe_bytes": options.exe.stat().st_size,
              "exe_sha256": hashlib.sha256(options.exe.read_bytes()).hexdigest(),
              "pixel_oracle": "PrintWindow client pixels from the native window; no application state bypass",
              "test_image": "6000 x 4000 JPEG (24 MP), synthetic gradient, warm OS file cache",
              "first_window_median_ms": round(statistics.median(windows_ms), 2),
              "first_image_median_ms": round(statistics.median(x["internal_ms"] for x in samples), 2),
              "external_observed_median_ms": round(statistics.median(x["external_observed_ms"] for x in samples), 2),
              "cached_navigation_median_ms": round(statistics.median(navigation_samples), 2),
              "cached_navigation_samples_ms": navigation_samples,
              "idle_cpu_ms_over_one_second": idle_cpu,
              "samples": samples}
    (output / "verification.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    (ROOT / "artifacts/verification.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    print("FOTO_SMOKE_PASS")


if __name__ == "__main__":
    main()
