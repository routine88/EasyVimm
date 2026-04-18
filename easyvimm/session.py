import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .catalog import build_queue, load_consoles
from .filer import (
    ext_matches,
    extract_rom_from_zip,
    file_rom,
    is_archive,
    is_partial,
    playable_extensions,
    sanitize_filename,
    target_folder,
    wait_until_stable,
)
from .persistence import clear_state, load_state, save_state


@dataclass
class HistoryEntry:
    title: str
    console: str
    status: str  # "filed", "skipped", "failed"
    saved_path: Optional[str] = None
    note: Optional[str] = None
    timestamp: float = field(default_factory=time.time)


IDLE_PROGRESS = {"state": "idle", "filename": None, "size_mb": None}
WAITING_PROGRESS = {"state": "waiting", "filename": None, "size_mb": None}


class DownloadSession:
    """Tracks a queue of ROM downloads and watches the downloads folder."""

    def __init__(self, data_dir: Path, config: dict, state_path: Optional[Path] = None):
        self.data_dir = data_dir
        self.config = config
        self.state_path = state_path
        self.consoles = load_consoles(data_dir)
        self.lock = threading.Lock()
        self.queue: list[dict] = []
        self.cursor: int = 0
        self.history: list[HistoryEntry] = []
        self.session_start: float = 0.0
        self.active: bool = False
        self.current_progress: dict = dict(IDLE_PROGRESS)

    def start(self, console_keys: list[str]) -> dict:
        queue, already_had = build_queue(
            self.data_dir,
            console_keys,
            output_root=Path(self.config["output_folder"]),
            naming=self.config["naming_convention"],
            skip_existing=True,
        )
        with self.lock:
            self.queue = queue
            self.cursor = 0
            self.history = [
                HistoryEntry(
                    title=g["title"],
                    console=g["console"],
                    status="skipped",
                    note="already on your computer",
                )
                for g in already_had
            ]
            self.session_start = time.time()
            self.active = bool(self.queue)
            self.current_progress = dict(WAITING_PROGRESS if self.active else IDLE_PROGRESS)
            snap = self.snapshot_locked()
        self._persist()
        return snap

    def load_persisted(self) -> bool:
        """Load a previously persisted session (paused). Returns True if one was loaded."""
        if not self.state_path:
            return False
        data = load_state(self.state_path)
        if not data:
            return False
        queue = data.get("queue") or []
        cursor = int(data.get("cursor") or 0)
        if not queue or cursor >= len(queue):
            clear_state(self.state_path)
            return False
        with self.lock:
            self.queue = queue
            self.cursor = cursor
            self.history = [HistoryEntry(**h) for h in data.get("history", [])]
            self.session_start = float(data.get("session_start") or time.time())
            self.active = False  # require explicit resume
            self.current_progress = dict(WAITING_PROGRESS)
        return True

    def pending(self) -> dict:
        """Describe a resumable session without side effects."""
        with self.lock:
            if not self.queue or self.cursor >= len(self.queue):
                return {"pending": False}
            consoles: list[str] = []
            seen: set[str] = set()
            for item in self.queue:
                if item["console"] not in seen:
                    seen.add(item["console"])
                    consoles.append(item["console"])
            return {
                "pending": True,
                "active": self.active,
                "cursor": self.cursor,
                "total": len(self.queue),
                "done": self.cursor,
                "remaining": len(self.queue) - self.cursor,
                "consoles": consoles,
            }

    def resume(self) -> dict:
        with self.lock:
            if self.queue and self.cursor < len(self.queue):
                self.active = True
                # Reset match window so we don't pick up stale files left in
                # Downloads from before the pause.
                self.session_start = time.time()
                self.current_progress = dict(WAITING_PROGRESS)
            snap = self.snapshot_locked()
        self._persist()
        return snap

    def discard(self) -> dict:
        with self.lock:
            self.queue = []
            self.cursor = 0
            self.history = []
            self.active = False
            self.current_progress = dict(IDLE_PROGRESS)
            snap = self.snapshot_locked()
        if self.state_path:
            clear_state(self.state_path)
        return snap

    def _persist(self) -> None:
        if not self.state_path:
            return
        with self.lock:
            if not self.queue or self.cursor >= len(self.queue):
                clear_state(self.state_path)
                return
            payload = {
                "queue": self.queue,
                "cursor": self.cursor,
                "history": [h.__dict__ for h in self.history],
                "session_start": self.session_start,
            }
        save_state(self.state_path, payload)

    def snapshot(self) -> dict:
        with self.lock:
            return self.snapshot_locked()

    def snapshot_locked(self) -> dict:
        return {
            "active": self.active,
            "total": len(self.queue),
            "cursor": self.cursor,
            "current": self.current_locked(),
            "current_progress": dict(self.current_progress),
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
                self.current_progress = dict(
                    WAITING_PROGRESS if self.active else IDLE_PROGRESS,
                )
            snap = self.snapshot_locked()
        self._persist()
        return snap

    def stop(self) -> dict:
        with self.lock:
            self.active = False
            self.current_progress = dict(IDLE_PROGRESS)
            snap = self.snapshot_locked()
        self._persist()
        return snap

    def _scan_downloads(self, current: dict) -> tuple[Optional[Path], Optional[Path]]:
        """Return (latest_complete_match, latest_partial) in downloads folder."""
        downloads = Path(self.config["downloads_folder"])
        if not downloads.exists():
            return None, None
        latest_complete: Optional[Path] = None
        latest_partial: Optional[Path] = None
        try:
            for path in downloads.iterdir():
                if not path.is_file():
                    continue
                try:
                    stat = path.stat()
                except OSError:
                    continue
                if stat.st_mtime + 1 < self.session_start:
                    continue
                if is_partial(path):
                    if latest_partial is None or stat.st_mtime > latest_partial.stat().st_mtime:
                        latest_partial = path
                    continue
                if ext_matches(path, current["extensions"]):
                    if latest_complete is None or stat.st_mtime > latest_complete.stat().st_mtime:
                        latest_complete = path
        except OSError:
            pass
        return latest_complete, latest_partial

    def probe_current(self) -> Optional[HistoryEntry]:
        """One watcher tick: update progress state, file the ROM if one is ready."""
        with self.lock:
            current = self.current_locked()
        if not current:
            self.current_progress = dict(IDLE_PROGRESS)
            return None

        complete, partial = self._scan_downloads(current)

        if complete:
            try:
                size_mb = complete.stat().st_size / (1024 * 1024)
            except OSError:
                size_mb = None
            self.current_progress = {
                "state": "finalizing",
                "filename": complete.name,
                "size_mb": round(size_mb, 2) if size_mb else None,
            }
            if not wait_until_stable(complete, timeout=60):
                return None
            return self._file_complete(current, complete)

        if partial:
            try:
                size_mb = partial.stat().st_size / (1024 * 1024)
            except OSError:
                size_mb = None
            self.current_progress = {
                "state": "downloading",
                "filename": partial.name,
                "size_mb": round(size_mb, 2) if size_mb else None,
            }
            return None

        self.current_progress = dict(WAITING_PROGRESS)
        return None

    def _file_complete(self, current: dict, match: Path) -> HistoryEntry:
        console_meta = self.consoles[current["console"]]
        dest = target_folder(
            Path(self.config["output_folder"]),
            console_meta,
            self.config["naming_convention"],
        )
        new_name = sanitize_filename(current["title"])
        note: Optional[str] = None
        try:
            if is_archive(match):
                rom_exts = playable_extensions(console_meta["extensions"])
                extracted = extract_rom_from_zip(match, dest, new_name, rom_exts)
                if extracted:
                    saved = extracted
                else:
                    saved = file_rom(match, dest, new_name)
                    note = "kept as archive — emulator will unzip"
            else:
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
                note=note,
            )
        with self.lock:
            self.history.append(entry)
            self.cursor += 1
            if self.cursor >= len(self.queue):
                self.active = False
            self.current_progress = dict(
                WAITING_PROGRESS if self.active else IDLE_PROGRESS,
            )
        self._persist()
        return entry

    # Backwards-compatible alias used by the watcher loop.
    def try_match_and_file(self) -> Optional[HistoryEntry]:
        return self.probe_current()
