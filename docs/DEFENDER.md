# Defender detection and release checks

On 2026-10-21, Microsoft Defender detected Foto 1.0.2 as
`Trojan:Win32/Bearfoos.A!ml`. The affected local distribution has SHA-256
`8bdced0523cdd5d9dd83fb8cca72f524bf1dcc17000ba686600685ce2e5b0fce`.
Its hash matches the recorded 1.0.2 build. Defender reported successful quarantine.

Diagnostic scans with engine 1.1.26090.9 and signatures 1.461.118.0 reproduced
the detection on 1.0.2. Preserved 1.0.0 and 1.0.1 builds, two newer local builds,
and a fresh 1.0.3 build returned explicit no-threat results. An update check
reported no newer signatures. These results identify affected bytes; they do
not prove a false positive or guarantee future antivirus verdicts.

The reviewed application source uses native Windows image decoding, rendering,
folder enumeration and window controls. No downloader, persistence mechanism,
process injection or embedded executable payload was found in that review.
The executable remains unsigned. The exact reason for Microsoft's classifier
decision is unknown. No application behavior was changed merely to alter its
antivirus classification.

## Release checks

Windows verification runs `tools/check_defender.py` before native smoke tests.
The publication job scans the independently downloaded executable too. The
checker records engine/signature versions, command output and executable hashes.
It requires a successful process, an explicit no-threat result, active antivirus
and real-time protection, and unchanged file bytes. Detection, missing access,
unexpected output or scanner failure blocks that gate.

Hosted CI and publication runners first run `tools/prepare_defender.ps1`.
It enables real-time protection, updates security intelligence through the
installed `MpCmdRun.exe -SignatureUpdate -MMPC` command, and observes actual
antivirus and real-time protection for up to 30 seconds. Both flags must be
enabled before preparation passes. An expired activation wait reports both
flags and blocks the job. This bounded observation does not retry the policy
change or signature update, and does not guarantee that a runner can activate
protection. The former `Update-MpSignature` route failed with RPC errors on
hosted runners before project verification. An update failure still blocks
the job; there is no ignored error or stale-definition fallback.
The preparation script refuses to run outside GitHub Actions. Local
verification does not change Defender policy.

Microsoft documents the [native update command](https://learn.microsoft.com/defender-endpoint/command-line-arguments-microsoft-defender-antivirus)
and the actual protection fields returned by
[`Get-MpComputerStatus`](https://learn.microsoft.com/powershell/module/defender/get-mpcomputerstatus).

The diagnostic scan uses Microsoft's documented custom-scan
`-DisableRemediation` option. It ignores file exclusions and reports detections
without applying scan remediation. It does not disable real-time protection or
restore quarantined files. Real-time protection remains active throughout.

The checker was tested with the detected 1.0.2 binary as a negative control and
the fresh 1.0.3 binary as a positive control. A successful scan is evidence for
those bytes and those definitions, not security certification.

## If Windows blocks Foto

Keep protection enabled and retain the detection name, file hash and signature
version. Do not add an exclusion or restore a file solely on the strength of
this document. Check the exact release's provenance and current scan results.
Microsoft's developer submission process is the route for disputing a detection;
only a completed Microsoft determination can establish their classification
decision. A new build passing a scan does not clear an older flagged build.

References: [Microsoft developer FAQ](https://learn.microsoft.com/en-us/defender-xdr/developer-faq),
[Defender scan options](https://learn.microsoft.com/en-us/defender-endpoint/command-line-arguments-microsoft-defender-antivirus),
[Microsoft file submission](https://www.microsoft.com/en-us/wdsi/filesubmission).
