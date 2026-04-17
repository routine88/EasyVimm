import json
import os
from pathlib import Path

DEFAULT_CONFIG = {
    "downloads_folder": "~/Downloads",
    "output_folder": "~/EasyVimm-ROMs",
    "naming_convention": "miyoo_onion",
    "match_window_seconds": 600,
    "auto_open_next": False,
}


def load_config(path: Path) -> dict:
    cfg = dict(DEFAULT_CONFIG)
    if path.exists():
        with path.open() as fh:
            user_cfg = json.load(fh)
        for key in DEFAULT_CONFIG:
            if key in user_cfg:
                cfg[key] = user_cfg[key]
    cfg["downloads_folder"] = os.path.expanduser(cfg["downloads_folder"])
    cfg["output_folder"] = os.path.expanduser(cfg["output_folder"])
    return cfg


def save_config(path: Path, cfg: dict) -> None:
    serializable = {k: cfg[k] for k in DEFAULT_CONFIG if k in cfg}
    path.write_text(json.dumps(serializable, indent=2))
