<#
.SYNOPSIS
  Read-only Windows memory audit. Never kills or reprioritizes processes.
.EXAMPLE
  .\tools\inspect-agent-host.ps1
  .\tools\inspect-agent-host.ps1 -Detailed
  .\tools\inspect-agent-host.ps1 -AsJson
#>
param([switch]$AsJson, [switch]$Detailed)
$ErrorActionPreference = 'Stop'
$os = Get-CimInstance Win32_OperatingSystem
$machine = Get-CimInstance Win32_ComputerSystem
$totalGB = [math]::Round([double]$machine.TotalPhysicalMemory / 1GB, 2)
$freeGB = [math]::Round([double]$os.FreePhysicalMemory * 1KB / 1GB, 2)
$usedGB = [math]::Round($totalGB - $freeGB, 2)
$memPct = if ($totalGB -gt 0) { [math]::Round(100 * $usedGB / $totalGB, 1) } else { 0 }

# CommandLine is examined for classification ONLY; never expose browser URLs,
# credentials, profiles, CLI switches, or command lines in logs or JSON.
$processes = @(Get-CimInstance Win32_Process | Where-Object {
    $_.Name -match '(?i)^(pythonw?|ollama|ollama_llama_server|chrome|chromium|chrome-headless-shell|msedge|cloudflared)\.exe$'
} | ForEach-Object {
    $group = switch -Regex ($_.Name) {
        '(?i)^chrome-headless-shell\.exe$' { 'Headless QA candidate'; break }
        '(?i)^(chrome|chromium|msedge)\.exe$' {
            if ($_.CommandLine -match '(?i)(--headless(?:\s|=)|chrome-headless-shell)') {
                'Headless QA candidate'
            } else {
                'Browser (origin not confirmed)'
            }
            break
        }
        '(?i)^pythonw?\.exe$' { 'Python agents'; break }
        '(?i)^cloudflared\.exe$' { 'Cloudflare tunnel'; break }
        default { 'Ollama runtime' }
    }
    [pscustomobject]@{
        Name = $_.Name
        ProcessId = $_.ProcessId
        Category = $group
        WorkingSetMB = [math]::Round([double]$_.WorkingSetSize / 1MB, 1)
        PrivateMB = [math]::Round([double]$_.PrivatePageCount / 1MB, 1)
    }
})
$groups = @($processes | Group-Object Category | ForEach-Object {
    $privateTotal = ($_.Group | Measure-Object -Property PrivateMB -Sum).Sum
    [pscustomobject]@{
        Category = $_.Name
        Processes = $_.Count
        PrivateMB = [math]::Round([double]$privateTotal, 1)
    }
} | Sort-Object PrivateMB -Descending)
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
    ProcessGroups = $groups
    AgentRelevantProcesses = @($processes | Sort-Object PrivateMB -Descending)
    TopWindowsProcesses = $top
    LocalPorts = @($ports)
    OllamaLoadedModels = $ollamaModels
    Recommendations = @(
        'The Chrome process count is not evidence of orphaned Playwright processes.',
        'PrivateMB is private committed memory, not a direct physical RAM usage total.',
        'Do not disable Windows Defender, core services or paging file.',
        'Use one producer lane and one Chromium QA lane until a loaded-model benchmark proves more parallelism is safe.',
        'Set OLLAMA_MAX_LOADED_MODELS for the Ollama SERVER before starting it; changing the API environment does not reconfigure an already running daemon.'
    )
}
if ($AsJson) {
    $result | ConvertTo-Json -Depth 8
} else {
    Write-Host "Project Visibility HOST AUDIT" -ForegroundColor Cyan
    Write-Host "RAM: $totalGB GB total, $freeGB GB free, $memPct% used"
    $ports | Format-Table -AutoSize
    Write-Host 'Agent / browser process categories (PrivateMB = private committed bytes):'
    $groups | Format-Table -AutoSize
    Write-Host 'Largest agent-related processes:'
    $result.AgentRelevantProcesses | Select-Object -First $(if ($Detailed) { 100 } else { 10 }) |
        Format-Table -AutoSize
    Write-Host 'Loaded Ollama models:'
    $result.OllamaLoadedModels | Format-Table -AutoSize
    Write-Host 'This audit did not change the system or close any process.'
}
