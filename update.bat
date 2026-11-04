@echo off
rem Kaigo tool updater (double-click to run)
rem Downloads the latest version from GitHub and overwrites the files in this folder.
rem Settings and the Python environment (.venv) are kept.
setlocal
cd /d "%~dp0"
set "URL=https://github.com/yuyatakeuchitopic/kaigotool/archive/refs/heads/claude/kaigo-insurance-automation-h38m9n.zip"
set "ZIP=%TEMP%\kaigotool_update.zip"
set "WORK=%TEMP%\kaigotool_update"
set "EXCL=%TEMP%\kaigotool_update_exclude.txt"

echo Downloading the latest version...
curl -L -f -s -o "%ZIP%" "%URL%"
if errorlevel 1 goto fail

if exist "%WORK%" rmdir /s /q "%WORK%"
mkdir "%WORK%"
tar -xf "%ZIP%" -C "%WORK%"
if errorlevel 1 goto fail

rem Do not overwrite this running script
echo \update.bat> "%EXCL%"
for /d %%D in ("%WORK%\*") do (
    xcopy "%%D\*" "%~dp0" /E /Y /I /Q /EXCLUDE:%EXCL% > nul
    if errorlevel 1 goto fail
)

rmdir /s /q "%WORK%"
del "%ZIP%" "%EXCL%"
echo.
echo Update complete. Start the tool with start.bat.
pause
exit /b 0

:fail
echo.
echo Update failed. Please download the zip from GitHub manually.
pause
exit /b 1
