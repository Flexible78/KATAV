@echo off
chcp 65001 >nul
title KATAV Launcher
color 0B

:: Switch to the batch file's own directory
cd /d "%~dp0"

:: Overwrite PID log on every launch
> .katav_pids echo.

echo =======================================================
echo STARTING SYSTEMS IN BACKGROUND MODE (Minimized)
echo =======================================================
echo.

:: 1. Start the local proxy server, minimized
echo [1/2] Starting KATAV AI Proxy...
start /min "KATAV AI Proxy" cmd /k ""%~dp0.venv\Scripts\python.exe" "%~dp0libs\Start1.py""
powershell -NoProfile -Command "for ($i=0; $i -lt 10; $i++) { $p = Get-Process | Where-Object {$_.MainWindowTitle -like 'KATAV AI Proxy*'} | Select-Object -First 1; if ($p) { $p.Id | Out-File -Append '.katav_pids'; break } Start-Sleep -Milliseconds 300 }"

:: Pause to let the proxy initialize
timeout /t 3 /nobreak >nul

:: 2. Start the main app, minimized
echo [2/2] Starting KATAV Main...
start /min "KATAV Main" cmd /k ""%~dp0.venv\Scripts\python.exe" "%~dp0main.py""
powershell -NoProfile -Command "for ($i=0; $i -lt 10; $i++) { $p = Get-Process | Where-Object {$_.MainWindowTitle -like 'KATAV Main*'} | Select-Object -First 1; if ($p) { $p.Id | Out-File -Append '.katav_pids'; break } Start-Sleep -Milliseconds 300 }"

echo.
echo All processes started in minimized windows.
echo Wait for the browser tab to open...
timeout /t 5 >nul