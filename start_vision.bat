@echo off
title Qwen3-VL Vision Server
color 0B
echo.
echo ============================================================
echo   Starting Qwen3-VL Vision Server (llama-server)
echo   Model:  Qwen3VL-2B-Instruct-Q4_K_M.gguf
echo   Port:   8090
echo ============================================================
echo.

set "PROJECT_DIR=%~dp0"
if "%VISION_PORT%"=="" set "VISION_PORT=8090"
if "%VISION_GPU_LAYERS%"=="" set "VISION_GPU_LAYERS=99"

:: Locate llama-server.exe if not already passed in
if defined LLAMA_SERVER goto check_llama
if exist "%PROJECT_DIR%bin\llama-server.exe" (
    set "LLAMA_SERVER=%PROJECT_DIR%bin\llama-server.exe"
) else if exist "%PROJECT_DIR%tools\llama-server.exe" (
    set "LLAMA_SERVER=%PROJECT_DIR%tools\llama-server.exe"
) else if exist "%USERPROFILE%\.docker\bin\inference\llama-server.exe" (
    set "LLAMA_SERVER=%USERPROFILE%\.docker\bin\inference\llama-server.exe"
) else (
    for /f "delims=" %%i in ('where.exe llama-server.exe 2^>nul') do set "LLAMA_SERVER=%%i"
)

:check_llama
if defined LLAMA_SERVER goto find_model
echo [ERROR] llama-server.exe was not found.
echo.
echo Expected one of:
echo   %PROJECT_DIR%bin\llama-server.exe
echo   %PROJECT_DIR%tools\llama-server.exe
echo   %USERPROFILE%\.docker\bin\inference\llama-server.exe
echo   Or available in Windows PATH
echo.
echo Please install llama.cpp (llama-server.exe) and place it in one of these locations.
echo.
pause
exit /b 1

:find_model
set "MODEL_NAME=Qwen3VL-2B-Instruct-Q4_K_M.gguf"
if defined MODEL_FILE goto check_model
if exist "%PROJECT_DIR%models\%MODEL_NAME%" (
    set "MODEL_FILE=%PROJECT_DIR%models\%MODEL_NAME%"
) else if exist "%USERPROFILE%\models\%MODEL_NAME%" (
    set "MODEL_FILE=%USERPROFILE%\models\%MODEL_NAME%"
)

:check_model
if defined MODEL_FILE goto find_mmproj
echo [ERROR] Model file not found: %MODEL_NAME%
echo.
echo Expected one of:
echo   %PROJECT_DIR%models\%MODEL_NAME%
echo   %USERPROFILE%\models\%MODEL_NAME%
echo.
echo Please download the required model and place it in one of these locations.
echo.
pause
exit /b 1

:find_mmproj
set "MMPROJ_NAME=mmproj-Qwen3VL-2B-Instruct-F16.gguf"
if defined MMPROJ_FILE goto check_mmproj
if exist "%PROJECT_DIR%models\%MMPROJ_NAME%" (
    set "MMPROJ_FILE=%PROJECT_DIR%models\%MMPROJ_NAME%"
) else if exist "%USERPROFILE%\models\%MMPROJ_NAME%" (
    set "MMPROJ_FILE=%USERPROFILE%\models\%MMPROJ_NAME%"
)

:check_mmproj
if defined MMPROJ_FILE goto start_server
echo [ERROR] Multi-modal projector file not found: %MMPROJ_NAME%
echo.
echo Expected one of:
echo   %PROJECT_DIR%models\%MMPROJ_NAME%
echo   %USERPROFILE%\models\%MMPROJ_NAME%
echo.
echo Please download the required projector and place it in one of these locations.
echo.
pause
exit /b 1

:start_server
echo [vision] Server:    %LLAMA_SERVER%
echo [vision] Model:     %MODEL_FILE%
echo [vision] Projector: %MMPROJ_FILE%
echo [vision] Port:      %VISION_PORT%
echo.

"%LLAMA_SERVER%" -m "%MODEL_FILE%" --mmproj "%MMPROJ_FILE%" -c 4096 --host 127.0.0.1 --port %VISION_PORT% -ngl %VISION_GPU_LAYERS%
if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Vision server exited with error code %errorlevel%.
    pause
)
