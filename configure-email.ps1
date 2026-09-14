$ErrorActionPreference = "Stop"
$repoRoot = $PSScriptRoot
Set-Location $repoRoot

function Secure-ToText([System.Security.SecureString]$Secure) {
  $ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($Secure)
  try { return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr) }
  finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr) }
}

Write-Host "PROJECT VISIBILITY - EMAIL SETUP" -ForegroundColor Green
Write-Host "This stores the Resend API key encrypted with Windows DPAPI for the current Windows user." -ForegroundColor DarkCyan
Write-Host ""

$secret = Read-Host "Paste Resend API key (hidden)" -AsSecureString
$plain = Secure-ToText $secret
if (-not $plain) { throw "No API key supplied." }

$secretFile = Join-Path $repoRoot "api\data\.resend-secret"
$dir = Split-Path $secretFile -Parent
New-Item -ItemType Directory -Force -Path $dir | Out-Null
$secret | ConvertFrom-SecureString | Set-Content -Path $secretFile -NoNewline

$from = Read-Host "From address (Enter = Project Visibility <onboarding@resend.dev>)"
if (-not $from) { $from = "Project Visibility <onboarding@resend.dev>" }
$fromFile = Join-Path $repoRoot "api\data\.resend-from"
Set-Content -Path $fromFile -Value $from -NoNewline

Write-Host ""
Write-Host "Email delivery configured." -ForegroundColor Green
Write-Host "Restart start-stable-local.ps1 so the API loads the new settings." -ForegroundColor Yellow
