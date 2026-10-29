# SPDX-License-Identifier: GPL-3.0-or-later
"""Exercise the hosted preparation gate without changing antivirus policy."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
PWSH = shutil.which("pwsh")


@unittest.skipUnless(PWSH, "PowerShell is required for Defender preparation controls")
class DefenderPreparationControls(unittest.TestCase):
    def run_control(self, *, update_code=0, antivirus=True, realtime=True, hosted=True):
        # Only the unsafe OS boundaries are replaced. The actual gate script executes.
        command = r"""
$ErrorActionPreference = 'Stop'
$script:policyCalls = 0
$script:updateCalls = 0
function Set-MpPreference { param([bool]$DisableRealtimeMonitoring) $script:policyCalls++ }
function Get-ChildItem {
    param($Path, [switch]$File)
    [pscustomobject]@{ FullName = 'Invoke-UpdateControl'; Directory = [pscustomobject]@{ Name = '4.18.26090.9-0' } }
}
function Invoke-UpdateControl {
    param([switch]$SignatureUpdate, [switch]$MMPC)
    $script:updateCalls++
    $global:LASTEXITCODE = [int]$env:FOTO_CONTROL_UPDATE_CODE
}
function Get-MpComputerStatus {
    [pscustomobject]@{
        AntivirusEnabled = $env:FOTO_CONTROL_AV -eq 'true'
        RealTimeProtectionEnabled = $env:FOTO_CONTROL_RTP -eq 'true'
        AntivirusSignatureVersion = 'control-signature'
    }
}
$ok = $false
$message = $null
try { & $env:FOTO_PREPARATION_SCRIPT; $ok = $true }
catch { $message = $_.Exception.Message }
[ordered]@{ ok = $ok; error = $message; policy_calls = $script:policyCalls; update_calls = $script:updateCalls } | ConvertTo-Json -Compress
"""
        env = os.environ | {
            "GITHUB_ACTIONS": "true" if hosted else "false",
            "ProgramData": str(ROOT),
            "FOTO_CONTROL_UPDATE_CODE": str(update_code),
            "FOTO_CONTROL_AV": str(antivirus).lower(),
            "FOTO_CONTROL_RTP": str(realtime).lower(),
            "FOTO_PREPARATION_SCRIPT": str(ROOT / "tools/prepare_defender.ps1"),
        }
        result = subprocess.run(
            [PWSH, "-NoProfile", "-NonInteractive", "-Command", command],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout.splitlines()[-1]), result.stdout

    def test_successful_update_with_active_protection_is_the_positive_control(self):
        record, output = self.run_control()
        self.assertTrue(record["ok"], record)
        self.assertIn("FOTO_DEFENDER_PREPARATION_PASS", output.splitlines())
        status = json.loads(output.splitlines()[-3])
        self.assertTrue(status["AntivirusEnabled"])
        self.assertTrue(status["RealTimeProtectionEnabled"])

    def test_update_failure_blocks_the_success_marker(self):
        record, output = self.run_control(update_code=23)
        self.assertFalse(record["ok"])
        self.assertIn("exit code 23", record["error"])
        self.assertNotIn("FOTO_DEFENDER_PREPARATION_PASS", output.splitlines())

    def test_either_disabled_protection_state_blocks_the_success_marker(self):
        for antivirus, realtime in [(False, True), (True, False), (False, False)]:
            with self.subTest(antivirus=antivirus, realtime=realtime):
                record, output = self.run_control(
                    antivirus=antivirus, realtime=realtime
                )
                self.assertFalse(record["ok"])
                self.assertIn("protection is unavailable", record["error"])
                self.assertNotIn("FOTO_DEFENDER_PREPARATION_PASS", output.splitlines())

    def test_local_invocation_refuses_before_any_policy_or_update_action(self):
        record, output = self.run_control(hosted=False)
        self.assertFalse(record["ok"])
        self.assertIn("restricted to GitHub Actions", record["error"])
        self.assertEqual(record["policy_calls"], 0)
        self.assertEqual(record["update_calls"], 0)
        self.assertNotIn("FOTO_DEFENDER_PREPARATION_PASS", output.splitlines())


if __name__ == "__main__":
    unittest.main()
