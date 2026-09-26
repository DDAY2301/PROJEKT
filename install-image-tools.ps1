param([switch]$SkipRembg)
$ErrorActionPreference="Stop"
$root=$PSScriptRoot
Set-Location $root
if(-not (Test-Path ".venv\Scripts\python.exe")) {
  Write-Host "Virtual environment not found. Run .\start-product.ps1 once first." -ForegroundColor Yellow
  exit 1
}
if(-not $SkipRembg) {
  Write-Host "Installing optional local AI background-removal engine (rembg CPU)..." -ForegroundColor Cyan
  & ".\.venv\Scripts\python.exe" -m pip install --upgrade "rembg[cpu]"
  if($LASTEXITCODE -ne 0){ throw "rembg installation failed" }
}
Write-Host ""
Write-Host "IMAGE TOOLS READY" -ForegroundColor Green
Write-Host "- Pillow edit/compose: built in"
Write-Host "- rembg: optional local subject extraction installed (unless skipped)"
Write-Host "- ComfyUI: optional; configure COMFYUI_BASE_URL and COMFYUI_CHECKPOINT before start"
Write-Host ""
Write-Host "Restart Project Visibility after installing tools." -ForegroundColor Yellow
