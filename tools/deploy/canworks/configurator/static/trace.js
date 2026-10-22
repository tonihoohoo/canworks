// Trace view (canopen-configurator "Trace view", canopen-bus-trace): records
// the bus through the runtime's diagnostics channel, or shows an opened trace
// file. The trace lives on the local server (/api/trace/*); this page asks for
// windows of decoded rows and decimated series, so a reload keeps the trace.
// Loaded after app.js and uses its helpers (el, api, banner, modal, S, ...).
"use strict";

const TRACE_KINDS = [["nmt", "NMT"], ["sync", "SYNC"], ["time", "TIME"], ["emcy", "EMCY"], ["heartbeat", "Heartbeat"],
  ["sdo", "SDO"], ["pdo", "PDO"], ["lss", "LSS"], ["error", "Error"], ["gap", "Gap"], ["other", "Other"],
  ["pgn", "J1939 PGN"], ["claim", "Address claim"], ["request", "Request"], ["ack", "ACK/NACK"], ["tp", "Transport"],
  ["raw", "Raw message"]];
const TRACE_FORMATS = [["pcapng", "pcapng (Wireshark)"], ["candump", "candump log"], ["asc", "Vector ASC"],
  ["blf", "Vector BLF"], ["trc", "PEAK TRC 2.1"], ["csv", "CSV, decoded"]];
const TRACE_STATES = { idle: "not recording", connecting: "connecting…", recording: "recording",
  no_bus: "waiting for the CANopen session", reconnecting: "reconnecting…", stopped: "stopped", error: "stopped",
  ended: "stopped" };
const TRACE_TABS = [["ids", "By identifier"], ["frames", "Chronological"], ["graph", "Graph"], ["sequences", "Sequences"],
  ["trigger", "Trigger"]];
const SPLIT_WIDE = 1280;  // the inspector sits beside the list from this window width, under it below
const SPLIT_PHONE = 640;  // below this the list and the inspector stack on the page instead of sharing its height
const ROW_H = 22;
const MAX_SCROLL_PX = 4000000;
const LANES = 4;
const ZOOM_MIN_US = 100;     // the narrowest graph window
const WHEEL_NOTCH = 1.25;    // graph zoom per wheel notch (about 100 px of scrolling)
const LIST_H = [120, 3000];  // the lists' height the user can drag to
const LANE_H = [80, 1000];   // the height of each graph lane
const COND_TYPES = [["frame", "Frame"], ["emcy", "EMCY"], ["state", "Node state"], ["heartbeat_lost", "Heartbeat lost"],
  ["boot_error", "Boot error"], ["sdo_abort", "SDO abort"], ["signal", "Signal value"], ["bus", "Bus state"],
  ["error_frame", "Error frame"]];
// A J1939 network shows only its kinds and conditions, a CANopen one only its
// own; a plain CAN network the shared kinds and the J1939 network's conditions.
const J1939_KINDS = ["pgn", "claim", "request", "ack", "tp"];
const SHARED_KINDS = ["error", "gap", "other", "raw"];
const J1939_CONDS = ["frame", "signal", "bus", "error_frame"];
function traceJ1939() { return isJ1939(onlineConfig()); }
function traceCanopen() { const n = onlineConfig(); return !isJ1939(n) && !isPlain(n); }
function traceKinds() {
  const j = traceJ1939(), co = traceCanopen();
  return TRACE_KINDS.filter(([k]) => SHARED_KINDS.includes(k) || (J1939_KINDS.includes(k) ? j : co));
}
function condTypes() { return traceCanopen() ? COND_TYPES : COND_TYPES.filter(([k]) => J1939_CONDS.includes(k)); }
const SIGNAL_OPS = [">", "<", "=", "!=", "cross_up", "cross_down", "rising", "falling"];
// Graph series colours, one set per theme (readable on the panel of each).
const SERIES_COLORS = {
  light: ["#1f5fbf", "#b3261e", "#256b2a", "#b25a00", "#6f42c1", "#0b7285", "#7a4a2a", "#b0287a", "#5a5a55", "#6c7a1e"],
  dark: ["#8ab4f8", "#ff8a80", "#81c784", "#ffb74d", "#c7a4ff", "#4dd0e1", "#d7a98c", "#f48fb1", "#b0b0a8", "#d4e157"],
};
function seriesColors() {
  const t = document.documentElement.dataset.theme;
  const dark = t === "dark" || (t !== "light" && window.matchMedia("(prefers-color-scheme: dark)").matches);
  return SERIES_COLORS[dark ? "dark" : "light"];
}

// Whether a recording is on the page that was neither saved nor downloaded.
function traceUnsaved() { return !!(T.st && T.st.frames && T.st.source === "live" && !T.kept); }

// The view's choices; the trace itself is on the server.
const T = {
  tab: "ids", prefs: null, split: 42, inspector: true, filter: {}, timeMode: "rel", follow: true, selected: null, focusSeq: null,
  chosen: [], lane: {}, zoom: null, a: null, b: null, st: null, seq: 0, timer: null,
  range: "all", saveFormat: "pcapng", exportFormat: "candump", capFilters: [], errorFrames: false,
  plots: [], jumpedFrom: null, rowsSeq: 0, lastFrames: -1, lastGeneration: -1, lastGraph: 0, lastIds: 0,
  trigDraft: null, data: {},
};

function stopTrace() {
  clearTimeout(T.timer);
  T.timer = null;
  T.seq++;
  for (const p of T.plots) p.destroy();
  T.plots = [];
  document.querySelector("#editor").classList.remove("wide-view");
}

// An error belongs to the tab or view it came from: a switch clears it.
function clearErrorBanner() {
  if ($("#banner").classList.contains("error")) banner("");
}

function traceT0() { return T.st && T.st.start_us != null ? T.st.start_us : 0; }

function timeText(us) {
  if (us == null) return "";
  if (T.timeMode === "utc") {
    const d = new Date(Math.floor(us / 1000));
    return d.toISOString().slice(11, 23) + String(us % 1000).padStart(3, "0");
  }
  return ((us - traceT0()) / 1e6).toFixed(6);
}

function secText(us) { return us == null ? "" : ((us - traceT0()) / 1e6).toFixed(3) + " s"; }

function download(r) {
  const bytes = Uint8Array.from(atob(r.data), (c) => c.charCodeAt(0));
  const url = URL.createObjectURL(new Blob([bytes], { type: r.content_type }));
  const a = el("a", { href: url, download: r.name });
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 10000);
}

// Recording and the transmit list use the connection in the connection bar
// (connection.js): the runtime with a config, the USB adapter in Commission
// a device, or an adapter on another machine. A runtime that is set up opens
// when recording starts.
function onlineReady() {
  if (S.state && (S.state.commission || connRemote())) return !!S.adapterOn;
  return connIsOn() || (connReady() && !S.runtimeOff);
}

// ---------------------------------------------------------------------------

// The graph's series, cursors and zoom belong to one network's trace.
function dropSeries() {
  T.chosen = [];
  T.picked = false;
  T.lane = {};
  T.data = {};
  T.zoom = null;
  T.a = T.b = null;
}

// The view settings kept on this PC (trace.json): view, split, sort, pane.
async function traceLoadPrefs() {
  if (T.prefs) return T.prefs;
  try { T.prefs = await api("GET", "/api/trace/prefs"); } catch (e) { T.prefs = {}; }
  const p = T.prefs;
  if (p.view) T.tab = p.view;
  if (p.split) T.split = p.split;
  if (typeof p.inspector === "boolean") T.inspector = p.inspector;
  if (p.sort) { TI.sort = p.sort; TI.desc = !!p.sort_desc; }
  if (typeof p.pane_open === "boolean") TX.open = p.pane_open;
  if (p.pane) TX.height = p.pane;
  T.listH = typeof p.list_h === "number" ? p.list_h : null;
  T.laneH = typeof p.lane_h === "number" ? p.lane_h : null;
  traceListHeight();
  return p;
}

function tracePrefs(changes) {
  T.prefs = Object.assign(T.prefs || {}, changes);
  api("POST", "/api/trace/prefs", { prefs: changes }).catch(() => {});
}

// Commission a device decodes with the Nodes tab's EDS files: {node: path}.
function commissionEds() {
  if (!(S.state && S.state.commission)) return null;
  const out = Object.assign({}, S.onlineEds || {});
  for (const [id, d] of Object.entries(typeof commNodes === "function" ? commNodes() : {})) if (d && d.eds_path) out[id] = d.eds_path;
  return out;
}

function renderTrace(view) {
  document.querySelector("#editor").classList.add("wide-view");
  if (traceWinElsewhere()) { renderTraceElsewhere(view); return; }
  if (!T.prefs) {
    view.append(el("h2", null, "Trace"), el("p", { class: "muted" }, "Loading…"));
    traceLoadPrefs().then(() => { if (S.view === "trace" && view.isConnected) { view.replaceChildren(); renderTrace(view); } });
    return;
  }
  const net = onlineNetwork();
  if (T.net !== undefined && T.net !== net) {
    dropSeries();
    T.trigDraft = null;
    clearErrorBanner();
  }
  if (!traceCanopen() && T.tab === "sequences") T.tab = "frames";
  T.net = net;
  // The Nodes tab's EDS files changed since the trace decoded with them: decode again.
  const eds = JSON.stringify(commissionEds() || {});
  if (T.edsSent !== undefined && T.edsSent !== eds) setTimeout(decodingRefresh);
  T.edsSent = eds;
  const fileInput = el("input", { type: "file", accept: ".pcapng,.pcap,.log,.asc", dataset: { trace: "open-input" } });
  fileInput.addEventListener("change", () => {
    const f = fileInput.files[0];
    fileInput.value = "";
    if (f) traceOpen(f);
  });
  const timeMode = el("div", { class: "segmented", role: "group", "aria-label": "Time" },
    [["rel", "Relative"], ["utc", "UTC"]].map(([v, l]) => el("button", { type: "button", "aria-pressed": String(T.timeMode === v),
      dataset: { traceTime: v }, onclick: () => {
        T.timeMode = v;
        for (const b of timeMode.children) b.setAttribute("aria-pressed", String(b.dataset.traceTime === v));
        renderTraceTab();
      } }, l)));
  const tabList = TRACE_TABS.filter(([k]) => !(k === "sequences" && !traceCanopen()));
  view.append(
    el("h2", null, "Trace"),
    traceSourceSlot(),
    el("div", { class: "toolbar trace-toolbar" },
      el("button", { type: "button", class: "primary", dataset: { trace: "start-stop" }, onclick: traceStartStop }, "Start"),
      el("button", { type: "button", dataset: { trace: "clear" }, onclick: traceClear }, "Clear"),
      el("label", { class: "file-button", title: "Open a pcapng, candump log or Vector ASC file" }, "Open…", fileInput),
      saveMenu(), captureSettings(), decodingMenu(), timeMode, traceWinButton()),
    el("div", { id: "trace-stats", class: "trace-stats", dataset: { trace: "stats" } }),
    el("div", { class: "trace-tabrow" },
      tabs(tabList, T.tab, (v) => traceShowTab(v), { class: "segmented trace-tabs", tab: "", dataset: "traceTab", panel: "trace-tab", label: "Trace views" }),
      filtersMenu()),
    el("div", { id: "trace-tab", role: "tabpanel", "aria-labelledby": "trace-tab-tab-" + T.tab }),
    txPane());
  T.lastFrames = -1;
  T.lastGeneration = -1;
  const seq = T.seq;
  pollTrace(seq, true);
}

