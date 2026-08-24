@echo off
chcp 65001 > nul
title Lumi Runtime Launcher

echo ========================================
echo  Lumi v1.5.0 - Windows Launcher
echo ========================================
echo.
echo [1/3] Checking environment...
python scripts\check_lumi_env.py
if %ERRORLEVEL% NEQ 0 (
    echo Environment check failed.
    pause
    exit /b 1
)
echo [2/3] Opening dashboard...
start "" python scripts\open_lumi_dashboard.py
echo [3/3] Starting Lumi backend...
python run_lumi.py
pause
