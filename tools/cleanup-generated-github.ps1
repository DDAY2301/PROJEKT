<#
.SYNOPSIS
  Review or delete ONLY the exact generated-site repositories inventoried on
  2026-10-11 for DDAY2301. Default is read-only inventory.

.EXAMPLE
  .\tools\cleanup-generated-github.ps1
.EXAMPLE
  .\tools\cleanup-generated-github.ps1 -Execute

Requires fresh fine-grained GitHub PAT with Administration: Read and write for
every target repository. Never paste credentials into chat, Git or script flags.
Before each deletion the script mirror-clones the repository locally.
#>
param(
    [switch]$Execute
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$manifestFile = Join-Path $PSScriptRoot 'generated-site-cleanup-manifest.json'
$manifest = Get-Content -LiteralPath $manifestFile -Raw -Encoding UTF8 | ConvertFrom-Json
$owner = [string]$manifest.owner
$names = @($manifest.generated_repositories)
$protected = @($manifest.protected)

if ($owner -cne 'DDAY2301') { throw 'Refusing unknown GitHub owner.' }
if ($names.Count -ne 21 -or @($names | Select-Object -Unique).Count -ne 21) {
    throw 'Manifest differs from the reviewed 21-repository inventory.'
}
foreach ($name in $names) {
    if ($name -cnotmatch '^generated-site-[a-z0-9][a-z0-9-]*$') {
        throw "Unsafe repository name: $name"
    }
    if ($name -in $protected -or $name -in @('blog-lab','PROJEKT')) {
        throw "Protected production repository found: $name"
    }
}

Write-Host "GitHub generated-site cleanup / owner: $owner" -ForegroundColor Cyan
Write-Host "Production protection: blog-lab, PROJEKT"
Write-Host "Candidate count: $($names.Count)"
$names | ForEach-Object { Write-Host "  $owner/$_" }

if (-not $Execute) {
    Write-Host ''
    Write-Host 'DRY RUN ONLY: no repository deleted, no credential requested.' -ForegroundColor Green
    Write-Host 'To back up and actually delete these exact 21 repositories, rerun with -Execute.'
    return
}

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    throw 'git command is required to create mirror backups before deletion.'
}
$approval = Read-Host "To delete these 21 repositories, type DELETE 21 GENERATED REPOSITORIES"
if ($approval -cne 'DELETE 21 GENERATED REPOSITORIES') {
    throw 'Cancelled; deletion phrase did not match.'
}

$secure = Read-Host 'Enter a fresh GitHub PAT (hidden)' -AsSecureString
$ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
$token = ''
try {
    $token = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr).Trim()
}
finally {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr)
}
if (-not $token) { throw 'Token cannot be empty.' }
$headers = @{
    Authorization = "Bearer $token"
    Accept = 'application/vnd.github+json'
    'X-GitHub-Api-Version' = '2022-11-28'
}
$base = Join-Path $env:LOCALAPPDATA 'ProjectVisibility\CleanupReports'
$timestamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$backupRoot = Join-Path $base $timestamp
New-Item -ItemType Directory -Force -Path $backupRoot | Out-Null
$results = New-Object 'System.Collections.Generic.List[object]'

try {
    # Ensure the token is valid before creating backups/deleting.
    $me = Invoke-RestMethod -Method Get -Uri 'https://api.github.com/user' -Headers $headers -TimeoutSec 20
    Write-Host "Authenticated GitHub account: $($me.login)"
    if ($me.login -ine $owner) {
        throw "Token owner is not $owner. Aborting."
    }

    foreach ($name in $names) {
        $repoApi = "https://api.github.com/repos/$owner/$name"
        $repo = Invoke-RestMethod -Method Get -Uri $repoApi -Headers $headers -TimeoutSec 25
        if ($repo.owner.login -cne $owner -or $repo.name -cne $name) {
            throw "Repository identity mismatch: $name"
        }
        # Backup the complete Git DAG before attempting an irreversible delete.
        $mirror = Join-Path $backupRoot "$name.git"
        Write-Host "Backing up $name -> $mirror" -ForegroundColor Cyan
        & git clone --mirror --quiet $repo.clone_url $mirror
        if ($LASTEXITCODE -ne 0) { throw "Mirror backup failed for $name; deletion aborted." }
        $bare = & git -C $mirror rev-parse --is-bare-repository
        $refs = @(& git -C $mirror show-ref)
        if ($LASTEXITCODE -ne 0 -or $bare -ne 'true' -or $refs.Count -eq 0) {
            throw "Backup verification failed for $name; deletion aborted."
        }

        # Write recovery manifest before destructive call.
        $metaPath = Join-Path $backupRoot "$name.metadata.json"
        $repo | Select-Object id,full_name,html_url,clone_url,default_branch,updated_at |
            ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $metaPath -Encoding UTF8

        Write-Host "Deleting $owner/$name ..." -ForegroundColor Yellow
        try {
            Invoke-RestMethod -Method Delete -Uri $repoApi -Headers $headers -TimeoutSec 40 | Out-Null
            $results.Add([pscustomobject]@{ repository="$owner/$name"; status='deleted'; backup=$mirror })
            Write-Host "Deleted: $owner/$name" -ForegroundColor Green
        }
        catch {
            $results.Add([pscustomobject]@{ repository="$owner/$name"; status='failed'; backup=$mirror })
            throw "GitHub rejected DELETE $owner/$name. Previous deletes, if any, are listed in $backupRoot. $($_.Exception.Message)"
        }
    }
}
finally {
    # Never persist the PAT. Save a recovery-oriented report instead.
    $results | ConvertTo-Json -Depth 5 |
        Set-Content -LiteralPath (Join-Path $backupRoot 'cleanup-results.json') -Encoding UTF8
    $headers.Remove('Authorization')
    Remove-Variable token -ErrorAction SilentlyContinue
    Write-Host "Backup and cleanup report: $backupRoot"
}
Write-Host "Deleted $($results.Count) generated repositories; protected projects unchanged." -ForegroundColor Green
