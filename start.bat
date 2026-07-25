@echo off
chcp 65001 >nul
title AT Whisper Master Launcher
color 0B

:: Switch to the batch file's own directory
cd /d "%~dp0"

echo =======================================================
echo 🍅 STARTING SYSTEMS IN BACKGROUND MODE (Minimized)
echo =======================================================
echo.

:: 1. Start the local proxy server, minimized
echo [1/2] Starting Local Proxy (libs\Start1.py)...
start /min "AI Proxy Server" cmd /k "python "%~dp0libs\Start1.py""

:: Pause to let the proxy initialize
timeout /t 3 /nobreak >nul

:: 2. Start Whisper, minimized (UPDATED: now launches main.py)
echo [2/2] Starting Whisper (main.py)...
start /min "Whisper Main" cmd /k "python "%~dp0main.py""

echo.
echo ✅ All processes started in minimized windows.
echo Wait for the browser tab to open...
timeout /t 5 >nul