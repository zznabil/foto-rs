# Security policy

Use the latest stable release. Security fixes are made on the latest supported 1.x source; older releases may not receive backports. Windows and installed image codecs must be maintained by the user or system administrator.

## Report a vulnerability

Use [GitHub's private vulnerability reporting](https://github.com/zznabil/foto-rs/security/advisories/new). Include the affected version, reproduction steps and a minimal synthetic sample where possible. Do not post credentials, private photos or exploit details in a public issue before coordination. Response is best effort; no response-time or commercial support SLA is promised.

## Boundaries

Foto opens untrusted files through Windows codecs. Decoded image buffers are bounded, but codecs and Windows libraries have their own allocations. Malformed-image testing and dependency checks are scoped evidence, not certification or a guarantee against all malicious files. The application does not edit photos or require administrator privileges.

GitHub Actions use pinned action commits and limited job permissions. Release tags require the exact merged-main CI result, followed by fresh tagged tests. A draft is published only after an independent runner downloads and verifies the assets, checks GitHub provenance against the source tag/commit, and tests the downloaded executable. The Windows executable is not Authenticode-signed.
