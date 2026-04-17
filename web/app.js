const state = {
  consoles: {},
  selected: new Set(),
  config: {},
  status: null,
  pollHandle: null,
  lastFiledCount: 0,
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
    card.innerHTML = `
      <div class="name">${meta.display_name}</div>
      <div class="count">${meta.game_count} curated games</div>
    `;
    card.addEventListener("click", () => toggleConsole(key, card));
    grid.appendChild(card);
  }
}

function toggleConsole(key, card) {
  if (state.selected.has(key)) {
    state.selected.delete(key);
    card.classList.remove("selected");
  } else {
    state.selected.add(key);
    card.classList.add("selected");
  }
}

async function startSession() {
  if (state.selected.size === 0) {
    alert("Pick at least one console.");
    return;
  }
  const consoles = Array.from(state.selected);
  state.status = await api("/api/session/start", {
    method: "POST",
    body: JSON.stringify({ consoles }),
  });
  state.lastFiledCount = 0;
  $("setup-panel").hidden = true;
  $("done-panel").hidden = true;
  $("session-panel").hidden = false;
  renderStatus();
  startPolling();
  if (state.config.auto_open_next && state.status.current) {
    // Server already opened it; no-op.
  } else if (state.status.current) {
    openCurrent();
  }
}

async function openCurrent() {
  const snap = state.status;
  if (!snap || !snap.current) return;
  // window.open inside a user gesture works without popup blocker.
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
  if (!confirm("Stop the current session?")) return;
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
      // ROM was filed in the background; if user wants auto-open, fetch next page.
      if (state.config.auto_open_next && next.current) {
        // Browsers block window.open outside user gestures, so we rely on
        // the server-side webbrowser.open instead.
        await fetch("/api/session/open_current", { method: "POST" });
      }
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
  $("progress-text").textContent = `${done} of ${total} processed · ${snap.remaining} remaining`;
  if (snap.current) {
    $("current-console").textContent = snap.current.console_display;
    $("current-rank").textContent = `#${snap.current.rank} on the curated list`;
    $("current-title").textContent = snap.current.title;
  } else {
    $("current-console").textContent = "—";
    $("current-rank").textContent = "—";
    $("current-title").textContent = "All done!";
  }
  const list = $("history-list");
  list.innerHTML = "";
  for (const h of snap.history.slice().reverse()) {
    const li = document.createElement("li");
    li.className = h.status;
    li.innerHTML = `
      <span><strong>${h.title}</strong> <em>(${h.console})</em></span>
      <span class="status">${h.status}${h.note ? " · " + h.note : ""}</span>
    `;
    list.appendChild(li);
  }
}

function showDone() {
  const snap = state.status;
  $("session-panel").hidden = true;
  $("done-panel").hidden = false;
  if (!snap) return;
  const filed = snap.history.filter((h) => h.status === "filed").length;
  const skipped = snap.history.filter((h) => h.status === "skipped").length;
  const failed = snap.history.filter((h) => h.status === "failed").length;
  $("done-summary").textContent =
    `Filed ${filed} · Skipped ${skipped} · Failed ${failed}.`;
}

function restart() {
  state.selected.clear();
  document.querySelectorAll(".console-card.selected").forEach((c) => c.classList.remove("selected"));
  $("done-panel").hidden = true;
  $("setup-panel").hidden = false;
}

function flash(msg) {
  const original = $("save-config-btn").textContent;
  $("save-config-btn").textContent = msg;
  setTimeout(() => ($("save-config-btn").textContent = original), 1500);
}

function wire() {
  $("save-config-btn").addEventListener("click", saveConfig);
  $("toggle-advanced").addEventListener("click", toggleAdvanced);
  $("start-btn").addEventListener("click", startSession);
  $("open-btn").addEventListener("click", openCurrent);
  $("skip-btn").addEventListener("click", skipCurrent);
  $("stop-btn").addEventListener("click", stopSession);
  $("restart-btn").addEventListener("click", restart);
}

(async function init() {
  wire();
  await loadConfig();
  await loadConsoles();
})();
