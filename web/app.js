const state = {
  consoles: {},
  selected: new Set(),
  config: {},
  status: null,
  pollHandle: null,
  sdCandidates: [],
  sdSelected: null,
  sdPollHandle: null,
  waitingSince: 0,       // ms timestamp when we entered "waiting"
  stuckPromptShown: false,
  lastProgressState: null,
  soundsEnabled: true,
};

const STUCK_AFTER_MS = 90_000;  // show nudge after 90s of waiting

const STATUS_LABELS = {
  filed: "saved",
  skipped: "skipped",
  failed: "couldn't save",
};

const $ = (id) => document.getElementById(id);

async function api(path, opts = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  if (!res.ok) throw new Error(`${path}: ${res.status}`);
  return res.json();
}

function formatSize(mb) {
  if (mb >= 1024) return `${(mb / 1024).toFixed(1)} GB`;
  if (mb >= 10) return `${Math.round(mb)} MB`;
  if (mb >= 1) return `${mb.toFixed(1)} MB`;
  return `${Math.round(mb * 1000)} KB`;
}

// Rough human-time per ROM: locate, click, Cloudflare, click Download, wait
// for the file. ~15 s per ROM is a realistic middle of the road.
const SECONDS_PER_ROM = 15;

function formatClickTime(games) {
  const totalSeconds = games * SECONDS_PER_ROM;
  const minutes = Math.round(totalSeconds / 60);
  if (minutes < 1) return "less than a minute";
  if (minutes < 60) {
    const rounded = minutes < 10 ? minutes : Math.round(minutes / 5) * 5;
    return `about ${rounded} minute${rounded === 1 ? "" : "s"} of clicking`;
  }
  const hours = Math.round((minutes / 60) * 2) / 2;  // nearest half-hour
  return `about ${hours} hour${hours === 1 ? "" : "s"} of clicking`;
}

function estimateForConsoles(keys) {
  let games = 0;
  let mb = 0;
  for (const key of keys) {
    const meta = state.consoles[key];
    if (!meta) continue;
    games += meta.game_count || 0;
    mb += (meta.game_count || 0) * (meta.avg_rom_mb || 0);
  }
  return { games, mb };
}

async function loadConfig() {
  state.config = await api("/api/config");
  $("cfg-downloads").value = state.config.downloads_folder;
  $("cfg-output").value = state.config.output_folder;
  $("cfg-naming").value = state.config.naming_convention;
  $("cfg-auto-open").checked = !!state.config.auto_open_next;
  $("summary-downloads").textContent = state.config.downloads_folder;
  $("summary-output").textContent = state.config.output_folder;
  $("footer-output").textContent = state.config.output_folder;
}

function toggleAdvanced() {
  const panel = $("advanced-panel");
  const btn = $("toggle-advanced");
  panel.hidden = !panel.hidden;
  btn.textContent = panel.hidden ? "Change these settings" : "Hide settings";
}

