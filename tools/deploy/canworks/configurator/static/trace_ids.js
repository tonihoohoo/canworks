// The Trace tab's By identifier view (canopen-configurator: "By identifier
// view", "Live updates of the By identifier view", "Sorting the By
// identifier view", "Change marks and reference", "Silent identifiers",
// "Selection in the By identifier view"). One row per identifier, format
// and direction, patched in place from /api/trace/ids answers that carry
// only the rows changed since the last one. Loaded after trace.js.
"use strict";

const IDS_ROW_H = 24;
const IDS_LIVE_MS = 250;  // four updates a second while recording
const IDS_IDLE_MS = 1500;
const IDS_MARK_US = 1000000;  // a changed byte stays marked for a second
const IDS_COLUMNS = [
  ["dir", "Dir"], ["id", "ID"], ["name", "Name"], ["dlc", "DLC"], ["data", "Data"], ["text", "Decoded"],
  ["count", "Count"], ["cycle_last", "Cycle ms"], ["cycle_avg", "Avg ms"], ["cycle_min", "Min ms"],
  ["cycle_max", "Max ms"], ["last_seen", "Last seen"]];
const IDS_SORTABLE = new Set(["id", "dir", "name", "dlc", "count", "cycle_last", "cycle_avg", "cycle_min", "cycle_max", "last_seen"]);

const TI = {
  rows: new Map(), since: null, now_us: null, timer: null, seq: 0, paused: false, pending: new Map(),
  selected: null, hold: false, heldSeq: null, inspected: null, sort: "id", desc: false, ref: false, refUs: null,
  els: new Map(),
};

function idsReset() {
  TI.rows = new Map();
  TI.pending = new Map();
  TI.since = null;
  TI.els = new Map();
}

function idsLive() { return !!(T.st && T.st.source === "live"); }

function idsSilent(r) {
  if (r.count < 3 || r.cycle_avg_ms == null || TI.now_us == null) return false;
  return TI.now_us - r.last_us > Math.max(3 * r.cycle_avg_ms * 1000, 1000000);
}

function idsMs(v) { return v == null ? "" : v.toFixed(v < 10 ? 2 : 1); }

function idsLastSeen(r) {
  if (!idsLive()) return timeText(r.last_us);
  const age = TI.now_us == null ? 0 : Math.max(0, (TI.now_us - r.last_us) / 1e6);
  return (idsSilent(r) ? "silent " : "") + (age < 10 ? age.toFixed(1) : Math.round(age)) + " s";
}

// The bits of byte k that changed between the previous and the last frame.
function idsChangedBits(r, k) {
  if (!r.prev) return [];
  const a = parseInt((r.prev.split(" ")[k]) || "0", 16), b = parseInt((r.data.split(" ")[k]) || "0", 16);
  const out = [];
  for (let bit = 0; bit < 8; bit++) if (((a ^ b) >> bit) & 1) out.push(bit);
  return out;
}

function idsChangeText(r) {
  const parts = [];
  const bytes = r.data ? r.data.split(" ") : [];
  bytes.forEach((h, k) => {
    if (!((r.changed >> k) & 1)) return;
    const bits = idsChangedBits(r, k);
    const prev = r.prev ? r.prev.split(" ")[k] : "--";
    parts.push(`byte ${k}: ${prev} → ${h}` + (bits.length ? ` (bit${bits.length > 1 ? "s" : ""} ${bits.join(", ")} changed)` : ""));
  });
  return parts.length ? "Changed since the previous frame: " + parts.join("; ") : "No change since the previous frame.";
}

function idsSortValue(r, key) {
  switch (key) {
    case "id": return [r.id < 0 ? 1 : 0, r.ext ? 1 : 0, r.id, r.dir];
    case "dir": return r.dir;
    case "name": return (r.name || "").toLowerCase();
    case "dlc": return r.dlc;
    case "count": return r.count;
    case "cycle_last": return r.cycle_last_ms == null ? Infinity : r.cycle_last_ms;
    case "cycle_avg": return r.cycle_avg_ms == null ? Infinity : r.cycle_avg_ms;
    case "cycle_min": return r.cycle_min_ms == null ? Infinity : r.cycle_min_ms;
    case "cycle_max": return r.cycle_max_ms == null ? Infinity : r.cycle_max_ms;
    case "last_seen": return -r.last_us;
    default: return 0;
  }
}

