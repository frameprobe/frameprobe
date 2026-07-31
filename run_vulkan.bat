@echo off
setlocal
rem Single-config generators (Ninja, MinGW) put the exe in bin\,
rem the Visual Studio generator in bin\<config>\.
set "BIN=%~dp0color-switcher-vulkan\build\bin\color-switcher.exe"
if not exist "%BIN%" set "BIN=%~dp0color-switcher-vulkan\build\bin\Release\color-switcher.exe"
if not exist "%BIN%" (
    echo color-switcher.exe not found - run build_vulkan.bat first. 1>&2
    exit /b 1
)
start "" "%BIN%" %*
