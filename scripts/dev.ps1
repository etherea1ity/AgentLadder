[CmdletBinding()]
param(
    [int]$ApiPort = 8011,
    [int]$WebPort = 5123,
    [switch]$Restart,
    [switch]$Open
)

$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$WebRoot = Join-Path $RepoRoot "apps\web"
$LogDir = Join-Path $RepoRoot ".klara"
$ApiLog = Join-Path $LogDir "dev-api.log"
$WebLog = Join-Path $LogDir "dev-web.log"
$PidFile = Join-Path $LogDir "dev-pids.json"

function Assert-Command {
    param([string]$Name)
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Missing command: $Name"
    }
}

function Get-Listener {
    param([int]$Port)
    Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
        Select-Object -First 1
}

function Wait-ForHttp {
    param(
        [string]$Url,
        [int]$Seconds = 30
    )
    $deadline = (Get-Date).AddSeconds($Seconds)
    while ((Get-Date) -lt $deadline) {
        try {
            Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 5 | Out-Null
            return $true
        }
        catch {
            Start-Sleep -Milliseconds 500
        }
    }
    return $false
}

function Test-Http {
    param([string]$Url)
    try {
        Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 5 | Out-Null
        return $true
    }
    catch {
        return $false
    }
}

function Stop-Listener {
    param(
        [int]$Port,
        [string]$Reason
    )
    $listener = Get-Listener $Port
    if (-not $listener) {
        return
    }
    $processId = [int]$listener.OwningProcess
    if ($processId -le 0) {
        throw "Port $Port is busy, but no owning process could be resolved."
    }
    Write-Host "Stopping process $processId on port ${Port}: $Reason"
    Stop-Process -Id $processId -Force
    Start-Sleep -Seconds 1
}

function New-EncodedCommand {
    param([string]$Command)
    $bytes = [System.Text.Encoding]::Unicode.GetBytes($Command)
    [Convert]::ToBase64String($bytes)
}

function Start-HiddenPowerShell {
    param(
        [string]$Command,
        [string]$WorkingDirectory
    )
    $encoded = New-EncodedCommand $Command
    Start-Process `
        -FilePath "powershell" `
        -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-EncodedCommand", $encoded) `
        -WorkingDirectory $WorkingDirectory `
        -WindowStyle Hidden `
        -PassThru
}

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
Assert-Command "python"
Assert-Command "npm"

if ($Restart) {
    Stop-Listener $ApiPort "restart requested"
    Stop-Listener $WebPort "restart requested"
}

if (-not (Test-Path -LiteralPath (Join-Path $RepoRoot ".env"))) {
    Write-Warning "No .env file found at repo root. Real LLM calls need DEEPSEEK_API_KEY or DASHSCOPE_API_KEY."
}

if (-not (Test-Path -LiteralPath (Join-Path $WebRoot "node_modules"))) {
    Write-Host "Installing frontend dependencies with npm ci..."
    Push-Location $WebRoot
    try {
        npm ci
    }
    finally {
        Pop-Location
    }
}

$apiProcess = $null
$apiListener = Get-Listener $ApiPort
if ($apiListener) {
    Write-Host "API already listening on http://127.0.0.1:$ApiPort (PID $($apiListener.OwningProcess))."
    Write-Host "Use .\scripts\dev.ps1 -Restart after backend code changes."
}
else {
    $apiCommand = @"
Set-Location -LiteralPath "$RepoRoot"
`$env:PYTHONPATH = "src"
python -m uvicorn apps.api.main:app --host 127.0.0.1 --port $ApiPort *> "$ApiLog"
"@
    $apiProcess = Start-HiddenPowerShell -Command $apiCommand -WorkingDirectory $RepoRoot
    Write-Host "Started API on http://127.0.0.1:$ApiPort (launcher PID $($apiProcess.Id))."
}

$apiReadyBeforeWeb = Wait-ForHttp "http://127.0.0.1:$ApiPort/api/health" 40

$webProcess = $null
$webListener = Get-Listener $WebPort
if ($webListener) {
    $webApiBridgeReady = Test-Http "http://127.0.0.1:$WebPort/api/health"
    if ($apiReadyBeforeWeb -and -not $webApiBridgeReady) {
        Stop-Listener $WebPort "existing web server does not proxy /api to Klara API"
        $webListener = $null
    }
    else {
        Write-Host "Web app already listening on http://127.0.0.1:$WebPort (PID $($webListener.OwningProcess))."
        Write-Host "Use .\scripts\dev.ps1 -Restart after frontend env or backend proxy changes."
    }
}

if (-not $webListener) {
    $webCommand = @"
Set-Location -LiteralPath "$WebRoot"
`$env:VITE_API_BASE_URL = "http://127.0.0.1:$ApiPort"
npm run dev -- --host 127.0.0.1 --port $WebPort *> "$WebLog"
"@
    $webProcess = Start-HiddenPowerShell -Command $webCommand -WorkingDirectory $WebRoot
    Write-Host "Started web app on http://127.0.0.1:$WebPort (launcher PID $($webProcess.Id))."
}

$apiReady = Wait-ForHttp "http://127.0.0.1:$ApiPort/api/health" 40
$webReady = Wait-ForHttp "http://127.0.0.1:$WebPort/" 40

$pidInfo = [ordered]@{
    api_port = $ApiPort
    web_port = $WebPort
    api_launcher_pid = if ($apiProcess) { $apiProcess.Id } else { $null }
    web_launcher_pid = if ($webProcess) { $webProcess.Id } else { $null }
    api_log = $ApiLog
    web_log = $WebLog
    started_at = (Get-Date).ToString("o")
}
$pidInfo | ConvertTo-Json | Set-Content -LiteralPath $PidFile -Encoding UTF8

Write-Host ""
Write-Host "Klara dev status:"
Write-Host "  API:  http://127.0.0.1:$ApiPort  ready=$apiReady"
Write-Host "  Web:  http://127.0.0.1:$WebPort  ready=$webReady"
Write-Host "  Logs: $LogDir"

if (-not $apiReady) {
    Write-Warning "API did not become ready. Check $ApiLog"
}
if (-not $webReady) {
    Write-Warning "Web app did not become ready. Check $WebLog"
}
if ($Open -and $webReady) {
    Start-Process "http://127.0.0.1:$WebPort/"
}