function idsCompare(a, b) {
  const va = idsSortValue(a, TI.sort), vb = idsSortValue(b, TI.sort);
  let c = 0;
  if (Array.isArray(va)) {
    for (let i = 0; i < va.length && !c; i++) c = va[i] < vb[i] ? -1 : va[i] > vb[i] ? 1 : 0;
  } else c = va < vb ? -1 : va > vb ? 1 : 0;
  if (!c && TI.sort !== "id") c = idsCompare.byId(a, b);
  return TI.desc ? -c : c;
}
idsCompare.byId = (a, b) => (a.id - b.id) || ((a.ext ? 1 : 0) - (b.ext ? 1 : 0)) || (a.dir < b.dir ? -1 : a.dir > b.dir ? 1 : 0);

function idsOrdered() { return [...TI.rows.values()].sort(idsCompare); }

function renderIds(box) {
  idsReset();
  const head = el("div", { class: "ids-row ids-head", role: "row" }, IDS_COLUMNS.map(([key, label]) => {
    const sortable = IDS_SORTABLE.has(key);
    const sorted = TI.sort === key;
    return el("div", { role: "columnheader", class: "ids-c-" + key,
      "aria-sort": sortable ? (sorted ? (TI.desc ? "descending" : "ascending") : "none") : null },
      sortable ? el("button", { type: "button", class: "ids-sort", dataset: { idsSort: key },
        title: `Sort by ${label.toLowerCase()}`, onclick: () => idsSetSort(key) }, label + (sorted ? (TI.desc ? " ▼" : " ▲") : "")) : label);
  }));
  const grid = el("div", { class: "ids-grid", id: "ids-grid", role: "grid", tabindex: "0", "aria-label": "Identifiers",
    "aria-rowcount": "0", dataset: { trace: "ids" } },
    el("div", { role: "rowgroup", class: "ids-headgroup" }, head),
    // The grid is the scroll box (its header row sticks), so the one tab stop that takes the arrow keys also scrolls.
    el("div", { class: "ids-scroll", id: "ids-scroll" },
      el("div", { role: "rowgroup", class: "ids-body", id: "ids-body" }), el("div", { class: "ids-spacer" })));
  grid.addEventListener("keydown", idsKey);
  grid.addEventListener("scroll", () => idsDraw());
  const pause = idsPauseLabel(el("button", { type: "button", dataset: { ids: "pause" }, onclick: () => idsPause(!TI.paused) }));
  box.append(
    el("div", { class: "toolbar ids-tools" },
      el("button", { type: "button", dataset: { ids: "set-ref" }, onclick: () => idsReference(idsLive() ? "now" : TI.selectedSeq()),
        title: "Keep the bytes that differ from the data each identifier has now marked" }, "Set reference"),
      el("button", { type: "button", dataset: { ids: "clear-ref" }, onclick: () => idsReference(null), disabled: "No reference is set." }, "Clear reference"),
      pause,
      el("span", { class: "muted", id: "ids-status", role: "status", dataset: { ids: "status" } })),
    grid,
    el("p", { class: "ids-change muted", id: "ids-change", "aria-live": "polite", dataset: { ids: "change" } }),
    el("div", { class: "toolbar", id: "ids-actions", dataset: { ids: "actions" } }));
  idsActions();
  idsPoll(++TI.seq, true);
}

// A file's reference is the frame the inspector shows, else the trace's end.
TI.selectedSeq = () => {
  if (T.selected != null) return T.selected;
  const r = TI.rows.get(TI.selected);
  return r ? r.seq : "now";
};

async function idsSetSort(key) {
  if (TI.sort === key) TI.desc = !TI.desc;
  else { TI.sort = key; TI.desc = false; }
  tracePrefs({ sort: TI.sort, sort_desc: TI.desc });
  const box = $("#trace-tab .trace-split-view") || $("#trace-tab");
  for (const h of document.querySelectorAll(".ids-head [role=columnheader]")) {
    const btn = h.querySelector("button");
    if (!btn) continue;
    const k = btn.dataset.idsSort;
    h.setAttribute("aria-sort", k === TI.sort ? (TI.desc ? "descending" : "ascending") : "none");
    btn.textContent = IDS_COLUMNS.find(([c]) => c === k)[1] + (k === TI.sort ? (TI.desc ? " ▼" : " ▲") : "");
  }
  if (box) idsDraw();
}

