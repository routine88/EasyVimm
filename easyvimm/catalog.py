import json
import re
from pathlib import Path
from urllib.parse import quote

VIMM_VAULT_URL = "https://vimm.net/vault/{vimm_id}"
VIMM_SYSTEM_INDEX_URL = "https://vimm.net/vault/{system}"


def load_consoles(data_dir: Path) -> dict:
    with (data_dir / "consoles.json").open() as fh:
        return json.load(fh)


def load_games(data_dir: Path, console_key: str) -> list[dict]:
    fname = f"roms_{console_key.lower()}.json"
    path = data_dir / fname
    if not path.exists():
        return []
    with path.open() as fh:
        payload = json.load(fh)
    return payload.get("games", [])


def vimm_url_for(game: dict, vimm_system: str) -> str:
    if game.get("vimm_id"):
        return VIMM_VAULT_URL.format(vimm_id=game["vimm_id"])
    return VIMM_SYSTEM_INDEX_URL.format(system=quote(vimm_system, safe=""))


_PAREN_RE = re.compile(r"\([^)]*\)")
_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")


def _fuzzy_title_key(title: str) -> str:
    """Normalize a title for fuzzy matching: lowercase, strip parentheticals and
    non-alphanumerics, collapse whitespace."""
    s = title.lower()
    s = _PAREN_RE.sub(" ", s)
    s = _NON_ALNUM_RE.sub(" ", s)
    return " ".join(s.split()).strip()


def merge_vault_ids(data_dir: Path, payload: dict) -> dict:
    """Fill in vimm_id values on curated games from a harvested payload.

    Accepts either::

        {"system": "NES", "pairs": [{"title": "...", "vimm_id": 123}, ...]}

    or a dict keyed by system name::

        {"NES": [{"title": "...", "vimm_id": 123}, ...], ...}

    Games are matched by fuzzy-normalized title against the curated list for
    the corresponding console. Only blank vimm_id slots are filled; existing
    values are left alone. Returns per-console match counts.
    """
    consoles = load_consoles(data_dir)
    system_to_key = {meta["vimm_system"].lower(): key for key, meta in consoles.items()}

    if "pairs" in payload and "system" in payload:
        by_system = {payload.get("system", ""): payload.get("pairs", [])}
    else:
        by_system = {k: v for k, v in payload.items() if isinstance(v, list)}

    result = {"matched": 0, "by_console": {}, "unmatched_consoles": []}

    for system, pairs in by_system.items():
        console_key = system_to_key.get((system or "").lower())
        if not console_key:
            result["unmatched_consoles"].append(system)
            continue
        path = data_dir / f"roms_{console_key.lower()}.json"
        if not path.exists():
            continue

        incoming: dict[str, int] = {}
        for p in pairs or []:
            title = (p.get("title") or "").strip()
            vid = p.get("vimm_id")
            try:
                vid = int(vid) if vid is not None else None
            except (TypeError, ValueError):
                vid = None
            if not title or not vid:
                continue
            key = _fuzzy_title_key(title)
            if key and key not in incoming:
                incoming[key] = vid

        with path.open() as fh:
            doc = json.load(fh)
        games = doc.get("games") or []
        matched = 0
        for game in games:
            if game.get("vimm_id"):
                continue
            key = _fuzzy_title_key(game.get("title", ""))
            if key and key in incoming:
                game["vimm_id"] = incoming[key]
                matched += 1
        if matched:
            path.write_text(json.dumps(doc, indent=2) + "\n")
        result["by_console"][console_key] = {
            "matched": matched,
            "pending": sum(1 for g in games if not g.get("vimm_id")),
            "total": len(games),
        }
        result["matched"] += matched

    return result


def build_queue(
    data_dir: Path,
    console_keys: list[str],
    *,
    output_root: Path | None = None,
    naming: str = "miyoo_onion",
    skip_existing: bool = False,
) -> tuple[list[dict], list[dict]]:
    """Build the queue and, optionally, a parallel list of games that were
    skipped because their output file already exists.

    Returns (queue, skipped). When `skip_existing` is False or `output_root`
    is None, `skipped` is always empty.
    """
    # Local import so the catalog module stays free of filer churn at import
    # time — filer in turn imports nothing out of catalog, so this is safe.
    from .filer import sanitize_filename, target_folder

    consoles = load_consoles(data_dir)
    queue: list[dict] = []
    skipped: list[dict] = []
    for key in console_keys:
        if key not in consoles:
            continue
        meta = consoles[key]
        games = load_games(data_dir, key)
        dest_dir = (
            target_folder(output_root, meta, naming)
            if output_root is not None and skip_existing
            else None
        )
        rom_exts = [e for e in meta["extensions"] if e.lower() not in {".zip", ".7z"}]
        for idx, game in enumerate(games):
            entry = {
                "console": key,
                "console_display": meta["display_name"],
                "vimm_system": meta["vimm_system"],
                "extensions": meta["extensions"],
                "title": game["title"],
                "vimm_id": game.get("vimm_id"),
                "url": vimm_url_for(game, meta["vimm_system"]),
                "rank": idx + 1,
            }
            if dest_dir is not None and _rom_on_disk(dest_dir, game["title"], rom_exts):
                skipped.append(entry)
                continue
            queue.append(entry)
    return queue, skipped


def _rom_on_disk(dest_dir: Path, title: str, rom_exts: list[str]) -> bool:
    """Has this game already been filed under dest_dir in a previous session?"""
    if not dest_dir.exists():
        return False
    from .filer import sanitize_filename  # local, see build_queue note
    base = sanitize_filename(title)
    # Match both "<Title>.ext" and "<Title> (2).ext" and the multi-file <Title>/ folder.
    if (dest_dir / base).is_dir():
        return True
    for ext in rom_exts:
        if (dest_dir / f"{base}{ext}").exists():
            return True
    return False
