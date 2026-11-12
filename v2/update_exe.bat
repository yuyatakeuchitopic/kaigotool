@echo off
rem Kaigo tool v2 (exe version) updater. Double-click to run.
rem Downloads the latest release and overwrites the files in this folder.
rem Settings and the Edge login are kept (they are stored in %LOCALAPPDATA%\kaigotool).
setlocal
cd /d "%~dp0"
set "URL=https://github.com/yuyatakeuchitopic/kaigotool/releases/latest/download/kaigotool-v2-windows.zip"
set "ZIP=%TEMP%\kaigotool_v2_update.zip"
set "WORK=%TEMP%\kaigotool_v2_update"
set "EXCL=%TEMP%\kaigotool_v2_update_exclude.txt"

tasklist /FI "IMAGENAME eq kaigotool.exe" | find /I "kaigotool.exe" > nul
if not errorlevel 1 (
    echo kaigotool.exe is running. Please close the tool and run this again.
    pause
    exit /b 1
)

echo Downloading the latest version...
curl -L -f -s -o "%ZIP%" "%URL%"
if errorlevel 1 goto fail

if exist "%WORK%" rmdir /s /q "%WORK%"
mkdir "%WORK%"
tar -xf "%ZIP%" -C "%WORK%"
if errorlevel 1 goto fail
if not exist "%WORK%\kaigotool\kaigotool.exe" goto fail

rem Do not overwrite this running script
echo \update.bat> "%EXCL%"
xcopy "%WORK%\kaigotool\*" "%~dp0." /E /Y /I /Q /EXCLUDE:%EXCL% > nul
if errorlevel 1 goto fail

rmdir /s /q "%WORK%"
del "%ZIP%" "%EXCL%"
echo.
echo Update complete. Start kaigotool.exe.
pause
exit /b 0

:fail
echo.
echo Update failed. Please download kaigotool-v2-windows.zip from the GitHub Releases page manually.
pause
exit /b 1
