# Changes

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
