# Recursive improvement wave — 2026-10-20

## Result

**One decoder repair retained; three consecutive subsequent candidates rejected and reverted.** No regression beyond the calibrated guards was detected in the final bounded suite. This is not a claim of universal improvement or zero regressions.

Only `src/decode.rs` changes application behavior. No dependency, image-quality setting, cache limit, application feature, file association, installed codec or machine policy was changed. The local executable is `dist/foto.exe`; no commit, push or remote release was made.

## Retained repair: oversized EXIF photos

A synthetic 9000 × 4000 JPEG with EXIF orientation 6 did not display after **90.146 seconds**, using **89734.375 ms CPU**. The process remained responsive to close. This is a censored lower bound, not a completed latency measurement. The unrotated scaled image displayed in 148.847 ms internal time.

Reordering the scaler and rotator alone did not fix the problem: the rotator still repeatedly pulled columns through a lazy scaler. The retained change scales in decoder row order, materializes the bounded scaled WIC bitmap once, then applies EXIF rotation/mirroring. Original oriented dimensions, Fant interpolation, premultiplied output and allocation limits are preserved.

The new J16 regression fails on the original executable with a decode timeout. With the repair, all eight oversized EXIF orientations pass dimensions, four rendered corner colors and a responsiveness guard. Final per-image journey times range from 202.339 to 618.557 ms. A separate eight-launch, single-image-folder workload measured:

- Internal first draw: **451.005 ms median**, 457.427 ms maximum.
- Externally observed first draw: **472.563 ms median**, 477.326 ms maximum.
- Median total process CPU: 492.188 ms.
- Median peak working set: 270286848 bytes.

The singleton folder deliberately excludes adjacent prefetch from this measurement. Its control is the preserved repaired build, not the original timed-out binary. No precise percentage speedup is claimed from a timeout. The temporary WIC bitmap has bounded dimensions but native-format/codec allocations are additional memory; the 192 MiB cache limit is not a process memory cap.

## Experiments and stopping rule

The fresh control was built from `dd86394` and preserved under `baselines/recursive-start-1.0.2/`. Historical ignored baselines/reports were absent in this checkout and were not substituted for fresh evidence.

Promotion requires passing correctness, a useful repeatable gain exceeding max(10%, twice unchanged-build median absolute paired percentage difference), and the regression guards in `artifacts/recursive/protocol.json`. A reproduced responsiveness defect can be repaired using a red/green journey. Completed measurements are not automatically optimization wins. Any retained improvement resets the consecutive no-gain count; setup/oracle failures do not count.

| Candidate | Evidence and decision | Consecutive no-gain count |
| --- | --- | ---: |
| C1: bounded materialization before EXIF transform | Retained: red/green oversized-image journey; ordinary workload comparison | 0 |
| C2: bypass converter when source is already PBGRA | Reverted: icon reopen median 2.9245 → 2.9565 ms; p99 4.864 → 6.622 ms; no resource gain | 1 |
| C3: prefetch membership without LRU promotion | Reverted: apparent pressure p95 gain 14.457%, below the calibrated 32.282% threshold; no resource gain | 2 |
| C4: remove temporary directory path/extension allocations | Reverted: indexing median 51.142 → 52.892 ms; CPU unchanged; threshold 16.259% | **3** |

C2 had four AB/BA pairs on icon and oversized-image workloads; C3 four on browsing and cache pressure; C4 six on a 10,000-entry directory. Relevant native journeys and Rust tests passed for each experiment. No rejected experimental product code remains.

## Final ordinary-workload confirmation

Eight serial alternating AB/BA pairs compare the **original** control with the final executable. Each workload has 192 navigation samples per build and 320 synchronous command-through-paint samples per build. Nearest-rank tails are pooled, with raw per-process observations retained.

| Navigation metric | Original | Final |
| --- | ---: | ---: |
| Three-photo median | 16.7815 ms | 18.0535 ms |
| Three-photo p95 | 28.343 ms | 28.120 ms |
| Three-photo p99 | 34.958 ms | 32.470 ms |
| Seven-photo pressure median | 11.1960 ms | 11.1605 ms |
| Seven-photo pressure p95 | 17.172 ms | 17.010 ms |
| Seven-photo pressure p99 | 20.788 ms | 22.232 ms |

The browsing median moved **7.580% slower**, within its **22.102%** calibrated guard. Pressure p99 moved **6.946% slower**, within its **32.282%** guard. These are not ordinary-browsing speedup claims. CPU and memory did not establish an additional useful improvement. Process memory was essentially unchanged in the matched paired workloads; all idle CPU samples were zero.

Pressure exceeds cache capacity, but all recorded foreground selections hit prefetch: it demonstrates cache churn and prefetch behavior, not foreground cache-miss latency. Photo-specific interior pixels now supplement shared corner markers, so a current title with a stale prior image fails. A deliberately wrong expected photo was rejected by this oracle.

