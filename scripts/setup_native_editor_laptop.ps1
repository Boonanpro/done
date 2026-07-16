[CmdletBinding()]
param(
    [string]$TargetRoot = 'D:\done',
    [string]$RepositoryUrl = 'https://github.com/Boonanpro/done.git',
    [string]$Branch = 'dan/native-timeline-stability-v2',
    [switch]$SkipFrontend,
    [switch]$SkipBuild
)

$ErrorActionPreference = 'Stop'

function Require-Command([string]$Name) {
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "$Name was not found. Install it on the laptop, then run this script again."
    }
}

Require-Command git
Require-Command npm
Require-Command cargo

if (Test-Path (Join-Path $TargetRoot '.git')) {
    Write-Host "Updating existing repository: $TargetRoot"
    Push-Location $TargetRoot
    try {
        git fetch origin $Branch
        git checkout $Branch
        git pull --ff-only origin $Branch
    } finally { Pop-Location }
} elseif (Test-Path $TargetRoot) {
    throw "$TargetRoot exists but is not a Git repository. Use an empty D:\done directory."
} else {
    $parent = Split-Path -Parent $TargetRoot
    New-Item -ItemType Directory -Force -Path $parent | Out-Null
    git clone --branch $Branch --single-branch $RepositoryUrl $TargetRoot
}

if (-not $SkipFrontend) {
    Write-Host 'Installing frontend dependencies for caption-frame...'
    Push-Location (Join-Path $TargetRoot 'frontend')
    try { npm ci } finally { Pop-Location }
}

if (-not $SkipBuild) {
    Write-Host 'Building the native editor (release)...'
    cargo build --release --manifest-path (Join-Path $TargetRoot 'scripts\poc\production_desktop\native_ui\Cargo.toml')
}

Write-Host ''
Write-Host 'Done. Export the project on the desktop PC, then import it on this laptop.'
