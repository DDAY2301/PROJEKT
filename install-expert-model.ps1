param(
  [ValidateSet('auto','IQ3_XXS','Q3_K_M','IQ3_M','Q4_K_M')]
  [string]$Quant = 'auto',
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

Write-Host ""
Write-Host "PROJECT VISIBILITY - EXPERT MODEL INSTALLER" -ForegroundColor Green
Write-Host "===========================================" -ForegroundColor Green
Write-Host ""

if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) {
  throw "Ollama is not installed or not on PATH."
}

$version = Get-OllamaVersion
if ($version -lt [version]'0.30.0') {
  throw "Ollama 0.30+ is required for current GGUF compatibility. Upgrade Ollama first, then rerun this script."
}

$ramGb = Get-RamGb
$diskGb = Get-FreeDiskGb
Write-Host "RAM: $ramGb GB"
Write-Host "Free disk: $diskGb GB"
Write-Host "Ollama: $version"
Write-Host ""

if ($Quant -eq 'auto') {
  if ($ramGb -ge 40 -and $diskGb -ge 27) {
    $Quant = 'Q4_K_M'
  } elseif ($ramGb -ge 24 -and $diskGb -ge 22) {
    $Quant = 'IQ3_M'
  } elseif ($ramGb -ge 20 -and $diskGb -ge 20) {
    $Quant = 'Q3_K_M'
  } elseif ($ForceLowMemory -and $diskGb -ge 18) {
    $Quant = 'IQ3_XXS'
  } else {
    throw "This machine does not have enough comfortable RAM/disk headroom for KAT-Coder. Keep qwen2.5-coder:7b, or rerun with -ForceLowMemory if you accept slower paging."
  }
}

$sizeHint = @{
  'IQ3_XXS' = 'about 14.9 GB'
  'Q3_K_M'  = 'about 16.2 GB'
  'IQ3_M'   = 'about 16.9 GB'
  'Q4_K_M'  = 'about 21.4 GB'
}[$Quant]

$kat = "hf.co/Abiray/KAT-Coder-V2.5-Dev-Imatrix-GGUF:$Quant"

Write-Host "Selected expert model:" -ForegroundColor Cyan
Write-Host "  $kat"
Write-Host "  $sizeHint"
Write-Host ""
Write-Host "KAT is used only for difficult coding/repository/repair tasks." -ForegroundColor DarkCyan
Write-Host "The fast 7B model remains the normal production model." -ForegroundColor DarkCyan
Write-Host ""

Write-Host "Downloading / verifying KAT-Coder..." -ForegroundColor Cyan
& ollama run $kat "Reply exactly READY and nothing else."
if ($LASTEXITCODE -ne 0) {
  if ($Quant -eq 'IQ3_M') {
    Write-Warning "IQ3_M could not be loaded directly. Retrying Q3_K_M."
    $Quant = 'Q3_K_M'
    $kat = "hf.co/Abiray/KAT-Coder-V2.5-Dev-Imatrix-GGUF:$Quant"
    & ollama run $kat "Reply exactly READY and nothing else."
  }
}
if ($LASTEXITCODE -ne 0) { throw "KAT-Coder download/import failed." }

if ($AlsoInstallQwen36) {
  $qwen = 'qwen3.6:35b-a3b-coding'
  Write-Host ""
  Write-Host "Downloading optional Qwen3.6 coding fallback..." -ForegroundColor Cyan
  & ollama pull $qwen
  if ($LASTEXITCODE -ne 0) {
    Write-Warning "Optional Qwen3.6 fallback failed; KAT remains installed."
  }
}

$tags = Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/tags' -Method Get -TimeoutSec 15
$names = @($tags.models | ForEach-Object { $_.name })
$installedKat = @($names | Where-Object { $_ -match '(?i)KAT-Coder-V2\.5-Dev' })
$installedQwen = @($names | Where-Object { $_ -match '(?i)qwen3\.6:35b-a3b-coding' })

Write-Host ""
if ($installedKat.Count -gt 0) {
  Write-Host "KAT-Coder: INSTALLED" -ForegroundColor Green
  $installedKat | ForEach-Object { Write-Host "  $_" -ForegroundColor Green }
} else {
  throw "Ollama finished without exposing KAT-Coder in /api/tags."
}
if ($installedQwen.Count -gt 0) {
  Write-Host "Qwen3.6 coding fallback: INSTALLED" -ForegroundColor Green
}

Write-Host ""
Write-Host "Next:" -ForegroundColor Cyan
Write-Host "  .\start-product.ps1"
Write-Host ""
Write-Host "The startup script will automatically detect KAT and route only expert tasks to it." -ForegroundColor Green
