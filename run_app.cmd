@echo off
setlocal

REM Run Chat-TTS v3 app on Windows
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo [INFO] .venv not found, creating virtual environment...
  py -3 -m venv .venv || goto :error
)

call ".venv\Scripts\activate.bat" || goto :error

python -m pip install --upgrade pip || goto :error
if exist requirements.txt (
  pip install -r requirements.txt || goto :error
)

python main.py
set EXIT_CODE=%ERRORLEVEL%

if not "%EXIT_CODE%"=="0" (
  echo.
  echo [ERROR] Application exited with code %EXIT_CODE%.
  goto :error
)

echo.
echo [OK] Application exited normally.
exit /b 0

:error
echo.
echo [FAILED] Please check output above.
pause
exit /b 1
