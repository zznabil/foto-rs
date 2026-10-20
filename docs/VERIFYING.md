# Verify a release

Download the Windows ZIP, `SHA256SUMS.txt` and optional source/inventory records from the same [release page](https://github.com/zznabil/foto-rs/releases/latest).

## Check integrity

```powershell
Get-FileHash .\Foto-1.0.3-windows-x64.zip -Algorithm SHA256
```

Compare the result with the matching entry in `SHA256SUMS.txt`. The portable ZIP also contains an internal checksum ledger, fresh test reports, build metadata and third-party notices.

## Check build provenance

With a current GitHub CLI, verify the artifact against this repository and release workflow:

```powershell
gh attestation verify .\Foto-1.0.3-windows-x64.zip --repo zznabil/foto-rs --signer-workflow zznabil/foto-rs/.github/workflows/release.yml --source-ref refs/tags/v1.0.3 --deny-self-hosted-runners
```

For an exact-source policy, add `--source-digest COMMIT`, using the full commit from the release's `build-info.json` and protected tag. Provenance is verified for the ZIP and JSON release records. `provenance.jsonl` is the downloadable attestation bundle. The checksum ledger and bundle are not claimed to attest themselves.

A digest identifies bytes. Provenance identifies the source/workflow that produced them. Neither proves safety, Windows signing, human acceptance or reproducibility. No SLSA level, security certification or byte-identical independent-build claim is made.

## Rebuild the supplied source

Extract `Foto-1.0.3-source.zip`. It contains the project, original build scripts, lockfile, vendored Cargo dependencies and source-specific Cargo configuration. With the pinned Rust toolchain, its rust-docs notices and Microsoft build tools already installed:

```powershell
cargo build --locked --release --offline
cargo test --locked --offline
```

CI repeats this with an empty Cargo home, checks the rebuilt executable and runs native-window smoke tests. `source-verification.json` records that result. The source ZIP's Cargo configuration is extended only to select its included vendor directory. Compiler/linker paths and timestamps may differ between machines; byte identity is not promised.
