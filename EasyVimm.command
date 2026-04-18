#!/usr/bin/env bash
# EasyVimm launcher for macOS and Linux.
# Double-click on macOS, or run `./EasyVimm.command` from the terminal.

set -u
cd "$(dirname "$0")"

echo ""
echo "  ============================================"
echo "    EasyVimm - Vimm's Lair ROM Downloader"
echo "  ============================================"
echo ""

# --- Pick a Python 3 interpreter ---
PYTHON_EXE=""
for cand in python3 python; do
  if command -v "$cand" >/dev/null 2>&1; then
    ver=$("$cand" -c 'import sys; print(sys.version_info[0])' 2>/dev/null || echo 0)
    if [ "$ver" = "3" ]; then
      PYTHON_EXE="$cand"
      break
    fi
  fi
done

if [ -z "$PYTHON_EXE" ]; then
  echo "[X] Python 3 is not installed on this computer."
  echo ""
  echo "To use EasyVimm you need Python 3.10 or newer."
  echo "Open this page in your browser and install the latest Python 3:"
  echo "    https://www.python.org/downloads/"
  echo ""
  if command -v open >/dev/null 2>&1; then
    open "https://www.python.org/downloads/" || true
  elif command -v xdg-open >/dev/null 2>&1; then
    xdg-open "https://www.python.org/downloads/" >/dev/null 2>&1 || true
  fi
  echo "After Python is installed, run EasyVimm again."
  read -r -p "Press Enter to close... " _
  exit 1
fi

# --- First-run: create virtual environment ---
if [ ! -x ".venv/bin/python" ]; then
  echo "[*] First-time setup: creating virtual environment..."
  if ! "$PYTHON_EXE" -m venv .venv; then
    echo "[X] Could not create the virtual environment."
    read -r -p "Press Enter to close... " _
    exit 1
  fi
fi

# --- Install / update dependencies (quiet, only shows errors) ---
echo "[*] Making sure required packages are installed..."
if ! ".venv/bin/python" -m pip install --disable-pip-version-check -q -r requirements.txt; then
  echo "[X] Could not install required packages. Check your internet connection."
  read -r -p "Press Enter to close... " _
  exit 1
fi

# --- Self-update: git pull for git clones, GitHub zip overlay otherwise ---
echo "[*] Checking for updates..."
".venv/bin/python" -m easyvimm.updater || true

echo ""
echo "[*] Starting EasyVimm... a browser window will open in a moment."
echo "    Keep this window open while you download games."
echo "    Close this window (or press Ctrl+C) when you are done."
echo ""

exec ".venv/bin/python" app.py