// The view tabs: By identifier, Chronological, Graph, Sequences, Trigger.
function traceShowTab(v) {
  T.tab = v;
  clearErrorBanner();
  tracePrefs({ view: v });
  if (S.view !== "trace") { showView("trace"); return; }
  renderTraceTab();
}

function closeOnOutside(menu) {
  document.addEventListener("click", (e) => { if (menu.open && !menu.contains(e.target)) menu.open = false; });
  menu.addEventListener("keydown", (e) => { if (e.key === "Escape" && menu.open) { menu.open = false; menu.querySelector("summary").focus(); } });
  return menu;
}

// Save ▾: to the traces folder on this PC, or a download; each with its format, and the range.
function saveMenu() {
  const fmtSelect = (key, list, data) => {
    const s = el("select", { dataset: { trace: data }, "aria-label": data === "save-format" ? "Format of the saved file" : "Format of the downloaded file" },
      list.map(([v, l]) => el("option", { value: v, selected: T[key] === v }, l)));
    s.onchange = () => { T[key] = s.value; };
    return s;
  };
  const range = el("select", { dataset: { trace: "range" }, "aria-label": "What to save or download" },
    [["all", "Whole trace"], ["view", "Graph zoom"], ["cursors", "Between cursors A and B"]]
      .map(([v, l]) => el("option", { value: v, selected: T.range === v }, l)));
  range.onchange = () => { T.range = range.value; };
  return closeOnOutside(el("details", { class: "menu trace-menu", dataset: { trace: "save-menu" } },
    el("summary", { "aria-haspopup": "true" }, "Save"),
    el("div", { class: "menu-panel", role: "group", "aria-label": "Save the trace" },
      el("label", { class: "menu-label" }, "What", range),
      el("div", { class: "menu-row" }, fmtSelect("saveFormat", TRACE_FORMATS, "save-format"),
        el("button", { type: "button", class: "item", dataset: { trace: "save" }, onclick: traceSave,
          title: "Save the trace in the traces folder on this PC" }, "Save to traces folder")),
      el("div", { class: "menu-row" }, fmtSelect("exportFormat", TRACE_FORMATS.concat([["signals", "Signals CSV"]]), "export-format"),
        el("button", { type: "button", class: "item", dataset: { trace: "export" }, onclick: traceExport,
          title: "Download the trace as a file in the chosen format" }, "Download")))));
}

// Filters ▾: the display filters of By identifier and Chronological.
function filtersMenu() {
  const f = T.filter;
  const offered = traceKinds();
  if (f.kinds) f.kinds = f.kinds.filter((k) => offered.some(([o]) => o === k));
  const changed = () => { updateFilterCount(); traceFilterChanged(); };
  const kinds = el("div", { class: "kind-chips" }, offered.map(([k, label]) => {
    const cb = el("input", { type: "checkbox", checked: (f.kinds || []).includes(k), dataset: { traceKind: k } });
    cb.onchange = () => {
      const set = new Set(f.kinds || []);
      if (cb.checked) set.add(k); else set.delete(k);
      f.kinds = [...set];
      changed();
    };
    return el("label", { class: "chip" }, cb, label);
  }));
  const input = (key, label, width) => {
    const i = el("input", { type: "text", spellcheck: "false", "aria-label": label, placeholder: label, dataset: { traceFilter: key } });
    i.style.width = width;
    i.value = f[key] != null ? f[key] : "";
    i.addEventListener("change", () => { f[key] = i.value.trim(); changed(); });
    return i;
  };
  const dir = el("select", { "aria-label": "Direction", dataset: { traceFilter: "dir" } },
    [["any", "Rx and Tx"], ["rx", "Rx only"], ["tx", "Tx only"]].map(([v, l]) => el("option", { value: v, selected: (f.dir || "any") === v }, l)));
  dir.onchange = () => { f.dir = dir.value; changed(); };
  const menu = closeOnOutside(el("details", { class: "menu trace-menu trace-filters-menu", dataset: { trace: "filters" } },
    el("summary", { "aria-haspopup": "true", id: "trace-filter-summary" }, "Filters"),
    el("div", { class: "menu-panel trace-filters" },
      el("div", { class: "row" }, input("nodes", "Nodes: 2, 23", "13ch"), input("id_from", "ID from", "9ch"),
        input("id_to", "ID to", "9ch"), dir, input("text", "Search text", "16ch")),
      kinds,
      el("p", { class: "hint" }, "Display filters never change what is recorded."),
      el("div", { class: "toolbar" }, el("button", { type: "button", dataset: { trace: "clear-filters" }, onclick: () => {
        T.filter = {};
        const fresh = filtersMenu();
        fresh.open = true;
        menu.replaceWith(fresh);
        traceFilterChanged();
      } }, "Clear filters")))));
  setTimeout(updateFilterCount);
  return menu;
}

function filterCount() {
  const f = T.filter;
  return [f.nodes, f.id_from || f.id_to, f.dir && f.dir !== "any", f.text, f.kinds && f.kinds.length].filter(Boolean).length;
}

function updateFilterCount() {
  const s = $("#trace-filter-summary");
  if (!s) return;
  const n = filterCount();
  s.textContent = n ? `Filters (${n})` : "Filters";
  // The fields follow T.filter when a row's Show frames changed it.
  for (const i of document.querySelectorAll("[data-trace-filter]")) {
    const k = i.dataset.traceFilter;
    const v = k === "dir" ? (T.filter.dir || "any") : (T.filter[k] != null ? T.filter[k] : "");
    if (document.activeElement !== i && i.value !== v) i.value = v;
  }
}

function traceFilterChanged() {
  if (T.tab === "frames") refreshRows(false, true);
  else if (T.tab === "ids") { idsReset(); idsPoll(++TI.seq, false); }
  showTraceHeader(T.st);
}

function captureSettings() {
  const list = el("div", { class: "cap-filters" });
  const draw = () => {
    list.replaceChildren(...T.capFilters.map((f, k) => {
      const id = el("input", { type: "text", class: "index", value: f.id, "aria-label": "Filter ID", dataset: { trace: "cap-id" } });
      const mask = el("input", { type: "text", class: "index", value: f.mask, "aria-label": "Filter mask", dataset: { trace: "cap-mask" } });
      id.onchange = () => { f.id = id.value.trim(); };
      mask.onchange = () => { f.mask = mask.value.trim(); };
      return el("div", { class: "row" }, "ID", id, "mask", mask,
        el("button", { type: "button", title: "Remove", "aria-label": "Remove filter",
          onclick: () => { T.capFilters.splice(k, 1); draw(); } }, "✕"));
    }));
  };
  draw();
  const errs = el("input", { type: "checkbox", checked: T.errorFrames, dataset: { trace: "error-frames" } });
  errs.onchange = () => { T.errorFrames = errs.checked; };
  return closeOnOutside(el("details", { class: "menu trace-menu", dataset: { trace: "capture" } },
    el("summary", { "aria-haspopup": "true" }, "Capture"), el("div", { class: "menu-panel trace-capture" },
    el("p", { class: "hint" }, "Applied from the next Start: only frames whose ID matches one filter (ID and mask, e.g. 0x180 and 0x780 for all TPDO1s) are recorded. No filter records everything. Display filters never change what is recorded."),
    list,
    el("div", { class: "toolbar" },
      el("button", { type: "button", dataset: { trace: "add-filter" }, onclick: () => {
        if (T.capFilters.length >= 16) return banner("At most 16 capture filters.", true);
        T.capFilters.push({ id: "0x180", mask: "0x780" });
        draw();
      } }, "Add filter"),
      el("label", { class: "check inline" }, errs, " Record error frames (the adapter must report them)")))));
}

async function pollTrace(seq, first) {
  let st = null;
  try { st = await api("GET", "/api/trace/state"); } catch (e) { if (seq === T.seq) banner(e.message, true); }
  if (seq !== T.seq || S.view !== "trace") return;
  if (st) {
    const prev = T.st;
    T.st = st;
    showTraceHeader(st);
    const changed = st.generation !== T.lastGeneration || st.frames !== T.lastFrames;
    const now = Date.now();
    if (first || !prev || st.generation !== T.lastGeneration) {
      if (st.generation !== T.lastGeneration && !first) { T.selected = null; T.zoom = null; T.a = T.b = null; }
      if (prev && (prev.network || null) !== (st.network || null)) dropSeries();
      renderTraceTab();
    } else if (changed) {
      if (T.tab === "frames" && T.follow) refreshRows(true);
      else if (T.tab === "frames") updateScroll();
      if (T.tab === "graph" && !T.zoom && now - T.lastGraph > 1000) loadGraph();
    }
    if (T.tab === "trigger" && prev && JSON.stringify(prev.recording.hits) !== JSON.stringify(st.recording.hits)) renderTriggerStatus();
    T.lastGeneration = st.generation;
    T.lastFrames = st.frames;
  }
  T.timer = setTimeout(() => pollTrace(seq, false), st && st.recording.running ? 500 : 1500);
}

// The place for the trace's source and its notes, under the title.
function traceSourceSlot() {
  const slot = noticeSlot({ id: "trace-source" });
  stateBars(slot, "info", "Loading…");
  return slot;
}

// Whose kernel dropped frames: the kernel that reads the bus, the PLC's on
// a runtime, the adapter machine's on an adapter on another machine.
function traceDropsBy(st) {
  const host = st.meta && st.meta.connection === "adapter" ? st.meta.adapter_host : null;
  return host ? `the adapter machine's kernel (${host})` : "the PLC's kernel";
}

