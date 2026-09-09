param(
  [string]$Model = "qwen2.5-coder:3b",
  [int]$Port = 8000
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
      $r = Invoke-RestMethod -Uri $Url -Method Get -TimeoutSec 3
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

if (Get-Command git -ErrorAction SilentlyContinue) {
  Write-Host "[1/6] Updating GitHub repository..."
  try { git pull --ff-only | Out-Host } catch { Write-Warning "git pull was skipped: $($_.Exception.Message)" }
} else {
  Write-Host "[1/6] Git is not on PATH - continuing with local files."
}

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
  $env:GITHUB_TOKEN = $null
  throw "GitHub token validation failed. Create a new token with repository write/administration access."
}

Write-Host "[4/6] Starting/checking website service..."
$health = $null
try { $health = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/health" -Method Get -TimeoutSec 3 } catch {}
if ($health -and $health.ok) {
  if (-not $health.github_configured) {
    $listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    $pidText = if ($listener) { $listener.OwningProcess } else { "unknown" }
    throw "An old service is already running WITHOUT GitHub token on port $Port (PID $pidText). Stop it and run this script again."
  }
  Write-Host "Service: already ONLINE" -ForegroundColor Green
} else {
  $apiScript = Join-Path $repoRoot "api\start-local.ps1"
  Start-Process powershell -ArgumentList @('-NoExit','-ExecutionPolicy','Bypass','-File',$apiScript,'-Model',$Model)
  $health = Wait-Url "http://127.0.0.1:$Port/health" 90
  if (-not $health -or -not $health.ok) { throw "Website service did not become healthy on port $Port." }
  if (-not $health.github_configured) { throw "Service started, but GitHub publishing is not configured." }
  Write-Host "Service: ONLINE / GitHub enabled" -ForegroundColor Green
}

Write-Host "[5/6] Starting secure Cloudflare quick tunnel..."
$cloudflared = $null
$cmd = Get-Command cloudflared -ErrorAction SilentlyContinue
if ($cmd) { $cloudflared = $cmd.Source }
if (-not $cloudflared) {
  $candidate = Get-ChildItem "$env:USERPROFILE\Downloads\cloudflared*.exe" -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 1
  if ($candidate) { $cloudflared = $candidate.FullName }
}
if (-not $cloudflared) { throw "cloudflared was not found. Install it or place cloudflared-windows-amd64.exe in Downloads." }

$dataDir = Join-Path $repoRoot "api\data"
New-Item -ItemType Directory -Force -Path $dataDir | Out-Null
$cfLog = Join-Path $dataDir "cloudflared.log"
if (Test-Path $cfLog) { Remove-Item $cfLog -Force }

$escapedExe = $cloudflared.Replace("'", "''")
$escapedLog = $cfLog.Replace("'", "''")
$cfCommand = "& '$escapedExe' tunnel --url http://127.0.0.1:$Port 2>&1 | ForEach-Object { `$line = `$_.ToString(); Add-Content -LiteralPath '$escapedLog' -Value `$line; Write-Host `$line }"
Start-Process powershell -ArgumentList @('-NoExit','-Command',$cfCommand)

$tunnelUrl = $null
$deadline = (Get-Date).AddSeconds(45)
while ((Get-Date) -lt $deadline -and -not $tunnelUrl) {
  if (Test-Path $cfLog) {
    $raw = Get-Content $cfLog -Raw -ErrorAction SilentlyContinue
    $match = [regex]::Match($raw, 'https://[a-z0-9-]+\.trycloudflare\.com', 'IgnoreCase')
    if ($match.Success) { $tunnelUrl = $match.Value }
  }
  if (-not $tunnelUrl) { Start-Sleep -Seconds 1 }
}
if (-not $tunnelUrl) {
  throw "Cloudflare tunnel started but its public URL was not detected. Check $cfLog."
}

Write-Host "Cloudflare URL created: $tunnelUrl" -ForegroundColor DarkCyan
Write-Host "Waiting for the Cloudflare edge route to become ready..."
$publicHealth = $null
$publicDeadline = (Get-Date).AddSeconds(90)
$attempt = 0
while ((Get-Date) -lt $publicDeadline -and -not $publicHealth) {
  $attempt += 1
  try {
    $candidateHealth = Invoke-RestMethod -Uri "$tunnelUrl/health" -Method Get -TimeoutSec 8
    if ($candidateHealth -and $candidateHealth.ok) {
      $publicHealth = $candidateHealth
      break
    }
  } catch {
    if ($attempt -eq 1 -or ($attempt % 5) -eq 0) {
      Write-Host "Cloudflare propagation attempt $attempt - not ready yet..." -ForegroundColor DarkYellow
    }
  }
  Start-Sleep -Seconds 2
}

if (-not $publicHealth) {
  Write-Warning "Cloudflare URL was created but the automatic public health check did not become ready within 90 seconds."
  Write-Warning "The tunnel window is still running. You can test manually: $tunnelUrl/health"
  if (Test-Path $cfLog) {
    Write-Host "Last Cloudflare log lines:" -ForegroundColor Yellow
    Get-Content $cfLog -Tail 12 -ErrorAction SilentlyContinue | Out-Host
  }
} else {
  Write-Host "Cloudflare: ONLINE / $tunnelUrl" -ForegroundColor Green
}

Write-Host "[6/6] Selecting public product URL..."
$encodedApi = [Uri]::EscapeDataString($tunnelUrl)
$githubLanding = "https://dday2301.github.io/PROJEKT/"
$githubRuntime = "https://dday2301.github.io/PROJEKT/runtime.html?api=$encodedApi"
$tunnelLanding = "$tunnelUrl/"
$tunnelBuilder = "$tunnelUrl/builder.html?api=$encodedApi&v=20260909-5"
$publicLanding = $githubLanding
$publicBuilder = $githubRuntime
$frontendSource = "GitHub Pages handoff -> same-origin HTTPS runtime"

# GitHub Pages is the public entry point, but the actual builder is handed off
# to the active Cloudflare origin. This keeps frontend and API on the same HTTPS
# origin and avoids browser CORS / Failed-to-fetch failures. If Pages is still
# propagating, open the exact same builder directly through Cloudflare.
try {
  $cacheBust = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
  $probeUrl = "$githubRuntime&pv=$cacheBust"
  $probe = Invoke-WebRequest -Uri $probeUrl -UseBasicParsing -Method Get -TimeoutSec 15
  if ($probe.StatusCode -lt 200 -or $probe.StatusCode -ge 400) { throw "GitHub Pages returned HTTP $($probe.StatusCode)" }
  Write-Host "Frontend handoff: GitHub Pages ONLINE" -ForegroundColor Green
} catch {
  $frontendSource = "Cloudflare same-origin HTTPS runtime"
  $publicLanding = $tunnelLanding
  $publicBuilder = $tunnelBuilder
  Write-Warning "GitHub Pages handoff is still propagating or returned 404. Opening the same-origin Cloudflare builder directly."
  Write-Host "Frontend: Cloudflare same-origin ONLINE" -ForegroundColor Green
}

Write-Host ""
Write-Host "PUBLIC LANDING: $publicLanding" -ForegroundColor Cyan
Write-Host "PUBLIC BUILDER: $publicBuilder" -ForegroundColor Cyan
Write-Host "FRONTEND SOURCE: $frontendSource" -ForegroundColor Cyan
Write-Host "PUBLIC SERVICE HEALTH: $tunnelUrl/health" -ForegroundColor Cyan
Write-Host "LOCAL HEALTH: http://127.0.0.1:$Port/health" -ForegroundColor Cyan
Write-Host ""
Write-Host "Keep the local engine, service and Cloudflare windows open while the product is in use." -ForegroundColor Yellow
Start-Process $publicBuilder
