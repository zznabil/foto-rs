# Foto performance loop

Goal: improve latency and resources without detected regressions. Explicit user request: keep iterating until repetitive plateau.
Owner: foreground get-it-done; experiment supports measurement. No workers or remote publication.
Scope: reversible local source changes and synthetic-file testing. Preserve v1.0.0 and performance-start-1.0.1 baseline. No machine configuration, codecs or user photos changed.

Contract: each experiment changes one material variable, records hypothesis, artifact hashes and raw paired samples. Promotion needs >=10% lower memory or a latency gain >=max(10%, 2x unchanged-build noise), with <=5% material latency regression on other workloads and no regression test failures. Borderline effects get repeat samples; inconclusive changes revert. Three consecutive evaluated candidates without a useful retained improvement establish a local plateau, not global optimality. Stop count resets after promotion.
Workloads: warm launch 24 MP JPEG, two-photo cached navigation, three-photo traversal in both directions, native window pixel checks, working set/private/peak/CPU/handles/GDI. Alternating control/candidate order, same fixtures/window/settling, serial runs. Unchanged-build A/A calibrates noise before promotion.
Required final gates: fmt, strict all-target Clippy, Rust tests, portable imports, live smoke, twelve journeys/120s soak, 200 malformed/native accessibility, report/executable hashes, preserved baseline hashes, clean worktree and no remaining test viewers.

Phase: baseline calibration. Plateau counter 0/3. No experiments evaluated yet. Next: build paired benchmark and run unchanged-build A/A, then test allocator initialization, prefetch/cache pressure and render work based on observed bottlenecks.
Result: IN PROGRESS. Windows 11 only; warm-cache synthetic images; human UAT, Windows 10 and real monitor transfers unverified. Prior reports are history, not final gates for a changed artifact.

2026-10-20 decisions:
- Preflight archived baselines/performance-start-1.0.1 with manifest/source. Worktree was clean. No relevant memory hit.
- Initial AA run overlapped a compile, so excluded from promotion calibration. Valid serial AA: artifacts/optimization/1792494363194120500-AA-serial/report.json. Median group differences: internal launch 5.11%, external 0.44%, navigation 3.39%, CPU 4.49%, RSS 0.02%, peak 0.26%. Latency promotion thresholds internal >=10.22%, external/navigation >=10%; memory >=10%; other latency guard <=5% subject to repeat if borderline.
- E01 alloc_zeroed: rejected and reverted. Six-pair report artifacts/optimization/1792494436183099900-E01-zeroed/report.json. Startup and nav slightly slower; peak about9.7% lower, below threshold. Zero retained app changes.
- E02 previous-image reuse: provisional promotion. Six-pair report artifacts/optimization/1792494552990634300-E02-reuse-previous/report.json. CPU 2039.062 to1148.438ms (-43.7%); peak482459648 to417697792 bytes (-13.4%); cached traversal30.622 to30.350ms; all12 hits; launch+2.9% internal/+3.2% external, inside guard. Added byte-budget/pointer-reuse regression. Full confirmation still pending. Plateau counter reset0/3.
- E03 explicit opaque bitmap path: currently measuring against E02. Conservative RGB formats only; alpha/unknown formats retain premultiplied rendering. Must reject on material latency or pixel regressions.

- E03 rejected/reverted: artifacts/optimization/1792494684354491200-E03-opaque/report.json. Nav30.596 to30.321ms (<1%); launch175.861 to185.850ms (+5.7%), external+6.6%; no memory reduction. Plateau1/3.
- E04 hypothesis: stale/empty ready notifications and unchanged toolbar states cause redundant paint work; skip only notifications with no accepted state change and unchanged enabled states. Measuring against E02, same six-pair matrix. No promotion yet.
- Next separating test if E04 fails: defer worker codec factories until their first actual job. Expected empty-window resource improvement; preserve eager thread failure reporting and all real decode behavior. Add a separately calibrated empty-window metric before observing candidate outcomes.

