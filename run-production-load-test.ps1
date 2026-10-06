param(
  [ValidateSet('smoke','production')]
  [string]$Mode = 'smoke',
  [string]$Api = 'http://127.0.0.1:8000',
  [int]$Count = 0,
  [int]$TimeoutMinutes = 0
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $repoRoot '.venv\Scripts\python.exe'
$script = Join-Path $repoRoot 'tools\production_load_test.py'

if (-not (Test-Path $python)) {
  throw "Python virtual environment not found: $python. Run start-product.ps1 first."
}
if (-not (Test-Path $script)) {
  throw "Load test harness not found: $script"
}

try {
  $health = Invoke-RestMethod -Uri "$Api/health" -Method Get -TimeoutSec 5
} catch {
  throw "Project Visibility API is not reachable at $Api. Run .\start-product.ps1 first."
}
if (-not $health.ok) {
  throw "API health check did not return ok=true."
}

if ($Count -le 0) {
  $Count = if ($Mode -eq 'production') { 50 } else { 10 }
}
if ($TimeoutMinutes -le 0) {
  $TimeoutMinutes = if ($Mode -eq 'production') { 240 } else { 90 }
}

Write-Host ""
Write-Host "PROJECT VISIBILITY - PRODUCTION LOAD TEST" -ForegroundColor Green
Write-Host "Mode: $Mode" -ForegroundColor Cyan
Write-Host "API: $Api"
Write-Host "Projects: $Count"
Write-Host "Timeout: $TimeoutMinutes min"
Write-Host ""
Write-Host "This test uses the REAL production pipeline and may create GitHub repositories / Pages deployments." -ForegroundColor Yellow
Write-Host "Results will be stored under .\load-test-results\<timestamp>." -ForegroundColor Yellow
Write-Host ""

& $python $script --api $Api --count $Count --timeout-minutes $TimeoutMinutes
$code = $LASTEXITCODE

if ($code -eq 0) {
  Write-Host ""
  Write-Host "LOAD TEST PASSED quality thresholds." -ForegroundColor Green
} elseif ($code -eq 2) {
  Write-Host ""
  Write-Host "LOAD TEST COMPLETED but one or more production thresholds failed. Review REPORT.md." -ForegroundColor Yellow
} else {
  Write-Host ""
  Write-Host "LOAD TEST ERROR. Exit code: $code" -ForegroundColor Red
}

exit $code
