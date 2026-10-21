# Changes

## 1.0.5

- Update the development-only SPDX validation dependency rpds-py from 2026.6.3 to 2026.9.1 with verified PyPI artifact hashes.
- Viewer features and runtime dependencies are unchanged.

## 1.0.4

- Update the fixture-generation dependency to Pillow 13.0.0, addressing nine GitHub advisories including a critical JPEG decoder issue. Pillow is not shipped in the viewer.
- Check all exact Python development pins against PyPI's version-specific advisory feed in CI and scheduled runs, alongside GitHub dependency review and Dependabot alerts.
- Resolve unpublished GitHub releases through their numeric release ID before downloading and verifying them. The release-by-tag REST endpoint excludes drafts.
- Report actual publication state separately from whether the verifier performed publication.
- First public release; includes the viewer and release safeguards prepared for the unpublished 1.0.3 candidate.

## 1.0.3

Unpublished candidate. Its tagged build passed, but publication stopped at draft lookup. Superseded by 1.0.4.

- Add Defender scans of built and independently downloaded executables; retain hash-bound scan evidence and block detected or inconclusive results. Document the 1.0.2 detection and its limits in docs/DEFENDER.md.
- Validate inventories against the pinned official SPDX schema and preserve identical metadata bytes inside ZIPs and detached assets on Windows.
- Fix toolbar clipping on small/high-DPI desktops by wrapping native controls into additional rows.

- Publish the GPL-3.0-or-later GitHub project with contributor and security guidance.
- Add native Windows product/file version metadata.
- Add pinned CI, minimum-Rust compilation, dependency checks, protected merge/release procedures, and automated draft-to-public verification.
- Package portable Windows binaries, complete vendored corresponding source, third-party notices, SPDX inventory, checksums and GitHub provenance.
- Label runner environments accurately and generate benchmark inputs without rewriting committed fixtures.
- Preserve the viewer behavior and existing decoded-image reuse optimization.

## 1.0.2

- Reuse the previously displayed decoded image after cache eviction during navigation, reducing redundant decoding without changing image quality or cache limits.
- Measured about 50% lower browsing CPU time and 12.5% lower peak working set in the paired three-photo workload. Steady-state memory was unchanged; startup was not faster.
- Added a regression for allocation reuse, selected-image survival and cache bounds, plus a paired native-window benchmark.
- Evaluated five optimization candidates. Reverted four and stopped after three consecutive candidates failed promotion. See PERFORMANCE.md for evidence and limits.

## 1.0.1

- Open existing photos whose normal Windows paths exceed 260 characters.
- Avoid a duplicate folder entry when the selected filename uses alternate casing.
- Ignore repeated fullscreen toggle keydown events while a key is held.
- Activate focused toolbar buttons with Enter.
- Add automated journey, resource-soak, malformed-image and native accessibility checks. Capture test-window pixels independently of other desktop windows.

## 1.0.0

Frozen user-approved native photo viewer baseline. See BASELINE.md.
