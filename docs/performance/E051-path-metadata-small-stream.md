# E051: reject path-metadata eligibility and 4 KiB owned streams

Archive status (2026-10-29 takeover): the results and checks below are the original study's report, not newly reproduced evidence. Its fingerprinted raw data and complete streak ledger have not been recovered in this takeover. The reported 29-plateau streak is not adopted as the current verified count. Current verification starts at zero unless that historical evidence is recovered and validated.

Checking path metadata before opening the file and limiting owned memory streams to 4 KiB did not repair the prior design's costs. This candidate failed latency, CPU and memory guards. Keep the original filename decoder. This PR proposes only an experiment report; no product change was retained.

The original study recorded E051 as a distinct rejected design, advancing its local streak once from 28 to 29. It reported 39 performance-evaluated candidates, ten unresolved candidates and zero retained improvements in that streak. Demonstrated harm counted as a rejection; a counted plateau did not mean the candidate was safe to ship. The target of exactly 100 remains incomplete.

## Hypothesis and scope

E050 showed small JPEG/PNG timing gains but failed at the 64 KiB memory boundary and just-over-limit fallback. E051 tested a coupled repair: use `std::fs::metadata(path)` to reject nonregular, empty or over-4,096-byte inputs before `File::open`, and cap owned copies at 4 KiB. The hypothesis was that cheaper eligibility and smaller copies would preserve the small-input gain while removing both harms. It was not supported by this screen; a path-metadata API is not assumed cheap merely because it precedes open.

Eligible JPEG/JPG/JFIF/PNG inputs still use fallibly allocated, fully initialized bounded storage of the observed length plus one byte, with growth/IO/allocation failures falling back. `SHCreateMemStream` owns its copied bytes; only Microsoft JPEG/PNG decoders are eligible. The original filename decoder handles all other routes. EXIF, scaling, premultiplied output, first frame and exact-capacity pixel reuse were held constant. No dependency, feature, cache-limit or machine-setting change was added.

- Local base: `16bde7b054695c4b643f22e4598b39341a1f07a2` plus ongoing study changes; source fingerprints below identify the actual tested decoder. Unresolved E010/E015 integration-base work is not accepted by this rejection.
- Rust 1.96.0, Python 3.14.8, Windows 11 x64, one host. Both arms use optimization level 3, full LTO, one codegen unit and static CRT.
- Five warm synthetic inputs, all 64 x 48: an 831-byte JPEG, a 169-byte PNG, that PNG padded to exactly 4,096 bytes, to 4,097 bytes and to 65,537 bytes. The last two exercise filename fallback. Padding holds decoded content constant across boundaries; it does not represent every large real-world image.

## Correctness and calibration

Before timing, 23 Rust tests, strict all-target Clippy, formatting, eight current native journeys (J06/J07/J13/J16/J21/J22/J23/J24) and the portable-import audit passed. New boundary tests cover 0/4,095/4,096/4,097 bytes, growth, EOF/shrink, injected read failure, missing/invalid files, extension case and renamed formats.

Complete PBGRA, dimensions and oriented-original-size parity passed across 46 fixtures: all 40 prior E050 fixtures plus adjacent 4 KiB JPEG/PNG fixtures. Each fixture had four actual decodes, including fresh and poisoned exact-capacity reuse with pointer checks: 184 decodes in total. Deliberate one-byte output mutations were rejected. The helper returns after dropping caller bytes and the stream wrapper, before deferred WIC frame/pixel reads; actual full-byte parity exercises that lifetime. The unchanged owned-stream API also retains the prior independent overwrite/drop/churn capability evidence and borrowed-storage counterexample; that historical capability was not rerun or counted as new performance data.

The five-case measurement protocol was frozen after correctness and before probe build/data. All new children used matched source/build/output rules. No E050 measurements were pooled or reused. Per case, actual 1,000 ms single-delay detection (at least 750 ms observed difference), doubled complete WIC work with wall/CPU ratio at least 1.5, retained 32 MiB private/peak increases of at least 24 MiB, full payload hashes and one-byte negatives passed. Process-time/cycle counters were read twice and checked before pixel transport.

## Measurement and analysis

Normal-load children each performed 4,096 complete fresh-buffer loads; each of five doubled-work controls performed 8,192. Four unchanged-control AA pairs and 12 alternating AB/BA pairs per case, with rotating case order, produced 160 comparison children and 25 controls. The exact total is **180 x 4,096 + 5 x 8,192 = 778,240** timed complete decodes across 185 children and 370 valid raw CPU records.

The endpoint includes file metadata/open/read/copy, decoder/vendor selection, WIC/EXIF/conversion and pixel allocation/copy. COM factory creation is outside the per-load timer and inside whole-process CPU. Resource counters precede pixel transport. This is not an initialization-only measurement.

Twenty formal fields cover process-mean per-load latency and mean whole-process CPU, peak commit and final private memory for five cases. Intervals use six two-pair blocks, 19,999 bootstrap draws and approximate 99% family coverage over 20 fields; BCa latency and percentile resource intervals. Noise guards remain `max(10%, 2 * median absolute AA percentage change)`, weak above 25%; both memory guards remain 10%. All 35 additional median resource checks and original absolute caps/deadlines remain. No guard relaxation, sample extension or unchanged retry occurred.

Probes publish 32 sums of 128 load timings per normal child (64 sums for doubled work), avoiding a full stderr pipe before the supervisor header. Any block-mean tail figures are descriptive, not individual-decode p95/p99 estimates. Loads within each process remain correlated.