async function saveConfig() {
  const payload = {
    downloads_folder: $("cfg-downloads").value,
    output_folder: $("cfg-output").value,
    naming_convention: $("cfg-naming").value,
    auto_open_next: $("cfg-auto-open").checked,
  };
  state.config = await api("/api/config", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  $("summary-downloads").textContent = state.config.downloads_folder;
  $("summary-output").textContent = state.config.output_folder;
  $("footer-output").textContent = state.config.output_folder;
  flash("Settings saved.");
}

async function loadConsoles() {
  state.consoles = await api("/api/consoles");
  const grid = $("console-grid");
  grid.innerHTML = "";
  const entries = Object.entries(state.consoles).sort((a, b) => {
    // Classic Six first (in consoles.json insertion order), then rest alphabetical.
    const aClassic = a[1].classic_six ? 0 : 1;
    const bClassic = b[1].classic_six ? 0 : 1;
    if (aClassic !== bClassic) return aClassic - bClassic;
    if (a[1].classic_six && b[1].classic_six) return 0;  // stable: preserve JSON order
    return a[1].display_name.localeCompare(b[1].display_name);
  });
  for (const [key, meta] of entries) {
    const card = document.createElement("div");
    card.className = "console-card";
    if (meta.classic_six) card.classList.add("classic");
    card.dataset.key = key;
    const sizeHint = meta.avg_rom_mb
      ? ` · ~${formatSize(meta.game_count * meta.avg_rom_mb)}`
      : "";
    const badge = meta.classic_six ? `<span class="card-badge">Classic Six</span>` : "";
    card.innerHTML = `
      ${badge}
      <div class="name">${meta.short_name || meta.display_name}</div>
      <div class="count">${meta.game_count} top games${sizeHint}</div>
    `;
    card.addEventListener("click", () => toggleConsole(key));
    grid.appendChild(card);
  }

  const classicKeys = Object.entries(state.consoles)
    .filter(([, meta]) => meta.classic_six)
    .map(([key]) => key);
  const classicEst = estimateForConsoles(classicKeys);
  $("preset-classic-six-estimate").textContent =
    `${classicEst.games} games · about ${formatSize(classicEst.mb)} · ${formatClickTime(classicEst.games)}`;

  updateSelectionSummary();
}

function toggleConsole(key) {
  const card = document.querySelector(`.console-card[data-key="${key}"]`);
  if (!card) return;
  if (state.selected.has(key)) {
    state.selected.delete(key);
    card.classList.remove("selected");
  } else {
    state.selected.add(key);
    card.classList.add("selected");
  }
  updateSelectionSummary();
}

function selectOnly(keys) {
  state.selected = new Set(keys);
  document.querySelectorAll(".console-card").forEach((card) => {
    card.classList.toggle("selected", state.selected.has(card.dataset.key));
  });
  updateSelectionSummary();
}

function updateSelectionSummary() {
  const el = $("selection-summary");
  const btn = $("start-btn");
  if (state.selected.size === 0) {
    el.textContent = "Pick at least one console above, or click Classic Six.";
    btn.disabled = true;
    return;
  }
  const est = estimateForConsoles(state.selected);
  const consoles = Array.from(state.selected)
    .map((k) => state.consoles[k]?.short_name || k)
    .join(", ");
  el.textContent =
    `Picked: ${consoles} — ${est.games} games, about ${formatSize(est.mb)}, ${formatClickTime(est.games)}.`;
  btn.disabled = false;
}

async function startSession() {
  if (state.selected.size === 0) return;
  const consoles = Array.from(state.selected);
  state.status = await api("/api/session/start", {
    method: "POST",
    body: JSON.stringify({ consoles }),
  });
  $("setup-panel").hidden = true;
  $("done-panel").hidden = true;
  $("session-panel").hidden = false;
  state.waitingSince = 0;
  state.stuckPromptShown = false;
  $("stuck-nudge").hidden = true;
  requestNotificationPermission();
  // Prime the audio context with this user gesture so later chimes are allowed.
  try { playChime(440, 30); } catch (_err) {}
  renderStatus();
  startPolling();
  if (!state.config.auto_open_next && state.status.current) {
    openCurrent();
  }
}

function requestNotificationPermission() {
  if (!("Notification" in window)) return;
  if (Notification.permission === "default") {
    try { Notification.requestPermission(); } catch (_e) {}
  }
}

async function openCurrent() {
  const snap = state.status;
  if (!snap || !snap.current) return;
  window.open(snap.current.url, "_blank", "noopener");
}

async function skipCurrent() {
  state.status = await api("/api/session/skip", {
    method: "POST",
    body: JSON.stringify({ note: "skipped by user" }),
  });
  renderStatus();
}

async function stopSession() {
  if (!confirm("Stop getting games? You can pick up again later.")) return;
  state.status = await api("/api/session/stop", { method: "POST" });
  renderStatus();
  showDone();
}

function startPolling() {
  if (state.pollHandle) clearInterval(state.pollHandle);
  state.pollHandle = setInterval(pollStatus, 1500);
}

async function pollStatus() {
  try {
    const next = await api("/api/session/status");
    const advanced = state.status && next.cursor > state.status.cursor;
    state.status = next;
    renderStatus();
    if (advanced) {
      onRomFiled(next);
      if (state.config.auto_open_next && next.current) {
        await fetch("/api/session/open_current", { method: "POST" });
      }
    }
    if (!next.active) {
      clearInterval(state.pollHandle);
      state.pollHandle = null;
      onSessionComplete();
      showDone();
    }
  } catch (err) {
    console.warn("poll failed", err);
  }
}

function onRomFiled(snap) {
  state.waitingSince = 0;
  state.stuckPromptShown = false;
  const hideNudge = $("stuck-nudge");
  if (hideNudge) hideNudge.hidden = true;
  if (!state.soundsEnabled) return;
  playChime();
  flashTitle(`✓ Saved ${snap.cursor}/${snap.total}`);
  tryNotify(
    "Game saved",
    `${snap.cursor} of ${snap.total} done — ${snap.remaining} to go.`,
  );
}

function onSessionComplete() {
  if (!state.soundsEnabled) return;
  playChime();
  playChime(880, 180);
  flashTitle("✓ All games saved!");
  tryNotify("EasyVimm: all done!", "Your games are ready to copy to your SD card.");
}

let _titleTimer = null;
function baseTitle() {
  const snap = state.status;
  if (snap && snap.total && snap.active) {
    return `EasyVimm · ${snap.cursor}/${snap.total}`;
  }
  return "EasyVimm";
}
function syncTitle() {
  if (_titleTimer) return;  // a flash is in progress; leave it alone
  document.title = baseTitle();
}
function flashTitle(msg) {
  if (_titleTimer) clearTimeout(_titleTimer);
  document.title = msg;
  _titleTimer = setTimeout(() => {
    _titleTimer = null;
    document.title = baseTitle();
  }, 6000);
}

let _audioCtx = null;
function playChime(freq = 660, durationMs = 150) {
  try {
    if (!_audioCtx) {
      _audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    }
    const osc = _audioCtx.createOscillator();
    const gain = _audioCtx.createGain();
    osc.frequency.value = freq;
    osc.type = "sine";
    gain.gain.setValueAtTime(0.001, _audioCtx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.15, _audioCtx.currentTime + 0.02);
    gain.gain.exponentialRampToValueAtTime(0.001, _audioCtx.currentTime + durationMs / 1000);
    osc.connect(gain).connect(_audioCtx.destination);
    osc.start();
    osc.stop(_audioCtx.currentTime + durationMs / 1000 + 0.05);
  } catch (_err) {
    // Audio can fail before the first user gesture; silent.
  }
}

function tryNotify(title, body) {
  if (!("Notification" in window)) return;
  if (Notification.permission === "granted") {
    try { new Notification(title, { body, silent: true }); } catch (_e) {}
  }
}

function evaluateStuckState(snap) {
  const stateKey = (snap.current_progress || {}).state || "waiting";
  if (stateKey !== "waiting") {
    state.waitingSince = 0;
    state.stuckPromptShown = false;
    $("stuck-nudge").hidden = true;
    return;
  }
  if (!state.waitingSince) {
    state.waitingSince = Date.now();
  }
  const elapsed = Date.now() - state.waitingSince;
  if (elapsed > STUCK_AFTER_MS && !state.stuckPromptShown) {
    state.stuckPromptShown = true;
    const path = $("stuck-watched-path");
    if (path && state.config.downloads_folder) {
      path.textContent = state.config.downloads_folder;
    }
    $("stuck-nudge").hidden = false;
  }
}

function openSettingsFromStuckNudge() {
  // Jump back to the setup page and reveal the advanced panel so the kid
  // can change the downloads folder without losing their session.
  showPanel("setup-panel");
  if ($("advanced-panel").hidden) {
    toggleAdvanced();
  }
  $("cfg-downloads").focus();
  $("cfg-downloads").select();
}

function renderStatus() {
  const snap = state.status;
  if (!snap) return;
  const total = snap.total || 1;
  const done = snap.cursor;
  $("progress-fill").style.width = `${(done / total) * 100}%`;
  $("progress-text").textContent =
    `Saved ${done} of ${total} — ${snap.remaining} to go.`;
  if (snap.current) {
    $("current-console").textContent =
      state.consoles[snap.current.console]?.short_name || snap.current.console_display;
    $("current-rank").textContent = `Game ${snap.current.rank} of the top ${total} you picked`;
    $("current-title").textContent = snap.current.title;
    $("walkthrough-title").textContent = snap.current.title;
  } else {
    $("current-console").textContent = "—";
    $("current-rank").textContent = "—";
    $("current-title").textContent = "All done!";
    $("walkthrough-title").textContent = "this game";
  }

  renderDownloadState(snap);
  evaluateStuckState(snap);
  syncTitle();

  const list = $("history-list");
  list.innerHTML = "";
  for (const h of snap.history.slice().reverse()) {
    const li = document.createElement("li");
    li.className = h.status;
    const label = STATUS_LABELS[h.status] || h.status;
    li.innerHTML = `
      <span><strong>${h.title}</strong> <em>(${h.console})</em></span>
      <span class="status">${label}${h.note ? " · " + h.note : ""}</span>
    `;
    list.appendChild(li);
  }
}

function renderDownloadState(snap) {
  const el = $("download-state");
  const text = $("state-text");
  const progress = snap.current_progress || { state: "waiting" };
  const title = snap.current ? snap.current.title : null;

  let stateKey = progress.state || "waiting";
  let msg;
  switch (stateKey) {
    case "downloading": {
      const size = formatProgressSize(progress.size_mb);
      msg = progress.filename
        ? `Downloading ${progress.filename}${size ? " (" + size + ")" : ""}…`
        : "Downloading…";
      break;
    }
    case "finalizing": {
      msg = title
        ? `Got the file — saving as “${title}” now…`
        : "Got the file — saving now…";
      break;
    }
    case "idle": {
      stateKey = "saved";
      msg = "All games are saved!";
      break;
    }
    default:
      msg = "Waiting for you to click Download on the Vimm page…";
      stateKey = "waiting";
  }
  el.dataset.state = stateKey;
  text.textContent = msg;
}

function formatProgressSize(mb) {
  if (mb == null) return "";
  if (mb >= 1024) return `${(mb / 1024).toFixed(1)} GB`;
  if (mb >= 10) return `${Math.round(mb)} MB`;
  if (mb >= 1) return `${mb.toFixed(1)} MB`;
  return `${Math.round(mb * 1000)} KB`;
}

function showDone() {
  const snap = state.status;
  $("session-panel").hidden = true;
  $("done-panel").hidden = false;
  if (!snap) return;
  const filed = snap.history.filter((h) => h.status === "filed").length;
  const skipped = snap.history.filter((h) => h.status === "skipped").length;
  const failed = snap.history.filter((h) => h.status === "failed").length;
  const parts = [`${filed} saved`];
  if (skipped) parts.push(`${skipped} skipped`);
  if (failed) parts.push(`${failed} couldn't save`);
  $("done-summary").textContent =
    `You got ${parts.join(", ")}. Your games are in ${state.config.output_folder}.`;
}

function restart() {
  state.selected.clear();
  document.querySelectorAll(".console-card.selected").forEach((c) =>
    c.classList.remove("selected"),
  );
  updateSelectionSummary();
  $("done-panel").hidden = true;
  $("setup-panel").hidden = false;
}

function flash(msg) {
  const original = $("save-config-btn").textContent;
  $("save-config-btn").textContent = msg;
  setTimeout(() => ($("save-config-btn").textContent = original), 1500);
}

function applyClassicSix() {
  const keys = Object.entries(state.consoles)
    .filter(([, meta]) => meta.classic_six)
    .map(([key]) => key);
  selectOnly(keys);
}

function showPanel(panelId) {
  for (const id of ["setup-panel", "session-panel", "done-panel", "sdcard-panel"]) {
    $(id).hidden = id !== panelId;
  }
}

function openSdPanel() {
  showPanel("sdcard-panel");
  $("sd-candidates").innerHTML = "";
  $("sd-copy-btn").hidden = true;
  $("sd-copy-btn").disabled = true;
  $("sd-progress-area").hidden = true;
  $("sd-done-area").hidden = true;
  state.sdSelected = null;
  state.sdCandidates = [];
  if (state.sdPollHandle) { clearInterval(state.sdPollHandle); state.sdPollHandle = null; }
}

function closeSdPanel() {
  if (state.sdPollHandle) { clearInterval(state.sdPollHandle); state.sdPollHandle = null; }
  showPanel("setup-panel");
}

async function scanSdCards() {
  const btn = $("sd-scan-btn");
  btn.disabled = true;
  btn.textContent = "Looking…";
  try {
    const data = await api("/api/sdcards");
    state.sdCandidates = data.candidates || [];
    renderSdCandidates();
  } finally {
    btn.disabled = false;
    btn.textContent = "Find my card again";
  }
}

function renderSdCandidates() {
  const container = $("sd-candidates");
  container.innerHTML = "";
  if (state.sdCandidates.length === 0) {
    container.innerHTML =
      `<p class="hint">I couldn't find any drives. Make sure the SD card is plugged in and try again.</p>`;
    $("sd-copy-btn").hidden = true;
    return;
  }
  for (const cand of state.sdCandidates) {
    const row = document.createElement("div");
    row.className = "sd-card-option";
    row.dataset.path = cand.path;
    const badgeClass = cand.confidence > 0 ? `confidence-${cand.confidence}` : "";
    const size = cand.total_gb ? `${cand.total_gb} GB` : "";
    const free = cand.free_gb != null ? `, ${cand.free_gb} GB free` : "";
    row.innerHTML = `
      <div class="sd-card-left">
        <div class="sd-card-name">${cand.label}${size ? " — " + size + free : ""}</div>
        <div class="sd-card-path">${cand.path}</div>
      </div>
      <div class="sd-card-badge ${badgeClass}">${cand.confidence ? "Likely your card" : "Unknown"}</div>
    `;
    row.addEventListener("click", () => selectSdCandidate(cand.path));
    container.appendChild(row);
  }
  const best = state.sdCandidates.find((c) => c.confidence >= 2);
  if (best) selectSdCandidate(best.path);
  $("sd-copy-btn").hidden = false;
}

function selectSdCandidate(path) {
  state.sdSelected = path;
  document.querySelectorAll(".sd-card-option").forEach((el) => {
    el.classList.toggle("selected", el.dataset.path === path);
  });
  $("sd-copy-btn").disabled = false;
}

async function startSdCopy() {
  if (!state.sdSelected) return;
  const btn = $("sd-copy-btn");
  btn.disabled = true;
  btn.textContent = "Copying…";
  $("sd-progress-area").hidden = false;
  $("sd-done-area").hidden = true;
  $("sd-progress-fill").style.width = "0%";
  $("sd-progress-text").textContent = "Starting copy…";
  await api("/api/sdcards/deploy", {
    method: "POST",
    body: JSON.stringify({ mount: state.sdSelected }),
  });
  if (state.sdPollHandle) clearInterval(state.sdPollHandle);
  state.sdPollHandle = setInterval(pollSdProgress, 800);
}

async function pollSdProgress() {
  let snap;
  try {
    snap = await api("/api/sdcards/deploy/status");
  } catch (err) {
    return;
  }
  const pct = snap.total ? (snap.copied + snap.skipped + snap.failed) / snap.total * 100 : 0;
  $("sd-progress-fill").style.width = `${pct}%`;
  if (snap.state === "copying") {
    const done = snap.copied + snap.skipped + snap.failed;
    const parts = [`Copying ${done} of ${snap.total}`];
    if (snap.current) parts.push(`now: ${snap.current}`);
    $("sd-progress-text").textContent = parts.join(" — ");
  } else if (snap.state === "done") {
    clearInterval(state.sdPollHandle);
    state.sdPollHandle = null;
    $("sd-progress-text").textContent = snap.message || "Done.";
    $("sd-copy-btn").hidden = true;
    $("sd-done-area").hidden = false;
    $("sd-done-text").textContent =
      `✓ ${snap.message || `Copied ${snap.copied} games.`}`;
    renderFinishSteps();
  } else if (snap.state === "error") {
    clearInterval(state.sdPollHandle);
    state.sdPollHandle = null;
    $("sd-progress-text").textContent = `Problem: ${snap.message || "copy failed"}.`;
    $("sd-copy-btn").hidden = false;
    $("sd-copy-btn").disabled = false;
    $("sd-copy-btn").textContent = "Try again";
  }
}

function detectClientOS() {
  const p = (navigator.userAgentData?.platform || navigator.platform || "").toLowerCase();
  if (p.includes("mac")) return "mac";
  if (p.includes("win")) return "win";
  if (p.includes("linux") || p.includes("chrome os") || p.includes("cros")) return "linux";
  return "other";
}

function ejectInstructions(os) {
  switch (os) {
    case "win":
      return (
        "On your computer, open <strong>File Explorer</strong>, right-click the " +
        "SD card in the left column, and choose <strong>Eject</strong>. Wait for " +
        "the safe-to-remove message before pulling the card out."
      );
    case "mac":
      return (
        "In <strong>Finder</strong>, click the eject arrow next to the SD card name " +
        "in the left column, or drag the card icon from your desktop to the Trash " +
        "(it turns into an Eject icon). Wait for it to disappear before unplugging."
      );
    case "linux":
      return (
        "In your file manager, click the eject arrow next to the SD card, or run " +
        "<code>sync &amp;&amp; udisksctl unmount -b /dev/&lt;your-card&gt;</code>. " +
        "Wait for the 'safe to remove' message before pulling the card out."
      );
    default:
      return (
        "Safely eject the SD card from your computer before you unplug it " +
        "(look for an 'Eject' option next to the card)."
      );
  }
}

function refreshInstructions(naming) {
  switch (naming) {
    case "miyoo_onion":
      return (
        "Put the SD card back in your Miyoo Mini Plus and turn it on. " +
        "If your new games don't show up, open <strong>Options → Refresh Roms</strong> " +
        "from the main menu. OnionOS will scan and add them."
      );
    case "miyoo_stock":
      return (
        "Put the SD card back in your Miyoo Mini and turn it on. The stock system " +
        "picks up new games automatically — scroll through each console list to see them."
      );
    case "retroarch":
      return (
        "In RetroArch, go to <strong>Import Content → Scan Directory</strong>, " +
        "point it at your card's roms folder, and wait for it to finish. Your new " +
        "games will appear in the console playlists."
      );
    case "es_de":
      return (
        "Start EmulationStation-DE. If your new games don't show up, go to " +
        "<strong>Main Menu → Other Settings → Rescan ROM Directory</strong>."
      );
    default:
      return "Put the SD card back in your handheld and turn it on.";
  }
}

function renderFinishSteps() {
  const ol = $("finish-list");
  if (!ol) return;
  const os = detectClientOS();
  const naming = state.config.naming_convention || "miyoo_onion";
  const steps = [
    `<strong>Eject safely.</strong> ${ejectInstructions(os)}`,
    `<strong>Plug into your handheld.</strong> ${refreshInstructions(naming)}`,
  ];
  ol.innerHTML = steps.map((s) => `<li>${s}</li>`).join("");
}

async function resumeExistingSession() {
  const snap = await api("/api/session/resume", { method: "POST" });
  state.status = snap;
  $("resume-banner").hidden = true;
  showPanel("session-panel");
  renderStatus();
  startPolling();
  if (!state.config.auto_open_next && snap.current) {
    openCurrent();
  }
}

async function discardExistingSession() {
  if (!confirm("Throw away your saved progress and start fresh?")) return;
  await api("/api/session/discard", { method: "POST" });
  $("resume-banner").hidden = true;
}

async function checkForPriorSession() {
  let status;
  try {
    status = await api("/api/session/status");
  } catch (_err) {
    return;
  }
  if (status.active) {
    state.status = status;
    showPanel("session-panel");
    renderStatus();
    startPolling();
    return;
  }
  let pending;
  try {
    pending = await api("/api/session/pending");
  } catch (_err) {
    return;
  }
  if (!pending.pending) return;
  const consoleLabels = (pending.consoles || [])
    .map((k) => state.consoles[k]?.short_name || k)
    .join(", ");
  const msg =
    `You saved ${pending.done} of ${pending.total} games` +
    (consoleLabels ? ` (${consoleLabels})` : "") +
    `. ${pending.remaining} to go.`;
  $("resume-summary").textContent = msg;
  $("resume-banner").hidden = false;
}

function wire() {
  $("save-config-btn").addEventListener("click", saveConfig);
  $("toggle-advanced").addEventListener("click", toggleAdvanced);
  $("preset-classic-six").addEventListener("click", applyClassicSix);
  $("preset-clear").addEventListener("click", () => selectOnly([]));
  $("start-btn").addEventListener("click", startSession);
  $("open-btn").addEventListener("click", openCurrent);
  $("skip-btn").addEventListener("click", skipCurrent);
  $("stop-btn").addEventListener("click", stopSession);
  $("restart-btn").addEventListener("click", restart);
  $("resume-btn").addEventListener("click", resumeExistingSession);
  $("discard-btn").addEventListener("click", discardExistingSession);
  $("sd-from-setup-btn").addEventListener("click", openSdPanel);
  $("sd-from-done-btn").addEventListener("click", openSdPanel);
  $("sd-back-btn").addEventListener("click", closeSdPanel);
  $("sd-scan-btn").addEventListener("click", scanSdCards);
  $("sd-copy-btn").addEventListener("click", startSdCopy);
  $("sd-done-btn").addEventListener("click", closeSdPanel);
  $("notify-toggle").addEventListener("change", (e) => {
    state.soundsEnabled = e.target.checked;
  });
  $("toggle-harvest").addEventListener("click", toggleHarvestPanel);
  $("harvest-save-btn").addEventListener("click", saveHarvestedIds);
  $("harvest-close-btn").addEventListener("click", toggleHarvestPanel);
  $("stuck-open-settings").addEventListener("click", openSettingsFromStuckNudge);
  $("toggle-help").addEventListener("click", toggleHelpPanel);
  $("help-close-btn").addEventListener("click", toggleHelpPanel);
}

const HARVEST_SNIPPET =
  "(function(){" +
    "var anchors=document.querySelectorAll('a[href*=\"/vault/\"]');" +
    "var seen={},pairs=[];" +
    "anchors.forEach(function(a){" +
      "var m=(a.getAttribute('href')||'').match(/^\\/vault\\/(\\d+)/);" +
      "if(!m)return;" +
      "var title=(a.textContent||'').trim();" +
      "if(!title||seen[m[1]])return;" +
      "seen[m[1]]=true;" +
      "pairs.push({title:title,vimm_id:parseInt(m[1],10)});" +
    "});" +
    "var sys=(location.pathname.match(/^\\/vault\\/([A-Za-z0-9]+)/)||[])[1]||'';" +
    "var out=JSON.stringify({system:sys,pairs:pairs},null,2);" +
    "function done(msg){alert(msg);}" +
    "if(navigator.clipboard&&navigator.clipboard.writeText){" +
      "navigator.clipboard.writeText(out).then(" +
        "function(){done('EasyVimm: copied '+pairs.length+' game IDs to your clipboard. Paste them into EasyVimm.');}," +
        "function(){window.prompt('Copy this JSON:',out);}" +
      ");" +
    "}else{window.prompt('Copy this JSON:',out);}" +
  "})();";

function installBookmarklet() {
  const el = $("harvest-bookmarklet");
  if (!el) return;
  el.href = "javascript:" + encodeURIComponent(HARVEST_SNIPPET);
  el.addEventListener("click", (e) => {
    e.preventDefault();
    alert(
      "Drag this link up to your bookmarks bar instead of clicking it. " +
      "Then open a Vimm vault page and click the bookmark.",
    );
  });
}

function toggleHarvestPanel() {
  const panel = $("harvest-panel");
  const btn = $("toggle-harvest");
  panel.hidden = !panel.hidden;
  btn.textContent = panel.hidden
    ? "Teach EasyVimm the exact Vimm pages →"
    : "Hide this";
}

function toggleHelpPanel() {
  const panel = $("help-panel");
  const btn = $("toggle-help");
  panel.hidden = !panel.hidden;
  btn.textContent = panel.hidden ? "Open the help guide →" : "Close the help guide";
  if (!panel.hidden) {
    const p = $("help-downloads-path");
    if (p) p.textContent = state.config.downloads_folder || "your Downloads folder";
  }
}

async function saveHarvestedIds() {
  const raw = ($("harvest-input").value || "").trim();
  const result = $("harvest-result");
  result.hidden = true;
  if (!raw) {
    return;
  }
  let payload;
  try {
    payload = JSON.parse(raw);
  } catch (err) {
    result.textContent = `That doesn't look like JSON: ${err.message}`;
    result.hidden = false;
    return;
  }
  try {
    const resp = await api("/api/catalog/merge", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    const per = Object.entries(resp.by_console || {})
      .map(([k, v]) => `${k}: ${v.matched} of ${v.total}`)
      .join(" · ") || "no consoles matched";
    result.textContent =
      `Saved ${resp.matched} IDs. ${per}.` +
      (resp.unmatched_consoles?.length
        ? ` Unknown system: ${resp.unmatched_consoles.join(", ")}.`
        : "");
    result.hidden = false;
    $("harvest-input").value = "";
    await loadConsoles();
  } catch (err) {
    result.textContent = `Couldn't save: ${err.message}`;
    result.hidden = false;
  }
}

(async function init() {
  wire();
  await loadConfig();
  await loadConsoles();
  installBookmarklet();
  await checkForPriorSession();
})();
