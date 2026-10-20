# Foto 1.0.1 hardening audit - 2026-10-20

Verdict: PASS for this bounded Windows 11 hardening wave. The user-approved viewer is frozen as v1.0.0. The 1.0.1 patch repairs four reproduced defects. No remote release was published.

## Findings

| Finding | Trigger and prior behavior | Repair | Regression |
| --- | --- | --- | --- |
| H01 | Open PHOTO1.PNG when the entry is photo1.png; Next selects a duplicate | Resolve the selected file on the directory worker and retain one entry | Rust test; J02 |
| H02 | Hold F11; repeated keydown toggles fullscreen back off | Ignore repeated fullscreen keydown | J04 |
| H03 | Tab to Next and press Enter; photo does not change | Activate enabled focused child buttons with Enter | J10 |
| H04 | Open an existing normal absolute path longer than 260 characters; WIC fails | Resolve an extended path on the decoding worker | Real-file Rust test; J01 |

All four failures reproduce with the frozen baseline using the calibrated verifier: artifacts/hardening/20261020-174350-30324/report.json. It exits unsuccessfully without a success marker. The corresponding repaired journeys pass.

## Review and verifier calibration

Review covered decoding/allocation bounds, stale-load cancellation, cache ownership, directory scanning, keyboard handling, fullscreen restoration, rendering lifecycle and portable dependencies. Synthetic images and generated folders were used. Source fixture hashes were checked. No user photos, file associations, installed codecs or machine policy were changed.

Early physical-screen pixel checks could sample an unrelated window. The verifier now captures only the viewer client with PrintWindow. Early focus tests sent messages to the wrong recipient; they now target the focused button. These were test-oracle defects, not additional product repairs.

A managed UI Automation client incorrectly reported generic panes. Independent native COM UI Automation verified eight named Button controls, Invoke patterns and enabled keyboard-focus support on both baseline and repaired builds. The application finding was refuted. Experimental accessibility changes were removed. The retained native probe actually invokes Fit and verifies resulting pixels.

## Final evidence

- Formatting, strict Clippy on all targets, 13 Rust tests and portable import audit: PASS.
- baselines/performance-start-1.0.1/verification.json: 16 live-window checks, 10 launch and 10 cached-navigation samples: PASS.
- artifacts/hardening/20261020-174902-22352/report.json: all twelve journey charters: PASS. Includes 2,000 rapid navigation inputs, 30 drops, 10,000 folder entries, 30 open/close cycles and 20 simulated DPI notifications.
- artifacts/hardening/20261020-174929-31132/malformed-report.json: 200 bounded mutations, 170 decoded or partially decoded, 30 rejected; valid recovery and native accessibility Invoke: PASS.
- All nine frozen v1.0.0 manifest hashes and its local source tag: unchanged.

The malformed corpus preserves dimension-bearing headers. Partial decoding is permitted if dimensions remain bounded and valid-image recovery succeeds. This is not a security certification or exhaustive codec fuzzing. Its before/after resource counters also include loading a 24 MP image and activating UI Automation, so they are not a matched leak comparison.

Final soak: 120 seconds, 2359 actions; GDI 14 to 14, handles 233 to 233, USER 19 to 19. Peak working set 491.3 MiB; idle CPU 0.0 ms over one second. The 192 MiB cache cap is not a process memory cap.

Warm-cache medians: externally observed first image 146.53 ms, internal first draw 115.18 ms, cached navigation 12.28 ms. The separate baseline external median was 125.59 ms. The later run is slower; these separate runs do not isolate a causal regression. Benchmarks ran separately; the malformed run briefly overlapped the soak.

## Limits

Automated agent-operated journeys are not human UAT. Windows 10, real multi-monitor transfers, hardware DPI transitions and image-content screen-reader access remain unverified. Warm-cache synthetic JPEG timings do not establish cold-start latency. A 120-second soak cannot establish behavior over days. No unresolved reproduced product defect remains in these charters. Earlier raw failed runs remain under artifacts/hardening; only the named final reports gate this build.

The tested 1.0.1 executable and its reports are preserved under baselines/performance-start-1.0.1. The current distribution is now 1.0.2; see PERFORMANCE.md for the later measured optimization and fresh regression results. See BASELINE.md for the frozen v1.0.0 source and executable.
