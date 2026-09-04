[CmdletBinding()]
param(
    [switch]$KeepDatabase
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot
$LogRoot = Join-Path $RepoRoot "tmp\demo-artifacts\demo-logs"
$PidFile = Join-Path $LogRoot "demo-pids.json"

if (Test-Path -LiteralPath $PidFile) {
    $json = Get-Content -LiteralPath $PidFile -Raw
    $parsed = ConvertFrom-Json -InputObject $json
    $items = @($parsed)
    foreach ($item in $items) {
        $targetPid = [int]$item.PID
        $process = Get-Process -Id $targetPid -ErrorAction SilentlyContinue
        if ($process) {
            Write-Host "Stopping $($item.Name), PID=$targetPid"
            & taskkill.exe /PID $targetPid /T /F | Out-Host
        }
    }
    Remove-Item -LiteralPath $PidFile -Force
} else {
    Write-Host "No one-click process record was found."
}

if (-not $KeepDatabase) {
    $docker = Get-Command docker -ErrorAction SilentlyContinue
    if ($docker) {
        & $docker.Source compose --profile basic stop db | Out-Host
    }
}

Write-Host "Demo stopped. Ollama remains running and models are preserved."
