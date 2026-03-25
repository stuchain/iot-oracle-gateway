#Requires -Version 5.1
<#
.SYNOPSIS
  Starts Ganache, deploys TelemetryAnchor, Mosquitto, oracle (with CONTRACT_ADDRESS), and Streamlit.
  Opens the dashboard in the default browser.

  Prerequisites: Python on PATH or venv at repo root, Node/npm.
  If Mosquitto is missing: winget (EclipseFoundation.Mosquitto), then Chocolatey (installs Chocolatey
  via official script only when running as Administrator and choco is missing).
  Before starting services: pip install -r requirements.txt, npm in contracts/ when needed.
#>
$ErrorActionPreference = 'Stop'

$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

function Resolve-Python {
    $venvPy = Join-Path $RepoRoot 'venv\Scripts\python.exe'
    if (Test-Path -LiteralPath $venvPy) {
        return $venvPy
    }
    if (Get-Command python -ErrorAction SilentlyContinue) {
        return (Get-Command python).Source
    }
    throw 'Python not found. Install Python 3.10+ or create a venv at the repository root (venv\).'
}

function Refresh-SessionPath {
    $machine = [System.Environment]::GetEnvironmentVariable('Path', 'Machine')
    $user = [System.Environment]::GetEnvironmentVariable('Path', 'User')
    $env:Path = "${machine};${user}"
}

function Test-Administrator {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    $p = New-Object Security.Principal.WindowsPrincipal($id)
    return $p.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Ensure-Chocolatey {
    if (Get-Command choco -ErrorAction SilentlyContinue) {
        return $true
    }
    if (-not (Test-Administrator)) {
        Write-Warning 'Chocolatey is not installed. To install it automatically, run this script from an elevated prompt (right-click run.bat -> Run as administrator).'
        return $false
    }
    Write-Host 'Installing Chocolatey (https://community.chocolatey.org/install) ...'
    Set-ExecutionPolicy Bypass -Scope Process -Force
    [System.Net.ServicePointManager]::SecurityProtocol = [System.Net.ServicePointManager]::SecurityProtocol -bor 3072
    Invoke-Expression ((New-Object System.Net.WebClient).DownloadString('https://community.chocolatey.org/install.ps1'))
    Refresh-SessionPath
    Start-Sleep -Seconds 2
    if (-not (Get-Command choco -ErrorAction SilentlyContinue)) {
        throw 'Chocolatey install finished but choco was not found on PATH. Close this window, open a new terminal, and run run.bat again.'
    }
    Write-Host 'Chocolatey is ready.'
    return $true
}

function Find-MosquittoExe {
    $fromPath = Get-Command mosquitto -ErrorAction SilentlyContinue
    if ($fromPath) {
        return $fromPath.Source
    }
    $candidates = @(
        (Join-Path $env:ProgramFiles 'mosquitto\mosquitto.exe')
        (Join-Path ${env:ProgramFiles(x86)} 'mosquitto\mosquitto.exe')
        'C:\mosquitto\mosquitto.exe'
    )
    foreach ($p in $candidates) {
        if ($p -and (Test-Path -LiteralPath $p)) {
            return $p
        }
    }
    return $null
}

function Ensure-Mosquitto {
    $exe = Find-MosquittoExe
    if ($exe) {
        return $exe
    }
    Write-Host 'Mosquitto not found. Installing Eclipse Mosquitto (MQTT broker)...'
    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if ($winget) {
        Write-Host 'Running: winget install -e --id EclipseFoundation.Mosquitto (UAC may ask for permission)...'
        & winget install -e --id EclipseFoundation.Mosquitto --accept-package-agreements --accept-source-agreements --silent
        Refresh-SessionPath
        Start-Sleep -Seconds 3
        $exe = Find-MosquittoExe
        if ($exe) {
            Write-Host "Mosquitto installed: $exe"
            return $exe
        }
        Write-Warning 'winget finished but mosquitto.exe was not found yet. Trying Chocolatey or see message below.'
    }
    else {
        Write-Warning 'winget not on PATH (install "App Installer" from Microsoft Store, or use Windows 11). Trying Chocolatey...'
    }
    if (-not (Get-Command choco -ErrorAction SilentlyContinue)) {
        [void](Ensure-Chocolatey)
    }
    $choco = Get-Command choco -ErrorAction SilentlyContinue
    if ($choco) {
        Write-Host 'Running: choco install mosquitto -y ...'
        & choco install mosquitto -y
        Refresh-SessionPath
        Start-Sleep -Seconds 3
        $exe = Find-MosquittoExe
        if ($exe) {
            Write-Host "Mosquitto installed: $exe"
            return $exe
        }
    }
    throw @'
Could not install or find Mosquitto automatically.

Try (1) Open PowerShell as Administrator and run:
    winget install -e --id EclipseFoundation.Mosquitto
  or (2) Install from https://mosquitto.org/download/
  or (3) Install Chocolatey (https://chocolatey.org/install) then: choco install mosquitto -y
Then run run.bat again.
'@
}

function Assert-NodeToolchain {
    if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
        throw 'Node.js not found on PATH. Install Node.js LTS (https://nodejs.org/) so npm is available.'
    }
    if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
        throw 'npm not found on PATH.'
    }
}

