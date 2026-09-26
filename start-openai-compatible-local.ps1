param(
  [Parameter(Mandatory=$true)]
  [string]$BaseUrl,
  [Parameter(Mandatory=$true)]
  [string]$Models,
  [string]$ApiKey = "",
  [string]$VisualModel = "qwen2.5vl:3b",
  [int]$Port = 8000,
  [switch]$SkipGitHub
)

$ErrorActionPreference = "Stop"
$repoRoot = $PSScriptRoot
Set-Location $repoRoot

$base = $BaseUrl.TrimEnd('/')
if ($base -notmatch '^https?://') {
  throw "BaseUrl must be an http(s) OpenAI-compatible endpoint, for example http://127.0.0.1:1234/v1"
}
$modelList = @($Models.Split(',') | ForEach-Object { $_.Trim() } | Where-Object { $_ })
if (-not $modelList.Count) { throw "Provide at least one model ID in -Models." }

Write-Host ""
Write-Host "PROJECT VISIBILITY - OPENAI-COMPATIBLE LOCAL BACKEND" -ForegroundColor Green
Write-Host "=====================================================" -ForegroundColor Green
Write-Host "Endpoint: $base" -ForegroundColor Cyan
Write-Host "Models:   $($modelList -join ', ')" -ForegroundColor Cyan

$headers = @{}
if ($ApiKey) { $headers.Authorization = "Bearer $ApiKey" }

Write-Host "Checking /models endpoint..."
try {
  $modelResponse = Invoke-RestMethod -Uri "$base/models" -Headers $headers -Method Get -TimeoutSec 12
} catch {
  throw "The OpenAI-compatible model server is not reachable at $base/models. Start LM Studio/vLLM/SGLang first. $($_.Exception.Message)"
}

$available = @($modelResponse.data | ForEach-Object { $_.id })
foreach ($model in $modelList) {
  if ($available.Count -and $available -notcontains $model) {
    Write-Warning "Model '$model' was not returned by /models. The server may still support it, but verify the exact model ID."
  }
}

$env:LOCAL_LLM_MODE = "openai"
$env:OPENAI_COMPAT_BASE_URL = $base
$env:OPENAI_COMPAT_MODELS = ($modelList -join ',')
$env:OPENAI_COMPAT_API_KEY = $ApiKey

Write-Host "Generation backend: OPENAI-COMPATIBLE LOCAL" -ForegroundColor Green
Write-Host "Vision QA remains local through Ollama ($VisualModel)." -ForegroundColor DarkCyan

$launcher = Join-Path $repoRoot "api\start-local.ps1"
$params = @{
  Model = $VisualModel
  VisualModel = $VisualModel
  Port = $Port
}
if ($SkipGitHub) { $params.SkipGitHub = $true }

& $launcher @params
exit $LASTEXITCODE
