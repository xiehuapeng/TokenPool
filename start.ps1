[CmdletBinding()]
param(
    [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"
$projectRoot = $PSScriptRoot
$backendDir = Join-Path $projectRoot "backend"
$frontendDir = Join-Path $projectRoot "frontend"
$runtimeDir = Join-Path $projectRoot ".run"
$stateFile = Join-Path $runtimeDir "processes.json"
$backendLog = Join-Path $runtimeDir "backend.log"
$backendErrorLog = Join-Path $runtimeDir "backend-error.log"
$frontendLog = Join-Path $runtimeDir "frontend.log"
$frontendErrorLog = Join-Path $runtimeDir "frontend-error.log"

function Write-Step([string]$message) {
    Write-Host "[TokenPool] $message" -ForegroundColor Cyan
}

function Test-HttpEndpoint([string]$url) {
    try {
        $response = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 3
        return $response.StatusCode -ge 200 -and $response.StatusCode -lt 500
    }
    catch {
        return $false
    }
}

function Wait-HttpEndpoint([string]$name, [string]$url, [int]$timeoutSeconds = 60) {
    $deadline = (Get-Date).AddSeconds($timeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if (Test-HttpEndpoint $url) {
            Write-Host "  OK  $name -> $url" -ForegroundColor Green
            return
        }
        Start-Sleep -Milliseconds 750
    }
    throw "$name did not become ready within $timeoutSeconds seconds. Check .run logs."
}

function Get-ListeningProcessId([int]$port) {
    $connection = Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($null -eq $connection) {
        return $null
    }
    return [int]$connection.OwningProcess
}

function Stop-StartedProcesses($processes) {
    foreach ($process in $processes) {
        if ($null -ne $process -and -not $process.HasExited) {
            & taskkill.exe /PID $process.Id /T /F 2>$null | Out-Null
        }
    }
}

$envFile = Join-Path $projectRoot ".env"
if (-not (Test-Path $envFile)) {
    Copy-Item (Join-Path $projectRoot ".env.example") $envFile
    throw "Created .env from .env.example. Configure its secrets and run start.bat again."
}

$pythonExe = Join-Path $backendDir ".venv\Scripts\python.exe"
if (-not (Test-Path $pythonExe)) {
    $pythonLauncher = Get-Command py -ErrorAction SilentlyContinue
    if ($null -ne $pythonLauncher) {
        Write-Step "Creating Python virtual environment..."
        & $pythonLauncher.Source -3.12 -m venv (Join-Path $backendDir ".venv")
    }
    else {
        $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
        if ($null -eq $pythonCommand) {
            throw "Python 3.11 or newer is required."
        }
        Write-Step "Creating Python virtual environment..."
        & $pythonCommand.Source -m venv (Join-Path $backendDir ".venv")
    }
}

& $pythonExe -c "import fastapi, uvicorn, sqlalchemy" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Step "Installing backend dependencies..."
    & $pythonExe -m pip install -r (Join-Path $backendDir "requirements.txt")
    if ($LASTEXITCODE -ne 0) {
        throw "Backend dependency installation failed."
    }
}

$nodeCommand = Get-Command node -ErrorAction SilentlyContinue
$npmCommand = Get-Command npm.cmd -ErrorAction SilentlyContinue
if ($null -eq $nodeCommand -or $null -eq $npmCommand) {
    throw "Node.js 20 or newer and npm are required."
}

$viteEntry = Join-Path $frontendDir "node_modules\vite\bin\vite.js"
if (-not (Test-Path $viteEntry)) {
    Write-Step "Installing frontend dependencies..."
    Push-Location $frontendDir
    try {
        & $npmCommand.Source ci
        if ($LASTEXITCODE -ne 0) {
            throw "Frontend dependency installation failed."
        }
    }
    finally {
        Pop-Location
    }
}

foreach ($port in 8000, 5173) {
    $ownerPid = Get-ListeningProcessId $port
    if ($null -ne $ownerPid) {
        throw "Port $port is already in use by PID $ownerPid. Stop that process or run stop.bat first."
    }
}

New-Item -ItemType Directory -Path $runtimeDir -Force | Out-Null
Remove-Item $backendLog, $backendErrorLog, $frontendLog, $frontendErrorLog, $stateFile `
    -Force -ErrorAction SilentlyContinue

$startedProcesses = @()
$previousAppEnv = $env:APP_ENV
try {
    Write-Step "Starting FastAPI backend..."
    $env:APP_ENV = "local"
    $backendProcess = Start-Process `
        -FilePath $pythonExe `
        -ArgumentList "main.py" `
        -WorkingDirectory $backendDir `
        -WindowStyle Hidden `
        -RedirectStandardOutput $backendLog `
        -RedirectStandardError $backendErrorLog `
        -PassThru
    $startedProcesses += $backendProcess

    Write-Step "Starting Vue development server..."
    $frontendProcess = Start-Process `
        -FilePath $nodeCommand.Source `
        -ArgumentList @($viteEntry, "--host", "127.0.0.1", "--port", "5173") `
        -WorkingDirectory $frontendDir `
        -WindowStyle Hidden `
        -RedirectStandardOutput $frontendLog `
        -RedirectStandardError $frontendErrorLog `
        -PassThru
    $startedProcesses += $frontendProcess

    Wait-HttpEndpoint "Backend health" "http://localhost:8000/health"
    Wait-HttpEndpoint "Frontend" "http://localhost:5173"

    @{
        backend_pid = $backendProcess.Id
        backend_listener_pid = Get-ListeningProcessId 8000
        frontend_pid = $frontendProcess.Id
        frontend_listener_pid = Get-ListeningProcessId 5173
        started_at = (Get-Date).ToString("o")
    } | ConvertTo-Json | Set-Content -Path $stateFile -Encoding UTF8
}
catch {
    Stop-StartedProcesses $startedProcesses
    Remove-Item $stateFile -Force -ErrorAction SilentlyContinue
    Write-Host ""
    Write-Host $_.Exception.Message -ForegroundColor Red
    if (Test-Path $backendErrorLog) {
        Write-Host "`nBackend error log:" -ForegroundColor Yellow
        Get-Content $backendErrorLog -Tail 20
    }
    if (Test-Path $frontendErrorLog) {
        Write-Host "`nFrontend error log:" -ForegroundColor Yellow
        Get-Content $frontendErrorLog -Tail 20
    }
    exit 1
}
finally {
    $env:APP_ENV = $previousAppEnv
}

Write-Host ""
Write-Host "TokenPool is running." -ForegroundColor Green
Write-Host "  Workspace: http://localhost:5173"
Write-Host "  API docs: http://localhost:8000/docs"
Write-Host "  Base URL: http://localhost:8000/v1"
Write-Host "  Logs:     $runtimeDir"
Write-Host "  Stop:     .\stop.bat"

if (-not $NoBrowser) {
    Start-Process "http://localhost:5173"
}
