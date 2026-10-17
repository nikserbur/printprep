@echo off
setlocal
cd /d "%~dp0"
echo Print Prep - Windows x64 build
rem PyInstaller wipes dist\PrintPrep first: a running copy would be left half-deleted.
tasklist /FI "IMAGENAME eq PrintPrep.exe" 2>nul | find /I "PrintPrep.exe" >nul
if not errorlevel 1 goto :app_running
rem Check actual interpreter output: launcher messages alone do not prove Python ran.
set "PRINTPREP_PYTHON_OK="
for /f "delims=" %%V in ('py -3.12 -c "import sys; print(31264 if sys.version_info[:2] == (3, 12) and sys.maxsize > 2**32 else 0)" 2^>nul') do if "%%V"=="31264" set "PRINTPREP_PYTHON_OK=1"
if not defined PRINTPREP_PYTHON_OK goto :missing_python
if not exist .venv-build\Scripts\python.exe (
  py -3.12 -m venv .venv-build
  if errorlevel 1 goto :fail
)
if not exist .venv-build\Scripts\python.exe goto :missing_venv
.venv-build\Scripts\python.exe -c "import sys; assert sys.version_info[:2] == (3, 12) and sys.maxsize > 2**32"
if errorlevel 1 goto :missing_venv
.venv-build\Scripts\python.exe -m pip install -r requirements-dev.txt
if errorlevel 1 goto :fail
set QT_QPA_PLATFORM=offscreen
.venv-build\Scripts\python.exe -m pytest -q
if errorlevel 1 goto :fail
.venv-build\Scripts\python.exe -m PyInstaller --noconfirm --clean printprep.spec
if errorlevel 1 goto :fail
powershell -NoProfile -Command "$p = Start-Process -FilePath 'dist\PrintPrep\PrintPrep.exe' -ArgumentList '--self-test' -Wait -PassThru; exit $p.ExitCode"
if errorlevel 1 goto :fail
set QT_QPA_PLATFORM=
copy /y README.txt dist\README.txt >nul
copy /y README_EN.txt dist\README_EN.txt >nul
copy /y THIRD_PARTY.md dist\THIRD_PARTY.md >nul
.venv-build\Scripts\python.exe tools\package_release.py
if errorlevel 1 goto :fail
.venv-build\Scripts\python.exe -m PyInstaller --noconfirm --clean --distpath dist --workpath build\installer installer\setup.spec
if errorlevel 1 goto :fail
.venv-build\Scripts\python.exe tools\check_installer.py
if errorlevel 1 goto :fail
echo.
echo SUCCESS: dist\PrintPrep-Setup.exe ^(installer for colleagues^) and dist\PrintPrep-Windows-x64.zip
if not defined CI pause
exit /b 0
:app_running
echo.
echo Print Prep is running. Close it and start the build again.
if not defined CI pause
exit /b 1
:missing_python
echo.
echo Python 3.12 x64 is required on the BUILD computer.
echo Git and the Python launcher do not include the Python runtime.
echo.
echo Open PowerShell and run:
echo   py install 3.12
echo If your launcher does not support install, use the Python 3.12 x64
echo installer from https://www.python.org/downloads/windows/
echo Then close this window and run build_exe.bat again.
echo Colleagues running the finished PrintPrep.exe do NOT need Python.
goto :fail
:missing_venv
echo The build environment is missing or incompatible.
echo Rename .venv-build to .venv-build-old, then run this script again.
goto :fail
:fail
echo BUILD FAILED. Read the error above. No verified release was produced.
if not defined CI pause
exit /b 1
