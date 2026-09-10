@echo off
REM Botu kendi penceresinde baslatir. Cift tiklayarak da acabilirsin.
REM Durdurmak icin bu pencerede Ctrl+C, ya da pencereyi kapat.

cd /d "%~dp0"
title Paper Trade Bot - runner

echo ================================================
echo   Paper Trade Bot
echo   Klasor: %CD%
echo   Durdurmak icin: Ctrl+C
echo ================================================
echo.

python runner.py

echo.
echo Bot durdu. Pencereyi kapatmak icin bir tusa bas.
pause >nul
