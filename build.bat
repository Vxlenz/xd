@echo off
setlocal
cd /d "%~dp0"

rem Requires a 64-bit Python 3.11+ installation on Windows.
if not exist ".venv-build\Scripts\python.exe" (
    python -m venv .venv-build
    if errorlevel 1 goto :failed
)
set "NOVADECK_PYTHON=%~dp0.venv-build\Scripts\python.exe"
"%NOVADECK_PYTHON%" -c "import sys, struct; sys.exit(0 if sys.platform == 'win32' and sys.version_info >= (3, 11) and struct.calcsize('P') == 8 else 1)"
if errorlevel 1 goto :failed
"%NOVADECK_PYTHON%" -m pip install -r requirements-build.txt
if errorlevel 1 goto :failed
"%NOVADECK_PYTHON%" -m pip check
if errorlevel 1 goto :failed
"%NOVADECK_PYTHON%" -m pytest -q
if errorlevel 1 goto :failed
"%NOVADECK_PYTHON%" -m PyInstaller --clean --noconfirm tools\novadeck.spec
if errorlevel 1 goto :failed
"%NOVADECK_PYTHON%" tools\check_build.py dist\NovaDeck\NovaDeck.exe
if errorlevel 1 goto :failed
copy /y README.md dist\NovaDeck\README.md >nul
if errorlevel 1 goto :failed
copy /y profiles.example.json dist\NovaDeck\profiles.example.json >nul
if errorlevel 1 goto :failed
echo NovaDeck is ready in dist\NovaDeck. Distribute the complete folder.
exit /b 0

:failed
echo NovaDeck build failed. Review the command output above.
exit /b 1