function showTraceHeader(st) {
  const src = $("#trace-source");
  const rec = st.recording;
  let text;
  let kind = "info";
  if (st.source === "live") {
    kind = "done";
    const via = st.meta && st.meta.connection === "adapter"
      ? (st.meta.adapter_host ? `the adapter on ${st.meta.adapter_host}` : `the USB adapter${st.meta.interface ? " " + st.meta.interface : ""}`) +
      (st.summary && st.summary.bitrate ? ` at ${st.summary.bitrate / 1000} kbit/s` : "")
      : (S.online.host || "the runtime");
    text = `Live trace from ${via}${st.network ? ", network " + st.network : ""}: ${TRACE_STATES[rec.state] || rec.state}`;
    if (rec.state === "ended") text = `Live trace from ${via}${st.network ? ", network " + st.network : ""}: recording stopped because the ${rec.message || "connection ended"}`;
    else if (rec.message) text += ` (${rec.message})`;
    if (rec.state === "error" || rec.state === "ended") kind = "error";
  } else if (st.source) {
    text = `File ${st.source}` + (st.network ? `, decoded with network ${st.network}` : "");
  } else {
    text = "No trace yet. Press Start, or open a trace file.";
  }
  // The trace's source as a bar under the title, its notes as bars with it (consistent-message-bars).
  const notes = [];
  if (!rec.running && !onlineReady()) {
    const commission = !!(S.state && S.state.commission);
    notes.push(noteBar("info",
      (connSimOn() ? "Recording needs a connection to the runtime; the connection bar is connected to a standalone simulator. "
        : commission ? `Recording needs the ${connRemote() ? "adapter" : "USB adapter"} connection: connect with Connect… in the connection bar above. `
        : diagConfig() ? "Recording needs the connection to the runtime: connect with Connect… in the connection bar above. "
        : "Recording needs online access: turn it on in Configure → Project → Online access, save and upload. ") +
      "Opening, viewing and exporting trace files works without it.", { trace: "online-hint" }));
  }
  for (const w of st.warnings || []) notes.push(noteBar("warning", humanise(w), { trace: "warning" }));
  const trimmed = rec.trimmed || 0;
  if (trimmed) notes.push(noteBar("info",
    `Single trigger: the trace holds the pre/post window around the hit; ${trimmed.toLocaleString()} frames outside it were removed.`, { trace: "trimmed" }));
  if (st.dropped) notes.push(noteBar("warning",
    `The trace holds the newest ${Number(st.frames || 0).toLocaleString()} frames (at most ${Number(st.limit || 0).toLocaleString()}; ` +
    `past that the oldest tenth goes at once); ${Number(st.dropped).toLocaleString()} older frames were dropped.`, { trace: "dropped" }));
  stateBars(src, kind, text, notes);
  const sm = st.summary;
  const dur = sm.first_us != null ? (sm.last_us - sm.first_us) / 1e6 : 0;
  const bits = [`${sm.frames.toLocaleString()} frames`, `${dur.toFixed(1)} s`,
    rec.running ? `${Math.round(sm.rate)} frames/s` : null,
    rec.running && sm.load != null ? `bus load ${sm.load.toFixed(1)} % (estimate)` : null,
    sm.bitrate ? `${sm.bitrate / 1000} kbit/s` : null,
    `${sm.error_frames} error frames`,
    sm.lost ? `${sm.lost} lost` : null, sm.kernel_drops ? `${sm.kernel_drops} dropped by ${traceDropsBy(st)}` : null,
    st.trigger_text ? `trigger: ${st.trigger_text}${rec.hits && rec.hits.length ? ` (${rec.hits.length} hit${rec.hits.length === 1 ? "" : "s"})` : ""}` : null];
  if (filterCount() && (T.tab === "frames" || T.tab === "ids") && T.total != null && T.tab === "frames") bits.push(`showing ${T.total.toLocaleString()} of ${sm.frames.toLocaleString()}`);
  else if (filterCount() && T.tab === "ids") bits.push(`showing ${TI.rows.size} identifier${TI.rows.size === 1 ? "" : "s"} (filtered)`);
  $("#trace-stats").textContent = bits.filter(Boolean).join(" · ");
  const ss = document.querySelector("[data-trace=start-stop]");
  if (ss) {
    ss.textContent = rec.running ? "Stop" : "Start";
    ss.classList.toggle("primary", !rec.running);
    ss.dataset.running = String(!!rec.running);
  }
  for (const k of ["save", "export"]) Icons.setDisabled(document.querySelector(`[data-trace=${k}]`), !st.frames && "Nothing recorded yet.");
}

function renderTraceTab() {
  const list = document.querySelector(".trace-tabs");
  if (list) selectTab(list, T.tab, "traceTab");
  const box = $("#trace-tab");
  if (!box) return;
  box.setAttribute("aria-labelledby", "trace-tab-tab-" + T.tab);
  for (const p of T.plots) p.destroy();
  T.plots = [];
  idsStop();
  box.replaceChildren();
  box.classList.toggle("trace-split-host", T.tab === "frames" || T.tab === "ids");
  if (T.tab === "frames") renderFrames(traceSplit(box));
  else if (T.tab === "ids") renderIds(traceSplit(box));
  else if (T.tab === "graph") renderGraph(box);
  else if (T.tab === "sequences") fxRenderSequences(box);
  else renderTrigger(box);
}

// The list or table beside (wide) or over (narrow) the inspector, with a
// split the user drags or moves with the arrow keys (canopen-configurator:
// "Docked inspector and transmit pane"). The inspector closes with its ✕ or
// Esc and leaves a rail that opens it again ("Close and reopen the
// inspector"). Returns the view's half.
function traceSplit(box) {
  const view = el("div", { class: "trace-split-view" });
  const body = el("div", { id: "trace-inspector", class: "fx-host trace-insp-body", tabindex: "-1", dataset: { trace: "inspector" } },
    el("p", { class: "muted" }, "Select a frame to see what every bit of it means."));
  const close = el("button", { type: "button", class: "small icon-button trace-insp-close", dataset: { trace: "inspector-toggle" },
    title: "Close the inspector (Esc)", "aria-label": "Close the inspector", onclick: () => traceInspector(false, true) }, "✕");
  const pane = el("section", { class: "trace-split-insp", "aria-label": "Frame inspector", dataset: { trace: "inspector-pane" } },
    el("div", { class: "trace-insp-head" }, el("h3", null, "Inspector"), close), body);
  const rail = el("button", { type: "button", class: "trace-insp-rail", dataset: { trace: "inspector-rail" }, "aria-expanded": "false",
    title: "Open the inspector", onclick: () => { T.inspWanted = true; if (T.inspector) apply(); else traceInspector(true); } }, el("span", null, "Inspector"));
  const handle = el("div", { class: "trace-split-handle", role: "separator", tabindex: "0", "aria-label": "Resize the inspector",
    "aria-orientation": "vertical", "aria-valuemin": "15", "aria-valuemax": "85", "aria-valuenow": String(T.split), dataset: { trace: "split" } });
  const split = el("div", { class: "trace-split", dataset: { trace: "split-box" } }, view, handle, pane, rail);
  const apply = () => {
    // Closed until a frame is picked by click or Enter (or the rail is pressed): the list keeps the width.
    split.classList.toggle("no-insp", !T.inspector || !T.inspWanted);
    split.style.setProperty("--insp", T.split + "%");
    handle.setAttribute("aria-valuenow", String(Math.round(T.split)));
    handle.setAttribute("aria-orientation", window.innerWidth >= SPLIT_WIDE ? "vertical" : "horizontal");
    traceFitSplit();
  };
  T.applySplit = apply;
  pane.addEventListener("keydown", (e) => {
    if (e.key !== "Escape" || e.target.closest("input, select, textarea, details.menu[open]")) return;
    e.preventDefault();
    traceInspector(false, true);
  });
  const set = (v) => { T.split = Math.max(15, Math.min(85, Math.round(v))); apply(); };
  let saveTimer = null;
  const save = () => { clearTimeout(saveTimer); saveTimer = setTimeout(() => tracePrefs({ split: T.split }), 300); };
  handle.addEventListener("pointerdown", (e) => {
    e.preventDefault();
    handle.setPointerCapture(e.pointerId);
    const r = split.getBoundingClientRect();
    const move = (ev) => {
      const wide = window.innerWidth >= SPLIT_WIDE;
      set(wide ? (r.right - ev.clientX) / r.width * 100 : (r.bottom - ev.clientY) / r.height * 100);
    };
    const up = () => { handle.removeEventListener("pointermove", move); handle.removeEventListener("pointerup", up); save(); };
    handle.addEventListener("pointermove", move);
    handle.addEventListener("pointerup", up);
  });
  handle.addEventListener("keydown", (e) => {
    const wide = window.innerWidth >= SPLIT_WIDE;
    const d = { ArrowLeft: wide ? 5 : 0, ArrowRight: wide ? -5 : 0, ArrowUp: wide ? 0 : 5, ArrowDown: wide ? 0 : -5, Home: 85 - T.split, End: 15 - T.split }[e.key];
    if (d === undefined || d === 0) return;
    e.preventDefault();
    set(T.split + d);
    save();
  });
  box.append(split);
  apply();
  return view;
}

// Opens or closes the docked inspector; `back` puts the focus on the list
// that holds the selected row (Esc and ✕) or, opening, on the inspector.
function traceInspector(open, back) {
  if (T.inspector === open) return;
  T.inspector = open;
  tracePrefs({ inspector: open });
  if (T.applySplit) T.applySplit();
  if (open) {
    if (T.selected != null && $("#trace-inspector")) fxInspectSeq(T.selected);
    const c = document.querySelector("[data-trace=inspector-toggle]");
    if (c && back) c.focus({ preventScroll: true });
  } else if (back) {
    const list = $("#trace-list") || $("#ids-grid");
    if (list) list.focus({ preventScroll: true });
  }
}

// Below SPLIT_WIDE the list and the inspector share the window height under
// the split's top, each scrolling on its own; the page scrolls so the split
// starts at the top of the window the first time a frame is picked.
function traceFitSplit() {
  const split = document.querySelector("[data-trace=split-box]");
  if (!split) return;
  const narrow = window.innerWidth < SPLIT_WIDE && window.innerWidth >= SPLIT_PHONE;
  split.classList.toggle("shared-height", narrow);
}

function traceRevealSplit() {
  const split = document.querySelector("[data-trace=split-box]");
  if (!split || !T.inspector) return;
  if (window.innerWidth < SPLIT_PHONE) {
    const insp = $("#trace-inspector");
    if (insp) insp.scrollIntoView({ block: "start" });
    return;
  }
  if (window.innerWidth >= SPLIT_WIDE) return;
  const top = split.getBoundingClientRect().top;
  // Under the sticky header, and under the simulation banner and the message bar while they show.
  let head = parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--header-h")) || 0;
  const b = $("#page-bars");
  if (b && b.offsetParent !== null) head += b.offsetHeight;
  if (top > head + 4 || top < head - 4) window.scrollBy(0, top - head);
}

window.addEventListener("resize", () => { if (T.applySplit) T.applySplit(); });

// Send…: the frame becomes a row of the transmit list; nothing is sent.
function traceSendTo(frame) {
  if (typeof frame === "string") frame = txFromCandump(frame);
  if (S.view !== "trace") showView("trace");
  const r = txAdd(frame, false);
  if (TX.firstSend) {
    TX.firstSend = false;
    banner("Added to the transmit list. Press Send there to put it on the bus.");
  }
  return r;
}

function txFromCandump(text) {
  const [id, rest] = String(text).split("#");
  const rtr = /^R/i.test(rest || "");
  const data = rtr ? "" : (rest || "").replace(/(..)/g, "$1 ").trim().toUpperCase();
  return { id: id.toUpperCase(), ext: id.length > 3, rtr, dlc: rtr ? Number((rest || "").slice(1) || 0) : null, data };
}

// Explain in Frame lab: the trace's explanation of frame `seq`, with its
// network, bit rate and SDO context (canopen-configurator: "Explain in Frame lab").
// From the trace's own window, `tab` is the view there the frame came from.
async function traceExplainInLab(seq, tab) {
  if (TRACE_WINDOW) { traceWinGoto({ type: "goto", kind: "explain", seq, tab: T.tab }); return; }
  let m;
  try { m = await api("POST", "/api/trace/explain", { seq }); } catch (e) { banner(e.message, true); return; }
  FX.lab.fromTrace = { seq, t_us: m.t_us, model: m, candump: m.frame.candump, edited: false, tab: tab || T.tab };
  FX.lab.frame = m.frame.candump;
  FX.lab.built = null;
  if (m.wire && m.wire.bitrate) FX.lab.bitrate = String(m.wire.bitrate);
  showView("framelab");
}

function traceExplainText(text) {
  if (TRACE_WINDOW) { traceWinGoto({ type: "goto", kind: "text", text }); return; }
  FX.lab.fromTrace = null;
  FX.lab.frame = text;
  FX.lab.built = null;
  showView("framelab");
}

// Back to trace: the view the frame came from, with that frame selected.
function traceBackFrom(src) {
  if (traceWinElsewhere()) {
    traceWinPost({ type: "select", src });
    const w = window.open("", TRACE_WINDOW_NAME);
    if (w) w.focus();
    return;
  }
  T.tab = src.tab === "ids" ? "ids" : "frames";
  T.selected = src.seq;
  T.selectedUs = src.t_us;
  T.follow = false;
  showView("trace");
  if (T.tab === "frames") setTimeout(() => refreshRows(false, false, src.t_us));
}

