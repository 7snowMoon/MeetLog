@echo off
cd /d "%~dp0"
title MeetLog - Meeting Recorder

REM 仮想環境があれば有効化
if exist "venv\Scripts\activate.bat" (
    call venv\Scripts\activate.bat
)

REM MeetLogを起動
python MeetLog.py

REM エラー時のみ一時停止
if %errorlevel% neq 0 (
    echo.
    echo エラーが発生しました。
    pause
)
