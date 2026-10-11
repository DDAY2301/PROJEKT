<#
.SYNOPSIS
  Non-destructive Windows host audit for Project Visibility / Agent Manager.
  No service changes, process termination, antivirus changes or new folders.
.EXAMPLE
  .\tools\inspect-agent-host.ps1
#>
param([switch]$AsJson)
$ErrorActionPreference = 'Stop'
$os = Get-CimInstance Win32_OperatingSystem
$machine = Get-CimInstance Win32_ComputerSystem
$totalGB = [math]::Round([double]$machine.TotalPhysicalMemory / 1GB, 2)
$freeGB = [math]::Round([double]$os.FreePhysicalMemory * 1KB / 1GB, 2)
$usedGB = [math]::Round($totalGB - $freeGB, 2)
$memPct = if ($totalGB -gt 0) { [math]::Round(100 * $usedGB / $totalGB, 1) } else { 0 }

$processes = @(Get-CimInstance Win32_Process | Where-Object {
    $_.Name -match '(?i)^(pythonw?|ollama|ollama_llama_server|chrome|chromium|msedge|cloudflared)\.exe$'
} | Select-Object -Property Name,ProcessId,
    @{n='WorkingSetMB';e={[math]::Round([double]$_.WorkingSetSize / 1MB, 1)}},
    @{n='PrivateMB';e={[math]::Round([double]$_.PrivatePageCount / 1MB, 1)}}
)
$top = @(Get-CimInstance Win32_Process | Sort-Object WorkingSetSize -Descending |
    Select-Object -First 12 -Property Name,ProcessId,
    @{n='WorkingSetMB';e={[math]::Round([double]$_.WorkingSetSize / 1MB, 1)}})
$ports = foreach ($port in @(8000,8787,11434)) {
    $conn = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
        Select-Object -First 1
    [pscustomobject]@{ Port = $port; Listening = [bool]$conn; PID = if ($conn) { $conn.OwningProcess } else { $null } }
}
$ollamaModels = @()
try {
    $running = Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/ps' -TimeoutSec 3
    $ollamaModels = @($running.models | ForEach-Object {
        [pscustomobject]@{ Name = $_.name; SizeGB = [math]::Round([double]$_.size / 1GB, 2); ExpiresAt = $_.expires_at }
    })
} catch {}

$result = [pscustomobject]@{
    Timestamp = (Get-Date).ToString('o')
    RAM = [pscustomobject]@{ TotalGB = $totalGB; FreeGB = $freeGB; UsedGB = $usedGB; UtilizationPercent = $memPct }
    ProcessCount = $processes.Count
    AgentRelevantProcesses = @($processes | Sort-Object WorkingSetMB -Descending)
    TopWindowsProcesses = $top
    LocalPorts = @($ports)
    OllamaLoadedModels = $ollamaModels
    Recommendations = @(
        'Do not disable Windows services, antivirus or paging file.',
        'Avoid running extra Chromium browsers while Ollama is memory constrained.',
        'Use PRODUCTION_WORKERS=1 and MODEL_CONCURRENCY=1 during initial quality benchmark.',
        'Measure actual free RAM and model reload latency before increasing parallelism.'
    )
}
if ($AsJson) {
    $result | ConvertTo-Json -Depth 8
} else {
    Write-Host "Project Visibility HOST AUDIT" -ForegroundColor Cyan
    Write-Host "RAM: $totalGB GB total, $freeGB GB free, $memPct% used"
    $ports | Format-Table -AutoSize
    Write-Host 'Agent-related processes:'
    $result.AgentRelevantProcesses | Format-Table -AutoSize
    Write-Host 'Loaded Ollama models:'
    $result.OllamaLoadedModels | Format-Table -AutoSize
    Write-Host 'Read-only report complete.'
}
