@echo off
setlocal
cd /d "%~dp0"

set PYTHONHOME=

if not exist ".venv\Scripts\python.exe" (
    echo Virtual environment not found.
    echo Create .venv and install requirements first.
    exit /b 1
)

".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean ZKBioSyncService.spec
if errorlevel 1 exit /b %errorlevel%

copy /Y ".env.example" "dist\.env.example" >nul
echo.
echo Build complete:
echo %CD%\dist\ZKBioSyncService.exe
endlocal