function Ensure-PythonRequirements {
    param([string]$PythonExe)
    $req = Join-Path $RepoRoot 'requirements.txt'
    if (-not (Test-Path -LiteralPath $req)) {
        throw "requirements.txt not found: $req"
    }
    # Idempotent: pip skips work when already satisfied. Avoids multiline `python -c` here-strings,
    # which PowerShell can pass incorrectly and trigger Python SyntaxError/tracebacks.
    Write-Host 'Ensuring Python dependencies (pip install -r requirements.txt)...'
    & $PythonExe -m pip install -r $req
    if ($LASTEXITCODE -ne 0) {
        Write-Host 'Retrying after upgrading pip...'
        & $PythonExe -m pip install --upgrade pip
        if ($LASTEXITCODE -ne 0) { throw 'pip install --upgrade pip failed.' }
        & $PythonExe -m pip install -r $req
        if ($LASTEXITCODE -ne 0) { throw 'pip install -r requirements.txt failed.' }
    }
    Write-Host 'Python dependencies ready.'
}

function Ensure-NodeRequirements {
    $contractsDir = Join-Path $RepoRoot 'contracts'
    $pkg = Join-Path $contractsDir 'package.json'
    if (-not (Test-Path -LiteralPath $pkg)) {
        throw "contracts/package.json not found: $pkg"
    }
    $nm = Join-Path $contractsDir 'node_modules'
    if ((Test-Path -LiteralPath $nm) -and (Test-Path -LiteralPath (Join-Path $nm 'hardhat'))) {
        Write-Host 'Node dependencies OK (contracts/node_modules present).'
        return
    }
    Write-Host 'Installing Node dependencies in contracts/ (npm install) ...'
    Push-Location $contractsDir
    try {
        npm install
        if ($LASTEXITCODE -ne 0) { throw 'npm install failed in contracts/.' }
    }
    finally {
        Pop-Location
    }
    Write-Host 'Node dependencies installed.'
}

$py = Resolve-Python
Ensure-PythonRequirements -PythonExe $py
$mosquittoExe = Ensure-Mosquitto
Write-Host "Using Mosquitto: $mosquittoExe"
Assert-NodeToolchain
Ensure-NodeRequirements

Write-Host 'Starting Ganache on port 8545 (new window)...'
Start-Process cmd.exe -ArgumentList @('/k', 'npx ganache --port 8545') -WorkingDirectory $RepoRoot | Out-Null
Write-Host 'Waiting for RPC...'
Start-Sleep -Seconds 5

$contractsDir = Join-Path $RepoRoot 'contracts'
Push-Location $contractsDir
try {
    Write-Host 'Compiling contracts...'
    npx hardhat compile
    if ($LASTEXITCODE -ne 0) { throw 'hardhat compile failed. Not starting oracle.' }
    Write-Host 'Deploying to localhost...'
    npx hardhat run scripts/deploy.js --network localhost
    if ($LASTEXITCODE -ne 0) { throw 'Deploy failed. Not starting oracle or downstream services.' }
}
finally {
    Pop-Location
}

$deployPath = Join-Path $contractsDir 'deployments\localhost.json'
if (-not (Test-Path -LiteralPath $deployPath)) {
    throw "Expected deployment file missing: $deployPath"
}
$deploy = Get-Content -LiteralPath $deployPath -Raw -Encoding UTF8 | ConvertFrom-Json
$contractAddress = $deploy.contractAddress
if ([string]::IsNullOrWhiteSpace($contractAddress)) {
    throw 'deployments/localhost.json has no contractAddress.'
}

Write-Host "Deployed contract: $contractAddress"

$mosqConf = Join-Path $RepoRoot 'mosquitto\mosquitto.conf'
Write-Host 'Starting Mosquitto (new window)...'
$mosqCmd = "`"$mosquittoExe`" -c `"$mosqConf`""
Start-Process cmd.exe -ArgumentList @('/k', $mosqCmd) -WorkingDirectory $RepoRoot | Out-Null
Start-Sleep -Seconds 2

Write-Host 'Starting oracle (new window)...'
$oracleCmd = "set CONTRACT_ADDRESS=$contractAddress&& cd /d `"$RepoRoot`" && `"$py`" -m oracle.service"
Start-Process cmd.exe -ArgumentList @('/k', $oracleCmd) | Out-Null

Write-Host 'Starting Streamlit dashboard (new window)...'
$dashCmd = "cd /d `"$RepoRoot`" && `"$py`" -m streamlit run dashboard\app.py"
Start-Process cmd.exe -ArgumentList @('/k', $dashCmd) | Out-Null

Start-Sleep -Seconds 3
Write-Host 'Opening browser at http://127.0.0.1:8501 ...'
Start-Process 'http://127.0.0.1:8501'

Write-Host ''
Write-Host 'Stack launch commands issued. Close each console window to stop that service.'
Write-Host 'Ports: Ganache 8545, Mosquitto 1883, Oracle 8000, Streamlit 8501.'
Write-Host 'Avoid running this twice without closing old windows (port conflicts).'
