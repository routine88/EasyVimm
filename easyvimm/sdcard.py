import os
import platform
import shutil
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

# Where on the card the per-console folders live, by naming scheme.
SDCARD_PREFIX = {
    "miyoo_onion": "Roms",
    "miyoo_stock": "Roms",
    "retroarch": "roms",
    "es_de": "ROMs",
}

ROMS_VARIANTS = ("Roms", "roms", "ROMs", "ROMS")


def _windows_removable_drives() -> list[Path]:
    try:
        import ctypes
        import string
    except ImportError:
        return []
    try:
        k32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    except OSError:
        return []
    DRIVE_REMOVABLE = 2
    out: list[Path] = []
    bits = k32.GetLogicalDrives()
    for i, letter in enumerate(string.ascii_uppercase):
        if not (bits & (1 << i)):
            continue
        root = f"{letter}:\\"
        if k32.GetDriveTypeW(root) == DRIVE_REMOVABLE:
            out.append(Path(root))
    return out


def _posix_mounts() -> list[Path]:
    candidates: list[Path] = []
    user = os.environ.get("USER", "")
    bases = [
        Path("/Volumes"),
        Path(f"/media/{user}") if user else None,
        Path(f"/run/media/{user}") if user else None,
        Path("/media"),
        Path("/mnt"),
    ]
    seen: set[str] = set()
    for base in bases:
        if not base or not base.exists():
            continue
        try:
            for child in base.iterdir():
                key = str(child.resolve())
                if key in seen:
                    continue
                # Skip the root volume on macOS and similar symlinks.
                try:
                    if child.is_symlink() and child.resolve() == Path("/"):
                        continue
                except OSError:
                    continue
                if child.is_dir():
                    seen.add(key)
                    candidates.append(child)
        except OSError:
            continue
    return candidates


def identify(path: Path) -> dict:
    has_onion_bootstrap = (path / ".tmp_update").exists()
    has_miyoo = any((path / n).exists() for n in ("miyoo", "MIYOO", "Miyoo"))
    roms_variant = next((n for n in ROMS_VARIANTS if (path / n).exists()), None)
    label = "Unknown drive"
    confidence = 0
    if has_onion_bootstrap:
        label = "Miyoo Mini Plus (OnionOS)"
        confidence = 3
    elif has_miyoo:
        label = "Miyoo card"
        confidence = 2
    elif roms_variant:
        label = "Has a ROMs folder"
        confidence = 1
    total_gb: Optional[float] = None
    free_gb: Optional[float] = None
    try:
        usage = shutil.disk_usage(path)
        total_gb = round(usage.total / (1024 ** 3), 1)
        free_gb = round(usage.free / (1024 ** 3), 1)
    except OSError:
        pass
    return {
        "path": str(path),
        "name": path.name or str(path),
        "label": label,
        "confidence": confidence,
        "has_roms": bool(roms_variant),
        "roms_variant": roms_variant,
        "total_gb": total_gb,
        "free_gb": free_gb,
    }


def detect_candidates() -> list[dict]:
    if platform.system() == "Windows":
        try:
            drives = _windows_removable_drives()
        except Exception:  # noqa: BLE001
            drives = []
    else:
        drives = _posix_mounts()
    results = []
    for drive in drives:
        if not drive.exists():
            continue
        try:
            results.append(identify(drive))
        except OSError:
            continue
    results.sort(key=lambda r: (-r["confidence"], r["path"]))
    return results


@dataclass
class DeployProgress:
    state: str = "idle"  # idle / copying / done / error
    total: int = 0
    copied: int = 0
    skipped: int = 0
    failed: int = 0
    current: Optional[str] = None
    mount: Optional[str] = None
    message: Optional[str] = None


class DeployJob:
    """Background job that copies per-console ROM folders onto an SD card."""

    def __init__(self):
        self.progress = DeployProgress()
        self.lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None

    def snapshot(self) -> dict:
        with self.lock:
            return self.progress.__dict__.copy()

    def start(self, output_root: Path, mount: Path, naming: str) -> dict:
        with self.lock:
            if self.progress.state == "copying":
                return self.progress.__dict__.copy()
            self.progress = DeployProgress(state="copying", mount=str(mount))
        self._thread = threading.Thread(
            target=self._run, args=(output_root, mount, naming), daemon=True,
        )
        self._thread.start()
        return self.snapshot()

    def _run(self, output_root: Path, mount: Path, naming: str) -> None:
        try:
            self._do_copy(output_root, mount, naming)
        except Exception as exc:  # noqa: BLE001
            with self.lock:
                self.progress.state = "error"
                self.progress.message = str(exc)
                self.progress.current = None

    def _do_copy(self, output_root: Path, mount: Path, naming: str) -> None:
        prefix = SDCARD_PREFIX.get(naming, "Roms")
        dest_root = mount / prefix

        files: list[tuple[Path, Path]] = []
        if output_root.exists():
            for console_dir in sorted(output_root.iterdir()):
                if not console_dir.is_dir():
                    continue
                target_dir = dest_root / console_dir.name
                for f in sorted(console_dir.iterdir()):
                    if f.is_file():
                        files.append((f, target_dir / f.name))

        with self.lock:
            self.progress.total = len(files)

        if not files:
            with self.lock:
                self.progress.state = "done"
                self.progress.message = "No games to copy yet."
            return

        for src, dst in files:
            with self.lock:
                self.progress.current = f"{dst.parent.name}/{src.name}"
            try:
                if dst.exists() and dst.stat().st_size == src.stat().st_size:
                    with self.lock:
                        self.progress.skipped += 1
                else:
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dst)
                    with self.lock:
                        self.progress.copied += 1
            except OSError as exc:
                with self.lock:
                    self.progress.failed += 1
                    self.progress.message = f"{src.name}: {exc}"

        with self.lock:
            self.progress.state = "done"
            self.progress.current = None
            parts = [f"Copied {self.progress.copied} games"]
            if self.progress.skipped:
                parts.append(f"{self.progress.skipped} already on card")
            if self.progress.failed:
                parts.append(f"{self.progress.failed} failed")
            self.progress.message = ", ".join(parts) + "."
