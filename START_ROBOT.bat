@echo off
title Webots Autonomous Robot Launcher
color 0A

echo.
echo  ================================================
echo   AUTONOMOUS ROBOT LAUNCHER
echo   Webots + Qwen3-VL + Nemotron-120B
echo  ================================================
echo.

:: ============================================================
::  CONFIGURATION  --  Edit these if anything moves
:: ============================================================

set "WEBOTS_EXE=C:\Program Files\Webots\msys64\mingw64\bin\webotsw.exe"
set "WORLD_FILE=c:\Users\joyji\OneDrive\my_project\worlds\Test.wbt"

set "LLAMA_SERVER=C:\Users\joyji\.docker\bin\inference\llama-server.exe"
set "MODEL_FILE=C:\Users\joyji\models\Qwen3VL-2B-Instruct-Q4_K_M.gguf"
set "MMPROJ_FILE=C:\Users\joyji\models\mmproj-Qwen3VL-2B-Instruct-F16.gguf"
set "VISION_PORT=8090"
set "VISION_GPU_LAYERS=99"

set "AI_BRIDGE_DIR=c:\Users\joyji\OneDrive\my_project\ai_bridge"

:: ============================================================
::  STEP 1 — Validate all required files before doing anything
:: ============================================================

echo [check] Verifying files...

if not exist "%WEBOTS_EXE%"   goto err_webots
if not exist "%WORLD_FILE%"   goto err_world
if not exist "%LLAMA_SERVER%" goto err_llama
if not exist "%MODEL_FILE%"   goto err_model
if not exist "%MMPROJ_FILE%"  goto err_mmproj
if not exist "%AI_BRIDGE_DIR%\orchestrator.py" goto err_orchestrator

echo [check] All files found. OK.
echo.
goto step2

:err_webots
echo [ERROR] Webots not found:      %WEBOTS_EXE%
echo         Edit WEBOTS_EXE in this script.
goto bail

:err_world
echo [ERROR] World file not found:  %WORLD_FILE%
echo         Edit WORLD_FILE in this script.
goto bail

:err_llama
echo [ERROR] llama-server not found: %LLAMA_SERVER%
echo         Edit LLAMA_SERVER in this script.
goto bail

:err_model
echo [ERROR] Model not found:       %MODEL_FILE%
echo         Edit MODEL_FILE in this script.
goto bail

:err_mmproj
echo [ERROR] mmproj not found:      %MMPROJ_FILE%
echo         Edit MMPROJ_FILE in this script.
goto bail

:err_orchestrator
echo [ERROR] orchestrator.py not found in: %AI_BRIDGE_DIR%
goto bail

:bail
echo.
pause
exit /b 1

:: ============================================================
::  STEP 2 — Kill any stale llama-server from a previous run
:: ============================================================

:step2
echo [cleanup] Stopping any leftover llama-server processes...
taskkill /F /IM llama-server.exe /T >nul 2>&1
timeout /t 1 /nobreak >nul

:: ============================================================
::  STEP 3 — Start Qwen3-VL vision server in its own window
:: ============================================================

echo [1/3] Starting Qwen3-VL vision server on port %VISION_PORT%...

start "Qwen3-VL Vision Server" "%~dp0start_vision.bat"

:: Give the process a moment to spawn before we start polling
timeout /t 3 /nobreak >nul

:: ============================================================
::  STEP 4 — Start Webots with the world file
:: ============================================================

echo [2/3] Starting Webots with: %WORLD_FILE%
start "Webots Simulation" "%WEBOTS_EXE%" "%WORLD_FILE%"

:: ============================================================
::  STEP 5 — Wait for vision server to be ready (HTTP /health)
:: ============================================================

echo.
echo [wait] Waiting for Qwen3-VL server to finish loading...
echo        (Usually 15-40 seconds on first load)
echo.

:wait_vision
timeout /t 4 /nobreak >nul
curl.exe -s --max-time 2 http://127.0.0.1:%VISION_PORT%/health >nul 2>&1
if %errorlevel% neq 0 (
    echo [wait]   Vision server not ready yet... retrying
    goto wait_vision
)
echo [wait] Vision server is READY.

:: ============================================================
::  STEP 6 — Wait for Webots TCP socket (port 10101)
:: ============================================================

echo.
echo [wait] Waiting for Webots TCP socket on port 10101...
echo        *** If Webots has loaded, press PLAY (triangle) now! ***
echo.

:wait_webots
timeout /t 4 /nobreak >nul
powershell -NoProfile -NonInteractive -Command "$c=New-Object Net.Sockets.TcpClient; try{$c.Connect('127.0.0.1',10101);$c.Close();exit 0}catch{exit 1}" >nul 2>&1
if %errorlevel% neq 0 (
    echo [wait]   Webots socket not open yet. Press PLAY in Webots if you haven't!
    goto wait_webots
)
echo [wait] Webots is READY.

:: ============================================================
::  STEP 7 — Mission loop  (Webots + vision stay running;
::            only the agent restarts between missions)
:: ============================================================

:mission_loop

echo.
echo  ================================================
echo   All systems ready!
echo.
echo   Webots and the vision server are running.
echo   You can start as many missions as you like.
echo   Just press Ctrl+C in the agent window to end
echo   the current mission, then type a new one here.
echo  ================================================
echo.
echo   Examples:
echo     Explore the environment autonomously.
echo     Find a red object and investigate it.
echo     Map the room by moving along the walls.
echo     Look for anything interesting and describe it.
echo     Navigate to the far end of the room.
echo.
set "MISSION="
set /p "MISSION=  Enter mission (or press Enter to quit): "

:: Blank input = user wants to exit
if "%MISSION%"=="" goto shutdown

echo.
echo [mission] Starting: "%MISSION%"
echo.

:: Run the agent directly in THIS window so Ctrl+C is caught here.
:: When the user presses Ctrl+C the agent stops cleanly,
:: then we loop back and ask for the next mission.
cd /d "%AI_BRIDGE_DIR%"
python orchestrator.py "%MISSION%"

echo.
echo [mission] Agent stopped.
goto mission_loop

:shutdown
echo.
echo  Exiting launcher. Webots and vision server are still running.
echo  Run STOP_ROBOT.bat to shut everything down.
echo.
pause
exit /b 0
