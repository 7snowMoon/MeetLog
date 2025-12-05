@echo off
cd /d "%~dp0"
title MeetLog - EXE Builder
echo ========================================
echo   MeetLog EXE Builder
echo ========================================
echo.

REM Use MeetLog's venv explicitly
set VENV_PYTHON=venv\Scripts\python.exe
set VENV_PIP=venv\Scripts\pip.exe
set VENV_PYINSTALLER=venv\Scripts\pyinstaller.exe

REM Check if venv exists
if not exist "%VENV_PYTHON%" (
    echo ERROR: venv not found. Please create venv first.
    pause
    exit /b 1
)

REM Install PyInstaller if not installed
%VENV_PIP% show pyinstaller >nul 2>&1
if %errorlevel% neq 0 (
    echo Installing PyInstaller...
    %VENV_PIP% install pyinstaller
)

echo Building EXE file...
echo Using Python: %VENV_PYTHON%
echo.

REM Use --onedir for better compatibility with google-generativeai
%VENV_PYINSTALLER% --name MeetLog --onedir --windowed --noconfirm --clean --icon=icon.ico ^
    --additional-hooks-dir=. ^
    --add-data "icon.ico;." --add-data "ja.json;." --add-data "en.json;." ^
    --collect-submodules google ^
    --collect-all google.generativeai ^
    --collect-all google.ai.generativelanguage ^
    --collect-all google.api_core ^
    --collect-all google.auth ^
    --collect-all google.protobuf ^
    --collect-all grpc ^
    --collect-all certifi ^
    --collect-all httpx ^
    --hidden-import=google.generativeai ^
    --hidden-import=google.generativeai.types ^
    --hidden-import=google.generativeai.client ^
    --hidden-import=google.ai.generativelanguage ^
    --hidden-import=google.ai.generativelanguage_v1 ^
    --hidden-import=google.ai.generativelanguage_v1beta ^
    --hidden-import=google.api_core ^
    --hidden-import=google.api_core.exceptions ^
    --hidden-import=google.api_core.gapic_v1 ^
    --hidden-import=google.auth ^
    --hidden-import=google.auth.transport.requests ^
    --hidden-import=google.protobuf ^
    --hidden-import=grpc ^
    --hidden-import=httpx ^
    --hidden-import=httpcore ^
    --hidden-import=certifi ^
    --hidden-import=proto ^
    --hidden-import=proto.marshal ^
    MeetLog.py

echo.
if exist "dist\MeetLog\MeetLog.exe" (
    echo ========================================
    echo   Build Success!
    echo ========================================
    echo.
    echo Output: dist\MeetLog\MeetLog.exe
    echo.
    
    REM Copy required files to dist\MeetLog
    copy /Y MANUAL.md dist\MeetLog\MANUAL.md >nul 2>&1
    if not exist "dist\MeetLog\recordings" mkdir "dist\MeetLog\recordings"
    
    echo.
    echo Distribution folder:
    echo   dist\MeetLog\
    echo     MeetLog.exe   - Main application
    echo     MANUAL.md     - User guide
    echo     recordings\   - Recording folder
    echo.
    echo Compress dist\MeetLog folder to ZIP for distribution.
) else (
    echo Build failed.
)
echo.
pause
