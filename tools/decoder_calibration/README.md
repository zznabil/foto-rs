# Decoder protocol calibration

This development tool checks whether the decoder measurement protocol and its controls work on a Windows x64 host. It measures one baseline executable. It does not compare candidates or establish performance, timing stability, a plateau, human UAT or release readiness.

Use the pinned Rust 1.98.1 and Python 3.14.7 development environment from `CONTRIBUTING.md`. Commit the source first. Run the portable checks, then one fresh native cohort:

```powershell
python -m unittest discover -s tools -p "test_decoder_calibration*.py" -v
python tools/calibrate_decoder.py
```

The native command refuses an existing `artifacts/decoder-calibration-v1` directory. It builds a disposable probe, checks kernel lifetime peak counters in a fresh process, and runs fifteen serial decoder controls: three exact raw path spellings times five modes. The paths contain 360, 364 and 287 UTF-16 units, including verbatim and normalizing spellings. Every run uses 512 decodes per batch and sixteen batches.

The five modes retain the normal-work window, one-second delay at batch eight, triple-work sensitivity, 32 MiB allocation sensitivity and exact one-byte payload mutation. The worker retains its 20-second header, 20-second payload and four-second exit limits. The build waits up to 1200 seconds and the fresh native peak setup waits up to 60 seconds; either can add a 30-second wait after killing a failed child. Full expected PBGRA bytes come from independently authored opaque quadrants for the committed synthetic fixture.

Source, toolchain, fixture, reference, executable, raw arguments, raw CPU/cycles, lifetime peaks, sampled resources and cleanup evidence are recorded. Any mismatch stops the cohort and preserves failure evidence. A failed or interrupted cohort is not a pass. Preserve its output; do not delete it for an unchanged retry. A reviewed method revision or a demonstrated host change needs a fresh checkout and separate evidence.

The shared package relocates existing worker, monitor, counter and guard implementations. Historical experiment folders are not runtime dependencies. Only repository imports, output wiring and provenance are portable; the existing measurement checks remain in force. `provenance.json` identifies their historical source and semantic closure. Portable tests use synthetic dictionary records and simulated processes; only the native command provides host-control evidence.

The guard wrapper calls `base_guards` directly. The former loader is removed. Original export hashes and equality claims remain archival records in `provenance.json`; `current_adoption` records the direct-call adaptation and current source hashes separately. Current shared helpers include the reporting and picker-readiness repairs. Their whole-file bytes differ from the export, but the listed FFI/resource segments retain exact AST equality. Source equality is not native-control evidence. Resource-monitor failures retain the original exception and traceback in the failure report and monitor cleanup record; every counter failure still rejects the cohort.

The separate GitHub Windows job uploads calibration JSON and logs. It excludes executables, Cargo targets, images and pixel files. Local output is retained locally. The job does not change the release verifier or its required checks.
