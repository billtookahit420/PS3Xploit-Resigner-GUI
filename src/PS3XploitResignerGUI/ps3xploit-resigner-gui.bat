@echo off
rem Launch PS3Xploit Resigner GUI on Windows. On first run,
rem create the bundled virtual environment and install the
rem app's deps. NOTE: this package is code-verified only --
rem the build fleet is Linux-only and the Windows path has
rem not been executed; see README.md.
cd /d "%~dp0"
if "%PS3RESIGN_GUI_DATA_DIR%"=="" set "PS3RESIGN_GUI_DATA_DIR=%LOCALAPPDATA%\PS3XploitResignerGUI"
if not exist .venv\Scripts\python.exe (
    echo First run: setting up the Python environment...
    python -m venv .venv || (
        echo Could not create the environment. Install Python 3.10+
        echo from python.org, tick "Add python.exe to PATH", retry.
        exit /b 1
    )
)
.venv\Scripts\python.exe -c "import PySide6" 2>nul
if errorlevel 1 (
    echo Installing Python dependencies...
    .venv\Scripts\python.exe -m pip install -r requirements.txt || (
        echo Dependency install failed - check connection, re-run.
        exit /b 1
    )
)
.venv\Scripts\python.exe app\main.py %*
