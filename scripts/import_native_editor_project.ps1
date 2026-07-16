[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)] [string]$Bundle,
    [string]$TargetRoot = 'D:\done'
)

$ErrorActionPreference = 'Stop'
$project = Join-Path $Bundle 'project'
$contents = Join-Path $project 'contents.json'
if (-not (Test-Path $contents)) { throw "Not a valid exported project folder: $Bundle" }
$raw = Get-Content $contents -Raw | ConvertFrom-Json
$roomId = [string]$raw.room_id
if (-not $roomId) { throw 'contents.json has no room_id.' }
$dest = Join-Path $TargetRoot "uploads\production-assets\$roomId"
if (Test-Path $dest) { throw "This room_id already exists: $dest (move it aside first)" }
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $dest) | Out-Null
Copy-Item -Recurse -Force $project $dest

$mapPath = Join-Path $Bundle 'path-map.json'
$assetsPath = Join-Path $dest 'assets.json'
if ((Test-Path $mapPath) -and (Test-Path $assetsPath)) {
    $map = Get-Content $mapPath -Raw | ConvertFrom-Json
    $lookup = @{}
    foreach ($row in $map) { $lookup[[string]$row.id] = [string]$row.file }
    $assets = Get-Content $assetsPath -Raw | ConvertFrom-Json
    foreach ($asset in $assets) {
        $rel = $lookup[[string]$asset.id]
        if ($rel) { $asset.local_path = (Join-Path $dest $rel.Replace('/', '\\')) }
    }
    Copy-Item $assetsPath "$assetsPath.before-import.bak"
    $assets | ConvertTo-Json -Depth 30 | Set-Content -Encoding UTF8 $assetsPath
}
Write-Host "Import complete: $dest"
