[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)] [string]$RoomId,
    [Parameter(Mandatory = $true)] [string]$Destination,
    [string]$SourceRoot = 'D:\done'
)

$ErrorActionPreference = 'Stop'
$room = Join-Path $SourceRoot "uploads\production-assets\$RoomId"
if (-not (Test-Path (Join-Path $room 'contents.json'))) { throw "contents.json was not found: $room" }

$bundle = Join-Path $Destination "native-editor-project-$RoomId"
if (Test-Path $bundle) { throw "Bundle already exists: $bundle (choose another destination)" }
New-Item -ItemType Directory -Force -Path $bundle | Out-Null
Copy-Item -Recurse -Force $room (Join-Path $bundle 'project')

$assetsPath = Join-Path $room 'assets.json'
$assets = if (Test-Path $assetsPath) { Get-Content $assetsPath -Raw | ConvertFrom-Json } else { @() }
$mediaDir = Join-Path $bundle 'external-media'
New-Item -ItemType Directory -Force -Path $mediaDir | Out-Null
$map = @()
foreach ($asset in $assets) {
    $src = [string]$asset.local_path
    if ($src -and (Test-Path -LiteralPath $src)) {
        $safeName = ([string]$asset.id) + '__' + (Split-Path $src -Leaf)
        Copy-Item -LiteralPath $src -Destination (Join-Path $mediaDir $safeName)
        $map += [pscustomobject]@{ id = [string]$asset.id; file = "external-media/$safeName" }
    }
}
$map | ConvertTo-Json | Set-Content -Encoding UTF8 (Join-Path $bundle 'path-map.json')
Write-Host "Export complete: $bundle"
