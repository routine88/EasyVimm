#!/usr/bin/env python3
"""EasyVimm cross-platform launcher.

Works on Windows, macOS, and Linux: just run `python3 EasyVimm.py`.
Creates the virtual environment, installs requirements, runs self-update,
and starts the app.

Use this if the OS-specific launcher (`EasyVimm.bat` / `EasyVimm.command`)
can't run — e.g. macOS stripped the executable bit from a ZIP download.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parent
    os.chdir(root)

    _banner()

    if not _verify_python():
        _pause()
        return 1

    venv_py = _ensure_venv(root)
    if not venv_py:
        _pause()
        return 1

    if not _install_requirements(root, venv_py):
        _pause()
        return 1

    _self_update(venv_py)

    print()
    print("[*] Starting EasyVimm... a browser window will open in a moment.")
    print("    Keep this window open while you download games.")
    print("    Close this window (or press Ctrl+C) when you are done.")
    print()

    try:
        subprocess.run([str(venv_py), str(root / "app.py")])
    except KeyboardInterrupt:
        pass
    return 0


def _banner() -> None:
    print()
    print("  ============================================")
    print("    EasyVimm - Vimm's Lair ROM Downloader")
    print("  ============================================")
    print()


def _verify_python() -> bool:
    exe = sys.executable or ""
    # Windows Store placeholder sits under \WindowsApps\PythonSoftwareFoundation...
    # and when launched directly, it opens the Store instead of running.
    if "WindowsApps" in exe and sys.platform == "win32":
        print("[X] This is the Windows Store 'python.exe' placeholder, not real Python.")
        print()
        print("    Please install real Python 3.10+ from:")
        print("        https://www.python.org/downloads/")
        print()
        print("    IMPORTANT: during install, check the box that says")
        print('        "Add python.exe to PATH"')
        print()
        print("    After installing, run EasyVimm again.")
        return False
    if sys.version_info < (3, 10):
        print(f"[X] You need Python 3.10 or newer. You have {sys.version.split()[0]}.")
        print("    Install the latest from https://www.python.org/downloads/")
        return False
    return True


def _venv_python(venv: Path) -> Path:
    if sys.platform == "win32":
        return venv / "Scripts" / "python.exe"
    return venv / "bin" / "python"


def _ensure_venv(root: Path) -> Path | None:
    venv = root / ".venv"
    venv_py = _venv_python(venv)
    if venv_py.exists():
        return venv_py
    print("[*] First-time setup: creating virtual environment...")
    try:
        subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True)
    except (subprocess.CalledProcessError, OSError) as exc:
        print(f"[X] Could not create the virtual environment: {exc}")
        return None
    if not venv_py.exists():
        print("[X] Virtual environment was created but the python binary is missing.")
        return None
    return venv_py


def _install_requirements(root: Path, venv_py: Path) -> bool:
    print("[*] Making sure required packages are installed...")
    try:
        subprocess.run(
            [
                str(venv_py), "-m", "pip", "install",
                "--disable-pip-version-check", "-q",
                "-r", str(root / "requirements.txt"),
            ],
            check=True,
        )
        return True
    except (subprocess.CalledProcessError, OSError) as exc:
        print(f"[X] Could not install required packages: {exc}")
        print("    Check your internet connection and try again.")
        return False


def _self_update(venv_py: Path) -> None:
    print("[*] Checking for updates...")
    try:
        subprocess.run([str(venv_py), "-m", "easyvimm.updater"], check=False)
    except OSError as exc:
        print(f"    update step skipped: {exc}")


def _pause() -> None:
    try:
        input("Press Enter to close... ")
    except EOFError:
        pass


if __name__ == "__main__":
    sys.exit(main())
