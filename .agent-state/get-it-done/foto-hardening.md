# Foto baseline and hardening

Goal: preserve the user-approved viewer as v1.0.0, then test, audit and repair real usage paths while retaining its minimal native design and speed.

Owner: foreground agent, get-it-done primary. Release supports baseline packaging. No delegated workers or external publication.

Authorisation: user requested the v1.0 baseline and continued stress testing, dogfooding, UAT, user journeys, audit, review, debugging and repairs. Local versioning, archives, tests and reversible repairs are in scope. No changes to file associations, machine security, installed codecs, power policy or user photo files. No publication or pushes.

Baseline: accepted executable SHA256 98babf4eac6aca68dfc502e437ebe4325ba9b89bcb479aec1cfd847d63de88a1. The original source and distribution are archived at baselines/accepted-original.zip before version edits. Rust 1.98.1 MSVC; Windows 11 Enterprise LTSC build 26100. Workspace initially had no Git repository or unrelated edits.

Plan:
1. Build, verify and freeze v1.0.0 with a local source checkpoint and archive.
2. Review lifecycle, cache, decoder and input handling. Record falsifiable defects.
3. Run the twelve journey charters below against the baseline, repair reproduced defects, and retain regressions.
4. Rebuild a separate patch release, rerun gates, compare measurements and preserve raw evidence.

Acceptance ledger and coverage manifest (owner: foreground agent):

| ID | Charter / observable | Verifier | Current state |
| --- | --- | --- | --- |
| B1 | Frozen v1.0.0 source/executable/checksums agree | archive and hash readback; local Git checkpoint | IN-FLIGHT |
| J01 | First use, picker, cancel, Unicode paths, repeated explicit opens | actual native windows and pixel checks | WAITING |
| J02 | Folder browsing, numeric order, filename case and mixed entries | real folder fixtures and title/pixel checks | WAITING |
| J03 | Zoom, pan, fit, actual pixels and rotation | actual input and coordinate/pixel oracle | WAITING |
| J04 | Full screen from normal/maximised/minimised windows; restore | native style/rect/state readback | WAITING |
| J05 | Rapid keys, holds, drops and superseded decodes | bounded seeded sequences; selected-file pixels | WAITING |
| J06 | Corrupt, truncated, missing, renamed and externally changed files | negative cases paired with valid recovery | WAITING |
| J07 | Alpha, formats, orientation, extreme dimensions | decoder fixtures and selected rendered pixels | WAITING |
| J08 | Large directories and cancellation | bounded generated folder; responsiveness/readback | WAITING |
| J09 | Long sessions, repeated open/close, CPU/memory/GDI/handle use | process counters and bounded soak | WAITING |
| J10 | Keyboard-only controls, focus and native accessibility names | native focus/UI Automation inspection | WAITING |
| J11 | DPI/layout/device lifecycle and display recovery | current-display tests plus simulated notifications, labelled as simulation | WAITING |
| J12 | Packaging, diagnostics integrity, no writes to source photos | import audit, negative control, hashes, local smoke | WAITING |

Definition of done for this bounded wave: every charter processed with an explicit verdict and evidence; reproduced in-scope defects repaired or named as unresolved; changed paths have fresh regression gates; patch executable/report/checksum match; v1.0 baseline still matches its frozen hashes; no test viewers remain running.

Evidence: raw test runs remain under artifacts/. Baseline assets remain under baselines/. Source-controlled audit report will link exact reports and disclose failed attempts. Historical measurements are not current gates after edits.

Progress: Baseline 0/1; journey charters planned 12, processed 0, passed 0, failed 0, blocked 0, skipped 0, not tested 12. Progress is processing, not a verdict.

Known limits: no separate Windows 10 host, multi-monitor hardware or human UAT participants are available in this session. Simulated DPI messages are not hardware coverage. These limits must remain explicit in the report; do not claim universal compatibility or human acceptance.

Resume: baseline freeze in progress. Next action: run the v1.0.0 release gates and archive it before applying behavioural repairs.

Result: IN PROGRESS. No user decision is currently needed.