// -- control ----------------------------------------------------------------

function traceStartStop() {
  if (T.st && T.st.recording && T.st.recording.running) traceStop();
  else traceStart();
}

// `again`: the start that waited for the connect panel, with the answer it already had.
async function traceStart(again) {
  let cont = again ? again.cont : false;
  if (!again && T.st && T.st.frames) {
    // A recording of the same network can go on after a gap; another network's cannot.
    const same = T.st.source === "live" && (T.st.network || null) === (onlineNetwork() || null);
    const lost = `The current recording (${T.st.frames.toLocaleString()} frames) is lost unless it was saved to the traces folder or downloaded.`;
    const v = same
      ? await modal(`Continue this trace, or start a new one? Continuing adds the new frames after a gap marker. ${lost.replace("is lost", "is lost with a new trace")}`,
        [["continue", "Continue this trace", true], ["new", "New trace", { danger: true }], ["cancel", "Cancel"]])
      : await modal(`Start a new trace? ${lost}`, [["cancel", "Keep the recording"], ["new", "Start a new trace", { danger: true }]]);
    if (v !== "new" && v !== "continue") return;
    cont = v === "continue";
    if (!cont) T.kept = false;
  }
  if (TRACE_WINDOW) traceWinEnsure();  // the main window opens it and tells this one
  else if (!(S.state && S.state.commission ? connIsOn() : connEnsure() || connIsOn() || connSimOn())) {
    // Not connected: Start opens the connect panel and starts once connected (one-place-navigation).
    T.startOnConnect = { cont };
    openConnect();
    return;
  }
  try {
    T.st = await api("POST", "/api/trace/start", { filters: T.capFilters.map((f) => ({ id: f.id, mask: f.mask })),
      error_frames: T.errorFrames, port: diagPort(), continue: cont, eds: commissionEds() || undefined });
    banner("");
    T.follow = true;
    T.zoom = null;
    T.a = T.b = null;
    T.selected = null;
  } catch (e) {
    banner(e.body && e.body.need === "online" ? e.message : `Trace not started: ${e.message}`, true);
    return;
  }
  restartPoll();
}

async function traceStop() {
  try { T.st = await api("POST", "/api/trace/stop", {}); } catch (e) { banner(e.message, true); }
  restartPoll();
}

async function traceClear() {
  if (T.st && T.st.frames) {
    const v = await modal(`Clear the trace? The recording (${T.st.frames.toLocaleString()} frames) is lost unless it was saved to the traces folder or downloaded.`,
      [["cancel", "Keep the recording"], ["clear", "Clear the trace", { danger: true }]]);
    if (v !== "clear") return;
    T.kept = false;
  }
  try { await api("POST", "/api/trace/clear", {}); } catch (e) { banner(e.message, true); }
  restartPoll();
}

function restartPoll() {
  clearTimeout(T.timer);
  T.seq++;
  pollTrace(T.seq, false);
}

async function traceOpen(file) {
  banner(`Opening ${file.name}…`, "info");
  try {
    // The file as it is (traces can be hundreds of MB); decoded with the saved canworks.json.
    const net = onlineNetwork();  // the network whose nodes decode it
    const eds = commissionEds();
    const res = await fetch("/api/trace/open?name=" + encodeURIComponent(file.name) +
      (net !== null ? "&network=" + encodeURIComponent(net) : "") + (eds ? "&eds=" + encodeURIComponent(JSON.stringify(eds)) : ""), {
      method: "POST", headers: { "X-CANopen-Token": TOKEN, "Content-Type": "application/octet-stream" }, body: file });
    if (!res.ok) {
      let msg = res.statusText;
      try { msg = (await res.json()).error || msg; } catch (e) { /* not JSON */ }
      throw new Error(msg);
    }
    banner(`Opened ${file.name}.`);
    T.zoom = null;
    T.a = T.b = null;
    T.selected = null;
  } catch (e) {
    banner(e.message, true);
  }
  restartPoll();
}

function traceRange() {
  if (T.range === "view") {
    if (!T.zoom) return {};
    return { start_us: Math.floor(T.zoom[0]), end_us: Math.ceil(T.zoom[1]) };
  }
  if (T.range === "cursors") {
    if (T.a == null || T.b == null) throw new Error("Set cursors A and B in the graph first (click, and Shift+click).");
    return { start_us: Math.floor(Math.min(T.a, T.b)), end_us: Math.ceil(Math.max(T.a, T.b)) };
  }
  return {};
}

async function traceSave() {
  try {
    const r = await api("POST", "/api/trace/save", Object.assign({ format: T.saveFormat }, traceRange()));
    T.kept = true;
    banner(`Saved ${r.frames.toLocaleString()} frames to ${r.path}.`);
  } catch (e) { banner(e.message, true); }
}

async function traceExport() {
  try {
    const body = Object.assign({ format: T.exportFormat, keys: T.chosen }, traceRange());
    const r = await api("POST", "/api/trace/export", body);
    download(r);
    T.kept = true;
    banner(`Downloaded ${r.name}.`);
  } catch (e) { banner(e.message, true); }
}

// -- frames -----------------------------------------------------------------

function renderFrames(box) {
  const follow = el("input", { type: "checkbox", checked: T.follow, dataset: { trace: "follow" } });
  follow.onchange = () => { T.follow = follow.checked; if (T.follow) refreshRows(true); };
  const list = el("div", { class: "trace-list", id: "trace-list", tabindex: "0", "aria-label": "Frames" },
    el("div", { class: "trace-rows", id: "trace-rows" }), el("div", { class: "trace-spacer" }));
  list.addEventListener("scroll", () => {
    const atEnd = list.scrollTop + list.clientHeight >= list.scrollHeight - 2;
    if (T.follow !== atEnd && T.st && T.st.recording.running) { T.follow = atEnd; follow.checked = atEnd; }
    requestRows();
  });
  box.append(
    el("div", { class: "toolbar trace-frames-tools" },
      el("label", { class: "check inline", title: "Keep the newest frames in view while recording" }, follow, "Follow"),
      el("span", { class: "muted" }, "Up and down arrows, Page Up, Page Down, Home and End move through the list.")),
    el("div", { class: "trace-head trace-row" }, ["Time", "Dir", "ID", "DLC", "Data", "Name", "Decoded"].map((h) => el("span", null, h))),
    list, listSizeBar(),
    el("div", { class: "toolbar", id: "trace-row-actions" }));
  list.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && T.selectedRow && T.selectedRow.seq === T.selected) { e.preventDefault(); selectRow(T.selectedRow, true); return; }
    const page = Math.max(1, Math.floor(list.clientHeight / ROW_H) - 1);
    const step = { ArrowDown: 1, ArrowUp: -1, PageDown: page, PageUp: -page, Home: -Infinity, End: Infinity }[e.key];
    if (step === undefined) return;
    e.preventDefault();
    T.follow = false;
    follow.checked = false;
    fxMoveSelection(step);
  });
  refreshRows(T.follow && T.st && T.st.recording.running, true, T.follow ? undefined : (T.selectedUs != null ? T.selectedUs : undefined));
}

function filterBody() {
  const f = T.filter;
  const out = {};
  if (f.kinds && f.kinds.length) out.kinds = f.kinds;
  if (f.nodes) out.nodes = f.nodes.split(/[\s,;]+/).filter(Boolean).map(Number).filter((n) => n >= 1 && n <= 127);
  if (f.id_from) out.id_from = f.id_from;
  if (f.id_to) out.id_to = f.id_to;
  if (f.dir && f.dir !== "any") out.dir = f.dir;
  if (f.text) out.text = f.text;
  return out;
}

// Scrolling: the list is as tall as its rows (capped; past the cap the
// scroll position maps proportionally) and draws only the rows in view.
function listGeometry() {
  const list = $("#trace-list");
  const total = T.total || 0;
  const visible = Math.max(1, Math.floor((list.clientHeight - 2) / ROW_H));
  const full = total * ROW_H;
  const height = Math.min(full, MAX_SCROLL_PX);
  return { list, total, visible, full, height };
}

function updateScroll() {
  const g = listGeometry();
  g.list.querySelector(".trace-spacer").style.height = Math.max(0, g.height - g.list.clientHeight) + "px";
}

// The rows in view: the first one and how many pixels of it sit above the
// top edge. Scrolled to the end, the newest row ends at the bottom edge, so
// the list never cuts it (the top row is the one cut instead).
function listWindow() {
  const g = listGeometry();
  const ch = g.list.clientHeight;
  const fit = Math.ceil(ch / ROW_H);
  if (g.full > ch && g.list.scrollTop + ch >= g.list.scrollHeight - 1)
    return { first: Math.max(0, g.total - fit), shift: fit * ROW_H - ch };
  if (g.full <= MAX_SCROLL_PX) return { first: Math.floor(g.list.scrollTop / ROW_H), shift: g.list.scrollTop % ROW_H };
  const span = Math.max(1, g.height - ch);
  return { first: Math.round(g.list.scrollTop / span * Math.max(0, g.total - g.visible)), shift: 0 };
}

function firstRow() { return listWindow().first; }

function scrollToRow(pos) {
  const g = listGeometry();
  if (g.full <= MAX_SCROLL_PX) g.list.scrollTop = pos * ROW_H;
  else g.list.scrollTop = pos / Math.max(1, g.total - g.visible) * Math.max(1, g.height - g.list.clientHeight);
}

let rowsPending = false;
function requestRows() {
  if (rowsPending) return;
  rowsPending = true;
  requestAnimationFrame(() => { rowsPending = false; refreshRows(false); });
}

async function refreshRows(toEnd, reset, atUs) {
  const list = $("#trace-list");
  if (!list) return;
  const seq = ++T.rowsSeq;
  const visible = Math.max(1, Math.floor((list.clientHeight - 2) / ROW_H));
  let offset = reset && !toEnd ? 0 : firstRow();
  if (toEnd) offset = 1e12;
  const body = { offset: toEnd ? Math.max(0, (T.st ? T.st.frames : 0)) : offset, count: visible + 3, filter: filterBody() };
  if (atUs != null) body.at_us = Math.round(atUs);
  let r;
  try { r = await api("POST", "/api/trace/frames", body); } catch (e) { banner(e.message, true); return; }
  if (seq !== T.rowsSeq || !$("#trace-list")) return;
  T.total = r.total;
  updateScroll();
  if (toEnd) scrollToRow(r.total);
  else if (reset && atUs == null) scrollToRow(0);
  if (r.focus != null) {
    T.selected = r.rows[r.focus - r.offset] ? r.rows[r.focus - r.offset].seq : null;
    if (T.selected != null) fxInspectSeq(T.selected);
    scrollToRow(Math.max(0, r.focus - Math.floor(visible / 2)));
    if (r.focus - Math.floor(visible / 2) !== r.offset) {
      // The window centred on the frame; fetch exactly what is now in view.
      const again = await api("POST", "/api/trace/frames", { offset: firstRow(), count: visible + 3, filter: filterBody() });
      if (seq !== T.rowsSeq) return;
      r = again;
    }
  }
  drawRows(r);
}

