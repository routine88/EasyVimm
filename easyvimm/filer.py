import re
import shutil
import time
import zipfile
from pathlib import Path
from typing import Optional

PARTIAL_SUFFIXES = (".crdownload", ".part", ".partial", ".download", ".tmp", ".opdownload")
ARCHIVE_EXTENSIONS = {".zip", ".7z"}


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
    candidate = _unique_sibling(dest_folder / f"{new_basename}{suffix}", new_basename, suffix)
    shutil.move(str(src), str(candidate))
    return candidate


def _unique_sibling(candidate: Path, base: str, suffix: str) -> Path:
    counter = 2
    while candidate.exists():
        candidate = candidate.parent / f"{base} ({counter}){suffix}"
        counter += 1
    return candidate


def is_archive(path: Path) -> bool:
    return path.suffix.lower() in ARCHIVE_EXTENSIONS


def playable_extensions(console_extensions: list[str]) -> list[str]:
    """ROM extensions minus archive formats — what an emulator can actually load."""
    return [e for e in console_extensions if e.lower() not in ARCHIVE_EXTENSIONS]


def extract_rom_from_zip(
    archive: Path,
    dest_folder: Path,
    new_basename: str,
    rom_exts: list[str],
) -> Optional[Path]:
    """Extract a zip, place the real ROM under dest_folder/new_basename.ext.

    Returns the final path of the saved content, or None if the zip couldn't
    be extracted or didn't contain a matching ROM. Safe members only — absolute
    paths and .. parents are refused. On success, the source archive is deleted.
    """
    if archive.suffix.lower() != ".zip":
        return None
    rom_ext_set = {e.lower() for e in rom_exts}
    try:
        with zipfile.ZipFile(archive) as zf:
            safe_members = []
            for info in zf.infolist():
                if info.is_dir():
                    continue
                member = Path(info.filename)
                if member.is_absolute() or any(p == ".." for p in member.parts):
                    continue
                safe_members.append(info)
            roms = [m for m in safe_members if Path(m.filename).suffix.lower() in rom_ext_set]
            dest_folder.mkdir(parents=True, exist_ok=True)
            if len(roms) == 1:
                info = roms[0]
                suffix = Path(info.filename).suffix
                dst = _unique_sibling(
                    dest_folder / f"{new_basename}{suffix}", new_basename, suffix,
                )
                with zf.open(info) as src, open(dst, "wb") as out:
                    shutil.copyfileobj(src, out)
                archive.unlink(missing_ok=True)
                return dst
            if len(roms) > 1:
                # Multi-file rom (e.g. PSX .bin + .cue). Keep them together.
                sub = dest_folder / new_basename
                counter = 2
                while sub.exists():
                    sub = dest_folder / f"{new_basename} ({counter})"
                    counter += 1
                sub.mkdir(parents=True)
                for info in safe_members:
                    target = sub / Path(info.filename).name
                    with zf.open(info) as src, open(target, "wb") as out:
                        shutil.copyfileobj(src, out)
                archive.unlink(missing_ok=True)
                return sub
    except (OSError, zipfile.BadZipFile):
        return None
    return None
