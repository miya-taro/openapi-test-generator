@echo off
rem exe化（PyInstaller）を行う。生成物は dist\openapi-test-tool\ 以下。
rem 事前に `pip install pyinstaller` が必要（requirements.txtには含めていない。
rem 実行時ではなくビルド時にしか要らないツールのため）。
cd /d "%~dp0.."
python -m PyInstaller gui\openapi-test-tool.spec --noconfirm
if errorlevel 1 (
    echo.
    echo ビルドに失敗しました。上記のエラー内容を確認してください。
    pause
    exit /b 1
)
echo.
echo 完成: dist\openapi-test-tool\openapi-test-tool.exe
pause