function drawRows(r) {
  const rows = $("#trace-rows");
  // The server may answer from an earlier row than the one at the top
  // (it keeps a full window near the end): start at the top row.
  const w = listWindow();
  const skip = Math.max(0, Math.min(r.rows.length, w.first - r.offset));
  const shown = r.rows.slice(skip);
  rows.replaceChildren(...shown.map((x) => {
    const cls = ["trace-row", "k-" + x.kind, x.seq === T.selected ? "selected" : "", x.dir === "Tx" ? "tx" : ""].join(" ");
    return el("div", { class: cls, dataset: { seq: x.seq, t: x.t_us }, onclick: () => selectRow(x, true) },
      el("span", null, timeText(x.t_us)), el("span", null, x.gap ? "" : x.dir),
      el("span", null, x.gap ? "" : x.err ? "ERR" : x.id + (x.rtr ? " R" : "")),
      el("span", null, x.gap || x.err ? "" : String(x.dlc)), el("span", { class: "mono" }, x.data),
      el("span", { title: x.name }, x.name, assumedTag(x.source)), el("span", { title: x.text }, x.text));
  }));
  if (shown.length && w.first >= r.offset) rows.firstChild.style.setProperty("margin-top", -w.shift + "px");
  if (!r.rows.length) rows.append(el("div", { class: "muted trace-empty" }, T.st && T.st.frames ? "No frames match the display filter." : "No frames yet. Press Start, or open a trace file."));
  rowActions();
  if (T.pendingStep) {
    const step = T.pendingStep;
    T.pendingStep = 0;
    fxMoveSelection(step);
  }
}

// `open`: a click or Enter, which opens a closed inspector; the arrow keys
// move the selection without opening it.
function selectRow(x, open) {
  T.selected = x.seq;
  T.selectedUs = x.t_us;
  T.selectedRow = x;
  for (const r of document.querySelectorAll("#trace-rows .trace-row")) r.classList.toggle("selected", Number(r.dataset.seq) === x.seq);
  rowActions();
  if (open) T.inspWanted = true;
  if (open && !T.inspector) traceInspector(true);
  else if (T.inspector) fxInspectSeq(x.seq);
  if (open) { if (T.applySplit) T.applySplit(); traceRevealSplit(); }
}

function rowActions() {
  const bar = $("#trace-row-actions");
  if (!bar) return;
  const parts = [];
  if (T.jumpedFrom === "graph") parts.push(el("button", { type: "button", dataset: { trace: "back-to-graph" },
    onclick: () => { T.jumpedFrom = null; T.tab = "graph"; renderTraceTab(); } }, "Back to graph"));
  if (T.selected != null && T.selectedUs != null) {
    parts.push(el("span", { class: "muted" }, `Selected frame at ${secText(T.selectedUs)}`),
      el("button", { type: "button", dataset: { trace: "to-graph" }, onclick: () => {
        T.a = T.selectedUs;
        T.jumpedFrom = "frames";
        T.tab = "graph";
        renderTraceTab();
      } }, "Show in graph (cursor A)"));
    const x = T.selectedRow;
    if (x && x.seq === T.selected && !x.gap && !x.err) {
      parts.push(el("button", { type: "button", dataset: { trace: "explain-lab" }, onclick: () => traceExplainInLab(x.seq) }, "Explain in Frame lab"));
      parts.push(sendButton({ id: x.id, ext: !!x.ext, rtr: !!x.rtr, dlc: x.dlc || 0, data: x.rtr ? "" : x.data }));
    }
  }
  bar.replaceChildren(...parts);
}

function jumpToFrame(us, from) {
  T.jumpedFrom = from;
  T.tab = "frames";
  T.follow = false;
  T.selectedUs = us;
  renderTraceTab();
  refreshRows(false, false, us);
}

// -- graph ------------------------------------------------------------------

function seriesGroups() {
  const all = (T.st ? T.st.series : []).slice();
  const out = [["Bus", [{ key: "bus.rate", label: "Frames per second", kind: "bus" }, { key: "bus.load", label: "Bus load % (estimate)", kind: "bus" }]]];
  const by = { signal: traceCanopen() ? "PDO signals" : "Message signals", status: "Status (polled)", event: "Events" };
  for (const kind of ["signal", "status", "event"]) {
    const list = all.filter((s) => s.kind === kind);
    if (list.length) out.push([by[kind], list]);
  }
  return out;
}

function seriesLabel(key) {
  for (const [, list] of seriesGroups()) for (const s of list) if (s.key === key) return s.label;
  return key;
}

function renderGraph(box) {
  const picker = el("div", { class: "series-picker", dataset: { trace: "series" } });
  // A first graph of the network starts with its first PDO signal.
  if (!T.picked && !T.chosen.length) {
    const first = ((T.st && T.st.series) || []).find((s) => s.kind === "signal");
    if (first) { T.chosen.push(first.key); T.lane[first.key] = 1; T.picked = true; }
  }
  for (const [group, list] of seriesGroups()) {
    picker.append(el("h4", null, group));
    for (const s of list) {
      const cb = el("input", { type: "checkbox", checked: T.chosen.includes(s.key), dataset: { traceSeries: s.key } });
      cb.onchange = () => {
        T.picked = true;
        if (cb.checked) { T.chosen.push(s.key); T.lane[s.key] = T.lane[s.key] || Math.min(LANES, T.chosen.length); }
        else T.chosen = T.chosen.filter((k) => k !== s.key);
        renderTraceTab();
      };
      const lane = el("select", { "aria-label": "Lane", title: "Lane (series in the same lane share a chart)", dataset: { traceLane: s.key },
        hidden: !T.chosen.includes(s.key) },
        Array.from({ length: LANES }, (_, k) => el("option", { value: k + 1, selected: (T.lane[s.key] || 1) === k + 1 }, "L" + (k + 1))));
      lane.onchange = () => { T.lane[s.key] = Number(lane.value); renderTraceTab(); };
      picker.append(el("div", { class: "series-item" }, el("label", { class: "check inline", title: s.label === s.key ? s.key : `${s.label} (${s.key})` }, cb, s.label), lane));
    }
  }
  const readout = el("div", { id: "trace-cursors", class: "trace-cursors", dataset: { trace: "cursors" } });
  box.append(el("div", { class: "graph-layout" }, picker,
    el("div", { class: "graph-main" },
      el("div", { class: "toolbar" },
        el("button", { type: "button", dataset: { trace: "zoom-all" }, onclick: () => { T.zoom = null; loadGraph(); } }, "Whole trace"),
        el("button", { type: "button", title: "Pan left", "aria-label": "Pan left", onclick: () => pan(-0.5) }, "◀"),
        el("button", { type: "button", title: "Pan right", "aria-label": "Pan right", onclick: () => pan(0.5) }, "▶"),
        el("button", { type: "button", dataset: { trace: "zoom-out" }, onclick: () => zoomBy(2) }, "Zoom out"),
        el("button", { type: "button", onclick: () => { T.a = T.b = null; redrawPlots(); } }, "Clear cursors"),
        el("span", { class: "hint" }, "Scroll to zoom at the pointer, Shift+scroll to pan, drag to zoom to a range, click to set cursor A, Shift+click for B, double-click for the whole trace.")),
      el("div", { id: "trace-plots" }), graphSizeBar(), readout)));
  loadGraph();
}

// The whole trace's time range (µs), or null without frames.
function traceSpan() {
  const sm = T.st && T.st.summary;
  return sm && sm.first_us != null ? [sm.first_us, Math.max(sm.last_us, sm.first_us + 1000)] : null;
}

function viewRange() { return T.zoom || traceSpan(); }

// Sets the graph's range: the whole trace (T.zoom null) when it covers the
// trace, else a window of at least ZOOM_MIN_US kept inside the trace.
function setZoom(a, b) {
  const span = traceSpan();
  if (!span) return;
  let w = Math.max(ZOOM_MIN_US, b - a);
  if (w >= span[1] - span[0]) { T.zoom = null; return; }
  if (b - a < ZOOM_MIN_US) a -= (w - (b - a)) / 2;
  a = Math.min(Math.max(a, span[0]), span[1] - w);
  T.zoom = [a, a + w];
}

// Zooms the graph by the factor f (above 1 out, below 1 in) keeping the
// trace time `at` (µs) where it is on the axis.
function zoomAround(at, f) {
  const r = viewRange();
  if (!r) return;
  const k = (at - r[0]) / (r[1] - r[0]);
  const w = Math.max(ZOOM_MIN_US, (r[1] - r[0]) * f);
  setZoom(at - k * w, at - k * w + w);
}

function pan(frac) {
  const r = viewRange();
  if (!r) return;
  const w = r[1] - r[0];
  T.zoom = [r[0] + w * frac, r[1] + w * frac];
  loadGraph();
}

function zoomBy(f) {
  const r = viewRange();
  if (!r) return;
  zoomAround((r[0] + r[1]) / 2, f);
  loadGraph();
}

// The mouse wheel over a plot (canopen-bus-trace "Graphs"): the wheel, and
// Ctrl+wheel (a trackpad pinch), zooms at the pointer; Shift+wheel and a
// sideways swipe pan. Every lane is redrawn at once from the points it has;
// the points of the new range are asked for when the wheel stops.
function graphWheel(e, u) {
  if (!T.chosen.length || !traceSpan()) return;
  e.preventDefault();
  const unit = e.deltaMode === 1 ? 16 : e.deltaMode === 2 ? u.over.clientHeight : 1;
  const dx = e.deltaX * unit;
  const dy = e.deltaY * unit;
  const r = viewRange();
  const w = r[1] - r[0];
  if (e.shiftKey || Math.abs(dx) > Math.abs(dy)) {
    const d = (e.shiftKey && !dx ? dy : dx) / Math.max(1, u.over.clientWidth) * w;
    setZoom(r[0] + d, r[1] + d);
  } else {
    const box = u.over.getBoundingClientRect();
    const at = traceT0() + u.posToVal(e.clientX - box.left, "x") * 1e6;
    // About WHEEL_NOTCH per 100 px, at most two notches per event.
    const step = Math.max(-200, Math.min(200, dy));
    zoomAround(at, Math.pow(WHEEL_NOTCH, step / 100));
  }
  for (const p of T.plots) p.setScale("x", { min: 0, max: 1 });  // the range function gives the view
  clearTimeout(T.wheelTimer);
  T.wheelTimer = setTimeout(loadGraph, 150);
}

async function loadGraph() {
  T.lastGraph = Date.now();
  clearTimeout(T.wheelTimer);
  const ask = T.graphSeq = (T.graphSeq || 0) + 1;
  const plotsBox = $("#trace-plots");
  if (!plotsBox) return;
  if (!T.chosen.length) {
    for (const p of T.plots) p.destroy();
    T.plots = [];
    plotsBox.replaceChildren(el("p", { class: "muted" }, T.st && T.st.frames ? "Choose series on the left." : "No frames yet. Press Start, or open a trace file."));
    showCursors();
    return;
  }
  const width = Math.max(300, plotsBox.clientWidth || 600);
  const range = T.zoom;
  let r;
  try {
    r = await api("POST", "/api/trace/series", { keys: T.chosen, points: width * 2,
      start_us: range ? Math.floor(range[0]) : null, end_us: range ? Math.ceil(range[1]) : null });
  } catch (e) { if (ask === T.graphSeq) banner(e.message, true); return; }
  // An answer for a range asked before the last one is of no use.
  if (ask !== T.graphSeq || !$("#trace-plots") || T.tab !== "graph") return;
  T.data = r.series;
  drawPlots(width);
}

// The lanes' height: the one the user dragged, else 200 px (150 px with more than two lanes).
function laneHeight(lanes) { return T.laneH || (lanes > 2 ? 150 : 200); }

function laneCount() { return Math.max(1, T.plots.length); }

