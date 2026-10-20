# v1.0.0 baseline

The user accepted the first viewer and requested it as the v1.0 baseline on 2026-10-20.

The accepted 0.1.0 build and its complete local distribution were archived before changes as `baselines/accepted-original.zip`. Its executable SHA256 is `98babf4eac6aca68dfc502e437ebe4325ba9b89bcb479aec1cfd847d63de88a1`.

The formal baseline changes only package/release version metadata to **1.0.0**. The rebuilt executable SHA256 is `ad39300963687039741f6cca8628da3666e420197f5f52d38e30b7c272558ad2`.

`baselines/v1.0.0/` contains the frozen executable distribution, verification report, source archive and manifest. The local Git tag `v1.0.0` identifies the source checkpoint. These assets are retained locally; no remote release has been published.

Baseline checks: 11 Rust tests, strict Clippy, formatting, portable import audit, 16 real-window smoke checks, 10 launch samples and 10 cached navigation samples. The versioned report records warm-cache medians of 95.39 ms from application entry to first image draw, 125.59 ms observed externally, and 14.26 ms cached navigation.

These results apply to this Windows 11 host and synthetic 24 MP JPEGs. They do not establish Windows 10, multi-monitor hardware or human UAT coverage. Later audit findings do not alter the frozen baseline.

To compare source, use `git diff v1.0.0`. To run the baseline, open `baselines/v1.0.0/foto.exe`. For recovery, run that copy without replacing or deleting a newer build.
