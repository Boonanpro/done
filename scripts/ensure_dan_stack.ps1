# DanStackWatchdog — single-shot health check + restart for the local Dan stack.
#
# Task Scheduler fires this every minute. For each service:
#   1. Probe its liveness.
#   2. If down, kick the existing start script (everything is reused — no
#      special restart logic lives here).
#
# Services watched:
#   - Frontend       Next.js PROD build on 0.0.0.0:3000    -> start_frontend.bat (+ preview dev 3001)
#   - Dan Core       FastAPI on 127.0.0.1:9000             -> dan_core_autostart.bat
#   - Sandbox        FastAPI on 127.0.0.1:8000             -> core POST /api/v1/sandbox/restart
#                                                            (falls back to dan_core_autostart.bat if core is also down)
#   - Cloudflared    named Dan connector + legacy quick tunnels during migration
#
# Replaces the older ensure_frontend_3000.ps1 (which only handled frontend).

$ErrorActionPreference = 'Stop'

$Root = 'D:\done'
$Log  = Join-Path $Root 'dan-watchdog.log'
$Python = 'C:\Program Files\Python310\python.exe'

function Write-WatchdogLog([string]$Message) {
    $stamp = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
    Add-Content -Path $Log -Value "[$stamp] $Message"
}

function Test-Responding([string]$Url) {
    # Treat any HTTP 2xx-4xx as "responding" — 401/404 etc still mean a
    # process answered, which is all we want to know.
    # 2026-09-11: core は DB 待ちで数秒応答が遅れることがある。6 秒で「落ちた」と
    # 誤判定して二重起動を仕掛けていたので、上限を 20 秒にし、失敗時は 5 秒おいて
    # もう一度だけ確かめてから down と判定する。
    foreach ($attempt in 1..2) {
        try {
            $r = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 20 -ErrorAction Stop
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

# 1) Frontend ------------------------------------------------------------
if (-not (Test-Responding 'http://127.0.0.1:3000')) {
    Write-WatchdogLog 'frontend (3000, production build) down -> start_frontend.bat'
    Start-Process -FilePath 'cmd.exe' -ArgumentList '/c', "$Root\scripts\start_frontend.bat" -WindowStyle Hidden
} elseif (-not (Test-Responding 'http://127.0.0.1:3001')) {
    # 成果物プレビュー用の開発サーバー(HMR)。ダッシュボード(3000)とは別プロセス。
    Write-WatchdogLog 'preview dev server (3001) down -> start_preview_dev.bat'
    Start-Process -FilePath 'cmd.exe' -ArgumentList '/c', "$Root\scripts\start_preview_dev.bat" -WindowStyle Hidden
}

# 2) Dan Core / Sandbox --------------------------------------------------
$coreUp    = Test-Responding 'http://127.0.0.1:9000/health'
$sandboxUp = Test-Responding 'http://127.0.0.1:8000/health'

if (-not $coreUp) {
    # Core gone takes the sandbox with it; the autostart script brings both back.
    Write-WatchdogLog 'core (9000) down -> dan_core_autostart.bat'
    Start-Process -FilePath 'cmd.exe' -ArgumentList '/c', "$Root\scripts\dan_core_autostart.bat" -WindowStyle Hidden
} elseif (-not $sandboxUp) {
    # Core is alive — let it respawn the sandbox via its SandboxManager.
    Write-WatchdogLog 'sandbox (8000) down (core up) -> POST /api/v1/sandbox/restart'
    try {
        Invoke-WebRequest -Uri 'http://127.0.0.1:9000/api/v1/sandbox/restart' -Method POST -UseBasicParsing -TimeoutSec 15 -ErrorAction Stop | Out-Null
    } catch {
        Write-WatchdogLog "sandbox restart API failed: $($_.Exception.Message)"
    }
}

# 3) Cloudflare tunnels --------------------------------------------------
$cf = @(Get-CimInstance Win32_Process -Filter "Name='cloudflared.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -and $_.CommandLine -match '--url\s+"?http://127\.0\.0\.1:(9000|8000)(?:"|\s|$)' })
if ($cf.Count -lt 2) {
    Write-WatchdogLog "cloudflared count=$($cf.Count) (expected 2) -> relaunch start_tunnel.py"
    # Clear any half-dead start_tunnel.py supervisor so we don't end up with two.
    try {
        Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" -ErrorAction SilentlyContinue |
            Where-Object { $_.CommandLine -and ($_.CommandLine -match 'start_tunnel\.py') } |
            ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    } catch {}
    Start-Sleep -Seconds 2
    Start-Process -FilePath 'cmd.exe' `
        -ArgumentList '/c', "cd /d $Root && `"$Python`" scripts\start_tunnel.py > $Root\tunnel.log 2>&1" `
        -WindowStyle Hidden
}

# The fixed connector is independent of the two legacy quick tunnels. Its
# launcher is idempotent and cloudflared reconnects itself on network changes.
try {
    & "$Root\scripts\start_named_tunnel.ps1" | ForEach-Object { Write-WatchdogLog $_ }
} catch {
    Write-WatchdogLog "named tunnel start failed: $($_.Exception.Message)"
}
