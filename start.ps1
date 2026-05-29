param(
    [switch]$Stop,
    [switch]$NoOpen,
    [int]$ApiPort = 8000,
    [int]$WebPort = 5123
)

$ErrorActionPreference = "Stop"

$Repo = Split-Path -Parent $MyInvocation.MyCommand.Path
$ApiUrl = "http://127.0.0.1:$ApiPort/api/health"
$WebUrl = "http://127.0.0.1:$WebPort"

function Stop-Port {
    param([int]$Port)
    $connections = @()
    try {
        $connections = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    } catch {
        $connections = @()
    }

    $pids = @($connections | Select-Object -ExpandProperty OwningProcess -Unique | Where-Object { $_ -and $_ -gt 0 })
    if ($pids.Count -eq 0) {
        Write-Host "port $Port is free"
        return
    }

    Write-Host "Stopping port ${Port}: $($pids -join ', ')"
    foreach ($processId in $pids) {
        try { Stop-Process -Id $processId -Force -ErrorAction Stop } catch { }
    }
}

function Test-UrlReady {
    param(
        [string]$Name,
        [string]$Url,
        [int]$Tries = 120
    )
    for ($i = 1; $i -le $Tries; $i++) {
        try {
            Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec 2 | Out-Null
            Write-Host "$Name ready: $Url"
            return $true
        } catch {
            Start-Sleep -Milliseconds 300
        }
    }
    Write-Host "! $Name may still be starting: $Url"
    return $false
}

function Get-PythonLauncher {
    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) { return @($py.Source, "-3") }
    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python) { return @($python.Source) }
    throw "Python was not found on Windows. Install Python 3.11+ or the Python launcher first."
}

function Ensure-PythonEnv {
    $venvDir = Join-Path $Repo ".venv-win"
    $venvPython = Join-Path $venvDir "Scripts\python.exe"
    if (!(Test-Path $venvPython)) {
        Write-Host "Creating Windows Python virtualenv at .venv-win ..."
        $launcher = Get-PythonLauncher
        $launcherExe = $launcher[0]
        $launcherArgs = @()
        if ($launcher.Length -gt 1) {
            $launcherArgs = @($launcher[1..($launcher.Length - 1)])
        }
        & $launcherExe @launcherArgs -m venv $venvDir
    }

    $uvicorn = Join-Path $venvDir "Scripts\uvicorn.exe"
    if (!(Test-Path $uvicorn)) {
        Write-Host "Installing Python dependencies into .venv-win ..."
        & $venvPython -m pip install --upgrade pip
        & $venvPython -m pip install -e "$Repo[dev]"
    }
    return $venvPython
}

function Ensure-WebEnv {
    $webDir = Join-Path $Repo "apps\web"
    $nodeModules = Join-Path $webDir "node_modules"
    $viteCmd = Join-Path $webDir "node_modules\.bin\vite.cmd"
    if (!(Test-Path $nodeModules) -or !(Test-Path $viteCmd)) {
        Write-Host "Installing frontend dependencies for Windows ..."
        Push-Location $webDir
        try { npm install } finally { Pop-Location }
    }
}

if ($Stop) {
    Stop-Port $ApiPort
    Stop-Port $WebPort
    Stop-Port 5173
    Write-Host "Stopped Klara dev ports."
    exit 0
}

Write-Host "Mode: Windows-native PowerShell runtime"
Stop-Port $ApiPort
Stop-Port $WebPort
if ($WebPort -ne 5173) { Stop-Port 5173 }

$pythonExe = Ensure-PythonEnv
Ensure-WebEnv

$webDir = Join-Path $Repo "apps\web"
$npm = Get-Command npm.cmd -ErrorAction SilentlyContinue
if (!$npm) { $npm = Get-Command npm -ErrorAction Stop }

Write-Host "Starting backend on $ApiUrl ..."
$apiArgs = @("-m", "uvicorn", "apps.api.main:app", "--host", "127.0.0.1", "--port", "$ApiPort")
Start-Process -FilePath $pythonExe -ArgumentList $apiArgs -WorkingDirectory $Repo -WindowStyle Hidden | Out-Null
Start-Sleep -Milliseconds 500

Write-Host "Starting frontend on $WebUrl ..."
$webArgs = @("run", "dev", "--", "--host", "127.0.0.1", "--port", "$WebPort")
Start-Process -FilePath $npm.Source -ArgumentList $webArgs -WorkingDirectory $webDir -WindowStyle Hidden | Out-Null
Start-Sleep -Milliseconds 500

Test-UrlReady "backend" $ApiUrl 180 | Out-Null
Test-UrlReady "frontend" $WebUrl 120 | Out-Null

if (!$NoOpen) {
    Start-Process $WebUrl
}

Write-Host ""
Write-Host "Klara is running."
Write-Host ""
Write-Host "Frontend: $WebUrl"
Write-Host "Backend:  $ApiUrl"
Write-Host ""
Write-Host "Stop:"
Write-Host "  powershell -ExecutionPolicy Bypass -File .\start.ps1 -Stop"
