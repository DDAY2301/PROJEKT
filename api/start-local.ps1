param(
  [string]$Model = "qwen2.5-coder:7b",
  [int]$Port = 8000
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

function Find-CompatiblePython {
  $candidates = @(
    @{ Command = "py"; Args = @("-3.12") },
    @{ Command = "py"; Args = @("-3.13") },
    @{ Command = "python"; Args = @() }
  )

  foreach ($candidate in $candidates) {
    if (-not (Get-Command $candidate.Command -ErrorAction SilentlyContinue)) { continue }
    try {
      $versionText = & $candidate.Command @($candidate.Args) -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null
      if ($LASTEXITCODE -ne 0) { continue }
      $parts = $versionText.Trim().Split('.')
      $major = [int]$parts[0]
      $minor = [int]$parts[1]
      if ($major -eq 3 -and $minor -ge 11 -and $minor -le 13) {
        return $candidate
      }
    } catch {}
  }
  return $null
}

Write-Host "[1/5] Checking Python and Ollama..."
$pythonCmd = Find-CompatiblePython
if (-not $pythonCmd) {
  throw "Compatible Python was not found. Install Python 3.12 (recommended), then run this script again. Windows: winget install -e --id Python.Python.3.12"
}
if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) { throw "Ollama is not installed or not on PATH." }
$pythonVersion = & $pythonCmd.Command @($pythonCmd.Args) -c "import sys; print(sys.version.split()[0])"
Write-Host "Using Python $pythonVersion"

Write-Host "[2/5] Checking local Ollama API..."
try {
  $null = Invoke-RestMethod -Uri "http://localhost:11434/api/tags" -Method Get -TimeoutSec 5
} catch {
  throw "Ollama API is not reachable on http://localhost:11434. Start Ollama first with: ollama serve"
}

Write-Host "[3/5] Preparing isolated Python environment..."
$recreateVenv = $false
if (Test-Path ".venv\Scripts\python.exe") {
  try {
    $venvVersion = & ".\.venv\Scripts\python.exe" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
    if ($LASTEXITCODE -ne 0 -or $venvVersion -notmatch '^3\.(11|12|13)$') { $recreateVenv = $true }
  } catch { $recreateVenv = $true }
}
if ($recreateVenv) {
  Write-Host "Removing incompatible .venv..."
  Remove-Item -Recurse -Force ".venv"
}
if (-not (Test-Path ".venv\Scripts\python.exe")) {
  & $pythonCmd.Command @($pythonCmd.Args) -m venv .venv
  if ($LASTEXITCODE -ne 0) { throw "Failed to create Python virtual environment." }
}

& ".\.venv\Scripts\python.exe" -m pip install --upgrade pip wheel setuptools
if ($LASTEXITCODE -ne 0) { throw "Failed to prepare pip tooling." }
& ".\.venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r "api\requirements.txt"
if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed. The API was not started." }
& ".\.venv\Scripts\python.exe" -c "import fastapi, pydantic, uvicorn; print('Dependencies OK')"
if ($LASTEXITCODE -ne 0) { throw "Dependency verification failed." }

Write-Host "[4/5] Configuring local agent..."
$env:OLLAMA_BASE_URL = "http://localhost:11434"
$env:OLLAMA_MODEL = $Model
$env:GITHUB_OWNER = "DDAY2301"
if (-not $env:APP_SECRET) {
  $env:APP_SECRET = & ".\.venv\Scripts\python.exe" -c "import secrets; print(secrets.token_urlsafe(48))"
}

if ($env:GITHUB_TOKEN) {
  Write-Host "GitHub publishing: ENABLED"
} else {
  Write-Warning "GITHUB_TOKEN is not set. Login/build can run, but final GitHub publishing will fail until you set it. Never commit the token to this repository."
}

Write-Host "[5/5] Starting API..."
Write-Host "Health:  http://localhost:$Port/health"
Write-Host "Builder: open dist\builder\index.html after the API starts"
Write-Host "Press Ctrl+C to stop."
& ".\.venv\Scripts\python.exe" -m uvicorn api.main:app --host 127.0.0.1 --port $Port
if ($LASTEXITCODE -ne 0) { throw "API process exited with code $LASTEXITCODE." }
