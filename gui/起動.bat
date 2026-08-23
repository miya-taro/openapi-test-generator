@echo off
cd /d "%~dp0"
python app.py
if errorlevel 1 (
    echo.
    echo アプリの起動に失敗しました。上記のエラー内容を確認してください。
    pause
)
