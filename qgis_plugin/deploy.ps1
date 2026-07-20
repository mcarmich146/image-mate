# QGIS Plugin Deployment Script
# Deploys the image_mate_qgis_plugin to the QGIS plugins folder

$ErrorActionPreference = "Stop"

# Source directory (the plugin to deploy)
$sourceDir = Join-Path $PSScriptRoot "image_mate_qgis_plugin"

# Target directory (QGIS plugins folder)
# Default QGIS3 profile location on Windows
$targetBase = Join-Path $env:APPDATA "QGIS\QGIS3\profiles\default\python\plugins"
$targetDir = Join-Path $targetBase "image_mate_qgis_plugin"

Write-Host "=== QGIS Plugin Deployment ===" -ForegroundColor Cyan
Write-Host "Source: $sourceDir" -ForegroundColor Yellow
Write-Host "Target: $targetDir" -ForegroundColor Yellow
Write-Host ""

# Check if source directory exists
if (-not (Test-Path $sourceDir)) {
    Write-Host "ERROR: Source directory not found: $sourceDir" -ForegroundColor Red
    exit 1
}

# Clean up __pycache__ directories and .pyc files from source
Write-Host "Cleaning source __pycache__ directories..." -ForegroundColor Yellow
$cleanedCount = 0
Get-ChildItem -Path $sourceDir -Recurse -Force -Include "__pycache__","*.pyc","*.pyo" | ForEach-Object {
    Remove-Item $_.FullName -Recurse -Force -ErrorAction SilentlyContinue
    $cleanedCount++
}
if ($cleanedCount -gt 0) {
    Write-Host "  Removed $cleanedCount cache files/directories" -ForegroundColor Gray
}

# Check if QGIS plugins directory exists
if (-not (Test-Path $targetBase)) {
    Write-Host "WARNING: QGIS plugins directory not found: $targetBase" -ForegroundColor Yellow
    Write-Host "Creating directory..." -ForegroundColor Yellow
    New-Item -ItemType Directory -Path $targetBase -Force | Out-Null
}

# Remove existing plugin installation if it exists
if (Test-Path $targetDir) {
    Write-Host "Removing existing plugin installation..." -ForegroundColor Yellow
    $retries = 3
    $removed = $false
    for ($i = 0; $i -lt $retries; $i++) {
        try {
            Remove-Item -Path $targetDir -Recurse -Force -ErrorAction Stop
            $removed = $true
            Write-Host "  Removed successfully" -ForegroundColor Gray
            break
        } catch {
            if ($i -lt ($retries - 1)) {
                Write-Host "  Retry $($i+1)/$($retries-1): File locked, waiting..." -ForegroundColor Yellow
                Start-Sleep -Milliseconds 500
            } else {
                Write-Host "  ERROR: Could not remove directory after $retries attempts" -ForegroundColor Red
                Write-Host "  Please close QGIS and try again, or manually delete: $targetDir" -ForegroundColor Red
                exit 1
            }
        }
    }
}

# Copy plugin to QGIS plugins directory (excluding cache files)
Write-Host "Copying plugin files..." -ForegroundColor Green
try {
    Copy-Item -Path $sourceDir -Destination $targetDir -Recurse -Force -Exclude "__pycache__","*.pyc","*.pyo"
    Write-Host "  Copied successfully" -ForegroundColor Gray
} catch {
    Write-Host "  ERROR: Failed to copy plugin files: $_" -ForegroundColor Red
    exit 1
}

# Verify deployment
Write-Host "Verifying deployment..." -ForegroundColor Yellow
$keyFiles = @("__init__.py", "plugin.py", "metadata.txt")
$missingFiles = @()
foreach ($file in $keyFiles) {
    if (-not (Test-Path (Join-Path $targetDir $file))) {
        $missingFiles += $file
    }
}
if ($missingFiles.Count -gt 0) {
    Write-Host "  WARNING: Missing files: $($missingFiles -join ', ')" -ForegroundColor Yellow
} else {
    Write-Host "  All key files present" -ForegroundColor Gray
}

# Count deployed files
$fileCount = (Get-ChildItem -Path $targetDir -Recurse -Filter "*.py" | Measure-Object).Count
Write-Host "  Deployed $fileCount Python files" -ForegroundColor Gray

Write-Host ""
Write-Host "=== Deployment Complete ===" -ForegroundColor Green
Write-Host "Timestamp: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" -ForegroundColor Gray
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Cyan
Write-Host "1. If QGIS is running, restart it to load the updated plugin" -ForegroundColor White
Write-Host "2. Or use Plugin Manager > 'Reload plugin: image_mate_qgis_plugin' if you have Plugin Reloader installed" -ForegroundColor White
Write-Host "3. Enable the plugin in: Plugins > Manage and Install Plugins" -ForegroundColor White
Write-Host ""
