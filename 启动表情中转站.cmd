@echo off
chcp 65001 >nul
cd /d "%~dp0"
python run_emoji_bridge.py
if errorlevel 1 pause
