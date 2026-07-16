[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)] [string]$RoomId,
    [string]$Root = 'D:\done'
)

$ErrorActionPreference = 'Stop'
$contents = Join-Path $Root "uploads\production-assets\$RoomId\contents.json"
$assets = Split-Path -Parent $contents
$exe = Join-Path $Root 'scripts\poc\production_desktop\native_ui\target\release\native_ui.exe'
if (-not (Test-Path $contents)) { throw "Project was not found: $contents" }
if (-not (Test-Path $exe)) { throw "Native editor is not built. Run setup_native_editor_laptop.ps1 first." }

# Designed captions are rendered by the local caption-frame page. Start it only when
# no process is already listening, so repeated launches do not create dev-server piles.
if (-not (Get-NetTCPConnection -LocalPort 3000 -State Listen -ErrorAction SilentlyContinue)) {
    $frontend = Join-Path $Root 'frontend'
    Start-Process -FilePath 'npm.cmd' -ArgumentList 'run','dev','--','--hostname','127.0.0.1','--port','3000' `
        -WorkingDirectory $frontend -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $Root 'frontend-dev-3000.log') `
        -RedirectStandardError (Join-Path $Root 'frontend-dev-3000.err.log')
}
Start-Process -FilePath $exe -ArgumentList $contents,$assets -WorkingDirectory $Root
