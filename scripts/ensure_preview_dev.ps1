# Health check + recovery for the artifact preview dev server (Next.js dev, HMR, port 3001).
#
# Called every minute by ensure_dan_stack.ps1; every line written to output goes to dan-watchdog.log.
#
# Why this is not a plain "does the port answer" check (2026-09-24 .. 2026-10-05, 11 days broken):
#   - The server answered 500 on every page (globals.css failed to parse; the dev server keeps the broken
#     class names for as long as it runs). The watchdog saw "down" and launched a second copy each minute,
#     which died with EADDRINUSE because the broken one still held the port (6,138 attempts).
#   - Another app can listen on the same port (a Docker container published 3001). With the dev server
#     gone, that app answered 404 and the watchdog saw "up", so nothing was ever started.
# So: decide "running" from our own process, decide "healthy" from HTTP, and when it stays unhealthy,
# stop the old process tree and clear its build cache before starting again.
#
# Keep this file ASCII-only: it has no BOM, and Windows PowerShell 5.1 would read other bytes as ANSI.

param(
    [string]$Root = 'D:\done',
    [int]$Port = 3001,
    [string]$ProbeUrl = '',
    [string]$DistDir = '.next-preview',
    [string]$StartScript = '',
    [string]$StateFile = '',
    # Consecutive failed checks (one per minute) before a restart. A page can answer 500 for a while
    # when someone is mid-edit on a shared file; restarting would not help and would drop their HMR session.
    [int]$FailThreshold = 5,
    # After a restart, do not restart again for this long. A fault that survives a clean restart
    # is not one a restart fixes.
    [int]$CooldownMinutes = 30
)

$ErrorActionPreference = 'Stop'

if (-not $ProbeUrl)    { $ProbeUrl = "http://127.0.0.1:$Port" }
if (-not $StartScript) { $StartScript = Join-Path $Root 'scripts\start_preview_dev.bat' }
if (-not $StateFile)   { $StateFile = Join-Path $Root '.tmp\preview_dev_watchdog.json' }

function Test-Responding([string]$Url) {
    # 2xx-4xx = a healthy process answered. 5xx or no answer = not healthy.
    # One retry after 5 seconds, as in ensure_dan_stack.ps1.
    foreach ($attempt in 1..2) {
        try {
            Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 20 -ErrorAction Stop | Out-Null
            return $true
        } catch {
            $sc = $null
            try { $sc = $_.Exception.Response.StatusCode.value__ } catch {}
            if ($sc -ne $null -and $sc -ge 200 -and $sc -lt 500) { return $true }
            if ($attempt -eq 1) { Start-Sleep -Seconds 5 }
        }
    }
    return $false
}

function Get-PreviewDevProcesses {
    # The launch chain of start_preview_dev.bat: cmd -> npm (node) -> cmd -> next dev (node).
    # The listening child (start-server.js) carries no port in its command line; it goes down with the tree.
    $pattern = '(run\s+dev|next"?\s+dev)\b.*--port\s+' + $Port + '(\D|$)'
    return @(Get-CimInstance Win32_Process -Filter "Name='node.exe' OR Name='cmd.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -and $_.CommandLine -match $pattern })
}

function Start-PreviewDev {
    Start-Process -FilePath 'cmd.exe' -ArgumentList '/c', "`"$StartScript`"" -WindowStyle Hidden
}

$state = @{ fails = 0; lastRestart = '' }
if (Test-Path -LiteralPath $StateFile) {
    try {
        $saved = Get-Content -LiteralPath $StateFile -Raw | ConvertFrom-Json
        $state.fails = [int]$saved.fails
        $state.lastRestart = [string]$saved.lastRestart
    } catch {}
}
function Save-State {
    ($state | ConvertTo-Json -Compress) | Set-Content -LiteralPath $StateFile -Encoding ascii
}

$procs = Get-PreviewDevProcesses
$nextDev = @($procs | Where-Object { $_.Name -eq 'node.exe' -and $_.CommandLine -match 'next"?\s+dev\b' })

# 1) Our process is not there. Start it, whatever else may be answering on the port.
if ($nextDev.Count -eq 0) {
    "preview dev server ($Port) not running -> $(Split-Path -Leaf $StartScript)"
    Start-PreviewDev
    if ($state.fails -ne 0) { $state.fails = 0; Save-State }
    return
}

# 2) Running and healthy.
if (Test-Responding $ProbeUrl) {
    if ($state.fails -ne 0) {
        "preview dev server ($Port) healthy again after $($state.fails) failed check(s)"
        $state.fails = 0
        Save-State
    }
    return
}

# 3) Running but not healthy. Count; restart only once it has stayed that way.
$state.fails = $state.fails + 1
Save-State
if ($state.fails -lt $FailThreshold) {
    "preview dev server ($Port) unhealthy ($($state.fails)/$FailThreshold)"
    return
}

if ($state.lastRestart) {
    $since = $null
    try { $since = (Get-Date) - [datetime]::Parse($state.lastRestart) } catch {}
    if ($since -ne $null -and $since.TotalMinutes -lt $CooldownMinutes) {
        # One line when the cooldown starts to bite, then one every 30 checks.
        if ($state.fails -eq $FailThreshold -or ($state.fails % 30) -eq 0) {
            "preview dev server ($Port) still unhealthy $([int]$since.TotalMinutes) min after a restart -> not restarting again (needs a look; see frontend-dev-$Port.log)"
        }
        return
    }
}

"preview dev server ($Port) unhealthy for $($state.fails) checks -> stop, clear $DistDir, start"

$ids = @($procs | ForEach-Object { $_.ProcessId })
$tops = @($procs | Where-Object { $ids -notcontains $_.ParentProcessId })
foreach ($top in $tops) {
    & cmd.exe /c "taskkill /PID $($top.ProcessId) /T /F >nul 2>&1"
}
foreach ($i in 1..20) {
    if ((Get-PreviewDevProcesses).Count -eq 0) { break }
    Start-Sleep -Milliseconds 500
}

# The cache is what a restart alone may not cure. Rename it out of frontend/ (instant on the same
# drive) and delete it in the background; it was 12 GB, and deleting inline would stall the watchdog.
$dist = Join-Path $Root "frontend\$DistDir"
if (Test-Path -LiteralPath $dist) {
    $trash = Join-Path $Root ('.tmp\next-preview-trash-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
    try {
        Move-Item -LiteralPath $dist -Destination $trash
        Start-Process -FilePath 'cmd.exe' -ArgumentList '/c', "rd /s /q `"$trash`"" -WindowStyle Hidden
    } catch {
        "preview dev server ($Port): could not clear $DistDir ($($_.Exception.Message)) -> starting with the old cache"
    }
}

Start-PreviewDev
$state.fails = 0
$state.lastRestart = (Get-Date).ToString('s')
Save-State
