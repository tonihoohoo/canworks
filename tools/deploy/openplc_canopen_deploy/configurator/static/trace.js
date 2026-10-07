// Trace view (canopen-configurator "Trace view", canopen-bus-trace): records
// the bus through the runtime's diagnostics channel, or shows an opened trace
// file. The trace lives on the local server (/api/trace/*); this page asks for
// windows of decoded rows and decimated series, so a reload keeps the trace.
// Loaded after app.js and uses its helpers (el, api, banner, modal, S, ...).
"use strict";

const TRACE_KINDS = [["nmt", "NMT"], ["sync", "SYNC"], ["time", "TIME"], ["emcy", "EMCY"], ["heartbeat", "Heartbeat"],
  ["sdo", "SDO"], ["pdo", "PDO"], ["lss", "LSS"], ["error", "Error"], ["gap", "Gap"], ["other", "Other"]];
const TRACE_FORMATS = [["pcapng", "pcapng (Wireshark)"], ["candump", "candump log"], ["asc", "Vector ASC"],
  ["blf", "Vector BLF"], ["trc", "PEAK TRC 2.1"], ["csv", "CSV, decoded"]];
const TRACE_STATES = { idle: "not recording", connecting: "connecting…", recording: "recording",
  no_bus: "waiting for the CANopen session", reconnecting: "reconnecting…", stopped: "stopped", error: "stopped" };
const ROW_H = 22;
const MAX_SCROLL_PX = 4000000;
const LANES = 4;
const COND_TYPES = [["frame", "Frame"], ["emcy", "EMCY"], ["state", "Node state"], ["heartbeat_lost", "Heartbeat lost"],
  ["boot_error", "Boot error"], ["sdo_abort", "SDO abort"], ["signal", "Signal value"], ["bus", "Bus state"],
  ["error_frame", "Error frame"]];
const SIGNAL_OPS = [">", "<", "=", "!=", "cross_up", "cross_down", "rising", "falling"];
const SERIES_COLORS = ["#1f77b4", "#d62728", "#2ca02c", "#ff7f0e", "#9467bd", "#17becf", "#8c564b", "#e377c2",
  "#7f7f7f", "#bcbd22"];

// The view's choices; the trace itself is on the server.
const T = {
  tab: "frames", filter: {}, timeMode: "rel", follow: true, selected: null, focusSeq: null,
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

function onlineReady() {
  return !!(diagConfig() && S.online && S.online.host && S.online.token && S.online.tokenOk);
}

// ---------------------------------------------------------------------------

function renderTrace(view) {
  document.querySelector("#editor").classList.add("wide-view");
  const fileInput = el("input", { type: "file", accept: ".pcapng,.pcap,.log,.asc", dataset: { trace: "open-input" } });
  fileInput.addEventListener("change", () => {
    const f = fileInput.files[0];
    fileInput.value = "";
    if (f) traceOpen(f);
  });
  const fmtSelect = (key, list, data) => {
    const s = el("select", { dataset: { trace: data }, "aria-label": "Format" },
      list.map(([v, l]) => el("option", { value: v, selected: T[key] === v }, l)));
    s.onchange = () => { T[key] = s.value; };
    return s;
  };
  const range = el("select", { dataset: { trace: "range" }, "aria-label": "What to save or export" },
    [["all", "Whole trace"], ["view", "Graph zoom"], ["cursors", "Between cursors A and B"]]
      .map(([v, l]) => el("option", { value: v, selected: T.range === v }, l)));
  range.onchange = () => { T.range = range.value; };
  view.append(
    el("h2", null, "Trace"),
    el("div", { id: "trace-source", class: "online-conn" }, "Loading…"),
    el("div", { class: "toolbar" }, netPicker(),
      el("button", { type: "button", class: "primary", dataset: { trace: "start" }, onclick: traceStart }, "Start"),
      el("button", { type: "button", dataset: { trace: "stop" }, onclick: traceStop }, "Stop"),
      el("button", { type: "button", dataset: { trace: "clear" }, onclick: traceClear }, "Clear"),
      el("label", { class: "file-button", title: "Open a pcapng, candump log or Vector ASC file" }, "Open file…", fileInput),
      el("span", { class: "joined" }, fmtSelect("saveFormat", TRACE_FORMATS, "save-format"),
        el("button", { type: "button", dataset: { trace: "save" }, onclick: traceSave,
          title: "Save to the traces folder on this PC" }, "Save")),
      el("span", { class: "joined" }, fmtSelect("exportFormat", TRACE_FORMATS.concat([["signals", "Signals CSV"]]), "export-format"),
        el("button", { type: "button", dataset: { trace: "export" }, onclick: traceExport,
          title: "Download a file" }, "Export")),
      range),
    captureSettings(),
    sendPanel(),
    el("div", { id: "trace-stats", class: "trace-stats", dataset: { trace: "stats" } }),
    el("div", { class: "segmented trace-tabs", role: "tablist" },
      [["frames", "Frames"], ["ids", "Identifiers"], ["graph", "Graph"], ["sequences", "Sequences"], ["trigger", "Trigger"]].map(([v, l]) =>
        el("button", { type: "button", role: "tab", "aria-pressed": String(T.tab === v), dataset: { traceTab: v },
          onclick: () => { T.tab = v; renderTraceTab(); } }, l))),
    el("div", { id: "trace-tab" }));
  T.lastFrames = -1;
  T.lastGeneration = -1;
  const seq = T.seq;
  pollTrace(seq, true);
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
  return el("details", { class: "advanced" }, el("summary", null, "Capture filters"),
    el("p", { class: "hint" }, "Applied on the runtime from the next Start: only frames whose ID matches one filter (ID and mask, e.g. 0x180 and 0x780 for all TPDO1s) are recorded. No filter records everything. Display filters under Frames never change what is recorded."),
    list,
    el("div", { class: "toolbar" },
      el("button", { type: "button", dataset: { trace: "add-filter" }, onclick: () => {
        if (T.capFilters.length >= 16) return banner("At most 16 capture filters.", true);
        T.capFilters.push({ id: "0x180", mask: "0x780" });
        draw();
      } }, "Add filter"),
      el("label", { class: "check inline" }, errs, " Record error frames (the adapter must report them)")));
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
      renderTraceTab();
    } else if (changed) {
      if (T.tab === "frames" && T.follow) refreshRows(true);
      else if (T.tab === "frames") updateScroll();
      if (T.tab === "ids" && now - T.lastIds > 1000) loadIds();
      if (T.tab === "graph" && !T.zoom && now - T.lastGraph > 1000) loadGraph();
    }
    if (T.tab === "trigger" && prev && JSON.stringify(prev.recording.hits) !== JSON.stringify(st.recording.hits)) renderTriggerStatus();
    T.lastGeneration = st.generation;
    T.lastFrames = st.frames;
  }
  T.timer = setTimeout(() => pollTrace(seq, false), st && st.recording.running ? 500 : 1500);
}

