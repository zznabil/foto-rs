# Foto baseline and hardening

Result: DONE for the bounded wave on 2026-10-20.

Authorization: freeze accepted v1.0, then stress test, dogfood, audit, debug and repair. No remote publication or machine configuration changes. No delegated workers.

Baseline: annotated local tag v1.0.0; commit 96170d5c18e0dc7778c038fbe9a248a5e7bdb6a1. baselines/v1.0.0 contains frozen distribution, source and nine-file hash manifest, reverified unchanged. Original archive: baselines/accepted-original.zip.

Current: 1.0.1. Four defects repaired: alternate-case duplicate entry, fullscreen auto-repeat, Enter activation, long WIC paths. See AUDIT.md and CHANGELOG.md.

Acceptance: B1 PASS; J01-J12 PASS. Progress [####################] 20/20 stages processed. Verdict PASS within limits. 13 Rust tests, strict Clippy, fmt, portability, 16 live smoke checks, twelve charters, 200 malformed trials and actual native UI Automation Invoke passed. Packaged reports and executable hashes agree.

Evidence: artifacts/verification.json; artifacts/hardening/20261020-174902-22352/report.json; artifacts/hardening/20261020-174929-31132/malformed-report.json. Negative control reproduced all four defects: artifacts/hardening/20261020-174350-30324/report.json. Managed UIA and screen/focus oracle false positives were refuted/calibrated; experimental product changes removed.

Limits: Windows 11 only. DPI simulated on current monitor. Human UAT, Windows 10 and real monitor transfers unverified. Soak bounded to 120 seconds. No scheduler installed.

Resume: this wave is complete. Preserve v1.0.0. Next useful coverage requires Windows 10/multi-monitor hardware or human UAT observations. Compare new findings with the local repair commit and retain representative negative controls.
