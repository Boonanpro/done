# ダンの本体が Mac にある時、voice.paina.info（Mac の cloudflared が 127.0.0.1:48763 へ渡す）を
# この PC の音声入力サーバー（127.0.0.1:48763）へつなぐ。PC から Mac への外向きの ssh なので、
# Windows のファイアウォールの確認は出ない。ensure_dan_stack.ps1 が、この PC が控えの時に呼ぶ。
$ErrorActionPreference = 'Stop'
$Existing = @(Get-CimInstance Win32_Process -Filter "Name='ssh.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -and $_.CommandLine.Contains('48763:127.0.0.1:48763') })
if ($Existing.Count -gt 0) { exit 0 }
$Mac = if ($env:DAN_MAC_HOST) { $env:DAN_MAC_HOST } else { 'mikihonda@192.168.40.172' }
$Known = Join-Path $env:USERPROFILE '.ssh\mac_mini_known_hosts'
# Git の ssh を使う（Windows 標準の ssh は鍵ファイルの権限が広いと鍵を読まない）。
Start-Process -FilePath 'C:\Program Files\Git\usr\bin\ssh.exe' -WindowStyle Hidden -ArgumentList @(
    '-N', '-o', 'BatchMode=yes', '-o', 'ExitOnForwardFailure=yes', '-o', 'ServerAliveInterval=30',
    '-o', 'ServerAliveCountMax=3', '-o', "UserKnownHostsFile=$Known",
    '-R', '127.0.0.1:48763:127.0.0.1:48763',
    # Mac のダンの desktop 道具 -> この PC の控えのダン（app/core/api/desktop_relay_routes.py）
    '-R', '127.0.0.1:19000:127.0.0.1:9000', $Mac)
Write-Output 'voice relay to Mac started'
