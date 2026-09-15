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
::  STEP 1 — Dynamic Path & Environment Detection
:: ============================================================

set "PROJECT_DIR=%~dp0"
set "WORLD_FILE=%PROJECT_DIR%worlds\Test.wbt"
set "AI_BRIDGE_DIR=%PROJECT_DIR%ai_bridge"
set "VISION_PORT=8090"
set "VISION_GPU_LAYERS=99"

set "MODEL_NAME=Qwen3VL-2B-Instruct-Q4_K_M.gguf"
set "MMPROJ_NAME=mmproj-Qwen3VL-2B-Instruct-F16.gguf"

echo [check] Verifying files and environment...

:: 1. Detect Webots
set "WEBOTS_EXE="
if exist "%ProgramFiles%\Webots\msys64\mingw64\bin\webotsw.exe" (
    set "WEBOTS_EXE=%ProgramFiles%\Webots\msys64\mingw64\bin\webotsw.exe"
) else if exist "%SystemDrive%\Program Files\Webots\msys64\mingw64\bin\webotsw.exe" (
    set "WEBOTS_EXE=%SystemDrive%\Program Files\Webots\msys64\mingw64\bin\webotsw.exe"
) else if exist "%LOCALAPPDATA%\Programs\Webots\msys64\mingw64\bin\webotsw.exe" (
    set "WEBOTS_EXE=%LOCALAPPDATA%\Programs\Webots\msys64\mingw64\bin\webotsw.exe"
) else (
    for /f "delims=" %%i in ('where.exe webotsw.exe 2^>nul') do set "WEBOTS_EXE=%%i"
    if not defined WEBOTS_EXE (
        for /f "delims=" %%i in ('where.exe webots.exe 2^>nul') do set "WEBOTS_EXE=%%i"
    )
)

if defined WEBOTS_EXE goto webots_ok
echo [ERROR] Webots was not found.
echo Please install Webots or add it to PATH.
echo Expected standard location:
echo   %ProgramFiles%\Webots\msys64\mingw64\bin\webotsw.exe
goto bail

:webots_ok

:: 2. Detect World File
if exist "%WORLD_FILE%" goto world_ok
echo [ERROR] World file not found: %WORLD_FILE%
goto bail

:world_ok

:: 3. Detect llama-server.exe
set "LLAMA_SERVER="
if exist "%PROJECT_DIR%bin\llama-server.exe" (
    set "LLAMA_SERVER=%PROJECT_DIR%bin\llama-server.exe"
) else if exist "%PROJECT_DIR%tools\llama-server.exe" (
    set "LLAMA_SERVER=%PROJECT_DIR%tools\llama-server.exe"
) else if exist "%USERPROFILE%\.docker\bin\inference\llama-server.exe" (
    set "LLAMA_SERVER=%USERPROFILE%\.docker\bin\inference\llama-server.exe"
) else (
    for /f "delims=" %%i in ('where.exe llama-server.exe 2^>nul') do set "LLAMA_SERVER=%%i"
)

if defined LLAMA_SERVER goto llama_ok
echo [ERROR] llama-server.exe was not found.
echo.
echo Expected one of:
echo   %PROJECT_DIR%bin\llama-server.exe
echo   %PROJECT_DIR%tools\llama-server.exe
echo   %USERPROFILE%\.docker\bin\inference\llama-server.exe
echo   Or available in Windows PATH
echo.
echo Please install llama.cpp (llama-server.exe) and place it in one of these locations.
goto bail

:llama_ok

:: 4. Detect Model file
set "MODEL_FILE="
if exist "%PROJECT_DIR%models\%MODEL_NAME%" (
    set "MODEL_FILE=%PROJECT_DIR%models\%MODEL_NAME%"
) else if exist "%USERPROFILE%\models\%MODEL_NAME%" (
    set "MODEL_FILE=%USERPROFILE%\models\%MODEL_NAME%"
)

if defined MODEL_FILE goto model_ok
echo [ERROR] Model file not found: %MODEL_NAME%
echo.
echo Expected one of:
echo   %PROJECT_DIR%models\%MODEL_NAME%
echo   %USERPROFILE%\models\%MODEL_NAME%
echo.
echo Please download the required model and place it in one of these locations.
goto bail

:model_ok

:: 5. Detect Multi-modal projector file
set "MMPROJ_FILE="
if exist "%PROJECT_DIR%models\%MMPROJ_NAME%" (
    set "MMPROJ_FILE=%PROJECT_DIR%models\%MMPROJ_NAME%"
) else if exist "%USERPROFILE%\models\%MMPROJ_NAME%" (
    set "MMPROJ_FILE=%USERPROFILE%\models\%MMPROJ_NAME%"
)

if defined MMPROJ_FILE goto mmproj_ok
echo [ERROR] Multi-modal projector file not found: %MMPROJ_NAME%
echo.
echo Expected one of:
echo   %PROJECT_DIR%models\%MMPROJ_NAME%
echo   %USERPROFILE%\models\%MMPROJ_NAME%
echo.
echo Please download the required projector and place it in one of these locations.
goto bail

:mmproj_ok

:: 6. Check Orchestrator script
if exist "%AI_BRIDGE_DIR%\orchestrator.py" goto orchestrator_ok
echo [ERROR] orchestrator.py not found in: %AI_BRIDGE_DIR%
goto bail

:orchestrator_ok

:: 7. Check Environment (.env) file
if exist "%AI_BRIDGE_DIR%\.env" goto env_ok
echo [ERROR] Environment file not found: %AI_BRIDGE_DIR%\.env
echo.
echo Please create it from the example template:
echo   copy "%AI_BRIDGE_DIR%\.env.example" "%AI_BRIDGE_DIR%\.env"
echo.
echo Then edit "%AI_BRIDGE_DIR%\.env" and set your NVIDIA_API_KEY.
goto bail

:env_ok

:: 8. Detect Python runtime (prefer local .venv if present)
set "PYTHON_CMD=python"
if exist "%PROJECT_DIR%.venv\Scripts\python.exe" (
    set "PYTHON_CMD=%PROJECT_DIR%.venv\Scripts\python.exe"
)

echo [check] All required files and dependencies detected. OK.
echo.
goto step2

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

start "Qwen3-VL Vision Server" "%PROJECT_DIR%start_vision.bat"

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
"%PYTHON_CMD%" orchestrator.py "%MISSION%"

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
