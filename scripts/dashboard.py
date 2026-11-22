#!/usr/bin/env python3
"""Launcher for the Stream Clips Uploader Dashboard.

Binds strictly to 127.0.0.1 and launches the local web server.
Automatically bootstraps into the private virtual environment if run from outside.
"""

import os
import subprocess
import sys
import webbrowser
from pathlib import Path

HERE = Path(__file__).resolve().parent
IS_WIN = os.name == "nt"
VENV = Path(os.environ.get("STREAMCLIPS_ENV_HOME", Path.home() / ".streamclips")) / "venv"
VENV_PY = VENV / ("Scripts/python.exe" if IS_WIN else "bin/python")


def in_venv():
    try:
        return Path(sys.prefix).resolve() == VENV.resolve()
    except OSError:
        return False


def main():
    # If not in venv, re-execute using the venv python if present
    if not in_venv() and VENV_PY.exists():
        env = dict(os.environ)
        bin_dir = str(VENV_PY.parent)
        env["PATH"] = bin_dir + os.pathsep + env.get("PATH", "")
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"
        sys.exit(subprocess.call([str(VENV_PY), str(Path(__file__).resolve()), *sys.argv[1:]], env=env))

    # Add scripts to sys.path
    if str(HERE) not in sys.path:
        sys.path.insert(0, str(HERE))

    port = 5050
    if len(sys.argv) > 1 and sys.argv[1].isdigit():
        port = int(sys.argv[1])

    from uploader.server import run_server
    run_server(host="127.0.0.1", port=port)


if __name__ == "__main__":
    main()