// The button says what pressing it does, so it has no pressed state.
function idsPauseLabel(b) {
  b.textContent = TI.paused ? "Resume view" : "Pause view";
  b.title = TI.paused ? "Show the waiting updates and keep updating the table" : "Stop updating the table; recording continues";
  return b;
}

function idsPause(on) {
  TI.paused = on;
  const b = document.querySelector("[data-ids=pause]");
  if (b) idsPauseLabel(b);
  if (!on && TI.pending.size) {
    for (const [k, r] of TI.pending) TI.rows.set(k, r);
    TI.pending = new Map();
    idsDraw();
  }
  idsStatus();
}

function idsStatus() {
  const s = $("#ids-status");
  if (!s) return;
  const parts = [`${TI.rows.size} identifier${TI.rows.size === 1 ? "" : "s"}`];
  if (TI.ref) parts.push(`reference at ${secText(TI.refUs)}`);
  if (TI.paused) parts.push(`paused, ${TI.pending.size} update${TI.pending.size === 1 ? "" : "s"} waiting`);
  s.textContent = parts.join(" · ");
  const clear = document.querySelector("[data-ids=clear-ref]");
  if (clear) Icons.setDisabled(clear, !TI.ref && "No reference is set.");
}

async function idsReference(at) {
  try {
    const r = await api("POST", "/api/trace/ids/reference", { at, filter: filterBody() });
    idsApply(r, true);
    banner(at === null ? "Reference cleared." : "Reference set: bytes that differ from it stay marked.");
  } catch (e) { banner(e.message, true); }
}

function idsPoll(seq, first) {
  clearTimeout(TI.timer);
  if (seq !== TI.seq) return;
  (async () => {
    let r = null;
    try {
      r = await api("POST", "/api/trace/ids", { since: TI.since, filter: filterBody() });
    } catch (e) { if (first) banner(e.message, true); }
    if (seq !== TI.seq || !$("#ids-grid")) return;
    if (r) idsApply(r, false);
    const running = T.st && T.st.recording && T.st.recording.running;
    TI.timer = setTimeout(() => idsPoll(seq, false), running ? IDS_LIVE_MS : IDS_IDLE_MS);
  })();
}

function idsStop() {
  TI.seq++;
  clearTimeout(TI.timer);
}

function idsApply(r, force) {
  TI.since = { generation: r.generation, rev: r.rev, filter: r.filter };
  TI.now_us = r.now_us;
  TI.ref = r.reference;
  TI.refUs = r.reference_us;
  if (r.reset) {
    TI.rows = new Map();
    TI.pending = new Map();
  }
  const target = TI.paused && !r.reset && !force ? TI.pending : TI.rows;
  for (const x of r.ids) target.set(x.key, x);
  if (TI.selected && !TI.rows.has(TI.selected) && r.reset) TI.selected = null;
  if (!TI.paused || r.reset || force) idsDraw();
  idsStatus();
  idsFollow();
}

// The inspector follows the selected identifier's newest frame unless held.
function idsFollow() {
  const r = TI.rows.get(TI.selected);
  if (!r || TI.hold) return;
  if (TI.inspected !== r.seq) {
    TI.inspected = r.seq;
    T.selected = r.seq;
    T.selectedUs = r.last_us;
    fxInspectSeq(r.seq);
  }
  const c = $("#ids-change");
  if (c) c.textContent = idsChangeText(r);
}

function idsGeometry() {
  const sc = $("#ids-grid");
  return { sc, visible: sc ? Math.max(1, Math.ceil(sc.clientHeight / IDS_ROW_H) + 1) : 1 };
}

