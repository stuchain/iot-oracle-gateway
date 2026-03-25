#Requires -Version 5.1
<#
.SYNOPSIS
  Phase 7.1 burst experiment runner (human-assisted).

  Expected behavior:
  - msgs_per_sec rises during burst window
  - z_score rises during burst
  - is_anomaly becomes 1 in at least one window

  Prerequisites (start these in separate terminals):
  1) Mosquitto: mosquitto -c mosquitto/mosquitto.conf
  2) Ganache:   npx ganache --port 8545
  3) Deploy contract if needed:
       cd contracts; npm install; npx hardhat compile
       npx hardhat run scripts/deploy.js --network localhost
  4) Oracle:    python -m oracle.service
  5) Optional dashboard: streamlit run dashboard/app.py

  This script starts only the simulator for the burst run.

.PARAMETER RunSeconds
  Duration to run the simulator (default 180 = 3 minutes).

.EXAMPLE
  .\scripts\run_experiment_burst.ps1
  .\scripts\run_experiment_burst.ps1 -RunSeconds 150
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

Write-Host 'Starting BURST experiment (Phase 7.1)'
Write-Host 'Params:'
Write-Host '  N_DEVICES=8 INTERVAL_SEC=1'
Write-Host '  BURST_ENABLED=true BURST_START_SEC=60 BURST_DURATION_SEC=20 BURST_MULTIPLIER=5'
Write-Host "Duration: ${RunSeconds}s"
Write-Host ''
Write-Host 'If prerequisites are not running yet, stop now (Ctrl+C) and start them first.'
Start-Sleep -Seconds 2

$env:N_DEVICES = '8'
$env:INTERVAL_SEC = '1'
$env:BURST_ENABLED = 'true'
$env:BURST_START_SEC = '60'
$env:BURST_DURATION_SEC = '20'
$env:BURST_MULTIPLIER = '5'

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
Write-Host 'Burst run ended. Check:'
Write-Host '- data/telemetry_windows.csv (spike in msgs_per_sec, z_score rise, is_anomaly=1)'
Write-Host '- GET /metrics from oracle for latest anomaly status'