// A resize bar under a trace list or the graph (sizeBar in app.js).
function traceSizeBar(label, key, get, set, reset, range) {
  return sizeBar(label, { trace: key }, get, set, reset, range, "trace-size-bar");
}

const clampTo = (v, [lo, hi]) => Math.round(Math.max(lo, Math.min(hi, v)));

// One height for the Chronological and By identifier lists (a CSS variable).
function traceListHeight() {
  const root = document.documentElement.style;
  if (T.listH) root.setProperty("--trace-list-h", T.listH + "px");
  else root.removeProperty("--trace-list-h");
}

function listSizeBar() {
  const list = () => $("#trace-list") || $("#ids-grid");
  return traceSizeBar("Resize the list", "list-size", () => (list() ? list().getBoundingClientRect().height : 0),
    (h, done) => {
      T.listH = clampTo(h, LIST_H);
      traceListHeight();
      // The lists draw only the rows they show: draw the ones the new height shows.
      if ($("#trace-list")) requestRows();
      if ($("#ids-grid")) idsDraw();
      if (done) tracePrefs({ list_h: T.listH });
    },
    () => {
      T.listH = null;
      traceListHeight();
      tracePrefs({ list_h: null });
      if ($("#trace-list")) requestRows();
      if ($("#ids-grid")) idsDraw();
    }, () => LIST_H);
}

function graphSizeBar() {
  const fit = () => {
    const h = laneHeight(laneCount());
    for (const p of T.plots) p.setSize({ width: p.width, height: h });
  };
  return traceSizeBar("Resize the graph", "graph-size", () => laneHeight(laneCount()) * laneCount(),
    (h, done) => {
      T.laneH = clampTo(h / laneCount(), LANE_H);
      fit();
      if (done) tracePrefs({ lane_h: T.laneH });
    },
    () => { T.laneH = null; fit(); tracePrefs({ lane_h: null }); },
    () => LANE_H.map((h) => h * laneCount()));
}

function themeColor(name) { return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || "#888"; }


function drawPlots(width) {
  for (const p of T.plots) p.destroy();
  T.plots = [];
  const box = $("#trace-plots");
  box.replaceChildren();
  const t0 = traceT0();
  const lanes = {};
  for (const k of T.chosen) (lanes[T.lane[k] || 1] = lanes[T.lane[k] || 1] || []).push(k);
  const laneKeys = Object.keys(lanes).map(Number).sort((a, b) => a - b);
  const r = viewRange();
  const text = themeColor("--text");
  const line = themeColor("--line");
  const muted = themeColor("--muted");
  const height = laneHeight(laneKeys.length);
  laneKeys.forEach((lane, li) => {
    const keys = lanes[lane];
    // One x array per lane: the union of the series' times, null where a series has no point.
    const xs = new Set();
    for (const k of keys) for (const t of (T.data[k] || [[], []])[0]) xs.add(t);
    const x = [...xs].sort((a, b) => a - b);
    const index = new Map(x.map((t, i) => [t, i]));
    const ys = keys.map((k) => {
      const out = new Array(x.length).fill(null);
      const [ts, vs] = T.data[k] || [[], []];
      for (let i = 0; i < ts.length; i++) out[index.get(ts[i])] = vs[i];
      return out;
    });
    const data = [x.map((t) => (t - t0) / 1e6), ...ys];
    const series = [{ label: "t (s)" }].concat(keys.map((k, i) => {
      const colors = seriesColors();
      const color = colors[T.chosen.indexOf(k) % colors.length];
      const ev = k.startsWith("emcy.") || k.startsWith("sdo_abort.");
      return { label: seriesLabel(k), stroke: color, width: 1.5, spanGaps: true,
        paths: ev ? () => null : uPlot.paths.stepped({ align: 1 }),
        points: { show: ev, size: 6, fill: color } };
    }));
    const opts = {
      width, height, series, legend: { show: true, live: true },
      // The view range at each redraw, so the wheel can set it on every lane at once.
      scales: { x: { time: false, auto: !r, range: r ? (_u, lo, hi) => {
        const v = viewRange();
        return v ? [(v[0] - t0) / 1e6, (v[1] - t0) / 1e6] : [lo, hi];
      } : undefined } },
      axes: [{ stroke: muted, grid: { stroke: line, width: 1 }, ticks: { stroke: line }, label: li === laneKeys.length - 1 ? "seconds" : undefined, labelSize: 18 },
        { stroke: muted, grid: { stroke: line, width: 1 }, ticks: { stroke: line }, size: 60 }],
      cursor: { sync: { key: "trace", setSeries: false }, drag: { x: true, y: false, setScale: false } },
      hooks: {
        setSelect: [(u) => {
          if (u.select.width < 4) return;
          const a = u.posToVal(u.select.left, "x");
          const b = u.posToVal(u.select.left + u.select.width, "x");
          u.setSelect({ left: 0, width: 0, top: 0, height: 0 }, false);
          T.justSelected = Date.now();
          T.zoom = [t0 + a * 1e6, t0 + b * 1e6];
          loadGraph();
        }],
        draw: [(u) => drawOverlays(u, t0)],
      },
    };
    const holder = el("div", { class: "plot", dataset: { traceLane: String(lane) } });
    box.append(holder);
    const plot = new uPlot(opts, data, holder);
    plot.over.addEventListener("click", (e) => {
      // The click that ends a drag-zoom (when the browser sends one) sets no cursor.
      const dragged = T.justSelected && Date.now() - T.justSelected < 300;
      T.justSelected = 0;
      if (dragged) return;
      if (plot.cursor.left == null || plot.cursor.left < 0) return;
      const us = t0 + plot.posToVal(plot.cursor.left, "x") * 1e6;
      if (e.shiftKey) T.b = us; else T.a = us;
      redrawPlots();
    });
    plot.over.addEventListener("dblclick", () => { T.zoom = null; loadGraph(); });
    plot.over.addEventListener("wheel", (e) => graphWheel(e, plot), { passive: false });
    T.plots.push(plot);
  });
  box.dataset.points = String(Object.values(T.data).reduce((n, s) => n + s[0].length, 0));
  showCursors();
  void text;
}

function drawOverlays(u, t0) {
  const ctx = u.ctx;
  const top = u.bbox.top;
  const h = u.bbox.height;
  const vline = (us, color, dash) => {
    const x = Math.round(u.valToPos((us - t0) / 1e6, "x", true));
    if (x < u.bbox.left || x > u.bbox.left + u.bbox.width) return;
    ctx.save();
    ctx.strokeStyle = color;
    ctx.lineWidth = 1.5 * devicePixelRatio;
    if (dash) ctx.setLineDash([5 * devicePixelRatio, 4 * devicePixelRatio]);
    ctx.beginPath();
    ctx.moveTo(x, top);
    ctx.lineTo(x, top + h);
    ctx.stroke();
    ctx.restore();
  };
  for (const m of (T.st && T.st.markers) || []) vline(m.time_us, m.kind === "trigger" ? themeColor("--st-error") : themeColor("--st-warn"), true);
  if (T.a != null) vline(T.a, themeColor("--accent"), false);
  if (T.b != null) vline(T.b, themeColor("--accent"), true);
}

function redrawPlots() {
  for (const p of T.plots) p.redraw(false, false);
  showCursors();
}

function valueAt(key, us) {
  const s = T.data[key];
  if (!s || !s[0].length) return null;
  const [ts, vs] = s;
  let lo = 0;
  let hi = ts.length - 1;
  if (us < ts[0]) return null;
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1;
    if (ts[mid] <= us) lo = mid; else hi = mid - 1;
  }
  return vs[lo];
}

function fmtValue(v) { return v == null ? "-" : Number.isInteger(v) ? String(v) : v.toPrecision(6); }

function showCursors() {
  const box = $("#trace-cursors");
  if (!box) return;
  if (T.a == null && T.b == null) { box.replaceChildren(el("span", { class: "muted" }, "No cursors set.")); return; }
  const head = [];
  if (T.a != null) head.push(`A ${secText(T.a)}`);
  if (T.b != null) head.push(`B ${secText(T.b)}`);
  if (T.a != null && T.b != null) head.push(`Δt ${((T.b - T.a) / 1000).toFixed(3)} ms`);
  const rows = T.chosen.map((k) => {
    const va = T.a != null ? valueAt(k, T.a) : null;
    const vb = T.b != null ? valueAt(k, T.b) : null;
    return el("tr", { dataset: { traceDelta: k } }, el("td", null, seriesLabel(k)), el("td", null, fmtValue(va)), el("td", null, fmtValue(vb)),
      el("td", null, va != null && vb != null ? fmtValue(vb - va) : "-"));
  });
  box.replaceChildren(...[
    el("div", { class: "toolbar" }, el("strong", { dataset: { trace: "delta-t" } }, head.join(" · ")),
      T.a != null ? el("button", { type: "button", dataset: { trace: "to-frames" }, onclick: () => jumpToFrame(T.a, "graph") }, "Show A in frames") : null,
      T.jumpedFrom === "frames" ? el("button", { type: "button", dataset: { trace: "back-to-frames" },
        onclick: () => { T.jumpedFrom = null; jumpToFrame(T.selectedUs != null ? T.selectedUs : T.a, null); } }, "Back to frames") : null),
    rows.length ? el("table", { class: "compare" }, el("thead", null, el("tr", null, thCells(["Series", "A", "B", "Δ (B − A)"]))),
      el("tbody", null, rows)) : null].filter(Boolean));
}

// -- trigger ----------------------------------------------------------------

function blankCondition(type) { return { type: type || (traceCanopen() ? "emcy" : "frame") }; }

function triggerDraft() {
  if (!T.trigDraft) {
    const cur = T.st && T.st.trigger;
    T.trigDraft = cur ? JSON.parse(JSON.stringify(cur)) : { conditions: [blankCondition()], combine: "and", window_ms: 100,
      count: 1, mode: "single", pre_s: 5, post_s: 2, autosave: null };
    for (const c of T.trigDraft.conditions) {
      if (c.type === "frame") {
        c.id = "0x" + Number(c.id).toString(16).toUpperCase();
        c.mask = c.mask === 0x1FFFFFFF ? "" : "0x" + Number(c.mask).toString(16).toUpperCase();
      }
      if (c.type === "emcy" && c.code != null) c.code = "0x" + Number(c.code).toString(16).toUpperCase().padStart(4, "0");
    }
  }
  return T.trigDraft;
}

