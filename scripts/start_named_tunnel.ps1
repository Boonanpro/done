# Start the fixed Dan connector without touching the user's desktop or legacy tunnels.
$ErrorActionPreference = 'Stop'
$Root = Split-Path $PSScriptRoot -Parent
$TokenFile = Join-Path $env:USERPROFILE '.cloudflared\dan-paina.token'
if (-not (Test-Path -LiteralPath $TokenFile)) { exit 0 }
$Mutex = [System.Threading.Mutex]::new($false, 'Local\DanNamedTunnelStart')
$Acquired = $false
try {
    try { $Acquired = $Mutex.WaitOne(0) } catch [System.Threading.AbandonedMutexException] { $Acquired = $true }
    if (-not $Acquired) { exit 0 }
    $Existing = @(Get-CimInstance Win32_Process -Filter "Name='cloudflared.exe'" |
        Where-Object { $_.CommandLine -and $_.CommandLine.Contains('dan-paina.token') -and $_.CommandLine.Contains('--token-file') })
    if ($Existing.Count -gt 0) { exit 0 }
    $Exe = Join-Path $env:LOCALAPPDATA 'Microsoft\WinGet\Packages\Cloudflare.cloudflared_Microsoft.Winget.Source_8wekyb3d8bbwe\cloudflared.exe'
    $LogDir = Join-Path $Root 'logs'
    New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
    $Stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    $Process = Start-Process -FilePath $Exe -ArgumentList @(
        'tunnel', '--no-autoupdate', '--protocol', 'http2', '--metrics', '127.0.0.1:20246',
        'run', '--token-file', ('"' + $TokenFile + '"')
    ) -WorkingDirectory $Root -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $LogDir "named-tunnel-$Stamp.out.log") `
        -RedirectStandardError (Join-Path $LogDir "named-tunnel-$Stamp.err.log")
    Write-Output "Named Dan connector started: PID $($Process.Id)"
} finally {
    if ($Acquired) { $Mutex.ReleaseMutex() }
    $Mutex.Dispose()
}