## Results

Negative values mean lower cost; positive values mean higher cost. These are component-level estimates, not application UI or physical-input latency.

| Workload / metric | Change | Approximate interval | Guard |
| --- | ---: | ---: | ---: |
| jpeg.decode_ms | +15.5276% | [+12.5372%, +16.9735%] | 10.0000% |
| jpeg.CPU_mean_ms | +15.7895% | [+10.2222%, +20.7143%] | 10.6686% |
| jpeg.peak_commit_mean_bytes | +7.9230% | [+7.4916%, +8.6719%] | 10.0000% |
| jpeg.private_mean_bytes | +7.9230% | [+7.4916%, +8.6719%] | 10.0000% |
| png.decode_ms | +26.6757% | [+25.1182%, +28.5329%] | 10.0000% |
| png.CPU_mean_ms | +26.4957% | [+22.5989%, +30.4598%] | 10.4762% |
| png.peak_commit_mean_bytes | +6.6415% | [+5.3846%, +7.3329%] | 10.0000% |
| png.private_mean_bytes | +6.6415% | [+5.3846%, +7.3329%] | 10.0000% |
| exact4k.decode_ms | +26.2217% | [+25.4589%, +27.8380%] | 10.0000% |
| exact4k.CPU_mean_ms | +22.7528% | [+16.3932%, +28.1609%] | 10.0000% |
| exact4k.peak_commit_mean_bytes | +13.2387% | [+12.4149%, +13.8949%] | 10.0000% |
| exact4k.private_mean_bytes | +13.2387% | [+12.4149%, +13.8949%] | 10.0000% |
| fallback4k.decode_ms | +46.5420% | [+43.9553%, +49.3106%] | 10.0000% |
| fallback4k.CPU_mean_ms | +47.9532% | [+43.3908%, +59.2596%] | 10.7143% |
| fallback4k.peak_commit_mean_bytes | +1.4006% | [+0.9677%, +1.7973%] | 10.0000% |
| fallback4k.private_mean_bytes | +1.4006% | [+0.9677%, +1.7973%] | 10.0000% |
| fallback64k.decode_ms | +44.7476% | [+42.8519%, +47.2197%] | 10.0000% |
| fallback64k.CPU_mean_ms | +41.8079% | [+37.4999%, +46.9027%] | 10.0000% |
| fallback64k.peak_commit_mean_bytes | +1.6343% | [+1.0228%, +2.9518%] | 10.0000% |
| fallback64k.private_mean_bytes | +1.6343% | [+1.0228%, +2.9518%] | 10.0000% |

Eleven formal fields demonstrate regression beyond their matching guards. The JPEG CPU field is not bounded but its lower interval does not exceed its 10.6686% AA guard, so it is not separately called a demonstrated regression. All AA guards are nonweak.

The exact-4-KiB peak/private increases of 13.2387% (interval +12.4149% to +13.8949%) exceed the fixed 10% memory guards. Two of 35 median resource checks also fail at that boundary: private memory and peak commit. Both fallback latency and CPU intervals exceed their guards. No qualifying gain was found or retained.

Historical decision: `REJECTED_DEMONSTRATED_COMPONENT_PERFORMANCE_OR_RESOURCE_REGRESSION`. The study reported protected source, Cargo/configuration, default executable and distribution executable byte-identical to their pre-experiment values, with only owned temporary examples removed. It recorded one streak increment and no reset or release change. This takeover has not verified that increment.

This screen does not isolate syscall or allocator costs. Attributing the slowdown specifically to the implementation of path metadata, or memory specifically to heap allocation classes, would require a separate discriminating probe.

## Evidence fingerprints

These identify locally retained evidence. This report excludes generated binaries, raw local paths, credentials and photos, and is not a standalone reproducible benchmark package.

- control decoder: `99ee3495915d35f9698ef920548ebff57ca4e30e7399fa0b8ecc29d680355557`
- candidate decoder: `840afdcd40d48767b09f7c9b35034aed427102d0d48c22e39f380eb02ee2e6f1`
- preimplementation plan: `3f60d0c5eae47a85c88db422c0df468766fcd821822c211e0e8da4d4ddf889d5`
- correctness manifest: `2be700eead421f77461b84f15058e5afcef82333b9eba24e8ad44ba38f387625`
- measurement protocol: `d840a284b0dbc299f6f883ae9e189946b60b9a6007476134eadb6b97607d748a`
- measurements: `919d18aad31a3ab4dd12c5c9941003a1e5d0c2e4a9f5fa0d0a2104adac47692d`
- analysis: `a56a528c57e712ab62d9ffc384d05d6cdfe7dda2c9bfec04bd23227a8780fdac`
- decision: `fc24aef7b4d1d5c7139151321ba98b2230afe53649ee7c4747f9ddfd045d4987`

## Limits and next condition

Full 31-journey/600-second acceptance, independent gain confirmation and original-base/current-upstream acceptance were skipped after this valid rejection. Historical local toolchain checks do not replace upstream's current clean-commit verification gate. Remote CI for this documentation PR is separate.

No human UAT, cold-cache, Windows 10, physical hardware/input, native UI tail-latency or universal no-regression claim is made. Revisit only with a materially different mechanism supported by a bounded diagnostic and a new frozen protocol; further unbounded size-threshold sweeps are not justified by this result.
