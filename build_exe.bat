@echo off
setlocal
cd /d "%~dp0"
echo Print Prep - Windows x64 build
py -3.12 --version >nul 2>&1
if errorlevel 1 (
  echo Install Python 3.12 x64 from python.org with the Python launcher.
  goto :fail
)
if not exist .venv-build\Scripts\python.exe (
  py -3.12 -m venv .venv-build
  if errorlevel 1 goto :fail
)
.venv-build\Scripts\python.exe -m pip install -r requirements-dev.txt
if errorlevel 1 goto :fail
set QT_QPA_PLATFORM=offscreen
.venv-build\Scripts\python.exe -m pytest -q
if errorlevel 1 goto :fail
.venv-build\Scripts\python.exe -m PyInstaller --noconfirm --clean --onefile --windowed --name PrintPrep --version-file assets\windows_version.txt --icon assets\printprep.ico --add-data "assets;assets" --collect-all PIL --exclude-module PySide6.QtWebEngineCore --exclude-module PySide6.QtWebEngineWidgets print_prep.py
if errorlevel 1 goto :fail
powershell -NoProfile -Command "$p = Start-Process -FilePath 'dist\PrintPrep.exe' -ArgumentList '--self-test' -Wait -PassThru; exit $p.ExitCode"
if errorlevel 1 goto :fail
set QT_QPA_PLATFORM=
copy /y README.txt dist\README.txt >nul
copy /y THIRD_PARTY.md dist\THIRD_PARTY.md >nul
.venv-build\Scripts\python.exe tools\package_release.py
if errorlevel 1 goto :fail
echo.
echo SUCCESS: dist\PrintPrep-Windows-x64.zip
if not defined CI pause
exit /b 0
:fail
echo BUILD FAILED. Read the error above. No verified release was produced.
if not defined CI pause
exit /b 1
