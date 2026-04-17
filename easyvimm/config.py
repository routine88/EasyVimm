import json
import os
import sys
from pathlib import Path

CONFIG_KEYS = (
    "downloads_folder",
    "output_folder",
    "naming_convention",
    "match_window_seconds",
    "auto_open_next",
)


def _windows_downloads_folder() -> str | None:
    try:
        import winreg
    except ImportError:
        return None
    key_path = r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders"
    value_name = "{374DE290-123F-4565-9164-39C4925E467B}"
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            raw, _ = winreg.QueryValueEx(key, value_name)
    except OSError:
        return None
    return os.path.expandvars(raw)


def _linux_downloads_folder() -> str | None:
    config = Path.home() / ".config" / "user-dirs.dirs"
    if not config.exists():
        return None
    try:
        for line in config.read_text().splitlines():
            line = line.strip()
            if line.startswith("XDG_DOWNLOAD_DIR="):
                value = line.split("=", 1)[1].strip().strip('"')
                return value.replace("$HOME", str(Path.home()))
    except OSError:
        return None
    return None


def default_downloads_folder() -> str:
    home = Path.home()
    detected: str | None = None
    if sys.platform == "win32":
        detected = _windows_downloads_folder()
    elif sys.platform.startswith("linux"):
        detected = _linux_downloads_folder()
    if detected:
        return os.path.expandvars(os.path.expanduser(detected))
    return str(home / "Downloads")


def default_output_folder(app_root: Path) -> str:
    return str(app_root / "ROMs")


def build_defaults(app_root: Path) -> dict:
    return {
        "downloads_folder": default_downloads_folder(),
        "output_folder": default_output_folder(app_root),
        "naming_convention": "miyoo_onion",
        "match_window_seconds": 600,
        "auto_open_next": True,
    }


def load_config(path: Path, app_root: Path | None = None) -> dict:
    if app_root is None:
        app_root = path.parent
    cfg = build_defaults(app_root)
    if path.exists():
        try:
            with path.open() as fh:
                user_cfg = json.load(fh)
        except (OSError, json.JSONDecodeError):
            user_cfg = {}
        for key in CONFIG_KEYS:
            if key in user_cfg and user_cfg[key] not in (None, ""):
                cfg[key] = user_cfg[key]
    else:
        _write(path, cfg)
    cfg["downloads_folder"] = os.path.expanduser(cfg["downloads_folder"])
    cfg["output_folder"] = os.path.expanduser(cfg["output_folder"])
    return cfg


def save_config(path: Path, cfg: dict) -> None:
    _write(path, cfg)


def _write(path: Path, cfg: dict) -> None:
    serializable = {k: cfg[k] for k in CONFIG_KEYS if k in cfg}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(serializable, indent=2))


# Backwards-compatible alias kept for any older code paths.
DEFAULT_CONFIG = {
    "downloads_folder": "~/Downloads",
    "output_folder": "./ROMs",
    "naming_convention": "miyoo_onion",
    "match_window_seconds": 600,
    "auto_open_next": True,
}
