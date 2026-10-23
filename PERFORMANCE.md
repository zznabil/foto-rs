# Foto performance loop

This document preserves the original 1.0.2 optimization wave. See [RECURSIVE.md](RECURSIVE.md) for the subsequent fresh-baseline wave, oversized-EXIF repair, broadened gates and new three-candidate plateau.

User request: improve performance and resource usage, preserve behavior, and continue until repeated attempts reach a plateau. The v1.0.0 baseline and a separate pre-optimization 1.0.1 archive remain frozen locally.

## Method and stopping rule

One material candidate changes at a time. Warm-cache synthetic 24 MP JPEGs, the same native window and serial alternating AB/BA runs control comparisons. The browsing workload traverses three photos in both directions, twelve moves per process with 200 ms between moves. CSV draw timings are paired with process CPU, working set/private memory, peak working set, handles and GDI/USER counts. Native window pixels and selected filenames are checked independently of timing logs. Optional empty-window runs settle for 300 ms. These are process measurements, not system-wide power or disk measurements.

Promotion requires at least 10% lower memory use, or repeatable latency reduction above max(10%, twice unchanged-build noise), with no failed correctness gate or material latency regression on other workloads. Changes below threshold revert. Three consecutive evaluated candidates without a useful retained improvement establish the local plateau. A retained improvement resets that count. This stopping rule does not establish global optimality.

The first AA run overlapped compilation and is excluded. Valid serial AA group differences were 5.11% for internal launch, 0.44% external launch, 3.39% navigation, 4.49% CPU and 0.26% peak working set. The internal-launch promotion threshold is therefore 10.22%; navigation/external remain 10%. Empty-window calibration was added before candidate E05: its RSS threshold remained 10%, private-memory threshold 21.43% and first-paint latency threshold 20.67%. Raw samples and executable hashes remain in each report.

## Experiments

| ID | Hypothesis | Outcome |
| --- | --- | --- |
| E01 | Zeroed allocation avoids an extra pass over decoded pixel memory | Reverted. Latency slightly worse; peak reduction 9.7%, below threshold |
| E02 | Reuse the previously displayed image after prefetch evicts it, avoiding another decode | Retained; initial six pairs showed CPU -43.7%, peak working set -13.4%, unchanged cache hits and no material latency regression |
| E03 | Explicit opaque bitmap mode avoids unnecessary blending | Reverted. Navigation improvement below 1%; startup slower; no memory benefit |
| E04 | Skip stale/empty loader redraws and unchanged button-state redraws | Reverted. Navigation improvement below 0.1%; no resource benefit |
| E05 | Initialize worker codecs only when a job needs them | Reverted. Empty RSS reduction 3.6%, below 10%; no useful latency or private-memory improvement |

E03, E04 and E05 are the three consecutive rejected candidates after E02: plateau 3/3. No rejected experimental code remains in the product.

The retained code passes the previous displayed image to the cache during navigation. It acquires the requested image first, then remembers the previous allocation under the same byte/item limits. Explicit reopen still clears the cache; loading/error states do not associate an old image with a new filename. This changes neither decoded image resolution nor render quality.

The new regression checks allocation identity, requested-image survival, eviction and byte bounds. Disabling reuse makes the test fail; restored code passes. An initial negative-control mutation damaged line endings and failed compilation, so it was excluded as evidence. The corrected byte-preserving mutation fails the intended test.

## Evidence

The complete historical final comparison is checked in at [docs/evidence/performance-1.0.2.json](docs/evidence/performance-1.0.2.json). The paths below identify local development records; current public release evidence is supplied in each release ZIP.

- AA calibration: artifacts/optimization/1792494363194120500-AA-serial/report.json
- E01: artifacts/optimization/1792494436183099900-E01-zeroed/report.json
- E02: artifacts/optimization/1792494552990634300-E02-reuse-previous/report.json
- E03: artifacts/optimization/1792494684354491200-E03-opaque/report.json
- E04: artifacts/optimization/1792494793534648300-E04-redraw/report.json
- Empty AA: artifacts/optimization/1792494895590475800-AA-empty/report.json
- E05: artifacts/optimization/1792494956414043800-E05-lazy-codecs/report.json
- Negative control: artifacts/optimization/reuse-negative-control.txt
- Final build gates: artifacts/optimization/final-build-gates.json

## Final build confirmation

Fresh eight-pair comparison: artifacts/optimization/1792495104226787300-final-1.0.2/report.json. Control and candidate are the frozen 1.0.1 and final 1.0.2 binaries. All 96 moves per build hit the cache. Native image pixels, selected filenames and unchanged fixture hashes passed.

| Metric | 1.0.1 control | 1.0.2 candidate | Change |
| --- | ---: | ---: | ---: |
| Browsing CPU time | 2046.875 ms | 1031.250 ms | -49.6% |
| Peak working set | 455.3 MiB | 398.3 MiB | -12.5% |
| Steady working set | 306.8 MiB | 306.8 MiB | Essentially unchanged |
| Three-photo navigation median | 30.030 ms | 30.159 ms | +0.43% |
| Navigation p95 per run, median | 36.201 ms | 34.660 ms | -4.26% |
| Internal first draw | 182.482 ms | 184.636 ms | +1.18% |
| Externally observed first draw | 237.080 ms | 248.778 ms | +4.93% |

The final source passes 14 Rust tests, strict all-target Clippy, formatting and the negative control. Startup is not faster. The observed latency differences remain within the predeclared 5% material-regression guard; this is bounded evidence, not proof of equivalence. Fresh separate ten-sample smoke runs measured two-photo cached navigation at 25.49 ms control and 22.62 ms candidate; both passed all 16 live checks. Those sequential blocks are additional regression evidence, not a randomized speedup claim.

Final live regression gates: PASS.

- artifacts/verification.json: all 16 smoke checks and 10 launch samples; idle CPU 0 ms over one second.
- artifacts/hardening/20261020-192115-10160/report.json: all twelve journey charters, 2,000 rapid navigation inputs, 30 drops, a 10,000-entry folder, 30 open/close cycles and a 120-second soak with 2342 actions. GDI 14 to 14, handles 258 to 260, USER 21 to 21; idle CPU 0.0 ms over one second.
- artifacts/hardening/20261020-192410-34620/malformed-report.json: 200 malformed inputs, valid-image recovery and actual native accessibility Invoke passed. This ran after the soak, without overlap.
- Portable x64 GUI imports remain Windows system libraries only. Both preserved baseline manifests match. Packaged reports match executable SHA256 `8bdced0523cdd5d9dd83fb8cca72f524bf1dcc17000ba686600685ce2e5b0fce`; every packaged file matches SHA256SUMS.txt. No test viewers remain running.

Verdict: PASS for this bounded optimization loop. Plateau 3/3 reached. Only E02 remains in the application; four candidates were reverted. Local rollback: run baselines/performance-start-1.0.1/foto.exe or baselines/v1.0.0/foto.exe. No external release was published.

## Limits

Single Windows 11 host, warm file cache and synthetic workload. No human UAT, Windows 10 or real multi-monitor transfer coverage. CPU reductions apply to this browsing pattern; idle CPU was already near zero. Lower peak memory does not imply lower steady-state memory. No guarantee covers every image, machine or codec. The benchmark is not security certification. No machine configuration, user images, remote publication or persistent scheduler was changed.
