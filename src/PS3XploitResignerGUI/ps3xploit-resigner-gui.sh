#!/bin/sh
# Launch PS3Xploit Resigner GUI. On first run (fresh
# download), create the bundled virtual environment and
# install the app's Python deps. The Resigner engine itself
# is carried ready-built in this package and is unpacked
# (hash-checked) into the per-user data folder by the app
# on first run.
cd "$(dirname "$0")" || exit 1
if [ -z "$PS3RESIGN_GUI_DATA_DIR" ]; then
    PS3RESIGN_GUI_DATA_DIR="$HOME/.local/share/ps3xploit-resigner-gui"
    export PS3RESIGN_GUI_DATA_DIR
fi
if [ ! -x .venv/bin/python ]; then
    echo "First run: setting up the Python environment..."
    python3 -m venv .venv || {
        echo "Could not create the environment. On Debian/Ubuntu run:"
        echo "  sudo apt install -y python3-venv"
        echo "then run ./ps3xploit-resigner-gui.sh again."
        exit 1
    }
fi
if ! .venv/bin/python -c "import PySide6" 2>/dev/null; then
    echo "Installing Python dependencies..."
    .venv/bin/pip install -r requirements.txt || {
        echo "Dependency install failed - check your connection and re-run."
        exit 1
    }
fi
exec .venv/bin/python app/main.py "$@"
