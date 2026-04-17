import json
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


def build_queue(data_dir: Path, console_keys: list[str]) -> list[dict]:
    consoles = load_consoles(data_dir)
    queue = []
    for key in console_keys:
        if key not in consoles:
            continue
        meta = consoles[key]
        games = load_games(data_dir, key)
        for idx, game in enumerate(games):
            queue.append({
                "console": key,
                "console_display": meta["display_name"],
                "vimm_system": meta["vimm_system"],
                "extensions": meta["extensions"],
                "title": game["title"],
                "vimm_id": game.get("vimm_id"),
                "url": vimm_url_for(game, meta["vimm_system"]),
                "rank": idx + 1,
            })
    return queue
