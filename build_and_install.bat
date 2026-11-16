@echo off
setlocal
cd /d "%~dp0"
title Shift - build and install
echo.
echo   Shift - build and install
echo   ============================
echo.

where py >nul 2>nul
if %errorlevel%==0 (set "PY=py -3") else (set "PY=python")
%PY% --version >nul 2>nul
if errorlevel 1 (
  echo Python was not found.
  echo Install Python 3.11 or newer from https://www.python.org/downloads/
  echo and tick "Add python.exe to PATH" during installation.
  pause
  exit /b 1
)

echo [1/3] Installing components...
%PY% -m pip install --upgrade pip >nul
%PY% -m pip install -r requirements.txt pyinstaller
if errorlevel 1 goto failed

echo.
echo [2/3] Building the app (this takes a few minutes)...
%PY% -m PyInstaller shift.spec --noconfirm --clean
if errorlevel 1 goto failed

echo.
echo [3/3] Installing...
set "TARGET=%LOCALAPPDATA%\Programs\Shift"
if not exist "%TARGET%" mkdir "%TARGET%"
copy /y "dist\Shift.exe" "%TARGET%\" >nul
if errorlevel 1 goto failed
powershell -NoProfile -ExecutionPolicy Bypass -Command "$s=New-Object -ComObject WScript.Shell; $exe=Join-Path $env:LOCALAPPDATA 'Programs\Shift\Shift.exe'; foreach($m in @([Environment]::GetFolderPath('Desktop'),[Environment]::GetFolderPath('Programs'),[Environment]::GetFolderPath('SendTo'))){ $l=$s.CreateShortcut((Join-Path $m 'Shift.lnk')); $l.TargetPath=$exe; $l.IconLocation=$exe; $l.Save(); foreach($old in 'Bestandsomzetter.lnk','Wissel.lnk'){ Remove-Item (Join-Path $m $old) -ErrorAction SilentlyContinue } }"

echo.
echo   Done! Shift is now available:
echo   - on your desktop
echo   - in the Start menu
echo   - under right-click ^> Send to
echo.
echo   The standalone program is also in the "dist" folder if you want to share it.
pause
exit /b 0

:failed
echo.
echo   Something went wrong. See the message above.
pause
exit /b 1
