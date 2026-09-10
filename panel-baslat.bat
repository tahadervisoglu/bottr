@echo off
REM Paneli kendi penceresinde baslatir ve tarayicida acar.
REM Sadece 127.0.0.1 dinler, yerel agdan erisilemez.

cd /d "%~dp0"
title Paper Trade Bot - panel

echo ================================================
echo   Panel baslatiliyor
echo   Adres: http://localhost:8511
echo   Durdurmak icin: Ctrl+C
echo ================================================
echo.

start "" http://localhost:8511
streamlit run app.py

echo.
echo Panel durdu. Pencereyi kapatmak icin bir tusa bas.
pause >nul
