param(
  [string]$Model = "qwen2.5-coder:3b",
  [int]$Port = 8000
)

$ErrorActionPreference = "Stop"
$repoRoot = $PSScriptRoot
Set-Location $repoRoot

function Secure-ToText([System.Security.SecureString]$Secure) {
  $ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($Secure)
  try { return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr) }
  finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr) }
}

function Read-SecretText([string]$Prompt) {
  return Secure-ToText (Read-Host $Prompt -AsSecureString)
}

function Wait-Json([string]$Url, [int]$Seconds = 60) {
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
Write-Host "PROJECT VISIBILITY - STABLE LOCAL START" -ForegroundColor Green
Write-Host "=======================================" -ForegroundColor Green
Write-Host "GitHub Pages frontend + local loopback agent" -ForegroundColor DarkCyan
Write-Host ""

Write-Host "[1/7] Updating approved agent source..."
if (Get-Command git -ErrorAction SilentlyContinue) {
  git pull --ff-only | Out-Host
  try { $env:PV_SOURCE_COMMIT = (git rev-parse --short HEAD).Trim() } catch { $env:PV_SOURCE_COMMIT = "unknown" }
  Write-Host "Source version: $env:PV_SOURCE_COMMIT" -ForegroundColor Green
} else {
  $env:PV_SOURCE_COMMIT = "unknown"
  Write-Warning "Git was not found; newest approved source cannot be checked automatically."
}

Write-Host "[2/7] Checking local engine and latest model tag..."
try {
  $tags = Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/tags" -TimeoutSec 3
} catch {
  Start-Process powershell -ArgumentList @('-NoExit','-Command','ollama serve')
  $tags = Wait-Json "http://127.0.0.1:11434/api/tags" 30
}
if (-not $tags) { throw "Ollama did not start." }
$models = @($tags.models | ForEach-Object { $_.name })
$hadModel = $models -contains $Model
try {
  & ollama pull $Model | Out-Host
  if ($LASTEXITCODE -ne 0 -and -not $hadModel) { throw "Could not download $Model." }
  if ($LASTEXITCODE -ne 0 -and $hadModel) { Write-Warning "Could not check for a newer model digest; using the installed $Model." }
} catch {
  if (-not $hadModel) { throw }
  Write-Warning "Could not check for a newer model digest; using the installed $Model."
}
Write-Host "Local engine: ONLINE / $Model" -ForegroundColor Green

Write-Host "[3/7] Preparing GitHub publishing..."
if (-not $env:GITHUB_TOKEN) {
  $env:GITHUB_TOKEN = Read-SecretText "Paste GitHub token (hidden)"
}
if (-not $env:GITHUB_TOKEN) { throw "GitHub token is required." }
$headers = @{ Authorization = "Bearer $env:GITHUB_TOKEN"; Accept = "application/vnd.github+json"; "X-GitHub-Api-Version" = "2022-11-28" }
try {
  $gh = Invoke-RestMethod -Uri "https://api.github.com/user" -Headers $headers -TimeoutSec 15
} catch {
  throw "GitHub token validation failed."
}
Write-Host "GitHub: CONNECTED as $($gh.login)" -ForegroundColor Green

Write-Host "[4/7] Preparing Stripe Checkout..."
$stripeSecretFile = Join-Path $repoRoot "api\data\.stripe-secret"
if (-not $env:STRIPE_SECRET_KEY -and (Test-Path $stripeSecretFile)) {
  try {
    $savedSecure = (Get-Content $stripeSecretFile -Raw).Trim() | ConvertTo-SecureString
    $env:STRIPE_SECRET_KEY = Secure-ToText $savedSecure
  } catch {
    Remove-Item $stripeSecretFile -Force -ErrorAction SilentlyContinue
  }
}
if (-not $env:STRIPE_SECRET_KEY) {
  $secureCandidate = Read-Host "Paste Stripe secret key (hidden; Enter = checkout disabled)" -AsSecureString
  $candidate = Secure-ToText $secureCandidate
  if ($candidate) {
    $env:STRIPE_SECRET_KEY = $candidate.Trim()
    $secretDir = Split-Path $stripeSecretFile -Parent
    New-Item -ItemType Directory -Force -Path $secretDir | Out-Null
    $secureCandidate | ConvertFrom-SecureString | Set-Content -Path $stripeSecretFile -NoNewline
  }
}
if (-not $env:PUBLIC_BUILDER_URL) {
  $env:PUBLIC_BUILDER_URL = "https://dday2301.github.io/PROJEKT/builder.html"
}
if (-not $env:PUBLIC_DASHBOARD_URL) {
  $env:PUBLIC_DASHBOARD_URL = "https://dday2301.github.io/PROJEKT/dashboard.html"
}
if ($env:STRIPE_SECRET_KEY) {
  if ($env:STRIPE_SECRET_KEY -like 'sk_live_*') {
    Write-Host "Stripe Checkout: LIVE / Start 490 EUR / Standard 890 EUR / Premium 1490 EUR" -ForegroundColor Yellow
  } elseif ($env:STRIPE_SECRET_KEY -like 'sk_test_*') {
    Write-Host "Stripe Checkout: TEST / Start 490 EUR / Standard 890 EUR / Premium 1490 EUR" -ForegroundColor Green
  } else {
    Write-Warning "Stripe key format was not recognized. Checkout may fail until a valid secret key is supplied."
  }
} else {
  Write-Host "Stripe Checkout: DISABLED (development fallback)" -ForegroundColor DarkYellow
}

Write-Host "[5/7] Loading customer email delivery..."
$resendSecretFile = Join-Path $repoRoot "api\data\.resend-secret"
$resendFromFile = Join-Path $repoRoot "api\data\.resend-from"
if (-not $env:RESEND_API_KEY -and (Test-Path $resendSecretFile)) {
  try {
    $savedResend = (Get-Content $resendSecretFile -Raw).Trim() | ConvertTo-SecureString
    $env:RESEND_API_KEY = Secure-ToText $savedResend
  } catch {
    Write-Warning "Saved email key could not be loaded. Run .\configure-email.ps1 again."
  }
}
if (-not $env:RESEND_FROM_EMAIL -and (Test-Path $resendFromFile)) {
  $env:RESEND_FROM_EMAIL = (Get-Content $resendFromFile -Raw).Trim()
}
if ($env:RESEND_API_KEY) {
  if (-not $env:RESEND_FROM_EMAIL) { $env:RESEND_FROM_EMAIL = "Project Visibility <onboarding@resend.dev>" }
  Write-Host "Customer email: ENABLED / $env:RESEND_FROM_EMAIL" -ForegroundColor Green
} else {
  Write-Host "Customer email: DISABLED / run .\configure-email.ps1 once to enable handoff emails" -ForegroundColor DarkYellow
}

Write-Host "[6/7] Starting fresh website service..."
$listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if ($listener) {
  $proc = Get-Process -Id $listener.OwningProcess -ErrorAction SilentlyContinue
  if ($proc -and $proc.ProcessName -match 'python|uvicorn') {
    Write-Host "Restarting previous service PID $($listener.OwningProcess) so the newest code is loaded..." -ForegroundColor DarkYellow
    Stop-Process -Id $listener.OwningProcess -Force
    Start-Sleep -Seconds 2
  } else {
    throw "Port $Port is occupied by PID $($listener.OwningProcess). Stop that process first."
  }
}

$apiScript = Join-Path $repoRoot "api\start-local.ps1"
Start-Process powershell -ArgumentList @('-NoExit','-ExecutionPolicy','Bypass','-File',$apiScript,'-Model',$Model)
$health = Wait-Json "http://127.0.0.1:$Port/health" 90
if (-not $health -or -not $health.ok) { throw "Website service did not start on port $Port." }
if (-not $health.github_configured) { throw "Website service is online but GitHub publishing is not enabled." }
Write-Host "Service: ONLINE / GitHub enabled" -ForegroundColor Green

try {
  $billing = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/billing/config" -Method Get -TimeoutSec 10
  if ($billing.enabled) {
    Write-Host "Payments: READY / hosted Stripe Checkout" -ForegroundColor Green
  } else {
    Write-Host "Payments: OFF / development mode" -ForegroundColor DarkYellow
  }
} catch {
  Write-Warning "Could not verify Stripe billing endpoint."
}

try {
  $preflightHeaders = @{
    Origin = 'https://dday2301.github.io'
    'Access-Control-Request-Method' = 'GET'
    'Access-Control-Request-Private-Network' = 'true'
  }
  $preflight = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/health" -Method Options -Headers $preflightHeaders -UseBasicParsing -TimeoutSec 10
  $pna = $preflight.Headers['Access-Control-Allow-Private-Network']
  if ($pna -ne 'true') { Write-Warning "Local Network Access header was not detected. Chrome may ask for permission or block the local bridge." }
  else { Write-Host "Browser local-network bridge: READY" -ForegroundColor Green }
} catch {
  Write-Warning "Could not verify browser local-network preflight. The API itself is still online."
}

Write-Host "[7/7] Opening public landing page..."
$localApi = "http://127.0.0.1:$Port"
$encodedApi = [Uri]::EscapeDataString($localApi)
$landing = "https://dday2301.github.io/PROJEKT/?api=$encodedApi&v=stable-local"
$builder = "https://dday2301.github.io/PROJEKT/builder.html?api=$encodedApi&v=stable-local"
Write-Host ""
Write-Host "PUBLIC LANDING: $landing" -ForegroundColor Cyan
Write-Host "BUILDER (opens only after landing choice): $builder" -ForegroundColor DarkCyan
Write-Host "LOCAL HEALTH: $localApi/health" -ForegroundColor Cyan
Write-Host "SOURCE: $env:PV_SOURCE_COMMIT / newest approved GitHub main" -ForegroundColor Green
Write-Host ""
Write-Host "Flow: landing -> package/brief -> builder/media -> generation -> private preview -> payment -> live." -ForegroundColor Green
Write-Host "The agent reloads persistent learning from SQLite on every build and updates approved source/model tags on restart." -ForegroundColor Green
Write-Host "If Chrome asks whether this site may access devices on your local network, choose Allow." -ForegroundColor Yellow
Write-Host "Keep the Ollama/API window open while building sites." -ForegroundColor Yellow
Start-Process $landing
