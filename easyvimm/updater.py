"""Self-update. Runs once at launch, via the shell launcher.

Two paths:

* If the install has a .git folder and git is on PATH, run `git pull --ff-only`.
* Otherwise fetch the latest commit SHA on main from the GitHub API, compare
  against a local marker, and — if different — download the repo zip and
  overlay new files onto the install, preserving user data and the venv.

Failures always degrade gracefully: we print a one-line note and let the app
start on the current version.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Optional

REPO = "routine88/easyvimm"
BRANCH = "main"
API_URL = f"https://api.github.com/repos/{REPO}/commits/{BRANCH}"
ZIP_URL = f"https://github.com/{REPO}/archive/refs/heads/{BRANCH}.zip"
SHA_MARKER = ".easyvimm_sha"

# Never overwritten by an update. User data + virtualenv + local config.
PRESERVE = {
    "config.json",
    "session.json",
    ".venv",
    "venv",
    "ROMs",
    ".git",
    ".easyvimm_sha",
}


def run(app_root: Path) -> None:
    try:
        if (app_root / ".git").exists() and _have_git():
            _git_update(app_root)
            return
        _zip_update(app_root)
    except Exception as exc:  # noqa: BLE001
        print(f"[update] skipped ({exc}); continuing with current version.")


def _have_git() -> bool:
    try:
        subprocess.run(
            ["git", "--version"], check=True, capture_output=True, timeout=5,
        )
        return True
    except (OSError, subprocess.SubprocessError):
        return False


def _git_update(app_root: Path) -> None:
    try:
        res = subprocess.run(
            ["git", "pull", "--ff-only"],
            cwd=app_root,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if res.returncode == 0:
            print("[update] up to date.")
        else:
            print("[update] couldn't update, continuing with current version.")
    except (OSError, subprocess.TimeoutExpired):
        print("[update] git update skipped.")


def _zip_update(app_root: Path) -> None:
    remote_sha = _fetch_remote_sha()
    if not remote_sha:
        print("[update] couldn't reach GitHub; continuing with current version.")
        return
    local_sha = _read_local_sha(app_root)
    if local_sha == remote_sha:
        print("[update] up to date.")
        return
    print("[update] downloading the latest version...")
    _download_and_overlay(app_root, remote_sha)
    print(f"[update] updated to {remote_sha[:7]}.")


def _fetch_remote_sha() -> Optional[str]:
    req = urllib.request.Request(API_URL, headers={"User-Agent": "EasyVimm"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return None
    sha = data.get("sha")
    return sha if isinstance(sha, str) else None


def _read_local_sha(app_root: Path) -> Optional[str]:
    marker = app_root / SHA_MARKER
    if not marker.exists():
        return None
    try:
        value = marker.read_text().strip()
        return value or None
    except OSError:
        return None


def _write_local_sha(app_root: Path, sha: str) -> None:
    try:
        (app_root / SHA_MARKER).write_text(sha + "\n")
    except OSError:
        pass


def _download_and_overlay(app_root: Path, sha: str) -> None:
    req = urllib.request.Request(ZIP_URL, headers={"User-Agent": "EasyVimm"})
    with tempfile.TemporaryDirectory() as tmp:
        zip_path = Path(tmp) / "update.zip"
        with urllib.request.urlopen(req, timeout=60) as resp, open(zip_path, "wb") as fh:
            shutil.copyfileobj(resp, fh)
        extract_root = Path(tmp) / "extract"
        extract_root.mkdir()
        with zipfile.ZipFile(zip_path) as zf:
            for info in zf.infolist():
                member = Path(info.filename)
                if member.is_absolute() or any(p == ".." for p in member.parts):
                    continue
                zf.extract(info, extract_root)
        roots = [p for p in extract_root.iterdir() if p.is_dir()]
        if not roots:
            return
        _overlay(roots[0], app_root)
    _write_local_sha(app_root, sha)


def _overlay(src_root: Path, dst_root: Path) -> None:
    for src in src_root.rglob("*"):
        rel = src.relative_to(src_root)
        if any(part in PRESERVE for part in rel.parts):
            continue
        dst = dst_root / rel
        if src.is_dir():
            dst.mkdir(parents=True, exist_ok=True)
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


if __name__ == "__main__":
    # Invoked by the shell launcher as:  python -m easyvimm.updater
    root = Path(__file__).resolve().parent.parent
    run(root)
    sys.exit(0)
