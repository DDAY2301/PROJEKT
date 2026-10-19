param(
  [ValidateSet('auto','compact','balanced','expert','ultra')]
  [string]$Profile = 'auto'
)

$ErrorActionPreference = 'Stop'
if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) {
  throw 'Install Ollama first: https://ollama.com/download'
}
$ramGb = 0
try { $ramGb = [math]::Round((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB, 1) } catch {}
if ($ramGb -le 0) { throw 'Could not determine installed RAM. Select a model manually after checking available memory.' }

$profileChosen = $Profile
if ($Profile -eq 'auto') {
  if ($ramGb -ge 40) { $profileChosen = 'ultra' }
  elseif ($ramGb -ge 24) { $profileChosen = 'expert' }
  elseif ($ramGb -ge 12) { $profileChosen = 'balanced' }
  elseif ($ramGb -ge 8) { $profileChosen = 'compact' }
  else { throw 'Less than 8 GB RAM: no new automatic model installation is recommended.' }
}
$spec = switch ($profileChosen) {
  'compact'  { @{ Name='qwen3.5:2b'; MinRam=8;  MinDisk=5 } }
  'balanced' { @{ Name='qwen3.5:4b'; MinRam=12; MinDisk=7 } }
  'expert'   { @{ Name='qwen3.5:9b'; MinRam=24; MinDisk=12 } }
  'ultra'    { @{ Name='qwen3.8:27b'; MinRam=40; MinDisk=25 } }
}
if ($ramGb -lt $spec.MinRam) {
  throw "Selected model $($spec.Name) requires at least $($spec.MinRam) GB host RAM for this Project Visibility safety profile."
}
$drive = (Get-Item $PSScriptRoot).PSDrive
if (-not $drive -or $null -eq $drive.Free) { throw 'Unable to verify free disk space. No download was started.' }
$diskGb = [math]::Round($drive.Free / 1GB, 1)
if ($diskGb -lt $spec.MinDisk) {
  throw "Insufficient disk space: $diskGb GB free; at least $($spec.MinDisk) GB required."
}

Write-Host 'PROJECT VISIBILITY — LOCAL MODEL INSTALLER' -ForegroundColor Cyan
Write-Host "Selected: $($spec.Name) / RAM: $ramGb GB / free disk: $diskGb GB" -ForegroundColor Green
Write-Host 'No private customer data, GitHub tokens or cloud API keys are required.' -ForegroundColor DarkCyan

& ollama pull $spec.Name
if ($LASTEXITCODE -ne 0) { throw "Ollama download failed: $($spec.Name)" }
$tags = Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/tags' -Method Get -TimeoutSec 15
$installed = @($tags.models | ForEach-Object { $_.name })
if ($installed -notcontains $spec.Name) { throw 'Downloaded model was not found in the Ollama local inventory.' }
Write-Host "INSTALLED: $($spec.Name)" -ForegroundColor Green
Write-Host 'Restart the current Project Visibility instance with .\start-product.ps1 or specify -Model explicitly.' -ForegroundColor Cyan
Write-Host 'The Builder Local Agent Engine card displays installed / loaded / used status after connection.' -ForegroundColor Cyan
