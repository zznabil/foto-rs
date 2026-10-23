# E049: retain one release codegen unit

The tested `codegen-units=16` release profile did not meet the frozen 10% practical-gain threshold. Keep `codegen-units=1`. This report proposes no product or release-profile change.

E049 is the 27th consecutive valid plateau in the local performance study. This is a count of distinct rejected candidates, not 27 passing releases or a claim that the 100-plateau goal is complete. Ten other tested candidates remain unresolved; zero improvements have been retained in this streak.

## Tested scope and provenance

- A fixed three-profile matrix registered codegen units 4, 8 and 16 before building or timing any of them. This report covers only E049 (16).
- Control: codegen units 1. Candidate: child-process environment `CARGO_PROFILE_RELEASE_CODEGEN_UNITS=16`. Both use optimization level 3, full LTO and static CRT. Source, lockfile and other release settings were held constant.
- Local base revision: `16bde7b054695c4b643f22e4598b39341a1f07a2`, with additional ongoing study changes. The revision alone does not identify the measured bytes. Exact relevant source and executable fingerprints are below.
- Rust 1.96.0, Python 3.14.8, one Windows 11 x64 host, warm synthetic directory inputs.
- The local integration base contains unresolved E010/E015 changes. This rejection does not accept those changes or establish performance of current upstream `main`.

## Method

Each workload used a 10,000-entry synthetic directory: one already ordered, one requiring natural reordering. Matching probes included the actual production loader source. Each child measured 16 complete scans after its own reference and three warmups. CPU and memory measurements covered the process; scans within a child are correlated.

Per workload: eight unchanged-control AA pairs, then 24 alternating control/candidate AB/BA pairs. The two workloads produced 128 comparison processes, eight additional control processes, 272 valid raw CPU records and 2,240 timed complete scans. Analysis used 12 two-pair blocks, 99,999 bootstrap draws and an approximate 99% family interval over all 24 formal fields in the predeclared three-profile matrix. Latency used BCa intervals; resource means used percentile intervals.

Noise guards were frozen as `max(10%, 2 * median absolute AA percentage change)`, with guards over 25% considered weak and ineligible for acceptance. Memory guards remained 10%. A qualifying practical gain required the interval to establish at least a 10% improvement. The separate footprint threshold was also 10%.

## Results

Percent change is candidate relative to control; negative values mean less time or resource use. These are component-level estimates, not end-user latency or p95/p99 claims.

| Workload / metric | Change | Approximate interval | Guard |
| --- | ---: | ---: | ---: |
| ordered.scan_median_ns | +0.7712% | [+0.1264%, +1.3313%] | 10.0000% |
| ordered.CPU_mean_ms | -1.6787% | [-5.7629%, +1.9900%] | 11.7647% |
| ordered.peak_commit_mean_bytes | +0.0518% | [-0.0262%, +0.1374%] | 10.0000% |
| ordered.private_mean_bytes | -0.1357% | [-0.3621%, +0.1321%] | 10.0000% |
| reordered.scan_median_ns | +0.9453% | [+0.6547%, +1.2676%] | 10.0000% |
| reordered.CPU_mean_ms | +0.3505% | [-1.7265%, +2.8695%] | 10.0000% |
| reordered.peak_commit_mean_bytes | +0.0662% | [-0.0309%, +0.3099%] | 10.0000% |
| reordered.private_mean_bytes | +0.0846% | [-0.0940%, +0.3346%] | 10.0000% |

All eight formal intervals excluded a 10% practical gain and stayed within their matching regression guards. All 14 additional median resource checks passed. Executable size fell by 1.3802%, below the predeclared 10% footprint threshold. Result: `REJECTED_NO_QUALIFYING_PRIMARY_OR_SECONDARY_GAIN`. The candidate was not retained; the streak advanced once, from 26 to 27.

## Verification actually performed

- 21 Rust tests, strict all-target Clippy and formatting checks passed for this variant.
- Current candidate native journeys J02, J08 and J15 and the portable-import audit passed.
- The newly rebuilt control was byte-equivalent to the stored control after only an already sealed 32-byte PE timestamp/RSDS metadata mask. Single-byte `.text`, `.rdata` and `.data` mutations were rejected; metadata-only positive controls passed. No broader normalization was introduced.
- Full filename vectors and hashes, independent numeric natural-order UTF-16 path hashes, cancellation and Unicode checks passed. Deliberate order and payload mutations were rejected.
- Known 20 ms delay, threefold scan work, actual CPU counter reads and retained 32 MiB private/peak-memory controls passed. The detector was calibrated against changed work and memory rather than its own labels.
- Classifier controls rejected unresolved or weak guards, a possible practical gain, nonfinite sizes and an exactly 10% footprint gain as valid futility plateaus; demonstrated resource harm takes priority over an apparent gain.
- Protected source, Cargo files, default executable and distribution executable were restored to their pre-experiment hashes. Only owned temporary examples were removed.

Full 31-journey/600-second acceptance and original-base integration acceptance were intentionally not run after the frozen futility rule rejected this candidate. No merge, release, source optimization, cache-limit change or machine-setting change is proposed.

## Evidence fingerprints

These identify locally retained evidence. Raw reports and generated executables are not included in this PR. This report alone is not a standalone reproducible benchmark package.

- measured src/loader.rs: `fa1e691079ec0143aed86b4612f784fb6451fcdd0d9af2b2158bf300477742e8`
- protected default foto.exe: `3959d345fb591522237b5d317f274e9393107abf817ed468867795a4907a66c4`
- E049 decision.json: `8e2efa3b80d708e73b9a95f51162878dbb8db576f3a9a3833b8c7b424daf2d3b`
- E049 plan.json: `0656bc9cde9eb7498228b6c1d59256027f9d6ca554e45c06f65e2b8b701f99e2`
- E049 runtime-plan.json: `e5292496e20709b9bbddf1cedd7470022fe1b171a3756cb92c7ea51c346583b2`
- E049 runtime-manifest.json: `1df41e5db89301a6dbe2698b4122d5f78db44923532020a25bcb8b5366e833e0`
- E049 analysis.json: `36bfb087d8eec6ce8ce4e432b2719f9c61b4253fd476a9ba824426831bdc069c`
- E049 summary.json: `e17264c6d21598b8422c0f1b0127d89a2cf19a8099a6747b05b8efde7696a68d`

## Limits and revisit condition

This study does not establish cold-cache performance, Windows 10 behavior, human UAT, physical monitor/input behavior, native UI tail latency, build-time improvements or universal absence of regressions. Upstream now specifies a newer toolchain; historical local checks do not satisfy its current clean-commit verification gate. CI status for this documentation PR must be read separately.

Revisit this profile only with a materially different justified workload or mechanism and a new frozen protocol. Repeating unchanged conditions, expanding the compiler-unit search or opening this PR does not add a plateau.
