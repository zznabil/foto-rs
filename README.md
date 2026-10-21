# Foto

[![CI](https://github.com/zznabil/foto-rs/actions/workflows/ci.yml/badge.svg)](https://github.com/zznabil/foto-rs/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/zznabil/foto-rs)](https://github.com/zznabil/foto-rs/releases/latest)
[![License: GPL v3 or later](https://img.shields.io/badge/license-GPL--3.0--or--later-blue)](LICENSE)

A minimal native photo viewer for Windows x64, written in Rust. Open a photo, browse its folder, zoom, pan, rotate and go full screen. Photos stay read only.

## Download

Download the **Windows x64 ZIP** from [the latest release](https://github.com/zznabil/foto-rs/releases/latest), extract it, and run `foto.exe`. No installation, account, Rust toolchain or separate Visual C++ runtime is required.

The executable is unsigned by Windows Authenticode. Release checksums and GitHub build provenance identify the published artifacts; provenance does not replace Windows code signing. See [verification instructions](docs/VERIFYING.md).

Defender scans gate the built and independently downloaded executable. See the [1.0.2 detection investigation](docs/DEFENDER.md) for the affected hash and current evidence limits.

Windows 10 and 11 x64 are the intended desktop targets. Windows 11 has local journey coverage; Windows Server runners provide CI coverage. A separate Windows 10 host and real multi-monitor DPI transfers remain unverified.

## Use

Drop a photo into the window, press **Ctrl+O**, or drop it onto `foto.exe`. You can also pass its path:

```powershell
.\foto.exe "C:\Pictures\photo.jpg"
```

The viewer finds other supported photos in the same folder, in Explorer-style numeric order: `photo2` comes before `photo10`. Rotation changes only the view.

| Control | Action |
| --- | --- |
| Left / Right; Page Up / Page Down | Previous / next photo |
| Home / End | First / last photo |
| Wheel; + / - | Zoom |
| Drag | Pan |
| 0 / 1 | Fit / actual decoded pixels |
| R | Rotate clockwise |
| F11; F; double-click | Toggle full screen |
| Escape | Leave full screen, or close |
| Tab / Shift+Tab; Enter / Space | Focus / activate toolbar buttons |
| F1 | Help |

## Formats and limits

JPEG, PNG, BMP, GIF, TIFF and ICO are supported. GIF and TIFF show their first frame. HEIC, HEIF, WebP and JPEG XR depend on installed Windows codecs. JPEG EXIF orientation includes mirrored orientations.

Images exceeding 32 million pixels or an 8192-pixel edge use a reduced preview, identified in the status bar. For these images, 100% means one decoded preview pixel per screen pixel. Foto does not animate GIFs, edit files, manage a photo library or play video. Image-content and custom status-line screen-reader access remain unverified; native toolbar names, focus and Invoke are tested.

## Performance

Native Win32 controls, WIC decoding, DirectWrite text and a Direct2D software DC target keep the app small and responsive. Two workers handle foreground decoding and lower-priority prefetch. Pending foreground work has one replaceable slot; stale results cannot replace the selected image. There is no idle rendering timer.

The decoded cache is capped at **192 MiB and five entries**. Active images, rendering bitmaps, codec allocations and in-flight decodes are additional memory. Navigation reuses the previous displayed allocation when prefetch has evicted it. An earlier paired synthetic 24 MP browsing test measured about 50% lower CPU time and 12.5% lower peak working set from that change. Steady memory did not improve, and no startup speedup is claimed. See [the experiment record](PERFORMANCE.md); results depend on workload, hardware, codecs and system load.

Each release includes fresh test evidence in its portable ZIP. Historical local reports are not CI or release acceptance for a later build.

## Build and contribute

See [CONTRIBUTING.md](CONTRIBUTING.md) for prerequisites, pinned dependencies and the complete Windows verification command. Build with the MSVC toolchain and Windows SDK:

```powershell
cargo build --locked --release
```

The executable is `target\release\foto.exe`. Python and Pillow are test tools only.

[Changes](CHANGELOG.md) | [Release process](docs/RELEASING.md) | [Security reports](SECURITY.md) | [Baseline](BASELINE.md)

## License

**GPL-3.0-or-later.** See [LICENSE](LICENSE) and [COPYRIGHT](COPYRIGHT). Contributions use the same license. Third-party licenses and the dependency inventory are described in [THIRD_PARTY.md](THIRD_PARTY.md). Corresponding release source, including vendored Cargo dependencies and build scripts, is distributed alongside the binary ZIP.