function idsDraw() {
  const body = $("#ids-body");
  if (!body) return;
  const list = idsOrdered();
  const g = idsGeometry();
  const grid = $("#ids-grid");
  grid.setAttribute("aria-rowcount", String(list.length + 1));
  const first = Math.max(0, Math.min(Math.floor(g.sc.scrollTop / IDS_ROW_H), list.length - g.visible + 1));
  const slice = list.slice(first, first + g.visible);
  // The rows in view lie over the spacer, which is as tall as the whole table.
  g.sc.querySelector(".ids-spacer").style.height = list.length * IDS_ROW_H + "px";
  const keep = new Set(slice.map((r) => r.key));
  for (const [k, e] of TI.els) if (!keep.has(k)) { e.remove(); TI.els.delete(k); }
  slice.forEach((r, i) => {
    let e = TI.els.get(r.key);
    if (!e) {
      e = el("div", { role: "row", class: "ids-row", id: "ids-r-" + r.key, dataset: { idsKey: r.key, traceId: r.id_text },
        onclick: () => idsSelect(r.key, false, true) });
      TI.els.set(r.key, e);
    }
    idsFill(e, r, first + i);
    if (body.children[i] !== e) body.insertBefore(e, body.children[i] || null);
  });
  while (body.children.length > slice.length) body.lastChild.remove();
  body.style.transform = `translateY(${first * IDS_ROW_H}px)`;
  if (!list.length && !body.querySelector(".trace-empty")) {
    body.append(el("div", { role: "row", class: "trace-empty" }, el("div", { role: "gridcell", class: "muted" },
      T.st && T.st.frames ? "No identifiers match the display filter." : "No frames yet. Press Start, or open a trace file.")));
  }
  if (TI.selected && TI.els.has(TI.selected)) grid.setAttribute("aria-activedescendant", "ids-r-" + TI.selected);
  else grid.removeAttribute("aria-activedescendant");
}

function idsFill(e, r, index) {
  const silent = idsSilent(r);
  e.className = ["ids-row", silent ? "silent" : "", r.ref_new ? "ref-new" : "", r.dir === "Tx" ? "tx" : "",
    r.key === TI.selected ? "selected" : "", "k-" + (r.kind || "other")].filter(Boolean).join(" ");
  e.setAttribute("aria-rowindex", String(index + 2));
  e.setAttribute("aria-selected", String(r.key === TI.selected));
  const bytes = r.data ? r.data.split(" ") : [];
  const marks = [];
  const data = el("div", { role: "gridcell", class: "ids-c-data mono", title: idsChangeText(r) }, bytes.map((h, k) => {
    const cls = [];
    const at = r.changed_at ? r.changed_at[k] : null;
    if (at != null && TI.now_us != null && TI.now_us - at < IDS_MARK_US) { cls.push("chg"); marks.push(k); }
    if (r.ref_diff != null && (r.ref_diff >> k) & 1) cls.push("ref");
    if (r.static && (r.static >> k) & 1) cls.push("static");
    return el("span", { class: cls.join(" ") || null, dataset: { byte: k } }, h);
  }));
  const label = [r.ref_new ? "new since the reference" : "", silent ? "silent" : ""].filter(Boolean).join(", ");
  const cells = [
    el("div", { role: "gridcell", class: "ids-c-dir" }, r.id < 0 ? "" : r.dir),
    el("div", { role: "gridcell", class: "ids-c-id mono" }, r.id_text),
    el("div", { role: "gridcell", class: "ids-c-name", title: r.name }, r.name + (label ? ` (${label})` : ""), assumedTag(r.source)),
    el("div", { role: "gridcell", class: "ids-c-dlc num" }, r.id < 0 ? "" : String(r.dlc)),
    data,
    el("div", { role: "gridcell", class: "ids-c-text", title: r.text }, r.text || ""),
    el("div", { role: "gridcell", class: "ids-c-count num" }, r.count.toLocaleString()),
    el("div", { role: "gridcell", class: "ids-c-cycle_last num" }, idsMs(r.cycle_last_ms)),
    el("div", { role: "gridcell", class: "ids-c-cycle_avg num" }, idsMs(r.cycle_avg_ms)),
    el("div", { role: "gridcell", class: "ids-c-cycle_min num" }, idsMs(r.cycle_min_ms)),
    el("div", { role: "gridcell", class: "ids-c-cycle_max num" }, idsMs(r.cycle_max_ms)),
    el("div", { role: "gridcell", class: "ids-c-last_seen num" }, idsLastSeen(r))];
  e.replaceChildren(...cells);
}

