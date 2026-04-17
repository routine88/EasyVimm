import re
import shutil
import time
from pathlib import Path

PARTIAL_SUFFIXES = (".crdownload", ".part", ".partial", ".download", ".tmp", ".opdownload")


def is_partial(path: Path) -> bool:
    return path.suffix.lower() in PARTIAL_SUFFIXES or path.name.startswith(".")


def ext_matches(path: Path, allowed: list[str]) -> bool:
    suffix = path.suffix.lower()
    return suffix in {e.lower() for e in allowed}


def sanitize_filename(title: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", title)
    cleaned = cleaned.strip().rstrip(".")
    return cleaned or "ROM"


def target_folder(output_root: Path, console_meta: dict, naming: str) -> Path:
    folder = console_meta.get("folders", {}).get(naming, console_meta.get("vimm_system", "Misc"))
    return output_root / folder


def wait_until_stable(path: Path, timeout: float = 600.0, poll: float = 1.0) -> bool:
    """Block until the file's size stops changing or timeout elapses."""
    deadline = time.monotonic() + timeout
    last_size = -1
    stable_for = 0.0
    while time.monotonic() < deadline:
        if not path.exists():
            return False
        try:
            size = path.stat().st_size
        except OSError:
            return False
        if size == last_size and size > 0:
            stable_for += poll
            if stable_for >= 2.0:
                return True
        else:
            stable_for = 0.0
            last_size = size
        time.sleep(poll)
    return False


def file_rom(src: Path, dest_folder: Path, new_basename: str) -> Path:
    dest_folder.mkdir(parents=True, exist_ok=True)
    suffix = src.suffix
    candidate = dest_folder / f"{new_basename}{suffix}"
    counter = 2
    while candidate.exists():
        candidate = dest_folder / f"{new_basename} ({counter}){suffix}"
        counter += 1
    shutil.move(str(src), str(candidate))
    return candidate
