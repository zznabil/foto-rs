# SPDX-License-Identifier: GPL-3.0-or-later
# This changes protection policy only on disposable GitHub-hosted runners.
$ErrorActionPreference = 'Stop'
if ($env:GITHUB_ACTIONS -ne 'true') {
    throw 'Defender preparation is restricted to GitHub Actions; local verification only scans.'
}

Set-MpPreference -DisableRealtimeMonitoring $false
$platform = Join-Path $env:ProgramData 'Microsoft/Windows Defender/Platform'
$scanner = Get-ChildItem (Join-Path $platform '*/MpCmdRun.exe') -File |
    Sort-Object { [version](($_.Directory.Name -split '-')[0]) } -Descending |
    Select-Object -First 1
if (-not $scanner) { throw 'Installed Defender platform command was not found' }

# Use the supported native update path, not the failing WMI/Windows Update route.
# MMPC contacts Microsoft directly; there is no ignored error, retry or stale-data fallback.
& $scanner.FullName -SignatureUpdate -MMPC
$updateExitCode = $LASTEXITCODE
if ($updateExitCode -ne 0) {
    throw "Defender security intelligence update failed with exit code $updateExitCode"
}
$status = Get-MpComputerStatus
if (-not $status.AntivirusEnabled -or -not $status.RealTimeProtectionEnabled) {
    throw 'Defender protection is unavailable'
}
$status | Select-Object AMProductVersion, AMEngineVersion, AntivirusSignatureVersion,
    AntivirusSignatureLastUpdated, AntivirusEnabled, RealTimeProtectionEnabled |
    ConvertTo-Json -Compress
Write-Output 'FOTO_DEFENDER_PREPARATION_PASS'
