# Foto

A minimal, native photo viewer for 64-bit Windows 10 and 11. Built in Rust.

## Run

Open `dist/foto.exe`, then drop a photo into the window or press **Ctrl+O**.
You can also drop a photo onto the executable, or run:

```powershell
.\dist\foto.exe "C:\Pictures\photo.jpg"
```

The viewer finds other photos in the same folder. File names use Explorer's numeric order, so `photo2` comes before `photo10`. Photos are read only. Rotation changes the view and does not save changes to the file.

## Controls

- **Left / Right**, **Page Up / Page Down**: previous / next photo.
- **Home / End**: first / last photo.
- **Mouse wheel**, **+ / -**: zoom. The wheel keeps the pointer over the same image position where the image bounds allow it.
- **Drag**: pan a zoomed photo.
- **0**: fit the photo inside the window. Small photos retain their original size.
- **1**: actual pixels.
- **R**: rotate clockwise.
- **F11**, **F**, or **double-click**: full screen.
- **Escape**: leave full screen, or close the viewer.
- **Tab / Shift+Tab**: focus the labelled native toolbar buttons. **Enter / Space** activates a focused button.
- **F1**: help.

## Formats and limits

JPEG, PNG, BMP, GIF, TIFF and ICO are supported. GIF and TIFF show their first frame. HEIC, HEIF, WebP and JPEG XR depend on the Windows codecs installed on the computer. JPEG EXIF orientation is applied, including mirrored orientations.

Images larger than 32 million pixels or 8192 pixels on either side are reduced before the viewer allocates its pixel buffer. The status bar identifies a reduced preview. For these images, **100%** means one decoded preview pixel per screen pixel.

This first version focuses on local image viewing. It does not animate GIFs, manage a photo library, edit files, or handle video. Screen-reader access to image contents and the custom-drawn status line has not been verified. Toolbar controls have native button names and keyboard focus.

## Performance

The executable uses native Win32 controls, Windows Imaging Component decoding, DirectWrite text and a Direct2D software DC render target. The DC render target avoids a window swap chain and works in the desktop session used for testing, where the swap-chain path could report occlusion for a visible window.

The viewer repaints on input, window changes and completed image loads. It has no idle rendering timer. Two worker threads handle foreground decoding and lower-priority prefetch. Pending foreground work has one replaceable slot. Stale results cannot replace the selected image.

Adjacent decoded photos use an LRU cache capped at **192 MiB and five entries**. Active image bytes, the drawing bitmap, codec allocations and in-flight decodes are additional memory. The drawing bitmap is reused when adjacent images have equal dimensions. Navigation also returns the previously displayed pixel buffer to the cache when prefetch has evicted it, avoiding unnecessary redecoding. See [PERFORMANCE.md](PERFORMANCE.md) for the measured optimization loop and its limits.

See `artifacts/verification.json` for the latest measured results. The test uses synthetic 6000 × 4000 JPEGs and a warm Windows file cache. Timings vary with the file, storage, codec, display, security scanning and system load. A warm-cache measurement is not a cold-start guarantee.

To collect a local CSV log, choose an output path that does not exist:

```powershell
.\dist\foto.exe "C:\Pictures\photo.jpg" --timings .\timings.csv
```

`elapsed_ms` measures time since application entry. On an `image` row, `request_ms` measures selection through a successful draw; `cached` records whether the image was cached when selected. Process creation and the desktop compositor add latency. The log also records decoder and drawing errors. The viewer refuses to overwrite an existing log file.

## Build and verify

Install the Rust MSVC toolchain and Microsoft C++ build tools. Then run:

```powershell
cargo fmt --all -- --check
cargo clippy --all-targets -- -D warnings
cargo test
cargo build --release
python tools/check_portable.py target/release/foto.exe
```

The executable is `target\release\foto.exe`. Copy it to `dist\foto.exe` for portable use. The project links the C runtime statically. The executable does not require a Rust installation or a separate Visual C++ runtime installation on the destination computer.

Decoder fixtures are included under `tests/fixtures`. To regenerate them and create larger benchmark images, install Pillow in the development environment and run `python tools/generate_fixtures.py`. Pillow is not an application dependency.

Run `python tools/smoke_test.py --exe dist/foto.exe --runs 10` in an unlocked Windows desktop session. The script opens temporary test windows, captures each test window with PrintWindow for pixel checks, and closes it. It checks actual rendered pixels, input ordering, navigation, resize, full screen, corrupt-file recovery, idle CPU and unchanged input files. It writes a success marker only after all checks pass.

For the extended local suite, build the native accessibility probe and run:

```powershell
cargo build --release --example uia_probe
python tools/stress_test.py --exe dist/foto.exe
python tools/malformed_test.py --exe dist/foto.exe --samples 200
```

The stress suite covers twelve journey charters, 2,000 rapid navigation inputs, 30 drops, a 10,000-entry folder, 30 open/close cycles and a 120-second active soak. The malformed suite uses bounded JPEG/PNG mutations and verifies native UI Automation button names, roles, focus support and actual Invoke behavior. Generated files stay under `artifacts/hardening/`. These are automated acceptance checks; see [AUDIT.md](AUDIT.md) for findings and evidence and [BASELINE.md](BASELINE.md) for the frozen v1.0.0 checkpoint.

The application was tested on Windows 11. A separate Windows 10 machine and multiple monitor DPI configurations have not been tested.

Windows API reference: [Direct2D and GDI interoperability](https://learn.microsoft.com/en-us/windows/win32/direct2d/direct2d-and-gdi-interoperation-overview).
