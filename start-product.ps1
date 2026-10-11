param(
  [string]$Model = "qwen2.5-coder:7b",
  [int]$Port = 8000,
  [switch]$LocalOnly,
  [string]$PublicApiUrl = $env:PV_PUBLIC_API_URL
)

$ErrorActionPreference = "Stop"
$repoRoot = $PSScriptRoot
Set-Location $repoRoot

function Read-SecretText([string]$Prompt) {
  $secure = Read-Host $Prompt -AsSecureString
  $ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
  try { return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr) }
  finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr) }
}

function Wait-Url([string]$Url, [int]$Seconds = 45) {
  $deadline = (Get-Date).AddSeconds($Seconds)
  while ((Get-Date) -lt $deadline) {
    try {
      $r = Invoke-RestMethod -Uri $Url -Method Get -TimeoutSec 4
      if ($r) { return $r }
    } catch {}
    Start-Sleep -Seconds 1
  }
  return $null
}

Write-Host ""
Write-Host "PROJECT VISIBILITY - PRODUCT START" -ForegroundColor Green
Write-Host "==================================" -ForegroundColor Green
Write-Host ""

$repoUpdated = $false
$headBefore = $null
$headAfter = $null
if (Get-Command git -ErrorAction SilentlyContinue) {
  Write-Host "[1/6] Updating GitHub repository..."
  try {
    $headBefore = (git rev-parse HEAD 2>$null).Trim()
    git pull --ff-only | Out-Host
    $headAfter = (git rev-parse HEAD 2>$null).Trim()
    $repoUpdated = $headBefore -and $headAfter -and ($headBefore -ne $headAfter)
    if ($repoUpdated) {
      Write-Host "Repository updated: $($headBefore.Substring(0,8)) -> $($headAfter.Substring(0,8))" -ForegroundColor Green
    } else {
      Write-Host "Repository already current." -ForegroundColor DarkGray
    }
  } catch {
    Write-Warning "git pull was skipped: $($_.Exception.Message)"
  }
} else {
  Write-Host "[1/6] Git is not on PATH - continuing with local files."
}

# Local-only mode is safe for diagnostics. It does not require a GitHub PAT,
# public DNS or a random trycloudflare.com URL; no customer repos are published.
if ($LocalOnly) {
  Write-Host "LOCAL MODE: no public tunnel or GitHub publishing" -ForegroundColor Cyan
  & (Join-Path $repoRoot 'api\start-local.ps1') -SkipGitHub -Model $Model -Port $Port
  return
}

