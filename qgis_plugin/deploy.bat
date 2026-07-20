@echo off
REM QGIS Plugin Deployment Script (Batch version)
REM Deploys the image_mate_qgis_plugin to the QGIS plugins folder

setlocal

echo === QGIS Plugin Deployment ===
echo.

REM Source directory (the plugin to deploy)
set SOURCE_DIR=%~dp0image_mate_qgis_plugin

REM Target directory (QGIS plugins folder)
set TARGET_BASE=%APPDATA%\QGIS\QGIS3\profiles\default\python\plugins
set TARGET_DIR=%TARGET_BASE%\image_mate_qgis_plugin

echo Source: %SOURCE_DIR%
echo Target: %TARGET_DIR%
echo.

REM Check if source directory exists
if not exist "%SOURCE_DIR%" (
    echo ERROR: Source directory not found: %SOURCE_DIR%
    pause
    exit /b 1
)

REM Clean up __pycache__ directories from source
echo Cleaning source __pycache__ directories...
for /d /r "%SOURCE_DIR%" %%d in (__pycache__) do @if exist "%%d" rmdir /s /q "%%d" 2>nul
del /s /q "%SOURCE_DIR%\*.pyc" 2>nul
del /s /q "%SOURCE_DIR%\*.pyo" 2>nul
echo   Cleaned cache files

REM Create target base directory if it doesn't exist
if not exist "%TARGET_BASE%" (
    echo WARNING: QGIS plugins directory not found
    echo Creating directory: %TARGET_BASE%
    mkdir "%TARGET_BASE%"
)

REM Remove existing plugin installation if it exists
if exist "%TARGET_DIR%" (
    echo Removing existing plugin installation...
    rmdir /s /q "%TARGET_DIR%" 2>nul
    if exist "%TARGET_DIR%" (
        echo   Retrying removal...
        timeout /t 1 /nobreak >nul
        rmdir /s /q "%TARGET_DIR%" 2>nul
    )
    if exist "%TARGET_DIR%" (
        echo   ERROR: Could not remove existing plugin
        echo   Please close QGIS and try again
        pause
        exit /b 1
    )
    echo   Removed successfully
)

REM Copy plugin to QGIS plugins directory
echo Copying plugin files...
xcopy /E /I /Y /Q "%SOURCE_DIR%" "%TARGET_DIR%" /EXCLUDE:"%SOURCE_DIR%\__pycache__" > nul
if errorlevel 1 (
    echo   ERROR: Failed to copy plugin files
    pause
    exit /b 1
)
echo   Copied successfully

REM Verify deployment
echo Verifying deployment...
if not exist "%TARGET_DIR%\__init__.py" echo   WARNING: Missing __init__.py
if not exist "%TARGET_DIR%\plugin.py" echo   WARNING: Missing plugin.py
if not exist "%TARGET_DIR%\metadata.txt" echo   WARNING: Missing metadata.txt
if exist "%TARGET_DIR%\plugin.py" echo   All key files present

echo.
echo === Deployment Complete ===
echo Timestamp: %date% %time%
echo.
echo Next steps:
echo 1. If QGIS is running, restart it to load the updated plugin
echo 2. Or use Plugin Manager ^> 'Reload plugin: image_mate_qgis_plugin' if you have Plugin Reloader installed
echo 3. Enable the plugin in: Plugins ^> Manage and Install Plugins
echo.
pause
