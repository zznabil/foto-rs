# Release procedure

Reader: the repository maintainer. Task: publish a version whose source, CI, binary, notices and checksums agree.

## Prepare and merge

1. Update Cargo.toml/Cargo.lock, CHANGELOG.md and `docs/releases/vX.Y.Z.md` in a PR. Do not move existing tags.
2. Run repository/verifier checks and the complete Windows gate. The package carries GPL notices, complete vendored project/dependency source, Rust library notices and an SPDX inventory with its scope stated.
3. Merge only after required PR checks pass and conversations are resolved. The solo-maintainer policy requires a PR and checks, but no independent approval is implied.
4. Wait for the exact merged-main CI run to pass. An earlier PR or branch run does not replace it.

## Tag and publish

Push an annotated `vX.Y.Z` tag at the tested main commit. Tag updates and deletions are protected. Tags authorize the automated release workflow; only maintainers with write access should create them.

The Release workflow verifies the version/tag/main-CI relationship, repeats the full Windows and dependency gates, packages the tested executable, and validates an isolated offline rebuild of the vendored source. It creates GitHub-hosted build attestations and stages a draft release. A second Windows runner independently downloads all assets, compares GitHub asset digests and local checksum ledgers, verifies provenance against the workflow/ref/commit and runs the downloaded executable's critical journeys. Only then does it publish the stable latest release.

The Windows binary is unsigned by Authenticode. Do not claim signing, a certification, a SLSA level, universal Windows compatibility or reproducible bytes from checksum/provenance checks.

## Hold and recovery

A failed gate leaves the release unpublished, or retains a draft for investigation. Never publish manually to bypass a failed gate. Do not overwrite already-published assets or move a public version tag. Preserve logs and repair through a new reviewed version if the protected tag already exists.

For a post-publication defect, point users to the prior release and ship a corrected patch. Do not silently replace executable bytes at the same version. The accepted v1.0.0 source and earlier local archives are historical checkpoints; their old reports do not validate a new release.
