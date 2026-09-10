param(
  [string]$Model = "qwen2.5-coder:3b",
  [int]$Port = 8000,
  [switch]$SkipGitHub
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
      if ([int]$parts[0] -eq 3 -and [int]$parts[1] -ge 11 -and [int]$parts[1] -le 13) { return $candidate }
    } catch {}
  }
  return $null
}

function Read-SecretText([string]$Prompt) {
  $secure = Read-Host $Prompt -AsSecureString
  $ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
  try { return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr) }
  finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr) }
}

Write-Host "[1/7] Checking Python and Ollama..."
$pythonCmd = Find-CompatiblePython
if (-not $pythonCmd) { throw "Compatible Python was not found. Install Python 3.12: winget install -e --id Python.Python.3.12" }
if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) { throw "Ollama is not installed or not on PATH." }
$pythonVersion = & $pythonCmd.Command @($pythonCmd.Args) -c "import sys; print(sys.version.split()[0])"
Write-Host "Using Python $pythonVersion"

Write-Host "[2/7] Checking local Ollama API..."
try { $tags = Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/tags" -Method Get -TimeoutSec 5 }
catch { throw "Ollama API is not reachable. Start it first with: ollama serve" }
$availableModels = @($tags.models | ForEach-Object { $_.name })
if ($availableModels -notcontains $Model) {
  Write-Host "Model '$Model' is missing. Downloading it with Ollama..."
  & ollama pull $Model
  if ($LASTEXITCODE -ne 0) { throw "Ollama model download failed." }
}

Write-Host "[3/7] Checking port $Port..."
$listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if ($listener) {
  try {
    $existingHealth = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/health" -Method Get -TimeoutSec 3
    if ($existingHealth.ok) {
      if (-not $SkipGitHub -and -not $existingHealth.github_configured) {
        throw "An agent is already running on port $Port WITHOUT GitHub publishing (PID $($listener.OwningProcess)). Stop it first: Stop-Process -Id $($listener.OwningProcess) -Force"
      }
      Write-Host "Agent is already running on port $Port (PID $($listener.OwningProcess))."
      Write-Host "Health: http://127.0.0.1:$Port/health"
      Write-Host "Builder: http://127.0.0.1:$Port/builder/"
      exit 0
    }
  } catch {
    if ($_.Exception.Message -like "An agent is already running*") { throw }
    throw "Port $Port is already in use by PID $($listener.OwningProcess), but it is not a healthy Project Visibility agent."
  }
}

Write-Host "[4/7] Preparing isolated Python environment..."
$recreateVenv = $false
if (Test-Path ".venv\Scripts\python.exe") {
  try {
    $venvVersion = & ".\.venv\Scripts\python.exe" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
    if ($LASTEXITCODE -ne 0 -or $venvVersion -notmatch '^3\.(11|12|13)$') { $recreateVenv = $true }
  } catch { $recreateVenv = $true }
}
if ($recreateVenv) { Remove-Item -Recurse -Force ".venv" }
if (-not (Test-Path ".venv\Scripts\python.exe")) {
  & $pythonCmd.Command @($pythonCmd.Args) -m venv .venv
  if ($LASTEXITCODE -ne 0) { throw "Failed to create Python virtual environment." }
}
& ".\.venv\Scripts\python.exe" -m pip install --upgrade pip wheel setuptools
if ($LASTEXITCODE -ne 0) { throw "Failed to prepare pip tooling." }
& ".\.venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r "api\requirements.txt"
if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed." }
& ".\.venv\Scripts\python.exe" -c "import fastapi, pydantic, uvicorn; print('Dependencies OK')"
if ($LASTEXITCODE -ne 0) { throw "Dependency verification failed." }

Write-Host "[5/7] Configuring local agent..."
$env:OLLAMA_BASE_URL = "http://127.0.0.1:11434"
$env:OLLAMA_MODEL = $Model
$env:GITHUB_OWNER = "DDAY2301"

# Keep the auth signing key stable across local restarts so browser sessions do
# not become invalid every time the API process is restarted. The file is
# intentionally stored under api/data and ignored by Git.
$secretFile = Join-Path $repoRoot "api\data\.app-secret"
if (-not $env:APP_SECRET) {
  if (Test-Path $secretFile) {
    $env:APP_SECRET = (Get-Content $secretFile -Raw).Trim()
  } else {
    $secretDir = Split-Path -Parent $secretFile
    New-Item -ItemType Directory -Path $secretDir -Force | Out-Null
    $env:APP_SECRET = & ".\.venv\Scripts\python.exe" -c "import secrets; print(secrets.token_urlsafe(48))"
    Set-Content -Path $secretFile -Value $env:APP_SECRET -NoNewline -Encoding UTF8
  }
}
if (-not $env:APP_SECRET) { throw "Could not prepare APP_SECRET." }
Write-Host "Local login sessions: PERSISTENT across restarts" -ForegroundColor Green

Write-Host "[6/7] Connecting GitHub publishing..."
if (-not $SkipGitHub -and -not $env:GITHUB_TOKEN) {
  Write-Host "GitHub token will be kept only in this process and will NOT be saved to the repository."
  $env:GITHUB_TOKEN = Read-SecretText "Paste NEW GitHub token"
}
if ($env:GITHUB_TOKEN) {
  try {
    $headers = @{ Authorization = "Bearer $env:GITHUB_TOKEN"; Accept = "application/vnd.github+json"; "X-GitHub-Api-Version" = "2022-11-28" }
    $ghUser = Invoke-RestMethod -Uri "https://api.github.com/user" -Headers $headers -Method Get -TimeoutSec 15
    Write-Host "GitHub publishing: ENABLED as $($ghUser.login)"
  } catch {
    $env:GITHUB_TOKEN = $null
    throw "GitHub token validation failed. The token was not saved."
  }
} else {
  Write-Warning "GitHub publishing is disabled."
}

Write-Host "[7/7] Starting API and builder..."
Write-Host "Health:  http://127.0.0.1:$Port/health"
Write-Host "Builder: http://127.0.0.1:$Port/builder/"
Write-Host "Press Ctrl+C to stop."
& ".\.venv\Scripts\python.exe" -m uvicorn api.server:app --host 127.0.0.1 --port $Port
if ($LASTEXITCODE -ne 0) { throw "API process exited with code $LASTEXITCODE." }
