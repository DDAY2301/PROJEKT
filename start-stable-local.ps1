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

if (Get-Command git -ErrorAction SilentlyContinue) {
  Write-Host "[1/6] Updating repository..."
  git pull --ff-only | Out-Host
}

Write-Host "[2/6] Checking local engine..."
try {
  $tags = Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/tags" -TimeoutSec 3
} catch {
  Start-Process powershell -ArgumentList @('-NoExit','-Command','ollama serve')
  $tags = Wait-Json "http://127.0.0.1:11434/api/tags" 30
}
if (-not $tags) { throw "Ollama did not start." }
$models = @($tags.models | ForEach-Object { $_.name })
if ($models -notcontains $Model) {
  & ollama pull $Model
  if ($LASTEXITCODE -ne 0) { throw "Could not download $Model." }
}
Write-Host "Local engine: ONLINE / $Model" -ForegroundColor Green

Write-Host "[3/6] Preparing GitHub publishing..."
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

Write-Host "[4/6] Preparing Stripe Checkout..."
$stripeSecretFile = Join-Path $repoRoot "api\data\.stripe-secret"
if (-not $env:STRIPE_SECRET_KEY -and (Test-Path $stripeSecretFile)) {
  try {
    # ConvertTo/From-SecureString uses Windows DPAPI by default, binding the
    # encrypted value to the current Windows user. No plaintext secret is kept.
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

Write-Host "[5/6] Starting fresh website service..."
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

Write-Host "[6/6] Opening public landing page..."
$localApi = "http://127.0.0.1:$Port"
$encodedApi = [Uri]::EscapeDataString($localApi)
$landing = "https://dday2301.github.io/PROJEKT/?api=$encodedApi&v=stable-local"
$builder = "https://dday2301.github.io/PROJEKT/builder.html?api=$encodedApi&v=stable-local"
Write-Host ""
Write-Host "PUBLIC LANDING: $landing" -ForegroundColor Cyan
Write-Host "BUILDER (opens only after landing choice): $builder" -ForegroundColor DarkCyan
Write-Host "LOCAL HEALTH: $localApi/health" -ForegroundColor Cyan
Write-Host ""
Write-Host "Flow: landing page -> choose package / brief -> builder -> build / publish." -ForegroundColor Green
Write-Host "If Chrome asks whether this site may access devices on your local network, choose Allow." -ForegroundColor Yellow
Write-Host "Keep the Ollama/API window open while building sites." -ForegroundColor Yellow
Start-Process $landing
