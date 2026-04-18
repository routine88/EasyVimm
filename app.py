import socket
import threading
import time
import webbrowser
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

from easyvimm.catalog import load_consoles, load_games, merge_vault_ids
from easyvimm.config import load_config, save_config
from easyvimm.sdcard import DeployJob, detect_candidates
from easyvimm.session import DownloadSession

ROOT = Path(__file__).parent
DATA_DIR = ROOT / "data"
CONFIG_PATH = ROOT / "config.json"
STATE_PATH = ROOT / "session.json"
STATIC_DIR = ROOT / "web"

app = Flask(__name__, static_folder=None)
config = load_config(CONFIG_PATH)
session = DownloadSession(DATA_DIR, config, state_path=STATE_PATH)
session.load_persisted()
deploy_job = DeployJob()


def watcher_loop():
    while True:
        try:
            if session.active:
                session.try_match_and_file()
        except Exception as exc:  # noqa: BLE001
            print(f"[watcher] error: {exc}")
        time.sleep(1.0)


@app.get("/")
def index():
    return send_from_directory(STATIC_DIR, "index.html")


@app.get("/web/<path:filename>")
def static_files(filename: str):
    return send_from_directory(STATIC_DIR, filename)


@app.get("/api/consoles")
def api_consoles():
    consoles = load_consoles(DATA_DIR)
    enriched = {}
    for key, meta in consoles.items():
        games = load_games(DATA_DIR, key)
        enriched[key] = {**meta, "game_count": len(games)}
    return jsonify(enriched)


@app.get("/api/config")
def api_get_config():
    return jsonify(config)


@app.post("/api/config")
def api_set_config():
    payload = request.get_json(force=True)
    for key, value in payload.items():
        if key in config:
            config[key] = value
    save_config(CONFIG_PATH, config)
    session.config = config
    return jsonify(config)


@app.post("/api/session/start")
def api_start():
    payload = request.get_json(force=True)
    consoles = payload.get("consoles", [])
    snapshot = session.start(consoles)
    if config.get("auto_open_next") and snapshot.get("current"):
        webbrowser.open_new_tab(snapshot["current"]["url"])
    return jsonify(snapshot)


@app.get("/api/session/status")
def api_status():
    return jsonify(session.snapshot())


@app.get("/api/session/pending")
def api_session_pending():
    return jsonify(session.pending())


@app.post("/api/session/resume")
def api_session_resume():
    return jsonify(session.resume())


@app.post("/api/session/discard")
def api_session_discard():
    return jsonify(session.discard())


@app.post("/api/session/skip")
def api_skip():
    payload = request.get_json(silent=True) or {}
    return jsonify(session.skip_current(payload.get("note", "skipped by user")))


@app.post("/api/session/stop")
def api_stop():
    return jsonify(session.stop())


@app.post("/api/session/open_current")
def api_open_current():
    snap = session.snapshot()
    current = snap.get("current")
    if not current:
        return jsonify({"opened": False})
    webbrowser.open_new_tab(current["url"])
    return jsonify({"opened": True, "url": current["url"]})


@app.get("/api/sdcards")
def api_sdcards():
    return jsonify({"candidates": detect_candidates()})


@app.post("/api/sdcards/deploy")
def api_sdcards_deploy():
    payload = request.get_json(force=True)
    mount_raw = payload.get("mount", "").strip()
    if not mount_raw:
        return jsonify({"error": "missing mount"}), 400
    mount = Path(mount_raw)
    if not mount.exists():
        return jsonify({"error": f"{mount_raw} does not exist"}), 400
    snap = deploy_job.start(
        Path(config["output_folder"]),
        mount,
        config["naming_convention"],
    )
    return jsonify(snap)


@app.get("/api/sdcards/deploy/status")
def api_sdcards_deploy_status():
    return jsonify(deploy_job.snapshot())


@app.post("/api/catalog/merge")
def api_catalog_merge():
    payload = request.get_json(force=True) or {}
    try:
        result = merge_vault_ids(DATA_DIR, payload)
    except (OSError, ValueError) as exc:
        return jsonify({"error": str(exc)}), 400
    session.consoles = load_consoles(DATA_DIR)
    return jsonify(result)


def _open_browser_soon(url: str, delay: float = 1.0) -> None:
    def _open():
        try:
            webbrowser.open_new(url)
        except Exception:  # noqa: BLE001
            pass
    threading.Timer(delay, _open).start()


def _find_free_port(start: int = 5000, count: int = 11) -> int | None:
    """Return the first port in [start, start+count) that we can bind on 127.0.0.1.

    macOS Monterey+ grabs 5000 for AirPlay Receiver by default, so we walk
    forward until we find one that's actually free.
    """
    for port in range(start, start + count):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    return None


def main():
    port = _find_free_port()
    if port is None:
        print("")
        print("[X] Could not find a free port between 5000 and 5010.")
        print("    Close any other EasyVimm windows and try again.")
        print("    (macOS: System Settings -> General -> AirDrop & Handoff, turn off")
        print("     'AirPlay Receiver' if you want EasyVimm to use port 5000.)")
        return

    threading.Thread(target=watcher_loop, daemon=True).start()
    url = f"http://127.0.0.1:{port}"

    print("")
    print(f"  EasyVimm is running at  {url}")
    print(f"  (If a browser tab does not open automatically, visit the URL above.)")
    print("")
    print(f"  Downloads come from :  {config['downloads_folder']}")
    print(f"  ROMs will be saved to: {config['output_folder']}")
    print("")
    if port != 5000:
        print(f"  [i] Port 5000 was in use, so EasyVimm moved to port {port}.")
        print("")

    _open_browser_soon(url)
    app.run(host="127.0.0.1", port=port, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
