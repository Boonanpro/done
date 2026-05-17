$ErrorActionPreference = "Stop"

$Root = "D:\done"
$Frontend = Join-Path $Root "frontend"
$Log = Join-Path $Root "frontend-watchdog.log"
$OutLog = Join-Path $Root "frontend-dev-3000.log"
$ErrLog = Join-Path $Root "frontend-dev-3000.err.log"
$Url = "http://127.0.0.1:3000"

function Write-WatchdogLog {
    param([string]$Message)
    $stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content -Path $Log -Value "[$stamp] $Message"
}

function Test-Frontend {
    try {
        $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 8
        return ($response.StatusCode -ge 200 -and $response.StatusCode -lt 500)
    } catch {
        return $false
    }
}

function Start-Frontend {
    $lock = Join-Path $Frontend ".next\dev\lock"
    if (Test-Path $lock) {
        Remove-Item -LiteralPath $lock -Force -ErrorAction SilentlyContinue
    }

    Start-Process `
        -FilePath "C:\Program Files\nodejs\npm.cmd" `
        -ArgumentList @("run", "dev", "--", "--hostname", "0.0.0.0", "--port", "3000") `
        -WorkingDirectory $Frontend `
        -RedirectStandardOutput $OutLog `
        -RedirectStandardError $ErrLog `
        -WindowStyle Hidden | Out-Null
}

if (Test-Frontend) {
    exit 0
}

$listeners = @(Get-NetTCPConnection -LocalPort 3000 -State Listen -ErrorAction SilentlyContinue)
if ($listeners.Count -gt 0) {
    $owners = @($listeners | Select-Object -ExpandProperty OwningProcess -Unique)
    Write-WatchdogLog "Port 3000 is listening but HTTP check failed; restarting owning process(es): $($owners -join ', ')"
    foreach ($owner in $owners) {
        try {
            Stop-Process -Id $owner -Force -ErrorAction Stop
        } catch {
            Write-WatchdogLog "Failed to stop process ${owner}: $($_.Exception.Message)"
        }
    }
    Start-Sleep -Seconds 2
} else {
    Write-WatchdogLog "Port 3000 is not listening; starting frontend."
}

Start-Frontend
Start-Sleep -Seconds 5

if (Test-Frontend) {
    Write-WatchdogLog "Frontend is healthy on 0.0.0.0:3000."
    exit 0
}

Write-WatchdogLog "Frontend restart attempted, but health check still failed."
exit 1