## User outcomes and acceptance coverage

| User story | Native journeys / evidence |
| --- | --- |
| Open a local photo without changing it | J01 Unicode/long paths and picker cancellation; J12 portable imports and fixture integrity; smoke diagnostics overwrite protection |
| Browse naturally and recover from bad files | J02 numeric/case ordering; J05 latest request wins; J06 missing, locked, edited and corrupt recovery |
| Inspect, zoom, pan, rotate and restore a photo | J03 geometry; J13 all rendered EXIF transforms and navigation reset; J18 anchored wheel zoom with a marker-width assertion proving zoom actually occurred |
| Use full screen, minimize and resize | J04 placement/fullscreen repeat handling and minimize recovery; J11 simulated DPI and toolbar geometry |
| Browse a large folder and leave promptly | J08 50,000 entries and superseding folder scans; J15 twelve close-while-busy cycles |
| Keep the viewer open and navigate heavily | J09 sixty open/close cycles and 300-second active soak; J05 8,000 rapid navigation inputs and 30 rapid drops |
| Use only the toolbar/keyboard or a single image | J10 Tab/Enter; J14 single-photo boundaries, Help and Escape; J17 actual Unicode picker acceptance and focused Space/Enter activation |
| Open formats and oversized oriented photos correctly | J07 format/alpha/reduced-preview checks; J13 small EXIFs; J16 all eight oversized EXIFs |
| Recover from malformed input and use accessibility controls | 256 bounded mutations; native UI Automation names, roles, focus support and actual Fit Invoke with pixel verification |

Final gates:

- Formatting, strict all-target Clippy, 14 Rust tests, release build and portable import audit: PASS.
- All 18 journey charters: PASS.
- Five-minute soak: **5914 actions**; GDI 14 → 14, USER 22 → 22, handles 224 → 222; idle CPU 0 ms over one second; process peak working set 489.535 MiB.
- The soak's starting and ending working sets differ with cache/display ownership. Its sampled working sets plateau rather than establish a matched leak comparison; it does not prove absence of long-term leaks.
- Malformed inputs: 218 decoded/partially decoded, 38 rejected; valid-image recovery and native UIA Invoke: PASS.
- All 16 smoke checks and 20 launch samples: PASS; input fixture hashes unchanged.
- Percentile self-check and image-identity negative control: PASS.

The picker verifier enumerates the nested Edit control rather than guessing its parent. Cross-process text is read through WM_GETTEXT, not GetWindowText. Its documented 200 ms shell-initialization settle is a test shortcut, not application latency. Earlier failed picker/Help verifier runs remain as failed evidence, not final gates.

## Evidence and reproduction

The consolidated machine-readable index is `artifacts/recursive/final-report.json`; calibration/experiment summaries and raw reports are linked there. Exact final gates:

- `artifacts/recursive/1792509868386711800-final-ordinary/report.json`
- `artifacts/recursive/1792510057611600700-final-oriented/report.json`
- `artifacts/hardening/20261020-232804-2672/report.json`
- `artifacts/hardening/20261020-233346-23876/malformed-report.json`
- `artifacts/verification.json`

Final executable SHA256: `6a99d861c752351d1e0e31ca1ada2ed9e191a4040e02dba725cb22a198f5f31b`.

```powershell
cargo fmt --all -- --check
cargo clippy --all-targets -- -D warnings
cargo test
cargo build --release
cargo build --release --example uia_probe
python tools/check_portable.py target/release/foto.exe
python tools/recursive_bench.py --self-test
python tools/stress_test.py --exe target/release/foto.exe --soak-seconds 300 --actions 8000 --cycles 60 --folder-entries 50000
python tools/malformed_test.py --exe target/release/foto.exe --samples 256
python tools/smoke_test.py --exe target/release/foto.exe --runs 20
python tools/recursive_bench.py --control baselines/recursive-start-1.0.2/foto.exe --candidate target/release/foto.exe --pairs 8 --label confirmation --workloads browse,pressure
```

The benchmark needs the synthetic `artifacts/photos` images described in README. Keep measurements serial, in an unlocked Windows desktop; do not overlap compilation or other suites with benchmarks. Run Python normally, not with `-O`, because assertions are acceptance gates.

## Limits

One Windows 11 host, warm file cache and synthetic images. Navigation samples within a process are correlated; launch p95/p99 with eight samples are descriptive maxima, not reliable population estimates. CPU includes the test's pixel-capture workload and prefetch; synchronous UI timing does not include the desktop compositor. No human UAT, physical multi-monitor/DPI transitions, Windows 10, exhaustive codec fuzzing, cold-start cache flushing, power measurement or multi-day soak was performed. Screenshots are saved under `artifacts/recursive/dogfood/`, but the visual-inspection tool failed with a permission error; no manual visual-review pass is claimed.
