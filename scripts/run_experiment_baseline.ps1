#Requires -Version 5.1
<#
.SYNOPSIS
  Phase 7.1 baseline experiment runner (human-assisted).

  Expected behavior:
  - Stable msgs_per_sec (roughly N_DEVICES / INTERVAL_SEC)
  - Low z_score values
  - is_anomaly mostly 0

  Prerequisites (start these in separate terminals):
  1) Mosquitto: mosquitto -c mosquitto/mosquitto.conf
  2) Ganache:   npx ganache --port 8545
  3) Deploy contract if needed:
       cd contracts; npm install; npx hardhat compile
       npx hardhat run scripts/deploy.js --network localhost
  4) Oracle:    python -m oracle.service
  5) Optional dashboard: streamlit run dashboard/app.py

  This script starts only the simulator for the baseline run.

.PARAMETER RunSeconds
  Duration to run the simulator (default 180 = 3 minutes).

.EXAMPLE
  .\scripts\run_experiment_baseline.ps1
  .\scripts\run_experiment_baseline.ps1 -RunSeconds 120
#>
param(
    [int]$RunSeconds = 180
)

$ErrorActionPreference = 'Stop'
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

$py = if (Get-Command python -ErrorAction SilentlyContinue) {
    (Get-Command python).Source
} elseif (Get-Command python3 -ErrorAction SilentlyContinue) {
    (Get-Command python3).Source
} else {
    throw 'python or python3 not found on PATH.'
}

Write-Host 'Starting BASELINE experiment (Phase 7.1)'
Write-Host 'Params: N_DEVICES=8 INTERVAL_SEC=1 BURST_ENABLED=false'
Write-Host "Duration: ${RunSeconds}s"
Write-Host ''
Write-Host 'If prerequisites are not running yet, stop now (Ctrl+C) and start them first.'
Start-Sleep -Seconds 2

$env:N_DEVICES = '8'
$env:INTERVAL_SEC = '1'
$env:BURST_ENABLED = 'false'

# Inherit console so simulator logs appear here (Start-Process -NoNewWindow often does not).
$proc = New-Object System.Diagnostics.Process
$proc.StartInfo.FileName = $py
$proc.StartInfo.Arguments = '-m simulator.iot_simulator'
$proc.StartInfo.WorkingDirectory = $RepoRoot
$proc.StartInfo.UseShellExecute = $false
$proc.StartInfo.RedirectStandardOutput = $false
$proc.StartInfo.RedirectStandardError = $false
[void]$proc.Start()
$timeoutMs = [Math]::Max(1000, $RunSeconds * 1000)
if (-not $proc.WaitForExit($timeoutMs)) {
    $proc.Kill()
    $null = $proc.WaitForExit(5000)
}

Write-Host ''
Write-Host 'Baseline run ended. Check:'
Write-Host '- data/telemetry_windows.csv (msgs_per_sec stability, low z_score)'
Write-Host '- GET /metrics from oracle for latest window + anomaly fields'
