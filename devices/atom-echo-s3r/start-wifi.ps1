param([switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$taskTemp = Join-Path $taskRoot '.tmp'
function Test-LocalPort([int]$Port) {
    return [bool](Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
}
if (!(Test-LocalPort 48801)) {
    Start-Process -FilePath 'C:/Program Files/Python310/python.exe' -ArgumentList ('"' + (Join-Path $taskRoot 'devices/atom-echo-s3r/wifi_bridge.py') + '"') -WorkingDirectory $taskRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $taskTemp 'atom-wifi-bridge.out.log') -RedirectStandardError (Join-Path $taskTemp 'atom-wifi-bridge.err.log') | Out-Null
}
if (!(Test-LocalPort 3000)) {
    & 'C:/Program Files/Python310/python.exe' (Join-Path $taskRoot 'scripts/frontend_prod.py') start
    if ($LASTEXITCODE -ne 0) { throw 'Dan frontend could not start.' }
}
if (!(Test-LocalPort 48802)) {
    Start-Process -FilePath 'C:/Program Files/Python310/python.exe' -ArgumentList ('"' + (Join-Path $taskRoot 'devices/atom-echo-s3r/headless_voice.py') + '"') -WorkingDirectory $taskRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $taskTemp 'atom-headless.out.log') -RedirectStandardError (Join-Path $taskTemp 'atom-headless.err.log') | Out-Null
}
Write-Output 'Dan Wi-Fi runs headlessly. First pairing: http://localhost:3000/atom-voice . Status: http://127.0.0.1:48802/status'