function showTraceHeader(st) {
  const src = $("#trace-source");
  const rec = st.recording;
  let text;
  let cls = "online-conn ok";
  if (st.source === "live") {
    text = `Live trace from ${S.online.host || "the runtime"}${st.network ? ", network " + st.network : ""}: ${TRACE_STATES[rec.state] || rec.state}`;
    if (rec.message) text += ` (${rec.message})`;
    if (rec.state === "error") cls = "online-conn error";
  } else if (st.source) {
    text = `File ${st.source}` + (st.network ? `, decoded with network ${st.network}` : "");
  } else {
    text = "No trace yet.";
  }
  const parts = [text];
  if (!rec.running && !onlineReady()) {
    parts.push(el("div", { class: "online-note", dataset: { trace: "online-hint" } },
      "Recording needs online access: set the runtime host and token in ",
      el("a", { href: "#", onclick: (e) => { e.preventDefault(); showView("online"); } }, "Online"),
      ". Opening, viewing and exporting trace files works without it."));
  }
  for (const w of st.warnings || []) parts.push(el("div", { class: "online-note warning" }, w));
  if (st.dropped) parts.push(el("div", { class: "online-note warning" },
    `The trace holds the newest ${st.limit.toLocaleString()} frames; ${st.dropped.toLocaleString()} older frames were dropped.`));
  src.className = cls;
  src.replaceChildren(...parts);
  const sm = st.summary;
  const dur = sm.first_us != null ? (sm.last_us - sm.first_us) / 1e6 : 0;
  const bits = [`${sm.frames.toLocaleString()} frames`, `${dur.toFixed(1)} s`,
    rec.running ? `${Math.round(sm.rate)} frames/s` : null,
    rec.running && sm.load != null ? `bus load ${sm.load.toFixed(1)} % (estimate)` : null,
    sm.bitrate ? `${sm.bitrate / 1000} kbit/s` : null,
    `${sm.error_frames} error frames`,
    sm.lost ? `${sm.lost} lost` : null, sm.kernel_drops ? `${sm.kernel_drops} dropped by the PLC's kernel` : null,
    st.trigger_text ? `trigger: ${st.trigger_text}${rec.hits && rec.hits.length ? ` (${rec.hits.length} hit${rec.hits.length === 1 ? "" : "s"})` : ""}` : null];
  $("#trace-stats").textContent = bits.filter(Boolean).join(" · ");
  const start = document.querySelector("[data-trace=start]");
  const stop = document.querySelector("[data-trace=stop]");
  start.disabled = rec.running;
  stop.disabled = !rec.running;
  for (const k of ["save", "export"]) document.querySelector(`[data-trace=${k}]`).disabled = !st.frames;
}

