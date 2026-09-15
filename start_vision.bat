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

set "LLAMA_SERVER=C:\Users\joyji\.docker\bin\inference\llama-server.exe"
set "MODEL_FILE=C:\Users\joyji\models\Qwen3VL-2B-Instruct-Q4_K_M.gguf"
set "MMPROJ_FILE=C:\Users\joyji\models\mmproj-Qwen3VL-2B-Instruct-F16.gguf"

"%LLAMA_SERVER%" -m "%MODEL_FILE%" --mmproj "%MMPROJ_FILE%" -c 4096 --host 127.0.0.1 --port 8090 -ngl 99
if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Vision server exited with error code %errorlevel%.
    pause
)
