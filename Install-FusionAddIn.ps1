[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$FusionAddInsRoot,
    [switch]$Clean
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$addinName = "FusionHeatInsertAddIn"
$sourceRoot = (Resolve-Path -LiteralPath $PSScriptRoot).Path

if ([string]::IsNullOrWhiteSpace($FusionAddInsRoot)) {
    if ([string]::IsNullOrWhiteSpace($env:APPDATA)) {
        throw "APPDATA is not available. Pass -FusionAddInsRoot explicitly."
    }

    $FusionAddInsRoot = Join-Path $env:APPDATA "Autodesk\Autodesk Fusion 360\API\AddIns"
}

$FusionAddInsRoot = [Environment]::ExpandEnvironmentVariables($FusionAddInsRoot)
$targetRoot = Join-Path $FusionAddInsRoot $addinName

if ([string]::Equals($sourceRoot, $targetRoot, [StringComparison]::OrdinalIgnoreCase)) {
    throw "The source repository and Fusion add-in directory must be different."
}

$runtimeFiles = @(
    "FusionHeatInsertAddIn.manifest",
    "FusionHeatInsertAddIn.py",
    "connection_data.py",
    "hardware_library.py",
    "hardware_library.json"
)

$repoOnlyPaths = @(
    ".gitignore",
    "README.md",
    "hardware_library_editor.html",
    "hardware_library_editor_server.py",
    "hardware_library_editor_server.ps1",
    "Open Hardware Library Editor.cmd",
    "tests",
    "__pycache__"
)

foreach ($relativePath in $runtimeFiles) {
    $sourcePath = Join-Path $sourceRoot $relativePath
    if (-not (Test-Path -LiteralPath $sourcePath -PathType Leaf)) {
        throw "Required runtime file is missing: $sourcePath"
    }
}

if ($PSCmdlet.ShouldProcess($targetRoot, "Create Fusion add-in directory")) {
    New-Item -ItemType Directory -Path $targetRoot -Force | Out-Null
}

foreach ($relativePath in $runtimeFiles) {
    $sourcePath = Join-Path $sourceRoot $relativePath
    $targetPath = Join-Path $targetRoot $relativePath
    if ($PSCmdlet.ShouldProcess($targetPath, "Copy $relativePath")) {
        Copy-Item -LiteralPath $sourcePath -Destination $targetPath -Force
    }
}

if ($Clean) {
    foreach ($relativePath in $repoOnlyPaths) {
        $stalePath = Join-Path $targetRoot $relativePath
        if (Test-Path -LiteralPath $stalePath) {
            if ($PSCmdlet.ShouldProcess($stalePath, "Remove repository-only content")) {
                Remove-Item -LiteralPath $stalePath -Recurse -Force
            }
        }
    }
}

Write-Host "Installed $addinName to $targetRoot"
Write-Host "Source repository: $sourceRoot"
if ($Clean) {
    Write-Host "Repository-only files were removed from the Fusion add-in directory."
}