function renderTraceTab() {
  for (const b of document.querySelectorAll("[data-trace-tab]")) b.setAttribute("aria-pressed", String(b.dataset.traceTab === T.tab));
  const box = $("#trace-tab");
  if (!box) return;
  for (const p of T.plots) p.destroy();
  T.plots = [];
  box.replaceChildren();
  if (T.tab === "frames") renderFrames(box);
  else if (T.tab === "ids") { box.append(el("div", { id: "trace-ids" })); loadIds(); }
  else if (T.tab === "graph") renderGraph(box);
  else if (T.tab === "sequences") fxRenderSequences(box);
  else renderTrigger(box);
}

// -- control ----------------------------------------------------------------

async function traceStart() {
  if (T.st && T.st.frames) {
    const v = await modal(`Start a new trace? The current trace (${T.st.frames.toLocaleString()} frames) is replaced; save or export it first if you need it.`,
      [["start", "Start", true], ["cancel", "Cancel"]]);
    if (v !== "start") return;
  }
  try {
    T.st = await api("POST", "/api/trace/start", { filters: T.capFilters.map((f) => ({ id: f.id, mask: f.mask })),
      error_frames: T.errorFrames, port: diagPort() });
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
    const v = await modal(`Clear the trace (${T.st.frames.toLocaleString()} frames)?`, [["clear", "Clear", true], ["cancel", "Cancel"]]);
    if (v !== "clear") return;
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
  banner(`Opening ${file.name}…`);
  try {
    // The file as it is (traces can be hundreds of MB); decoded with the saved canopen.json.
    const net = onlineNetwork();  // the network whose nodes decode it
    const res = await fetch("/api/trace/open?name=" + encodeURIComponent(file.name) +
      (net !== null ? "&network=" + encodeURIComponent(net) : ""), {
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
    banner(`Saved ${r.frames.toLocaleString()} frames to ${r.path}.`);
  } catch (e) { banner(e.message, true); }
}

async function traceExport() {
  try {
    const body = Object.assign({ format: T.exportFormat, keys: T.chosen }, traceRange());
    const r = await api("POST", "/api/trace/export", body);
    download(r);
    banner(`Exported ${r.name}.`);
  } catch (e) { banner(e.message, true); }
}

// -- frames -----------------------------------------------------------------

function renderFrames(box) {
  const f = T.filter;
  const kinds = el("div", { class: "kind-chips" }, TRACE_KINDS.map(([k, label]) => {
    const cb = el("input", { type: "checkbox", checked: (f.kinds || []).includes(k), dataset: { traceKind: k } });
    cb.onchange = () => {
      const set = new Set(f.kinds || []);
      if (cb.checked) set.add(k); else set.delete(k);
      f.kinds = [...set];
      refreshRows(false, true);
    };
    return el("label", { class: "chip" }, cb, label);
  }));
  const input = (key, label, width, attrs) => {
    const i = el("input", Object.assign({ type: "text", spellcheck: "false", "aria-label": label, placeholder: label,
      dataset: { traceFilter: key } }, attrs || {}));
    i.style.width = width;
    i.value = f[key] != null ? f[key] : "";
    i.addEventListener("change", () => { f[key] = i.value.trim(); refreshRows(false, true); });
    return i;
  };
  const dir = el("select", { "aria-label": "Direction", dataset: { traceFilter: "dir" } },
    [["any", "Rx and Tx"], ["rx", "Rx only"], ["tx", "Tx only"]].map(([v, l]) => el("option", { value: v, selected: (f.dir || "any") === v }, l)));
  dir.onchange = () => { f.dir = dir.value; refreshRows(false, true); };
  const timeMode = el("div", { class: "segmented", role: "group", "aria-label": "Time" },
    [["rel", "Relative"], ["utc", "UTC"]].map(([v, l]) => el("button", { type: "button", "aria-pressed": String(T.timeMode === v),
      dataset: { traceTime: v }, onclick: () => { T.timeMode = v; renderTraceTab(); } }, l)));
  const follow = el("input", { type: "checkbox", checked: T.follow, dataset: { trace: "follow" } });
  follow.onchange = () => { T.follow = follow.checked; if (T.follow) refreshRows(true); };
  const list = el("div", { class: "trace-list", id: "trace-list", tabindex: "0" },
    el("div", { class: "trace-rows", id: "trace-rows" }), el("div", { class: "trace-spacer" }));
  list.addEventListener("scroll", () => {
    const atEnd = list.scrollTop + list.clientHeight >= list.scrollHeight - 2;
    if (T.follow !== atEnd && T.st && T.st.recording.running) { T.follow = atEnd; follow.checked = atEnd; }
    requestRows();
  });
  box.append(
    el("div", { class: "trace-filters" },
      el("div", { class: "row" }, input("nodes", "Nodes: 2, 23", "13ch"), input("id_from", "ID from", "9ch"),
        input("id_to", "ID to", "9ch"), dir, input("text", "Search text", "16ch"), timeMode,
        el("label", { class: "check inline", title: "Keep the newest frames in view while recording" }, follow, "Follow")),
      kinds),
    el("div", { class: "trace-head trace-row" }, ["Time", "Dir", "ID", "DLC", "Data", "Name", "Decoded"].map((h) => el("span", null, h))),
    list,
    el("div", { class: "toolbar", id: "trace-row-actions" }),
    el("div", { id: "trace-inspector", class: "fx-host", dataset: { trace: "inspector" } },
      el("p", { class: "muted" }, "Select a frame to see what every bit of it means. Up and down arrows move through the list.")));
  list.addEventListener("keydown", (e) => {
    if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
    e.preventDefault();
    T.follow = false;
    follow.checked = false;
    fxMoveSelection(e.key === "ArrowDown" ? 1 : -1);
  });
  refreshRows(T.follow && T.st && T.st.recording.running, true);
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

function firstRow() {
  const g = listGeometry();
  if (g.full <= MAX_SCROLL_PX) return Math.floor(g.list.scrollTop / ROW_H);
  const span = Math.max(1, g.height - g.list.clientHeight);
  return Math.round(g.list.scrollTop / span * Math.max(0, g.total - g.visible));
}

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
  const body = { offset: toEnd ? Math.max(0, (T.st ? T.st.frames : 0)) : offset, count: visible + 2, filter: filterBody() };
  if (atUs != null) body.at_us = Math.round(atUs);
  let r;
  try { r = await api("POST", "/api/trace/frames", body); } catch (e) { banner(e.message, true); return; }
  if (seq !== T.rowsSeq || !$("#trace-list")) return;
  T.total = r.total;
  updateScroll();
  if (toEnd) { r.offset = Math.max(0, r.total - visible); scrollToRow(r.total); }
  else if (reset && atUs == null) scrollToRow(0);
  if (r.focus != null) {
    T.selected = r.rows[r.focus - r.offset] ? r.rows[r.focus - r.offset].seq : null;
    if (T.selected != null) fxInspectSeq(T.selected);
    scrollToRow(Math.max(0, r.focus - Math.floor(visible / 2)));
    if (r.focus - Math.floor(visible / 2) !== r.offset) {
      // The window centred on the frame; fetch exactly what is now in view.
      const again = await api("POST", "/api/trace/frames", { offset: firstRow(), count: visible + 2, filter: filterBody() });
      if (seq !== T.rowsSeq) return;
      r = again;
    }
  }
  drawRows(r);
}

function drawRows(r) {
  const rows = $("#trace-rows");
  rows.replaceChildren(...r.rows.map((x) => {
    const cls = ["trace-row", "k-" + x.kind, x.seq === T.selected ? "selected" : "", x.dir === "Tx" ? "tx" : ""].join(" ");
    return el("div", { class: cls, dataset: { seq: x.seq, t: x.t_us }, onclick: () => selectRow(x) },
      el("span", null, timeText(x.t_us)), el("span", null, x.gap ? "" : x.dir),
      el("span", null, x.gap ? "" : x.err ? "ERR" : x.id + (x.rtr ? " R" : "")),
      el("span", null, x.gap || x.err ? "" : String(x.dlc)), el("span", { class: "mono" }, x.data),
      el("span", { title: x.name }, x.name), el("span", { title: x.text }, x.text));
  }));
  if (!r.rows.length) rows.append(el("div", { class: "muted trace-empty" }, T.st && T.st.frames ? "No frames match the display filter." : "No frames."));
  rowActions();
  if (T.pendingStep) {
    const step = T.pendingStep;
    T.pendingStep = 0;
    fxMoveSelection(step);
  }
}

function selectRow(x) {
  T.selected = x.seq;
  T.selectedUs = x.t_us;
  T.selectedRow = x;
  for (const r of document.querySelectorAll("#trace-rows .trace-row")) r.classList.toggle("selected", Number(r.dataset.seq) === x.seq);
  rowActions();
  fxInspectSeq(x.seq);
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
    if (x && x.seq === T.selected && !x.gap && !x.err) parts.push(el("button", { type: "button", dataset: { trace: "send-this" },
      title: "Fill the Send panel with this frame", onclick: () => sendThisFrame(x) }, "Send this frame"));
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

// -- identifiers ------------------------------------------------------------

async function loadIds() {
  T.lastIds = Date.now();
  let r;
  try { r = await api("POST", "/api/trace/ids", {}); } catch (e) { banner(e.message, true); return; }
  const box = $("#trace-ids");
  if (!box) return;
  const ms = (v) => (v == null ? "" : v.toFixed(v < 10 ? 2 : 1));
  box.replaceChildren(el("table", { class: "trace-ids" },
    el("thead", null, el("tr", null, ["ID", "Name", "Node", "Dir", "Count", "Cycle min ms", "avg ms", "max ms", "Last data"].map((h) => el("th", null, h)))),
    el("tbody", null, r.ids.length ? r.ids.map((x) => el("tr", { dataset: { traceId: x.id_text } },
      el("td", { class: "mono" }, x.id_text), el("td", null, x.name), el("td", null, x.node == null ? "" : String(x.node)),
      el("td", null, x.dir), el("td", null, x.count.toLocaleString()), el("td", null, ms(x.cycle_min_ms)),
      el("td", null, ms(x.cycle_avg_ms)), el("td", null, ms(x.cycle_max_ms)), el("td", { class: "mono" }, x.data)))
      : [el("tr", null, el("td", { colspan: 9, class: "muted" }, "No frames."))])),
  el("p", { class: "hint" }, "Cycle times come from the frames' time stamps; with an slcan adapter (CANable) they jitter by about 1 ms."));
}

// -- graph ------------------------------------------------------------------

function seriesGroups() {
  const all = (T.st ? T.st.series : []).slice();
  const out = [["Bus", [{ key: "bus.rate", label: "Frames per second", kind: "bus" }, { key: "bus.load", label: "Bus load % (estimate)", kind: "bus" }]]];
  const by = { signal: "PDO signals", status: "Status (polled)", event: "Events" };
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
  for (const [group, list] of seriesGroups()) {
    picker.append(el("h4", null, group));
    for (const s of list) {
      const cb = el("input", { type: "checkbox", checked: T.chosen.includes(s.key), dataset: { traceSeries: s.key } });
      cb.onchange = () => {
        if (cb.checked) { T.chosen.push(s.key); T.lane[s.key] = T.lane[s.key] || Math.min(LANES, T.chosen.length); }
        else T.chosen = T.chosen.filter((k) => k !== s.key);
        renderTraceTab();
      };
      const lane = el("select", { "aria-label": "Lane", title: "Lane (series in the same lane share a chart)", dataset: { traceLane: s.key },
        hidden: !T.chosen.includes(s.key) },
        Array.from({ length: LANES }, (_, k) => el("option", { value: k + 1, selected: (T.lane[s.key] || 1) === k + 1 }, "L" + (k + 1))));
      lane.onchange = () => { T.lane[s.key] = Number(lane.value); renderTraceTab(); };
      picker.append(el("div", { class: "series-item" }, el("label", { class: "check inline", title: s.key }, cb, s.label), lane));
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
        el("span", { class: "hint" }, "Drag to zoom, click to set cursor A, Shift+click for B, double-click for the whole trace.")),
      el("div", { id: "trace-plots" }), readout)));
  loadGraph();
}

function viewRange() {
  if (T.zoom) return T.zoom;
  const sm = T.st && T.st.summary;
  return sm && sm.first_us != null ? [sm.first_us, Math.max(sm.last_us, sm.first_us + 1000)] : null;
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
  const mid = (r[0] + r[1]) / 2;
  const w = (r[1] - r[0]) * f / 2;
  const sm = T.st.summary;
  if (sm.first_us != null && mid - w <= sm.first_us && mid + w >= sm.last_us) { T.zoom = null; }
  else T.zoom = [mid - w, mid + w];
  loadGraph();
}

async function loadGraph() {
  T.lastGraph = Date.now();
  const plotsBox = $("#trace-plots");
  if (!plotsBox) return;
  if (!T.chosen.length) {
    for (const p of T.plots) p.destroy();
    T.plots = [];
    plotsBox.replaceChildren(el("p", { class: "muted" }, T.st && T.st.frames ? "Choose series on the left." : "No frames yet."));
    showCursors();
    return;
  }
  const width = Math.max(300, plotsBox.clientWidth || 600);
  const range = T.zoom;
  let r;
  try {
    r = await api("POST", "/api/trace/series", { keys: T.chosen, points: width * 2,
      start_us: range ? Math.floor(range[0]) : null, end_us: range ? Math.ceil(range[1]) : null });
  } catch (e) { banner(e.message, true); return; }
  if (!$("#trace-plots") || T.tab !== "graph") return;
  T.data = r.series;
  drawPlots(width);
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
  const xmin = r ? (r[0] - t0) / 1e6 : null;
  const xmax = r ? (r[1] - t0) / 1e6 : null;
  const text = themeColor("--text");
  const line = themeColor("--line");
  const muted = themeColor("--muted");
  const height = laneKeys.length > 2 ? 150 : 200;
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
      const color = SERIES_COLORS[T.chosen.indexOf(k) % SERIES_COLORS.length];
      const ev = k.startsWith("emcy.") || k.startsWith("sdo_abort.");
      return { label: seriesLabel(k), stroke: color, width: 1.5, spanGaps: true,
        paths: ev ? () => null : uPlot.paths.stepped({ align: 1 }),
        points: { show: ev, size: 6, fill: color } };
    }));
    const opts = {
      width, height, series, legend: { show: true, live: true },
      scales: { x: { time: false, auto: !r, range: r ? () => [xmin, xmax] : undefined } },
      axes: [{ stroke: muted, grid: { stroke: line, width: 1 }, ticks: { stroke: line }, label: li === laneKeys.length - 1 ? "seconds" : undefined, labelSize: 18 },
        { stroke: muted, grid: { stroke: line, width: 1 }, ticks: { stroke: line }, size: 60 }],
      cursor: { sync: { key: "trace", setSeries: false }, drag: { x: true, y: false, setScale: false } },
      hooks: {
        setSelect: [(u) => {
          if (u.select.width < 4) return;
          const a = u.posToVal(u.select.left, "x");
          const b = u.posToVal(u.select.left + u.select.width, "x");
          u.setSelect({ left: 0, width: 0, top: 0, height: 0 }, false);
          T.justSelected = true;
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
      if (T.justSelected) { T.justSelected = false; return; }
      if (plot.cursor.left == null || plot.cursor.left < 0) return;
      const us = t0 + plot.posToVal(plot.cursor.left, "x") * 1e6;
      if (e.shiftKey) T.b = us; else T.a = us;
      redrawPlots();
    });
    plot.over.addEventListener("dblclick", () => { T.zoom = null; loadGraph(); });
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
  for (const m of (T.st && T.st.markers) || []) vline(m.time_us, m.kind === "trigger" ? themeColor("--error") : themeColor("--warn"), true);
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
    rows.length ? el("table", { class: "compare" }, el("thead", null, el("tr", null, ["Series", "A", "B", "Δ (B − A)"].map((h) => el("th", null, h)))),
      el("tbody", null, rows)) : null].filter(Boolean));
}

