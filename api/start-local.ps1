param(
  [string]$Model = "qwen2.5-coder:3b",
  [string]$VisualModel = "qwen2.5vl:3b",
  [int]$Port = 8000,
  [switch]$SkipGitHub
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

function Read-SecretText([string]$Prompt) {
  $secure = Read-Host $Prompt -AsSecureString
  $ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
  try { return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr) }
  finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr) }
}

function Find-Python {
  $py = Get-Command py -ErrorAction SilentlyContinue
  if ($py) { return @{ Command = $py.Source; Args = @("-3.12") } }
  $python = Get-Command python -ErrorAction SilentlyContinue
  if ($python) { return @{ Command = $python.Source; Args = @() } }
  throw "Python 3.12+ was not found."
}

Write-Host "[1/9] Checking Python and Ollama..."
$pythonCmd = Find-Python
$version = & $pythonCmd.Command @($pythonCmd.Args) -c "import sys; print('.'.join(map(str,sys.version_info[:3])))"
if ($LASTEXITCODE -ne 0) { throw "Python check failed." }
Write-Host "Using Python $version"

$ollama = Get-Command ollama -ErrorAction SilentlyContinue
if (-not $ollama) { throw "Ollama was not found in PATH." }

Write-Host "[2/9] Checking local Ollama API..."
try {
  $tags = Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/tags" -TimeoutSec 5
} catch {
  Start-Process -FilePath $ollama.Source -ArgumentList "serve" -WindowStyle Minimized
  Start-Sleep -Seconds 3
  $tags = Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/tags" -TimeoutSec 10
}
$models = @($tags.models | ForEach-Object { $_.name })
if ($models -notcontains $Model) {
  Write-Host "Model $Model is missing. Pulling it now..."
  & $ollama.Source pull $Model
  if ($LASTEXITCODE -ne 0) { throw "Failed to pull Ollama model $Model." }
}

Write-Host "[3/9] Preparing local vision reviewer..."
$tags = Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/tags" -TimeoutSec 5
$models = @($tags.models | ForEach-Object { $_.name })
if ($models -notcontains $VisualModel) {
  Write-Host "Downloading $VisualModel for screenshot art-direction QA (one-time download)..." -ForegroundColor Cyan
  & $ollama.Source pull $VisualModel
  if ($LASTEXITCODE -ne 0) { throw "Failed to pull visual QA model $VisualModel." }
}
Write-Host "Vision reviewer: READY / $VisualModel" -ForegroundColor Green

Write-Host "[4/9] Checking port $Port..."
$listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if ($listener) {
  try {
    $old = Get-Process -Id $listener.OwningProcess -ErrorAction Stop
    if ($old.ProcessName -match 'python|uvicorn') {
      Write-Host "Stopping previous local agent process $($old.Id)..."
      Stop-Process -Id $old.Id -Force
      Start-Sleep -Seconds 1
    } else {
      throw "Port $Port is already used by $($old.ProcessName) (PID $($old.Id))."
    }
  } catch {
    if (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) { throw }
  }
}

Write-Host "[5/9] Preparing isolated Python environment..."
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
& ".\.venv\Scripts\python.exe" -c "import fastapi, pydantic, uvicorn, PIL, playwright; print('Dependencies OK')"
if ($LASTEXITCODE -ne 0) { throw "Dependency verification failed." }

Write-Host "[6/9] Preparing Chromium visual QA engine..."
$browserProbe = & ".\.venv\Scripts\python.exe" -c "from pathlib import Path; from playwright.sync_api import sync_playwright; p=sync_playwright().start(); x=Path(p.chromium.executable_path); p.stop(); print('ok' if x.exists() else 'missing')"
if ($browserProbe -ne 'ok') {
  Write-Host "Installing headless Chromium for desktop/tablet/mobile QA..."
  & ".\.venv\Scripts\python.exe" -m playwright install chromium
  if ($LASTEXITCODE -ne 0) { throw "Could not install Chromium required for visual QA." }
}
Write-Host "Visual QA browser: READY / Chromium" -ForegroundColor Green

Write-Host "[7/9] Configuring local agent..."
$env:OLLAMA_BASE_URL = "http://127.0.0.1:11434"
$env:OLLAMA_MODEL = $Model
$env:VISUAL_QA_MODEL = $VisualModel
$env:VISUAL_QA_VISION = "true"
$env:GITHUB_OWNER = "DDAY2301"

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

Write-Host "[8/9] Connecting GitHub repository access..."
if (-not $SkipGitHub -and -not $env:GITHUB_TOKEN) {
  Write-Host "The token is kept only in this process and is NOT saved to the repository."
  Write-Host "For full automatic publishing use a fine-grained token with:" -ForegroundColor Yellow
  Write-Host "  Repository access: All repositories" -ForegroundColor Yellow
  Write-Host "  Contents: Read and write" -ForegroundColor Yellow
  Write-Host "  Pages: Read and write" -ForegroundColor Yellow
  Write-Host "  Administration: Read and write" -ForegroundColor Yellow
  $env:GITHUB_TOKEN = Read-SecretText "Paste GitHub token"
}
if ($env:GITHUB_TOKEN) {
  try {
    $headers = @{ Authorization = "Bearer $env:GITHUB_TOKEN"; Accept = "application/vnd.github+json"; "X-GitHub-Api-Version" = "2022-11-28" }
    $ghUser = Invoke-RestMethod -Uri "https://api.github.com/user" -Headers $headers -Method Get -TimeoutSec 15
    Write-Host "GitHub repository access: CONNECTED as $($ghUser.login)" -ForegroundColor Green
    Write-Host "Pages publication permissions are verified when a generated site is published." -ForegroundColor DarkGray
  } catch {
    $env:GITHUB_TOKEN = $null
    throw "GitHub token validation failed. The token was not saved."
  }
} else {
  Write-Warning "GitHub repository publishing is disabled."
}

Write-Host "[9/9] Starting API and builder..."
Write-Host "Health:  http://127.0.0.1:$Port/health"
Write-Host "Builder: http://127.0.0.1:$Port/builder/"
Write-Host "Dashboard: http://127.0.0.1:$Port/dashboard.html"
Write-Host "Press Ctrl+C to stop."
& ".\.venv\Scripts\python.exe" -m uvicorn api.server:app --host 127.0.0.1 --port $Port
if ($LASTEXITCODE -ne 0) { throw "API process exited with code $LASTEXITCODE." }
