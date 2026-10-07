param(
  [ValidateSet('auto','KAT-IQ3_XXS','KAT-Q3_K_M','KAT-IQ3_M','KAT-Q4_K_M','QWEN-IQ2_XXS','QWEN-IQ2_M')]
  [string]$Profile = 'auto',
  [switch]$ForceLowMemory,
  [switch]$AlsoInstallQwen36
)

$ErrorActionPreference = 'Stop'
$repoRoot = $PSScriptRoot
Set-Location $repoRoot

function Get-OllamaVersion {
  try {
    $text = (& ollama --version 2>&1 | Out-String)
    if ($text -match '(\d+\.\d+\.\d+)') { return [version]$Matches[1] }
  } catch {}
  return [version]'0.0.0'
}

function Get-FreeDiskGb {
  $drive = (Get-Item $repoRoot).PSDrive
  if ($drive -and $drive.Free) { return [math]::Round($drive.Free / 1GB, 1) }
  return 0
}

function Get-RamGb {
  try {
    $bytes = (Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory
    return [math]::Round($bytes / 1GB, 1)
  } catch { return 0 }
}

function Install-Expert([string]$Model) {
  Write-Host "Downloading / verifying expert model..." -ForegroundColor Cyan
  Write-Host "  $Model" -ForegroundColor Cyan
  & ollama run $Model "Reply exactly READY and nothing else."
  if ($LASTEXITCODE -ne 0) {
    throw "Expert model download/import failed: $Model"
  }
}

Write-Host ""
Write-Host "PROJECT VISIBILITY - ADAPTIVE EXPERT INSTALLER" -ForegroundColor Green
Write-Host "==============================================" -ForegroundColor Green
Write-Host ""

if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) {
  throw "Ollama is not installed or not on PATH."
}

$version = Get-OllamaVersion
if ($version -lt [version]'0.30.0') {
  throw "Ollama 0.30+ is required. Upgrade Ollama first, then rerun this script."
}

$ramGb = Get-RamGb
$diskGb = Get-FreeDiskGb
Write-Host "RAM: $ramGb GB"
Write-Host "Free disk: $diskGb GB"
Write-Host "Ollama: $version"
Write-Host ""

$katRepo = "hf.co/Abiray/KAT-Coder-V2.5-Dev-Imatrix-GGUF"
$qwenRepo = "hf.co/bartowski/Qwen_Qwen3.6-35B-A3B-GGUF"

if ($Profile -eq 'auto') {
  if ($ramGb -ge 40 -and $diskGb -ge 27) {
    $Profile = 'KAT-Q4_K_M'
  } elseif ($ramGb -ge 24 -and $diskGb -ge 22) {
    $Profile = 'KAT-IQ3_M'
  } elseif ($ramGb -ge 20 -and $diskGb -ge 20) {
    $Profile = 'KAT-IQ3_XXS'
  } elseif ($ramGb -ge 17 -and $diskGb -ge 16) {
    $Profile = 'QWEN-IQ2_M'
  } elseif ($ramGb -ge 14 -and $diskGb -ge 14) {
    $Profile = 'QWEN-IQ2_XXS'
  } elseif ($ForceLowMemory -and $diskGb -ge 14) {
    $Profile = 'QWEN-IQ2_XXS'
  } else {
    throw "This machine should stay on qwen2.5-coder:7b. There is not enough safe RAM headroom even for the compact 35B-A3B expert."
  }
}

switch ($Profile) {
  'KAT-IQ3_XXS' {
    $expert = $katRepo + ":IQ3_XXS"
    $sizeHint = "about 14.9 GB"
    $kind = "KAT expert"
  }
  'KAT-Q3_K_M' {
    $expert = $katRepo + ":Q3_K_M"
    $sizeHint = "about 16.2 GB"
    $kind = "KAT expert"
  }
  'KAT-IQ3_M' {
    $expert = $katRepo + ":IQ3_M"
    $sizeHint = "about 16.9 GB"
    $kind = "KAT expert"
  }
  'KAT-Q4_K_M' {
    $expert = $katRepo + ":Q4_K_M"
    $sizeHint = "about 21.4 GB"
    $kind = "KAT expert"
  }
  'QWEN-IQ2_M' {
    $expert = $qwenRepo + ":IQ2_M"
    $sizeHint = "about 13.0 GB"
    $kind = "Qwen3.6 compact expert"
  }
  'QWEN-IQ2_XXS' {
    $expert = $qwenRepo + ":IQ2_XXS"
    $sizeHint = "about 10.7 GB"
    $kind = "Qwen3.6 compact expert"
  }
  default { throw "Unsupported profile: $Profile" }
}

Write-Host "Selected profile: $Profile" -ForegroundColor Green
Write-Host "Expert type: $kind"
Write-Host "Approx model weights: $sizeHint"
Write-Host ""
Write-Host "The normal production model remains qwen2.5-coder:7b." -ForegroundColor DarkCyan
Write-Host "This larger model is loaded only for difficult coding/repository/repair tasks." -ForegroundColor DarkCyan
Write-Host ""

Install-Expert $expert

if ($AlsoInstallQwen36 -and $kind -notmatch 'Qwen3\.6') {
  Write-Host ""
  Write-Host "Downloading optional full Qwen3.6 coding fallback..." -ForegroundColor Cyan
  & ollama pull "qwen3.6:35b-a3b-coding"
  if ($LASTEXITCODE -ne 0) {
    Write-Warning "Optional Qwen3.6 coding fallback failed; the selected expert remains installed."
  }
}

$tags = Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/tags' -Method Get -TimeoutSec 15
$names = @($tags.models | ForEach-Object { $_.name })
$installed = @(
  $names |
    Where-Object {
      $_ -match '(?i)KAT-Coder-V2\.5-Dev' -or
      $_ -match '(?i)Qwen_Qwen3\.6-35B-A3B' -or
      $_ -match '(?i)qwen3\.6:35b-a3b-coding'
    }
)

Write-Host ""
if ($installed.Count -gt 0) {
  Write-Host "Expert models available to the adaptive router:" -ForegroundColor Green
  $installed | ForEach-Object { Write-Host "  $_" -ForegroundColor Green }
} else {
  throw "Ollama finished without exposing the installed expert in /api/tags."
}

Write-Host ""
Write-Host "Next:" -ForegroundColor Cyan
Write-Host "  .\start-product.ps1"
Write-Host ""
Write-Host "The startup script will auto-detect the compact or KAT expert model." -ForegroundColor Green
