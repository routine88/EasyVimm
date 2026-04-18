const state = {
  consoles: {},
  selected: new Set(),
  config: {},
  status: null,
  pollHandle: null,
  sdCandidates: [],
  sdSelected: null,
  sdPollHandle: null,
};

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
  const entries = Object.entries(state.consoles).sort((a, b) =>
    a[1].display_name.localeCompare(b[1].display_name),
  );
  for (const [key, meta] of entries) {
    const card = document.createElement("div");
    card.className = "console-card";
    card.dataset.key = key;
    const sizeHint = meta.avg_rom_mb
      ? ` · ~${formatSize(meta.game_count * meta.avg_rom_mb)}`
      : "";
    card.innerHTML = `
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
    `${classicEst.games} games · about ${formatSize(classicEst.mb)}`;

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
  el.textContent = `Picked: ${consoles} — ${est.games} games, about ${formatSize(est.mb)}.`;
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
  renderStatus();
  startPolling();
  if (!state.config.auto_open_next && state.status.current) {
    openCurrent();
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
    if (advanced && state.config.auto_open_next && next.current) {
      await fetch("/api/session/open_current", { method: "POST" });
    }
    if (!next.active) {
      clearInterval(state.pollHandle);
      state.pollHandle = null;
      showDone();
    }
  } catch (err) {
    console.warn("poll failed", err);
  }
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
      `✓ ${snap.message || `Copied ${snap.copied} games.`} You can safely eject your SD card.`;
  } else if (snap.state === "error") {
    clearInterval(state.sdPollHandle);
    state.sdPollHandle = null;
    $("sd-progress-text").textContent = `Problem: ${snap.message || "copy failed"}.`;
    $("sd-copy-btn").hidden = false;
    $("sd-copy-btn").disabled = false;
    $("sd-copy-btn").textContent = "Try again";
  }
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
  $("sd-from-setup-btn").addEventListener("click", openSdPanel);
  $("sd-from-done-btn").addEventListener("click", openSdPanel);
  $("sd-back-btn").addEventListener("click", closeSdPanel);
  $("sd-scan-btn").addEventListener("click", scanSdCards);
  $("sd-copy-btn").addEventListener("click", startSdCopy);
  $("sd-done-btn").addEventListener("click", closeSdPanel);
}

(async function init() {
  wire();
  await loadConfig();
  await loadConsoles();
})();
