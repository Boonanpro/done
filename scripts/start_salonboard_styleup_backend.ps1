param(
    [int]$Port = 8000,
    [string]$HostName = "127.0.0.1",
    [string]$PythonExe = "C:\Program Files\Python310\python.exe",
    [string]$Root = "D:\done"
)

$ErrorActionPreference = "Stop"
Set-Location $Root

$log = Join-Path $Root "sandbox.log"
$err = Join-Path $Root "sandbox.err.log"

$existing = Get-CimInstance Win32_Process -Filter "name='python.exe'" |
    Where-Object { $_.CommandLine -like "*app.sandbox.main:app*" -and $_.CommandLine -like "*--port $Port*" }

foreach ($proc in $existing) {
    Stop-Process -Id $proc.ProcessId -Force
}

Start-Process `
    -FilePath $PythonExe `
    -ArgumentList @("-m", "uvicorn", "app.sandbox.main:app", "--host", $HostName, "--port", "$Port") `
    -WorkingDirectory $Root `
    -RedirectStandardOutput $log `
    -RedirectStandardError $err `
    -WindowStyle Hidden

Start-Sleep -Seconds 4

$healthUrl = "http://${HostName}:${Port}/health"
$health = Invoke-WebRequest -Uri $healthUrl -UseBasicParsing -TimeoutSec 10
"Started Salonboard StyleUp backend on $healthUrl ($($health.StatusCode))"