- E04 rejected/reverted: artifacts/optimization/1792494793534648300-E04-redraw/report.json. Nav32.499 to32.486ms (<0.1%); CPU1015.625 to1085.938ms; no resource improvement; external+5.6%. Plateau2/3.
- Empty-window AA calibration: artifacts/optimization/1792494895590475800-AA-empty/report.json. Empty RSS32,176,128 vs31,100,928 bytes (3.34% noise); private8,470,528 vs9,377,792 (10.71%); first-paint111.919 vs123.483ms (10.33%). E05 thresholds before candidate measurement: >=10% empty RSS reduction, or >=21.43% empty private reduction; latency must beat2x metric noise (empty20.67%, launch10.22%, navigation10%) and no material other-workload slowdown. Added optional --empty; all E05 control/candidate runs use the same extended method.

- E05 rejected/reverted: artifacts/optimization/1792494956414043800-E05-lazy-codecs/report.json. Empty RSS32,258,048 to31,098,880 (-3.6%, below10%); empty paint130.732 to130.080ms; photo launch187.125 to193.784ms; navigation30.285 to30.244ms. No qualifying benefit. Plateau3/3 achieved after E03/E04/E05; stop candidate search.
- Final source now E02 only plus reuse regression test and version1.0.2. Negative-control test deliberately omitting cache reinsert fails1/1 as expected; restored code passes14/14. First mutation attempt had CRLF encoding damage and failed compilation, so excluded; retained invalid log for transparency. Correct byte-preserving mutation proves the test observes missing reuse.
- Final build gates all pass: artifacts/optimization/final-build-gates.json. Fresh eight-pair control1.0.1 vs final1.0.2 comparison currently running with empty-window metrics. Final stress/smoke/malformed and package-integrity gates remain required. No DONE claim yet.

## Final result

DONE. Plateau3/3 reached (E03/E04/E05) after retaining E02. No global-optimum claim. No action needed.

Fresh final comparison: artifacts/optimization/1792495104226787300-final-1.0.2/report.json (eight AB/BA pairs with empty-window metrics). CPU2046.875 to1031.250ms (-49.618%); peak477427712 to417665024 bytes (-12.518%); steadyRSS essentially unchanged; internal launch+1.18%, external+4.934%, nav+0.43%, all within5% material guard. No startup speedup claimed. All96 traversals per binary hit cache.

Final acceptance ledger (foreground owner; this Windows11 host; fresh):
- P1 baseline preservation PASS: both manifest file sets verified; v1.0.0 tag unchanged.
- P2 paired performance PASS: final comparison and threshold assertions; candidate hash matches package.
- P3 plateau PASS: E03/E04/E05 measured and reverted, following E02 improvement.
- P4 build/correctness PASS: fmt, strict all-target Clippy,14 Rust tests; missing-reuse negative control fails as expected.
- P5 live smoke PASS:16 checks;10 launches; new/control two-photo cached22.62/25.49ms; no cold-start claim.
- P6 journeys PASS: artifacts/hardening/20261020-192115-10160/report.json, all12 charters,120-second soak,30 cycles,2,000 keys,30 drops,10,000 entries,20 simulated DPI notifications.
- P7 malformed/native accessibility PASS: artifacts/hardening/20261020-192410-34620/malformed-report.json,200 inputs, valid recovery,8 named native buttons with actual Invoke.
- P8 package/operations PASS: current report hashes, checksums and portable imports verified; no test viewers running.

Progress: acceptance stages planned8, processed8, passed8, failed0, blocked0, skipped0, not-tested0. [####################] 8/8; verdict PASS within limits.

Resume: local plateau, not budget or approval stop. No optimization attempt remains in flight. Preserve current commit and all baselines. Reopen only with new profiling evidence or a distinct workload; do not rerun rejected candidates without a new mechanism. Windows10, real monitor transfers, human UAT and prolonged multi-day soak remain unverified. No persistent scheduler installed.

Recovery: run baselines/performance-start-1.0.1/foto.exe; frozen v1.0.0 remains available. Distribution1.0.2: dist/foto.exe, PERFORMANCE.md and packaged reports/checksums. Final source/reports are committed locally after this ledger is written; final clean-worktree readback is required before closing the goal.
