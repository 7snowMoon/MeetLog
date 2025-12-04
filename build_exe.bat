@echo off
cd /d "%~dp0"
title MeetLog - EXE Builder
echo ========================================
echo   MeetLog EXE Builder
echo ========================================
echo.

REM Activate virtual environment if exists
if exist "venv\Scripts\activate.bat" (
    call venv\Scripts\activate.bat
)

REM Install PyInstaller if not installed
pip show pyinstaller >nul 2>&1
if %errorlevel% neq 0 (
    echo Installing PyInstaller...
    pip install pyinstaller
)

echo Building EXE file...
echo.

pyinstaller --name MeetLog --onefile --windowed --noconfirm --clean --icon=icon.ico --add-data "icon.ico;." --add-data "ja.json;." --add-data "en.json;." MeetLog.py

echo.
if exist "dist\MeetLog.exe" (
    echo ========================================
    echo   Build Success!
    echo ========================================
    echo.
    echo Output: dist\MeetLog.exe
    echo.
    
    REM Copy required files to dist
    copy /Y MANUAL.md dist\MANUAL.md >nul 2>&1
    if not exist "dist\recordings" mkdir "dist\recordings"
    
    echo.
    echo Distribution folder:
    echo   dist\
    echo     MeetLog.exe   - Main application
    echo     MANUAL.md     - User guide
    echo     recordings\   - Recording folder
    echo.
    echo Compress dist folder to ZIP for distribution.
) else (
    echo Build failed.
)
echo.
pause
