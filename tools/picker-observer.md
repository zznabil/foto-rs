# Picker state observer

`python tools/observe_picker.py` records one diagnostic attempt using the existing smoke flow through picker cancellation. Build the release executable and generate benchmark fixtures first, using the pinned development environment. Commit the source before running; the observer requires a clean checkout.

It first calibrates its HWND reader with a synthetic hidden, shown without activation, then destroyed dialog. It runs the unchanged smoke prelude and the original broad PID/class disappearance oracle with its eight-second wait and one picker-close message. It records the exact selected HWND and other matches, visibility, ownership, GUI-thread state, process exit state, post result and cleanup. It stops before later smoke phases. It never activates another window or substitutes a narrower success predicate.

The helper hashes bind this observer to the reviewed smoke/stress contract. A helper change requires review before updating those hashes. Observation adds overhead and can affect readiness. Each checkout permits one attempt; preserve failures instead of deleting output for an unchanged retry.

Outputs live in `artifacts/picker-observer-v1`. A diagnostic completion is not a full smoke pass, a reproduction of a prior failure, a root-cause finding, performance evidence, UAT or release acceptance. A process disappearance, observation error or incomplete cleanup cannot count as a valid picker diagnostic. The separate CI job retains JSON and timing CSV evidence, excluding photos and executable bytes.