// -- trigger ----------------------------------------------------------------

function blankCondition(type) { return { type: type || "emcy" }; }

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
    COND_TYPES.map(([v, l]) => el("option", { value: v, selected: c.type === v }, l)));
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
    fields.push(sel("key", "Signal", sigs.length ? sigs.map((s) => [s.key, s.label]) : [["", "no PDO signals in this config"]], sigs.length ? sigs[0].key : ""),
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
  const autoFmt = el("select", { "aria-label": "Auto-save format", dataset: { traceTrig: "autosave-format" }, disabled: !d.autosave },
    TRACE_FORMATS.map(([v, l]) => el("option", { value: v, selected: d.autosave && d.autosave.format === v }, l)));
  const autoDir = el("input", { type: "text", spellcheck: "false", class: "wide", "aria-label": "Auto-save folder", dataset: { traceTrig: "autosave-folder" },
    placeholder: (T.st && T.st.traces_dir) || "", disabled: !d.autosave });
  autoDir.value = d.autosave && d.autosave.folder ? d.autosave.folder : "";
  const syncAuto = () => {
    d.autosave = auto.checked ? { format: autoFmt.value, folder: autoDir.value.trim() } : null;
    autoFmt.disabled = autoDir.disabled = !auto.checked;
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
      el("p", { class: "hint" }, "Files are named <project>-trace-<UTC time>. The default folder is the configurator's settings folder; the project's canopen folder is refused, since it travels with the PLC program.")),
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
// The Send panel (add-raw-frames-bitrate-detect): raw frames through online
// access, once or as cyclic jobs. The jobs run on the local server's own
// connection to the runtime; leaving the view or closing the page stops them.

const SEND_LOG = 20;
const SEND = {
  open: false, id: "", ext: false, rtr: false, dlc: 0, data: "", mode: "single", period: "100", count: "",
  jobs: [], log: [], timer: null, seq: 0,
};

function sendBlocked() {
  if (!onlineReady()) return "Sending needs online access: set the runtime host and token in Online.";
  if (!diagConfig().allow_changes) return "Sending needs Allow changes in Online access";
  return null;
}

function sendFrameText(f) {
  const id = String(f.id).replace(/^0x/i, "").toUpperCase();
  if (f.rtr) return `${id} remote [${f.dlc || 0}]`;
  const data = (f.data || "").trim().toUpperCase();
  return `${id} [${data ? data.split(/\s+/).length : 0}] ${data}`.trim();
}

function sendPanel() {
  const blocked = sendBlocked();
  const d = el("details", { class: "advanced", dataset: { trace: "send-panel" }, open: SEND.open },
    el("summary", null, "Send"));
  d.addEventListener("toggle", () => { SEND.open = d.open; });
  const input = (key, label, width, attrs) => {
    const i = el("input", Object.assign({ type: "text", spellcheck: "false", "aria-label": label, placeholder: label,
      dataset: { send: key } }, attrs || {}));
    i.style.width = width;
    i.value = SEND[key];
    i.addEventListener("input", () => { SEND[key] = i.value.trim(); });
    return i;
  };
  const check = (key, label) => {
    const c = el("input", { type: "checkbox", checked: SEND[key], dataset: { send: key } });
    c.onchange = () => { SEND[key] = c.checked; drawSendPanel(); };
    return el("label", { class: "check inline" }, c, " " + label);
  };
  const mode = el("select", { "aria-label": "Single or cyclic", dataset: { send: "mode" } },
    [["single", "Single"], ["cyclic", "Cyclic"]].map(([v, l]) => el("option", { value: v, selected: SEND.mode === v }, l)));
  mode.onchange = () => { SEND.mode = mode.value; drawSendPanel(); };
  const dlc = el("input", { type: "number", min: 0, max: 8, class: "short", "aria-label": "DLC", dataset: { send: "dlc" } });
  dlc.value = SEND.dlc;
  dlc.addEventListener("input", () => { SEND.dlc = Number(dlc.value); });
  const fields = el("fieldset", { class: "send-fields", disabled: !!blocked },
    el("div", { class: "row wrap" },
      el("label", { class: "inline" }, "ID (hex)", input("id", "60A", "11ch")), check("ext", "Extended"), check("rtr", "Remote"),
      SEND.rtr ? el("label", { class: "inline" }, "DLC", dlc)
        : el("label", { class: "inline" }, "Data", input("data", "40 18 10 01 00 00 00 00", "26ch"))),
    el("div", { class: "row wrap" }, mode,
      SEND.mode === "cyclic" ? [el("label", { class: "inline" }, "every", input("period", "ms", "8ch"), "ms"),
        el("label", { class: "inline" }, "count", input("count", "no limit", "10ch"))] : null,
      el("button", { type: "button", class: "primary", dataset: { send: "send" }, onclick: () => sendFrame(false) }, "Send"),
      el("button", { type: "button", dataset: { send: "stop" }, disabled: !SEND.jobs.length, onclick: () => sendStop(null) }, "Stop")));
  d.append(
    blocked ? el("p", { class: "field-msg warning", dataset: { send: "blocked" } }, blocked) : null,
    el("p", { class: "hint" }, "Frames go onto the picked network through the runtime and show in a running trace as Tx. Identifiers the network uses, and any frame while a node is OPERATIONAL, need a confirmation."),
    fields,
    sendLists());
  return d;
}

function sendLists() {
  return el("div", { class: "send-lists", dataset: { send: "lists" } },
    el("div", null, el("h4", null, "Running cyclic jobs"),
      SEND.jobs.length ? el("ul", { dataset: { send: "jobs" } }, SEND.jobs.map((j) => el("li", { dataset: { sendJob: j.job } },
        `Job ${j.job}: ${sendFrameText(j)} every ${j.period_ms} ms, ${j.sent} sent${j.count ? " of " + j.count : ""} `,
        el("button", { type: "button", class: "small", dataset: { send: "stop-job" }, onclick: () => sendStop(j) }, "Stop"))))
        : el("p", { class: "muted", dataset: { send: "jobs" } }, "None.")),
    el("div", null, el("h4", null, `Sent (last ${SEND_LOG})`),
      SEND.log.length ? el("ol", { class: "mono", dataset: { send: "sent" } }, SEND.log.map((x) => el("li", null, x)))
        : el("p", { class: "muted", dataset: { send: "sent" } }, "Nothing sent yet.")));
}

function drawSendPanel() {
  const old = document.querySelector("[data-trace=send-panel]");
  if (!old) return;
  SEND.open = old.open;  // its toggle event may not have fired yet
  old.replaceWith(sendPanel());
}

// Only the lists, so a refresh does not take the focus from a field.
function drawSendLists() {
  const old = document.querySelector("[data-send=lists]");
  if (old) old.replaceWith(sendLists());
  const stop = document.querySelector("[data-send=stop]");
  if (stop) stop.disabled = !SEND.jobs.length;
}

function sendBody(force) {
  const body = { id: SEND.id, ext: SEND.ext, rtr: SEND.rtr, port: diagPort() };
  if (SEND.rtr) body.dlc = SEND.dlc;
  else body.data = SEND.data;
  if (SEND.mode === "cyclic") {
    body.period_ms = Number(SEND.period);
    if (SEND.count) body.count = Number(SEND.count);
  }
  if (force) body.force = true;
  return body;
}

async function sendFrame(force) {
  if (!SEND.id) return banner("Enter the identifier in hex, for example 60A.", true);
  if (SEND.mode === "cyclic" && !/^\d+$/.test(SEND.period)) return banner("Enter the period in ms (10-60000).", true);
  if (SEND.mode === "cyclic" && SEND.count && !/^\d+$/.test(SEND.count)) return banner("The count is a number of frames, or empty.", true);
  const body = sendBody(force);
  let r;
  try {
    r = await api("POST", "/api/online/send_frame", body);
  } catch (e) {
    if (e.body && e.body.force && !force) {
      const v = await modal(`The runtime refused this frame: "${e.message}". Send it anyway?`,
        [["force", "Send anyway", true], ["cancel", "Cancel"]]);
      if (v === "force") return sendFrame(true);
      banner("Nothing was sent.");
      return;
    }
    banner(`Not sent: ${e.message}`, true);
    return;
  }
  const time = new Date().toLocaleTimeString();
  const text = sendFrameText(body) + (force ? " (forced)" : "");
  SEND.log.unshift(r.job !== undefined && r.job !== null ? `${time} ${text}, cyclic job ${r.job} every ${r.period_ms} ms` : `${time} ${text}`);
  SEND.log.length = Math.min(SEND.log.length, SEND_LOG);
  banner(r.job !== undefined && r.job !== null ? `Cyclic job ${r.job} started.` : "Frame sent.");
  if (r.job !== undefined && r.job !== null) {
    SEND.jobs.push({ job: r.job, id: body.id, ext: body.ext, rtr: body.rtr, dlc: body.dlc, data: body.data,
      period_ms: r.period_ms, count: r.count, sent: 0, network: onlineNetwork() });
    pollSendJobs(SEND.seq);
  }
  drawSendLists();
}

async function pollSendJobs(seq) {
  clearTimeout(SEND.timer);
  SEND.timer = null;
  if (seq !== SEND.seq || !SEND.jobs.length) return;
  SEND.timer = setTimeout(async () => {
    if (seq !== SEND.seq) return;
    let r;
    try { r = await api("POST", "/api/online/send_jobs", { port: diagPort() }); } catch (e) { r = null; }
    if (seq !== SEND.seq) return;
    if (r) {
      SEND.jobs = r.jobs;
      for (const j of r.ended) {
        if (j.reason !== "stopped") banner(`Cyclic job ${j.job} (${sendFrameText(j)}) ended: ${j.reason}, ${j.sent} sent.`, j.reason !== "count reached");
      }
      drawSendLists();
    }
    pollSendJobs(seq);
  }, 1000);
}

async function sendStop(job) {
  try {
    const r = await api("POST", "/api/online/send_stop", job ? { job: job.job, network: job.network, port: diagPort() } : { port: diagPort() });
    const stopped = r.stopped || [];
    SEND.jobs = SEND.jobs.filter((j) => job ? j.job !== job.job : false);
    banner(stopped.length ? stopped.map((s) => `Job ${s.job} stopped, ${s.sent} sent.`).join(" ") : "No job was running.");
  } catch (e) { banner(e.message, true); }
  drawSendLists();
}

// Leaving the Trace view stops the page's cyclic jobs.
function sendLeave() {
  SEND.seq++;
  clearTimeout(SEND.timer);
  SEND.timer = null;
  if (!SEND.jobs.length) return;
  SEND.jobs = [];
  api("POST", "/api/online/send_stop", { port: diagPort() }).catch(() => {});
}

// "Send this frame" from a trace row: fills the panel.
function sendThisFrame(x) {
  Object.assign(SEND, { open: true, id: x.id, ext: !!x.ext, rtr: !!x.rtr, dlc: x.dlc || 0, data: x.rtr ? "" : x.data, mode: "single" });
  drawSendPanel();
  const panel = document.querySelector("[data-trace=send-panel]");
  if (panel) panel.scrollIntoView({ block: "nearest" });
}

// Closing or reloading the page stops its jobs too (keepalive outlives the page).
window.addEventListener("pagehide", () => {
  if (!SEND.jobs.length) return;
  SEND.jobs = [];
  fetch("/api/online/send_stop", { method: "POST", keepalive: true,
    headers: { "X-CANopen-Token": TOKEN, "Content-Type": "application/json" }, body: JSON.stringify({ port: diagPort() }) });
});
