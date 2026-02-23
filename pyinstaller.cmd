@echo off
setlocal

REM Build one-folder executable with PyInstaller
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo [INFO] .venv not found, creating virtual environment...
  py -3 -m venv .venv || goto :error
)

call ".venv\Scripts\activate.bat" || goto :error

python -m pip install --upgrade pip || goto :error
pip install -r requirements.txt || goto :error
pip install pyinstaller || goto :error

REM Clean previous build output
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist main_v3.spec del /f /q main_v3.spec

pyinstaller ^
  --noconfirm ^
  --clean ^
  --name chat-tts ^
  --windowed ^
  --onedir ^
  --add-data "app;app" ^
  main_v3.py || goto :error

echo.
echo [OK] Build complete. Output: dist\chat-tts\chat-tts.exe
exit /b 0

:error
echo.
echo [FAILED] Build failed. Please check output above.
pause
exit /b 1