function condEditor(c, k) {
  const d = triggerDraft();
  const type = el("select", { "aria-label": "Condition", dataset: { traceCond: k + ".type" } },
    condTypes().map(([v, l]) => el("option", { value: v, selected: c.type === v }, l)));
  type.onchange = () => { d.conditions[k] = blankCondition(type.value); renderTrigger($("#trace-tab")); };
  const txt = (key, label, width) => {
    const i = el("input", { type: "text", spellcheck: "false", placeholder: label, "aria-label": label,
      dataset: { traceCond: k + "." + key } });
    i.style.width = width;
    i.value = c[key] != null ? c[key] : "";
    i.addEventListener("input", () => { if (i.value.trim() === "") delete c[key]; else c[key] = i.value.trim(); });
    return i;
  };
  const sel = (key, label, list, dflt) => {
    const s = el("select", { "aria-label": label, dataset: { traceCond: k + "." + key } },
      list.map(([v, l]) => el("option", { value: v, selected: (c[key] || dflt) === v }, l)));
    c[key] = c[key] || dflt;
    s.onchange = () => { c[key] = s.value; };
    return s;
  };
  const fields = [];
  if (c.type === "frame") fields.push(txt("id", "ID, e.g. 0x702", "11ch"), txt("mask", "mask (all bits)", "11ch"),
    txt("data", "data bytes, e.g. 05", "16ch"), txt("data_mask", "data mask", "12ch"),
    sel("dir", "Direction", [["any", "Rx or Tx"], ["rx", "Rx"], ["tx", "Tx"]], "any"));
  if (["emcy", "state", "heartbeat_lost", "boot_error", "sdo_abort"].includes(c.type)) fields.push(txt("node", c.type === "state" ? "node" : "node (any)", "11ch"));
  if (c.type === "emcy") fields.push(txt("code", "code (any)", "10ch"));
  if (c.type === "state") fields.push(sel("state", "State", [["any", "any change"], ["bootup", "boot-up"], ["stopped", "STOPPED"],
    ["operational", "OPERATIONAL"], ["preop", "PRE-OPERATIONAL"]], "any"));
  if (c.type === "signal") {
    const sigs = ((T.st && T.st.series) || []).filter((s) => s.kind === "signal");
    fields.push(sel("key", "Signal", sigs.length ? sigs.map((s) => [s.key, s.label]) : [["", traceCanopen() ? "no PDO signals in this config" : "no message signals in this config"]], sigs.length ? sigs[0].key : ""),
      sel("op", "Comparison", SIGNAL_OPS.map((o) => [o, o.replace("_", " ")]), ">"), txt("value", "value", "10ch"));
  }
  if (c.type === "bus") fields.push(sel("state", "Bus state", [["warning", "error-warning or worse"], ["passive", "error-passive or worse"], ["off", "bus-off"]], "warning"));
  return el("div", { class: "row cond" }, el("strong", null, k === 0 ? "A" : "B"), type, ...fields,
    k === 1 ? el("button", { type: "button", "aria-label": "Remove condition B", title: "Remove", onclick: () => { d.conditions.splice(1, 1); renderTrigger($("#trace-tab")); } }, "✕") : null);
}

function renderTrigger(box) {
  const d = triggerDraft();
  const num = (key, label, attrs) => {
    const i = el("input", Object.assign({ type: "number", "aria-label": label, dataset: { traceTrig: key }, class: "short" }, attrs || {}));
    i.value = d[key];
    i.addEventListener("input", () => { d[key] = i.value === "" ? d[key] : Number(i.value); });
    return el("label", { class: "inline" }, label, i);
  };
  const combine = el("select", { "aria-label": "Combine", dataset: { traceTrig: "combine" } },
    [["and", "A and B within the window"], ["then", "B after A within the window (0: any time)"]].map(([v, l]) => el("option", { value: v, selected: d.combine === v }, l)));
  combine.onchange = () => { d.combine = combine.value; };
  const mode = el("select", { "aria-label": "Mode", dataset: { traceTrig: "mode" } },
    [["single", "Single: stop after the post-trigger time"], ["normal", "Normal: mark each hit and keep recording"]].map(([v, l]) => el("option", { value: v, selected: d.mode === v }, l)));
  mode.onchange = () => { d.mode = mode.value; };
  const auto = el("input", { type: "checkbox", checked: !!d.autosave, dataset: { traceTrig: "autosave" } });
  const autoFmt = el("select", { "aria-label": "Auto-save format", dataset: { traceTrig: "autosave-format" }, disabled: !d.autosave && "Tick Auto-save first." },
    TRACE_FORMATS.map(([v, l]) => el("option", { value: v, selected: d.autosave && d.autosave.format === v }, l)));
  const autoDir = el("input", { type: "text", spellcheck: "false", class: "wide", "aria-label": "Auto-save folder", dataset: { traceTrig: "autosave-folder" },
    placeholder: (T.st && T.st.traces_dir) || "", disabled: !d.autosave && "Tick Auto-save first." });
  autoDir.value = d.autosave && d.autosave.folder ? d.autosave.folder : "";
  const syncAuto = () => {
    d.autosave = auto.checked ? { format: autoFmt.value, folder: autoDir.value.trim() } : null;
    for (const x of [autoFmt, autoDir]) Icons.setDisabled(x, !auto.checked && "Tick Auto-save first.");
  };
  auto.onchange = syncAuto;
  autoFmt.onchange = syncAuto;
  autoDir.addEventListener("input", syncAuto);
  box.replaceChildren(
    el("p", { class: "hint" }, "Evaluated on this PC while recording. A hit puts a marker in the trace and the graph."),
    el("fieldset", null, el("legend", null, "Condition"),
      ...d.conditions.map((c, k) => condEditor(c, k)),
      d.conditions.length < 2 ? el("button", { type: "button", dataset: { trace: "add-cond" }, onclick: () => { d.conditions.push(blankCondition("frame")); renderTrigger(box); } }, "Add condition B")
        : el("div", { class: "row" }, combine, num("window_ms", "Window ms", { min: 0 }))),
    el("fieldset", null, el("legend", null, "When it fires"),
      el("div", { class: "row wrap" }, num("count", "Fire on every", { min: 1 }), el("span", null, "match"), mode),
      el("div", { class: "row wrap" }, num("pre_s", "Pre-trigger s", { min: 0, step: "any" }), num("post_s", "Post-trigger s", { min: 0, max: 600, step: "any" })),
      el("div", { class: "row wrap" }, el("label", { class: "check inline" }, auto, "Auto-save each pre/post window as"), autoFmt),
      el("label", { class: "inline wide-label" }, el("span", null, "in folder"), autoDir),
      el("p", { class: "hint" }, "Files are named <project>-trace-<UTC time>. The default folder is the configurator's settings folder. Another folder must exist and be given as a full path; the project's canworks folder is refused, since it travels with the PLC program.")),
    el("div", { class: "toolbar" },
      el("button", { type: "button", class: "primary", dataset: { trace: "apply-trigger" }, onclick: applyTrigger }, "Apply trigger"),
      el("button", { type: "button", dataset: { trace: "remove-trigger" }, onclick: removeTrigger }, "Remove trigger")),
    el("div", { id: "trigger-status" }));
  renderTriggerStatus();
}

function renderTriggerStatus() {
  const box = $("#trigger-status");
  if (!box || !T.st) return;
  const rec = T.st.recording;
  const hits = rec.hits || [];
  box.replaceChildren(...[
    el("p", { dataset: { trace: "trigger-text" } }, T.st.trigger_text ? `Active trigger: ${T.st.trigger_text} (${T.st.trigger.mode}). Used from the next Start, and at once while recording.` : "No trigger."),
    hits.length ? el("ul", { class: "trigger-hits" }, hits.map((h, k) => el("li", null, `Hit ${k + 1} at ${secText(h)} `,
      el("button", { type: "button", onclick: () => jumpToFrame(h, null) }, "Show"),
      el("button", { type: "button", onclick: () => { T.a = h; T.tab = "graph"; renderTraceTab(); } }, "Graph")))) : null,
    rec.saved && rec.saved.length ? el("div", null, el("p", null, "Auto-saved:"),
      el("ul", { dataset: { trace: "saved" } }, rec.saved.map((p) => el("li", { class: "mono" }, p)))) : null].filter(Boolean));
}

async function applyTrigger() {
  const d = triggerDraft();
  try {
    T.st = await api("POST", "/api/trace/trigger", { trigger: d });
    T.trigDraft = null;
    banner("Trigger set: " + T.st.trigger_text);
    renderTrigger($("#trace-tab"));
    showTraceHeader(T.st);
  } catch (e) { banner(e.message, true); }
}

async function removeTrigger() {
  try {
    T.st = await api("POST", "/api/trace/trigger", { trigger: null });
    T.trigDraft = null;
    renderTrigger($("#trace-tab"));
    showTraceHeader(T.st);
  } catch (e) { banner(e.message, true); }
}

// -- send -------------------------------------------------------------------
// Sending (transmit.js): why it is not possible now, and a frame as text.
function sendBlocked() {
  if (S.state && (S.state.commission || connRemote())) {
    if (!S.adapterOn) return "Sending needs the adapter connection: Connect… in the connection bar";
    if (!S.online.allow_changes) return "Sending needs Allow changes in the connection bar";
    return null;
  }
  if (!onlineReady()) return "Sending needs a connection: Connect… in the connection bar";
  if (!diagConfig().allow_changes) return "Sending needs Allow changes in Online access";
  return null;
}

function sendFrameText(f) {
  // The jobs the server lists carry the identifier as a number.
  const id = (typeof f.id === "number" ? f.id.toString(16) : String(f.id).replace(/^0x/i, "")).toUpperCase();
  if (f.rtr) return `${id} remote [${f.dlc || 0}]`;
  const data = (f.data || "").trim().toUpperCase();
  return `${id} [${data ? data.split(/\s+/).length : 0}] ${data}`.trim();
}

// -- Decoding: DBC files and the nodes' PDO layouts (canopen-configurator:
// "Decoding panel in the Trace view", "PDO layout in the frame inspector",
// "Automatic PDO layout reads in Commission a device") --------------------------

const ASSUMED_TIP = "Decoded with the EDS defaults: the device may be mapped differently. " +
  "Read PDOs from device under Decoding makes it certain.";
const LAYOUT_SOURCE = { configuration: "configuration", bus: "set on the bus", device: "read from the device",
  eds: "EDS defaults (assumed)" };

function assumedTag(source) {
  return source === "eds" ? el("span", { class: "tag warn-tag", title: ASSUMED_TIP, dataset: { trace: "assumed" } }, "assumed") : null;
}

function decodingBody(extra) {
  return Object.assign({ eds: commissionEds() || undefined }, extra || {});
}

function decodingSummary(v) {
  if (!v) return "Decoding";
  const files = v.dbc.length;
  const known = v.nodes.filter((n) => n.source).length;
  const parts = [files ? `${files} DBC` : "", known ? `${known} node${known === 1 ? "" : "s"}` : ""].filter(Boolean);
  return parts.length ? `Decoding · ${parts.join(", ")}` : "Decoding";
}

function decodingWarn(v) {
  return !!(v && v.dbc.some((d) => d.missing || d.error || (d.problems && d.problems.length)));
}

// The toolbar's Decoding ▾ (between Capture and the time mode).
function decodingMenu() {
  const panel = el("div", { class: "menu-panel trace-decoding", dataset: { trace: "decoding-panel" } },
    el("p", { class: "muted" }, "Loading…"));
  const summary = el("summary", { "aria-haspopup": "true", id: "trace-decoding-summary" }, decodingSummary(T.decoding));
  const menu = closeOnOutside(el("details", { class: "menu trace-menu", dataset: { trace: "decoding" } }, summary, panel));
  menu.addEventListener("toggle", () => { if (menu.open) loadDecoding(); });
  setTimeout(() => updateDecodingSummary(T.decoding));
  if (!T.decoding) loadDecoding(true);
  return menu;
}

function updateDecodingSummary(v) {
  const s = $("#trace-decoding-summary");
  if (!s) return;
  s.replaceChildren(decodingSummary(v), decodingWarn(v) ? el("span", { class: "warn-mark", title: "A DBC file is missing or has problems", "aria-label": "(a DBC file needs attention)" }, " ⚠") : "");
}

async function loadDecoding(quiet) {
  try { T.decoding = await api("GET", "/api/trace/decoding"); } catch (e) { if (!quiet) banner(e.message, true); return; }
  updateDecodingSummary(T.decoding);
  drawDecoding();
}

