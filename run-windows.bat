@echo off
setlocal

set "REPO_ROOT=%~dp0"
set "VSWHERE=%ProgramFiles(x86)%\Microsoft Visual Studio\Installer\vswhere.exe"

if not exist "%VSWHERE%" goto missing_cpp_tools

for /f "usebackq tokens=*" %%I in (`"%VSWHERE%" -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath`) do set "VSINSTALL=%%I"
if not defined VSINSTALL goto missing_cpp_tools

set "VSDEVCMD=%VSINSTALL%\Common7\Tools\VsDevCmd.bat"
if not exist "%VSDEVCMD%" goto missing_cpp_tools
call "%VSDEVCMD%" -arch=x64 -host_arch=x64
if errorlevel 1 goto setup_failed

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%REPO_ROOT%scripts\run-windows.ps1"
set "EXIT_CODE=%ERRORLEVEL%"
if not "%EXIT_CODE%"=="0" pause
exit /b %EXIT_CODE%

:missing_cpp_tools
echo Microsoft Visual Studio C++ Build Tools were not found.
echo Install Visual Studio 2022 Build Tools with the "Desktop development with C++" workload, then run this file again.
echo https://visualstudio.microsoft.com/visual-cpp-build-tools/
pause
exit /b 1

:setup_failed
echo Could not initialize the Visual Studio C++ build environment.
pause
exit /b 1