$env:DESIGN_CRITIC_MODE = "adaptive"
$env:MODEL_QA_MODE = "deterministic"
$env:VISUAL_QA_VISION_MAX_PAGES = "1"
$env:TEXT_REPAIR_ATTEMPTS = "1"
$env:VISUAL_REPAIR_ATTEMPTS = "1"
$env:MODEL_REPAIR_FILES_PER_ATTEMPT = "2"
$env:MODEL_ROUTING = "adaptive"
$systemRamGB = 0
try {
  $systemRamGB = [math]::Round((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB, 1)
} catch {}

# V7 RAM-aware defaults. Respect explicit user overrides, and avoid
# overcommitting Ollama inference, Chromium and project workers on 8 GB PCs.
$lowMemoryProfile = $systemRamGB -gt 0 -and $systemRamGB -le 12
# Balanced 16 GB hosts can still page heavily when Ollama, Chromium and
# several builders load together. Prefer stability; benchmarks may override.
$stableMemoryProfile = $systemRamGB -eq 0 -or $systemRamGB -le 20
$autoModelConcurrency = if ($systemRamGB -ge 24) { "2" } else { "1" }
$autoWorkers = if ($stableMemoryProfile) { "1" } else { "4" }
$autoVisualConcurrency = if ($stableMemoryProfile) { "1" } else { "2" }
$autoLoadedModels = if ($stableMemoryProfile) { "1" } else { "2" }
if (-not $env:MODEL_CONCURRENCY) { $env:MODEL_CONCURRENCY = $autoModelConcurrency }
if (-not $env:PRODUCTION_WORKERS) { $env:PRODUCTION_WORKERS = $autoWorkers }
if (-not $env:VISUAL_QA_CONCURRENCY) { $env:VISUAL_QA_CONCURRENCY = $autoVisualConcurrency }
if (-not $env:OLLAMA_EXPERT_KEEP_ALIVE) { $env:OLLAMA_EXPERT_KEEP_ALIVE = "10s" }
if (-not $env:OLLAMA_FAST_KEEP_ALIVE) { $env:OLLAMA_FAST_KEEP_ALIVE = if ($stableMemoryProfile) { "90s" } else { "10m" } }
if (-not $env:OLLAMA_VISION_KEEP_ALIVE) { $env:OLLAMA_VISION_KEEP_ALIVE = if ($stableMemoryProfile) { "15s" } else { "10m" } }
if (-not $env:OLLAMA_NUM_PARALLEL) { $env:OLLAMA_NUM_PARALLEL = $env:MODEL_CONCURRENCY }
if (-not $env:OLLAMA_MAX_LOADED_MODELS) { $env:OLLAMA_MAX_LOADED_MODELS = $autoLoadedModels }
if (-not $env:OLLAMA_FLASH_ATTENTION) { $env:OLLAMA_FLASH_ATTENTION = "1" }
if (-not $env:PV_RESOURCE_GUARD_ENABLED) { $env:PV_RESOURCE_GUARD_ENABLED = "1" }
if (-not $env:PV_MIN_FREE_RAM_MB) { $env:PV_MIN_FREE_RAM_MB = if ($lowMemoryProfile) { "768" } else { "1536" } }
if (-not $env:PV_AGENT_V7_ENABLED) { $env:PV_AGENT_V7_ENABLED = "1" }

Write-Host "[2/6] Starting/checking local engine..."
$ollamaOk = $false
try {
  $null = Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/tags" -Method Get -TimeoutSec 3
  $ollamaOk = $true
} catch {}
if (-not $ollamaOk) {
  Start-Process powershell -ArgumentList @('-NoExit','-Command','ollama serve')
  $ollamaHealth = Wait-Url "http://127.0.0.1:11434/api/tags" 30
  if (-not $ollamaHealth) { throw "Local engine did not start. Run 'ollama serve' manually and retry." }
}
$tags = Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/tags" -Method Get -TimeoutSec 5
$models = @($tags.models | ForEach-Object { $_.name })
if ($models -notcontains $Model) {
  Write-Host "Downloading local model $Model ..."
  & ollama pull $Model
  if ($LASTEXITCODE -ne 0) { throw "Could not download local model $Model." }
}
Write-Host "Local engine: ONLINE / $Model" -ForegroundColor Green
Write-Host "Factory profile: RAM=$systemRamGB GB · workers=$env:PRODUCTION_WORKERS · model concurrency=$env:MODEL_CONCURRENCY · visual QA=$env:VISUAL_QA_CONCURRENCY" -ForegroundColor DarkCyan

$tags = Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/tags" -Method Get -TimeoutSec 5
$models = @($tags.models | ForEach-Object { $_.name })
$experts = @(
  $models |
    Where-Object {
      $_ -match '(?i)KAT-Coder-V2\.5-Dev' -or
      $_ -match '(?i)Qwen_Qwen3\.6-35B-A3B' -or
      $_ -match '(?i)qwen3\.6:35b-a3b-coding'
    } |
    Select-Object -Unique
)
# Prevent heavy expert routing on memory-constrained systems.
if ($stableMemoryProfile -and $env:PV_ENABLE_LARGE_EXPERT_MODELS -notin @('1','true','yes','on')) {
  if ($experts.Count -gt 0) {
    Write-Warning 'Large expert routing disabled on this host. Set PV_ENABLE_LARGE_EXPERT_MODELS=1 to opt in.'
  }
  $experts = @()
}
if ($experts.Count -gt 0) {
  $env:OLLAMA_EXPERT_MODELS = ($experts -join ',')
  Write-Host "Expert router: ACTIVE / $($experts -join ' + ')" -ForegroundColor Green
  Write-Host "Routing: 7B fast path -> expert model only for difficult coding/repair work" -ForegroundColor DarkCyan
} else {
  $env:OLLAMA_EXPERT_MODELS = ""
  Write-Host "Expert router: no expert model installed; fast 7B path remains active." -ForegroundColor DarkGray
  Write-Host "Optional install: .\install-expert-model.ps1" -ForegroundColor DarkGray
}

Write-Host "[3/6] Preparing GitHub publishing token..."
Write-Host "Use a NEW token. Any token previously pasted into chat must be revoked." -ForegroundColor Yellow
if (-not $env:GITHUB_TOKEN) {
  $env:GITHUB_TOKEN = Read-SecretText "Paste NEW GitHub token (hidden)"
}
if (-not $env:GITHUB_TOKEN) { throw "GitHub token is required for the complete product flow." }
try {
  $headers = @{ Authorization = "Bearer $env:GITHUB_TOKEN"; Accept = "application/vnd.github+json"; "X-GitHub-Api-Version" = "2022-11-28" }
  $gh = Invoke-RestMethod -Uri "https://api.github.com/user" -Headers $headers -Method Get -TimeoutSec 15
  Write-Host "GitHub: CONNECTED as $($gh.login)" -ForegroundColor Green
} catch {
  $statusCode = 0
  if ($_.Exception.Response) {
    $statusCode = [int]$_.Exception.Response.StatusCode
  }
  $env:GITHUB_TOKEN = $null
  if ($statusCode -eq 401) {
    throw "GitHub HTTP 401: token is expired, revoked, malformed or incorrect. Create a fresh fine-grained PAT."
  }
  if ($statusCode -eq 403) {
    throw "GitHub HTTP 403: token lacks permission, is restricted or was rate-limited. Review GitHub token access."
  }
  throw "GitHub token validation failed (HTTP $statusCode). Check GitHub availability and network access."
}

Write-Host "[4/6] Starting/checking website service..."
$health = $null
try { $health = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/health" -Method Get -TimeoutSec 3 } catch {}
if ($health -and $health.ok) {
  $listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
  if ($listener) {
    $old = Get-Process -Id $listener.OwningProcess -ErrorAction SilentlyContinue
    $details = Get-CimInstance Win32_Process -Filter "ProcessId=$($listener.OwningProcess)" -ErrorAction SilentlyContinue
    $isOurApi = $old -and $old.ProcessName -match 'python|uvicorn' -and
      $details -and $details.CommandLine -match '(?i)(uvicorn\s+api\.server:app|api[\\/]server\.py)'
    if (-not $isOurApi) {
      throw "Port $Port belongs to another process. Refusing to stop unrelated service PID $($listener.OwningProcess)."
    }
    Write-Host "Restarting Project Visibility API PID $($old.Id) to load updated code..." -ForegroundColor Yellow
    Stop-Process -Id $old.Id -Force
    Start-Sleep -Seconds 1
    $health = $null
  }
}

if ($health -and $health.ok) {
  if (-not $health.github_configured) {
    $listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    $pidText = if ($listener) { $listener.OwningProcess } else { "unknown" }
    throw "An old service is already running WITHOUT GitHub token on port $Port (PID $pidText). Stop it and run this script again."
  }
  Write-Host "Service: already ONLINE" -ForegroundColor Green
} else {
  $apiScript = Join-Path $repoRoot "api\start-local.ps1"

  $parseTokens = $null
  $parseErrors = $null
  [void][System.Management.Automation.Language.Parser]::ParseFile(
    $apiScript,
    [ref]$parseTokens,
    [ref]$parseErrors
  )
  if ($parseErrors -and $parseErrors.Count -gt 0) {
    $details = ($parseErrors | ForEach-Object { "line $($_.Extent.StartLineNumber): $($_.Message)" }) -join "; "
    throw "Local API startup script has a PowerShell syntax error: $details"
  }

  Start-Process powershell -ArgumentList @('-NoExit','-NoProfile','-ExecutionPolicy','Bypass','-File',$apiScript,'-Model',$Model)
  $health = Wait-Url "http://127.0.0.1:$Port/health" 90
  if (-not $health -or -not $health.ok) { throw "Website service did not become healthy on port $Port." }
  if (-not $health.github_configured) { throw "Service started, but GitHub publishing is not configured." }
  Write-Host "Service: ONLINE / GitHub enabled" -ForegroundColor Green
  if ($health.model) { Write-Host "Production model: $($health.model)" -ForegroundColor Green }
}

Write-Host "[5/6] Selecting a stable, safe connection..." -ForegroundColor Cyan

# Product URLs must not expose logins via random/disposable tunnels.
# An operator-managed Cloudflare named tunnel (or another stable HTTPS API
# hostname) is required for remote access. Default stays on loopback.
$publicApi = [string]$PublicApiUrl
$publicApi = $publicApi.Trim().TrimEnd('/')
$localBuilder = "http://127.0.0.1:$Port/builder.html"
$localHealth = Wait-Url "http://127.0.0.1:$Port/health" 10
if (-not $localHealth -or -not $localHealth.ok) {
  throw "API is offline at http://127.0.0.1:$Port. Check the start-local PowerShell window before opening the builder."
}
if (-not $publicApi) {
  Write-Warning 'No permanent HTTPS API hostname is configured. Public access is disabled to avoid unsafe temporary Quick Tunnel URLs.'
  Write-Host "LOCAL BUILDER: $localBuilder" -ForegroundColor Green
  Write-Host "LOCAL HEALTH:  http://127.0.0.1:$Port/health" -ForegroundColor Cyan
  Write-Host "For remote access, configure a stable named tunnel and launch with -PublicApiUrl https://api.your-domain.example."
  Start-Process $localBuilder
  return
}

try {
  $uri = [Uri]$publicApi
} catch {
  throw 'PublicApiUrl must be a valid HTTPS URL for your own stable domain.'
}
if ($uri.Scheme -ne 'https' -or
    -not $uri.IsAbsoluteUri -or
    $uri.UserInfo -or
    $uri.Query -or
    $uri.Fragment -or
    $uri.AbsolutePath -ne '/' -or
    $uri.Host -match '(?i)(^|\.)trycloudflare\.com$') {
  throw 'Refusing temporary or unsafe public API URL. Configure a stable HTTPS hostname on a named tunnel instead.'
}

Write-Host "[6/6] Checking stable remote API before opening the frontend..."
$remoteHealth = Wait-Url "$publicApi/health" 15
if (-not $remoteHealth -or -not $remoteHealth.ok -or
    $remoteHealth.product -ne 'project_visibility') {
  throw "Stable remote API did not identify itself as Project Visibility: $publicApi. No public builder was opened."
}
if (-not $remoteHealth.github_configured) {
  throw 'Stable remote API is responding but GitHub publishing is not configured.'
}
$encodedApi = [Uri]::EscapeDataString($publicApi)
$stableBuilder = "https://dday2301.github.io/PROJEKT/builder.html?api=$encodedApi"
Write-Host "STABLE FRONTEND: $stableBuilder" -ForegroundColor Green
Write-Host "STABLE API:      $publicApi" -ForegroundColor Cyan
Write-Host "LOCAL BUILDER:   $localBuilder" -ForegroundColor Cyan
Write-Host 'Never accept browser Dangerous warnings or enter credentials on untrusted tunnel URLs.' -ForegroundColor Yellow
Start-Process $stableBuilder
