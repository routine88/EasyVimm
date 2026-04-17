import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .catalog import build_queue, load_consoles
from .filer import (
    ext_matches,
    file_rom,
    is_partial,
    sanitize_filename,
    target_folder,
    wait_until_stable,
)


@dataclass
class HistoryEntry:
    title: str
    console: str
    status: str  # "filed", "skipped", "failed"
    saved_path: Optional[str] = None
    note: Optional[str] = None
    timestamp: float = field(default_factory=time.time)


class DownloadSession:
    """Tracks a queue of ROM downloads and watches the downloads folder."""

    def __init__(self, data_dir: Path, config: dict):
        self.data_dir = data_dir
        self.config = config
        self.consoles = load_consoles(data_dir)
        self.lock = threading.Lock()
        self.queue: list[dict] = []
        self.cursor: int = 0
        self.history: list[HistoryEntry] = []
        self.session_start: float = 0.0
        self.active: bool = False

    def start(self, console_keys: list[str]) -> dict:
        with self.lock:
            self.queue = build_queue(self.data_dir, console_keys)
            self.cursor = 0
            self.history = []
            self.session_start = time.time()
            self.active = bool(self.queue)
            return self.snapshot_locked()

    def snapshot(self) -> dict:
        with self.lock:
            return self.snapshot_locked()

    def snapshot_locked(self) -> dict:
        current = self.current_locked()
        return {
            "active": self.active,
            "total": len(self.queue),
            "cursor": self.cursor,
            "current": current,
            "history": [h.__dict__ for h in self.history[-50:]],
            "remaining": max(0, len(self.queue) - self.cursor),
        }

    def current_locked(self) -> Optional[dict]:
        if not self.active or self.cursor >= len(self.queue):
            return None
        return dict(self.queue[self.cursor])

    def skip_current(self, note: str = "skipped by user") -> dict:
        with self.lock:
            current = self.current_locked()
            if current:
                self.history.append(HistoryEntry(
                    title=current["title"],
                    console=current["console"],
                    status="skipped",
                    note=note,
                ))
                self.cursor += 1
                if self.cursor >= len(self.queue):
                    self.active = False
            return self.snapshot_locked()

    def stop(self) -> dict:
        with self.lock:
            self.active = False
            return self.snapshot_locked()

    def candidate_files(self) -> list[Path]:
        """Files in the downloads folder that arrived after the session started."""
        downloads = Path(self.config["downloads_folder"])
        if not downloads.exists():
            return []
        results = []
        for path in downloads.iterdir():
            if not path.is_file() or is_partial(path):
                continue
            try:
                mtime = path.stat().st_mtime
            except OSError:
                continue
            if mtime + 1 < self.session_start:
                continue
            results.append(path)
        return results

    def try_match_and_file(self) -> Optional[HistoryEntry]:
        """Look for a downloaded ROM matching the current queue entry and file it."""
        with self.lock:
            current = self.current_locked()
        if not current:
            return None

        downloads = Path(self.config["downloads_folder"])
        if not downloads.exists():
            return None

        match: Optional[Path] = None
        for path in self.candidate_files():
            if ext_matches(path, current["extensions"]):
                if match is None or path.stat().st_mtime > match.stat().st_mtime:
                    match = path

        if not match:
            return None

        if not wait_until_stable(match, timeout=120):
            return None

        console_meta = self.consoles[current["console"]]
        dest = target_folder(
            Path(self.config["output_folder"]),
            console_meta,
            self.config["naming_convention"],
        )
        new_name = sanitize_filename(current["title"])
        try:
            saved = file_rom(match, dest, new_name)
        except OSError as exc:
            entry = HistoryEntry(
                title=current["title"],
                console=current["console"],
                status="failed",
                note=f"file move failed: {exc}",
            )
        else:
            entry = HistoryEntry(
                title=current["title"],
                console=current["console"],
                status="filed",
                saved_path=str(saved),
            )

        with self.lock:
            self.history.append(entry)
            self.cursor += 1
            if self.cursor >= len(self.queue):
                self.active = False

        return entry
