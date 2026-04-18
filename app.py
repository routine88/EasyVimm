import threading
import time
import webbrowser
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

from easyvimm.catalog import load_consoles, load_games
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


def _open_browser_soon(url: str, delay: float = 1.0) -> None:
    def _open():
        try:
            webbrowser.open_new(url)
        except Exception:  # noqa: BLE001
            pass
    threading.Timer(delay, _open).start()


def main():
    threading.Thread(target=watcher_loop, daemon=True).start()
    url = "http://127.0.0.1:5000"
    print("")
    print(f"  EasyVimm is running.")
    print(f"  If your browser does not open on its own, go to: {url}")
    print(f"  Downloads folder: {config['downloads_folder']}")
    print(f"  ROMs will be saved to: {config['output_folder']}")
    print("")
    _open_browser_soon(url)
    app.run(host="127.0.0.1", port=5000, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
