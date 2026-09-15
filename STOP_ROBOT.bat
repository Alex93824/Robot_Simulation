@echo off
title Stop Robot
color 0C

echo.
echo  ================================================
echo   STOPPING AUTONOMOUS ROBOT SYSTEM
echo  ================================================
echo.

echo [stop] Killing llama-server (Qwen3-VL)...
taskkill /F /IM llama-server.exe /T >nul 2>&1
echo        Done.

echo [stop] Sending stop signal to orchestrator (python)...
:: This only kills python processes running orchestrator.py
:: If you have other python processes you want to keep, close
:: the "Nemotron Autonomous Agent" window manually instead.
taskkill /F /FI "WINDOWTITLE eq Nemotron Autonomous Agent" /T >nul 2>&1
echo        Done.

echo [stop] Closing Webots...
taskkill /F /IM webotsw.exe /T >nul 2>&1
taskkill /F /IM webots.exe  /T >nul 2>&1
echo        Done.

echo.
echo  All systems stopped.
echo.
pause
exit /b 0
