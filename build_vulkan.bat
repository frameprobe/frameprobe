@echo off
setlocal
pushd "%~dp0"

if not exist color-switcher-vulkan\build mkdir color-switcher-vulkan\build
cd color-switcher-vulkan\build
cmake .. || goto :fail
cmake --build . --config Release || goto :fail

popd
exit /b 0

:fail
popd
exit /b 1
