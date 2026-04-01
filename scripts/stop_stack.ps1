#Requires -Version 5.1
<#
.SYNOPSIS
  Stops local processes listening on the IoT Oracle stack ports (dev cleanup).

.DESCRIPTION
  Use after closing the cmd windows from run.bat, or when the next run.bat fails
  with "port already in use". Kills LISTENING processes on 8545, 1883, 8000, 8501.

  WARNING: This ends whatever is bound to those ports (not only this project).
  Close the stack consoles first; use this script to clear stuck listeners.

.PARAMETER Force
  Do not prompt; stop matching processes immediately.
#>
param(
    [switch]$Force
)

$ErrorActionPreference = 'Stop'

$StackPorts = @(8545, 1883, 8000, 8501)

function Get-ListeningPidsForPort {
    param([int]$Port)
    $set = [System.Collections.Generic.HashSet[int]]::new()
    try {
        Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | ForEach-Object {
            $op = $_.OwningProcess
            if ($op -and $op -gt 0) {
                [void]$set.Add([int]$op)
            }
        }
    }
    catch {
        # ignore; netstat fallback below
    }
    if ($set.Count -eq 0) {
        $lines = netstat -ano
        foreach ($line in $lines) {
            if ($line -notmatch 'LISTENING\s+(\d+)\s*$') { continue }
            $procId = [int]$Matches[1]
            if ($procId -le 4) { continue }
            if ($line -match ":$Port\s") {
                [void]$set.Add($procId)
            }
        }
    }
    return @($set)
}

function Get-ProcessSummary {
    param([int]$ProcessId)
    try {
        $p = Get-Process -Id $ProcessId -ErrorAction Stop
        return "$($p.ProcessName) (pid=$ProcessId)"
    }
    catch {
        return "pid=$ProcessId (name unavailable)"
    }
}

$allPids = [System.Collections.Generic.HashSet[int]]::new()
foreach ($port in $StackPorts) {
    foreach ($pid in (Get-ListeningPidsForPort -Port $port)) {
        if ($pid -gt 4) {
            [void]$allPids.Add($pid)
        }
    }
}

if ($allPids.Count -eq 0) {
    Write-Host 'No LISTENING processes found on ports 8545, 1883, 8000, 8501. Nothing to stop.'
    exit 0
}

Write-Host 'The following processes are listening on stack ports (8545 / 1883 / 8000 / 8501):'
foreach ($procId in ($allPids | Sort-Object)) {
    Write-Host ('  - ' + (Get-ProcessSummary -ProcessId $procId))
}

if (-not $Force) {
    $answer = Read-Host 'Stop these processes? [y/N]'
    if ($answer -notmatch '^(y|yes)$') {
        Write-Host 'Cancelled.'
        exit 1
    }
}

foreach ($procId in ($allPids | Sort-Object)) {
    try {
        Stop-Process -Id $procId -Force -ErrorAction Stop
        Write-Host "Stopped pid $procId"
    }
    catch {
        Write-Warning "Could not stop pid ${procId}: $_"
    }
}

Write-Host 'Done. You can run run.bat again when ports are free.'
exit 0
