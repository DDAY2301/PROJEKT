param(
  [string]$Model = "qwen2.5-coder:7b",
  [int]$Port = 8000
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

Write-Host "[1/5] Checking Python and Ollama..."
if (-not (Get-Command python -ErrorAction SilentlyContinue)) { throw "Python is not installed or not on PATH." }
if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) { throw "Ollama is not installed or not on PATH." }

Write-Host "[2/5] Checking local Ollama API..."
try {
  $null = Invoke-RestMethod -Uri "http://localhost:11434/api/tags" -Method Get -TimeoutSec 5
} catch {
  throw "Ollama API is not reachable on http://localhost:11434. Start Ollama first."
}

Write-Host "[3/5] Preparing isolated Python environment..."
if (-not (Test-Path ".venv\Scripts\python.exe")) {
  python -m venv .venv
}
& ".\.venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r "api\requirements.txt"

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
