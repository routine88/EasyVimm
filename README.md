# EasyVimm

A local, click-through ROM downloader for [Vimm's Lair](https://vimm.net/vault).

> **Please read.** EasyVimm is a personal-use tool. You are responsible for
> making sure anything you download is legal where you live. Downloading
> ROMs for games you do not own may infringe copyright in many countries.
> Common legitimate uses include preserving games whose physical copies you
> already own, public-domain titles, and homebrew. When in doubt, don't.

## Why this exists

Modern Vimm scrapers keep dying because the site is fronted by Cloudflare and
other bot-detection layers. EasyVimm takes the opposite approach: **you** stay
in the loop, solve any Cloudflare challenge, and click the actual download
button. EasyVimm just orchestrates the queue, watches your downloads folder,
and files each ROM into a clean, device-ready folder structure.

The flow:

1. Pick the consoles you care about (NES, SNES, GBA, …).
2. EasyVimm builds a queue from a curated list of the top games on each.
3. For each game, it opens a tab on Vimm's vault page.
4. You solve the Cloudflare challenge (if any) and click "Download".
5. EasyVimm sees the new file in your downloads folder, renames it after the
   game's title, and moves it into the right console folder.
6. The next ROM tab opens automatically (optional) and you keep going.

## Quickstart (the easy way)

1. Install [Python 3.10 or newer](https://www.python.org/downloads/).
   On Windows, **check the box "Add python.exe to PATH"** during install.
   On Windows, install Python **from python.org**, not the Microsoft Store
   — the Store placeholder can't create virtual environments.
2. Download this project ([Code → Download ZIP](https://github.com/routine88/easyvimm)
   or `git clone`) and unzip it somewhere you can find again (e.g. your Desktop).
3. Double-click the launcher for your OS:
   - **Windows:** `EasyVimm.bat`
   - **macOS / Linux:** `EasyVimm.command`
   - **Any OS:** `EasyVimm.py` — run as `python3 EasyVimm.py` (works even when
     `.command` has no execute bit, which happens on macOS ZIP downloads).

The launcher sets up everything on first run, checks GitHub for updates on
every launch, starts the app, and opens your browser automatically.

### Nothing happens when I double-click `EasyVimm.command` (macOS)

macOS strips the execute bit when you unzip a download from a browser, so
Finder silently refuses to run the file. You have three options:

1. **Easiest:** run `python3 EasyVimm.py` from a Terminal window instead:
   open Terminal (Cmd+Space, type "Terminal", Enter), then drag the EasyVimm
   folder into the Terminal and press Enter — that `cd`s into the folder — and
   finally type `python3 EasyVimm.py` and press Enter.
2. **Permanent fix:** in Terminal, run `chmod +x EasyVimm.command` once.
   After that, double-click will work.
3. **Gatekeeper fallback:** right-click `EasyVimm.command` in Finder and pick
   "Open". macOS will ask permission once, then remember it.

## Manual install (advanced)

```bash
git clone https://github.com/routine88/easyvimm.git
cd easyvimm
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

Then open <http://127.0.0.1:5000> in your browser.

## Configuration

`config.json`:

| Key | Meaning |
| --- | --- |
| `downloads_folder` | Folder EasyVimm watches for new files. Default `~/Downloads`. |
| `output_folder`    | Where renamed ROMs land, organized by console. Default `~/EasyVimm-ROMs`. |
| `naming_convention`| Folder naming scheme for the output. See below. |
| `match_window_seconds` | How long after session start a file is considered "from this session". |
| `auto_open_next`   | If true, the server pops the next vault tab automatically when a ROM is filed. |

### Naming conventions

Each console entry in `data/consoles.json` defines a folder name per scheme:

- `miyoo_onion` – OnionOS for Miyoo Mini Plus (`FC`, `SFC`, `GB`, `GBC`, `GBA`,
  `MD`, `PS`, …)
- `miyoo_stock` – Stock Miyoo Mini firmware (same shortnames)
- `retroarch`   – Libretro folder names (e.g. `Nintendo - Game Boy Advance`)
- `es_de`       – EmulationStation-DE shortnames (`gba`, `snes`, `psx`, …)

You can freely add new schemes by editing `data/consoles.json`.

## How file matching works

EasyVimm doesn't bypass any bot protection. After you click "Download" on
Vimm's page, the file lands in your `downloads_folder`. The watcher loop:

1. Looks for files with a modification time after the session started.
2. Skips temporary files (`.crdownload`, `.part`, `.tmp`, etc.).
3. Picks the newest file whose extension matches the current ROM's expected
   extensions (e.g. `.gba`, `.zip`).
4. Waits until the file size stops growing (download is finished).
5. Renames it to match the curated game title.
6. Moves it to `output_folder/<console-folder>/`.
7. Advances the queue.

If you accidentally start a different download during a session, just hit
**Skip** to advance the queue without touching the unrelated file.

## Curated lists

Curated top-50 lists per console live in `data/roms_<console>.json`. Each entry
is `{ "title": "...", "vimm_id": null }`. If you fill in `vimm_id` with the
numeric ID from a vault URL like `https://vimm.net/vault/12345`, EasyVimm will
open that page directly. Otherwise it falls back to Vimm's A–Z system index
(e.g. `https://vimm.net/vault/NES`) — you click into the listed title from
there.

Library sizes: NES, SNES, GB, GBC, GBA, N64, Genesis, and PSX ship with 50
titles each. Master System, Game Gear, and TG16 ship with 30 — those libraries
have fewer widely-agreed classics.

To add or reorder games, just edit the JSON files. To add a new console,
append it to `data/consoles.json` and create a matching `data/roms_<key>.json`.

## Limitations

- This is a personal-use tool. Download only ROMs you have a legal right to
  back up.
- Vimm's Lair throttles repeated downloads; if you click too fast it'll
  temporarily refuse new requests. EasyVimm goes at your pace, which usually
  keeps you under the limit.
- The download detector matches by extension and timing, not by hash. If you
  download something else into the same folder during a session, hit **Skip**
  to keep the queue from grabbing the wrong file.
