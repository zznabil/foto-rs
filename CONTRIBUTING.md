# Contributing

Foto favors a small native viewer, read-only image handling, predictable resource bounds and measured changes. Keep unrelated work separate. Contributions are licensed under GPL-3.0-or-later.

## Windows prerequisites

Use an x64 Windows desktop, Microsoft C++ build tools and the Windows SDK, Rust through rustup, and Python 3.14.7. `rust-toolchain.toml` pins Rust 1.98.1, Clippy, rustfmt and the library notices supplied with rust-docs. CI also compiles against the declared Rust 1.85 minimum.

```powershell
rustup toolchain install 1.98.1 --profile minimal --component clippy,rustfmt,rust-docs --target x86_64-pc-windows-msvc
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --require-hashes --only-binary=:all: -r requirements-dev.txt
cargo build --locked --release
```

## Verify a change

Use a fresh checkout or archive an earlier `artifacts/ci` directory. Commit the candidate source before collecting release evidence; the gate records its commit and requires an unchanged tracked tree.

```powershell
.\.venv\Scripts\python.exe tools/verify.py
```

The gate runs formatting, strict all-target Clippy, Rust tests, release/example builds, portable imports, Windows file-version readback, 16 native-window smoke checks, eighteen journey charters, a 120-second soak, 30 open/close cycles and 200 malformed-input trials with native UI Automation Invoke. Synthetic images are generated under ignored `artifacts/`; committed decoder fixtures remain unchanged. Run in an interactive desktop session. CI exercises the Windows Server runner desktop; it does not claim human UAT or real monitor transfers.

Run the release-verifier controls and workflow/dependency checks separately:

```powershell
python -m unittest discover -s tools -p test_release_checks.py -v
python tools/run_pinned_tool.py actionlint -color
python tools/run_pinned_tool.py cargo-deny check
```

Verification tools are downloaded from pinned upstream releases and checked against committed SHA-256 values before execution. GitHub Actions are pinned to commit IDs. Dependabot proposes updates; passing checks do not replace review of changes to release permissions or gates.

For performance work, compare unchanged builds to estimate noise, alternate control/candidate order, keep synthetic inputs and settling periods fixed, and record both gains and regressions. The historical `tools/perf_compare.py` requires two supplied Windows executables. Do not present warm-cache results as cold-start guarantees or the cache budget as a process-memory cap.

## Pull requests

Describe the user-visible change, relevant tests and remaining limits. Do not include user photos, credentials, generated binaries or private machine data. Main requires successful checks and resolved conversations. The current solo-maintainer configuration requires a PR but does not claim independent human approval. Squash merging keeps release commits easy to identify.
