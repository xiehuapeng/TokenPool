[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$runtimeDir = Join-Path $PSScriptRoot ".run"
$stateFile = Join-Path $runtimeDir "processes.json"

if (-not (Test-Path $stateFile)) {
    Write-Host "[TokenPool] No recorded running processes." -ForegroundColor Yellow
    exit 0
}

$state = Get-Content $stateFile -Raw | ConvertFrom-Json
$stopped = 0
$processIds = @(
    $state.backend_pid,
    $state.backend_listener_pid,
    $state.frontend_pid,
    $state.frontend_listener_pid
) | Where-Object { $null -ne $_ } | Sort-Object -Unique

foreach ($processId in $processIds) {
    if ($null -eq $processId) {
        continue
    }
    $process = Get-Process -Id $processId -ErrorAction SilentlyContinue
    if ($null -ne $process) {
        & taskkill.exe /PID $processId /T /F 2>$null | Out-Null
        Write-Host "[TokenPool] Stopped $($process.ProcessName) process tree (PID $processId)." -ForegroundColor Green
        $stopped++
    }
}

Remove-Item $stateFile -Force
if ($stopped -eq 0) {
    Write-Host "[TokenPool] Recorded processes were already stopped." -ForegroundColor Yellow
}
