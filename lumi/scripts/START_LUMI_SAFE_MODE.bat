@echo off
chcp 65001 > nul
title Lumi Runtime - Safe Mode
set LUMI_SAFE_MODE=1
python run_lumi.py
pause