async function decodingAction(body, done) {
  T.edsSent = JSON.stringify(commissionEds() || {});
  try {
    T.decoding = await api("POST", "/api/trace/decoding", decodingBody(body));
    banner(done || "");
  } catch (e) { banner(e.message, true); return false; }
  updateDecodingSummary(T.decoding);
  drawDecoding();
  return true;
}

// After a change of the nodes' EDS files: the trace decodes again.
function decodingRefresh() {
  if (S.view === "trace") decodingAction({ action: "refresh" });
}

async function addDbcFiles(files, replacing) {
  for (const f of files) {
    const ok = await decodingAction({ action: "add", name: f.name, data: await readBase64(f) }, `Added ${f.name}.`);
    if (ok && replacing) { await decodingAction({ action: "remove", path: replacing }); replacing = null; }
  }
}

function drawDecoding() {
  const panel = document.querySelector("[data-trace=decoding-panel]");
  if (!panel) return;
  const v = T.decoding;
  if (!v) return;
  const add = el("input", { type: "file", accept: ".dbc,.DBC", multiple: true, dataset: { trace: "add-dbc" } });
  add.addEventListener("change", () => { const files = [...add.files]; add.value = ""; addDbcFiles(files); });
  const paths = v.dbc.map((d) => d.path);
  const move = (k, step) => {
    const order = paths.slice();
    const [p] = order.splice(k, 1);
    order.splice(k + step, 0, p);
    decodingAction({ action: "order", paths: order }).then(() => {
      const b = document.querySelector(`[data-dbc-row="${k + step}"] [data-trace="${step < 0 ? "dbc-up" : "dbc-down"}"]`);
      if (b && !b.disabled) b.focus();
    });
  };
  const rows = v.dbc.map((d, k) => {
    let state;
    if (d.missing) state = el("span", { class: "bad" }, "missing");
    else if (d.error) state = el("span", { class: "bad", title: d.error }, "cannot be read");
    else state = el("span", null, `${d.used} of ${d.total} messages used`);
    const locate = el("input", { type: "file", accept: ".dbc,.DBC", dataset: { trace: "locate-dbc" } });
    locate.addEventListener("change", () => { const f = locate.files[0]; locate.value = ""; if (f) addDbcFiles([f], d.path); });
    const notes = [...(d.problems || []), ...(d.unused || []).map((u) => "Not used: " + u)];
    return el("li", { class: "dbc-row", dataset: { dbcRow: k } },
      el("div", { class: "row" },
        el("strong", { title: d.path }, d.name), state,
        el("span", { class: "spacer" }),
        orderButton("↑", `Move ${d.name} up`, "dbc-up", k === 0 ? "Already the first file" : null, () => move(k, -1)),
        orderButton("↓", `Move ${d.name} down`, "dbc-down", k === v.dbc.length - 1 ? "Already the last file" : null, () => move(k, 1)),
        d.missing ? el("label", { class: "file-button small" }, "Locate…", locate) : null,
        el("button", { type: "button", class: "small", "aria-label": `Remove ${d.name}`, dataset: { trace: "dbc-remove" },
          onclick: () => decodingAction({ action: "remove", path: d.path }, `Removed ${d.name}.`) }, "Remove")),
      notes.length ? el("details", { class: "dbc-notes" }, el("summary", null, `${notes.length} note${notes.length === 1 ? "" : "s"}`),
        el("ul", null, notes.map((n) => el("li", null, n)))) : null);
  });
  const parts = [
    el("h3", null, "DBC files"),
    el("p", { class: "hint" }, v.protocol === "canopen"
      ? "Messages of these files decode their identifiers: the configuration's own PDOs and raw messages first, then the files in this order. NMT, SYNC, EMCY, SDO, heartbeat and LSS keep their CANopen decoding, with the DBC's next to it. Kept on this PC."
      : "Messages of these files decode their identifiers: the configuration's own messages first, then the files in this order. Kept on this PC."),
    rows.length ? el("ul", { class: "dbc-list" }, rows) : el("p", { class: "muted" }, "No DBC file."),
    el("div", { class: "toolbar" }, el("label", { class: "file-button" }, "Add DBC…", add))];
  if (v.protocol === "canopen") parts.push(el("h3", null, "Nodes"), decodingNodes(v));
  panel.replaceChildren(...parts);
}

function orderButton(text, label, data, why, onclick) {
  const b = el("button", { type: "button", class: "small", "aria-label": label, title: label, dataset: { trace: data }, onclick }, text);
  return why ? Icons.disable(b, why) : b;
}

function decodingNodes(v) {
  if (!v.nodes.length) return el("p", { class: "muted" }, "No node in the trace yet.");
  const commission = !!(S.state && S.state.commission);
  return el("table", { class: "data", dataset: { trace: "decoding-nodes" } },
    el("thead", null, el("tr", null, thCells(["Node", "Device", "EDS", "PDO layout", ""]))),
    el("tbody", null, v.nodes.map((n) => {
      const added = typeof commNodes === "function" ? commNodes()[n.node] || {} : {};
      const eds = (S.onlineEdsName || {})[n.node] || added.eds_name || (S.onlineEds || {})[n.node];
      const scanned = ((S.scanResult && S.scanResult.nodes) || []).find((d) => d.node_id === n.node);
      const at = (t) => t != null && t >= 0 && v.start_us != null ? ` at ${traceSeconds(t - v.start_us)}` : "";
      const bad = n.read ? n.read.pdos.filter((p) => !p.usable) : [];
      let source = n.source ? LAYOUT_SOURCE[n.source] + at(n.since_us) : "unknown";
      if (!n.source && n.read) source = n.read.pdos.length ? "not read" + at(n.read.since_us) : "not read: no valid PDO";
      return el("tr", { dataset: { decodingNode: n.node } },
        el("td", { class: "num" }, String(n.node)),
        el("td", null, scanned && scanned.device_name ? scanned.device_name : ""),
        el("td", null, n.has_eds ? (eds || "yes") : el("span", { class: "muted" }, "none, built-in CiA names")),
        el("td", null, source, n.pdos.length ? el("div", { class: "muted" }, n.pdos.join(", ")) : null,
          bad.map((p) => el("div", { class: "muted", dataset: { trace: "read-why" } }, `${p.name}: ${p.reason}`))),
        el("td", null, commission && n.source !== "configuration" ? layoutActions(n.node, n.has_eds) : null));
    })));
}

function traceSeconds(us) { return `${(us / 1e6).toFixed(3)} s`; }

// Pick EDS… (or Change EDS…) and Read PDOs from device for a node of Commission a device.
function layoutActions(node, hasEds) {
  const input = el("input", { type: "file", accept: ".eds,.EDS", dataset: { trace: "pick-eds" } });
  input.addEventListener("change", () => { const f = input.files[0]; input.value = ""; if (f) tracePickEds(node, f); });
  const read = el("button", { type: "button", class: "small", dataset: { trace: "read-pdos" }, onclick: () => readPdoLayout(node, true) }, "Read PDOs from device");
  if (!S.adapterOn) Icons.disable(read, `Reading needs the ${connRemote() ? "adapter" : "USB adapter"} connection: Connect… in the connection bar`);
  return el("div", { class: "row" }, el("label", { class: "file-button small" }, hasEds ? "Change EDS…" : "Pick EDS…", input), read);
}

// The node's EDS, as the Nodes table's pick sets it, and the trace decodes again.
async function tracePickEds(node, file) {
  let res;
  try {
    res = await api("POST", "/api/eds", { name: file.name, data: await readBase64(file), on_conflict: "keep_both", eds_lint: edsLint() });
  } catch (e) { banner(e.message, true); return; }
  commNodes()[node] = Object.assign(commNodes()[node] || {}, { eds_path: res.name, eds_name: res.name });
  S.onlineEds = Object.assign(S.onlineEds || {}, { [node]: res.name });
  S.onlineEdsName = Object.assign(S.onlineEdsName || {}, { [node]: res.name });
  await decodingAction({ action: "refresh" }, `Node ${node} decodes with ${res.name}.`);
}

function otherMaster() {
  const r = S.onlineLast;
  return !!(r && ((r.status && r.status.other_master_seen) || (r.conn && r.conn.other_master)));
}

// One node's PDO objects read from the device; `asked`: pressed by the user.
async function readPdoLayout(node, asked) {
  if (asked && otherMaster()) {
    const v = await modal(`Another master is active on this bus. Its SDO transfers to node ${node} can be mixed with this read, and either side may then take the wrong answer. Read node ${node}'s PDOs anyway?`,
      [["read", "Read anyway"], ["cancel", "Cancel", true]]);
    if (v !== "read") return;
  }
  PL.done.set(node, "reading");
  try {
    const r = await api("POST", "/api/online/pdo_layout", { node, port: diagPort() });
    PL.done.set(node, "read");
    if (asked) readBanner(node, r.pdos);
  } catch (e) {
    PL.done.set(node, "failed");
    if (asked) banner(`Node ${node}'s PDOs not read: ${e.message}`, true);
  }
  if (S.view === "trace") loadDecoding(true);
}

// The message after Read PDOs from device: the PDOs that now decode, and each
// other one with its reason (canopen-configurator: "Result of a PDO layout read").
function readBanner(node, pdos) {
  if (!pdos.length) { banner(`Node ${node} has no valid PDO.`, "warning"); return; }
  const usable = pdos.filter((p) => p.usable).map((p) => p.name);
  const why = pdos.filter((p) => !p.usable).map((p) => `${p.name} not usable: ${p.reason}`).join("; ");
  if (!usable.length) banner(`Node ${node}: no PDO decodes after the read. ${why}.`, true);
  else banner(`Node ${node}: ${usable.join(", ")} read from the device.${why ? ` ${why}.` : ""}`);
}

// Automatic reads in Commission a device: each heard node once per
// connection and again after its boot-up, one at a time; never from a STOPPED
// node, and not while another master is on the bus.
const PL = { done: new Map(), states: new Map(), busy: false };

function pdoAutoReset() {
  PL.done.clear();
  PL.states.clear();
}

async function pdoAutoRead(r) {
  if (!(S.state && S.state.commission) || !S.adapterOn || PL.busy || !r || !r.status) return;
  const nodes = r.status.nodes || [];
  for (const n of nodes) {
    const prev = PL.states.get(n.node_id);
    if (n.state === 0 && prev !== 0 && PL.done.get(n.node_id) !== "reading") PL.done.delete(n.node_id);  // booted again
    PL.states.set(n.node_id, n.state);
  }
  if (otherMaster()) return;
  const next = nodes.find((n) => n.state !== null && n.state !== undefined && n.state !== 4 && n.state !== 0 && !PL.done.has(n.node_id));
  if (!next) return;
  PL.busy = true;
  try { await readPdoLayout(next.node_id, false); } finally { PL.busy = false; }
}

// The inspector's Layout line of a PDO frame, with its node's actions.
function fxLayoutLine(m) {
  const l = m.layout;
  if (!l) return null;
  const commission = !!(S.state && S.state.commission);
  const since = l.since_us != null && l.since_us >= 0 && T.st && T.st.start_us != null ? ` (at ${traceSeconds(l.since_us - T.st.start_us)})` : "";
  return el("p", { class: "fx-layout", dataset: { fx: "layout" } },
    el("strong", null, "Layout: "), l.text.replace(/\.$/, "") + since + ".",
    l.source === "eds" ? assumedTag("eds") : null,
    commission && l.node != null && (l.source === null || l.source === "eds") ? layoutActions(l.node, l.source === "eds") : null);
}