// `open`: a click or Enter, which opens a closed inspector (the arrow keys don't).
function idsSelect(key, scroll, open) {
  TI.selected = key;
  TI.inspected = null;
  for (const [k, e] of TI.els) {
    e.classList.toggle("selected", k === key);
    e.setAttribute("aria-selected", String(k === key));
  }
  const grid = $("#ids-grid");
  if (grid) grid.setAttribute("aria-activedescendant", "ids-r-" + key);
  if (scroll) {
    const list = idsOrdered();
    const i = list.findIndex((r) => r.key === key);
    const g = idsGeometry();
    if (g.sc && i >= 0) {
      const top = i * IDS_ROW_H;
      if (top < g.sc.scrollTop) g.sc.scrollTop = top;
      // + one row: the sticky header row sits above the rows in the same scroll box.
      else if (top + 2 * IDS_ROW_H > g.sc.scrollTop + g.sc.clientHeight) g.sc.scrollTop = top + 2 * IDS_ROW_H - g.sc.clientHeight;
      idsDraw();
    }
  }
  TI.hold = false;  // a newly picked row shows its newest frame
  idsActions();
  if (open && !T.inspector) traceInspector(true);
  idsFollow();
  if (open) traceRevealSplit();
}

function idsKey(e) {
  const list = idsOrdered();
  if (!list.length) return;
  const g = idsGeometry();
  const page = Math.max(1, g.visible - 2);
  if (e.key === "Enter" && TI.selected) { e.preventDefault(); idsSelect(TI.selected, false, true); return; }
  const step = { ArrowDown: 1, ArrowUp: -1, PageDown: page, PageUp: -page, Home: -Infinity, End: Infinity }[e.key];
  if (step === undefined) return;
  e.preventDefault();
  let k = list.findIndex((r) => r.key === TI.selected);
  if (k < 0) k = step > 0 ? -1 : list.length;
  const next = step === -Infinity ? 0 : step === Infinity ? list.length - 1 : Math.max(0, Math.min(list.length - 1, k + step));
  idsSelect(list[next].key, true);
}

function idsActions() {
  const bar = $("#ids-actions");
  if (!bar) return;
  const r = TI.rows.get(TI.selected);
  if (!r) {
    bar.replaceChildren(el("span", { class: "muted" }, "Select a row to see its newest frame. Up and down arrows, Page Up, Page Down, Home and End move through the table."));
    return;
  }
  const hold = el("button", { type: "button", dataset: { ids: "hold" }, "aria-pressed": String(TI.hold),
    title: "Keep the inspector on the frame it shows while the row keeps updating",
    onclick: () => { TI.hold = !TI.hold; hold.setAttribute("aria-pressed", String(TI.hold)); if (!TI.hold) { TI.inspected = null; idsFollow(); } } }, "Hold frame");
  const parts = [el("span", { class: "muted" }, `${r.id_text} ${r.name || ""}`.trim()), hold];
  if (r.id >= 0) {
    parts.push(el("button", { type: "button", dataset: { ids: "show-frames" }, onclick: () => {
      Object.assign(T.filter, { id_from: r.id_text, id_to: r.id_text });
      T.follow = false;
      traceShowTab("frames");
    } }, "Show frames"));
    // The row keeps updating: the buttons take its newest frame when pressed.
    const now = () => TI.rows.get(r.key) || r;
    parts.push(el("button", { type: "button", dataset: { ids: "explain" },
      onclick: () => traceExplainInLab(TI.hold && TI.inspected != null ? TI.inspected : now().seq) }, "Explain in Frame lab"));
    parts.push(sendButton(() => { const x = now(); return { id: x.id_text, ext: x.ext, rtr: false, data: x.data, dlc: x.dlc, name: x.name }; }));
    const keys = ((T.st && T.st.series) || []).filter((s) => r.name && s.kind === "signal" && s.key.startsWith(r.name + ".")).map((s) => s.key);
    if (keys.length) parts.push(el("button", { type: "button", dataset: { ids: "graph" }, onclick: () => {
      for (const k of keys) if (!T.chosen.includes(k)) T.chosen.push(k);
      traceShowTab("graph");
    } }, "Graph signals"));
  }
  bar.replaceChildren(...parts);
}
