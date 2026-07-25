@echo off
chcp 65001 >nul
title Local AI Proxy Server
color 0A

echo ==========================================
echo 🍅 Starting the local proxy (Start1.py)
echo ==========================================
echo.

:: Run the script from the libs folder
python libs\Start1.py

:: If the script crashes, the window will not close immediately so you can see the error
echo.
pause