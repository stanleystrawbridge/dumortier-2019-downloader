@echo off
rem SPDX-License-Identifier: GPL-3.0-only
rem Copyright (C) 2026 Stanley E. Strawbridge
setlocal DisableDelayedExpansion
set "PYTHONUTF8=1"
set "PYTHONNOUSERSITE=1"
set "RESULT=1"
pushd "%~dp0" || goto failed_to_open

if not exist "download_dumortier_2019.py" goto missing_files
if not exist "requirements.txt" goto missing_files
if exist ".venv\Scripts\python.exe" goto check_environment

py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
if not errorlevel 1 goto create_with_py
python -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
if not errorlevel 1 goto create_with_python
python3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
if not errorlevel 1 goto create_with_python3

echo Python 3.10 or newer is required. Install Python, or run this launcher
echo from an Anaconda Prompt with a suitable Python version. See README.md.
goto finish

:create_with_py
echo Creating an isolated Python environment in .venv ...
py -3 -m venv .venv
if errorlevel 1 goto environment_failed
goto check_environment

:create_with_python
echo Creating an isolated Python environment in .venv ...
python -m venv .venv
if errorlevel 1 goto environment_failed
goto check_environment

:create_with_python3
echo Creating an isolated Python environment in .venv ...
python3 -m venv .venv
if errorlevel 1 goto environment_failed

:check_environment
".venv\Scripts\python.exe" -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
if errorlevel 1 goto environment_failed
".venv\Scripts\python.exe" -c "import hashlib, pathlib, requests; p=pathlib.Path('.venv/requirements.sha256'); assert p.read_text().strip() == hashlib.sha256(pathlib.Path('requirements.txt').read_bytes()).hexdigest()" >nul 2>&1
if not errorlevel 1 goto run

echo Installing the downloader dependency into .venv ...
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r requirements.txt
if errorlevel 1 goto install_failed
".venv\Scripts\python.exe" -c "import hashlib, pathlib; pathlib.Path('.venv/requirements.sha256').write_text(hashlib.sha256(pathlib.Path('requirements.txt').read_bytes()).hexdigest())"
if errorlevel 1 goto install_failed

:run
".venv\Scripts\python.exe" download_dumortier_2019.py %*
set "RESULT=%ERRORLEVEL%"
goto finish

:missing_files
echo Extract the full repository ZIP before running this launcher.
goto finish

:environment_failed
echo The local environment could not be created or used. Check write access.
echo For a broken or moved environment, remove only .venv and try again.
echo Do not remove your data. See README.md.
goto finish

:install_failed
echo Dependency installation failed. Check your network and proxy settings.
echo See README.md. No imaging download has started.
goto finish

:finish
popd
if "%~1"=="" pause
exit /b %RESULT%

:failed_to_open
echo Could not open the launcher folder. Extract the repository first.
if "%~1"=="" pause
exit /b 1
