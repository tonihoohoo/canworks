// CANopen configurator page. Holds the draft config; every check, suggestion
// and write goes through the local server (server.py), which uses the same
// Python modules as canworks-deploy.
"use strict";

const TOKEN = document.querySelector('meta[name="canworks-token"]').content;
const BITRATES = [10000, 20000, 50000, 125000, 250000, 500000, 800000, 1000000];
// A new network's bit rate per protocol (spec "Defaults of a new network").
const DEFAULT_BITRATE = { canopen: 500000, j1939: 250000, none: 500000 };
// A new CANopen master: node ID 1, no SYNC until the user turns it on.
function newMaster() { return { node_id: 1 }; }
// Switching protocol moves a rate still at the old protocol's default to
// the new one's; a rate the user chose stays.
function switchDefaultRate(net, from, to) {
  if (net.adapter && net.adapter.bitrate === DEFAULT_BITRATE[from || "canopen"]) net.adapter.bitrate = DEFAULT_BITRATE[to || "canopen"];
}
const TYPES = ["BOOLEAN", "INTEGER8", "INTEGER16", "INTEGER32", "INTEGER64", "UNSIGNED8", "UNSIGNED16",
  "UNSIGNED32", "UNSIGNED64", "REAL32", "REAL64"];

const S = {
  state: null,      // last /api/state
  model: null,      // the draft: { top, networks, diagnostics } (see toModel)
  net: 0,           // the open network tab
  config: null,     // the open network of the draft (adapter, master, nodes)
  dirty: false,
  view: "bus",      // "bus" | "node:<i>" | "declarations" | "online" | "nodes" (commissioning) | "trace" | "simulation"
  check: null,      // last /api/check
  objectFilter: "",
  sdoFilter: "",
  sdoShowAll: false,  // the startup SDO picker lists every writable object
  varFilter: "",
  varDirection: "read",  // the SDO variable picker: "read" or "write"
  checkTimer: null,
  checkSeq: 0,
  undo: [],         // draft snapshots before each edit (see changed), newest last
  redo: [],
  lastClean: null,  // the draft as it was after the last edit (the next snapshot)
  sectionOpen: {},  // node page sections the user opened or closed by hand
  pickerOpen: {},   // "input" / "output": the object picker of a PDO direction is open
};

const $ = (sel) => document.querySelector(sel);

function el(tag, attrs, ...children) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === undefined || v === null || v === false) continue;
    if (k === "class") e.className = v;
    else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
    else if (k === "dataset") Object.assign(e.dataset, v);
    // disabled: a reason string disables the control and says why (tooltip and description).
    else if (k === "disabled" && typeof v === "string") { e.disabled = true; e.title = v; e.setAttribute("aria-description", v); e.dataset.disabledReason = v; }
    else if (v === true) e.setAttribute(k, "");
    else e.setAttribute(k, v);
  }
  for (const c of children.flat(Infinity)) {
    if (c === null || c === undefined || c === false) continue;
    e.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return e;
}

// -- selected rows (row-highlight-and-list-resize) --------------------------
// Every table whose rows are items gets one selected row, shown the same way
// everywhere (.row-selected: a wash and an accent bar, aria-current). A click
// anywhere on a row, or the focus moving into it, selects it; Escape clears.
// The selection lives here, not in the page, so the page's re-renders keep
// it: a list is named by where its table sits, a row by data-sel, else its
// first cell's text, else its place. Not saved.
// Tables that are not item lists, or that keep their own selection.
const LIST_SKIP = "table.online-bus, table.fx-bytes, table.raw-grid, table.fx-table, table.raw-table, table.od-tree, table[data-no-select]";
const LIST_SEL = new Map();
function listIdOf(table) {
  if (table.dataset.selList) return table.dataset.selList;
  const ctx = table.closest("[data-path], [data-picker], [data-node-tab-panel], dialog, section[id], [id]");
  const sig = [ctx ? (ctx.dataset.path || ctx.dataset.picker || ctx.dataset.nodeTabPanel || ctx.id || ctx.tagName) : "",
    table.className, JSON.stringify(Object.assign({}, table.dataset))].join("|");
  const peers = [...(ctx || document).querySelectorAll("table")].filter((t) => t.className === table.className
    && JSON.stringify(Object.assign({}, t.dataset)) === JSON.stringify(Object.assign({}, table.dataset)));
  return sig + "|" + Math.max(0, peers.indexOf(table));
}
function listRowKey(tr) {
  if (tr.dataset.sel) return tr.dataset.sel;
  const c = tr.cells[0];
  const t = c && !c.querySelector("input, select, textarea") ? c.textContent.trim() : "";
  return t ? "t:" + t : "i:" + [...tr.parentElement.children].indexOf(tr);
}
function listRowAt(target) {
  const tr = target && target.closest && target.closest("tbody tr");
  if (!tr) return null;
  const table = tr.closest("table");
  return table && !table.matches(LIST_SKIP) && tr.parentElement.parentElement === table ? tr : null;
}
function markListRow(table) {
  const key = LIST_SEL.get(listIdOf(table));
  for (const tr of table.tBodies.length ? [...table.tBodies].flatMap((b) => [...b.rows]) : []) {
    const on = key !== undefined && listRowKey(tr) === key;
    if (on === tr.classList.contains("row-selected")) continue;
    tr.classList.toggle("row-selected", on);
    if (on) tr.setAttribute("aria-current", "true"); else tr.removeAttribute("aria-current");
  }
}
function pickListRow(tr) {
  const table = tr.closest("table");
  const list = listIdOf(table), key = listRowKey(tr);
  if (LIST_SEL.get(list) === key && tr.classList.contains("row-selected")) return;
  LIST_SEL.set(list, key);
  markListRow(table);
}
let listScan = 0;
function scanListRows() {
  if (listScan) return;
  listScan = requestAnimationFrame(() => {
    listScan = 0;
    if (!LIST_SEL.size) return;
    for (const t of document.querySelectorAll("table")) if (!t.matches(LIST_SKIP) && t.querySelector("tbody tr")) markListRow(t);
  });
}
document.addEventListener("pointerdown", (ev) => { const tr = listRowAt(ev.target); if (tr) pickListRow(tr); }, true);
document.addEventListener("focusin", (ev) => { const tr = listRowAt(ev.target); if (tr) pickListRow(tr); });
document.addEventListener("keydown", (ev) => {
  if (ev.key !== "Escape" || ev.target.closest("input, select, textarea")) return;
  const tr = listRowAt(ev.target);
  if (!tr || !tr.classList.contains("row-selected")) return;
  const table = tr.closest("table");
  LIST_SEL.delete(listIdOf(table));
  markListRow(table);
});
new MutationObserver(scanListRows).observe(document.documentElement, { childList: true, subtree: true });

// -- resize bars --------------------------------------------------------------
// A bar under a list or graph that makes it taller or shorter: drag it, or
// Up and Down by 40 px when it has the focus; double-click for the default.
// get() is the height now, set(h, done) sets one, reset() the default;
// range() is the [lowest, highest] height.
function sizeBar(label, data, get, set, reset, range, cls) {
  const bar = el("div", { class: cls || "size-bar", role: "separator", tabindex: "0", "aria-orientation": "horizontal",
    "aria-label": label, title: label + ": drag, or double-click for the default height", dataset: data });
  const show = () => {
    const [lo, hi] = range();
    bar.setAttribute("aria-valuemin", String(lo));
    bar.setAttribute("aria-valuemax", String(hi));
    bar.setAttribute("aria-valuenow", String(Math.round(Math.max(lo, Math.min(hi, get() || 0)))));
  };
  bar.addEventListener("pointerdown", (e) => {
    if (e.button !== 0) return;
    e.preventDefault();
    bar.setPointerCapture(e.pointerId);
    const y0 = e.clientY;
    const h0 = get();
    const move = (ev) => { set(h0 + ev.clientY - y0, false); show(); };
    const up = () => {
      for (const [n, f] of [["pointermove", move], ["pointerup", up], ["pointercancel", up]]) bar.removeEventListener(n, f);
      set(get(), true);
      show();
    };
    for (const [n, f] of [["pointermove", move], ["pointerup", up], ["pointercancel", up]]) bar.addEventListener(n, f);
  });
  bar.addEventListener("keydown", (e) => {
    const d = { ArrowUp: -40, ArrowDown: 40 }[e.key];
    if (!d) return;
    e.preventDefault();
    set(get() + d, true);
    show();
  });
  bar.addEventListener("dblclick", () => { reset(); show(); });
  requestAnimationFrame(show);
  return bar;
}

// A list box the user can make taller or shorter: any element with
// data-box="<kind>" (and data-box-label) gets a resize bar right after it.
// One height per kind of box on this PC (ui.json box_heights), so every
// node's picker of that kind opens at the height last chosen.
const BOX_RANGE = [120, 3000];
S.boxHeights = S.boxHeights || {};
let boxSaves = Promise.resolve();
function boxBar(box) {
  const kind = box.dataset.box;
  box.dataset.boxReady = "1";
  const h = S.boxHeights[kind];
  box.style.maxHeight = h ? h + "px" : "";
  const clamp = (v) => Math.round(Math.max(BOX_RANGE[0], Math.min(BOX_RANGE[1], v)));
  // One save at a time and in order, so the last height chosen is the one kept.
  const save = () => {
    const heights = { ...S.boxHeights };
    boxSaves = boxSaves.then(() => api("POST", "/api/ui", { box_heights: heights })).catch(() => {});
    return boxSaves;
  };
  const all = () => document.querySelectorAll(`[data-box="${kind}"]`);
  box.after(sizeBar("Resize " + (box.dataset.boxLabel || "the list"), { boxBar: kind }, () => box.getBoundingClientRect().height,
    (v, done) => {
      S.boxHeights[kind] = clamp(v);
      for (const b of all()) b.style.maxHeight = S.boxHeights[kind] + "px";
      if (done) save();
    },
    () => { delete S.boxHeights[kind]; for (const b of all()) b.style.maxHeight = ""; save(); },
    () => BOX_RANGE));
}
function applyBoxHeights() {
  for (const b of document.querySelectorAll("[data-box]")) {
    const h = S.boxHeights[b.dataset.box];
    b.style.maxHeight = h ? h + "px" : "";
  }
}
let boxScan = 0;
new MutationObserver(() => {
  if (boxScan) return;
  boxScan = requestAnimationFrame(() => {
    boxScan = 0;
    for (const b of document.querySelectorAll("[data-box]:not([data-box-ready])")) boxBar(b);
  });
}).observe(document.documentElement, { childList: true, subtree: true });
document.addEventListener("DOMContentLoaded", () => { for (const b of document.querySelectorAll("[data-box]:not([data-box-ready])")) boxBar(b); });

const JOB_ROUTES = /^\/api\/(online\/(scan|scan_stop|lss_find|backup|compare|restore|restore_plan|configure\w*|od_read|job|pdo_test_start|pdo_test_stop|sync_start|sync_stop|send_frame|send_stop)|trace\/(start|stop))$/;
async function api(method, path, body) {
  // After Quit nothing answers: the page's timers wait for good (life.js).
  if (typeof LIFE !== "undefined" && LIFE.stopped) return new Promise(() => {});
  // Requests to the runtime name the picked network; the server passes it
  // on only to a plugin that runs several.
  const net = onlineNetwork();
  if (net !== null && body && body.network === undefined && (path.startsWith("/api/online/") || path.startsWith("/api/trace/") || path.startsWith("/api/sim/"))) {
    body = Object.assign({ network: net }, body);
  }
  // Simulated devices are those of the connection in the connection bar:
  // the runtime's unless the CANopen simulator is the connection.
  if (body && body.target === undefined && path.startsWith("/api/sim/") && path !== "/api/sim/settings" && !S.simOn) {
    body = Object.assign({ target: "runtime" }, body);
  }
  const res = await fetch(path, {
    method,
    headers: Object.assign({ "X-CANopen-Token": TOKEN }, body ? { "Content-Type": "application/json" } : {}),
    body: body ? JSON.stringify(body) : undefined,
  });
  let data = {};
  try { data = await res.json(); } catch (e) { /* empty body */ }
  // The online status of a runtime or adapter that does not answer comes as
  // { reachable: false, error, kind }: an error to the callers, like any other.
  const ok = res.ok && !(data && data.reachable === false);
  if (method === "POST" && typeof commLogApi === "function") commLogApi(path, body, ok, data);
  // A job was started or stopped: the status bar (jobs.js) looks at once.
  if (method === "POST" && typeof jobsKick === "function" && JOB_ROUTES.test(path)) jobsKick();
  if (!ok) {
    const err = new Error(data.error || res.statusText);
    err.status = res.ok ? 502 : res.status;
    err.body = data;
    throw err;
  }
  return data;
}

// A confirmation. buttons: [value, label, options] where options is true
// (the primary button) or { primary, danger }. The safe choice, the button
// with value "cancel", is always drawn first and gets focus, so Enter never
// removes, discards or overwrites anything; a dialog with a form focuses
// its first field instead, and one with choice buttons (data-value) in its
// extra part the first choice. Escape resolves null. One cancel listener is
// wired in wire().
let modalResolve = null;
function modal(text, buttons, extra) {
  const dlg = $("#modal");
  $("#modal-text").textContent = text;
  const ex = $("#modal-extra");
  ex.replaceChildren(...(extra ? [extra] : []));
  const menu = $("#modal-buttons");
  menu.replaceChildren();
  if (modalResolve) modalResolve(null);
  const order = buttons.filter(([v]) => v === "cancel").concat(buttons.filter(([v]) => v !== "cancel"));
  return new Promise((resolve) => {
    modalResolve = resolve;
    const done = (v) => { modalResolve = null; dlg.close(); resolve(v); };
    for (const [value, label, opts] of order) {
      const o = opts === true ? { primary: true } : opts || {};
      menu.append(el("button", { type: "button", class: [o.primary ? "primary" : "", o.danger ? "danger" : ""].join(" ").trim() || null,
        hidden: o.hidden || null, dataset: { value }, onclick: () => done(value) }, label));
    }
    // Choice buttons in the extra part (data-value) answer like the menu's.
    const picks = extra && extra.querySelectorAll ? [...extra.querySelectorAll("button[data-value]")] : [];
    for (const b of picks) b.onclick = () => done(b.dataset.value);
    if (!dlg.open) dlg.opener = document.activeElement;
    dlg.showModal();
    const fields = "input:not([type=checkbox]), select, textarea";
    const field = !extra || !extra.querySelector ? null : extra.matches(fields) ? extra : extra.querySelector(fields);
    (field || picks[0] || menu.firstElementChild).focus();
  });
}

// The dialog just answered, shown again while its request runs: one
// disabled button with `label`, Escape ignored. Returns the call that closes it.
function modalWorking(label) {
  const dlg = $("#modal");
  $("#modal-buttons").replaceChildren(el("button", { type: "button", class: "primary", disabled: true,
    dataset: { value: "working" } }, label));
  dlg.dataset.working = "1";
  if (!dlg.open) dlg.showModal();
  return () => { delete dlg.dataset.working; if (dlg.open) dlg.close(); };
}

// A control that runs a request: disabled with a busy label until the
// request settles, so a second click meanwhile does nothing.
async function busy(button, label, fn) {
  if (!button || button.dataset.busy) return undefined;
  // Only the caption changes: a file button keeps its input.
  const node = [...button.childNodes].find((c) => c.nodeType === Node.TEXT_NODE && c.textContent.trim()) || button;
  const text = node.textContent;
  const wasDisabled = button.disabled;
  const hadFocus = document.activeElement === button;
  button.dataset.busy = "1";
  button.disabled = true;
  button.classList.add("busy");
  button.setAttribute("aria-busy", "true");
  node.textContent = label;
  try { return await fn(); } finally {
    delete button.dataset.busy;
    node.textContent = text;
    button.disabled = wasDisabled;
    button.classList.remove("busy");
    button.removeAttribute("aria-busy");
    // Disabling dropped the keyboard focus: it comes back, or goes next door when the button is gone or disabled.
    if (hadFocus && (document.activeElement === document.body || !document.activeElement)) {
      if (button.isConnected && !button.disabled && button.offsetParent !== null) button.focus();
      else if (button.isConnected) focusNear(button);
    }
  }
}

// A tab list: items [key, label], Left/Right/Home/End move the selection,
// each tab names the panel it controls (`panel` is the content host's id).
function tabs(items, active, onPick, opts) {
  opts = opts || {};
  const list = el("div", { class: opts.class || "tabs", role: "tablist", "aria-label": opts.label || null });
  const buttons = items.map(([key, label]) => el("button", {
    type: "button", role: "tab", id: opts.panel ? `${opts.panel}-tab-${key}` : null, class: (opts.tab || "tab") + (key === active ? " active" : ""),
    "aria-selected": String(key === active), "aria-controls": opts.panel || null, tabindex: key === active ? "0" : "-1",
    dataset: Object.assign({}, opts.dataset ? { [opts.dataset]: key } : {}),
    onclick: (e) => {
      const had = document.activeElement === e.currentTarget, id = e.currentTarget.id;
      onPick(key);
      // A pick that re-renders the list keeps the focus on the picked tab.
      if (had && id && !e.currentTarget.isConnected) { const fresh = document.getElementById(id); if (fresh) fresh.focus(); }
    },
  }, label));
  list.append(...buttons);
  list.addEventListener("keydown", (e) => {
    const k = buttons.indexOf(document.activeElement);
    if (k < 0) return;
    const next = { ArrowRight: k + 1, ArrowLeft: k - 1, Home: 0, End: buttons.length - 1 }[e.key];
    if (next === undefined) return;
    e.preventDefault();
    const b = buttons[(next + buttons.length) % buttons.length];
    b.focus();
    onPick(items[buttons.indexOf(b)][0]);
    // A pick that re-renders the list keeps the focus on the picked tab.
    if (b.id && !b.isConnected) { const fresh = document.getElementById(b.id); if (fresh) fresh.focus(); }
  });
  return list;
}

// Marks the tab list's selected tab and its panel after a pick without a re-render.
function selectTab(list, key, dataset) {
  for (const b of list.querySelectorAll("[role=tab]")) {
    const on = b.dataset[dataset] === key;
    b.classList.toggle("active", on);
    b.setAttribute("aria-selected", String(on));
    b.tabIndex = on ? 0 : -1;
  }
}

// Attributes of a table row that opens something: in the tab order, a
// button for assistive technology, Enter and Space act as a click.
function rowAttrs(onPick, attrs) {
  return Object.assign({ tabindex: "0", role: "button", onclick: onPick,
    onkeydown: (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onPick(e); } } }, attrs || {});
}

// Table header cells; a column with no caption holds buttons, and says so
// to assistive technology.
function thCells(headers) {
  return headers.map((h) => el("th", null, h === "" ? el("span", { class: "visually-hidden" }, "Actions") : h));
}

// Message bars (consistent-message-bars): every message about a page, view,
// section or dialog is a bar of one of four kinds, with the same tint, left
// accent and state icon everywhere. A message sits at the top of what it is
// about: the page's message bar under the header, a section's slot under its
// heading, a dialog's slot at the top of its body. Field text (hints, a
// field's error) stays at its field and is not a bar.
const NOTICE_KINDS = ["error", "warning", "info", "done"];  // the order in a slot
const NOTICE_ICON = { error: "error", warning: "warning", info: "info", done: "operational" };

// A message bar. kind: "info", "done", "warning" or "error"; content: text,
// a node or a list of them. opts: actions (buttons after the text), close
// (true, or a function run after closing), key (setNotice replaces a bar of
// the same key), live (false: drawn with its view, so not announced), id,
// dataset, textId.
function notice(kind, content, opts) {
  opts = opts || {};
  if (!NOTICE_ICON[kind]) kind = "info";
  const live = opts.live !== false;
  const bar = el("div", {
    id: opts.id || null, class: `notice notice-${kind}` + (opts.class ? " " + opts.class : ""),
    role: live ? (kind === "error" ? "alert" : "status") : null,
    dataset: Object.assign({ notice: kind }, opts.key ? { noticeKey: opts.key } : {}, opts.dataset || {}),
  });
  bar.append(Icons.stateIcon(NOTICE_ICON[kind], { label: false }),
    el("div", { class: "notice-text", id: opts.textId || null }, content));
  const actions = (opts.actions || []).filter((a) => a);
  if (actions.length) bar.append(el("div", { class: "notice-actions" }, actions));
  if (opts.close) {
    bar.append(el("button", { type: "button", class: "notice-close", title: "Close", "aria-label": "Close message",
      onclick: () => { bar.remove(); if (typeof opts.close === "function") opts.close(); } }, "✕"));
  }
  return bar;
}

// A dialog's error bar, hidden while empty: bar.say(text) shows or clears it.
function msgBar(data, text) {
  const bar = notice("error", "", { dataset: data || null });
  const t = bar.querySelector(".notice-text");
  bar.say = (s) => { t.textContent = s || ""; bar.hidden = !s; };
  bar.say(text);
  return bar;
}

// The place for the messages of a view, section or dialog: put it directly
// under the heading, before the first control.
function noticeSlot(attrs) { return el("div", Object.assign({ class: "notice-slot" }, attrs || {})); }

// A view's connection line (Nodes, Simulation, Trace): the
// state as a bar of `kind` and its notes as bars, most severe first, in the
// view's slot. The slot is a polite live region, rewritten only when the
// bars change, so a screen reader hears each change once.
function stateBars(slot, kind, line, notes) {
  if (!slot) return;
  const bars = byKind([notice(kind, line, { live: false }), ...(notes || [])]);
  const sig = bars.map((b) => b.outerHTML).join("");
  if (slot.dataset.html === sig) return;
  slot.dataset.html = sig;
  slot.replaceChildren(...bars);
}

// A note under a view's connection line, as a bar without its own live role.
function noteBar(kind, text, data) { return notice(kind, text, { live: false, dataset: data || null }); }

// Sorts bars most severe first: error, warning, information, done.
function byKind(bars) {
  const rank = (b) => (b && b.dataset && b.dataset.notice ? NOTICE_KINDS.indexOf(b.dataset.notice) : NOTICE_KINDS.length);
  return bars.filter((b) => b).map((b, i) => [b, i]).sort((x, y) => rank(x[0]) - rank(y[0]) || x[1] - y[1]).map((x) => x[0]);
}

// Puts a bar into a slot, replacing the one with the same key, in kind order.
// kind null (or no content) removes the bar of that key.
function setNotice(slot, key, kind, content, opts) {
  if (!slot) return null;
  const old = [...slot.children].find((c) => c.dataset.noticeKey === key);
  if (!kind || content === null || content === undefined || content === "") { if (old) old.remove(); return null; }
  const bar = notice(kind, content, Object.assign({}, opts || {}, { key }));
  if (old) old.replaceWith(bar); else slot.append(bar);
  slot.replaceChildren(...byKind([...slot.children]));
  return bar;
}

// The page's message bar, under the header and the simulation banner, for
// the results of the user's actions and the errors of a request. text: a
// string, or an element (the EDS import report). kind: "done" (default),
// "info", "warning" or "error"; true is "error". Information and done close
// by themselves after BANNER_MS; warnings, errors and elements stay until
// closed, replaced, or the user switches view. An element with data-timed
// closes like a string.
const BANNER_MS = 6000;
function banner(text, kind) {
  if (kind === true) kind = "error";
  if (!kind) kind = "done";
  const b = $("#banner");
  clearTimeout(S.bannerTimer);
  b.hidden = !text;
  if (text instanceof Node) $("#banner-text").replaceChildren(text);
  else $("#banner-text").textContent = text || "";
  b.className = `notice notice-${kind}` + (kind === "error" ? " error" : "");
  b.dataset.notice = kind;
  b.setAttribute("role", kind === "error" ? "alert" : "status");
  const icon = b.querySelector(":scope > svg.st");
  if (icon) icon.remove();
  if (text) b.prepend(Icons.stateIcon(NOTICE_ICON[kind], { label: false }));
  const timed = typeof text === "string" ? !!text : !!(text && text.dataset && text.dataset.timed);
  if (timed && (kind === "done" || kind === "info")) S.bannerTimer = setTimeout(() => banner(""), BANNER_MS);
}

// "Removed 0x6150:1 from TPDO 2." with an Undo action, shown for BANNER_MS.
function removedBanner(what) {
  banner(el("span", { dataset: { timed: "1", removed: "1" } }, `Removed ${what}. `,
    el("button", { type: "button", class: "link", dataset: { undo: "1" }, onclick: () => undo(false) }, "Undo")));
}

// Switches view on the user's request; a message about the last view goes.
function showView(view) {
  if (TRACE_WINDOW && view !== "trace") return;
  if (view !== S.view) banner("");
  followWorkspace(view);
  S.view = view;
  render();
}

// The EDS lint setting the draft uses (strict_eds was migrated on load).
function edsLint() { return (S.config && S.config.master && S.config.master.eds_lint) || "communication"; }

// One correction of the prepared EDS copy in the banner's words, with its
// count; a kind this page does not know keeps edslint's own text.
function correctionLine(c) {
  const one = c.count === 1;
  const n = `${c.count} ${one ? "value" : "values"}`;
  const is = one ? "is" : "are";
  switch (c.kind) {
    case "nodeid": return `${n} written "<number>+$NODEID" ${is} read as "$NODEID+<number>"`;
    case "nodeid_bare": return `${one ? "1 bare value" : `${c.count} bare values`} "$NODEID" ${is} read as "$NODEID+0"`;
    case "real": return `${one ? "1 decimal REAL value" : `${c.count} decimal REAL values`} ${is} read as ${one ? "its" : "their"} hexadecimal bit pattern`;
    case "string": return `${one ? "1 OCTET_STRING/DOMAIN value" : `${c.count} OCTET_STRING/DOMAIN values`} ${is} cleared: ` +
      c.items.map((i) => `[${i.section}] ${i.key} was "${i.old}"`).join(", ");
    default: return `${c.text} (${c.count})`;
  }
}

// What the PLC's checks before dcfgen said about an imported EDS: readable,
// the corrections in the copy the target reads, and the accepted lint
// findings, collapsed and grouped by object. `slave`: the slave EDS import,
// which CODESYS never gets.
function importReport(res, { slave = false } = {}) {
  const lint = res.lint || { corrections: [], accepted: [] };
  const lines = [];
  if (res.converted) lines.push(el("div", null, `${res.name} was converted to UTF-8 (the editor sends project files as UTF-8).`));
  const target = projectTarget();
  const dcfs = target === "codesys" && !slave;
  // The exported DCFs write REAL values as decimals again.
  const fixes = lint.corrections.filter((c) => c.kind !== "utf8" && !(dcfs && c.kind === "real"));
  if (fixes.length) {
    const why = ", because its CANopen stack cannot read these values:";
    const reader = dcfs ? " The DCFs exported to CODESYS are built from a corrected copy:"
      : target === "bridge" ? " The Modbus bridge reads a corrected copy" + why
      : target === "codesys" ? " canworks reads a corrected copy" + why
      : " The OpenPLC plugin reads a corrected copy" + why;
    lines.push(el("div", { dataset: { report: "corrections" } },
      el("div", null, el("code", null, res.name), " is kept as imported." + reader),
      el("ul", null, fixes.map((c) => el("li", null, correctionLine(c))))));
  }
  if (res.lint && !fixes.length && !lint.accepted.length) {
    lines.push(el("div", { dataset: { report: "readable" } }, `${res.name} is readable by dcfgen and Lely on the PLC.`));
  }
  if (lint.accepted.length) {
    const groups = new Map();
    for (const f of lint.accepted) {
      const k = f.object;
      if (!groups.has(k)) groups.set(k, []);
      groups.get(k).push(f.message);
    }
    const n = lint.accepted.length;
    lines.push(el("details", { dataset: { report: "accepted" } },
      el("summary", null, `${res.name}: ${n} lint finding${n === 1 ? "" : "s"} accepted (they do not stop the PLC with EDS lint "${lint.mode}")`),
      el("ul", null, [...groups].map(([obj, msgs]) => el("li", null, `${obj}: ${msgs.join("; ")}`)))));
  }
  return el("div", null, lines);
}

// ---------------------------------------------------------------------------
// Values

function hex4(n) { return "0x" + Number(n).toString(16).toUpperCase().padStart(4, "0"); }
function num(v) {
  if (typeof v === "number") return v;
  if (typeof v === "string" && /^0x[0-9a-f]+$/i.test(v)) return parseInt(v, 16);
  if (typeof v === "string" && /^[0-9]+$/.test(v)) return parseInt(v, 10);
  return NaN;
}
function sameObject(a, ai, b, bi) { return num(a) === num(b) && num(ai || 0) === num(bi || 0); }

// The object a page path starts in, and the path's parts: the open network,
// or for "master.diagnostics…" the draft's one diagnostics object, which
// every network shares (master.diagnostics in a version 1 file), or for
// "gateway…", "bridge…" and the project's "codesys.project|device|create|
// variables" the top of the draft (a network's own "codesys…" is its
// net_id and interface).
function pathRoot(path) {
  const parts = path.match(/[^.[\]]+/g);
  if (parts[0] === "master" && (parts[1] === "diagnostics" || parts[1] === "cia309")) return [S.model, parts.slice(1)];
  if (parts[0] === "gateway" || parts[0] === "bridge") return [S.model.top, parts];
  if (parts[0] === "codesys" && CODESYS_TOP_KEYS.includes(parts[1])) return [S.model.top, parts];
  return [S.config, parts];
}

// Writes a value at a JSON path in the draft ("" or undefined deletes it).
function setPath(path, value) {
  const nodeId = /^nodes\[\d+\]\.node_id$/.test(path);
  const was = nodeId ? getPath(path) : undefined;
  const [root, parts] = pathRoot(path);
  let obj = root;
  for (let i = 0; i < parts.length - 1; i++) {
    const k = /^\d+$/.test(parts[i]) ? Number(parts[i]) : parts[i];
    if (obj[k] === undefined || obj[k] === null) obj[k] = /^\d+$/.test(parts[i + 1]) ? [] : {};
    obj = obj[k];
  }
  const last = parts[parts.length - 1];
  if (value === undefined || value === "") delete obj[last];
  else obj[last] = value;
  if (nodeId) followNodeId(path, was, getPath(path));
  changed(false, path);
}

function getPath(path) {
  let [obj, parts] = pathRoot(path);
  for (const p of parts) {
    if (obj === undefined || obj === null) return undefined;
    obj = obj[/^\d+$/.test(p) ? Number(p) : p];
  }
  return obj;
}

// Every edit of the draft ends here. The draft as it was before the edit
// (kept since the last call) goes onto the undo stack; edits of one field
// within a second are one step, so typing undoes as a whole. `path` names
// the edited field, when there is one.
const UNDO_MAX = 50;
function changed(rerender, path) {
  const now = Date.now();
  if (S.lastClean) {
    const same = path && S.undoPath === path && now - S.undoAt < 1000 && S.undo.length;
    if (!same) {
      // The snapshot's draft is from before the edit; its place is where the edit was made.
      S.undo.push({ model: S.lastClean.model, net: S.net, view: S.view });
      if (S.undo.length > UNDO_MAX) S.undo.shift();
    }
    S.redo = [];
  }
  S.undoPath = path || null;
  S.undoAt = now;
  undoBase();
  S.dirty = draftDirty();
  if (rerender) render();
  else {
    updateSimBanner();
    if (path && /^nodes\[\d+\]\.(name|node_id)$/.test(path)) renderSide();
  }
  scheduleCheck();
}

// Whether there is something to save: the draft differs from the file as
// loaded (a field typed back to its value is clean again), or a file built
// here (a generated slave EDS) waits for Save.
function draftDirty() {
  return !!S.unsavedFiles || JSON.stringify(S.model) !== S.savedJson;
}

// The draft as it is now, kept as the snapshot of the next edit.
function undoBase() {
  S.lastClean = { model: structuredClone(S.model), net: S.net, view: S.view };
}

// Forgets the undo history: the draft was loaded, saved or closed.
function resetUndo() {
  S.undo = [];
  S.redo = [];
  S.undoPath = null;
  S.unsavedFiles = false;
  S.savedJson = S.model ? JSON.stringify(S.model) : null;
  if (S.model) undoBase();
}

// Ctrl+Z (Cmd+Z) and Ctrl+Shift+Z: the draft one step back or forward,
// across views. Returns false when there is nothing to do.
function undo(redo) {
  const from = redo ? S.redo : S.undo;
  const to = redo ? S.undo : S.redo;
  if (!from.length || !S.model) return false;
  const snap = from.pop();
  to.push({ model: structuredClone(S.model), net: S.net, view: S.view });
  S.model = snap.model;
  openNet(Math.min(snap.net, S.model.networks.length - 1));
  S.view = snap.view;
  if (S.view.startsWith("node:") && !(S.config.nodes || [])[Number(S.view.slice(5))]) S.view = "bus";
  S.undoPath = null;
  S.supervision = {};
  undoBase();
  S.dirty = draftDirty();
  banner("");
  render();
  scheduleCheck();
  return true;
}

// The undo keys. A field bound to the draft undoes through the draft (its
// typed value is already in the draft); any other field (a filter, a
// dialog) keeps the browser's own undo.
function undoKeys(e) {
  if (!(e.ctrlKey || e.metaKey) || e.altKey || e.key.toLowerCase() !== "z") return;
  if ($("#modal").open || !S.state || !S.state.mode) return;
  const a = document.activeElement;
  const field = a && (a.tagName === "INPUT" || a.tagName === "TEXTAREA" || a.tagName === "SELECT");
  if (field && !a.dataset.path) return;
  e.preventDefault();
  // Commission a device has no draft for notes: Ctrl+Z puts back the last note write.
  if (S.state.commission && !e.shiftKey && S.notesUndo) { liveNotesUndo(); return; }
  undo(e.shiftKey);
}

// An input bound to a JSON path. kind: "text" | "int" | "intstr" (keeps "0x.." text)
function field(label, path, kind, opts) {
  opts = opts || {};
  const value = getPath(path);
  const input = el("input", { type: "text", spellcheck: "false", dataset: { path }, placeholder: opts.placeholder,
    list: opts.list, "aria-label": label });
  input.value = value === undefined || value === null ? "" : String(opts.show ? opts.show(value) : value);
  input.addEventListener("input", () => {
    const t = input.value.trim();
    let v;
    if (t === "") v = opts.empty;  // undefined unless the field saves something for empty
    else if (opts.parse) v = opts.parse(t);
    else if (kind === "int") v = /^-?[0-9]+$/.test(t) ? parseInt(t, 10) : t;
    else if (kind === "intstr") v = /^[0-9]+$/.test(t) ? parseInt(t, 10) : t;
    else v = t;
    setPath(path, v);
  });
  return el("label", null, label, input, hint(opts.hint), el("span", { class: "field-msg", dataset: { for: path } }));
}

function hint(text) { return text ? el("span", { class: "hint" }, text) : null; }

// Why a node setting is off because of the node's EDS (canopen-configurator
// "One look for EDS limits"): hint text while the config has nothing the EDS
// cannot back; warning text, with the remove action when given, while it
// still has such a setting. `section`: the reason is about a whole section
// (EMCY), so a leftover setting is a warning bar at its top
// (consistent-message-bars); otherwise it is the field's own text.
function edsLimit(text, leftover, remove, data, section) {
  if (!leftover) return el("span", { class: "hint", dataset: Object.assign({ edsLimit: "" }, data) }, text);
  const btn = remove ? el("button", { type: "button", class: section ? "small" : "link", dataset: remove.dataset, onclick: () => { remove.run(); render(); } },
    remove.label) : null;
  if (section) return notice("warning", text, { live: false, actions: [btn], dataset: Object.assign({ edsLimit: "leftover" }, data) });
  return el("p", { class: "field-msg warning", dataset: Object.assign({ edsLimit: "leftover" }, data) }, text + " ", btn);
}

// Whether the node's EDS has the EMCY COB-ID (0x1014) and a writable 0x1016
// sub-index; true without a readable EDS, which the Check reports itself.
function edsHasEmcy(eds) { return !eds || !eds.objects || !!objectInfo(eds, "0x1014", 0); }
function edsHasHeartbeatConsumer(eds) {
  return !eds || !eds.objects || eds.objects.some((o) => num(o.index) === 0x1016 && num(o.subindex) >= 1 && o.writable);
}

function checkbox(label, path, dflt, help) {
  const v = getPath(path);
  const input = el("input", { type: "checkbox", dataset: { path } });
  input.checked = v === undefined ? dflt : !!v;
  input.addEventListener("change", () => setPath(path, input.checked));
  return el("div", { class: "check-field" }, el("label", { class: "check" }, input, " " + label),
    hint((help ? help + " " : "") + "Default: " + (dflt ? "on." : "off.")));
}

// A dropdown of fixed choices, each with an explanation shown under it.
// choices: [{ value, label, help }]; value is what goes in the config
// (undefined = leave the key out and use the default).
function choice(label, path, choices, opts) {
  opts = opts || {};
  const key = (v) => (v === undefined ? "" : String(v));
  let current = opts.current !== undefined ? opts.current : getPath(path);
  const list = choices.slice();
  if (current === undefined && !list.some((c) => c.value === undefined)) current = list[0].value;
  // A default written out ("word_order": "high_first") shows as the default's row.
  const lit = list.find((c) => c.literal !== undefined && key(c.literal) === key(current));
  if (lit) current = lit.value;
  if (!list.some((c) => key(c.value) === key(current))) {
    list.push({ value: current, label: String(current) + " (as in the file)", help: "A value this page has no name for." });
  }
  const sel = el("select", { dataset: opts.noPath ? opts.dataset : Object.assign({ path }, opts.dataset), "aria-label": label },
    list.map((c) => el("option", { value: key(c.value) }, c.label)));
  sel.value = key(current);
  const help = el("span", { class: "hint" });
  const show = () => { const c = list.find((x) => key(x.value) === sel.value); help.textContent = c ? c.help : ""; };
  show();
  sel.addEventListener("change", () => {
    show();
    const c = list.find((x) => key(x.value) === sel.value);
    if (opts.onChange) opts.onChange(c.value);
    else setPath(path, c.value);
  });
  // A long choice gets two grid columns, so the dropdown shows it whole.
  const long = Math.max(...list.map((c) => String(c.label).length)) > 24;
  return el("label", { class: [opts.wide ? "wide" : null, long ? "span2" : null].filter(Boolean).join(" ") || null }, label, sel, help,
    opts.noPath ? null : el("span", { class: "field-msg", dataset: { for: path } }));
}

// ---------------------------------------------------------------------------
// Networks (canopen-networks). The draft is always a network list; a file
// with one network that has no name of its own goes back to the server as
// version 1, anything else as version 2 (canopen-config-contract: writers
// use the lowest version that holds the config).

const NETWORK_NAME = /^[A-Za-z][A-Za-z0-9_]{0,15}$/;
const MAX_NETWORKS = 8;
const NETWORK_KEYS = ["name", "adapter", "master", "nodes", "links"];

// The draft of a file as the server sent it (version 1 or 2).
function toModel(cfg) {
  cfg = JSON.parse(JSON.stringify(cfg || {}));
  const top = {};
  let networks;
  let diagnostics;
  let cia309;
  if (cfg.schema_version === 2 && Array.isArray(cfg.networks)) {
    for (const [k, v] of Object.entries(cfg)) if (k !== "networks" && k !== "diagnostics" && k !== "cia309") top[k] = v;
    networks = cfg.networks.map((n) => (n && typeof n === "object" && !Array.isArray(n) ? n : {}));
    diagnostics = cfg.diagnostics;
    cia309 = cfg.cia309;
  } else {
    const net = {};
    for (const [k, v] of Object.entries(cfg)) {
      if (k === "adapter" || k === "master" || k === "nodes" || k === "links") net[k] = v;
      else top[k] = v;
    }
    if (net.master && typeof net.master === "object" && "diagnostics" in net.master) {
      diagnostics = net.master.diagnostics;
      delete net.master.diagnostics;
    }
    if (net.master && typeof net.master === "object" && "cia309" in net.master) {
      cia309 = net.master.cia309;
      delete net.master.cia309;
    }
    networks = [net];
  }
  if (!networks.length) networks.push({ adapter: { type: "socketcan", bitrate: DEFAULT_BITRATE.canopen }, master: newMaster(), nodes: [] });
  return { top, networks, diagnostics, cia309 };
}

function setModel(cfg) {
  S.model = toModel(cfg);
  openNet(Math.min(S.net || 0, S.model.networks.length - 1));
  resetUndo();
}

function openNet(i) {
  S.net = i;
  S.config = S.model.networks[i];
}

function several() { return !!S.model && S.model.networks.length > 1; }

// A network's name: its own, else its interface's (when that is a valid name).
function netName(net) {
  if (net && typeof net.name === "string" && net.name) return net.name;
  const iface = net && net.adapter ? net.adapter.interface : undefined;
  return typeof iface === "string" && NETWORK_NAME.test(iface) ? iface : "";
}
function netLabel(net, i) { return netName(net) || `network ${i + 1}`; }
// The network in a sentence: "network io", or "network 5" without a name.
function netNamed(net, i) { return netName(net) ? `network ${netName(net)}` : netLabel(net, i); }

function customName(net) {
  return typeof net.name === "string" && net.name !== "" && !(net.adapter && net.name === net.adapter.interface);
}

// The draft as a file: version 1 when it holds one network without a name
// of its own, else version 2 (always for a Modbus bridge or CODESYS project).
function fileConfig() {
  const m = S.model;
  const out = {};
  const swapSchema = (from, to) => {
    if (typeof out.$schema === "string" && out.$schema.endsWith(`canworks.v${from}.schema.json`)) {
      out.$schema = out.$schema.slice(0, -`canworks.v${from}.schema.json`.length) + `canworks.v${to}.schema.json`;
    }
  };
  const net = m.networks[0];
  if (m.networks.length === 1 && !customName(net) && Object.keys(net).every((k) => NETWORK_KEYS.includes(k)) && !("bridge" in m.top) && !("codesys" in m.top)) {
    for (const [k, v] of Object.entries(m.top)) out[k] = k === "schema_version" && v === 2 ? 1 : v;
    for (const k of ["adapter", "master", "nodes", "links"]) if (k in net) out[k] = net[k];
    if (m.diagnostics !== undefined) out.master = Object.assign({}, net.master, { diagnostics: m.diagnostics });
    if (m.cia309 !== undefined) out.master = Object.assign({}, out.master || net.master, { cia309: m.cia309 });
    swapSchema(2, 1);
    return out;
  }
  out.schema_version = 2;
  for (const [k, v] of Object.entries(m.top)) out[k] = k === "schema_version" ? 2 : v;
  out.networks = m.networks;
  if (m.diagnostics !== undefined) out.diagnostics = m.diagnostics;
  if (m.cia309 !== undefined) out.cia309 = m.cia309;
  swapSchema(1, 2);
  return out;
}

function fileVersion(cfg) { return cfg.schema_version === 2 ? 2 : 1; }

// A path of a check result, in the page's terms: { net, path } with net the
// network index (null for the shared diagnostics and the top level) and the
// path as the page's fields name it.
function pagePath(p, version) {
  if (typeof p !== "string") return { net: null, path: p };
  if (version === 2) {
    const m = /^networks\[(\d+)\](?:\.(.*))?$/.exec(p);
    if (m) return { net: Number(m[1]), path: m[2] || "" };
    if (p === "diagnostics" || p.startsWith("diagnostics.") || p === "cia309" || p.startsWith("cia309.")) return { net: null, path: "master." + p };
    return { net: null, path: p };
  }
  if (p.startsWith("master.diagnostics") || p.startsWith("master.cia309")) return { net: null, path: p };
  return { net: 0, path: p };
}

// A /api/check shaped answer with its paths in the page's terms: `where` on
// each item, and the declared map keyed by "<network index>|<path>".
function normCheck(r, version) {
  // Values the target does not use are no problem: save leaves them out.
  if (r.items && r.items.some(isUnusedItem)) {
    r.items = r.items.filter((it) => !isUnusedItem(it));
    r.warnings = r.items.filter((it) => it.level !== "error").length;
  }
  for (const it of r.items || []) it.where = (it.paths || []).map((p) => pagePath(p, version));
  if (r.declared) {
    const d = {};
    for (const [p, name] of Object.entries(r.declared)) {
      const w = pagePath(p, version);
      d[`${w.net}|${w.path}`] = name;
    }
    r.declared = d;
  }
  return r;
}

// Opens a network's tab. The online and scan views follow it; a node page
// goes to the new tab's Bus and master.
function switchNet(i) {
  if (i === S.net) return;
  openNet(i);
  S.onlineNet = null;
  S.onlineNode = null;
  S.scanResult = null;
  S.lssFound = null;
  S.lssDevice = null;
  S.supervision = {};
  if (S.view.startsWith("node:")) S.view = "bus";
  render();
}

// Add network's protocols: one choice per row with a line on what it is for;
// Up and Down move between them. CANopen, the default, comes first.
const PROTOCOL_CHOICES = [
  ["canopen", "CANopen", "A master and its nodes from EDS files, or the PLC as a slave device."],
  ["j1939", "J1939", "The PLC as an ECU that sends and receives parameter groups from a DBC file."],
  ["none", "Plain CAN", "CAN frames only, from a DBC file or entered by hand, with no protocol on top."],
];
function protocolChoices() {
  const list = el("div", { class: "modal-choices", role: "group", "aria-label": "Protocol" },
    PROTOCOL_CHOICES.map(([value, name, help]) => el("button", { type: "button", class: "choice", dataset: { value } },
      el("strong", null, name), el("span", null, help))));
  list.addEventListener("keydown", (e) => {
    if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
    const bs = [...list.children];
    const i = bs.indexOf(document.activeElement);
    bs[(i + (e.key === "ArrowDown" ? 1 : bs.length - 1)) % bs.length].focus();
    e.preventDefault();
  });
  return list;
}

async function addNetwork() {
  const protocol = await modal("Add a network with its own CAN interface. Which protocol does it run?",
    [["cancel", "Cancel"]], protocolChoices());
  if (protocol !== "canopen" && protocol !== "j1939" && protocol !== "none") return;
  // No interface: the user picks it (each network needs its own). The rate
  // is the protocol's default, not another network's.
  S.model.networks.push(protocol === "j1939" ? newJ1939Network()
    : protocol === "none" ? { protocol: "none", adapter: { type: "socketcan", bitrate: DEFAULT_BITRATE.none } }
    : { adapter: { type: "socketcan", bitrate: DEFAULT_BITRATE.canopen }, master: newMaster(), nodes: [] });
  openNet(S.model.networks.length - 1);
  S.onlineNet = null;
  S.view = "bus";
  banner(`Added ${protocol === "j1939" ? "J1939 " : protocol === "none" ? "plain CAN " : ""}network ${S.model.networks.length}. Enter its CAN interface (each network needs its own), then ` +
    (protocol === "j1939" ? "its ECU identity and messages." : protocol === "none" ? "its messages on the CAN messages page." : "add its nodes."));
  changed(true);
}

async function renameNetwork() {
  const net = S.config;
  const input = el("input", { type: "text", spellcheck: "false", maxlength: 16, "aria-label": "Network name", dataset: { net: "name" } });
  input.value = netName(net);
  const iface = net.adapter && net.adapter.interface;
  let text = "Network name: a letter, then letters, digits or _, at most 16 characters. It names the network's folder " +
    "in exports and prefixes its variables" + (iface ? `. Empty: ${iface}, the interface's name.` : ".");
  for (;;) {
    const v = await modal(text, [["rename", "Rename", true], ["cancel", "Cancel"]], input);
    if (v !== "rename") return;
    const name = input.value.trim();
    const taken = S.model.networks.some((n, i) => i !== S.net && netName(n).toLowerCase() === name.toLowerCase());
    if (name && !NETWORK_NAME.test(name)) text = `"${name}" is not a network name: a letter, then letters, digits or _, at most 16 characters.`;
    else if (name && taken) text = `Another network is already named ${name}.`;
    else break;
  }
  const name = input.value.trim();
  const was = netName(net);
  if (!name || name === iface) delete net.name;
  else net.name = name;
  // The gateway and the Modbus bridge's live lists name networks: they follow the rename.
  const g = S.model.top.gateway;
  const now = netName(net);
  if (g && was && now && was !== now) {
    if (g.upper === was) g.upper = now;
    for (const r of g.routes || []) if (r && r.field && r.field.network === was) r.field.network = now;
  }
  if (was && now && was !== now) for (const e of bridgeLists()) if (e.network === was) e.network = now;
  changed(true);
}

// The Modbus bridge's live lists ({ network, location }) of the draft.
function bridgeLists() {
  const b = S.model.top.bridge;
  return b && Array.isArray(b.live_lists) ? b.live_lists.filter((e) => e && typeof e === "object") : [];
}

// A node ID changed: the gateway routes that read or write the node, the
// PDO links it is in and the heartbeat watches of it follow it. The last
// whole ID is kept while the field is empty, so typing over the ID carries
// them along too.
function followNodeId(path, was, now) {
  S.nodeIdWas = S.nodeIdWas || {};
  const key = `${S.net}|${path}`;
  const from = Number.isInteger(was) ? was : S.nodeIdWas[key];
  if (Number.isInteger(was)) S.nodeIdWas[key] = was;
  if (!Number.isInteger(now)) return;
  S.nodeIdWas[key] = now;
  if (!Number.isInteger(from) || from === now) return;
  const u = nodeUses(from);
  for (const r of u.routes) r.field.node = now;
  for (const l of u.from) l.from.node = now;
  for (const c of u.to) c.node = now;
  for (const h of u.watches) h.node = now;
}

// What names node `id` of the open network: the gateway routes that read or
// write it, the links it produces ({ from }) or receives ({ to }, the
// consumers) and the other nodes' heartbeat watches of it.
function nodeUses(id) {
  const g = S.model.top.gateway;
  const net = netName(S.config);
  const out = { routes: [], from: [], to: [], watches: [] };
  if (g && net) for (const r of g.routes || []) if (r && r.field && r.field.network === net && num(r.field.node) === id) out.routes.push(r);
  for (const l of S.config.links || []) {
    if (l && l.from && num(l.from.node) === id) out.from.push(l);
    for (const c of (l && Array.isArray(l.to) ? l.to : [])) if (c && num(c.node) === id) out.to.push(c);
  }
  for (const n of S.config.nodes || []) for (const h of n.heartbeat_watch || []) if (h && num(h.node) === id) out.watches.push(h);
  return out;
}

async function removeNetwork() {
  const label = netNamed(S.config, S.net);
  const k = (S.config.nodes || []).length;
  const g = S.model.top.gateway;
  const upper = !!(g && netName(S.config) && g.upper === netName(S.config));
  const routes = upper && Array.isArray(g.routes) ? g.routes.length : 0;
  const live = netName(S.config) ? bridgeLists().filter((e) => e.network === netName(S.config)) : [];
  // The gateway's upper network: the gateway goes with it. Its bridge live list too.
  const v = await modal(`Remove ${label}` + (k ? ` and its ${k} node${k === 1 ? "" : "s"}` : "") + "? " +
    (upper ? `It is the gateway's upper network: the gateway and its ${routes} route${routes === 1 ? "" : "s"} are removed too, ` +
      "and the PDO entries the routes use then need a PLC location. " : "") +
    (live.length ? "Its Modbus bridge live list is removed too. " : "") +
    "Its EDS files stay in the folder.", [["cancel", "Keep the network"], ["remove", upper ? "Remove network and gateway" : "Remove network", { danger: true }]]);
  if (v !== "remove") return;
  if (upper) delete S.model.top.gateway;
  if (live.length) {
    const b = S.model.top.bridge;
    b.live_lists = b.live_lists.filter((e) => !live.includes(e));
    if (!b.live_lists.length) delete b.live_lists;
  }
  S.model.networks.splice(S.net, 1);
  openNet(Math.min(S.net, S.model.networks.length - 1));
  S.onlineNet = null;
  S.onlineNode = null;
  S.scanResult = null;
  S.lssFound = null;
  if (S.view.startsWith("node:")) S.view = "bus";
  banner(`Removed ${label}` + (upper ? " and the gateway." : "."));
  changed(true);
}

// The network the online, scan and trace views talk to: the picked one, else
// the open tab's. null with one network everywhere (nothing to name).
function onlineNetwork() {
  if (!S.model) return null;
  const runtime = S.runtimeNets || [];
  if (!several() && runtime.length < 2) return null;
  return S.onlineNet || netName(S.config) || (runtime[0] ? runtime[0].name : null);
}

// The draft network the picked runtime network is (its nodes and EDS files).
// A draft with one network stands for the runtime network of another name
// (a runtime that also runs other networks, a draft without network names).
function onlineConfig() {
  const name = onlineNetwork();
  if (name === null) return S.config;
  return S.model.networks.find((n) => netName(n) === name) || (several() ? { nodes: [] } : S.config);
}

// The network picker of the online, scan and trace views: the runtime's
// networks once it has said them, else the draft's.
function netPicker() {
  const runtime = (S.runtimeNets || []).map((n) => n.name).filter((n) => n);
  const names = runtime.length > 1 ? runtime : S.model.networks.map(netName).filter((n) => n);
  if (names.length < 2) return el("span", { dataset: { online: "net-picker" } });
  const current = onlineNetwork();
  const sel = el("select", { "aria-label": "Network", dataset: { online: "network" } },
    names.map((n) => el("option", { value: n }, n + ((S.runtimeNets || []).find((r) => r.name === n && r.interface)
      ? ` (${S.runtimeNets.find((r) => r.name === n).interface})` : ""))));
  if (!names.includes(current)) sel.prepend(el("option", { value: current }, current + " (not on the runtime)"));
  sel.value = current;
  sel.addEventListener("change", () => pickNetwork(sel.value));
  return el("label", { class: "inline", dataset: { online: "net-picker" } }, "Network ", sel);
}

function pickNetwork(name) {
  const i = S.model.networks.findIndex((n) => netName(n) === name);
  if (i >= 0 && i !== S.net) {
    openNet(i);
    S.supervision = {};
  }
  S.onlineNet = name;
  traceWinNet(name);
  S.onlineNode = null;
  S.scanResult = null;
  S.lssFound = null;
  S.lssDevice = null;
  render();
  // An answer still on its way is about the network before: the next one asks for this one.
  if (connIsOn()) connKick();
}

// The runtime's networks from an online answer; the picker is drawn again
// when they change, or when the server picked another network.
function runtimeNetworks(r) {
  const nets = Array.isArray(r.networks) ? r.networks : [];
  let redraw = JSON.stringify(nets) !== JSON.stringify(S.runtimeNets || []);
  S.runtimeNets = nets;
  if (r.network && nets.length > 1 && r.network !== onlineNetwork()) {
    S.onlineNet = r.network;
    redraw = true;
    const i = S.model.networks.findIndex((n) => netName(n) === r.network);
    if (i >= 0 && i !== S.net) { openNet(i); renderSide(); }
  }
  if (redraw) {
    for (const old of document.querySelectorAll("[data-online=net-picker]")) old.replaceWith(netPicker());
  }
}

// ---------------------------------------------------------------------------
// Start page

async function loadState() {
  S.state = await api("GET", "/api/state");
  if (S.state.mode) S.devicesOnly = false;
  // The device list's plans follow the open config's target (devices.js).
  if (typeof devContext === "function") devContext(S.state.mode ? S.state.folder : null);
  if (S.workspace === undefined) { await loadShellSettings(); await loadTreeSettings(); }
  if (S.state.mode) {
    setModel(S.state.config);
    await loadOnlineSettings();
    // A migrated file (an old setting rewritten on load) differs from the draft: there is something to save.
    S.dirty = !!(S.state.notices && S.state.notices.length);
    if (S.dirty) S.savedJson = null; // the file is not the draft until saved
    S.supervision = {};
    if (S.view.startsWith("node:") && !(S.config.nodes || [])[Number(S.view.slice(5))]) S.view = "bus";
    if (typeof simLoad === "function") simLoad();
    if (S.state.load_error) banner(S.state.load_error, true);
    else if (S.state.notices && S.state.notices.length) banner(S.state.notices.join(" "), "info");
    else banner("");
  } else if (S.state.open_error) banner(S.state.open_error, true);
  render();
  if (S.state.mode) {
    runCheck();
    connSession();
    if (workspace() === "commission") connEnter();
    if (typeof jobsStart === "function" && !TRACE_WINDOW) jobsStart();
  }
}

function renderStart() {
  // Back on the start page: the next folder or commissioning session starts afresh.
  if (typeof CONN !== "undefined") { CONN.key = null; connStop(); }
  document.body.classList.remove("devices-only");
  for (const id of ["#tool-tabs", "#conn-bar", "#bottom", "#ws"]) $(id).hidden = true;
  $("#start").hidden = false;
  $("#editor").hidden = true;
  $("#actions").hidden = true;
  fitHeaderMore();
  $("#mode").hidden = true;
  $("#sim-banner").hidden = true;
  // Recent is the page; with nothing in it, four starting points take its place.
  const items = S.state.recent || [];
  $("#start-first").hidden = items.length > 0;
  $("#start-recent").hidden = items.length === 0;
  $("#recent").replaceChildren(...items.map((r) => {
    const target = r.target || (r.mode === "project" ? "openplc" : null);
    return el("li", null, el("button", { type: "button", class: "folder", title: r.path, onclick: () => openFolder(r.path, r.mode) },
      el("span", { class: "recent-name" }, folderName(r.path)),
      target ? el("span", { class: "tag", dataset: { recentTarget: target } }, TARGET_TITLES[target]) : null,
      el("span", { class: "tag" }, r.mode === "project" ? "editor project" : "config folder"),
      r.opened ? el("span", { class: "recent-when" }, whenOpened(r.opened)) : null,
      el("span", { class: "recent-path" }, r.path)),
    el("button", { type: "button", class: "small", dataset: { forget: r.path }, "aria-label": "Remove " + r.path + " from Recent",
      title: "Remove from Recent (the folder stays)", onclick: () => forgetRecent(r.path) }, "Remove"));
  }));
}

const TARGET_TITLES = { openplc: "OpenPLC", bridge: "Modbus bridge", codesys: "CODESYS" };

// The last part of a path, on Windows too.
function folderName(path) {
  const parts = String(path).replace(/[\\/]+$/, "").split(/[\\/]/);
  return parts[parts.length - 1] || path;
}

function splitPath(path) {
  const p = String(path).replace(/[\\/]+$/, "");
  const k = Math.max(p.lastIndexOf("/"), p.lastIndexOf("\\"));
  return k < 0 ? ["", p] : [k === 0 || /^[A-Za-z]:$/.test(p.slice(0, k)) ? p.slice(0, k + 1) : p.slice(0, k), p.slice(k + 1)];
}

function joinPath(parent, name) {
  if (!parent) return name;
  const sep = parent.includes("\\") && !parent.includes("/") ? "\\" : "/";
  return /[\\/]$/.test(parent) ? parent + name : parent + sep + name;
}

// "today", "yesterday", "3 days ago", or the date: seconds since 1970 of the last open.
function whenOpened(seconds) {
  const then = new Date(seconds * 1000), now = new Date();
  const day = (d) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
  const days = Math.round((day(now) - day(then)) / 86400000);
  if (days <= 0) return "today";
  if (days === 1) return "yesterday";
  if (days < 7) return days + " days ago";
  return then.toLocaleDateString();
}

async function forgetRecent(path) {
  const list = $("#recent");
  const rows = [...list.querySelectorAll("[data-forget]")];
  const k = rows.findIndex((b) => b.dataset.forget === path);
  try {
    S.state.recent = (await api("POST", "/api/recent/forget", { path })).recent;
    renderStart();
    // The focus goes to the next entry's Remove, or the one before, or Open….
    const left = [...list.querySelectorAll("[data-forget]")];
    (left[Math.min(k, left.length - 1)] || $("#start-open")).focus();
  } catch (e) {
    banner(e.message, true);
  }
}

// Open…: an OpenPLC Editor project or a config folder, whichever the picked folder is.
async function startOpen() {
  const path = await chooseFolder({ title: "Open a project or config folder", start: S.lastFolder || S.state.home,
    note: "An OpenPLC Editor project opens as a project; a folder with a canworks config opens as a config folder." });
  if (path) await openFolder(path, "auto", false);
}

// New config…: what runs it first, then where; for OpenPLC optionally a new editor project around it.
async function newConfig(folder) {
  const cli = !!S.state.openplc_cli;
  const pick = (value, title, text) => el("label", { class: "choice" },
    el("input", { type: "radio", name: "new-target", value, dataset: { newTarget: value }, checked: value === "openplc" || null }),
    el("strong", null, title), el("span", null, text));
  const targets = el("fieldset", null, el("legend", null, "What will run the networks?"),
    el("div", { class: "target-choices" },
      pick("openplc", "OpenPLC Runtime", "The canworks plugin runs the networks; PLC variables map to PDOs and signals."),
      pick("bridge", "Modbus bridge", "No PLC: the values are served as Modbus TCP registers, for Node-RED, an HMI or any Modbus client."),
      pick("codesys", "CODESYS", "A CODESYS PLC runs the CANopen master; canworks builds it into your CODESYS project.")));
  const [start, startName] = folder ? splitPath(folder) : [S.lastFolder || S.state.home, ""];
  const name = el("input", { type: "text", spellcheck: "false", "aria-label": "Name", dataset: { newConfig: "name" }, placeholder: "new-machine" });
  name.value = startName;
  const where = el("input", { type: "text", spellcheck: "false", "aria-label": "Location", dataset: { newConfig: "location" } });
  where.value = start;
  const choose = el("button", { type: "button", dataset: { newConfig: "choose" }, onclick: async () => {
    const p = await chooseFolder({ title: "Where the new config goes", start: where.value.trim() || S.state.home });
    if (p) where.value = p;
  } }, "Choose…");
  const project = el("input", { type: "checkbox", dataset: { newConfig: "project" }, disabled: !cli || null,
    checked: (cli && !folder) || null });
  const projectRow = el("label", { class: "inline" }, project, " Also create an OpenPLC Editor project here, with the I/O declared in main");
  const projectHint = el("p", { class: "hint", dataset: { newConfig: "project-hint" } }, cli
    ? "Untick to keep just a config folder; Project → New editor project… makes one later."
    : "The OpenPLC Editor's command-line tool (openplc-cli) was not found on this PC, so only a config folder can be made.");
  const projectBox = el("div", null, projectRow, projectHint);
  // A problem goes under the field it concerns; the dialog's title stays.
  const nameErr = el("span", { class: "field-msg", id: "new-config-name-msg", dataset: { newConfig: "name-error" } });
  const whereErr = el("span", { class: "field-msg", id: "new-config-location-msg", dataset: { newConfig: "location-error" } });
  name.setAttribute("aria-describedby", nameErr.id);
  where.setAttribute("aria-describedby", whereErr.id);
  const form = el("div", { class: "new-config", dataset: { newConfig: "form" } }, targets,
    el("label", null, "Name (its folder: new, or an existing empty one)", name), nameErr,
    el("div", { class: "field" }, el("label", { for: "new-config-location" }, "Location"), el("div", { class: "row" }, where, choose), whereErr),
    projectBox);
  where.id = "new-config-location";
  const target = () => (form.querySelector("input[name=new-target]:checked") || {}).value || "openplc";
  const sync = () => { projectBox.hidden = target() !== "openplc"; };
  form.addEventListener("change", sync);
  sync();
  let bad = null;
  const fail = (input, msg, text) => {
    for (const [i, m] of [[name, nameErr], [where, whereErr]]) {
      i.classList.toggle("invalid", i === input);
      i.toggleAttribute("aria-invalid", i === input);
      m.textContent = i === input ? text : "";
    }
    bad = input;
  };
  for (;;) {
    const answer = modal("New config", [["create", "Create", true], ["cancel", "Cancel"]], form);
    if (bad) bad.focus();
    const v = await answer;
    if (v !== "create") return;
    const nm = name.value.trim(), loc = where.value.trim();
    if (!nm) { fail(name, nameErr, "Give the new config a name: it becomes its folder."); continue; }
    if (/[\\/]/.test(nm)) { fail(name, nameErr, "The name is one folder name, without slashes."); continue; }
    fail(null);
    const path = joinPath(loc, nm);
    const withProject = target() === "openplc" && project.checked && !project.disabled;
    const finish = withProject ? modalWorking("Creating the editor project…") : () => {};
    try {
      banner("");
      await api("POST", "/api/new", { path, editor_project: withProject, target: target() });
      finish();
    } catch (e) {
      finish();
      if (e.body && (e.body.has_config || e.body.is_project)) {
        const o = await modal(e.message + ". Open it instead?", [["open", "Open it", true], ["cancel", "Cancel"]]);
        if (o === "open") await openFolder(e.body.path || path, "auto");
        return;
      }
      fail(where, whereErr, "Not created: " + e.message);
      continue;
    }
    // Create wrote the target's config: the page opens it as saved.
    await opened();
    if (withProject) banner("Created the OpenPLC Editor project " + path + ". Add nodes, save, then open it in the editor with Open Project.", "info");
    return;
  }
}

// A folder picked in a dialog (browse-eds-library-folder): the PC's folders
// as the server lists them, with Up (the drives above a Windows drive root),
// a path field for a typed or pasted path, and each folder's EDS count.
// Resolves the folder's path, or null on Cancel or Escape. File mode
// (codesys-new-project-picker): `files` (".project") also lists the folder's
// files with that extension, and picking one resolves its path; `newName`
// adds a name field whose Create here resolves <folder>/<name><files>.
// One click selects a folder (Use this folder takes it), a double-click or
// Enter opens it; each folder says whether it is an OpenPLC project or holds
// a canworks config. `eds` (picking an EDS folder) adds the EDS counts.
async function chooseFolder({ title, start, note, files, newName, eds }) {
  const path = el("input", { type: "text", spellcheck: "false", "aria-label": "Folder path", dataset: { folder: "path" } });
  const up = el("button", { type: "button", title: "Parent folder", "aria-label": "Parent folder", dataset: { folder: "up" } }, "↑");
  const go = el("button", { type: "button", dataset: { folder: "go" } }, "Go");
  const here = el("p", { class: "muted", dataset: { folder: "here" }, "aria-live": "polite" });
  const list = el("ul", { class: "folders", "aria-label": "Subfolders", dataset: { folder: "list" } });
  const err = msgBar({ folder: "error" });
  let shown = null;  // the listing on screen
  let selected = null;  // the folder clicked once
  let pick = () => {};  // file mode: resolves the dialog with a file's path
  // File mode's new name: Create here, refused in the dialog when the name has slashes or its file is listed.
  let create = null;
  const name = newName ? el("input", { type: "text", spellcheck: "false", id: "folder-new-name", dataset: { folder: "new-name" } }) : null;
  const createNew = () => {
    let n = name.value.trim();
    if (!n) { err.say("Give the new " + files + " file a name."); name.focus(); return; }
    if (/[\\/]/.test(n)) { err.say("The name is one file name, without slashes; open its folder in the list."); name.focus(); return; }
    if (!n.toLowerCase().endsWith(files)) n += files;
    const taken = shown && shown.entries.find((e) => e.file && e.name.toLowerCase() === n.toLowerCase());
    if (taken) { err.say(n + " exists already: pick it in the list to use it."); name.focus(); return; }
    pick(joinPath(shown.path, n));
  };
  if (newName) {
    name.addEventListener("keydown", (e) => {
      if (e.key === "Enter") { e.preventDefault(); e.stopPropagation(); createNew(); }
    });
    create = el("div", { class: "field", dataset: { folder: "new" } },
      el("label", { for: "folder-new-name" }, newName === true ? "New file name" : newName),
      el("div", { class: "row" }, name, el("button", { type: "button", dataset: { folder: "create" }, onclick: createNew }, "Create here")),
      hint(`A new file in the folder shown above (${files} is added). Nothing is written until the build.`));
  }
  const edsTag = (n) => (eds && n ? el("span", { class: "tag" }, n + " EDS") : null);
  const kindTag = (e) => (e.project ? el("span", { class: "tag", dataset: { folderKind: "project" } }, "OpenPLC project")
    : e.config ? el("span", { class: "tag", dataset: { folderKind: "config" } }, "canworks config") : null);
  const select = (b) => {
    for (const x of list.querySelectorAll("[aria-pressed]")) x.setAttribute("aria-pressed", "false");
    b.setAttribute("aria-pressed", "true");
    selected = b.dataset.folderPath;
  };
  async function open(where, drives) {
    const inList = list.contains(document.activeElement);
    let r;
    try {
      r = await api("GET", "/api/folders?" + (drives ? "drives=1" : "path=" + encodeURIComponent(where)) +
        (files ? "&files=" + encodeURIComponent(files) : ""));
    } catch (e) {
      err.say(e.message);
      return false;
    }
    err.say("");
    shown = r;
    selected = null;
    path.value = r.path;
    up.disabled = !r.parent && !r.drive;
    const nFiles = r.entries.filter((e) => e.file).length;
    const kind = files ? files.split(",").join(" or ") : "";
    here.textContent = r.drive_list ? "Drives on this PC"
      : files ? (!nFiles ? `No ${kind} files in this folder` : nFiles === 1 ? `1 ${kind} file in this folder` : `${nFiles} ${kind} files in this folder`)
      : !eds ? ""
      : !r.eds ? "No EDS files in this folder" : r.eds === 1 ? "1 EDS file in this folder" : r.eds + " EDS files in this folder";
    here.hidden = !here.textContent;
    list.replaceChildren(...r.entries.map((e) => el("li", null, e.file
      ? el("button", { type: "button", class: "folder file", title: e.path, dataset: { filePath: e.path }, onclick: () => pick(e.path) }, "📄 " + e.name)
      : el("button", { type: "button", class: "folder", title: e.path, "aria-pressed": "false", dataset: { folderPath: e.path },
        onclick: (ev) => select(ev.currentTarget), ondblclick: () => open(e.path) },
        "📁 " + e.name, kindTag(e), files ? null : edsTag(e.eds)))));
    if (!r.entries.length) list.append(el("li", { class: "muted" }, r.drive_list ? "No drives found" : files ? `No subfolders or ${kind} files` : "No subfolders"));
    if (create) create.hidden = !!r.drive_list;
    if (inList || (up.disabled && document.activeElement === up)) (list.querySelector("button") || path).focus();
    return true;
  }
  const goUp = () => { if (shown && shown.parent) open(shown.parent); else if (shown && shown.drive) open("", true); };
  up.onclick = goUp;
  go.onclick = () => open(path.value.trim());
  // Enter in the path field opens the typed folder (not Use this folder).
  path.addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); e.stopPropagation(); open(path.value.trim()); }
  });
  list.addEventListener("keydown", (e) => {
    const items = [...list.querySelectorAll("button")];
    const i = items.indexOf(document.activeElement);
    if (e.key === "Enter" && i >= 0 && items[i].dataset.folderPath) {
      e.preventDefault();
      open(items[i].dataset.folderPath);
    } else if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      const to = items[Math.max(0, Math.min(items.length - 1, i + (e.key === "ArrowDown" ? 1 : -1)))];
      if (to) to.focus();
    } else if (e.key === "Home" || e.key === "End") {
      e.preventDefault();
      const to = e.key === "Home" ? items[0] : items[items.length - 1];
      if (to) to.focus();
    } else if (e.key === "Backspace" || (e.key === "ArrowLeft" && e.altKey) || (e.key === "ArrowUp" && e.altKey)) {
      e.preventDefault();
      goUp();
    }
  });
  // Its own dialog, so it can open over another one (Add to a config…).
  // File mode picks a file or a new name; there is no folder to use.
  const use = el("button", { type: "button", class: "primary", dataset: { value: "use" }, hidden: files ? true : null }, "Use this folder");
  const cancel = el("button", { type: "button", dataset: { value: "cancel" } }, "Cancel");
  const dlg = el("dialog", { class: "folder-dialog", "aria-labelledby": "folder-dialog-title", dataset: { folder: "dialog" } },
    el("h2", { id: "folder-dialog-title" }, title),
    el("div", { class: "folder-picker" }, err, el("div", { class: "row" }, up, path, go), here, list, create, note ? hint(note) : null),
    el("menu", null, cancel, use));
  // The nearest folder that exists: the start, else its parents, else home.
  let ok = false;
  for (let p = start; p && !ok; ) {
    ok = await open(p);
    const parent = p.replace(/[\\/]+[^\\/]*$/, "");
    if (ok || parent === p || !parent) break;
    p = /^[A-Za-z]:$/.test(parent) ? parent + "\\" : parent;
  }
  if (!ok) await open(S.state && S.state.home ? S.state.home : "~");
  err.say("");
  const opener = document.activeElement;
  document.body.append(dlg);
  const answer = await new Promise((resolve) => {
    use.onclick = () => resolve("use");
    pick = (p) => resolve({ file: p });
    cancel.onclick = () => resolve(null);
    dlg.addEventListener("cancel", (e) => { e.preventDefault(); resolve(null); });
    dlg.showModal();
    (list.querySelector("button") || path).focus();
  });
  dlg.close();
  dlg.remove();
  if (opener && opener.isConnected) opener.focus();
  if (answer && answer.file) return answer.file;
  if (answer !== "use") return null;
  // A typed path not opened with Go is used as typed: the caller checks it.
  const typed = path.value.trim();
  if (typed && (!shown || typed !== shown.path)) return typed;
  if (selected) return selected;
  return shown && !shown.drive_list ? shown.path : null;
}

async function openFolder(path, mode, isNew) {
  try {
    banner("");
    await api("POST", "/api/open", { path, mode, new: isNew });
    await opened(null);
  } catch (e) {
    if (e.body && e.body.no_config) {
      const v = await modal(e.message + ". Start a new config there?", [["new", "New config…", true], ["cancel", "Cancel"]]);
      if (v === "new") return newConfig(e.body.path || path);
    } else if (e.body && e.body.not_a_project) {
      const v = await modal(e.message + ".", [["standalone", "Open as config folder", true], ["cancel", "Cancel"]]);
      if (v === "standalone") return openFolder(path, "standalone");
    } else if (e.body && e.body.is_project) {
      const v = await modal(e.message + ".", [["project", "Open as project", true], ["cancel", "Cancel"]]);
      if (v === "project") return openFolder(path, "project");
    } else {
      banner(e.message, true);
    }
  }
}

// After a folder opened: the page shows it; a new config for the bridge or
// CODESYS starts as that target's empty config.
async function opened(target) {
  S.view = "bus";
  await loadState();
  if (S.state.folder) S.lastFolder = splitPath(S.state.folder)[0];
  if (target && target !== "openplc" && S.model) {
    bridgeReplaceDraft((await api("POST", "/api/switch_target", { config: fileConfig(), target })).config);
    changed(true);
  }
  // The start page is gone: keyboard focus goes to the network tree, not the page body.
  const a = document.activeElement;
  if (!a || a === document.body || !a.isConnected || a.closest("#start")) {
    const to = document.querySelector('#tree [role=treeitem][tabindex="0"]') || document.querySelector("#view h2");
    if (to) { if (!to.hasAttribute("tabindex")) to.setAttribute("tabindex", "-1"); to.focus(); }
  }
}

// ---------------------------------------------------------------------------
// Editor

function render() {
  if (TRACE_WINDOW) {
    // The trace's own window shows the Trace view and nothing else (tracewin.js).
    if (!S.state || !S.state.mode) return renderTraceWindowEmpty();
    S.view = "trace";
  }
  if (!S.state || !S.state.mode) return S.devicesOnly ? renderDevicesOnly() : renderStart();
  document.body.classList.remove("devices-only");
  $("#start").hidden = true;
  $("#editor").hidden = false;
  $("#actions").hidden = false;
  fitHeaderMore();
  const badge = $("#mode");
  badge.hidden = false;
  badge.replaceChildren(el("span", { class: "mode-name" }, S.state.commission ? "commissioning a device (nothing here is saved to a project)"
    : S.state.mode === "project" ? "project " + S.state.name : "config " + S.state.name));
  badge.title = S.state.config_path;
  if (!S.state.commission && S.model) {
    // The target opens the Project page, where it is switched.
    badge.append(el("span", { class: "target-mark", dataset: { targetMark: projectTarget() } }, " · ",
      el("button", { type: "button", class: "link", dataset: { openProject: "1" }, title: "Open the Project page: target and Online access",
        onclick: () => { switchWorkspace("configure"); showView("project"); } }, TARGET_TITLE[projectTarget()])));
  }
  // "● unsaved": in a narrow window only the dot shows (its title says it).
  if (!S.state.commission) badge.append(el("span", { class: "unsaved-mark", dataset: { unsaved: "1" }, hidden: !S.dirty, title: "Unsaved changes" }, " ●", el("span", { class: "unsaved-word" }, " unsaved")));
  // Commissioning a device: no config, so nothing that edits, saves or checks one.
  const commission = !!S.state.commission;
  document.body.classList.toggle("commission", commission);
  $("#editor").classList.toggle("commission", commission);
  // The editor project actions are OpenPLC's (canopen-configurator "Only what the target uses is shown").
  $("#menu-project").hidden = S.state.mode !== "standalone" || commission || (!!S.model && !usedBy("ui:editor_project"));
  // The target's own action: one split button in the header (CODESYS:
  // Build, with Download under ▾; the bridge: Install on device…).
  const codesys = !commission && !!S.model && codesysOn();
  const bridge = !commission && !!S.model && projectTarget() === "bridge";
  $("#btn-codesys-build").hidden = !codesys;
  $("#btn-codesys-download").hidden = !codesys;
  $("#menu-target").hidden = !codesys;
  $("#btn-bridge-install").hidden = !bridge;
  $("#target-action").hidden = !codesys && !bridge;
  Icons.setDisabled($("#btn-export-node"), !S.view.startsWith("node:") && "Open a node first.");
  // Exports that do not apply are not offered: no DCF of a slave or J1939
  // network (none at all, and no CODESYS export, without a CANopen master
  // network), no DBC of a slave.
  if (S.model) {
    $("#btn-export-all").hidden = !S.model.networks.some(dcfNetwork);
    $("#btn-export-node").hidden = !dcfNetwork(S.config);
    $("#btn-export-dbc").closest(".menu-row").hidden = isSlave(S.config);
  }
  // A J1939 network has no nodes or simulated devices.
  if (!commission) {
    if (isJ1939(S.config) && (S.view.startsWith("node:") || S.view === "simfile")) S.view = "bus";
    if (isPlain(S.config) && S.view.startsWith("node:")) S.view = "bus";
    if (S.view === "bridge" && !S.model.top.bridge) S.view = "bus";
    if (S.view === "codesys" && !codesysOn()) S.view = "bus";
    if (S.view === "raw" && !usedBy("raw")) S.view = "bus";
    if (S.view === "gateway" && !usedBy("/gateway")) S.view = "bus";
    if (S.view === "declarations" && !usedBy("ui:declarations")) S.view = "bus";
    if (S.view === "links" && !linksNetwork(S.config)) S.view = "bus";
  }
  // The view belongs to the workspace shown (shell.js).
  fitView();
  renderSide();
  renderShell();
  updateSimBanner();
  // The connection stays open across views until Disconnect (connection.js);
  // the views only stop their own timers.
  stopOnline();
  stopSim(S.view === "simulation" || S.view === "simfile");
  stopTrace();
  const view = $("#view");
  view.replaceChildren();
  view.classList.toggle("wide-cols", S.view === "bus");
  if (S.view === "bus") {
    (isJ1939(S.config) ? renderJ1939(view) : isPlain(S.config) ? renderPlainBus(view) : renderBus(view));
  }
  else if (S.view === "raw") renderCanMessages(view);
  else if (S.view === "declarations") renderDeclarations(view);
  else if (S.view === "online") renderOnline(view);
  else if (S.view === "nodes") renderCommNodes(view);
  else if (S.view === "trace") renderTrace(view);
  else if (S.view === "gateway") renderGateway(view);
  else if (S.view === "project") renderProject(view);
  else if (S.view === "bridge") renderBridge(view);
  else if (S.view === "codesys") renderCodesys(view);
  else if (S.view === "simulation" || S.view === "simfile") renderSimulation(view);
  else if (S.view === "framelab") renderFrameLab(view);
  else if (S.view === "links") renderLinks(view);
  else if (S.view === "devices") renderDevices(view);
  else renderNode(view, Number(S.view.slice(5)));
  if (workspace() === "configure") applyTarget(view);
  applyCheck();
  if (TRACE_WINDOW) traceWinBar();
  else traceWinSendConn();
}

function renderSide() {
  renderTree();
  const unused = S.state.unused_eds || [];
  $("#unused-eds").replaceChildren(...(unused.length ? [el("h2", { class: "side-caption" }, "Unused EDS files"),
    el("p", { class: "muted" }, unused.join(", ") + " (left in place, never deleted)")] : []));
  // The editor project's address scan is OpenPLC's.
  $("#scan-info").hidden = !!S.model && !usedBy("ui:editor_project");
  $("#scan-info").textContent = S.state.mode === "project"
    ? `Project addresses scanned ${S.state.scanned_at}: ${S.state.project_uses.length} in use.`
    : "Standalone: address checks against an editor project are skipped.";
}

const BUS_DIAG = [
  ["bus_state_location", "Bus state", "%IB…",
    "0 no bus (interface missing or down), 1 error-active, 2 error-warning, 3 error-passive (a pulled cable ends here), 4 bus-off. Empty: none."],
  ["tx_error_count_location", "TX errors", "%IB…", "The controller's transmit error counter (0-255). Empty: none."],
  ["rx_error_count_location", "RX errors", "%IB…", "The controller's receive error counter (0-255). Empty: none."],
  ["bus_off_count_location", "Bus-off count", "%IW…",
    "bus_off_count"],
  ["state_location", "Master state", "%IB…",
    "The master's own NMT state: 5 operational, 127 pre-operational (start off, or a mandatory node missing), 4 stopped. Empty: none."],
];

// Fields only one adapter type takes; switching type drops the other type's.
const ADAPTER_ONLY = { socketcan: ["configure_link", "restart_ms"], slcan: ["device", "serial_baudrate"] };

function switchAdapterType(type) {
  const ad = S.config.adapter || (S.config.adapter = {});
  for (const [t, keys] of Object.entries(ADAPTER_ONLY)) if (t !== type) for (const k of keys) delete ad[k];
  ad.type = type;
  changed(true);
}

// ---------------------------------------------------------------------------
// What is simulated (docs/simulator.md, "Two switches"): the network
// (adapter.simulate) and each node (simulate). A node's field is stored only
// when it differs from the network's default (simulated on a simulated
// network, real on a real one), so switching the network sets every node back
// to that default.

// A target that runs no canworks simulation (CODESYS) simulates nothing,
// whatever its config still says.
function simIgnored() { return !!S.model && !!S.state && !!S.state.targets && !usedBy("ui:simulation"); }
function simNetwork(net = S.config) { return !simIgnored() && !!(net && net.adapter && net.adapter.simulate === true); }
function nodeSimulated(n, net = S.config) { return !simIgnored() && (n.simulate === undefined ? simNetwork(net) : n.simulate === true); }
function netSimulates(net) { return simNetwork(net) || (net.nodes || []).some((n) => nodeSimulated(n, net)); }
function anySimulated() { return !!S.model && S.model.networks.some(netSimulates); }
function nodeIds(list) { return list.map((n) => n.node_id ?? "?").join(", "); }
function plural(list, one, many) { return list.length === 1 ? one : many; }
// "1 error", "2 errors".
function counted(n, one, many) { return `${n} ${n === 1 ? one : many}`; }

function simBadge(n) {
  if (nodeSimulated(n)) return el("span", { class: "tag sim-tag", dataset: { simBadge: "simulated" }, title: "A simulated device" }, "simulated");
  if (simNetwork()) return el("span", { class: "tag", dataset: { simBadge: "absent" }, title: "Absent from the simulated network" }, "absent");
  return null;
}

// What is simulated in one network, in one sentence, or "" when nothing is.
function netSimSummary(net) {
  if (isSlave(net)) {
    if (!simNetwork(net)) return "";
    const iface = (net.adapter && net.adapter.interface) || "";
    return `The slave runs on the simulated bus ${iface} inside the plugin, where a simulated master network with the same interface name reaches it.`;
  }
  const nodes = net.nodes || [];
  const sim = nodes.filter((n) => nodeSimulated(n, net));
  if (simNetwork(net)) {
    // The plugin's own slave on the same simulated bus serves its node ID.
    const iface = (net.adapter && net.adapter.interface) || "";
    const slaveIds = ((S.model && S.model.networks) || []).filter((o) => isSlave(o) && simNetwork(o) && iface &&
      o.adapter.interface === iface && o.slave && Number.isInteger(o.slave.node_id)).map((o) => o.slave.node_id);
    const served = nodes.filter((n) => !nodeSimulated(n, net) && slaveIds.includes(n.node_id));
    const absent = nodes.filter((n) => !nodeSimulated(n, net) && !served.includes(n));
    return "The network is simulated: the master runs on a virtual bus inside the plugin" +
      (sim.length ? `, with ${plural(sim, "node", "nodes")} ${nodeIds(sim)} simulated` : ", with no node simulated") +
      (absent.length ? ` and ${plural(absent, "node", "nodes")} ${nodeIds(absent)} absent` : "") +
      (served.length ? `; node ${nodeIds(served)} is the plugin's own slave on the same bus` : "") + ".";
  }
  if (!sim.length) return "";
  const iface = (net.adapter && net.adapter.interface) || "";
  return `${plural(sim, "Node", "Nodes")} ${nodeIds(sim)} ${plural(sim, "is", "are")} simulated on the real network${iface ? " " + iface : ""}.`;
}

// What is simulated, network by network when there are several, or "".
function simSummary() {
  if (!S.config || !S.model) return "";
  if (!several()) return netSimSummary(S.config);
  const parts = S.model.networks.map((net, i) => [net, i]).filter(([net]) => netSimulates(net))
    .map(([net, i]) => `${upperFirst(netNamed(net, i))}: ${netSimSummary(net)}`);
  if (!parts.length) return "";
  return parts.join(" ");
}

// What is simulated in one network, in a few words: "(nodes 5, 6, 7)".
function netSimShort(net) {
  if (isSlave(net)) return simNetwork(net) ? "slave" : "";
  const sim = (net.nodes || []).filter((n) => nodeSimulated(n, net));
  if (simNetwork(net)) return sim.length ? `${plural(sim, "node", "nodes")} ${nodeIds(sim)}` : "bus only";
  return sim.length ? `${plural(sim, "node", "nodes")} ${nodeIds(sim)} on the real bus` : "";
}

// The one-line form (canopen-configurator: "Simulation banner on one line").
function simShort() {
  if (!S.config || !S.model) return "";
  if (!several()) {
    const t = netSimShort(S.config);
    return t && (simNetwork(S.config) && !isSlave(S.config) ? `the network (${t})` : t);
  }
  return S.model.networks.map((net, i) => [net, i]).filter(([net]) => netSimulates(net))
    .map(([net, i]) => `${netLabel(net, i)} (${netSimShort(net)})`).join(", ");
}

const SIM_WARNING = "This configuration must not be uploaded to a machine as it is: its simulated devices control nothing.";

// The chip in the header while anything is simulated (compact-chrome):
// what is simulated in a few words, the full text and the warning under
// Details, in a popover. It takes no row of its own.
function updateSimBanner() {
  const b = $("#sim-banner");
  if (!b) return;
  const text = S.state && S.state.mode ? simSummary() : "";
  b.hidden = !text;
  if (!text) { b.replaceChildren(); b.removeAttribute("aria-label"); return; }
  const wasOpen = !!b.querySelector("[data-sim=details]:not([hidden])");
  const full = el("p", { id: "sim-details", dataset: { sim: "details" }, hidden: wasOpen ? null : true },
    text + " " + SIM_WARNING + " Do not upload it as it is.");
  const toggle = el("button", { type: "button", class: "small", dataset: { sim: "details-toggle" }, "aria-expanded": String(wasOpen),
    "aria-controls": "sim-details",
    onclick: () => { full.hidden = !full.hidden; toggle.setAttribute("aria-expanded", String(!full.hidden)); toggle.textContent = full.hidden ? "Details" : "Hide details"; } },
  wasOpen ? "Hide details" : "Details");
  const nets = several() ? S.model.networks.filter(netSimulates).length : 0;
  const what = nets > 1 ? `${nets} networks` : simShort();
  const line = `Simulated: ${what}`;
  b.setAttribute("aria-label", line + ". Do not upload it to a machine as it is.");
  // In a narrow window only "Simulated" shows, so the header stays one row.
  b.replaceChildren(Icons.stateIcon("warning", { label: false }),
    el("span", { class: "sim-text", title: text + " " + SIM_WARNING, dataset: { sim: "line" } }, "Simulated", el("span", { class: "sim-what" }, ": " + what)), toggle, full);
}

// Simulating anything needs online access with Allow changes for the
// Simulation view; turned on when online access is off.
async function simulationNeedsOnline() {
  if (!anySimulated() || diagConfig()) return;
  try {
    if (!S.online.token) {
      const r = await api("POST", "/api/online/token", { action: "generate" });
      S.online = Object.assign(S.online, r);
    }
    S.model.diagnostics = { token_verifier: await verifierForToken(), allow_changes: true };
    await checkToken();
    banner("Online access is now on with Allow changes, so Commission → Simulation can control the simulated devices. Save and upload to use it.", "info");
  } catch (e) { banner(e.message, true); }
}

async function setNetwork(simulated) {
  const ad = S.config.adapter || (S.config.adapter = {});
  if (simulated) ad.simulate = true; else delete ad.simulate;
  for (const n of S.config.nodes || []) delete n.simulate;
  await simulationNeedsOnline();
  changed(true);
}

function storeSimulate(n, on) {
  if (on === simNetwork()) delete n.simulate; else n.simulate = on;
}

async function setNodeSimulated(i, on) {
  storeSimulate(S.config.nodes[i], on);
  await simulationNeedsOnline();
  changed(true);
}

async function simulateAll(on) {
  for (const n of S.config.nodes || []) storeSimulate(n, on);
  await simulationNeedsOnline();
  changed(true);
}

function networkSettings() {
  const nodes = S.config.nodes || [];
  const sim = nodes.filter((n) => nodeSimulated(n));
  return el("fieldset", { dataset: { section: "network" } }, el("legend", null, "Network"),
    el("div", { class: "grid" },
      choice("Network", "adapter.simulate", [
        { value: undefined, label: "Real",
          help: "The CAN adapter below. Nodes switched to Simulated run as simulated devices inside the plugin on the same interface, next to the real devices." },
        { value: true, label: "Simulated",
          help: targetText("sim_network") },
      ], { onChange: (v) => setNetwork(v === true) })),
    el("div", { class: "toolbar" },
      el("span", { dataset: { sim: "nodes" } }, nodes.length
        ? (sim.length ? `Simulated: ${plural(sim, "node", "nodes")} ${nodeIds(sim)}.` : "No node is simulated.") : "No nodes yet."),
      el("button", { type: "button", dataset: { sim: "all" }, disabled: !nodes.length, onclick: () => simulateAll(true) }, "Simulate all"),
      el("button", { type: "button", dataset: { sim: "none" }, disabled: !nodes.length, onclick: () => simulateAll(false) }, "Simulate none")),
    hint("A simulated device is built from the node's EDS. Its behaviour, faults and scenarios are set in Simulation file (simulation.json)."));
}

// A slave network on the simulated bus (docs/slave.md, "Simulated bus").
function slaveNetworkSettings() {
  return el("fieldset", { dataset: { section: "network" } }, el("legend", null, "Network"),
    el("div", { class: "grid" },
      choice("Network", "adapter.simulate", [
        { value: undefined, label: "Real",
          help: "The CAN adapter below." },
        { value: true, label: "Simulated",
          help: "The simulated bus inside the plugin named by the interface below: a simulated master network with the same interface name runs the plugin's own master against this slave, with no CAN adapter. On that master, set the node for this slave to not simulated. The adapter settings below are kept for switching back." },
      ], { onChange: (v) => {
        const ad = S.config.adapter || (S.config.adapter = {});
        if (v === true) ad.simulate = true; else delete ad.simulate;
        changed(true);
      } })));
}

// Whether the page offers simulated devices: the target runs canworks (or
// every field is shown). A CODESYS config's leftover `simulate` is listed in
// the page's bar instead (target.js).
function simulationShown() {
  return usedBy("ui:simulation");
}

// The node page's Simulated switch.
function simSwitch(i) {
  const n = S.config.nodes[i];
  if (!simulationShown()) return null;
  const on = nodeSimulated(n);
  const input = el("input", { type: "checkbox", dataset: { sim: "node" } });
  input.checked = on;
  input.addEventListener("change", () => setNodeSimulated(i, input.checked));
  const help = simNetwork()
    ? (on ? "A simulated device on the simulated network (the default there)." : "Absent: the node is left off the simulated network, as an unplugged device. Its status bit stays FALSE.")
    : (on ? "A simulated device inside the plugin on the real network, next to the real devices. It starts only when no real device answers with its node ID."
      : "A real device on the bus (the default on a real network).");
  return el("div", { class: "check-field" }, el("label", { class: "check" }, input, " Simulated"), hint(help));
}

// SYNC source: off (no SYNC keys), the master's timer (a period) or the PLC
// cycle (a cycle count); the period and the cycle count exclude each other.
function syncSource(m) {
  m = m || {};
  if (m.sync_source === "plc_cycle") return "plc_cycle";
  const us = m.sync_period_us;
  return us !== undefined && us !== null && us !== "" && us !== 0 ? "timer" : undefined;
}

function switchSyncSource(source) {
  const m = S.config.master || (S.config.master = {});
  if (source === "plc_cycle") {
    m.sync_source = "plc_cycle";
    delete m.sync_period_us;
  } else {
    delete m.sync_source;
    delete m.sync_cycles;
    if (source === "timer") {
      if (syncSource(m) !== "timer") m.sync_period_us = 10000;  // a starting period
    } else delete m.sync_period_us;
  }
  changed(true);
}

// The SYNC period field; emptied, SYNC is off and the choice shows Off.
function syncPeriodField() {
  const f = field("SYNC period (ms)", "master.sync_period_us", "int", {
    show: (us) => (typeof us === "number" ? us / 1000 : us),
    parse: (t) => (/^[0-9]+(\.[0-9]+)?$/.test(t) ? Math.round(parseFloat(t) * 1000) : t),
    placeholder: "off",
    hint: "How often the master sends SYNC; synchronous PDOs move at this rate. Empty: SYNC off.",
  });
  const input = f.querySelector("input");
  input.addEventListener("change", () => { if (!input.value.trim()) render(); });
  return f;
}

// The CAN adapter of the open network (CANopen and J1939 alike).
function adapterFieldset() {
  const a = "adapter";
  const slcan = getPath("adapter.type") === "slcan";
  const rateSel = el("select", { dataset: { path: "adapter.bitrate" }, "aria-label": "Bit rate" },
    BITRATES.map((r) => el("option", { value: r }, (r >= 1000000 ? r / 1000000 + " Mbit/s" : r / 1000 + " kbit/s"))));
  const rate = getPath("adapter.bitrate");
  if (rate !== undefined && !BITRATES.includes(rate)) rateSel.prepend(el("option", { value: rate }, String(rate) + " (not CiA 301)"));
  rateSel.value = rate === undefined ? "" : String(rate);
  rateSel.addEventListener("change", () => setPath("adapter.bitrate", Number(rateSel.value)));
  const body = [
      el("div", { class: "grid" },
        choice("Adapter type", a + ".type", [
          { value: "socketcan", label: "SocketCAN (CAN HAT, candleLight/gs_usb, PEAK, vcan)",
            help: "An interface the PLC already has: a CAN HAT, a CANable with candleLight firmware, a PEAK USB adapter, or vcan0." },
          { value: "slcan", label: "CANable / serial (slcan)",
            help: "A serial-line adapter: a CANable with its stock slcan firmware, or a Lawicel CANUSB. The plugin creates the interface from the serial device itself, so no slcand service is needed." },
        ], { onChange: switchAdapterType }),
        slcan ? field("Serial device", a + ".device", "text", { placeholder: "/dev/serial/by-id/usb-…",
          hint: "Required. The adapter's device on the PLC (the Pi). Use the /dev/serial/by-id/… path (ls /dev/serial/by-id/): /dev/ttyACM0 can change number when the adapter is plugged in again." }) : null,
        field("Interface", a + ".interface", "text", { list: "ifaces", placeholder: "can0",
          hint: codesysOn() ? "Optional. The bus's name in canworks; a name ending in a number (can1) gives the CODESYS network number when it is not set below."
            : slcan ? "Required. The name the plugin gives the interface it creates, such as can0. Nothing else may use that name (stop an old slcand service)."
            : targetText("interface") }),
        el("label", null, "Bit rate", rateSel, hint("Required. Every node on the bus must use the same rate."),
          el("span", { class: "field-msg", dataset: { for: "adapter.bitrate" } })),
        slcan ? field("Serial speed (baud)", a + ".serial_baudrate", "int", { placeholder: "leave as is",
          hint: "Only for adapters behind a real serial port, such as the FTDI-based Lawicel CANUSB. A CANable ignores it." }) : null,
        slcan ? el("p", { class: "hint wide" },
          "slcan firmware does not report the CAN error state: the bus state input shows only whether the link is up, and the error counters read 0. For error state and counters, flash a CANable with candleLight firmware and use SocketCAN.") : null,
        slcan ? null : checkbox(targetText("configure_link"), a + ".configure_link", true,
          "Off: the interface must already be up at the right rate, for example from the OS network setup."),
        slcan ? null : field("Bus-off restart (ms)", a + ".restart_ms", "intstr", { placeholder: "not set",
          hint: targetText("restart") })),
      el("datalist", { id: "ifaces" }, ["can0", "can1", "vcan0"].map((v) => el("option", { value: v })))];
  if (!simNetwork()) return el("fieldset", null, el("legend", null, "CAN adapter"), ...body);
  // A simulated network uses no adapter: the section folds, opened by hand when wanted.
  S.advOpen = S.advOpen || {};
  const d = el("details", { class: "advanced", dataset: { advanced: "adapter" } },
    el("summary", null, "CAN adapter (not used while the network is simulated)"), ...body);
  d.open = !!S.advOpen.adapter;
  d.addEventListener("toggle", () => { S.advOpen.adapter = d.open; });
  return d;
}

// A CANopen master network without nodes: the first step, not an error
// (spec "Empty network is a warning").
function noNodesYet() {
  return el("p", { class: "empty-state", dataset: { emptyNodes: "1" } }, "No nodes yet: ",
    el("button", { type: "button", dataset: { emptyAdd: "1" }, onclick: () => addNodeDialog() }, "Add node…"),
    ", or find the devices on the bus in Commission.");
}

function renderBus(view) {
  const sync = syncSource(S.config.master);
  const slave = isSlave(S.config);
  view.append(
    el("h2", null, (slave ? "Bus and slave device" : "Bus and master") + (several() ? `: ${netNamed(S.config, S.net)}` : "")),
    ...(dcfNetwork(S.config) && !(S.config.nodes || []).length ? [noNodesYet()] : []),
    protocolField(),
    roleField(),
    ...(simulationShown() ? [slave ? slaveNetworkSettings() : networkSettings()] : []),
    adapterFieldset(),
    ...(!slave && usedBy("ui:codesys") ? [codesysNetworkFieldset()] : []),
    ...(slave ? slaveFieldsets() : [el("fieldset", null, el("legend", null, "Master"),
      el("div", { class: "grid" },
        field("Node ID", "master.node_id", "intstr", { placeholder: "1",
          hint: "Required, 1 to 127, and not used by any slave. New configs start with 1." }),
        choice("SYNC source", "master.sync_source", [
          { value: undefined, label: "Off",
            help: "Default. The master sends no SYNC: every PDO needs an event-driven transmission type (254 or 255)." },
          { value: "timer", label: "Timer",
            help: "The master sends SYNC at a fixed period of its own, independent of the PLC cycle." },
          { value: "plc_cycle", label: "PLC cycle",
            help: "One SYNC at the start of every PLC cycle (or every N cycles): inputs are one cycle old and outputs reach the devices after a fixed delay. The SYNC period is the PLC task interval; give every task an interval that is a multiple of the fastest one." },
        ], { onChange: switchSyncSource, current: sync || "" }),
        sync === "plc_cycle" ? field("Every N PLC cycles", "master.sync_cycles", "intstr", { placeholder: "1",
          hint: "1 to 1000. Empty: a SYNC every PLC cycle." }) : sync === "timer" ? syncPeriodField() : null,
        field("Master heartbeat (ms)", "master.heartbeat_ms", "intstr", { placeholder: "off",
          hint: "Empty: off. Set it when slaves should watch the master." }),
        choice("When the PLC stops", "master.on_plc_stop", [
          { value: undefined, literal: "preop", label: "Pre-operational",
            help: "Default. Each node that is up gets ENTER PRE-OPERATIONAL before the network closes: its PDOs stop, so its own communication-loss setting applies, and SDO access stays for a restart." },
          { value: "stop", label: "Stopped", help: "Each node that is up gets NMT STOP: PDOs and SDO stop until the next PLC start." },
          { value: "keep", label: "Keep running", help: "Nothing is sent: the nodes keep the last outputs they got. Only for devices that are safe that way." },
        ]),
        field("Scan watchdog (ms)", "master.scan_watchdog_ms", "intstr", { placeholder: "1000",
          hint: "When the PLC scan has not advanced for this long while the PLC runs, the outputs stop (RPDOs and raw sends; SYNC goes on) until it advances again. 10 to 60000, 0 turns it off. Empty: 1000." }),
        choice("EDS lint (dcfgen)", "master.eds_lint", [
          { value: undefined, literal: "communication", label: "Communication objects",
            help: targetText("lint_communication") },
          { value: "all", label: "Every object", help: targetText("lint_all") },
          { value: "off", label: "Off", help: targetText("lint_off") },
        ]))),
    el("fieldset", null, el("legend", null, "Bus diagnostics"),
      el("p", { class: "muted" }, "Optional inputs that let the program tell a bus fault (cable, termination, bit rate) from one missing node."),
      el("div", { class: "grid" }, BUS_DIAG.map(([key, label, placeholder, help]) => {
        const path = "master." + key;
        const btn = el("button", { type: "button", dataset: { suggest: key },
          onclick: async () => {
            const r = await api("POST", "/api/place", { config: fileConfig(), network: S.net, direction: key });
            setPath(path, r.location);
            render();
          } }, "Suggest");
        return el("label", null, label, el("span", { class: "row" },
          field("", path, "text", { placeholder }).querySelector("input"), btn),
          hint(TARGET_TEXT[help] ? targetText(help) : help),
          el("span", { class: "field-msg", dataset: { for: path } }),
          declNote(path));
      })))]),
    ...(slave ? [] : [masterAdvanced()]));
}

// Online access (the plugin's diagnostics channel, with the CiA 309-3
// gateway part): one setting for the whole config, its own tree entry.
// The Project page: what the whole project is, not one network. The target
// (target.js) and, when the target runs canworks, Online access.
function renderProject(view) {
  view.append(el("h2", null, "Project"), targetField());
  if (!usedBy("ui:runtime")) return;
  view.append(el("h3", { id: "online-access" }, "Online access"),
    el("p", { class: "muted" }, "The runtime's encrypted diagnostics channel, for the Commission workspace, Trace and Simulation. One setting for every network of this config."),
    onlineAccessSettings(),
    cia309Settings());
}

// A collapsed section of rarely needed settings. It opens by itself when one
// of `keys` is set under `base`, and remembers being opened by hand.
function advanced(id, title, base, keys, ...children) {
  S.advOpen = S.advOpen || {};
  const obj = getPath(base) || {};
  const set = keys.filter((k) => obj[k] !== undefined);
  const d = el("details", { class: "advanced", dataset: { advanced: id } },
    el("summary", null, title + (set.length ? ` (${set.length} set)` : "")), ...children);
  d.open = S.advOpen[id] !== undefined ? S.advOpen[id] : set.length > 0;
  d.addEventListener("toggle", () => { S.advOpen[id] = d.open; });
  return d;
}

// Object 0x1029 as "1=0, 2=1" text (sub-index = value), stored as an object.
function errorBehaviorField(label, path, help) {
  const show = (o) => (o && typeof o === "object" ? Object.entries(o).map(([k, v]) => `${k}=${v}`).join(", ") : o);
  const parse = (t) => {
    const out = {};
    for (const part of t.split(/[,;\s]+/).filter(Boolean)) {
      const m = part.match(/^([0-9]+|0x[0-9a-f]+)=([0-9]+|0x[0-9a-f]+)$/i);
      if (!m) return t;
      out[m[1]] = /^[0-9]+$/.test(m[2]) ? parseInt(m[2], 10) : m[2];
    }
    return out;
  };
  return field(label, path, "text", { show, parse, placeholder: "EDS default", hint: help });
}

const u32 = (t) => (/^[0-9]+$/.test(t) ? parseInt(t, 10) : t);

function masterAdvanced() {
  const m = "master.";
  const keys = ["vendor_id", "product_code", "revision_number", "serial_number", "sync_window_us",
    "sync_counter_overflow", "time_cob_id", "time_period_ms", "emcy_inhibit_time_us", "heartbeat_consumer", "heartbeat_multiplier",
    "error_behavior", "nmt_inhibit_time_us", "start", "start_nodes", "start_all_nodes", "reset_all_nodes",
    "stop_all_nodes", "boot_time_ms", "sdo_timeout_ms"];
  return advanced("master", "Advanced master settings", "master", keys,
    el("p", { class: "muted" }, "dcfgen's master options. Leave them empty unless a device or the plant needs them."),
    el("h3", null, "Start-up"),
    el("div", { class: "grid" },
      el("div", null, checkbox("Master goes operational", m + "start", true,
        "Off: the master stays pre-operational and no PDOs move until the PLC program starts it with CO_NETWORK_START."),
        el("button", { type: "button", dataset: { action: "network-start-st" },
          title: "Copy as ST call (CO_NETWORK_START block)", onclick: async () => {
            await copyText(stNetworkStartCall());
            banner("Copied the CO_NETWORK_START call. Enable the canworks library in the editor project to use it.");
          } }, "Copy as ST call")),
      checkbox("Start the nodes", m + "start_nodes", true,
        "Off: the master configures the nodes but leaves them pre-operational."),
      checkbox("Start all nodes with one command", m + "start_all_nodes", false,
        "On: one broadcast NMT start once every mandatory node has booted, instead of one per node."),
      checkbox("Reset all nodes when a mandatory node is lost", m + "reset_all_nodes", false,
        "On: every node, the master included, is reset. Off: the master resets only that node."),
      checkbox("Stop all nodes when a mandatory node is lost", m + "stop_all_nodes", false,
        "On: every node, the master included, is stopped. Wins over reset all nodes."),
      field("Boot time (ms)", m + "boot_time_ms", "intstr", { placeholder: "no limit",
        hint: "Time allowed for all mandatory nodes to boot (0x1F89). Empty: no limit." }),
      field("Boot SDO timeout (ms)", m + "sdo_timeout_ms", "intstr", { placeholder: "1000",
        hint: "How long the master waits for each SDO answer while it boots and configures a node, 10-60000. " +
          "Raise it for a device that answers late. Empty: 1000." })),
    el("h3", null, "Heartbeat consumer"),
    el("div", { class: "grid" },
      checkbox("Master watches node heartbeats", m + "heartbeat_consumer", true,
        "Off: the master ignores node heartbeats (0x1016 stays empty)."),
      field("Heartbeat timeout factor", m + "heartbeat_multiplier", "text", { placeholder: "3",
        parse: (t) => (/^[0-9]+(\.[0-9]+)?$/.test(t) ? parseFloat(t) : t),
        hint: "A node's heartbeat times out after its period × this factor. Default: 3." })),
    el("h3", null, "Master identity (0x1018)"),
    el("div", { class: "grid" },
      field("Vendor ID", m + "vendor_id", "intstr", { placeholder: "dcfgen default", hint: "Decimal or 0x hex." }),
      field("Product code", m + "product_code", "intstr", { placeholder: "dcfgen default" }),
      field("Revision number", m + "revision_number", "intstr", { placeholder: "dcfgen default" }),
      field("Serial number", m + "serial_number", "intstr", { placeholder: "dcfgen default" })),
    el("h3", null, "Communication"),
    el("div", { class: "grid" },
      field("SYNC window (µs)", m + "sync_window_us", "intstr", { placeholder: "none",
        hint: "Synchronous window length (0x1007). Empty: none." }),
      field("SYNC counter overflow", m + "sync_counter_overflow", "intstr", { placeholder: "no counter",
        hint: "2 to 240 adds a counter to SYNC (0x1019), needed for a PDO's SYNC start. Empty: no counter." }),
      field("TIME COB-ID", m + "time_cob_id", "intstr", { placeholder: "0x100",
        hint: "0x1012. The COB-ID the master sends TIME on when the TIME period is set." }),
      timePeriodField(),
      field("EMCY inhibit time (µs)", m + "emcy_inhibit_time_us", "intstr", { placeholder: "none",
        hint: "A multiple of 100 (0x1015)." }),
      field("NMT inhibit time (µs)", m + "nmt_inhibit_time_us", "intstr", { placeholder: "none",
        hint: "Minimum gap between NMT commands, a multiple of 100 (0x102A)." }),
      errorBehaviorField("Error behavior", m + "error_behavior",
        "0x1029 as sub=value pairs, e.g. 1=0 (0 pre-operational, 1 no change, 2 stopped). Empty: none.")));
}


// The master's TIME producer: the time of day every period, on the COB-ID
// shown under the field. Empty: no TIME (nothing saved).
function timePeriodField() {
  const f = field("TIME period (ms)", "master.time_period_ms", "intstr", { placeholder: "no TIME",
    hint: "The master sends the runtime's time of day every this many ms, 100-3600000, and at once when the bus comes up. " +
      "Nodes that should use it need TIME COB-ID with bit 31 (0x80000000) set. Empty: no TIME." });
  f.insertBefore(el("span", { class: "hint", dataset: { online: "time-cob" } }), f.querySelector(".field-msg"));
  setTimeout(showTimeCob);
  return f;
}

function showTimeCob() {
  const span = document.querySelector("[data-online=time-cob]");
  if (!span) return;
  const c = num(getPath("master.time_cob_id"));
  const id = Number.isFinite(c) ? (c & 0x7FF) : 0x100;
  span.textContent = getPath("master.time_period_ms") === undefined ? "" : `Sent on COB-ID 0x${id.toString(16).toUpperCase().padStart(3, "0")}.`;
}

document.addEventListener("input", (ev) => {
  const path = ev.target && ev.target.dataset ? ev.target.dataset.path : null;
  if (path === "master.time_period_ms" || path === "master.time_cob_id") showTimeCob();
  if (path === "adapter.interface") renderTree();  // the tree shows the interface's name
});

// ---------------------------------------------------------------------------
// Slave networks (canopen-slave-device): OpenPLC as a node of a network
// another master runs. The network's `slave` object takes the place of its
// master and nodes; its EDS is picked or built here (canopen-slave-eds).

const isSlave = (net) => !!net && net.role === "slave";
const SLAVE_ID = 10;  // a new slave network's node ID
const SLAVE_DIAG = [
  ["state_location", "slave_state", "Own state", "%IB…",
    "The slave's NMT state: 0 not started, 4 stopped, 5 operational, 127 pre-operational. Empty: none."],
  ["comm_ok_location", "slave_comm_ok", "Communication OK", "%IX…",
    "TRUE while operational with no heartbeat consumer or life guarding error. Empty: none."],
  ["sync_count_location", "slave_sync_count", "SYNC count", "%IW…", "SYNCs received, wrapping at 65535. Empty: none."],
  ["emcy_code_location", "slave_emcy", "EMCY code", "%QW…",
    "Output: a change to a non-zero code sends one EMCY with it, a change to 0 the error reset. Empty: the program sends no EMCY."],
  ["error_register_location", "slave_errreg", "Error register", "%QB…",
    "Output: the 0x1001 bits sent with the EMCY. Empty: none."],
];
const BINDABLE = { rww: "input", rw: "input", ro: "output", rwr: "output" };

// The network's role: switching to slave drops the master settings and the
// nodes (asked first when there are any); back to master starts empty.
function roleField() {
  return el("fieldset", null, el("legend", null, "Role"),
    el("div", { class: "grid" }, choice("This network", "role", [
      { value: undefined, literal: "master", label: "Master", help: targetText("role_master") },
      { value: "slave", label: "Slave", help: "Another master runs this network; the plugin is one of its nodes, with an EDS for that master's tool." },
    ], { onChange: switchRole })));
}

async function switchRole(role) {
  const net = S.config;
  if ((role === "slave") === isSlave(net)) return;
  if (role === "slave") {
    const k = (net.nodes || []).length;
    const settings = Object.keys(net.master || {}).filter((key) => !["node_id", "sync_period_us"].includes(key)).length;
    if (k || settings) {
      const v = await modal(`Make ${netNamed(net, S.net)} a slave network? Its master settings` +
        (k ? ` and its ${k} node${k === 1 ? "" : "s"}` : "") + " are dropped. Their EDS files stay in the folder.",
        [["slave", "Make it a slave", true], ["cancel", "Cancel"]]);
      if (v !== "slave") { render(); return; }
    }
    delete net.master;
    delete net.nodes;
    net.role = "slave";
    net.slave = { node_id: SLAVE_ID, eds: "", objects: [] };
  } else {
    const s = net.slave || {};
    if (s.eds || (s.objects || []).length) {
      const v = await modal(`Make ${netNamed(net, S.net)} a master network again? The slave settings and ` +
        "bindings are dropped. The EDS file stays in the folder.", [["master", "Make it a master", true], ["cancel", "Cancel"]]);
      if (v !== "master") { render(); return; }
    }
    delete net.role;
    delete net.slave;
    net.master = newMaster();
    net.nodes = [];
  }
  changed(true);
}

// The description the slave's EDS was built from (the server keeps it next
// to the EDS as <name>.json), else a starting one.
function slaveDesc() {
  S.slaveDesc = S.slaveDesc || {};
  const s = S.config.slave || {};
  const key = `${S.net}|${s.eds || ""}`;
  if (!S.slaveDesc[key]) {
    const saved = (S.state.slave_descriptions || {})[s.eds];
    S.slaveDesc[key] = saved ? JSON.parse(JSON.stringify(saved)) :
      { device_name: "OpenPLC slave", vendor_id: 0, product_code: 1, heartbeat_ms: 1000, layout: "manufacturer", objects: [] };
  }
  return S.slaveDesc[key];
}

function slaveFieldsets() {
  const base = "slave";
  const s = S.config.slave || (S.config.slave = { eds: "", objects: [] });
  const eds = s.eds ? (S.state.eds || {})[s.eds] || null : null;
  const lss = s.node_id === null;
  const lssBox = el("input", { type: "checkbox", dataset: { path: base + ".lss" } });
  lssBox.checked = lss;
  lssBox.addEventListener("change", () => { setPath(base + ".node_id", lssBox.checked ? null : SLAVE_ID); render(); });
  const edsBox = edsField({ name: s.eds || "", product: edsProduct(s.eds), none: "None yet: build one below, or choose an EDS file",
    label: "the slave", buttonData: { path: base + ".eds" }, onChoose: chooseSlaveEds,
    extra: [el("button", { type: "button", class: "small", dataset: { exportEds: "1" }, onclick: exportSlaveEds, disabled: !s.eds,
      title: "The EDS the plugin runs, for import into the other master's configuration tool" }, "Export EDS")] });
  return [
    el("fieldset", null, el("legend", null, "Slave device"),
      el("div", { class: "grid" },
        lss ? el("label", null, "Node ID", el("input", { type: "text", disabled: true, value: "assigned by LSS", "aria-label": "Node ID" }),
          hint("The node starts without an ID and waits for the master's LSS to assign one."))
          : field("Node ID", base + ".node_id", "intstr", { hint: "Required, 1 to 127: the ID the other master expects." }),
        el("div", { class: "check-field" }, el("label", { class: "check" }, lssBox, " Node ID by LSS"),
          hint("On: no node ID in the config; an LSS master assigns it at start. Default: off.")),
        el("div", { class: "field span2", role: "group", "aria-label": "EDS" }, el("span", null, "EDS"), edsBox,
          hint("The slave's object dictionary. Build one below, or choose an EDS file."),
          el("span", { class: "field-msg", dataset: { for: base + ".eds" } })),
        choice("Inputs when the master is lost", base + ".inputs_on_loss", [
          { value: undefined, literal: "hold", label: "Hold", help: "Default. Inputs keep their last value while the node is not operational or the master's heartbeat is lost." },
          { value: "zero", label: "Zero", help: "Inputs read 0 while the node is not operational or the master's heartbeat is lost." },
        ]),
        choice("EDS lint (dcfgen)", base + ".eds_lint", [
          { value: undefined, literal: "communication", label: "Communication objects", help: "Default. The PLC stops only on lint findings in 0x1000-0x1FFF." },
          { value: "all", label: "Every object", help: "The PLC stops on any lint finding. An EDS built here always passes it." },
          { value: "off", label: "Off", help: "The PLC never stops on a lint finding." },
        ]))),
    slaveBuilder(),
    slaveObjects(eds),
    el("fieldset", null, el("legend", null, "Status and EMCY"),
      el("p", { class: "muted" }, "Optional locations: the slave's own state for the program, and an EMCY the program sends."),
      el("div", { class: "grid" }, SLAVE_DIAG.map(([key, direction, label, placeholder, help]) => {
        const path = base + "." + key;
        const btn = el("button", { type: "button", dataset: { suggest: direction },
          onclick: async () => {
            const r = await api("POST", "/api/place", { config: fileConfig(), network: S.net, direction });
            setPath(path, r.location);
            render();
          } }, "Suggest");
        return el("label", null, label, el("span", { class: "row" },
          field("", path, "text", { placeholder }).querySelector("input"), btn),
          hint(help), el("span", { class: "field-msg", dataset: { for: path } }), declNote(path));
      }))),
  ];
}

// The bound objects, from the EDS: direction from the access type, the PLC
// area to match, and a picker of the objects not bound yet.
function slaveObjects(eds) {
  const fs = el("fieldset", { dataset: { slaveObjects: "1" } }, el("legend", null, "Objects"));
  const s = S.config.slave;
  const objects = s.objects || [];
  if (!eds || !eds.objects) {
    fs.append(el("p", { class: "muted" }, eds && eds.error ? eds.error : "Build or pick the slave's EDS first."));
    return fs;
  }
  const rows = objects.map((o, j) => {
    const info = objectInfo(eds, o.index, o.subindex);
    const dir = info ? BINDABLE[info.access] : undefined;
    const path = `slave.objects[${j}]`;
    const suggest = el("button", { type: "button", dataset: { suggest: "slave_object" }, disabled: !info || !dir || !info.type,
      onclick: async () => {
        const r = await api("POST", "/api/place", { config: fileConfig(), network: S.net, direction: "slave_object",
          type: info.type, access: info.access });
        setPath(path + ".iec_location", r.location);
        render();
      } }, "Suggest");
    return el("tr", { dataset: { object: `${o.index}:${o.subindex ?? 0}` } },
      el("td", null, `${o.index}:${o.subindex ?? 0}`),
      el("td", null, info ? info.name : el("span", { class: "field-msg" }, "not in the EDS")),
      el("td", null, info ? info.type || "" : "",
        info ? hint(`${info.access}: ` + (dir === "input" ? "PLC input (%I)" : dir === "output" ? "PLC output (%Q)" : "cannot be bound")) : null),
      el("td", null, el("span", { class: "row" }, field("", path + ".iec_location", "text",
        { placeholder: dir === "output" ? "%Q…" : "%I…" }).querySelector("input"), suggest),
        el("span", { class: "field-msg", dataset: { for: path + ".iec_location" } }),
        el("span", { class: "field-msg", dataset: { for: path } }), declNote(path + ".iec_location")),
      el("td", null, field("", path + ".name", "text", { placeholder: info ? info.name : "" }).querySelector("input")),
      el("td", null, el("button", { type: "button", onclick: () => { objects.splice(j, 1); changed(true); } }, "Remove")));
  });
  const free = eds.objects.filter((o) => BINDABLE[o.access] && o.type && o.subindex !== undefined &&
    !(o.subindex === 0 && eds.objects.some((x) => x.index === o.index && x.subindex > 0)) &&
    !objects.some((b) => sameObject(b.index, b.subindex, o.index, o.subindex)) &&
    num(o.index) >= 0x2000);
  const pick = el("select", { "aria-label": "Object to bind" }, free.map((o, k) =>
    el("option", { value: k }, `${o.index}:${o.subindex} ${o.name} (${o.type}, ${o.access})`)));
  fs.append(el("p", { class: "muted" }, "Objects the master writes (AccessType rww or rw) are PLC inputs; objects the " +
      "program writes (ro or rwr) are PLC outputs the master reads. The name is optional and names the variable."),
    el("div", { class: "objects", dataset: { box: "slave_objects", boxLabel: "the bound objects" } }, el("table", { class: "slave-objects" },
      el("thead", null, el("tr", null, thCells(["Object", "EDS name", "Type and direction", targetText("location_column"), "Name", ""]))),
      el("tbody", null, rows.length ? rows : el("tr", null, el("td", { colspan: 6, class: "muted" }, "No objects yet. Bind an object of the slave's dictionary to a PLC location below, so the master can read or write it."))))),
    free.length ? el("div", { class: "toolbar" }, pick, el("button", { type: "button", dataset: { bind: "1" },
      onclick: async () => {
        const o = free[Number(pick.value)];
        const r = await api("POST", "/api/place", { config: fileConfig(), network: S.net, direction: "slave_object",
          type: o.type, access: o.access });
        s.objects = s.objects || [];
        s.objects.push({ index: o.index, subindex: o.subindex, iec_location: r.location });
        changed(true);
      } }, "Bind")) : null);
  return fs;
}

// The object list editor: name, type, direction, default and limits, the
// identity and the layout; Generate builds the EDS with slave-eds's generator.
function slaveBuilder() {
  const d = slaveDesc();
  d.objects = d.objects || [];
  const input = (obj, key, label, kind, opts) => {
    const i = el("input", { type: "text", spellcheck: "false", "aria-label": label, placeholder: (opts || {}).placeholder, dataset: { desc: key } });
    i.value = obj[key] === undefined || obj[key] === null ? "" : String(obj[key]);
    i.addEventListener("input", () => {
      const t = i.value.trim();
      if (t === "") delete obj[key];
      else obj[key] = kind === "num" && /^-?[0-9]+(\.[0-9]+)?$/.test(t) ? Number(t) : t;
    });
    return i;
  };
  const sel = (obj, key, label, values) => {
    const e = el("select", { "aria-label": label, dataset: { desc: key } }, values.map(([v, t]) => el("option", { value: v }, t)));
    e.value = obj[key] || values[0][0];
    e.addEventListener("change", () => { obj[key] = e.value; });
    return e;
  };
  const cia401 = d.layout === "cia401";
  const rows = d.objects.map((o, k) => el("tr", { dataset: { descObject: k } },
    el("td", null, input(o, "name", "Object name")),
    el("td", null, sel(o, "type", "Type", (cia401 ? ["UNSIGNED8", "INTEGER16"] : TYPES).map((t) => [t, t]))),
    el("td", null, sel(o, "direction", "Direction", [["from_master", "input, from master"], ["to_master", "output, to master"]])),
    el("td", null, input(o, "default", "Default", "num", { placeholder: "0" })),
    el("td", null, input(o, "low", "Low limit", "num")),
    el("td", null, input(o, "high", "High limit", "num")),
    el("td", null, el("button", { type: "button", onclick: () => { d.objects.splice(k, 1); render(); } }, "Remove"))));
  const g = S.model.top.gateway;
  const gatewayBox = el("input", { type: "checkbox", dataset: { desc: "gateway" } });
  gatewayBox.checked = !!(g && g.upper === netName(S.config));
  const layoutSel = sel(d, "layout", "Layout", [["manufacturer", "Manufacturer objects (0x2000/0x2100)"], ["cia401", "CiA 401 generic I/O"]]);
  layoutSel.addEventListener("change", () => render());
  // Open by itself while the slave has no EDS.
  S.advOpen = S.advOpen || {};
  if (!(S.config.slave || {}).eds && S.advOpen["slave-build"] === undefined) S.advOpen["slave-build"] = true;
  return advanced("slave-build", "Build the EDS", "slave", [],
    el("p", { class: "muted" }, "The objects of the slave's dictionary. Generate writes the EDS into the folder with the config " +
      "(on Save), with the same generator as canworks-deploy slave-eds, and offers to bind every object."),
    el("div", { class: "grid" },
      el("label", null, "Device name", input(d, "device_name", "Device name"), hint("Also names the exported EDS.")),
      el("label", null, "Vendor ID", input(d, "vendor_id", "Vendor ID", "num", { placeholder: "0" })),
      el("label", null, "Product code", input(d, "product_code", "Product code", "num", { placeholder: "0" })),
      el("label", null, "Revision number", input(d, "revision_number", "Revision number", "num", { placeholder: "from the content" }),
        hint("Empty: derived from the objects, so a changed dictionary gets a new revision.")),
      el("label", null, "Heartbeat (ms)", input(d, "heartbeat_ms", "Heartbeat", "num", { placeholder: "1000" })),
      el("label", { class: "span2" }, "Layout", layoutSel,
        hint(cia401 ? "Device type 401: digital I/O as UNSIGNED8 (0x6000/0x6200), analog as INTEGER16 (0x6401/0x6411)."
          : "From the master in 0x2000 and up, to the master in 0x2100 and up, one ARRAY per type."))),
    el("div", { class: "objects", dataset: { box: "slave_builder", boxLabel: "the object list" } }, el("table", { class: "slave-builder" },
      el("thead", null, el("tr", null, thCells(["Name", "Type", "Direction", "Default", "Low", "High", ""]))),
      el("tbody", null, rows))),
    el("div", { class: "toolbar" },
      el("button", { type: "button", dataset: { addDescObject: "1" }, onclick: () => {
        d.objects.push({ name: `value${d.objects.length + 1}`, type: cia401 ? "UNSIGNED8" : "UNSIGNED16", direction: "from_master" });
        render();
      } }, "Add object"),
      g ? el("label", { class: "check" }, gatewayBox, " With the gateway objects (routes, status, SDO bridge)") : null,
      el("div", { class: "spacer" }),
      el("button", { type: "button", class: "primary", dataset: { generate: "1" }, onclick: () => generateSlaveEds(gatewayBox.checked) }, "Generate EDS")));
}

async function generateSlaveEds(withGateway) {
  const d = slaveDesc();
  const s = S.config.slave;
  const body = { config: fileConfig(), network: S.net, description: d, gateway: withGateway };
  if (s.eds && (S.state.slave_descriptions || {})[s.eds]) body.name = s.eds;
  let r;
  try {
    r = await api("POST", "/api/slave_eds", body);
  } catch (e) {
    if (e.status === 409 && e.body.conflict) {
      const v = await modal(e.message + ". Replace it with the generated EDS?", [["cancel", "Cancel"], ["replace", "Replace", { danger: true }]]);
      if (v !== "replace") return;
      r = await api("POST", "/api/slave_eds", Object.assign(body, { replace: true }));
    } else {
      banner(e.message, true);
      return;
    }
  }
  S.state.eds = S.state.eds || {};
  S.state.eds[r.name] = r.summary;
  S.state.slave_descriptions = S.state.slave_descriptions || {};
  S.state.slave_descriptions[r.name] = JSON.parse(JSON.stringify(d));
  S.slaveDesc[`${S.net}|${r.name}`] = d;
  s.eds = r.name;
  const g = S.model.top.gateway;
  if (withGateway && g && Array.isArray(g.routes)) r.routes.forEach((place, j) => { if (g.routes[j]) g.routes[j].slave = place; });
  S.unsavedFiles = true;
  const what = `Generated ${r.name}: ${r.objects.length} object${r.objects.length === 1 ? "" : "s"}, revision number ` +
    `${hex8(r.revision_number)}.`;
  // Nothing to bind (an empty list, or only route objects): no question.
  const v = !r.bindings.length ? "keep" : await modal(what + ` Bind ${r.bindings.length === 1 ? "the object" : `all ${r.bindings.length} objects`} to the suggested locations` +
    ` (${r.bindings.map((b) => `${b.name} ${b.iec_location}`).join(", ")})?`,
    [["bind", "Bind all", true], ["keep", "Keep the bindings"]]);
  if (v === "bind") s.objects = r.bindings;
  banner(`Generated ${r.name}; it is written with the config on Save.`);
  changed(true);
}

// Choose EDS… on the slave page: the EDS dialog with the EDS files built for
// a slave first, imported with the slave's EDS lint (one-eds-picker).
async function chooseSlaveEds() {
  const s = S.config.slave;
  const lint = s.eds_lint;
  const a = await chooseEds({ title: "Choose the slave's EDS", current: s.eds, builtHere: true, lint });
  if (!a || !a.choice) return;
  const res = await edsIntoDraft(a.choice, lint);
  if (!res) return;
  S.config.slave.eds = res.name;
  if (res.lint) {  // imported now: kept with the draft, written on Save
    S.unsavedFiles = true;
    banner(importReport(res, { slave: true }), "info");
  }
  changed(true);
  edsNotesArrived(res);
}

// Export EDS: the exact file the plugin runs, named after its device name.
async function exportSlaveEds() {
  try {
    const r = await api("POST", "/api/export_eds", { config: fileConfig(), network: S.net });
    downloadBase64(r.data, r.name, r.content_type);
    banner(`Exported ${r.name}: import it into the other master's configuration tool.`);
  } catch (e) {
    banner(e.message, true);
  }
}

// ---------------------------------------------------------------------------
// Gateway (canopen-gateway): routes between a slave network and the field
// networks, status, EMCY forwarding, upper loss and the SDO bridge. Paths
// "gateway…" live at the top of the draft.

function renderGateway(view) {
  const top = S.model.top;
  const slaves = S.model.networks.filter(isSlave).map(netName).filter(Boolean);
  const masters = S.model.networks.filter((n) => !isSlave(n));
  view.append(el("h2", null, "Gateway"));
  if (!top.gateway && (!slaves.length || !masters.length)) {
    view.append(el("p", { class: "muted" }, "A gateway needs a slave network with a name (the upper network) and at least one " +
      "master network (the field). Add a network and set its role to slave."));
    return;
  }
  const on = el("input", { type: "checkbox", dataset: { path: "gateway" } });
  on.checked = !!top.gateway;
  on.addEventListener("change", async () => {
    if (on.checked) top.gateway = { upper: slaves[0] || "", routes: [] };
    else {
      const k = ((top.gateway || {}).routes || []).length;
      if (k && await modal(`Remove the gateway and its ${k} route${k === 1 ? "" : "s"}?`, [["cancel", "Keep the gateway"], ["remove", "Remove the gateway", { danger: true }]]) !== "remove") { render(); return; }
      delete top.gateway;
    }
    changed(true);
  });
  view.append(el("fieldset", null, el("legend", null, "Gateway"),
    el("div", { class: "check-field" }, el("label", { class: "check" }, on, " OpenPLC copies values between the upper network and the field"),
      hint("The plugin moves routed values at bus speed, without the PLC program. Default: off."))));
  const g = top.gateway;
  if (!g) return;
  const upperSlave = (S.model.networks.find((n) => isSlave(n) && netName(n) === g.upper) || {}).slave || {};
  const upperEds = upperSlave.eds ? (S.state.eds || {})[upperSlave.eds] : null;
  view.append(
    el("fieldset", null, el("legend", null, "Networks"),
      el("div", { class: "grid" }, choice("Upper network", "gateway.upper", slaves.map((n) => ({ value: n, label: n,
        help: "The slave network the upper master runs." }))),
      el("p", { class: "hint wide" }, "Build the upper network's EDS with \"With the gateway objects\" ticked, so it has an object per route, " +
        "the status ARRAYs and the bridge record; generating again updates the routes' slave objects."))),
    gatewayRoutes(g, masters, upperEds),
    el("fieldset", null, el("legend", null, "Options"),
      el("div", { class: "grid" },
        gatewayCheck("Field node status", "gateway.status", !!g.status, (v) => { if (v) g.status = {}; else delete g.status; },
          "Each field node's NMT state at 0x5E00 + k and its operational bit at 0x5E10 + k, for master network k (at most 4)."),
        g.status ? field("Status index", "gateway.status.index", "text", { placeholder: "0x5E00" }) : null,
        checkbox("Forward field EMCYs", "gateway.emcy_forward", false,
          "A field node's EMCY goes out as the gateway's EMCY, with the network and node in the manufacturer bytes."),
        choice("When the upper master is lost", "gateway.on_upper_loss", [
          { value: undefined, literal: "hold", label: "Hold", help: "Default. Routed field outputs keep their last values." },
          { value: "zero", label: "Zero", help: "Routed field outputs are set to 0." },
          { value: "stop_nodes", label: "Stop the field nodes", help: "Field nodes that receive routes get NMT stop, and start again when the upper master starts the gateway." },
        ]),
        checkbox("SDO bridge", "gateway.sdo_bridge", false,
          "A record the upper master uses to read objects of up to 4 bytes on a field node."),
        g.sdo_bridge ? field("Bridge index", "gateway.sdo_bridge_index", "text", { placeholder: "0x5F00" }) : null,
        g.sdo_bridge ? checkbox("Bridge may write", "gateway.sdo_bridge_write", false, "On: the upper master may also write field node objects.") : null)));
}

function gatewayCheck(label, path, value, set, help) {
  const input = el("input", { type: "checkbox", dataset: { path } });
  input.checked = value;
  input.addEventListener("change", () => { set(input.checked); changed(true); });
  return el("div", { class: "check-field" }, el("label", { class: "check" }, input, " " + label), hint(help + " Default: off."));
}

// The PDO entries of a field node a route can use: TPDO entries go up,
// RPDO entries come down.
function fieldEntries(node) {
  const out = [];
  for (const [key, dir] of [["tx_pdos", "up"], ["rx_pdos", "down"]]) {
    for (const [j, p] of (node[key] || []).entries()) {
      for (const e of p.entries || []) {
        out.push({ index: e.index, subindex: e.subindex ?? 0, type: e.type, dir,
          label: `${key === "tx_pdos" ? "TPDO" : "RPDO"} ${p.number ?? j + 1} ${e.index}:${e.subindex ?? 0} ${e.type || ""}` });
      }
    }
  }
  return out;
}

function gatewayRoutes(g, masters, upperEds) {
  g.routes = g.routes || [];
  const slaveObjs = upperEds && upperEds.objects ? upperEds.objects.filter((o) => BINDABLE[o.access] && o.type && num(o.index) >= 0x2000) : [];
  const rows = g.routes.map((rt, j) => {
    const path = `gateway.routes[${j}]`;
    const who = `route ${rt.name || j + 1}`;
    rt.slave = rt.slave || {};
    rt.field = rt.field || {};
    const objSel = el("select", { dataset: { path: path + ".slave" }, "aria-label": `Slave object of ${who}` },
      el("option", { value: "" }, "(pick)"),
      slaveObjs.map((o, k) => el("option", { value: k }, `${o.index}:${o.subindex} ${o.name} (${o.access})`)));
    const cur = slaveObjs.findIndex((o) => sameObject(o.index, o.subindex, rt.slave.index, rt.slave.subindex));
    if (cur < 0 && rt.slave.index !== undefined) objSel.prepend(el("option", { value: "keep" }, `${rt.slave.index}:${rt.slave.subindex ?? 0}`));
    objSel.value = cur >= 0 ? String(cur) : rt.slave.index !== undefined ? "keep" : "";
    objSel.addEventListener("change", () => {
      if (objSel.value === "keep") return;
      const o = slaveObjs[Number(objSel.value)];
      rt.slave = o ? { index: o.index, subindex: o.subindex } : {};
      changed();
    });
    const netSel = el("select", { dataset: { path: path + ".field.network" }, "aria-label": `Field network of ${who}` },
      el("option", { value: "" }, "(pick)"), masters.map((n) => el("option", { value: netName(n) }, netName(n))));
    netSel.value = rt.field.network || "";
    netSel.addEventListener("change", () => { rt.field = { network: netSel.value }; changed(true); });
    const net = masters.find((n) => netName(n) === rt.field.network);
    const nodes = net ? net.nodes || [] : [];
    const nodeSel = el("select", { dataset: { path: path + ".field.node" }, "aria-label": `Field node of ${who}` },
      el("option", { value: "" }, "(pick)"), nodes.map((n) => el("option", { value: n.node_id }, `${n.node_id} ${n.name || ""}`)));
    nodeSel.value = rt.field.node === undefined ? "" : String(rt.field.node);
    nodeSel.addEventListener("change", () => {
      rt.field = { network: rt.field.network, node: nodeSel.value === "" ? undefined : Number(nodeSel.value) };
      changed(true);
    });
    const node = nodes.find((n) => num(n.node_id) === num(rt.field.node));
    const entries = node ? fieldEntries(node) : [];
    const entrySel = el("select", { dataset: { path: path + ".field" }, "aria-label": `Field PDO entry of ${who}` },
      el("option", { value: "" }, "(pick)"), entries.map((e, k) => el("option", { value: k }, e.label)));
    const ce = entries.findIndex((e) => sameObject(e.index, e.subindex, rt.field.index, rt.field.subindex));
    entrySel.value = ce >= 0 ? String(ce) : "";
    entrySel.addEventListener("change", () => {
      const e = entries[Number(entrySel.value)];
      Object.assign(rt.field, e ? { index: e.index, subindex: e.subindex } : { index: undefined, subindex: undefined });
      changed(true);
    });
    const e = ce >= 0 ? entries[ce] : null;
    // The field end in one cell, the PDO entry and its direction under
    // the network and node, so the table fits next to Problems.
    return el("tr", { dataset: { route: j } },
      el("td", null, field(`Name of route ${j + 1}`, path + ".name", "text", { placeholder: `route${j + 1}` }).querySelector("input")),
      el("td", null, objSel),
      el("td", null, el("span", { class: "row" }, netSel, nodeSel), entrySel,
        e ? hint(e.dir === "up" ? "up: node to upper master" : "down: upper master to node") : null),
      el("td", null, el("button", { type: "button", "aria-label": `Remove ${who}`, onclick: () => { g.routes.splice(j, 1); changed(true); } }, "Remove"),
        el("span", { class: "field-msg", dataset: { for: path } })));
  });
  return el("fieldset", null, el("legend", null, "Routes"),
    upperEds ? null : notice("warning", "Build or pick the upper network's EDS to pick slave objects.", { live: false }),
    el("p", { class: "muted" }, "Each route copies one value: a field TPDO entry up to a slave object the upper master reads (ro), " +
      "or a slave object the upper master writes (rww) down to a field RPDO entry, of the same type. An RPDO entry a route writes " +
      "needs no PLC location: one writer per object."),
    el("div", { class: "objects", dataset: { box: "routes", boxLabel: "the routes" } }, el("table", { class: "routes" },
      el("thead", null, el("tr", null, thCells(["Name", "Slave object", "Field network, node and PDO entry", ""]))),
      el("tbody", null, rows.length ? rows : el("tr", null, el("td", { colspan: 4, class: "muted" }, "No routes yet. A route passes a slave object to a node's PDO entry on a field network; add one with Add route."))))),
    el("div", { class: "toolbar" }, el("button", { type: "button", dataset: { addRoute: "1" },
      onclick: () => { g.routes.push({ slave: {}, field: {} }); changed(true); } }, "Add route")));
}

function edsFor(n) { return (S.state.eds || {})[n.eds] || null; }

function objectInfo(eds, index, sub) {
  if (!eds || !eds.objects) return null;
  return eds.objects.find((o) => sameObject(o.index, o.subindex, index, sub)) || null;
}

function declaredAs(path) { return S.check && S.check.declared ? S.check.declared[`${S.net}|${path}`] : null; }

// A section of the SDOs tab (startup SDO writes, SDO variables), with its
// count and its add action in the summary. Open, as the tab holds nothing
// else; the user's own open or close wins for the open node.
function collapsible(key, i, label, count, body, summaryExtra) {
  const k = `node${i}.${key}`;
  const open = S.sectionOpen[k] !== undefined ? S.sectionOpen[k] : true;
  const d = el("details", { class: "section", open: open || null, dataset: { section: key } },
    el("summary", null, label, el("span", { class: "muted" }, count ? `${count} ${count === 1 ? "entry" : "entries"}` : "none")),
    body);
  d.addEventListener("toggle", () => { S.sectionOpen[k] = d.open; });
  if (!summaryExtra) return d;
  // The "Add…" button shows on the summary line but lives outside the
  // details: not a control nested in a control, and visible while folded.
  return el("div", { class: "section-wrap" }, d, el("div", { class: "section-tools" }, summaryExtra));
}

// The node as a CiA 402 axis for the editor's PLCopen motion blocks: the
// `axis` object (left out when off) with its scaling, and "Map CiA 402
// objects" (/api/map_cia402), which puts the standard objects into PDOs.
function axisFields(i, eds) {
  const base = `nodes[${i}]`;
  const n = S.config.nodes[i];
  const on = !!n.axis && typeof n.axis === "object";
  // Only a drive: the EDS has the controlword and statusword. An axis set
  // already can still be switched off.
  const drive = !!(objectInfo(eds, "0x6040", 0) && objectInfo(eds, "0x6041", 0));
  const why = drive || on ? null : "The EDS has no controlword (0x6040) and statusword (0x6041): this device is not a CiA 402 drive.";
  const box = el("input", { type: "checkbox", disabled: !!why, title: why, dataset: { path: base + ".axis" } });
  box.checked = on;
  box.addEventListener("change", () => { setPath(base + ".axis", box.checked ? {} : undefined); render(); });
  // The section's messages (profile, status bit, the mapping's result) under its legend.
  const slot = noticeSlot({ dataset: { axisNotices: "" } });
  const fs = el("fieldset", { dataset: { axis: base } }, el("legend", null, "CiA 402 axis"), slot,
    el("div", { class: "check-field" },
      el("label", { class: "check" + (why ? " muted" : "") }, box, " Use as a CiA 402 axis"),
      why ? el("p", { class: "muted", dataset: { axisNoDrive: "" } }, why) : null,
      hint("The generated program declares an axis (AXIS_REF_SM3) for this node and calls the editor's CiA 402 drive bridge first in every scan, so MC_Power, MC_MoveAbsolute, MC_MoveVelocity and the other motion blocks drive it. Default: off."),
      el("span", { class: "field-msg", dataset: { for: base + ".axis" } })));
  if (!on) return fs;
  const dt = objectInfo(eds, "0x1000", 0);
  const value = dt ? num(dt.default) : NaN;
  if (eds && !eds.error && !(Number.isFinite(value) && (value & 0xFFFF) === 402))
    slot.append(notice("warning", "The EDS device type (0x1000) does not say device profile 402. Check that this device is a CiA 402 drive.",
      { live: false, dataset: { axisProfile: "" } }));
  if (!n.status_location)
    slot.append(notice("error", "An axis needs the status bit (under Supervision): the axis goes into error stop when the drive is lost.",
      { live: false, dataset: { axisStatus: "" } }));
  fs.append(el("div", { class: "grid" },
    field("Scale numerator", base + ".axis.scale_numerator", "int", { placeholder: "1",
      hint: "Drive increments for 'denominator' units of the program (10: a move of 25 units is 250 increments). Empty: 1." }),
    field("Scale denominator", base + ".axis.scale_denominator", "intstr", { placeholder: "1",
      hint: "Program units the numerator's increments stand for. Empty: 1." }),
    field("Scale factor", base + ".axis.scale_factor", "text", { placeholder: "1.0",
      parse: (t) => (/^-?[0-9]*\.?[0-9]+(e-?[0-9]+)?$/i.test(t) ? Number(t) : t), hint: "The motion library's extra scale factor on that ratio. Empty: 1.0." })));
  fs.append(cyclicFields(base, n));
  fs.append(el("div", { class: "toolbar" },
    el("button", { type: "button", dataset: { mapCia402: base }, disabled: !eds || !!eds.error, onclick: async () => {
      const r = await api("POST", "/api/map_cia402", { config: fileConfig(), network: S.net, node: i });
      S.config.nodes[i] = r.node;
      S.axisResult = { node: i, mapped: r.mapped, missing: r.missing, changes: r.changes || [] };
      changed(true);
    } }, "Map CiA 402 objects"),
    hint(n.axis.cyclic === true
      ? "Puts the drive's objects that are not mapped yet into its PDOs for cyclic use: controlword, modes and target position in one RPDO, the other set-points in the next, statusword, modes display and actual position in one TPDO, with transmission type 1 (every SYNC)."
      : "Puts the drive's controlword, statusword, modes, positions, velocities and torques that are not mapped yet into its PDOs, with suggested locations, as the drive's own default mapping has them where it can.")));
  // Map CiA 402 objects' result: a bar at the top of the section.
  const last = S.axisResult && S.axisResult.node === i ? S.axisResult : null;
  if (last) {
    const lines = [];
    lines.push(el("p", null, last.mapped.length
      ? "Mapped: " + last.mapped.map((m) => m.index ? `${m.index} ${m.name} (${m.pdo}, ${m.location})` : `${m.name} ${m.location}`).join("; ") + "."
      : "Nothing new to map."));
    if (last.changes && last.changes.length)
      lines.push(el("p", { dataset: { axisChanges: "" } }, "Transmission type 1 (every SYNC) for the cyclic axis: " +
        last.changes.map((c) => `${c.pdo} (was ${c.was === null || c.was === undefined ? "not set" : c.was})`).join(", ") + "."));
    if (last.missing.length) lines.push(el("ul", null, ...last.missing.map((m) => el("li", null, `${m.index} ${m.name}: ${m.reason}`))));
    slot.append(notice(last.missing.length ? "warning" : last.mapped.length ? "done" : "info", lines, { dataset: { axisResult: "" } }));
    slot.replaceChildren(...byKind([...slot.children]));
  }
  return fs;
}

// Cyclic synchronous modes (CSP/CSV/CST with the CO402_Cyclic* blocks):
// `axis.cyclic` and `axis.interpolation_period_us`. A cyclic axis needs one
// SYNC every PLC cycle; the button switches this network to it.
function cyclicFields(base, n) {
  const cyclic = n.axis.cyclic === true;
  const box = el("input", { type: "checkbox", dataset: { path: base + ".axis.cyclic" } });
  box.checked = cyclic;
  box.addEventListener("change", () => {
    setPath(base + ".axis.cyclic", box.checked ? true : undefined);
    if (!box.checked) setPath(base + ".axis.interpolation_period_us", undefined);
    render();
  });
  const wrap = el("div", { dataset: { axisCyclic: base } },
    el("div", { class: "check-field" },
      el("label", { class: "check" }, box, " Cyclic synchronous"),
      hint("The program sends a set-point every cycle (CSP, CSV, CST) with the CO402_Cyclic* blocks of the canworks library; the drive interpolates between them. Needs SYNC from the PLC cycle and synchronous PDOs. Default: off."),
      el("span", { class: "field-msg", dataset: { for: base + ".axis.cyclic" } })));
  if (!cyclic) return wrap;
  const m = S.config.master || {};
  const cycles = num(m.sync_cycles);
  if (m.sync_source !== "plc_cycle" || (Number.isFinite(cycles) && cycles !== 1)) {
    // The check's error shows under the switch; this is its fix.
    wrap.append(el("div", { class: "toolbar", dataset: { cyclicSync: "" } },
      el("button", { type: "button", dataset: { cyclicFix: "" }, onclick: () => {
        const mm = S.config.master || (S.config.master = {});
        mm.sync_source = "plc_cycle";
        delete mm.sync_period_us;
        delete mm.sync_cycles;
        changed(true);
      } }, "Use SYNC from the PLC cycle"),
      hint("Sets this network's SYNC source to the PLC cycle, one SYNC every cycle (Bus settings).")));
  }
  wrap.append(el("div", { class: "grid" },
    field("Interpolation period (us)", base + ".axis.interpolation_period_us", "int", { placeholder: "the PLC cycle",
      hint: "Written to the drive's 0x60C2 at boot. Empty: the runtime's cycle time, which is right when the task interval is the base tick." })));
  return wrap;
}

// emcy_cob_id: Device (the default, saved as no field), EDS, or a COB-ID
// typed in hex or decimal. The Check gives the plugin's messages for a
// COB-ID it does not take.
const EMCY_COB_HELP = {
  device: "Read from the node's 0x1014 after each boot; the master listens on the COB-ID the device uses.",
  eds: "The EDS default of 0x1014 (0x80 + node ID without one); nothing is read from the device.",
  number: "This COB-ID, hex (0xC5) or decimal; nothing is read from the device. Not a restricted CAN-ID, nor one the network already uses.",
};
function emcyCobField(i) {
  const path = `nodes[${i}].emcy_cob_id`;
  const v = getPath(path);
  const mode = v === undefined || v === "device" ? "device" : v === "eds" ? "eds" : "number";
  const sel = el("select", { "aria-label": "EMCY COB-ID", dataset: { emcyCob: "mode" } },
    el("option", { value: "device" }, "Device"), el("option", { value: "eds" }, "EDS"), el("option", { value: "number" }, "COB-ID"));
  sel.value = mode;
  const input = el("input", { type: "text", spellcheck: "false", class: "index", placeholder: "0xC5", "aria-label": "EMCY COB-ID number",
    dataset: { emcyCob: "number" } });
  input.value = mode === "number" ? String(v) : "";
  const help = el("span", { class: "hint" });
  const show = () => { help.textContent = EMCY_COB_HELP[sel.value]; input.hidden = sel.value !== "number"; };
  const save = () => {
    show();
    if (sel.value !== "number") { setPath(path, sel.value === "eds" ? "eds" : undefined); return; }
    const t = input.value.trim();
    setPath(path, t === "" ? undefined : /^[0-9]+$/.test(t) ? parseInt(t, 10) : t);
  };
  show();
  sel.addEventListener("change", () => { save(); if (sel.value === "number") input.focus(); });
  input.addEventListener("input", save);
  return el("label", null, "EMCY COB-ID", el("span", { class: "row" }, sel, input), help,
    el("span", { class: "field-msg", dataset: { for: path } }));
}

function nodeAdvanced(i, eds) {
  const base = `nodes[${i}]`;
  const n = S.config.nodes[i];
  const keys = ["mandatory", "boot", "reset_communication", "revision_number", "serial_number", "lss", "heartbeat_consumer",
    "retry_factor", "time_cob_id", "error_behavior", "restore_configuration", "config_check", "store_configuration"];
  const dflt = (index, sub, fmt) => {
    const v = edsDefault(eds, index, sub);
    return v === null ? "EDS default" : `EDS default (${fmt ? fmt(v) : v})`;
  };
  const hex8 = (v) => "0x" + v.toString(16).toUpperCase().padStart(8, "0");
  const ltf = num(n.life_time_factor);
  return advanced("node" + i, "Advanced node settings", base, keys,
    el("p", { class: "muted" }, "Node options canworks writes into the node's DCF. Empty node-side fields write nothing, so the node keeps its EDS values."),
    el("h3", null, "Boot"),
    el("div", { class: "grid" },
      checkbox("Mandatory", base + ".mandatory", false,
        "On: the master holds the whole network pre-operational (no PDOs for any node) until this node boots."),
      checkbox("Boot and configure", base + ".boot", true,
        "Off: the master neither configures nor starts the node; it only watches it."),
      resetCommField(i),
      field("Guarding retries", base + ".retry_factor", "intstr", { placeholder: ltf > 0 ? String(ltf) : "0",
        hint: "Node guarding retries (0x1F81). Default: the life time factor." })),
    el("h3", null, "Identity check"),
    el("div", { class: "grid" },
      field("Revision number", base + ".revision_number", "intstr", { placeholder: "not checked",
        hint: "Expected 0x1018 sub 3; 0 or empty: not checked. Vendor ID and product code always come from the EDS." }),
      field("Serial number", base + ".serial_number", "intstr", { placeholder: lssAssign(i) ? "needed for LSS" : "not checked",
        hint: "Expected 0x1018 sub 4 (pins one physical device). Empty: not checked." + (lssAssign(i) ? " Needed for LSS assignment." : "") })),
    el("h3", null, "Node ID by serial number (LSS)"),
    el("div", { class: "grid" }, ...lssFields(i, eds)),
    el("h3", null, "Node objects"),
    el("div", { class: "grid" },
      heartbeatConsumerField(i, eds),
      field("TIME COB-ID", base + ".time_cob_id", "intstr", { placeholder: dflt(0x1012, 0, hex8),
        hint: "0x1012. Bit 31 (0x80000000) set makes the node consume TIME." }),
      field("Restore configuration", base + ".restore_configuration", "intstr", { placeholder: "none",
        hint: "Sub-index of 0x1011 the master restores before configuring (1 all, 2 communication, 3 application). Empty: none." }),
      errorBehaviorField("Error behavior", base + ".error_behavior",
        "0x1029 as sub=value pairs, e.g. 1=0 (0 pre-operational, 1 no change, 2 stopped). Empty: EDS default.")),
    el("h3", null, "Configuration check"),
    el("div", { class: "grid" }, configCheckField(i, eds), storeConfigurationField(i, eds)));
}

// heartbeat_consumer: only for a node whose EDS has a writable 0x1016.
function heartbeatConsumerField(i, eds) {
  const path = `nodes[${i}].heartbeat_consumer`;
  const f = choice("Watches the master heartbeat", path, [
    { value: undefined, label: "EDS default", help: "Nothing is written: the node keeps its 0x1016 entries from the EDS." },
    { value: true, label: "On", help: "The node watches the master's heartbeat (needs a master heartbeat)." },
    { value: false, label: "Off", help: "The node's entry for the master is cleared." },
  ]);
  if (edsHasHeartbeatConsumer(eds)) return f;
  const set = getPath(path) !== undefined;
  const why = "The EDS has no consumer heartbeat time (0x1016), so the device cannot watch the master's heartbeat.";
  const sel = f.querySelector("select");
  if (!set) Icons.disable(sel, why);
  f.querySelector(".hint").replaceWith(edsLimit(why, set,
    { label: "Remove the heartbeat setting", dataset: { heartbeatRemove: "" }, run: () => setPath(path, undefined) },
    { heartbeatLimit: "" }));
  return f;
}

const lssAssign = (i) => getPath(`nodes[${i}].lss.assign`) === true;

// reset_communication: on (left out) cannot be turned off while LSS assigns
// the node ID, which becomes active only on a communication reset.
function resetCommField(i) {
  const path = `nodes[${i}].reset_communication`;
  const f = checkbox("Reset communication before boot", path, true,
    "Off: the master skips the reset communication command.");
  if (lssAssign(i)) {
    const input = f.querySelector("input");
    input.disabled = getPath(path) !== false;
    if (input.disabled) f.append(hint("Stays on while LSS assigns the node ID: the new ID becomes active only on a communication reset."));
  }
  f.append(el("span", { class: "field-msg", dataset: { for: path } }));
  return f;
}

// lss.assign and lss.store: unticked boxes and an empty lss object are left
// out; store needs assign.
function lssFields(i, eds) {
  const base = `nodes[${i}]`;
  const n = S.config.nodes[i];
  const set = (key, on) => {
    const lss = Object.assign({}, getPath(base + ".lss") || {});
    if (on) lss[key] = true; else delete lss[key];
    if (key === "assign" && !on) delete lss.store;
    setPath(base + ".lss", Object.keys(lss).length ? lss : undefined);
    render();
  };
  const assign = el("input", { type: "checkbox", dataset: { path: base + ".lss.assign" } });
  assign.checked = lssAssign(i);
  assign.addEventListener("change", () => {
    if (assign.checked && getPath(base + ".reset_communication") === false) setPath(base + ".reset_communication", undefined);
    set("assign", assign.checked);
  });
  const store = el("input", { type: "checkbox", dataset: { path: base + ".lss.store" } });
  store.checked = getPath(base + ".lss.store") === true;
  Icons.setDisabled(store, !assign.checked && !store.checked && "Needs \"Assign node ID by serial number\".");
  store.addEventListener("change", () => set("store", store.checked));
  // No LSS on a node whose EDS has none: the boxes stay off (a ticked one can
  // still be unticked), and an lss object left in the file can be removed.
  const dev = eds && eds.device;
  const noLss = !!dev && !dev.lss_supported;
  if (noLss) {
    Icons.setDisabled(assign, !assign.checked && "This device's EDS has no LSS.");
    Icons.setDisabled(store, !store.checked && "This device's EDS has no LSS.");
  }
  const has = getPath(base + ".lss") !== undefined;
  const warn = noLss
    ? edsLimit("This device's EDS has no LSS (LSS_Supported=1 missing), so LSS cannot be used for this node.", has,
      { label: "Remove the LSS settings", dataset: { lssRemove: "" }, run: () => setPath(base + ".lss", undefined) },
      { lssWarning: "" })
    : null;
  return [
    el("div", { class: "check-field" },
      el("label", { class: "check" }, assign, " Assign node ID by serial number (LSS)"),
      hint(assign.checked
        ? `The master gives the device with this serial number node ID ${n.node_id ?? "?"} at every start, before the network boots. Needs the serial number above.`
        : "The master finds the device by vendor ID, product code (from the EDS) and serial number, and gives it this node ID at every start. For devices without DIP switches. Default: off."),
      warn,
      el("span", { class: "field-msg", dataset: { for: base + ".lss.assign" } })),
    el("div", { class: "check-field" },
      el("label", { class: "check" }, store, " Store node ID in the device"),
      hint("Saves the node ID in the device's memory with LSS, only when the master had to change it. Without it the device needs the master after every power cycle. Default: off."),
      el("span", { class: "field-msg", dataset: { for: base + ".lss.store" } })),
  ];
}

// config_check: a checkbox that is left out of the config when off, disabled
// (unless already on, so it can be turned off) when the EDS cannot take the
// stamp in 0x1020 sub 1 and 2.
function configCheckField(i, eds) {
  const base = `nodes[${i}]`;
  const on = getPath(base + ".config_check") === true;
  const subs = [1, 2].map((s) => objectInfo(eds, "0x1020", s));
  let why = null;
  if (subs.every((o) => !o)) why = "The EDS has no 0x1020 (configuration date and time), so the device cannot keep the stamp.";
  else if (subs.some((o) => !o || !o.writable)) why = "The EDS has no writable 0x1020 sub 1 and sub 2, so the device cannot keep the stamp.";
  const input = el("input", { type: "checkbox", dataset: { path: base + ".config_check" } });
  input.checked = on;
  Icons.setDisabled(input, !on && why);
  input.addEventListener("change", () => {
    if (!input.checked) setPath(base + ".store_configuration", undefined);
    setPath(base + ".config_check", input.checked ? true : undefined);
    render();
  });
  return el("div", { class: "check-field" },
    el("label", { class: "check" }, input, " Skip download when unchanged (0x1020)"),
    why ? edsLimit(why, on) : hint("After a download the master writes a stamp of this node's configuration to 0x1020, and at later boots " +
      "skips the download when the node still has it. Default: off."),
    el("span", { class: "field-msg", dataset: { for: base + ".config_check" } }));
}

// store_configuration: "No" or a writable 0x1010 sub-index of the EDS; it
// needs config_check, so the device saves only after a download.
function storeConfigurationField(i, eds) {
  const base = `nodes[${i}]`;
  const subs = eds && eds.objects ? eds.objects.filter((o) => num(o.index) === 0x1010 && num(o.subindex) >= 1 &&
    num(o.subindex) <= 127 && o.writable) : [];
  const choices = [{ value: undefined, label: "No",
    help: "The master never writes 0x1010; the device keeps what it was sent until it is switched off." }]
    .concat(subs.map((o) => ({ value: num(o.subindex), label: `Sub ${num(o.subindex)}: ${o.name}`,
      help: `After each download the master writes "save" to 0x1010 sub ${num(o.subindex)}. Boots that skip ` +
        "the download save nothing, so the device's memory is written only when the configuration changes." })));
  const f = choice("Save configuration on the device (0x1010)", base + ".store_configuration", choices);
  const set = getPath(base + ".store_configuration") !== undefined;
  let why = null;
  if (!subs.length) why = "The EDS has no writable 0x1010 sub-index (store parameters).";
  else if (getPath(base + ".config_check") !== true) why = "Needs \"Skip download when unchanged\", so the device saves only after a download.";
  if (why && !set) Icons.disable(f.querySelector("select"), why);
  if (why) f.querySelector(".hint").replaceWith(subs.length ? hint(why) : edsLimit(why, set));
  return f;
}

const SUPERVISION = [
  { value: "none", label: "EDS default", help: "Nothing is written to the slave: it keeps the heartbeat its EDS gives (object 0x1017), and the master watches that heartbeat. An EDS default of 0 is a problem the runtime refuses, since a node that drops off the bus would not be noticed: pick Heartbeat and set a period (or 0 to accept that)." },
  { value: "heartbeat", label: "Heartbeat (recommended)",
    help: "The slave sends a heartbeat every period. The master marks it lost when none arrives within the timeout." },
  { value: "guarding", label: "Node guarding",
    help: "Older method: the master polls the slave every guard time and marks it lost after guard time × life time factor without an answer." },
];

function supervisionMode(i) {
  const n = S.config.nodes[i];
  if (n.guard_time_ms !== undefined || n.life_time_factor !== undefined) return "guarding";
  if (n.heartbeat_ms !== undefined || n.heartbeat_timeout_ms !== undefined) return "heartbeat";
  return (S.supervision || {})[i] || "none";
}

function supervisionFields(i) {
  const base = `nodes[${i}]`;
  const n = S.config.nodes[i];
  const mode = supervisionMode(i);
  const keys = { heartbeat: ["heartbeat_ms", "heartbeat_timeout_ms"], guarding: ["guard_time_ms", "life_time_factor"] };
  const out = [choice("Method", base + ".supervision", SUPERVISION, {
    current: mode, noPath: true, dataset: { supervision: String(i) },
    onChange: (v) => {
      S.supervision = S.supervision || {};
      S.supervision[i] = v;
      for (const [m, ks] of Object.entries(keys)) if (m !== v) for (const k of ks) delete n[k];
      changed(true);
    },
  })];
  const edsHb = edsDefault(edsFor(n), 0x1017, 0);
  if (mode === "heartbeat") {
    const dflt = () => {
      const hb = num(n.heartbeat_ms) > 0 ? num(n.heartbeat_ms) : edsHb;
      return hb > 0 ? String(Math.min(hb * 3, 65535)) : "3 × period";
    };
    const period = field("Heartbeat period (ms)", base + ".heartbeat_ms", "intstr", {
      placeholder: edsHb > 0 ? String(edsHb) : "e.g. 100",
      hint: "How often the slave sends its heartbeat. Empty: the EDS default (" +
        (edsHb === null ? "unknown" : edsHb > 0 ? edsHb + " ms" : "off") + "); 0 switches it off." });
    const timeout = field("Heartbeat timeout (ms)", base + ".heartbeat_timeout_ms", "intstr",
      { placeholder: dflt(), hint: "Default: 3 × the period. Not shorter than the period." });
    period.querySelector("input").addEventListener("input", () => { timeout.querySelector("input").placeholder = dflt(); });
    out.push(period, timeout);
  } else if (mode === "guarding") {
    out.push(field("Guard time (ms)", base + ".guard_time_ms", "intstr", { placeholder: "e.g. 100",
      hint: "How often the master polls the slave." }),
    field("Life time factor", base + ".life_time_factor", "intstr", { placeholder: "e.g. 3",
      hint: "Missed polls before the node counts as lost." }));
  }
  // A node the master would never see lost (no heartbeat_ms, no guarding, EDS
  // heartbeat 0) is refused on its heartbeat_ms: shown under Method.
  if (mode !== "heartbeat") out.push(el("span", { class: "field-msg wide", dataset: { for: base + ".heartbeat_ms" } }));
  if (S.addedSupervision && S.addedSupervision.has(`${S.net}|${num(n.node_id)}`) && mode !== "none")
    out.push(el("span", { class: "hint wide", dataset: { supervisionAdded: "1" } },
      "Set when the node was added: its EDS heartbeat default is 0, so the node would not be supervised."));
  out.push(heartbeatWatchFields(i));
  return out;
}

// The variable name a PDO entry gets, whole (`io_rtd_AI0_Input_PV`), from the
// last check's declarations; "" without one.
function entryVariable(ep, prefix) {
  const decls = (S.check && S.check.declarations) || [];
  const want = prefix + ep + ".iec_location";
  const d = decls.find((x) => x.kind === "pdo" && x.path === want);
  return d ? d.name || "" : "";
}

function declNote(path) {
  return el("span", { class: "muted decl", dataset: { declFor: path } });
}

function renderPdos(i, key, dir, title, eds) {
  const n = S.config.nodes[i];
  const pdos = n[key] || [];
  const fs = el("fieldset", { dataset: { path: `nodes[${i}].${key}` } }, el("legend", null, title));
  const count = eds && eds.pdo_count ? eds.pdo_count[dir] : 0;
  fs.append(el("p", { class: "muted" }, `${pdos.length} of ${count} PDOs defined in the EDS used. Add entries with "Add entry…" (a new PDO is started when the open ones are full).`));
  // The Location column is the target's: CODESYS assigns the addresses itself
  // (a location left in an entry is listed in the tab's bar, target.js).
  const locations = usedBy(`nodes.${key}.entries.iec_location`);
  pdos.forEach((p, j) => {
    const pb = `nodes[${i}].${key}[${j}]`;
    const bits = (p.entries || []).reduce((s, e) => s + (S.state.type_bits[e.type] || 0), 0);
    const number = num(p.number) || j + 1;
    const box = el("div", { class: "pdo", dataset: { path: pb } },
      el("div", { class: "pdo-title" },
        el("strong", null, `${dir === "input" ? "TPDO" : "RPDO"} ${p.number ?? j + 1}`),
        el("span", { class: "muted" }, `${(p.entries || []).length}/8 entries, ${bits}/64 bits`),
        dir === "input" ? linkTag(n, number) : null,
        el("span", { class: "field-msg", dataset: { for: pb } }),
        eds && eds.objects ? el("button", { type: "button", class: "small", dataset: { addEntry: pb },
          title: `Pick an object for ${dir === "input" ? "TPDO" : "RPDO"} ${number}`,
          onclick: () => { S.pickerTarget = { dir, number }; S.pickerOpen[dir] = true; render(); focusPicker(dir); } }, "Add entry…") : null,
        el("button", { type: "button", class: "small", dataset: { removePdo: pb }, title: `Remove ${dir === "input" ? "TPDO" : "RPDO"} ${number} and its entries`,
          onclick: () => removePdo(i, key, j) }, "Remove PDO")),
      pdoSettings(pb, dir, p, j, eds, el("div", { class: "pdo-grid" },
        pdoField("Number", pb + ".number", String(j + 1)),
        cobIdField(pb, n, dir, p, j),
        transmissionField(pb, dir, p, eds)),
      timingLine(pb, dir, p, eds),
      dir === "input" ? timeoutLine(i, pb, p, eds) : null),
      mappingLine(i, key, dir, p, j, eds));
    const rows = (p.entries || []).map((e, k) => {
      const ep = `${pb}.entries[${k}]`;
      const info = objectInfo(eds, e.index, e.subindex);
      const loc = el("input", { type: "text", spellcheck: "false", dataset: { path: ep + ".iec_location" },
        "aria-label": "Location of " + (info ? info.name : e.index) });
      loc.value = e.iec_location || "";
      if (hasBits(e) && !e.iec_location) loc.placeholder = dir === "output" ? "bits below" : "bits only";
      loc.addEventListener("input", () => setPath(ep + ".iec_location", loc.value.trim()));
      const move = el("select", { "aria-label": "Move to PDO" },
        pdos.map((_, x) => el("option", { value: x }, `PDO ${pdos[x].number ?? x + 1}`)),
        pdos.length < count ? el("option", { value: "new" }, "new PDO") : null);
      move.value = String(j);
      move.addEventListener("change", () => moveEntry(i, key, j, k, move.value));
      // The placeholder is the generated name, filled in by applyCheck.
      const variable = el("input", { type: "text", spellcheck: "false", dataset: { path: ep + ".name", entryVariable: ep },
        "aria-label": "Variable name of " + (info ? info.name : e.index) });
      variable.value = typeof e.name === "string" ? e.name : "";
      variable.addEventListener("input", () => setPath(ep + ".name", variable.value.trim()));
      const bitsKey = `${S.net}|${ep}`;
      const bitsButton = intInfo(e.type) ? el("button", { type: "button", class: "small bits-button", dataset: { bitsFor: ep },
        "aria-expanded": String(bitsOpen(bitsKey, ep)), title: `Map single bits of ${e.index}:${e.subindex ?? 0} to their own BOOL variables`,
        onclick: () => { S.bitsOpen[bitsKey] = !bitsOpen(bitsKey, ep); render(); } },
        hasBits(e) ? `Bits… (${e.bits.length})` : "Bits…") : null;
      const columns = 6 + (locations ? 1 : 0);
      // data-label names a cell where the table is a card per entry (phone width).
      const row = el("tr", { dataset: { path: ep } },
        el("td", { dataset: { label: "Object" } }, `${e.index}:${e.subindex ?? 0}`), el("td", { dataset: { label: "Name" } }, info ? info.name : "?"),
        el("td", { class: "entry-type", dataset: { label: "Type" } }, e.type, bitsButton),
        el("td", { dataset: { label: "Variable" } }, variable, el("span", { class: "field-msg", dataset: { for: ep + ".name" } }),
          el("span", { class: "field-msg", dataset: { for: ep + ".bits" } }),
          locations ? null : el("span", { class: "field-msg", dataset: { for: ep } }),
          locations ? null : el("span", { class: "field-msg", dataset: { for: ep + ".type" } })),
        locations ? el("td", { dataset: { label: targetText("location_column") } }, loc, unmappedMark(i, dir, ep, e),
          el("span", { class: "field-msg", dataset: { for: ep + ".iec_location" } }),
          el("span", { class: "field-msg", dataset: { for: ep } }), el("span", { class: "field-msg", dataset: { for: ep + ".type" } }),
          declNote(ep + ".iec_location")) : null,
        el("td", { dataset: { label: "PDO" } }, move),
        el("td", null, el("button", { type: "button", title: "Remove", "aria-label": `Remove ${e.index}:${e.subindex ?? 0} from the PDO`,
          onclick: () => removeEntry(i, key, j, k) }, "✕")));
      return bitsButton && bitsOpen(bitsKey, ep) ? [row, el("tr", { class: "entry-bits-row" },
        el("td", { colspan: columns }, bitTable(i, dir, ep, e, info, eds)))] : [row];
    });
    box.append(el("table", { class: "pdo-entries" }, el("thead", null, el("tr", null, thCells(["Object", "Name", "Type", "Variable"]
      .concat(locations ? [targetText("location_column")] : [], ["PDO", ""])))),
      el("tbody", null, rows.flat())));
    fs.append(box);
  });
  fs.append(objectPicker(i, eds, dir));
  return fs;
}

// An entry with no PLC location and no bits reaches no variable: said in
// warning text, with Suggest filling a free location.
function unmappedMark(i, dir, ep, e) {
  if (e.iec_location || hasBits(e)) return null;
  const suggest = el("button", { type: "button", class: "small", dataset: { suggestLocation: ep }, onclick: () => busy(suggest, "Suggesting…", async () => {
    const r = await api("POST", "/api/place", { config: fileConfig(), network: S.net, node: i, direction: dir, type: e.type });
    if (!r.location) { banner(`No free location: ${r.reason || "the location tables are full"}.`, true); return; }
    setPath(ep + ".iec_location", r.location);
    render();
  }) }, "Suggest");
  return el("span", { class: "unmapped", dataset: { unmapped: ep } }, el("span", { class: "warning-text" }, "not mapped to the PLC"), " ", suggest);
}

// -- bit channels (canworks.json `bits`): single bits of an integer entry as
// BOOL variables of their own.
function hasBits(e) { return Array.isArray(e.bits) && e.bits.length > 0; }

// Whether an entry's bit table is unfolded: the user's choice, else open
// while one of its bits has a problem.
function bitsOpen(key, ep) {
  S.bitsOpen = S.bitsOpen || {};
  if (S.bitsOpen[key] !== undefined) return S.bitsOpen[key];
  return ((S.check && S.check.items) || []).some((it) => (it.where || []).some((w) =>
    (w.net === null || w.net === S.net) && typeof w.path === "string" && w.path.startsWith(ep + ".bits")));
}

// An IEC 61131-3 identifier (declare.identifier); a note's text lower case.
function bitIdentifier(text, lower = true) {
  let s = String(text || "").replace(/[^A-Za-z0-9_]+/g, "_").replace(/_+/g, "_").replace(/^_|_$/g, "");
  if (lower) s = s.toLowerCase();
  if (!s) s = "v";
  return /^[0-9]/.test(s) ? "n" + s : s;
}

// The name part a bit without a `name` gets: `<entry part>_bit<n>` (declare.bit_name).
function bitDefaultName(e, info, bit) {
  const label = (typeof e.name === "string" && e.name) || (info && info.name) || `x${hex4(num(e.index)).slice(2)}_${num(e.subindex || 0)}`;
  return `${bitIdentifier(label, false)}_bit${bit}`;
}

// The Modbus number of a bit in a bridge config: the image byte holding it
// (modbusmap.bit_byte) times 8 plus its place in the byte; null without the
// entry's location.
function bridgeBitNumber(e, bit) {
  const m = /^%([IQ])([BWDL])(\d+)$/i.exec(String(e.iec_location || "").trim());
  const it = intInfo(e.type);
  if (!m || !it) return null;
  let byte = Number(m[3]);
  if (it.bytes > 1) {
    const words = Math.floor(it.bytes / 2), word = Math.floor(bit / 16);
    const order = S.model.top.bridge && S.model.top.bridge.word_order === "low_first" ? "low_first" : "high_first";
    byte += 2 * (order === "low_first" ? word : words - 1 - word) + (bit % 16 >= 8 ? 0 : 1);
  }
  return `${m[1].toUpperCase() === "I" ? "discrete input" : "coil"} ${byte * 8 + (bit % 8)}`;
}

// The note's name of each bit of an entry: { "0": "ready to switch on", ... }.
function noteBitNames(n, e) {
  const info = objectInfo(edsFor(n), e.index, e.subindex);
  const note = noteFor(notesOf(n.eds), n.eds, e.index, e.subindex ?? 0, !!(info && info.var));
  return note.bits || {};
}

// A new bit's name from the device note, as an identifier, unless the node
// already uses it; undefined for the default name.
function noteBitName(n, e, bit, taken) {
  const text = noteBitNames(n, e)[String(bit)];
  if (!text) return undefined;
  const name = bitIdentifier(text);
  if (taken.has(name)) return undefined;
  taken.add(name);
  return name;
}

// The names the node's entries and bits use, lower case (they must differ ignoring case).
function nodeNames(n) {
  const out = new Set();
  for (const key of ["tx_pdos", "rx_pdos"]) for (const p of n[key] || []) for (const e of p.entries || []) {
    if (typeof e.name === "string" && e.name) out.add(e.name.toLowerCase());
    for (const b of Array.isArray(e.bits) ? e.bits : []) if (typeof b.name === "string" && b.name) out.add(b.name.toLowerCase());
  }
  return out;
}

// The bit channels of a node's PDO entries for one object: [{ bit, name }].
function bitChannelsOf(n, o) {
  const out = [];
  for (const key of ["tx_pdos", "rx_pdos"]) for (const p of n[key] || []) for (const e of p.entries || []) {
    if (!hasBits(e) || !sameObject(e.index, e.subindex, o.index, o.subindex)) continue;
    const info = objectInfo(edsFor(n), e.index, e.subindex);
    for (const b of e.bits) out.push({ bit: b.bit, name: b.name || bitDefaultName(e, info, b.bit) });
  }
  return out;
}

// Before an RPDO entry with its own location gets bits on OpenPLC: the bits
// write the value, so the location goes. False when the user keeps it.
async function bitsReplaceLocation(e, ep) {
  if (!e.iec_location || hasBits(e) || !usedBy("nodes.rx_pdos.entries.bits.iec_location")) return true;
  const answer = await modal(`${e.index}:${e.subindex ?? 0} is written from ${e.iec_location} now. With bits, the program sets each bit ` +
    `and the bits make up the value, so ${e.iec_location} is removed from the entry.`,
    [["cancel", "Keep the location"], ["bits", "Use bits", true]]);
  if (answer !== "bits") return false;
  delete getPath(ep).iec_location;
  return true;
}

async function mapBit(i, dir, ep, bit) {
  const n = S.config.nodes[i];
  const e = getPath(ep);
  if (dir === "output" && !(await bitsReplaceLocation(e, ep))) { render(); return; }
  const b = { bit };
  const name = noteBitName(n, e, bit, nodeNames(n));
  if (name) b.name = name;
  if (usedBy(`nodes.${dir === "input" ? "tx" : "rx"}_pdos.entries.bits.iec_location`)) {
    try {
      b.iec_location = (await api("POST", "/api/place", { config: fileConfig(), network: S.net,
        direction: dir === "input" ? "bit_in" : "bit_out" })).location;
    } catch (err) { banner(err.message, true); }
  }
  e.bits = (e.bits || []).concat([b]).sort((x, y) => x.bit - y.bit);
  changed(true);
}

function unmapBit(ep, bit) {
  const e = getPath(ep);
  e.bits = (e.bits || []).filter((b) => b.bit !== bit);
  if (!e.bits.length) delete e.bits;
  changed(true);
}

// Every bit mapped: the missing ones on the free block's bit of their number
// (bit n at bit n mod 8 of the block's (n div 8)-th byte); the mapped ones stay.
async function mapAllBits(i, dir, ep, button) {
  const n = S.config.nodes[i];
  const e = getPath(ep);
  const count = intInfo(e.type).bytes * 8;
  if (dir === "output" && !(await bitsReplaceLocation(e, ep))) { render(); return; }
  let locations = null;
  if (usedBy(`nodes.${dir === "input" ? "tx" : "rx"}_pdos.entries.bits.iec_location`)) {
    try {
      locations = (await busy(button, "Placing…", () => api("POST", "/api/place", { config: fileConfig(), network: S.net,
        direction: dir === "input" ? "bits_in" : "bits_out", type: count }))).locations;
    } catch (err) { banner(err.message, true); return; }
  }
  const have = new Map((e.bits || []).map((b) => [b.bit, b]));
  const taken = nodeNames(n);
  const out = [];
  for (let bit = 0; bit < count; bit++) {
    if (have.has(bit)) { out.push(have.get(bit)); continue; }
    const b = { bit };
    const name = noteBitName(n, e, bit, taken);
    if (name) b.name = name;
    if (locations) b.iec_location = locations[bit];
    out.push(b);
  }
  e.bits = out;
  changed(true);
}

function unmapAllBits(ep) {
  delete getPath(ep).bits;
  changed(true);
}

// The unfolded bit table of an entry: bit, the note's name, a tick that maps
// it, its name and (OpenPLC) its location, or (bridge) its Modbus number.
function bitTable(i, dir, ep, e, info, eds) {
  const n = S.config.nodes[i];
  const count = intInfo(e.type).bytes * 8;
  const notes = noteBitNames(n, e);
  const located = usedBy(`nodes.${dir === "input" ? "tx" : "rx"}_pdos.entries.bits.iec_location`);
  const bridge = projectTarget() === "bridge";
  const what = `${e.index}:${e.subindex ?? 0}`;
  const byBit = new Map((e.bits || []).map((b, m) => [b.bit, m]));
  const rows = [];
  for (let bit = 0; bit < count; bit++) {
    const m = byBit.get(bit);
    const b = m === undefined ? null : e.bits[m];
    const bp = `${ep}.bits[${m}]`;
    const tick = el("input", { type: "checkbox", "aria-label": `Map bit ${bit} of ${what}`, dataset: { bitTick: bit } });
    tick.checked = !!b;
    tick.addEventListener("change", () => (tick.checked ? mapBit(i, dir, ep, bit) : unmapBit(ep, bit)));
    let nameCell, locCell = null;
    if (b) {
      const name = el("input", { type: "text", spellcheck: "false", dataset: { path: bp + ".name", bitOf: ep, bit },
        placeholder: bitDefaultName(e, info, bit), "aria-label": `Name of bit ${bit} of ${what}` });
      name.value = typeof b.name === "string" ? b.name : "";
      name.addEventListener("input", () => setPath(bp + ".name", name.value.trim()));
      nameCell = el("td", null, name, el("span", { class: "field-msg", dataset: { for: bp + ".name" } }),
        el("span", { class: "field-msg", dataset: { for: bp + ".bit" } }), el("span", { class: "field-msg", dataset: { for: bp } }));
      if (located) {
        const loc = el("input", { type: "text", spellcheck: "false", dataset: { path: bp + ".iec_location" },
          "aria-label": `Location of bit ${bit} of ${what}`, placeholder: dir === "input" ? "%IX…" : "%QX…" });
        loc.value = b.iec_location || "";
        loc.addEventListener("input", () => setPath(bp + ".iec_location", loc.value.trim()));
        const suggest = el("button", { type: "button", class: "small", title: `Suggest a free ${dir === "input" ? "%IX" : "%QX"} bit`,
          onclick: (ev) => busy(ev.currentTarget, "…", async () => {
            try {
              const r = await api("POST", "/api/place", { config: fileConfig(), network: S.net, direction: dir === "input" ? "bit_in" : "bit_out" });
              setPath(bp + ".iec_location", r.location);
              render();
            } catch (err) { banner(err.message, true); }
          }) }, "Suggest");
        locCell = el("td", null, el("div", { class: "entry-variable" }, loc, suggest),
          el("span", { class: "field-msg", dataset: { for: bp + ".iec_location" } }), declNote(bp + ".iec_location"));
      } else if (bridge) {
        locCell = el("td", { class: "muted", dataset: { bitModbus: bit } }, bridgeBitNumber(e, bit) || "with the entry's location");
      }
    } else {
      nameCell = el("td", { class: "muted" }, dir === "output" && hasBits(e) && !(bridge && e.iec_location) ? "sent as 0" : "");
      locCell = located || bridge ? el("td") : null;
    }
    rows.push(el("tr", { class: b ? "mapped" : null, dataset: { bitRow: bit } },
      el("td", null, String(bit)), el("td", { class: "muted bit-note" }, notes[String(bit)] || ""), el("td", null, tick), nameCell, locCell));
  }
  const mapped = (e.bits || []).length;
  return el("div", { class: "entry-bits", dataset: { bitsTable: ep } },
    el("div", { class: "entry-bits-head" },
      el("span", { class: "muted" }, `${mapped} of ${count} bits of ${what} mapped to BOOL variables` +
        (located ? "" : bridge ? ", served in the entry's own location" : "")),
      mapped < count ? el("button", { type: "button", class: "small", dataset: { mapAllBits: ep },
        onclick: (ev) => mapAllBits(i, dir, ep, ev.currentTarget) }, "Map all bits") : null,
      mapped ? el("button", { type: "button", class: "small", dataset: { unmapAllBits: ep }, onclick: () => unmapAllBits(ep) }, "Unmap all") : null),
    el("table", { class: "bits" }, el("thead", null, el("tr", null, thCells(["Bit", "Device note", "Map", "Variable"]
      .concat(located ? [targetText("location_column")] : bridge ? ["Modbus"] : [])))), el("tbody", null, rows)));
}

// A PDO's communication settings under one summary line ("COB-ID 0x185 ·
// on change · event 100 ms · timeout 500 ms"), closed until opened, or
// until one of them has a problem; the user's choice stays for the node.
const PDO_SETTING_KEYS = /^\.(number|cob_id|transmission|inhibit_time_us|event_timer_ms|sync_start|timeout_ms|on_timeout|timeout_location)/;
function pdoSettings(pb, dir, p, j, eds, ...body) {
  S.pdoOpen = S.pdoOpen || {};
  const key = `${S.net}|${pb}`;
  const problem = ((S.check && S.check.items) || []).some((it) => (it.where || []).some((w) =>
    (w.net === null || w.net === S.net) && typeof w.path === "string" && w.path.startsWith(pb) && PDO_SETTING_KEYS.test(w.path.slice(pb.length))));
  const d = el("details", { class: "pdo-settings", dataset: { pdoSettings: pb } },
    el("summary", null, el("span", { class: "pdo-summary", dataset: { pdoSummary: pb } }, pdoSummaryText(pb, dir, p, j, eds)),
      el("span", { class: "muted settings-word" }, " · Settings")), ...body);
  d.open = problem || !!S.pdoOpen[key];
  d.addEventListener("toggle", () => { S.pdoOpen[key] = d.open; });
  return d;
}

function pdoSummaryText(pb, dir, p, j, eds) {
  const n = S.config.nodes[Number(/^nodes\[(\d+)\]/.exec(pb)[1])];
  const nr = num(p.number) || j + 1;
  const sub = (s) => (eds ? commSub(eds, dir, nr, s) : null);
  const hex = (c) => "0x" + Number(c).toString(16).toUpperCase();
  const parts = [];
  const cob = p.cob_id;
  parts.push("COB-ID " + (Number.isInteger(num(cob)) && cob !== "auto" ? hex(num(cob))
    : cob === "auto" ? (autoCobIds()[pb] !== undefined ? hex(autoCobIds()[pb]) : "auto") : defaultCobId(n, dir, nr)));
  const t = p.transmission !== undefined ? num(p.transmission) : sub(2) ? sub(2).value : null;
  if (t !== null && t !== undefined) {
    const words = dir === "input" ? { 0: "on change, at SYNC", 1: "every SYNC", 254: "event (manufacturer)", 255: "on change" }
      : { 1: "at SYNC", 254: "event (manufacturer)", 255: "event-driven" };
    parts.push(words[t] || (t >= 2 && t <= 240 ? `every ${t}th SYNC` : `type ${t}`));
  }
  const ev = p.event_timer_ms !== undefined ? num(p.event_timer_ms) : sub(5) ? sub(5).value : null;
  if (ev) parts.push(`${dir === "input" ? "event" : "deadline"} ${ev} ms`);
  if (dir === "input" && p.timeout_ms !== undefined && usedBy("nodes.tx_pdos.timeout_ms")) parts.push(p.timeout_ms === "auto" ? "timeout auto" : `timeout ${p.timeout_ms} ms`);
  return parts.join(" · ");
}

function focusPicker(dir) {
  const f = document.querySelector(`details[data-picker="${dir}"] input[type=text]`);
  if (f) f.focus();
}

// A PDO's mapping object from the EDS: { writable, has_default, defaults:
// [{ index, subindex, bits }] }, or null when the EDS does not define it.
function pdoMap(eds, dir, number) {
  return eds && eds.pdo_maps && eds.pdo_maps[dir] ? eds.pdo_maps[dir][String(number)] || null : null;
}

// Whether the PDO keeps the device's mapping, decided as the plugin does:
// "device", or left out on a mapping the EDS makes read-only.
function usesDeviceMapping(p, m) {
  return p.mapping === "device" || (p.mapping === undefined && !!m && !m.writable);
}

// Dummy entries (0x0001-0x0007) fill gaps in a mapping and carry no data.
function isDummy(d) { return num(d.index) < 8; }

// Who sets the PDO's mapping: fixed by the device, or a choice when the EDS
// lets the master write it. With the device mapping, its objects are listed
// (those the config uses in bold) with "Map all".
function mappingLine(i, key, dir, p, j, eds) {
  const pb = `nodes[${i}].${key}[${j}]`;
  const m = pdoMap(eds, dir, num(p.number) || j + 1);
  if (!m) return null;
  const parts = [];
  if (!m.writable) {
    parts.push(el("div", { class: "fixed-field" }, el("output", { dataset: { mapping: pb } }, "Set by the device"),
      hint("The EDS makes this PDO's mapping read-only; the node keeps it and the PLC uses the objects listed.")));
  } else {
    parts.push(choice("Mapping source", pb + ".mapping", [
      { value: undefined, label: "Write from this config", help: "The master writes this PDO's mapping from the entries below." },
      { value: "device", label: "Use device mapping", help: "Nothing is written: the node keeps the mapping from its EDS, and the entries below name the objects of it the PLC uses." },
    ], { onChange: (v) => { setPath(pb + ".mapping", v); render(); } }));
  }
  if (usesDeviceMapping(p, m)) {
    if (!m.has_default) {
      parts.push(el("span", { class: "field-msg" }, "The EDS gives no default mapping for this PDO."));
    } else {
      const used = (d) => (p.entries || []).some((e) => sameObject(e.index, e.subindex, d.index, d.subindex));
      parts.push(el("ul", { class: "pdo-map" }, ...m.defaults.map((d) => {
        const info = objectInfo(eds, d.index, d.subindex);
        const text = `${d.index}:${d.subindex}${info ? " " + info.name : isDummy(d) ? " (gap)" : ""}`;
        return el("li", { class: used(d) ? "used" : null }, text, used(d) ? el("span", { class: "tag" }, "used") : null);
      })));
      if (m.defaults.some((d) => !isDummy(d) && !used(d)))
        parts.push(el("button", { type: "button", dataset: { mapAll: pb }, onclick: () => mapAll(i, key, dir, j) }, "Map all"));
    }
  }
  return el("div", { class: "pdo-row" }, el("span", { class: "row-head" }, "Mapping"), el("div", { class: "pdo-row-body" }, ...parts));
}

function pdoField(label, path, dflt, help) {
  const v = getPath(path);
  const input = el("input", { type: "text", dataset: { path }, placeholder: dflt, "aria-label": label });
  input.value = v === undefined ? "" : String(v);
  input.addEventListener("input", () => {
    const t = input.value.trim();
    setPath(path, t === "" ? undefined : /^[0-9]+$/.test(t) ? parseInt(t, 10) : t);
  });
  return el("label", null, label, input, hint(help || (dflt ? "Empty: " + dflt : null)),
    el("span", { class: "field-msg", dataset: { for: path } }));
}

// The CiA 301 default COB-ID the plugin uses when cob_id is left out (PDOs 1-4).
function defaultCobId(n, dir, number) {
  const id = num(n.node_id);
  const nr = num(number);
  if (!(nr >= 1 && nr <= 4)) return "auto or a COB-ID";
  if (!(id >= 1 && id <= 127)) return "from node ID";
  const cob = (dir === "input" ? 0x80 : 0x100) + 0x100 * nr + id;
  return "0x" + cob.toString(16).toUpperCase();
}

// What "auto" COB-IDs resolve to, as the plugin does it (contract.auto_cob_ids):
// the CiA 301 default for PDOs 1-4; above, the highest COB-ID in 0x181-0x57F
// outside every node's predefined set and not used by another PDO, in config
// order. Returns { "nodes[i].tx_pdos[j]": cob }.
function autoCobIds() {
  const nodes = (S.config && S.config.nodes) || [];
  const keys = [["tx_pdos", "input"], ["rx_pdos", "output"]];
  const dflt = (id, nr, dir) => (nr >= 1 && nr <= 4 ? (dir === "input" ? 0x80 : 0x100) + 0x100 * nr + id : null);
  const taken = new Set();
  nodes.forEach((n) => {
    const id = num(n.node_id);
    if (!(id >= 1 && id <= 127)) return;
    for (let b = 0x180; b <= 0x500; b += 0x80) taken.add(b + id);
    for (const [k, dir] of keys)
      (n[k] || []).forEach((p, j) => {
        const c = p.cob_id === "auto" || p.cob_id === undefined ? dflt(id, num(p.number ?? j + 1), dir) : num(p.cob_id);
        if (c !== null && !Number.isNaN(c)) taken.add(c);
      });
  });
  const out = {};
  nodes.forEach((n, i) => {
    for (const [k, dir] of keys)
      (n[k] || []).forEach((p, j) => {
        if (p.cob_id !== "auto") return;
        let c = dflt(num(n.node_id), num(p.number ?? j + 1), dir);
        if (c === null) {
          c = 0x57F;
          while (c > 0x180 && taken.has(c)) c--;
          if (c === 0x180) return;
          taken.add(c);
        }
        out[`nodes[${i}].${k}[${j}]`] = c;
      });
  });
  return out;
}

function cobIdField(pb, n, dir, p, j) {
  const f = pdoField("COB-ID", pb + ".cob_id", defaultCobId(n, dir, p.number ?? j + 1),
    "Empty: the CiA default (PDOs 1-4). \"auto\": the default, or a free COB-ID above PDO 4.");
  // What "auto" resolves to, updated as the user types.
  const resolved = el("span", { class: "hint" });
  const show = () => {
    if (getPath(pb + ".cob_id") !== "auto") { resolved.textContent = ""; return; }
    const c = autoCobIds()[pb];
    resolved.textContent = c === undefined ? "no free COB-ID" : "auto = 0x" + c.toString(16).toUpperCase();
  };
  f.querySelector("input").addEventListener("input", show);
  show();
  f.append(resolved);
  return f;
}

// A PDO communication sub-object from the EDS: { access, writable, value }
// or null when the EDS does not define it.
function commSub(eds, dir, number, sub) {
  const o = objectInfo(eds, hex4((dir === "input" ? 0x1800 : 0x1400) + number - 1), sub);
  return o ? { access: o.access, writable: o.writable, value: edsDefault(eds, (dir === "input" ? 0x1800 : 0x1400) + number - 1, sub) } : null;
}

// One timing field from the EDS: hidden when the EDS lacks the sub-index,
// read-only (showing the EDS value) when the device fixes it. opts.show /
// opts.parse convert between the config value and what the page shows;
// opts.fromEds turns the EDS value into the config's unit.
function timingField(label, path, info, unit, help, opts) {
  if (!info) return null;
  opts = opts || {};
  const show = opts.show || ((v) => String(v));
  const parse = opts.parse || ((t) => (/^[0-9]+$/.test(t) ? parseInt(t, 10) : t));
  const eds = info.value === null ? null : (opts.fromEds ? opts.fromEds(info.value) : info.value);
  const edsText = eds === null ? "EDS default" : `EDS default (${show(eds)}${unit})`;
  const v = getPath(path);
  const input = el("input", { type: "text", dataset: { path }, "aria-label": label, placeholder: edsText });
  input.value = v === undefined ? "" : (typeof v === "number" ? show(v) : String(v));
  const title = label + (unit ? ` (${unit.trim()})` : "");
  if (!info.writable) {
    input.disabled = true;
    input.value = eds === null ? "" : show(eds);
    return el("label", null, title, input, hint(`Fixed by the EDS (${info.access}).`),
      el("span", { class: "field-msg", dataset: { for: path } }));
  }
  input.addEventListener("input", () => {
    const t = input.value.trim();
    setPath(path, t === "" ? undefined : parse(t));
  });
  return el("label", null, title, input, hint(help + " Empty: " + edsText + "."),
    el("span", { class: "field-msg", dataset: { for: path } }));
}

// The PDO's timing settings the EDS offers for its direction.
function timingLine(pb, dir, p, eds) {
  if (!eds) return null;
  const nr = num(p.number) || 1;
  const sub = (s) => commSub(eds, dir, nr, s);
  const fields = [];
  if (dir === "input") {
    // Shown in ms; stored in µs; the EDS gives 100 µs units.
    fields.push(timingField("Inhibit time", pb + ".inhibit_time_us", sub(3), " ms",
      "The slave waits at least this long between two sends of this PDO.", {
        show: (us) => String(us / 1000),
        parse: (t) => (/^[0-9]+(\.[0-9]+)?$/.test(t) ? Math.round(parseFloat(t) * 10) * 100 : t),
        fromEds: (units) => units * 100,
      }));
    fields.push(timingField("Event timer", pb + ".event_timer_ms", sub(5), " ms",
      "With an event-driven type the slave sends at least this often."));
    const t = p.transmission !== undefined ? num(p.transmission) : (sub(2) ? sub(2).value : null);
    if (t !== null && t >= 1 && t <= 240)
      fields.push(timingField("SYNC start", pb + ".sync_start", sub(6), "",
        "The SYNC counter value at which the slave sends this PDO the first time (needs a SYNC counter)."));
  } else {
    fields.push(timingField("Deadline", pb + ".event_timer_ms", sub(5), " ms",
      "The slave reports an error when this PDO has not arrived within this time."));
  }
  const shown = fields.filter(Boolean);
  return shown.length ? el("div", { class: "pdo-row" }, el("span", { class: "row-head" }, "Timing"),
    el("div", { class: "pdo-grid" }, ...shown)) : null;
}

// The receive timeout of a TPDO (canopen-pdo-io "Receive timeout setting"):
// off, a number of ms, or "auto" (two times the PDO's event timer, from the
// config or the EDS). With a timeout: what the inputs show meanwhile and the
// optional timeout bit.
function timeoutLine(i, pb, p, eds) {
  const nr = num(p.number) || 1;
  // Read when shown: the event timer field above can change without a render.
  const eventTimer = () => {
    const own = getPath(pb + ".event_timer_ms");
    if (own !== undefined) return num(own);
    return eds && commSub(eds, "input", nr, 5) ? commSub(eds, "input", nr, 5).value : null;
  };
  const path = pb + ".timeout_ms";
  const input = el("input", { type: "text", spellcheck: "false", dataset: { path }, placeholder: "off",
    "aria-label": "Receive timeout" });
  const v = getPath(path);
  input.value = v === undefined ? "" : String(v);
  const resolved = el("span", { class: "hint", dataset: { timeoutFor: pb } });
  const show = () => {
    const t = getPath(path);
    const et = eventTimer();
    resolved.textContent = t !== "auto" ? ""
      : et ? `auto (${Math.min(2 * et, 65535)} ms)` : "auto needs an event timer (set one, or give milliseconds)";
  };
  input.addEventListener("input", () => {
    const t = input.value.trim();
    setPath(path, t === "" ? undefined : /^[0-9]+$/.test(t) ? parseInt(t, 10) : t.toLowerCase() === "auto" ? "auto" : t);
    show();
  });
  // Off and on change which fields follow.
  input.addEventListener("change", () => {
    if (getPath(path) === undefined) {
      // Part of emptying the field: one undo step brings all three back.
      const pdo = getPath(pb);
      if (pdo) { delete pdo.on_timeout; delete pdo.timeout_location; }
      undoBase();
      scheduleCheck();
    }
    render();
  });
  show();
  const autoBtn = el("button", { type: "button", dataset: { timeoutAuto: pb },
    onclick: () => { setPath(path, "auto"); render(); } }, "Auto");
  const fields = [el("label", null, "Receive timeout (ms)", el("span", { class: "row" }, input, autoBtn), resolved,
    hint("The master flags this PDO when it has not arrived for this long while the node is up. Empty: off." +
      " Auto: two times its event timer."),
    el("span", { class: "field-msg", dataset: { for: path } }))];
  if (v !== undefined) {
    fields.push(choice("On timeout", pb + ".on_timeout", [
      { value: undefined, label: "Hold last values", help: "The PDO's inputs keep their last values, as for a lost node." },
      { value: "zero", label: "Set inputs to 0", help: "The PDO's inputs read 0 until it arrives again." },
    ]));
    const locPath = pb + ".timeout_location";
    const loc = field("", locPath, "text", { placeholder: "%IX…" }).querySelector("input");
    const suggest = el("button", { type: "button", dataset: { suggest: "timeout" },
      onclick: async () => {
        const r = await api("POST", "/api/place", { config: fileConfig(), network: S.net, node: i, direction: "status" });
        setPath(locPath, r.location);
        render();
      } }, "Suggest");
    fields.push(el("label", null, "Timeout bit", el("span", { class: "row" }, loc, suggest),
      hint("Optional. TRUE while this PDO is timed out and its node is up. Empty: no bit."),
      el("span", { class: "field-msg", dataset: { for: locPath } }), declNote(locPath)));
  }
  return el("div", { class: "pdo-row" }, el("span", { class: "row-head" }, "Timeout"),
    el("div", { class: "pdo-grid" }, ...fields));
}

// A sub-object's DefaultValue in the EDS as a number (null if absent or
// node-ID relative).
function edsDefault(eds, index, sub) {
  const o = objectInfo(eds, "0x" + index.toString(16).toUpperCase().padStart(4, "0"), sub);
  const d = o && typeof o.default === "string" ? o.default.trim() : "";
  if (/^0x[0-9a-f]+$/i.test(d)) return parseInt(d, 16);
  if (/^[0-9]+$/.test(d)) return parseInt(d, 10);
  return null;
}

const TRANSMISSION = {
  input: [
    { value: 1, label: "1: every SYNC", help: "The slave sends this PDO after every SYNC." },
    { value: 0, label: "0: on change, at SYNC", help: "The slave sends after a SYNC, but only when the value has changed (device-specific)." },
    { value: "n", label: "Every n-th SYNC", help: "The slave sends after every n-th SYNC (n = 2 to 240), for slow signals." },
    { value: 254, label: "254: event (manufacturer)", help: "The slave sends when it decides to, as its manual describes. Set an event timer for a minimum rate." },
    { value: 255, label: "255: event (device profile)", help: "The slave sends on change, as its device profile defines, and when the event timer runs out." },
  ],
  output: [
    { value: 1, label: "1: at SYNC", help: "The master sends the outputs with every SYNC and the slave applies them at the SYNC." },
    { value: 255, label: "255: event-driven", help: "The slave applies the outputs as soon as they arrive." },
    { value: 254, label: "254: event (manufacturer)", help: "Event-driven, as the slave's manual describes." },
  ],
};

function transmissionField(pb, dir, p, eds) {
  const path = pb + ".transmission";
  const t = p.transmission;
  const many = dir === "input" && typeof t === "number" && t >= 2 && t <= 240;
  // Left empty, the slave keeps the transmission type its EDS gives.
  const number = num(p.number) || 1;
  const d = edsDefault(eds, (dir === "input" ? 0x1800 : 0x1400) + number - 1, 2);
  const known = d === null ? null
    : TRANSMISSION[dir].find((o) => o.value === d) || (d >= 2 && d <= 240 ? { label: `every ${d}th SYNC` } : { label: String(d) });
  const info = commSub(eds, dir, number, 2);
  if (info && !info.writable && (t === undefined || t === d)) {
    // The device fixes it: nothing to choose (a different value in the file
    // stays editable below, so the check's error can be fixed here).
    return el("div", { class: "fixed-field" }, el("span", { class: "label" }, "Transmission type"),
      el("output", { dataset: { path }, "aria-label": "Transmission type" }, d === null ? "Fixed by the EDS" : `${known.label}, fixed by the EDS`),
      hint(`The EDS marks it ${info.access}; the slave keeps its own value.`), el("span", { class: "field-msg", dataset: { for: path } }));
  }
  const choices = [{ value: undefined, label: d === null ? "EDS default" : `EDS default (${known.label})`,
    help: "Nothing is written to the slave: it keeps the transmission type from its EDS." }, ...TRANSMISSION[dir]];
  const c = choice("Transmission type", path, choices, {
    current: many ? "n" : t, wide: true,
    onChange: (v) => { setPath(path, v === "n" ? 2 : v); render(); },
  });
  if (many) {
    const nIn = el("input", { type: "text", "aria-label": "SYNC count", value: String(t), class: "short" });
    nIn.addEventListener("input", () => {
      const s = nIn.value.trim();
      setPath(path, /^[0-9]+$/.test(s) ? parseInt(s, 10) : s);
    });
    c.querySelector("select").after(el("span", { class: "row" }, "n =", nIn));
  }
  return c;
}

// The object picker of one PDO direction, at the end of its fieldset:
// "Add entry…" opens the list of that direction's mappable objects. An
// object goes into the PDO whose "Add entry…" opened the picker, else
// into the first PDO with room (a new one when none has).
function objectPicker(i, eds, dir) {
  if (!eds || !eds.objects) return el("p", { class: "muted" }, "Pick an EDS for this node first.");
  const label = dir === "input" ? "TPDO" : "RPDO";
  const target = S.pickerTarget && S.pickerTarget.dir === dir ? S.pickerTarget.number : null;
  const objects = eds.objects.map((o) => Object.assign({}, o, { directions: pickable(eds, o) })).filter((o) => o.directions.includes(dir));
  const name = S.config.nodes[i].eds;
  const noteOfObj = (o) => noteFor(notesOf(name), name, o.index, o.subindex, !!o.var);
  const d = el("details", { class: "picker", open: S.pickerOpen[dir] || null, dataset: { picker: dir } },
    el("summary", null, "Add entry…"));
  d.addEventListener("toggle", () => { S.pickerOpen[dir] = d.open; if (!d.open) S.pickerTarget = null; });
  const filter = el("input", { type: "text", placeholder: "Index, name or note", "aria-label": `Filter ${dir} objects` });
  filter.value = S.objectFilter;
  const body = el("tbody");
  const fill = () => {
    const f = S.objectFilter.toLowerCase();
    body.replaceChildren(...objects
      .filter((o) => objectMatches(o, f, noteOfObj(o)))
      .map((o) => el("tr", null, el("td", null, `${o.index}:${o.subindex}`), el("td", null, o.name, noteLine(noteOfObj(o))),
        el("td", null, o.type, noteOfObj(o).unit ? el("span", { class: "muted" }, " " + noteOfObj(o).unit) : null),
        el("td", null, o.access),
        el("td", null, isMapped(i, o) ? el("span", { class: "muted" }, "mapped") :
          el("button", { type: "button", dataset: { add: `${o.index}:${o.subindex}` }, "aria-label": `Add ${o.index}:${o.subindex} ${o.name || ""}`,
            onclick: (e) => busy(e.currentTarget, "Adding…", async () => {
              await addEntry(i, o, dir, target);
              // The object's row now reads "mapped": the focus goes back to the picker's filter for the next one.
              const a = document.activeElement;
              if (!a || a === document.body || !a.isConnected) focusPicker(dir);
            }) }, "Add")))));
  };
  filter.addEventListener("input", () => { S.objectFilter = filter.value; fill(); });
  fill();
  d.append(el("div", null,
    el("div", { class: "toolbar" }, filter,
      el("span", { class: "muted", dataset: { pickerTarget: dir } }, target !== null
        ? `Adding to ${label} ${target}. ` : `${objects.length} ${dir}-direction object${objects.length === 1 ? "" : "s"} the EDS lets a ${label} carry. `),
      target !== null ? el("button", { type: "button", class: "small", onclick: () => { S.pickerTarget = null; render(); } }, "Any PDO") : null),
    el("div", { class: "objects", dataset: { box: "pdo_picker", boxLabel: "the object picker" } }, el("table", null,
      el("thead", null, el("tr", null, thCells(["Object", "Name", "Type", "Access", ""]))), body))));
  return d;
}

// The directions an object can be added in: when every PDO of a direction
// has a mapping the device fixes, only objects of those mappings.
function pickable(eds, o) {
  return o.directions.filter((dir) => {
    const maps = Object.values((eds.pdo_maps || {})[dir] || {});
    if (!maps.length || maps.some((m) => m.writable)) return true;
    return maps.some((m) => m.defaults.some((d) => sameObject(d.index, d.subindex, o.index, o.subindex)));
  });
}

// The PDO number whose device mapping carries the object, for a node:
// one already in the config with the device mapping, else a fixed one.
function devicePdoFor(i, dir, o) {
  const n = S.config.nodes[i];
  const eds = edsFor(n);
  const pdos = n[dir === "input" ? "tx_pdos" : "rx_pdos"] || [];
  const has = (m) => m && m.has_default && m.defaults.some((d) => sameObject(d.index, d.subindex, o.index, o.subindex));
  for (const [j, p] of pdos.entries()) {
    const number = num(p.number) || j + 1;
    const m = pdoMap(eds, dir, number);
    if (usesDeviceMapping(p, m) && has(m)) return number;
  }
  const count = eds && eds.pdo_count ? eds.pdo_count[dir] : 0;
  for (let number = 1; number <= count; ++number) {
    const m = pdoMap(eds, dir, number);
    if (m && !m.writable && has(m) && !pdos.some((p, j) => (num(p.number) || j + 1) === number)) return number;
  }
  return null;
}

// Adds the object to PDO `number` (creating that PDO) with a suggested location.
async function addToPdo(i, dir, number, o) {
  const n = S.config.nodes[i];
  const key = dir === "input" ? "tx_pdos" : "rx_pdos";
  const r = await api("POST", "/api/place", { config: fileConfig(), network: S.net, node: i, direction: dir, type: o.type });
  n[key] = n[key] || [];
  let p = n[key].find((q, j) => (num(q.number) || j + 1) === number);
  if (!p) {
    p = { number, entries: [] };
    n[key].push(p);
  }
  p.entries = p.entries || [];
  p.entries.push({ index: o.index, subindex: o.subindex, type: o.type, iec_location: r.location });
}

// Adds every object of the PDO's device mapping that is not in it yet.
async function mapAll(i, key, dir, j) {
  const n = S.config.nodes[i];
  const eds = edsFor(n);
  const p = n[key][j];
  const number = num(p.number) || j + 1;
  const m = pdoMap(eds, dir, number);
  for (const d of m.defaults) {
    if (isDummy(d) || (p.entries || []).some((e) => sameObject(e.index, e.subindex, d.index, d.subindex))) continue;
    const info = objectInfo(eds, d.index, d.subindex);
    if (!info || !info.type) continue;
    await addToPdo(i, dir, number, { index: info.index, subindex: info.subindex, type: info.type });
  }
  changed(true);
}

function isMapped(i, o) {
  const n = S.config.nodes[i];
  return ["tx_pdos", "rx_pdos"].some((k) => (n[k] || []).some((p) =>
    (p.entries || []).some((e) => sameObject(e.index, e.subindex, o.index, o.subindex))));
}

function renderSdos(i, eds) {
  const n = S.config.nodes[i];
  const list = n.sdo || [];
  const fs = el("fieldset", { dataset: { path: `nodes[${i}].sdo` } }, el("legend", { class: "visually-hidden" }, "Startup SDO writes"),
    el("p", { class: "muted" }, "Written in this order every time the node is configured at boot, after the PDO parameters. Only objects the EDS marks writable can be added."));
  const nb = notesOf(n.eds);
  const noteOfObj = (o) => noteFor(nb, n.eds, o.index, o.subindex, !!o.var);
  const rows = list.map((s, j) => {
    const sp = `nodes[${i}].sdo[${j}]`;
    const info = objectInfo(eds, s.index, s.subindex);
    const note = info ? noteOfObj(info) : {};
    const value = el("input", { type: "text", dataset: { path: sp + ".value" }, "aria-label": "Value",
      placeholder: info && info.default ? info.default : null });
    // The value in its default's notation: hex next to a hex EDS default.
    const hexDefault = !!(info && typeof info.default === "string" && /^0x/i.test(info.default.trim()));
    value.value = s.value === undefined ? "" : typeof s.value === "number" && hexDefault && Number.isInteger(s.value) && s.value >= 0
      ? "0x" + s.value.toString(16).toUpperCase() : String(s.value);
    const meaning = el("span", { class: "muted", dataset: { sdoMeaning: sp } });
    const showMeaning = () => { const t = value.value.trim(); const w = /^-?[0-9]+(\.[0-9]+)?$/.test(t) ? noteMeaning(note, Number(t)) : ""; meaning.textContent = w ? ` (${w})` : ""; };
    const setValue = () => {
      const t = value.value.trim();
      let v = t;
      if (/^-?[0-9]+$/.test(t)) v = parseInt(t, 10);
      else if (/^-?[0-9]*\.[0-9]+$/.test(t)) v = parseFloat(t);
      else if (t === "true" || t === "false") v = t === "true";
      setPath(sp + ".value", t === "" ? undefined : v);
      showMeaning();
    };
    value.addEventListener("input", setValue);
    const pick = valuePicker(note, value, (x) => { value.value = x; setValue(); });
    showMeaning();
    const typeCell = info && info.type ? s.type : (() => {
      const sel = el("select", { dataset: { path: sp + ".type" }, "aria-label": "Type" }, TYPES.map((t) => el("option", { value: t }, t)));
      sel.value = s.type || "";
      sel.addEventListener("change", () => setPath(sp + ".type", sel.value));
      return sel;
    })();
    // The same object written twice: the node keeps the later value.
    const twice = list.map((o, x) => x).filter((x) => x !== j && sameObject(list[x].index, list[x].subindex, s.index, s.subindex));
    return el("tr", { dataset: { path: sp } },
      el("td", null, `${s.index}:${s.subindex ?? 0}`),
      el("td", null, info ? info.name : el("span", { class: "field-msg warning" }, "not in the EDS"),
        noteLine(note),
        twice.length ? el("span", { class: "field-msg warning", dataset: { twice: "1" } },
          ` also written in row ${twice.map((x) => x + 1).join(", ")}; the last write wins`) : null),
      el("td", null, typeCell),
      el("td", null, pick, value, meaning, el("span", { class: "field-msg", dataset: { for: sp + ".value" } }),
        el("span", { class: "field-msg", dataset: { for: sp } }), el("span", { class: "field-msg", dataset: { for: sp + ".type" } }),
        info && info.default ? el("span", { class: "muted" }, " · EDS default " + info.default) : null),
      el("td", null, el("span", { class: "btn-group" },
        el("button", { type: "button", title: "Up", "aria-label": `Move ${s.index}:${s.subindex ?? 0} up`, disabled: j === 0, onclick: () => moveSdo(i, j, -1) }, "↑"),
        el("button", { type: "button", title: "Down", "aria-label": `Move ${s.index}:${s.subindex ?? 0} down`, disabled: j === list.length - 1, onclick: () => moveSdo(i, j, 1) }, "↓"),
        el("button", { type: "button", title: "Remove", "aria-label": `Remove the write of ${s.index}:${s.subindex ?? 0}`,
          onclick: () => { list.splice(j, 1); changed(true); removedBanner(`the startup write of ${s.index}:${s.subindex ?? 0}`); } }, "✕"))));
  });
  fs.append(el("table", null, el("thead", null, el("tr", null, thCells(["Object", "Name", "Type", "Value", ""]))),
    el("tbody", null, rows)));
  // Picker: settings from the EDS (or every writable object), or an index
  // typed by hand.
  const filter = el("input", { type: "text", placeholder: "Index, name or note", "aria-label": "Filter SDO objects" });
  filter.value = S.sdoFilter;
  const body = el("tbody");
  const hidden = el("span", { class: "muted" });
  const all = el("input", { type: "checkbox", "aria-label": "Show all writable objects" });
  all.checked = S.sdoShowAll;
  all.addEventListener("change", () => { S.sdoShowAll = all.checked; fill(); });
  const fill = () => {
    const f = S.sdoFilter.toLowerCase();
    const writable = ((eds && eds.objects) || []).filter((o) => o.writable && o.type && !NO_STORE_WRITE[num(o.index)]);
    const why = { signal: 0, plugin: 0, listed: 0 };
    const shown = S.sdoShowAll ? writable : writable.filter((o) => {
      const r = sdoHiddenReason(list, o);
      if (r) why[r]++;
      return !r;
    });
    const parts = [];
    if (why.signal) parts.push(`${why.signal} process signal${why.signal === 1 ? "" : "s"} (PDO-mappable, map them in a PDO)`);
    if (why.plugin) parts.push(`${why.plugin} ${targetText("sdo_hidden").replace(/^communication objects/, why.plugin === 1 ? "communication object" : "communication objects")}`);
    if (why.listed) parts.push(`${why.listed} already in the list`);
    hidden.textContent = parts.length ? "Hidden: " + parts.join(", ") + "." : "";
    body.replaceChildren(...shown
      .filter((o) => objectMatches(o, f, noteOfObj(o)))
      .slice(0, 400)
      .map((o) => el("tr", null, el("td", null, `${o.index}:${o.subindex}`), el("td", null, o.name, noteLine(noteOfObj(o))),
        el("td", null, o.type || "?"), el("td", null, o.access), el("td", null, withMeaning(noteOfObj(o), o.default)),
        el("td", null, el("button", { type: "button", dataset: { sdo: `${o.index}:${o.subindex}` },
          onclick: () => addSdo(i, o.index, o.subindex) }, "Add")))));
  };
  filter.addEventListener("input", () => { S.sdoFilter = filter.value; fill(); });
  fill();
  const idx = el("input", { type: "text", placeholder: "0x2100", "aria-label": "SDO index" });
  const sub = el("input", { type: "text", placeholder: "0", "aria-label": "SDO subindex" });
  fs.append(el("div", { class: "toolbar" }, filter, el("label", { class: "check" }, all, " Show all writable objects"),
    byHand(idx, sub, el("button", { type: "button", onclick: () => addSdo(i, idx.value.trim(), sub.value.trim() || "0") }, "Add write"))),
  hidden,
  el("div", { class: "objects", dataset: { box: "sdo_picker", boxLabel: "the Startup SDO writes picker" } }, el("table", null,
    el("thead", null, el("tr", null, thCells(["Object", "Name", "Type", "Access", "Default", ""]))), body)));
  return collapsible("sdo", i, "Startup SDO writes", list.length, fs, summaryAdd("sdo", filter));
}

// The add action in a collapsed section's summary: opens it on the picker.
function summaryAdd(key, filter) {
  return el("button", { type: "button", class: "small", dataset: { sectionAdd: key }, onclick: (e) => {
    e.preventDefault();
    e.currentTarget.closest(".section-wrap").querySelector("details.section").open = true;
    filter.focus();
  } }, "Add…");
}

// An object picker's "or by hand" index, subindex and button, kept together.
function byHand(idx, sub, button) {
  idx.classList.add("index");
  sub.classList.add("subindex");
  return el("span", { class: "by-hand" }, el("span", { class: "muted" }, "or by hand:"), idx, sub, button);
}

// SDO variables: objects moved between the node and the program over SDO
// while the network runs.
function renderSdoVars(i, eds) {
  const n = S.config.nodes[i];
  const list = n.sdo_variables || [];
  const nb = notesOf(n.eds);
  const noteOfObj = (o) => noteFor(nb, n.eds, o.index, o.subindex, !!o.var);
  const fs = el("fieldset", { dataset: { path: `nodes[${i}].sdo_variables` } }, el("legend", { class: "visually-hidden" }, "SDO variables"),
    el("p", { class: "muted" }, "Objects read into or written from the program over SDO while the network runs. A read lands after each boot, every period and on each trigger edge. A write without a trigger is owned by the program: sent after each boot and whenever the value changes. With a trigger it is sent only on each rising edge. The status byte reads 0 idle, 1 busy, 2 done, 3 aborted (see the abort code), 4 node not available."));
  // One block per variable that wraps to the view's width: object, name,
  // type, direction and remove on the first line, the labelled locations
  // and times below, the messages under it.
  const loc = (vp, label, key, direction, type, placeholder) => {
    const input = field("", vp + "." + key, "text", { placeholder }).querySelector("input");
    input.setAttribute("aria-label", label);
    const btn = el("button", { type: "button", dataset: { suggest: direction }, onclick: async () => {
      const r = await api("POST", "/api/place", { config: fileConfig(), network: S.net, node: i, direction, type });
      setPath(vp + "." + key, r.location);
      render();
    } }, "Suggest");
    return el("label", { class: "loc" }, label, el("span", { class: "row" }, input, btn),
      el("span", { class: "field-msg", dataset: { for: vp + "." + key } }), declNote(vp + "." + key));
  };
  const numField = (vp, label, key, placeholder) => {
    const input = field("", vp + "." + key, "int", { placeholder }).querySelector("input");
    input.setAttribute("aria-label", label);
    return el("label", { class: "num" }, label, input, el("span", { class: "field-msg", dataset: { for: vp + "." + key } }));
  };
  const blocks = list.map((v, j) => {
    const vp = `nodes[${i}].sdo_variables[${j}]`;
    const info = objectInfo(eds, v.index, v.subindex);
    const read = v.direction !== "write";
    const name = field("", vp + ".name", "text", { placeholder: info ? info.name : "name" }).querySelector("input");
    name.setAttribute("aria-label", "Name");
    return el("div", { class: "sdo-var", dataset: { path: vp } },
      el("div", { class: "sdo-var-head" },
        el("code", null, `${v.index}:${v.subindex ?? 0}`),
        el("label", { class: "name" }, "Name", name),
        el("span", null, v.type || "?"),
        el("span", { class: "tag" }, read ? "read" : "write"),
        el("span", { class: "spacer" }),
        el("button", { type: "button", title: "Remove", "aria-label": `Remove the SDO variable ${v.name || `${v.index}:${v.subindex ?? 0}`}`,
          onclick: () => {
            list.splice(j, 1);
            if (!list.length) delete n.sdo_variables;
            changed(true);
            removedBanner(`the SDO variable ${v.name || `${v.index}:${v.subindex ?? 0}`}`);
          } }, "✕")),
      info ? noteLine(noteOfObj(info)) : null,
      el("div", { class: "sdo-var-fields" },
        loc(vp, "Value", "iec_location", read ? "sdo_read" : "sdo_write", v.type, read ? "%I…" : "%Q…"),
        read ? numField(vp, "Period (ms)", "period_ms", "none") : el("label", { class: "num" }, "Period", el("span", { class: "muted" }, "on change")),
        loc(vp, "Trigger", "trigger_location", "sdo_trigger", null, "%QX…"),
        loc(vp, "Status", "status_location", "sdo_status", null, "%IB…"),
        loc(vp, "Abort code", "abort_code_location", "sdo_abort", null, "%ID…"),
        numField(vp, "Timeout (ms)", "timeout_ms", "1000")),
      el("div", { class: "field-msg", dataset: { for: vp } }));
  });
  if (blocks.length) fs.append(el("div", { class: "sdo-vars" }, blocks));
  // Picker: readable objects for a read entry, writable ones for a write.
  const dirSel = el("select", { "aria-label": "SDO variable direction" },
    el("option", { value: "read" }, "Read (node to PLC)"), el("option", { value: "write" }, "Write (PLC to node)"));
  dirSel.value = S.varDirection;
  dirSel.addEventListener("change", () => { S.varDirection = dirSel.value; fill(); });
  const filter = el("input", { type: "text", placeholder: "Index, name or note", "aria-label": "Filter SDO variable objects" });
  filter.value = S.varFilter;
  const body = el("tbody");
  const fill = () => {
    const f = S.varFilter.toLowerCase();
    const write = S.varDirection === "write";
    body.replaceChildren(...((eds && eds.objects) || [])
      .filter((o) => o.type && (write ? o.writable : o.readable))
      .filter((o) => objectMatches(o, f, noteOfObj(o)))
      .slice(0, 400)
      .map((o) => el("tr", null, el("td", null, `${o.index}:${o.subindex}`), el("td", null, o.name, noteLine(noteOfObj(o))),
        el("td", null, o.type), el("td", null, o.access),
        el("td", null, write && pluginObject(o.index) ? el("span", { class: "field-msg warning" }, "set by the plugin") : null),
        el("td", null, el("button", { type: "button", dataset: { sdoVar: `${o.index}:${o.subindex}` },
          onclick: () => addSdoVar(i, o.index, o.subindex, S.varDirection) }, "Add")))));
  };
  filter.addEventListener("input", () => { S.varFilter = filter.value; fill(); });
  fill();
  const idx = el("input", { type: "text", placeholder: "0x2100", "aria-label": "SDO variable index" });
  const sub = el("input", { type: "text", placeholder: "0", "aria-label": "SDO variable subindex" });
  fs.append(el("div", { class: "toolbar" }, dirSel, filter, byHand(idx, sub,
    el("button", { type: "button", onclick: () => addSdoVar(i, idx.value.trim(), sub.value.trim() || "0", S.varDirection) },
      "Add variable"))),
  el("div", { class: "objects", dataset: { box: "sdo_var_picker", boxLabel: "the SDO variables picker" } }, el("table", null,
    el("thead", null, el("tr", null, thCells(["Object", "Name", "Type", "Access", "Note", ""]))), body)));
  return collapsible("sdo_variables", i, "SDO variables", list.length, fs, summaryAdd("sdo_variables", filter));
}

// Communication objects the plugin writes itself from the node's settings
// (SYNC, guarding, heartbeat, PDOs, NMT startup).
// What to say before an online write to an object: the plugin's own
// objects on a master network; on a slave network the objects its master
// configures and the objects bound in the draft.
function ownWriteWarnings(index, sub) {
  const out = [];
  if (onlineIsSlave()) {
    if (pluginObject(index)) out.push(`The network's master may write ${hex4(index)} when it configures this device; your value lasts until then.`);
    const bound = slaveBindText(index, sub);
    if (bound) out.push(`${hex4(index)}:${sub} is bound to ${bound}; whatever writes it there (the program, the master's PDOs or the gateway) overwrites your value.`);
  } else {
    if (pluginObject(index)) out.push(`The plugin configures ${hex4(index)} itself when the node boots; your value lasts until the next boot.`);
    const e = odEntryCached(S.onlineNode, index, sub);
    const rx = e ? (e.pdo || []).filter((m) => /^RPDO/.test(m.pdo)) : [];
    if (rx.length) out.push(`${hex4(index)}:${sub} is in ${rx.map(odPdoText).join(" and ")}: the PLC program writes it through the PDO every cycle, so your value is overwritten at once.`);
  }
  return out;
}

function pluginObject(index) {
  const ix = num(index);
  return (ix >= 0x1005 && ix <= 0x1007) || ix === 0x100C || ix === 0x100D || (ix >= 0x1014 && ix <= 0x1017) ||
    (ix >= 0x1400 && ix <= 0x1BFF) || ix === 0x1F80;
}

// Why the startup SDO picker hides an object by default, or null.
function sdoHiddenReason(list, o) {
  if (list.some((s) => sameObject(s.index, s.subindex, o.index, o.subindex))) return "listed";
  if (o.directions && o.directions.length) return "signal";
  if (pluginObject(o.index)) return "plugin";
  return null;
}

// A cyclic CiA 402 axis's cycle time line (fCycleTime) comes from the
// program's task interval, which this page does not know: the user gives it.
function cyclicInterval() {
  const cyclic = S.model.networks.some((net) => (net.nodes || []).some((n) => n.axis && n.axis.cyclic === true));
  if (!cyclic) return null;
  const input = el("input", { type: "text", spellcheck: "false", id: "task-interval", placeholder: "T#20ms",
    "aria-label": "Task interval" });
  // A check that lands while the user types renders the view again: keep
  // the text not yet committed (no change event yet) and the focus.
  const typing = S.taskIntervalTyping;
  input.value = typing ? typing.value : S.taskInterval || "";
  if (typing) setTimeout(() => { input.focus(); input.setSelectionRange(typing.caret, typing.caret); });
  S.taskIntervalTyping = null;
  input.addEventListener("input", () => { S.taskIntervalDirty = true; });
  input.addEventListener("change", () => {
    S.taskIntervalDirty = false;
    S.taskInterval = input.value.trim();
    scheduleCheck();
  });
  return el("div", { class: "grid" }, el("label", null, "Task interval", input,
    hint("The interval of the editor task that runs the program, for the cyclic axis's fCycleTime line. Change the line with the interval. Empty: T#20ms, the project generator's default."),
    el("span", { class: "field-msg", dataset: { for: "task_interval" } })));
}

function renderDeclarations(view) {
  const decls = (S.check && S.check.declarations) || [];
  const block = (S.check && S.check.block) || "";
  const ta = el("textarea", { class: "block", readonly: true, "aria-label": "Declarations block" });
  ta.value = block || "(every mapped entry is already declared in the project)";
  view.append(
    el("h2", null, "Variable declarations"),
    el("p", { class: "muted" }, "Paste this block into the VAR block of the program that uses these variables, not into a global variable list: " +
      "located variables there do not reach the runtime. You can also type the rows below into the program's variables table. " +
      "Entries the project already declares at the same location are left out."),
    el("div", { class: "toolbar" }, el("button", { type: "button", class: "primary", id: "copy-block", onclick: async () => {
      try { await navigator.clipboard.writeText(block); banner("Copied the declarations block."); }
      catch (e) { ta.select(); document.execCommand("copy"); banner("Copied the declarations block."); }
    } }, "Copy block")),
    ta,
    cyclicInterval() || "",
    declTable(decls));
}

// The declarations table: a check mark for an entry the project declares
// under the same name, the project's name only when it differs; "Only
// missing" leaves out the declared ones.
function declTable(decls) {
  const only = el("input", { type: "checkbox", dataset: { declMissing: "" }, checked: !!S.declOnlyMissing,
    onchange: () => { S.declOnlyMissing = only.checked; fill(); } });
  const body = el("tbody");
  const fill = () => {
    const rows = S.declOnlyMissing ? decls.filter((d) => !d.declared_as) : decls;
    body.replaceChildren(...rows.map((d) => el("tr", null, el("td", null, d.name), el("td", null, d.location), el("td", null, d.type),
      el("td", { dataset: { declState: d.declared_as ? (d.declared_as === d.name ? "same" : "other") : "missing" } },
        !d.declared_as ? "not yet"
          : d.declared_as === d.name ? el("span", { title: "Declared in the project under this name" }, "\u2713", el("span", { class: "visually-hidden" }, " declared"))
          : "declared as " + d.declared_as))));
    if (!rows.length) body.append(el("tr", null, el("td", { colspan: 4, class: "muted", dataset: { declEmpty: "" } },
      decls.length ? "Every entry is declared in the project." : "No mapped entries yet.")));
  };
  fill();
  return el("div", null,
    el("label", { class: "check" }, only, " Only missing"),
    el("table", { dataset: { declTable: "" } }, el("thead", null, el("tr", null, thCells(["Name", "Location", "Type", "In the project"]))), body));
}

// ---------------------------------------------------------------------------
// Online access: the diagnostics channel of the plugin on the runtime. The
// token stays on this PC (server.py keeps it in its settings); the config
// holds only its SHA-256. Every runtime request goes through /api/online/*,
// and only while the online view or the scan page is open.

const DIAG_PORT = 7531;
const NODE_STATES = { 0: "no contact", 4: "STOPPED", 5: "OPERATIONAL", 127: "PRE-OPERATIONAL" };
const BUS_STATES = { 0: "no bus", 1: "error-active", 2: "error-warning", 3: "error-passive", 4: "bus-off" };
const SDO_TYPES = ["BOOLEAN", "INTEGER8", "INTEGER16", "INTEGER24", "INTEGER32", "INTEGER64", "UNSIGNED8",
  "UNSIGNED16", "UNSIGNED24", "UNSIGNED32", "UNSIGNED64", "REAL32", "REAL64", "VISIBLE_STRING", "OCTET_STRING",
  "UNICODE_STRING", "DOMAIN"];
// "Copy as ST call": a CO_SDO_* block instance and its call (spec
// canopen-configurator, Copy as ST call; the blocks are the canworks
// library, docs/plc-sdo.md).
const ST_INT_TYPES = { BOOLEAN: "BOOL", INTEGER8: "SINT", INTEGER16: "INT", INTEGER24: "DINT", INTEGER32: "DINT",
  INTEGER40: "LINT", INTEGER48: "LINT", INTEGER56: "LINT", INTEGER64: "LINT", UNSIGNED8: "USINT", UNSIGNED16: "UINT",
  UNSIGNED24: "UDINT", UNSIGNED32: "UDINT", UNSIGNED40: "ULINT", UNSIGNED48: "ULINT", UNSIGNED56: "ULINT",
  UNSIGNED64: "ULINT" };
function stBlock(type, write) {
  const kind = type === "REAL32" || type === "REAL64" ? "_REAL" : type === "VISIBLE_STRING" ? "_STRING"
    : type === "OCTET_STRING" || type === "DOMAIN" ? "_BYTES" : "";
  return (write ? "CO_SDO_WRITE" : "CO_SDO_READ") + kind;
}
// With several networks: the online network's number (its place in the
// runtime's list, which is the config's order) and name; null with one.
function stNetwork() {
  const name = onlineNetwork();
  if (name === null) return null;
  const runtime = S.runtimeNets || [];
  let i = runtime.findIndex((n) => n.name === name);
  if (i < 0) i = S.model.networks.findIndex((n) => netName(n) === name);
  return i < 0 ? null : { index: i, name };
}
function stCall(node, index, subindex, type, write, net = stNetwork()) {
  const block = stBlock(type, write);
  const ix = index.toString(16).toUpperCase().padStart(4, "0");
  const inst = `${write ? "wr" : "rd"}_${net ? net.name + "_" : ""}n${node}_${ix}_${subindex}`;
  const iec = ST_INT_TYPES[type];
  const lines = [`VAR`, `  ${inst} : ${block};`];
  if (block.endsWith("_BYTES")) lines.push(`  ${inst}_buf : ARRAY[0..1023] OF BYTE;`);
  lines.push(`END_VAR`, ``);
  lines.push(`(* EXECUTE: a rising edge starts the transfer; FALSE clears DONE and ERROR. *)`);
  const args = [`EXECUTE := ${inst}_go`, ...(net ? [`NETWORK := ${net.index} (* ${net.name} *)`] : []), `NODE := ${node}`, `INDEX := 16#${ix}`, `SUBINDEX := ${subindex}`];
  if (block === "CO_SDO_WRITE") args.push(`DATA := ${iec ? `${iec}_TO_LWORD(value)` : "value"}`, `SIZE := 0`);
  if (block === "CO_SDO_WRITE_REAL") args.push(`VALUE := value`, `SIZE := 0`);
  if (block === "CO_SDO_WRITE_STRING") args.push(`VALUE := text`);
  if (block === "CO_SDO_WRITE_BYTES") args.push(`BUFFER := ${inst}_buf`, `SIZE := 0 (* bytes to send *)`);
  if (block === "CO_SDO_READ_BYTES") args.push(`BUFFER := ${inst}_buf`);
  lines.splice(2, 0, `  ${inst}_go : BOOL;`);
  lines.push(`${inst}(${args.join(", ")});`);
  lines.push(`IF ${inst}.DONE THEN`);
  if (!write) {
    const result = block === "CO_SDO_READ" ? (iec ? `LWORD_TO_${iec}(${inst}.DATA)` : `${inst}.DATA (* SIZE bytes *)`)
      : block === "CO_SDO_READ_BYTES" ? `${inst}_buf (* ${inst}.SIZE bytes *)` : `${inst}.VALUE`;
    lines.push(`  (* value := ${result}; *)`);
  } else lines.push(`  (* written *)`);
  lines.push(`ELSIF ${inst}.ERROR THEN`, `  (* ${inst}.ERROR_ID, ${inst}.ABORT_CODE *)`, `END_IF;`, ``);
  return lines.join("\n");
}
async function copyText(text) {
  try { await navigator.clipboard.writeText(text); }
  catch (e) {
    const ta = el("textarea", null);
    ta.value = text;
    document.body.append(ta);
    ta.select();
    document.execCommand("copy");
    ta.remove();
  }
}
// Copies the read or write call, asking which when both apply.
async function copyStCall(node, index, subindex, type, readable, writable) {
  let write = !readable && writable;
  if (readable && writable) {
    const v = await modal(`Copy the Structured Text call for ${hex4(index)}:${subindex} of node ${node}:`,
      [["read", "Read call (" + stBlock(type, false) + ")", true], ["write", "Write call (" + stBlock(type, true) + ")"], ["cancel", "Cancel"]]);
    if (v !== "read" && v !== "write") return;
    write = v === "write";
  } else if (!readable && !writable) return;
  const text = stCall(node, index, subindex, type, write);
  await copyText(text);
  banner(`Copied the ${stBlock(type, write)} call. Enable the canworks library in the editor project to use it.`);
}
// "Copy as ST call" for NMT: a CO_NMT instance and its call for a node and a
// CiA 301 command code, or a CO_NETWORK_START call (spec canopen-configurator,
// Copy NMT calls as ST; the blocks are in the canworks library, docs/plc-nmt.md).
const NMT_CODES = { start: [1, "START"], stop: [2, "STOP"], preop: [128, "ENTER PRE-OPERATIONAL"],
  reset: [129, "RESET NODE"], "reset-comm": [130, "RESET COMMUNICATION"] };
function stNmtCall(node, command, net = stNetwork()) {
  const [code, name] = NMT_CODES[command];
  const inst = `nmt_${net ? net.name + "_" : ""}n${node}_${command.replace("-", "_")}`;
  const args = [`EXECUTE := ${inst}_go`, ...(net ? [`NETWORK := ${net.index} (* ${net.name} *)`] : []),
    `NODE := ${node}`, `COMMAND := ${code} (* ${name} *)`];
  return [`VAR`, `  ${inst} : CO_NMT;`, `  ${inst}_go : BOOL;`, `END_VAR`, ``,
    `(* EXECUTE: a rising edge sends the command; FALSE clears DONE and ERROR. *)`,
    `${inst}(${args.join(", ")});`,
    `IF ${inst}.ERROR THEN`, `  (* ${inst}.ERROR_ID *)`, `END_IF;`, ``].join("\n");
}
// The editor's network for CO_NETWORK_START: its number and name with
// several networks, null with one.
function stEditNetwork() {
  if (!several()) return null;
  return { index: S.net || 0, name: netName(S.config) || `net${(S.net || 0) + 1}` };
}
function stNetworkStartCall(net = stEditNetwork()) {
  const inst = `net_start${net ? "_" + net.name : ""}`;
  const args = [`EXECUTE := ${inst}_go`, ...(net ? [`NETWORK := ${net.index} (* ${net.name} *)`] : []),
    `TIMEOUT := T#0s (* no limit *)`];
  return [`VAR`, `  ${inst} : CO_NETWORK_START;`, `  ${inst}_go : BOOL; (* TRUE once the machine is ready *)`, `END_VAR`, ``,
    `(* The master goes OPERATIONAL (PDOs run) once every mandatory node has booted. *)`,
    `${inst}(${args.join(", ")});`,
    `IF ${inst}.ERROR THEN`, `  (* ${inst}.ERROR_ID: 2 timeout, 9 the master is STOPPED *)`, `END_IF;`, ``].join("\n");
}
const NO_ST_SLAVE = "The program's SDO blocks address nodes of a master network; on a slave network the program has the bound locations instead.";
const RUNTIME_NO_CHANGES = "Online changes are not allowed in this configuration (turn on \"Allow changes\" under Online access, then upload).";
const ADAPTER_NO_CHANGES = "Changes are off for this USB adapter connection (press Unlock… in the connection bar).";
// An adapter on another machine (canopen-remote-adapter): the lock names its host.
function remoteNoChanges(host) {
  return `Changes are off for this connection to the adapter on ${host} (press Unlock… in the connection bar).`;
}
let NO_CHANGES = RUNTIME_NO_CHANGES;

function hex8(n) { return "0x" + (Number(n) >>> 0).toString(16).toUpperCase().padStart(8, "0"); }
function stateName(s) { return NODE_STATES[s] || String(s); }
function diagConfig() { return S.model ? S.model.diagnostics : undefined; }
function diagPort() { const d = diagConfig(); return d && Number.isInteger(d.port) ? d.port : DIAG_PORT; }

// A token_verifier (SCRAM-SHA-256, a fresh salt) for this PC's token.
async function verifierForToken() {
  return (await api("POST", "/api/online/token", { action: "verifier" })).token_verifier;
}

// The config's token as the server checks it: token_verifier, or the former token_sha256.
function configToken(d) {
  return { token_verifier: d && typeof d.token_verifier === "string" ? d.token_verifier : "",
    token_sha256: d && typeof d.token_sha256 === "string" ? d.token_sha256 : "" };
}

// S.online: { token, host, eds_library, tokenOk } from /api/online/settings.
async function loadOnlineSettings() {
  try {
    S.online = await api("GET", "/api/online/settings");
  } catch (e) {
    S.online = { token: null, host: "", eds_library: "" };
  }
  await checkToken();
}

async function checkToken() {
  const d = diagConfig();
  S.online.tokenOk = false;
  if (!S.online.token || !d || (!d.token_verifier && !d.token_sha256)) return;
  try {
    S.online.tokenOk = !!(await api("POST", "/api/online/token", Object.assign({ action: "check" }, configToken(d)))).match;
  } catch (e) { /* shown as "does not match" */ }
}

// A config from before the encrypted channel (token_sha256): a token_verifier
// for the same token, so tokens copied to other PCs keep working.
async function upgradeToken() {
  try {
    const v = await verifierForToken();
    delete S.model.diagnostics.token_sha256;
    S.model.diagnostics.token_verifier = v;
    await checkToken();
    banner("The token is set for the encrypted channel. Save and upload to use it.");
    changed(true);
  } catch (e) { banner(e.message, true); }
}

async function enableOnline(on) {
  if (!on) {
    const v = await modal("Turn online access off? The runtime closes the diagnostics port after the next upload.",
      [["cancel", "Keep it on"], ["off", "Turn off", { danger: true }]]);
    if (v !== "off") return render();
    delete S.model.diagnostics;
    return changed(true);
  }
  if (S.online.token) {
    S.model.diagnostics = { token_verifier: await verifierForToken() };
  } else {
    const r = await api("POST", "/api/online/token", { action: "generate" });
    S.online = Object.assign(S.online, r);
    S.model.diagnostics = { token_verifier: r.token_verifier };
  }
  await checkToken();
  changed(true);
}

async function newToken() {
  const v = await modal("Make a new access token? The old token stops working once this config is saved and uploaded.",
    [["cancel", "Keep the token"], ["new", "New token", { danger: true }]]);
  if (v !== "new") return;
  const r = await api("POST", "/api/online/token", { action: "generate" });
  S.online = Object.assign(S.online, r);
  delete S.model.diagnostics.token_sha256;
  S.model.diagnostics.token_verifier = r.token_verifier;
  await checkToken();
  changed(true);
}

async function enterToken() {
  const input = el("input", { type: "text", spellcheck: "false", class: "wide", "aria-label": "Access token" });
  const v = await modal("The access token of this project (from the PC that set up online access):",
    [["set", "Use this token", true], ["cancel", "Cancel"]], input);
  if (v !== "set") return false;
  try {
    const d = diagConfig();
    const r = await api("POST", "/api/online/token", Object.assign({ action: "set", token: input.value.trim() },
      configToken(d)));
    S.online = Object.assign(S.online, r);
    await checkToken();
    banner("");
    render();
    return true;
  } catch (e) {
    banner(e.message, true);
    return false;
  }
}

async function copyToken() {
  try { await navigator.clipboard.writeText(S.online.token); banner("Copied the access token."); }
  catch (e) { await modal("The access token:", [["ok", "Close", true]], el("code", null, S.online.token)); }
}

// say: where a dialog shows the error instead of the page bar.
async function saveHost(host, say) {
  try {
    S.online = Object.assign(S.online, await api("POST", "/api/online/settings", { host }));
    if (!say) banner("");
    return true;
  } catch (e) { if (say) say(e.message); else banner(e.message, true); return false; }
}

// The runtime host on the Project page: typed, or "local" for the local
// local runtime. The connect panel has the combobox (runtimeHost).
function hostField() {
  const input = el("input", { type: "text", spellcheck: "false", placeholder: "for example plc.local", "aria-label": "Runtime host",
    dataset: { online: "host" } });
  input.value = S.online.host || "";
  input.addEventListener("change", () => saveHost(input.value.trim()));
  const local = el("button", { type: "button", class: "small", dataset: { online: "local" },
    title: "The local runtime started with canworks-local-runtime start" }, "Local runtime");
  local.addEventListener("click", () => { input.value = "local"; saveHost("local"); });
  return el("label", null, "Runtime host", input, local,
    hint(`The PLC running this config, as HOST or HOST:PORT (port ${diagPort()} when not given), or "local" for the local runtime (canworks-local-runtime). Kept on this PC, not in the project.`));
}

// The connect panel's runtime host (canopen-configurator, Connect panel):
// one combobox. Its list has the runtimes that answer on the local network,
// by name and address, the ones this PC remembers, by name, and the local
// local runtime; any host can be typed. A discovered runtime fills its
// address, a remembered one its name, which connects by the automatic path
// choice (the local network first, the remote link when this PC is paired).
let RUNTIME_LIST_ID = 0;
function runtimeHost() {
  const id = "runtime-options-" + (++RUNTIME_LIST_ID);
  const local = () => el("option", { value: "local", dataset: { kind: "local" } }, "Local runtime");
  const list = el("datalist", { id, dataset: { online: "runtime-list" } }, local());
  const input = el("input", { type: "text", spellcheck: "false", placeholder: "pick a runtime or type its host, for example plc.local",
    "aria-label": "Runtime host", list: id, autocomplete: "off", dataset: { online: "host" } });
  input.value = S.online.host || "";
  input.addEventListener("change", () => saveHost(input.value.trim()));
  const status = el("span", { class: "muted", "aria-live": "polite", dataset: { online: "runtime-status" } }, "Looking for runtimes…");
  const fill = async () => {
    status.textContent = "Looking for runtimes…";
    let r;
    try { r = await api("GET", "/api/online/runtimes"); } catch (e) {
      status.textContent = "Finding runtimes is not available.";
      return;
    }
    const found = (r.discovered || []).filter((d) => d.address);
    const mem = r.remembered || [];
    list.replaceChildren(
      ...found.map((d) => el("option", { value: d.address, dataset: { runtime: d.name, kind: "discovered" } }, `${d.name}, on this network`)),
      ...mem.map((m) => el("option", { value: m.name, dataset: { runtime: m.name, kind: "remembered" } },
        "remembered" + (m.hosts.length ? `, ${m.hosts[0]}` : "") + (m.paired ? (m.internet ? ", paired, from other networks" : ", paired") : ""))),
      local());
    const parts = [];
    if (found.length) parts.push(`${found.length} on this network`);
    if (mem.length) parts.push(`${mem.length} remembered`);
    status.textContent = parts.length ? parts.join(", ") + ": pick one from the list." : r.discovery ? "No runtime found on this network." : "Finding runtimes on the network is not available.";
  };
  const refresh = el("button", { type: "button", class: "small", dataset: { online: "runtime-refresh" }, onclick: fill }, "Refresh");
  fill();
  return el("label", null, "Runtime", el("div", { class: "row" }, input, refresh), list, status,
    hint(`A runtime from the list, a host as HOST or HOST:PORT (port ${diagPort()} when not given), or "local" for the local runtime (canworks-local-runtime). Kept on this PC, not in the project.`));
}

// A token typed into the connect panel: kept on this PC when it matches the
// config's verifier. Returns the error text, or "" when it was taken.
async function takeToken(value) {
  try {
    const r = await api("POST", "/api/online/token", Object.assign({ action: "set", token: value }, configToken(diagConfig())));
    S.online = Object.assign(S.online, r);
    await checkToken();
    return S.online.tokenOk ? "" : "The token does not match this config.";
  } catch (e) { return e.message; }
}

// A password field with Show, for a token.
function secretField(attrs) {
  const input = el("input", Object.assign({ type: "password", autocomplete: "off", spellcheck: "false" }, attrs));
  const show = el("button", { type: "button", class: "small", "aria-pressed": "false", onclick: () => {
    const on = input.type === "password";
    input.type = on ? "text" : "password";
    show.setAttribute("aria-pressed", String(on));
  } }, "Show");
  return [input, show];
}

function onlineAccessSettings() {
  const d = diagConfig();
  const on = el("input", { type: "checkbox", dataset: { online: "enable" } });
  on.checked = !!d;
  on.addEventListener("change", () => enableOnline(on.checked));
  const fs = el("fieldset", { dataset: { section: "online" } }, el("legend", null, several() ? "Online access (all networks)" : "Online access"),
    el("p", { class: "muted" }, "Lets this configurator (and canworks-diag) watch the live network from this PC: node states, boot errors, emergencies, SDO values, and a scan of the bus. " + targetText("diag_port")),
    el("div", { class: "check-field" }, el("label", { class: "check" }, on, " Online access (diagnostics channel)")));
  if (!d) return fs;
  const allow = el("input", { type: "checkbox", dataset: { path: "master.diagnostics.allow_changes" } });
  allow.checked = !!d.allow_changes;
  allow.addEventListener("change", async () => {
    if (allow.checked) {
      const v = await modal("Allow changes? Anyone with the token can then write any object of any node and stop or reset nodes.",
        [["allow", "Allow changes", true], ["cancel", "Cancel"]]);
      if (v !== "allow") { allow.checked = false; return; }
    }
    setPath("master.diagnostics.allow_changes", allow.checked ? true : undefined);
    render();
  });
  const old = typeof d.token_sha256 === "string" && !d.token_verifier;
  const tokenState = old
    ? "This config has the former unencrypted token (token_sha256), which the plugin no longer accepts: " +
      (S.online.tokenOk ? "press Upgrade to set the same token for the encrypted channel." : "enter the token or make a new one.")
    : !S.online.token ? "This PC has no token for this project."
      : S.online.tokenOk ? "This PC has the token (it matches the config)."
        : "The token on this PC does not match the token in the config.";
  fs.append(el("div", { class: "grid" },
    field("Port", "master.diagnostics.port", "intstr", { placeholder: String(DIAG_PORT),
      hint: "TCP port on the PLC, 1024-65535. Default: 7531." }),
    field("Bind address", "master.diagnostics.bind", "text", { placeholder: "0.0.0.0",
      hint: "The PLC's address to listen on. 0.0.0.0: all interfaces; give one address to keep the port off other networks." }),
    el("div", { class: "check-field" }, el("label", { class: "check" }, allow, " Allow changes (SDO writes and NMT commands)"),
      hint("Off: read-only. On: anyone with the token can write parameters and stop nodes."),
      d.allow_changes ? el("span", { class: "field-msg warning" }, "Changes are allowed: keep the token secret and the port on a trusted network.") : null),
    hostField()),
  (typeof devHostState === "function" && devHostState()) || "",
  el("div", { class: "toolbar" },
    el("span", { class: S.online.tokenOk && !old ? "ok-text" : "field-msg warning", dataset: { online: "token-state" } }, tokenState),
    old && S.online.tokenOk ? el("button", { type: "button", class: "primary", dataset: { online: "upgrade" }, onclick: upgradeToken }, "Upgrade") : null,
    S.online.token ? el("button", { type: "button", onclick: copyToken }, "Copy token") : null,
    el("button", { type: "button", onclick: enterToken }, "Enter token…"),
    el("button", { type: "button", onclick: newToken }, "New token")),
  remoteLinkSettings(),
  el("p", { class: "muted" }, "Open the Commission workspace once the config with online access is saved and uploaded to the runtime."));
  return fs;
}

// diagnostics.remote_link (design decision 5): the draft's object, {} when absent.
function remoteLink() {
  const d = diagConfig();
  const rl = d ? d.remote_link : undefined;
  return rl && typeof rl === "object" && !Array.isArray(rl) ? rl : {};
}

// Writes remote_link with `values` merged in; the other diagnostics fields
// stay. Defaults are left out (internet off, no relays, no pairing scope),
// and the object as a whole when nothing else is left.
function setRemoteLink(values) {
  const rl = Object.assign({}, remoteLink(), values);
  if (rl.internet !== true) delete rl.internet;
  if (!Array.isArray(rl.relays) || !rl.relays.length) delete rl.relays;
  if (rl.pairing === undefined || rl.pairing === null) delete rl.pairing;
  setPath("master.diagnostics.remote_link", Object.keys(rl).length ? rl : undefined);
}

const RELAY_URL = /^https:\/\/[^\s/?#]+(\/\S*)?$/;

// "Reachable from other networks", its relay list, and the PCs paired with
// the runtime (remote-link; the link service reads remote_link from the
// uploaded config).
function remoteLinkSettings() {
  const rl = remoteLink();
  const internet = el("input", { type: "checkbox", dataset: { path: "master.diagnostics.remote_link.internet", online: "internet" } });
  internet.checked = rl.internet === true;
  internet.addEventListener("change", () => { setRemoteLink({ internet: internet.checked }); render(); });
  const box = el("div", { dataset: { online: "remote-link" } },
    el("div", { class: "check-field" }, el("label", { class: "check" }, internet, " Reachable from other networks"),
      hint("PCs paired with this runtime reach it from any network over the remote link (canworks-link on the device), through a relay when no direct path is found. " +
        "A PC is paired when it connects once on the local network with the token. Off: the link service contacts nothing outside the local network. Default: off.")));
  if (rl.internet === true || (Array.isArray(rl.relays) && rl.relays.length)) {
    const relays = el("textarea", { rows: 3, spellcheck: "false", "aria-label": "Relay URLs",
      placeholder: "one https URL per line", dataset: { path: "master.diagnostics.remote_link.relays", online: "relays" } });
    relays.value = (Array.isArray(rl.relays) ? rl.relays : []).join("\n");
    const msg = el("span", { class: "field-msg warning", dataset: { online: "relays-msg" } });
    const check = (lines) => {
      const bad = lines.filter((u) => !RELAY_URL.test(u));
      msg.textContent = bad.length ? `Relay URLs must use https: ${bad.join(", ")}` : "";
    };
    relays.addEventListener("input", () => {
      const lines = relays.value.split(/\r?\n/).map((s) => s.trim()).filter(Boolean);
      check(lines);
      setRemoteLink({ relays: lines });
    });
    check(Array.isArray(rl.relays) ? rl.relays : []);
    box.append(el("label", { class: "field-block" }, "Relay URLs (optional)", relays,
      hint("One https URL per line, for a relay of your own. Empty: the public relays of the iroh project."), msg));
  }
  box.append(pairedPcsBox());
  return box;
}

// The CiA 309-3 gateway (canopen-cia309-gateway, docs/cia309-gateway.md):
// cia309 at the top level of the file (master.cia309 in a version 1 file).
function cia309Config() { return S.model ? S.model.cia309 : undefined; }

// [[number, network label]] as the plugin numbers them: nets when given
// (several networks), else 1..n in config order.
function cia309Numbering() {
  const g = cia309Config() || {};
  if (several() && g.nets && typeof g.nets === "object" && !Array.isArray(g.nets) && Object.keys(g.nets).length) {
    return Object.entries(g.nets).map(([k, v]) => [Number(k), String(v)]).sort((a, b) => a[0] - b[0]);
  }
  return S.model.networks.map((n, i) => [i + 1, netLabel(n, i)]);
}

function cia309Settings() {
  const g = cia309Config();
  const on = el("input", { type: "checkbox", dataset: { online: "cia309" } });
  on.checked = !!g;
  on.addEventListener("change", () => {
    if (on.checked) S.model.cia309 = { allow_changes: false };
    else delete S.model.cia309;
    changed(true);
  });
  const fs = el("fieldset", { dataset: { section: "cia309" } }, el("legend", null, "CiA 309-3 gateway"),
    el("p", { class: "muted" }, "Standard CiA 309-3 text commands (SDO, NMT, PDO read, LSS) for SCADA systems, test benches and scripts. " +
      "The plain port listens on the PLC's loopback address only; other machines connect through canworks-diag gateway, which logs in with the project's token over the diagnostics channel. Off by default."),
    el("div", { class: "check-field" }, el("label", { class: "check" }, on, " CiA 309-3 gateway")));
  if (!g) return fs;
  const allow = el("input", { type: "checkbox", dataset: { path: "master.cia309.allow_changes" } });
  allow.checked = g.allow_changes === true;
  allow.addEventListener("change", async () => {
    if (allow.checked) {
      const v = await modal("Allow changes through the CiA 309-3 gateway? Programs on the PLC and everyone with the token can then write objects, send NMT commands and run LSS.",
        [["allow", "Allow changes", true], ["cancel", "Cancel"]]);
      if (v !== "allow") { allow.checked = false; return; }
    }
    setPath("master.cia309.allow_changes", allow.checked);
    render();
  });
  const force = el("input", { type: "checkbox", dataset: { path: "master.cia309.allow_force" } });
  force.checked = g.allow_force === true;
  force.addEventListener("change", async () => {
    if (force.checked) {
      const v = await modal("Allow force on running nodes? A standard CiA 309-3 tool can then stop and write nodes the PLC program drives. For test benches only.",
        [["allow", "Allow force", { danger: true }], ["cancel", "Cancel"]]);
      if (v !== "allow") { force.checked = false; return; }
    }
    setPath("master.cia309.allow_force", force.checked ? true : undefined);
    render();
  });
  const numbers = cia309Numbering().map(([n, name]) => `${n} = ${name}`).join(", ");
  fs.append(el("div", { class: "grid" },
    field("Plain port", "master.cia309.port", "intstr", { placeholder: "7533",
      hint: "TCP port on the PLC's loopback address (127.0.0.1), 1024-65535; 0: no plain port, sessions through the diagnostics channel only. Default: 7533." }),
    field("Sessions at a time", "master.cia309.max_clients", "intstr", { placeholder: "4",
      hint: "Gateway sessions, plain and through the diagnostics channel together, 1-16. Default: 4." }),
    field("Idle timeout (s)", "master.cia309.idle_timeout_s", "intstr", { placeholder: "300",
      hint: "A plain-port session that sends no line this long is closed and its place freed, 0-86400; 0: no limit. Default: 300." }),
    el("div", { class: "check-field" }, el("label", { class: "check" }, allow, " Allow changes (SDO downloads, NMT and LSS)"),
      hint("Off: read-only. Default: off.")),
    el("div", { class: "check-field" }, el("label", { class: "check" }, force, " Allow force on running nodes"),
      hint("What the diagnostics channel refuses without force: SDO writes and NMT commands other than start to OPERATIONAL nodes. Default: off."),
      g.allow_force ? el("span", { class: "field-msg warning" }, "Force is allowed: a standard tool can stop nodes the program drives.") : null)),
  el("p", { dataset: { online: "cia309-numbering" } }, "Network numbers: " + numbers));
  if (several()) {
    const nets = g.nets && typeof g.nets === "object" && !Array.isArray(g.nets) ? g.nets : {};
    const grid = el("div", { class: "grid" });
    S.model.networks.forEach((n, i) => {
      const name = netName(n);
      if (!name) return;
      const current = Object.keys(nets).find((k) => nets[k] === name);
      const input = el("input", { type: "text", spellcheck: "false", placeholder: Object.keys(nets).length ? "none" : String(i + 1),
        "aria-label": `CiA 309 number of ${name}`, dataset: { online: "cia309-net", net: name } });
      input.value = current || "";
      input.addEventListener("change", () => {
        const next = Object.assign({}, nets);
        for (const k of Object.keys(next)) if (next[k] === name) delete next[k];
        const t = input.value.trim();
        if (t) next[t] = name;
        setPath("master.cia309.nets", Object.keys(next).length ? next : undefined);
        render();
      });
      grid.append(el("label", null, `Number of ${name}`, input));
    });
    fs.append(el("p", { class: "muted" }, "Explicit network numbers (optional, 1-127): leave all empty to number the networks in file order."), grid,
      el("span", { class: "field-msg", dataset: { for: "master.cia309.nets" } }));
  }
  fs.append(el("span", { class: "field-msg", dataset: { for: "master.cia309.bind" } }),
    el("p", { class: "muted" }, diagConfig()
      ? "From another machine: canworks-diag --runtime HOST gateway --listen, then point the CiA 309-3 tool at 127.0.0.1:7533 on that PC."
      : "Without online access only programs on the PLC itself reach the gateway; turn on online access for canworks-diag gateway."));
  return fs;
}
// The PCs paired with the runtime of the online access settings, with
// Remove. Listed on request (the link's manage stream, with this PC's
// token): the editing views open no connection by themselves.
function pairedPcsBox() {
  const box = el("div", { dataset: { online: "paired" } });
  const mem = S.online.remembered;
  if (!S.online.token || !S.online.tokenOk || !S.online.host) return box;
  if (!mem || !mem.link) {
    box.append(el("p", { class: "muted", dataset: { online: "paired-none" } },
      "Paired PCs: connect to this runtime once on its local network with the token, and this PC pairs itself for the remote link."));
    return box;
  }
  const out = el("div", { dataset: { online: "paired-list" }, "aria-live": "polite" });
  const show = (data) => {
    S.pairedPcs = { host: S.online.host, data };
    if (data.error) { put(out, notice("warning", data.error)); return; }
    const when = (t) => (Number.isFinite(t) && t > 0 ? new Date(t * 1000).toLocaleString() : "never");
    put(out, el("table", { class: "scan" },
      el("thead", null, el("tr", null, thCells(["PC", "Link ID", "Paired", "Last seen", "Paired over", ""]))),
      el("tbody", null, data.pcs.length ? data.pcs.map((p) => el("tr", { dataset: { pairedPc: p.id } },
        el("td", null, (p.name || "-") + (p.id === data.you ? " (this PC)" : "")),
        el("td", null, el("code", { title: p.id }, String(p.id).slice(0, 10) + "…")),
        el("td", null, when(p.paired)), el("td", null, when(p.last_seen)), el("td", null, p.via || "-"),
        el("td", null, el("button", { type: "button", class: "small danger", dataset: { online: "remove-pc" },
          onclick: (e) => removePc(e.currentTarget, p, data.you, load) }, "Remove")))) :
        [el("tr", null, el("td", { colspan: 6, class: "muted" }, "No PC is paired."))])));
  };
  const load = async (button) => {
    const run = async () => {
      try { show(await api("POST", "/api/online/paired_pcs", {})); }
      catch (e) { show({ error: e.message }); }
    };
    return button ? busy(button, "Listing…", run) : run();
  };
  const list = el("button", { type: "button", dataset: { online: "paired-show" }, onclick: (e) => load(e.currentTarget) },
    S.pairedPcs && S.pairedPcs.host === S.online.host ? "Refresh paired PCs" : "Show paired PCs");
  box.append(el("div", { class: "toolbar" }, el("span", null, `PCs paired with ${mem.name}`), list), out);
  if (S.pairedPcs && S.pairedPcs.host === S.online.host) show(S.pairedPcs.data);
  return box;
}

async function removePc(button, p, you, reload) {
  const me = p.id === you;
  const v = await modal(me
    ? `Remove this PC from ${S.online.remembered.name}? It can no longer reach the runtime from other networks until it connects once on the local network again.`
    : `Remove ${p.name || "this PC"}? Its open sessions end now, and it can no longer reach the runtime over the remote link.`,
  [["cancel", "Keep it"], ["remove", "Remove", { danger: true }]]);
  if (v !== "remove") return;
  await busy(button, "Removing…", async () => {
    try {
      await api("POST", "/api/online/remove_pc", { id: p.id });
      banner(`Removed ${p.name || "the PC"} from the paired PCs.`);
    } catch (e) { banner(e.message, true); }
  });
  await reload();
}

// ---------------------------------------------------------------------------
// The Commission Nodes view

// Stops the online view's own timers. The connection stays open until
// Disconnect (connection.js); a view change never closes it.
function stopOnline() {
  clearTimeout(S.onlineTimer);
  S.onlineTimer = null;
  S.onlineSeq = (S.onlineSeq || 0) + 1;
  clearTimeout(S.scanTimer);
}


async function saveOnline(values) {
  try {
    S.online = Object.assign(S.online, await api("POST", "/api/online/settings", values));
    banner("");
    return true;
  } catch (e) { banner(e.message, true); return false; }
}

// The Commission workspace's Nodes page with a config: the runtime's bus,
// master and nodes. The connection is made in the connect panel and shown in
// the connection bar; the page shows the session (plugin, protocol, notes).
function renderOnline(view) {
  view.append(el("h2", { dataset: { onlinePart: "net" } }, "Nodes"));
  // An adapter on another machine needs no online access in the config.
  if (!connAdapter() && !diagConfig()) {
    view.append(notice("info", ["Online access is off for this config. Turn it on in Configure → ",
      el("a", { href: "#", class: "target", onclick: (e) => { e.preventDefault(); switchWorkspace("configure"); showView("project"); } }, "Project → Online access"),
      ", save, and upload the program to the runtime."], { live: false, dataset: { online: "access-off" } }));
    return;
  }
  if (!connEnsure()) {
    view.append(nodesNotConnected());
    return;
  }
  const conn = noticeSlot({ id: "online-conn", "aria-live": "polite" });
  stateBars(conn, "info", "Connecting to " + (connRemote() ? "the adapter server " + S.online.remote_host : S.online.host) + "…");
  view.append(conn,
    el("div", { dataset: { onlinePart: "net" } },
      onlineIsSlave() ? null : nodesToolbar(),
      el("div", { id: "online-live" }),
      el("div", { id: "online-raw" }),
      el("div", { id: "online-lss" })),
    el("div", { id: "online-node", hidden: true }));
  S.lssAllow = undefined;
  S.onlineOpen = true;
  // The last answer at once, when it is about the network shown.
  const last = S.onlineLast;
  if (last && !CONN.error && (!last.network || last.network === onlineNetwork())) onlineApply(last, null);
  connStart();
  onlineLayout();
  if (S.onlineNode) renderOnlineNode();
}

// The views that poll the connection's status.
function onlineViews() { return S.state && S.state.commission ? ["online", "nodes"] : ["online"]; }

// The node panel's controls that send to the device (NMT, Read, Write): off
// while the connection is lost, as they were once it answers again.
const NODE_TALK = ["[data-nmt]", "read", "write", "od-read", "od-read-object", "od-read-all", "od-any-read", "od-any-write",
  "od-write", "od-edit"].map((k) => (k.startsWith("[") ? k : `[data-online="${k}"]`)).join(", ");
const LOST_TEXT = "The connection is lost: nothing can be sent until the runtime answers again.";
function nodeTalk(box, on) {
  if (on) {
    for (const b of box.querySelectorAll("[data-lost]")) {
      const [title, desc] = JSON.parse(b.dataset.lost);
      delete b.dataset.lost;
      b.disabled = false;
      if (title) b.title = title; else b.removeAttribute("title");
      if (desc) b.setAttribute("aria-description", desc); else b.removeAttribute("aria-description");
    }
    return;
  }
  for (const b of box.querySelectorAll(NODE_TALK)) {
    if (b.disabled || b.dataset.lost) continue;
    b.dataset.lost = JSON.stringify([b.getAttribute("title"), b.getAttribute("aria-description")]);
    const had = document.activeElement === b;
    b.disabled = true;
    b.title = LOST_TEXT;
    b.setAttribute("aria-description", LOST_TEXT);
    if (had) focusNear(b);
  }
}

// A status answer (or the error of the last poll) on the online views; the
// connection's poller (connection.js) calls it.
function onlineApply(r, err) {
  const seq = CONN.seq;
  const conn = $("#online-conn");
  if (!conn) return;
  conn.setAttribute("aria-live", "polite");
  const live = $("#online-live");
  if (err) {
    const why = { closed: "port closed", unreachable: "host unreachable", token: "wrong token", timeout: "no answer",
      protocol: "not a CANopen diagnostics port", refused: "refused" }[err.body && err.body.kind] || "error";
    // Values from before the failure stay, greyed, with their age.
    const age = S.onlineLastAt ? Math.max(0, Math.round((Date.now() - S.onlineLastAt) / 1000)) : null;
    const text = `Not connected (${why}): ${err.message}. Retrying…`;
    stateBars(conn, "error", text, [age !== null && live.childElementCount ? noteBar("warning", `Last data ${age} s ago; the values below are not live.`, { online: "stale-age" }) : null]);
    live.classList.toggle("stale", !!live.childElementCount);
    // The open node's panel too: greyed, with the age of its values.
    const node = $("#online-node");
    const nodeAge = (a) => `Connection lost: the values on this page are from ${a} s ago.`;
    if (node && node.childElementCount) {
      node.classList.add("stale");
      const note = node.querySelector("[data-online=node-stale] .notice-text");
      if (note) note.textContent = nodeAge(age ?? 0);
      else (node.querySelector(":scope > .notice-slot") || node).prepend(noteBar("error", nodeAge(age ?? 0), { online: "node-stale" }));
      nodeTalk(node, false);
    }
    clearTimeout(S.onlineAgeTimer);
    if (age !== null) S.onlineAgeTimer = setTimeout(() => {
      if (seq !== CONN.seq || !onlineViews().includes(S.view)) return;
      const a = document.querySelector("[data-online=stale-age] .notice-text");
      if (a) a.textContent = `Last data ${age + 1} s ago; the values below are not live.`;
      const b = document.querySelector("[data-online=node-stale] .notice-text");
      if (b) b.textContent = nodeAge(age + 1);
    }, 1000);
    return;
  }
  clearTimeout(S.onlineAgeTimer);
  live.classList.remove("stale");
  const nodeBox = $("#online-node");
  if (nodeBox) { nodeBox.classList.remove("stale"); nodeTalk(nodeBox, true); }
  const staleNote = document.querySelector("[data-online=node-stale]");
  if (staleNote) staleNote.remove();
  runtimeNetworks(r);
  const st = r.status;
  NO_CHANGES = !st.local ? RUNTIME_NO_CHANGES : st.remote ? remoteNoChanges(r.remote || st.remote) : ADAPTER_NO_CHANGES;
  if (st.local) {
    localLive(r, conn);
    if (S.onlineNode !== undefined && S.onlineNode !== null && S.onlineNodeAllow !== r.hello.allow_changes) renderOnlineNode();
    if (S.lssAllow !== r.hello.allow_changes) renderLss(r.hello.allow_changes);
    return;
  }
  const notes = [];
  const bus = st.bus || {};
  const protocol = st.protocol === "j1939" ? "J1939" : st.protocol === "none" ? "plain CAN" : "CANopen";
  if (!st.session && st.protocol !== "none") notes.push(noteBar("error", `No ${protocol} session: the CAN interface ${bus.interface || "of this network"} is missing or down on the runtime.`));
  if (r.config === "different") notes.push(noteBar("warning",
    "The runtime runs a different configuration than the saved canworks.json (saved changes not uploaded yet, or another project). " +
    "Upload the saved config with the deploy tool (canworks deploy) or the editor's Build and upload with the CANopen hook.", { online: "fingerprint" }));
  if (S.dirty) notes.push(noteBar("info", "This page has unsaved changes; the runtime runs what was uploaded."));
  if (st.simulation_forced) notes.push(noteBar("warning",
    `This runtime simulates every network${/^local$/i.test((S.online.host || "").trim()) ? " (the local runtime)" : ""}: no CAN interface is used, whatever the adapter settings say.`, { online: "forced" }));
  // The connection line is a live region: it is rewritten only when it changes.
  stateBars(conn, "done", `Connected to ${S.online.host}${r.network ? ", network " + r.network : ""}: plugin ${st.version || "?"}, ${st.protocol === "none" ? "plain CAN network" : protocol + " session"} up ${Math.floor(st.uptime_s || 0)} s, ` +
    (r.hello.allow_changes ? "changes allowed." : "read-only."), notes);
  // This PC was just paired in the background and can reach the runtime from other networks: said once.
  if (r.pairing_note) banner(r.pairing_note, "info");
  rawLive(st);
  if (st.protocol === "none") {
    plainLive(st);
    return;
  }
  if (st.protocol === "j1939") {
    j1939Live(st);
    return;
  }
  if (st.role === "slave") {
    slaveLive(r);
    return;
  }
  const nodeName = (id, fallback) => {
    const n = (onlineConfig().nodes || []).find((x) => num(x.node_id) === id);
    return n && n.name ? n.name : fallback;
  };
  const cmp = comparison(st);
  treeLive(st);
  const rows = (st.nodes || []).map((n) => {
    const boot = n.boot_error ? `error ${n.boot_error}: ${n.boot_error_text || ""}` : n.booted ? "booted" : "not booted";
    const hold = n.hold === "none" ? "" : `held ${n.hold === "stopped" ? "STOPPED" : "PRE-OPERATIONAL"} by ${n.hold_by === "operator" ? "operator" : "the program"}`;
    const em = lastEmcyText(n);
    const vars = (n.sdo_variables || []).map((v) => `${v.name} = ${v.raw}${v.status > 2 ? " (" + sdoStatus(v) + ")" : ""}`).join(", ");
    const stale = (n.pdo_timeouts || []).filter((t) => t.timed_out).map((t) => `TPDO ${t.tpdo} timed out (${t.count})`);
    const c = cmp[n.node_id];
    if (S.nodesFilter && (!c || c.state !== S.nodesFilter)) return null;
    const cn = configNode(n.node_id);
    const sim = cn && nodeSimulated(cn, onlineConfig()) ? el("span", { class: "tag", dataset: { simMark: n.node_id } }, "simulated") : null;
    // The row opens the node on a click; the node ID is the button for the
    // keyboard, as the comparison's own buttons sit in the row too.
    return el("tr", { class: "clickable" + (onlineRowActive(n.node_id) ? " active" : ""), dataset: { onlineNode: n.node_id },
      onclick: (e) => { if (!e.target.closest("button, input, label, a, select")) openOnlineNode(n.node_id); } },
    el("td", null, el("button", { type: "button", class: "small", "aria-label": `Open node ${n.node_id}`, dataset: { openNode: n.node_id },
      onclick: () => openOnlineNode(n.node_id) }, String(n.node_id))), el("td", null, nodeName(n.node_id, n.name), sim ? " " : null, sim,
      ownName(n.node_id, nodeName(n.node_id, n.name))),
    el("td", null, el("span", { class: "state-mark", "aria-hidden": "true" }, ...markIcons(liveMark(n)[0])), stateName(n.state)),
    el("td", { dataset: { onlineStatus: n.node_id } }, n.status ? "TRUE" : "FALSE",
      ...stale.map((t) => el("div", { class: "bad", dataset: { pdoTimeout: n.node_id } }, t))),
    el("td", { class: n.boot_error ? "bad" : null }, boot + (n.retry_pending ? " (retrying)" : ""), hold ? el("div", null, hold) : null),
    el("td", null, em, emcyCobNote(n)), el("td", null, vars),
    el("td", null, lastHeardText(n)), el("td", { title: cn && cn.eds ? "From the config: change it on the node's page in Configure" : null }, cn && cn.eds ? cn.eds : ""),
    compareCell(c, n.node_id));
  }).filter(Boolean);
  // Nodes of the draft the runtime does not run yet (added here, not uploaded).
  const running = new Set((st.nodes || []).map((n) => n.node_id));
  const drafted = (onlineConfig().nodes || []).filter((n) => Number.isInteger(num(n.node_id)) && !running.has(num(n.node_id))).map((n) => {
    const id = num(n.node_id);
    const c = cmp[id];
    if (S.nodesFilter && (!c || c.state !== S.nodesFilter)) return null;
    return el("tr", { dataset: { onlineNode: id, draftNode: id } },
      el("td", null, String(id)), el("td", null, n.name || ""),
      el("td", { class: "muted", colspan: 6 }, S.dirty ? "In this page's changes: save and upload to run it." : "Not run by the runtime yet: upload the saved config to run it."),
      el("td", null, n.eds || ""), compareCell(c, id));
  }).filter(Boolean);
  const extra = drafted.concat(notInConfigRows(cmp, 10).filter((r) => !S.nodesFilter || S.nodesFilter === "not_in_config"));
  patchLive($("#online-live"), [
    el("table", { class: "online-bus" }, el("tbody", null,
      el("tr", null, el("th", null, "Bus"), el("td", { dataset: { online: "bus" } }, `${bus.interface || "?"}: ${BUS_STATES[bus.state] || bus.state || "?"}`),
        el("th", null, "TX / RX errors"), el("td", null, `${bus.tx_errors ?? "-"} / ${bus.rx_errors ?? "-"}`),
        el("th", null, "Bus-off"), el("td", null, String(bus.bus_off_count ?? "-")),
        el("th", null, "Master"), el("td", null, `node ${(st.master || {}).node_id ?? "?"}, ${stateName((st.master || {}).state)}`)),
      st.sync ? el("tr", null, el("th", null, "SYNC"),
        el("td", { colspan: 7, dataset: { online: "sync" } }, syncText(st.sync))) : null)),
    compareSummary(cmp),
    el("table", { class: "online-nodes", dataset: { online: "nodes" } },
      el("thead", null, el("tr", null, thCells(["Node", "Name", "State", "Status bit", "Boot", "Last EMCY", "SDO variables", "Last heard", "EDS", "Compared"]))),
      el("tbody", null, rows.length || extra.length ? rows.concat(extra) : [el("tr", null, el("td", { colspan: 10, class: "muted" },
        S.nodesFilter ? "No node in this group." : "No nodes in the configuration the runtime runs."))])),
    linksLive(st)]);
  const tbox = document.querySelector("[data-online='pdo-timeouts']");
  if (tbox) tbox.replaceChildren(pdoTimeoutTable((st.nodes || []).find((n) => n.node_id === S.onlineNode)));
  refreshNodeHeader(st);
  if (S.onlineNode !== undefined && S.onlineNode !== null && S.onlineNodeAllow !== r.hello.allow_changes) renderOnlineNode();
  if (S.lssAllow !== r.hello.allow_changes) renderLss(r.hello.allow_changes);
}

// ---------------------------------------------------------------------------
// A slave network in the online view: the plugin's own device, the PDO
// mappings in force and, on a gateway's upper network, the gateway. Its
// own dictionary opens below; the master's tools (node list, NMT, LSS, scan,
// parameter backup) need a master network.

const SLAVE_MASTER_ONLY = "This is a slave network: the plugin is a node of another master. The node list, NMT, LSS, " +
  "the bus scan and parameter backup need a master network; here you read and write the plugin's own dictionary.";

// The slave object of the online network's draft when that is a slave network, else null.
function onlineSlaveCfg() {
  const net = onlineConfig();
  return isSlave(net) ? net.slave || {} : null;
}

// Whether the online network is a slave network: as the runtime's hello says, else as the draft says.
function onlineIsSlave() {
  const nets = S.runtimeNets || [];
  const name = onlineNetwork();
  const rt = name === null ? (nets.length === 1 ? nets[0] : null) : nets.find((n) => n.name === name);
  if (rt && rt.role) return rt.role === "slave";
  return !!onlineSlaveCfg();
}

function slaveStateName(s) { return s ? stateName(s) : "not started"; }

function transmissionText(t) {
  if (t === 0) return "synchronous (acyclic)";
  if (t >= 1 && t <= 240) return t === 1 ? "every SYNC" : `every ${t} SYNCs`;
  if (t === 254 || t === 255) return `event (${t})`;
  return `type ${t}`;
}

// What the draft binds an object of the slave to: "%IW300 speed_setpoint", "route pong", or "".
function slaveBindText(index, sub) {
  const s = onlineSlaveCfg();
  if (!s) return "";
  const o = (s.objects || []).find((x) => sameObject(x.index, x.subindex, index, sub));
  if (o) return [o.iec_location, o.name].filter(Boolean).join(" ");
  const g = S.model.top.gateway;
  if (g && g.upper === netName(onlineConfig())) {
    const k = (g.routes || []).findIndex((r) => r && r.slave && sameObject(r.slave.index, r.slave.subindex, index, sub));
    if (k >= 0) return "route " + (g.routes[k].name || k + 1);
  }
  return "";
}

// {key: [PDO marks]} of the slave's own dictionary, from the mappings in
// force (the status answer's tpdos and rpdos), as the master's od_entries
// gives them for a configured node.
function slavePdoMarks(s) {
  const out = {};
  for (const [list, kind] of [[s.tpdos, "TPDO"], [s.rpdos, "RPDO"]]) {
    for (const p of list || []) {
      if ((Number(p.cob_id) >>> 0) & 0x80000000) continue;  // switched off
      let bit = 0;
      for (const e of p.entries || []) {
        const key = odKey(e.index, e.subindex);
        if (e.index >= 0x0008) (out[key] = out[key] || []).push({ pdo: kind + p.number, bits: [bit, bit + e.bits - 1] });
        bit += e.bits;
      }
    }
  }
  return out;
}

function slavePdoTable(list, dir, id) {
  const title = dir === "tx" ? "TPDOs (sent by this device)" : "RPDOs (received from the master)";
  const rows = (list || []).map((p) => {
    const cob = Number(p.cob_id) >>> 0;
    const off = (cob & 0x80000000) !== 0;
    const entries = (p.entries || []).map((e) => {
      // Bound in the draft, else the dictionary's name (the gateway's status objects).
      const known = odEntryCached(id, e.index, e.subindex);
      const bound = slaveBindText(e.index, e.subindex) || (known ? known.name : "");
      return el("div", null, `${hex4(e.index)}:${e.subindex} (${e.bits} bit${e.bits === 1 ? "" : "s"})`, bound ? el("span", { class: "muted" }, "  " + bound) : null);
    });
    return el("tr", { class: off ? "muted" : null, dataset: { slavePdo: `${dir}${p.number}` } },
      el("td", null, `${dir === "tx" ? "TPDO" : "RPDO"}${p.number}`),
      el("td", { class: "mono" }, "0x" + (cob & 0x1FFFFFFF).toString(16).toUpperCase().padStart(3, "0") + (off ? " (off)" : "")),
      el("td", null, transmissionText(p.transmission)),
      el("td", null, entries.length ? entries : el("span", { class: "muted" }, "nothing mapped")));
  });
  return el("fieldset", { dataset: { online: dir === "tx" ? "slave-tpdos" : "slave-rpdos" } }, el("legend", null, title),
    el("table", null, el("thead", null, el("tr", null, thCells(["PDO", "COB-ID", "Transmission", "Mapped objects"]))),
      el("tbody", null, rows.length ? rows : [el("tr", null, el("td", { colspan: 4, class: "muted" },
        list ? "None in the dictionary." : "Not known while there is no CANopen session."))])));
}

function slaveLive(r) {
  const st = r.status;
  const s = st.slave || {};
  const id = s.node_id || null;
  const em = s.emcy_code ? `${hex4(s.emcy_code)} ${emcyClass(s.emcy_code)}` : "none";
  const g = st.gateway;
  patchLive($("#online-live"), [
    el("p", { class: "muted", dataset: { online: "slave-note" } }, SLAVE_MASTER_ONLY),
    el("table", { class: "online-bus" }, el("tbody", null,
      el("tr", null, el("th", null, "Bus"), el("td", { dataset: { online: "bus" } }, st.bus.interface + (st.simulated_network ? " (simulated)" : "")),
        el("th", null, "This device"), el("td", { dataset: { online: "slave-node" } }, id ? `node ${id}` : "waiting for a node ID (LSS)"),
        el("th", null, "State"), el("td", { class: "state-" + s.state, dataset: { online: "slave-state" } }, slaveStateName(s.state))),
      el("tr", null, el("th", null, "Communication OK"), el("td", { class: s.comm_ok ? null : "bad", dataset: { online: "slave-comm" } }, s.comm_ok ? "TRUE" : "FALSE"),
        el("th", null, "SYNC count"), el("td", { dataset: { online: "slave-sync" } }, String(s.sync_count ?? "-")),
        el("th", null, "EMCY"), el("td", { dataset: { online: "slave-emcy" } },
          `${em}, error register 0x${Number(s.error_register || 0).toString(16).toUpperCase().padStart(2, "0")}`)),
      g ? el("tr", { dataset: { online: "gateway" } }, el("th", null, "Gateway routes"), el("td", { dataset: { online: "gw-routes" } }, String(g.routes)),
        el("th", null, "Upper master"), el("td", { class: g.upper_ok ? "state-5" : "bad", dataset: { online: "gw-upper" } },
          g.upper_ok ? "present" : "missing (no heartbeat, or not started)"),
        el("th", null, "Forwarded errors"), el("td", { dataset: { online: "gw-errors" } }, `${g.forwarded_errors} active`)) : null)),
    slavePdoTable(s.tpdos, "tx", id), slavePdoTable(s.rpdos, "rx", id)]);
  // The dictionary's names for the PDO tables, once.
  if (id && !(S.odEntries || {})[id] && !S.odFetching && nodeSource(id)) {
    S.odFetching = true;
    odEntries(id).catch(() => {}).finally(() => { S.odFetching = false; });
  }
  $("#online-lss").replaceChildren();
  S.lssAllow = undefined;
  const allow = r.hello.allow_changes;
  if (!id) {
    S.onlineNode = null;
    $("#online-node").replaceChildren();
  } else if (S.onlineNode !== id || S.onlineNodeAllow !== allow || !$("#online-node").childNodes.length) {
    S.onlineNode = id;
    renderOnlineNode();
  }
}

// An online request that LSS refuses while another master runs on the bus:
// ask, then send it again with force.
async function apiForce(path, body) {
  try {
    return await api("POST", path, body);
  } catch (e) {
    if (!/another master is active/.test(e.message)) throw e;
    const v = await modal(e.message.replace(/; --force.*$/, "") + ". LSS switches every device's state. Run it anyway?",
      [["force", "Run anyway", true], ["cancel", "Cancel"]]);
    if (v !== "force") throw new Error("Not run: another master is active on this bus.");
    return api("POST", path, Object.assign({}, body, { force: true }));
  }
}

// The connection's path and round trip (canopen-configurator, Path and round
// trip in the online view): "LAN", "internet direct" or "internet relayed",
// amber above 100 ms and red above 300 ms. None for a USB adapter.
const SLOW_RTT_MS = 100;
const VERY_SLOW_RTT_MS = 300;
function pathBadge(r) {
  if (!r || !r.path) return null;
  const rtt = Number.isFinite(r.rtt_ms) ? r.rtt_ms : null;
  const cls = rtt !== null && rtt > VERY_SLOW_RTT_MS ? "bad" : rtt !== null && rtt > SLOW_RTT_MS ? "warn" : "";
  return el("span", { class: ("pill " + cls).trim(), dataset: { online: "path", path: r.path },
    title: "How this PC reaches the runtime, and the measured round trip" },
  r.path + (rtt !== null ? `, ${rtt} ms` : ""));
}

// The last status answer when its path is slow for work that needs quick
// answers on the bus (relayed, or above 100 ms), else null.
function slowPath() {
  const r = S.onlineLast;
  if (!r || !r.path || (r.status && r.status.local)) return null;
  return r.path === "internet relayed" || (Number.isFinite(r.rtt_ms) && r.rtt_ms > SLOW_RTT_MS) ? r : null;
}

// LSS fast scan and a PDO test with a SYNC period on a slow path: asks
// first; nothing is sent until the user confirms. True to go on.
async function askSlowPath(what) {
  const r = slowPath();
  if (!r) return true;
  const v = await modal(`The connection to the runtime is ${r.path}` +
    (Number.isFinite(r.rtt_ms) ? `, round trip ${r.rtt_ms} ms` : "") +
    `. ${what} runs on the runtime, but its results and stop commands arrive late over this path. Start it anyway?`,
  [["go", "Start anyway", true], ["cancel", "Cancel"]]);
  return v === "go";
}

async function commissionDevice() {
  try {
    banner("");
    await api("POST", "/api/commission", {});
    S.view = "online";
    S.commLog = [];
    S.commLogSaved = 0;
    S.commDevice = {};
    S.commNodes = {};
    S.identity = null;
    S.adapterOn = false;
    S.adapterEnded = null;
    await loadState();
    // The start page's button is gone: the focus goes to Connect… in the connection bar.
    const first = document.querySelector('#conn-bar [data-conn="connect"]');
    if (first) first.focus();
  } catch (e) { banner(e.message, true); }
}

// The status answer's SYNC object as one line (as the CLI's status prints it).
function syncText(sy) {
  if (sy.source === "none") return "off";
  const head = sy.source === "plc_cycle"
    ? "PLC cycle" + (sy.cycles > 1 ? `, every ${sy.cycles} cycles` : "")
    : `timer ${sy.period_us} µs`;
  let t = `${head}, ${sy.count} sent`;
  if (sy.count > 1) t += `, interval ${sy.last_us} µs (min ${sy.min_us}, max ${sy.max_us})`;
  return t + `, skipped ${sy.skipped}, late PDOs ${sy.late_pdos}`;
}

// ---------------------------------------------------------------------------
// Unconfigured devices (LSS): find a device without a node ID, set its node
// ID or bit rate. Nothing is stored in the device unless the dialog's box is
// ticked, and the box starts unticked every time.

const LSS_BITRATES = [10, 20, 50, 125, 250, 500, 800, 1000];
const LSS_KEYS = ["vendor_id", "product_code", "revision_number", "serial_number"];

function renderLss(allow) {
  const box = $("#online-lss");
  if (!box) return;
  S.lssAllow = allow;
  // The search's progress beside its button; what it found, or why not, at the section's top.
  const status = el("span", { class: "muted", dataset: { online: "lss-status" } });
  const slot = noticeSlot({ dataset: { online: "lss-notices" } });
  if (!allow) slot.append(lockedNote("lss-no-changes", '[data-online="lss-find"]'));
  const result = el("div", { dataset: { online: "lss-result" } });
  const find = el("button", { type: "button", disabled: !allow, title: allow ? null : NO_CHANGES,
    dataset: { online: "lss-find" }, onclick: () => runLssFind(true) }, "Find a device without node ID");
  box.replaceChildren(el("fieldset", { dataset: { online: "lss" } }, el("legend", null, "Unconfigured devices (LSS)"), slot,
    el("p", { class: "muted" }, "Devices without DIP switches get their node ID and bit rate over the bus (LSS, CiA 305). " +
      "Find one device that has no node ID yet, then set its node ID or bit rate." + (S.state.commission ? "" : " PDOs of the configured nodes keep running.")),
    el("div", { class: "toolbar" }, find, status), result));
  if (allow && S.lssDevice) showLssDevice(S.lssDevice);
}

// The LSS search's message: a bar at the top of its section; kind null clears it.
function lssSay(kind, text) {
  const slot = document.querySelector("[data-online=lss-notices]");
  if (slot) setNotice(slot, "find", kind, text, { dataset: { online: "lss-msg" } });
}

async function runLssFind(start) {
  const seq = S.onlineSeq;
  const status = document.querySelector("[data-online=lss-status]");
  lssSay(null);
  if (start && !(await askSlowPath("The LSS fast scan"))) {
    lssSay("info", "Not started.");
    return;
  }
  let r;
  try {
    r = start ? await apiForce("/api/online/lss_find", { start, port: diagPort() })
      : await api("POST", "/api/online/lss_find", { start, port: diagPort() });
  } catch (e) {
    if (seq === S.onlineSeq && status) { status.textContent = ""; lssSay("error", e.message); }
    return;
  }
  if (seq !== S.onlineSeq || !onlineViews().includes(S.view)) return;
  const st = document.querySelector("[data-online=lss-status]");
  if (!st) return;
  if (r.running) {
    st.textContent = `Searching… ${Math.floor(r.seconds || 0)} s (up to about 15 s)`;
    setTimeout(() => runLssFind(false), 300);
    return;
  }
  st.textContent = "";
  if (r.error) { lssSay("error", "The search failed: " + r.error); return; }
  if (!r.found || !r.device) {
    S.lssDevice = null;
    lssSay("info", `No device without a node ID answered (${(r.seconds || 0).toFixed(1)} s).`);
    document.querySelector("[data-online=lss-result]").replaceChildren();
    return;
  }
  lssSay("done", `Found in ${(r.seconds || 0).toFixed(1)} s.`);
  S.lssDevice = r.device;
  showLssDevice(r.device);
}

function showLssDevice(d) {
  const box = document.querySelector("[data-online=lss-result]");
  if (!box) return;
  const m = d.eds_matches || [];
  const vendorName = m.length ? m[0].vendor_name : "";
  // The best match as text: after Set node ID the node's EDS is changed in the Nodes table (one-eds-picker).
  const sel = m.length ? el("span", { title: m[0].path, dataset: { online: "lss-eds" } }, edsLabel(m[0].product_name, m[0].name),
    el("span", { class: "muted" }, ` (${m[0].where === "project" ? "project" : "library"}${m[0].revision_match ? ", exact revision" : ""})`))
    : el("span", { class: "muted" }, "No matching EDS");
  box.replaceChildren(el("table", { class: "scan" },
    el("thead", null, el("tr", null, thCells(["Vendor", "Product", "Revision", "Serial number", "Node ID", "EDS", ""]))),
    el("tbody", null, el("tr", { dataset: { lssDevice: d.serial_number } },
      el("td", null, hex8(d.vendor_id) + (vendorName ? " " + vendorName : "")), el("td", null, hex8(d.product_code)),
      el("td", null, hex8(d.revision_number)), el("td", null, `${d.serial_number} (${hex8(d.serial_number)})`),
      el("td", null, d.node_id === undefined || d.node_id === 255 ? "none" : String(d.node_id)),
      el("td", null, sel),
      el("td", null,
        el("button", { type: "button", dataset: { online: "lss-set-id" }, onclick: () => lssSetId(d, m.length ? m[0] : null) }, "Set node ID…"),
        el("button", { type: "button", dataset: { online: "lss-set-bitrate" }, onclick: () => lssSetBitrate(d) }, "Set bit rate…"))))));
}

function lssAddress(d) { const a = {}; for (const k of LSS_KEYS) a[k] = d[k]; return a; }

function lowestFreeNodeId() {
  const master = num(getPath("master.node_id")) || (S.onlineLast ? S.onlineLast.hello.master_node_id : 1);
  const used = new Set((S.config.nodes || []).map((n) => num(n.node_id)));
  for (let id = 1; id <= 127; id++) if (id !== master && !used.has(id)) return id;
  return null;
}

function storeBox() {
  return el("label", { class: "check" }, el("input", { type: "checkbox", dataset: { online: "lss-store" } }),
    " Store in the device (non-volatile memory; without it a power cycle undoes the change)");
}

async function lssSetId(d, match) {
  const idInput = el("input", { type: "number", min: 1, max: 127, class: "short", dataset: { online: "lss-node-id" } });
  const free = lowestFreeNodeId();
  if (free) idInput.value = String(free);
  const store = storeBox();
  const idMsg = el("p", { class: "field-msg", dataset: { online: "lss-node-id-msg" } });
  const form = el("div", null, el("label", { class: "inline" }, "Node ID ", idInput), idMsg, el("div", null, store));
  let node;
  for (;;) {  // an invalid node ID shows the dialog again, with the reason
    const v = await modal(`Set the node ID of the device with serial number ${hex8(d.serial_number)}.`,
      [["set", "Set node ID", true], ["cancel", "Cancel"]], form);
    if (v !== "set") return;
    node = Number(idInput.value);
    if (/^\s*\d+\s*$/.test(idInput.value) && node >= 1 && node <= 127) break;
    idMsg.textContent = "The node ID must be 1-127.";
  }
  let r;
  try {
    r = await apiForce("/api/online/lss_set_id", { address: lssAddress(d), node, store: store.querySelector("input").checked, port: diagPort() });
  } catch (e) { banner(e.message, true); return; }
  banner(`Node ID ${node} set${r.stored ? " and stored in the device" : ""}. ${r.note.charAt(0).toUpperCase() + r.note.slice(1)}.`);
  S.lssDevice = null;
  const box = document.querySelector("[data-online=lss-result]");
  if (box) box.replaceChildren();
  if (S.state.commission) {  // a row of the Nodes page, with the EDS that matched
    commNodes()[node] = Object.assign(commNodes()[node] || {}, lssAddress(d), { lss: true },
      match ? { eds_path: match.path, eds_name: match.name } : {});
    if (match) {
      S.onlineEds = Object.assign(S.onlineEds || {}, { [node]: match.path });
      S.onlineEdsName = Object.assign(S.onlineEdsName || {}, { [node]: match.name });
    }
    const live = $("#online-live");
    if (live) patchLive(live, [commNodeTable(S.onlineLast && S.onlineLast.status)]);
    return;
  }
  if (configNode(node)) return;
  // commission-workspace: the device is listed as Not in config, with Add to config on its row.
  S.lssSet = Object.assign(S.lssSet || {}, { [node]: true });
  S.lssFound = (S.lssFound || []).filter((x) => x.node_id !== node);
  S.lssFound.push(Object.assign({}, d, { node_id: node, eds_matches: match ? [match] : (d.eds_matches || []) }));
  onlineRedraw();
}

async function lssSetBitrate(d) {
  const sel = el("select", { "aria-label": "Bit rate", dataset: { online: "lss-bitrate" } },
    LSS_BITRATES.map((b) => el("option", { value: b }, `${b} kbit/s`)));
  const current = num(getPath("adapter.bitrate"));
  sel.value = String(LSS_BITRATES.includes(current / 1000) ? current / 1000 : 125);
  const store = storeBox();
  const v = await modal(`Set the bit rate of the device with serial number ${hex8(d.serial_number)}. ` +
    "The device switches to it after its next power cycle; the rest of the bus does not. Change the adapter bit rate " +
    "(Bus and master) to match once every device is set.",
    [["set", "Set bit rate", true], ["cancel", "Cancel"]],
    el("div", null, el("label", { class: "inline" }, "Bit rate ", sel), el("div", null, store)));
  if (v !== "set") return;
  try {
    const r = await apiForce("/api/online/lss_set_bitrate", { address: lssAddress(d), bitrate_kbit: Number(sel.value),
      store: store.querySelector("input").checked, port: diagPort() });
    banner(`Bit rate ${r.bitrate_kbit} kbit/s set${r.stored ? " and stored in the device" : ""}. ${r.note.charAt(0).toUpperCase() + r.note.slice(1)}.`);
  } catch (e) { banner(e.message, true); }
}

function pollHighlight() {
  for (const tr of document.querySelectorAll("tr[data-online-node]")) tr.classList.toggle("active", onlineRowActive(Number(tr.dataset.onlineNode)));
}

// Puts a poll's parts into the live box in place of the last poll's: a part
// that did not change stays, and a node table keeps its rows (keyed by node
// ID) with new cells, so keyboard focus and a pending click stay on a row.
function patchLive(live, parts) {
  const old = [...live.children];
  const same = old.length === parts.length && parts.every((p, k) => p.tagName === old[k].tagName &&
    p.className === old[k].className && p.dataset.online === old[k].dataset.online);
  if (!same) { live.replaceChildren(...parts); return; }
  parts.forEach((p, k) => {
    const o = old[k];
    if (o.innerHTML === p.innerHTML) return;
    const ob = o.tagName === "TABLE" && o.tBodies[0], nb = p.tagName === "TABLE" && p.tBodies[0];
    if (!ob || !nb || !nb.querySelector("tr[data-online-node]") || o.tHead.innerHTML !== p.tHead.innerHTML) { o.replaceWith(p); return; }
    const rows = new Map([...ob.rows].filter((tr) => tr.dataset.onlineNode).map((tr) => [tr.dataset.onlineNode, tr]));
    const want = [...nb.rows].map((tr) => {
      const was = rows.get(tr.dataset.onlineNode);
      if (!was) return tr;
      rows.delete(tr.dataset.onlineNode);
      if (was.className !== tr.className) was.className = tr.className;
      if (was.innerHTML !== tr.innerHTML) {
        // Cell by cell, so a focused button in an unchanged cell keeps the focus.
        if (was.cells.length === tr.cells.length) {
          [...tr.cells].forEach((td, i) => { const c = was.cells[i]; if (c.outerHTML !== td.outerHTML) c.replaceWith(td); });
        } else was.replaceChildren(...tr.childNodes);
      }
      return was;
    });
    for (const tr of [...ob.rows]) if (!want.includes(tr)) tr.remove();
    want.forEach((tr, i) => { if (ob.rows[i] !== tr) ob.insertBefore(tr, ob.rows[i] || null); });
  });
}

// An SDO variable's status byte in words (docs/config.md): 2 (done) and
// below need none.
function sdoStatus(v) {
  return v.abort_code ? "abort " + hex8(v.abort_code) : { 3: "aborted", 4: "node not available" }[v.status] || "status " + v.status;
}

// A status node's EMCY COB-ID in use (emcy_cob_id: value, source, valid),
// shown when it is not 0x80 + node ID or the device switched its EMCY off;
// null for the default and for a plugin that does not send it.
function emcyCobNote(n) {
  const e = n && n.emcy_cob_id;
  if (!e || !Number.isInteger(e.value)) return null;
  const valid = e.valid !== false;
  if (valid && e.value === 0x80 + n.node_id) return null;
  return el("div", { class: valid ? "muted" : "bad", dataset: { emcyCob: n.node_id },
    title: valid ? "The COB-ID the master listens on for this node's EMCY" : "The device reports its EMCY not valid (0x1014 bit 31): it sends none" },
  `EMCY COB-ID 0x${e.value.toString(16).toUpperCase()} (${e.source || "?"}${valid ? "" : ", off on the device"})`);
}

function emcyClass(code) {
  const c = Number(code);
  if (c === 0) return "error reset or no error";
  const classes = [[0xFF00, 0x1000, "generic error"], [0xF000, 0x2000, "current"], [0xF000, 0x3000, "voltage"],
    [0xF000, 0x4000, "temperature"], [0xFF00, 0x5000, "device hardware"], [0xF000, 0x6000, "device software"],
    [0xFF00, 0x7000, "additional modules"], [0xFF00, 0x8100, "communication"], [0xFF00, 0x8200, "protocol error"],
    [0xF000, 0x8000, "monitoring"], [0xFF00, 0x9000, "external error"], [0xFF00, 0xF000, "additional functions"],
    [0xFF00, 0xFF00, "device specific"]];
  for (const [mask, value, name] of classes) if ((c & mask) === value) return name;
  return "reserved";
}

function configNode(id) { return (onlineConfig().nodes || []).find((x) => num(x.node_id) === id) || null; }

async function renderOnlineNode() {
  if (typeof renderTree === "function") renderTree();
  onlineLayout();
  const box = $("#online-node");
  if (!box || S.onlineNode === undefined || S.onlineNode === null) return;
  const id = S.onlineNode;
  const slave = onlineIsSlave() ? onlineSlaveCfg() || {} : null;
  // The slave's own device: its EDS stands in for a configured node's.
  const n = slave ? { node_id: id, name: "this PLC (slave device)", eds: slave.eds } : configNode(id);
  const allow = S.onlineLast ? S.onlineLast.hello.allow_changes : false;
  S.onlineNodeAllow = S.onlineLast ? allow : undefined;
  let tab = S.onlineTab || "status";
  // The PDO test only on a USB adapter: on a runtime the PLC runs the PDOs.
  const pdoTab = !slave && pdoTestLocal();
  const have = COMMISSION_TABS.filter(([k]) => (!slave || (k !== "params" && k !== "log")) && (pdoTab || k !== "pdo"));
  if (!have.some(([k]) => k === tab)) tab = "status";
  if (tab === "status" && S.emcyNew && S.emcyNew[id]) { delete S.emcyNew[id]; if (S.onlineLast) treeLive(S.onlineLast.status); }
  const logCount = commLogOn() ? (S.commLog || []).filter((e) => e.node === id).length : 0;
  const notesLabel = commNotesLabel(id, n);
  const tabList = tabs(have.map(([k, label]) => [k, k === "log" && logCount ? `${label} ${logCount}` : k === "notes" ? notesLabel : label]),
    tab, (k) => { S.onlineTab = k; renderOnlineNode(); onlineTop(); }, { dataset: "onlineTab", panel: "online-node-panel", label: "Node pages" });
  const head = el("h2", { dataset: { online: "node-heading" } }, nodeHeading(id));
  const last = S.onlineLast && S.onlineLast.status ? (S.onlineLast.status.nodes || []).find((x) => x.node_id === id) : null;
  // The one-line node header (commission-master-detail): back to the Nodes table, the node, its live state.
  const back = slave ? null : el("button", { type: "button", class: "small", dataset: { online: "back-to-nodes" },
    "aria-label": "Back to the Nodes table", onclick: backToNodes }, "← Nodes");
  const title = el("div", { class: "toolbar node-head", dataset: { online: "node-header" } }, back, head, nodeHeaderLive(id, last),
    S.state.commission ? el("button", { type: "button", dataset: { online: "add-to-config" }, onclick: () => addToConfig(id) }, "Add to a config…") : null);
  const panel = (...kids) => el("div", { id: "online-node-panel", role: "tabpanel", "aria-labelledby": `online-node-panel-tab-${tab}` }, ...kids);
  // The node page's messages (values no longer live) under its heading.
  const top = [title, noticeSlot({ dataset: { online: "node-notices" } }), tabList];
  // The object dictionary tab takes the problems pane's room, as the trace does.
  $("#editor").classList.toggle("wide-view", tab === "od");
  if (tab === "od") { put(box, top, panel(odPanel(id, n, allow))); return; }
  if (tab === "params") { put(box, top, panel(paramsPanel(id, n, allow))); return; }
  if (tab === "pdo") { put(box, top, panel(pdoTestPanel(id, n, allow))); return; }
  if (tab === "notes") { put(box, top, panel(commNotesTab(id, n))); return; }
  if (tab === "log") { put(box, top, panel(nodeLogTab(id))); return; }
  if (slave) { put(box, top, panel(sdoPanel(id, n, allow))); return; }
  const emcy = el("div", { dataset: { online: "emcy" } }, el("span", { class: "muted" }, "Loading…"));
  const timeouts = last && (last.pdo_timeouts || []).length
    ? el("fieldset", null, el("legend", null, "Input PDO timeouts"), el("div", { dataset: { online: "pdo-timeouts" } }, pdoTimeoutTable(last)))
    : null;
  put(box, top, panel(
    deviceLine(id),
    el("fieldset", null, el("legend", null, "NMT"), nmtButtons(id, allow)),
    simulatedNode(id) ? simPanel(id) : null,
    timeouts,
    sdoPanel(id, n, allow),
    el("fieldset", null, el("legend", null, "Emergency history (newest first)"), emcy,
      el("button", { type: "button", onclick: () => renderOnlineNode() }, "Refresh")),
    errorFieldPanel(id, allow)));
  try {
    const r = await api("POST", "/api/online/emcy", { node: id, port: diagPort() });
    emcy.replaceChildren(r.emcy.length ? el("table", null,
      el("thead", null, el("tr", null, thCells(["Time (UTC)", "Code", "Class", "Error register", "Manufacturer data"]))),
      el("tbody", null, r.emcy.map((e) => el("tr", null, el("td", null, e.time.replace("T", " ").replace("Z", "")),
        el("td", null, hex4(e.code)), el("td", null, e.class), el("td", null, "0x" + e.error_register.toString(16).toUpperCase().padStart(2, "0")),
        el("td", null, e.manufacturer))))) : el("p", { class: "muted" }, "No EMCY from this node since the CANopen session started."));
  } catch (e) {
    emcy.replaceChildren(notice("error", e.message));
  }
}

// The device's own error history, 0x1003 (canopen-configurator: Device error
// history in the online view): count and entries newest first, read with the
// manual SDO read; Clear writes 0 to sub-index 0 with the manual write, so it
// needs changes allowed and, on an OPERATIONAL node, force (asked first).
function errorFieldPanel(id, allow) {
  // The section's messages (locked, read failed) are at its top, under the legend.
  const slot = noticeSlot();
  if (!allow) slot.append(lockedNote("error-field-no-changes", '[data-online="error-field-clear"]', "Clear:"));
  const box = el("div", { dataset: { online: "error-field" } }, el("span", { class: "muted" }, "Loading…"));
  const say = (kind, text, data) => setNotice(slot, "read", kind, text, data ? { dataset: data } : null);
  let last = null;
  const show = (r) => {
    last = r;
    say(null);
    if (!r.history) { box.replaceChildren(); say("info", `Node ${id} has no error history (0x1003).`); return; }
    if (r.failed) say("error", r.count === null ? `Sub-index 0: ${r.failed.reason}.` : `Sub-index ${r.failed.subindex}: ${r.failed.reason}; the list ends here.`,
      { online: "error-field-failed" });
    if (r.count === null) { box.replaceChildren(); return; }
    put(box, el("p", { dataset: { online: "error-field-count" } }, `Count ${r.count}` + (r.entries.length ? " (newest first)" : "")),
      r.entries.length ? el("table", null,
        el("thead", null, el("tr", null, thCells(["Sub-index", "Code", "Class", "Manufacturer information"]))),
        el("tbody", null, r.entries.map((e) => el("tr", { dataset: { errorFieldRow: e.subindex } }, el("td", null, String(e.subindex)),
          el("td", null, hex4(e.code)), el("td", null, e.class), el("td", null, hex4(e.info)))))) : null);
  };
  const read = async () => {
    try { show(await api("POST", "/api/online/error_field", { node: id, port: diagPort() })); } catch (e) {
      last = null;
      box.replaceChildren();
      say("error", e.message);
    }
  };
  const clear = async () => {
    const n = last && last.count !== null && last.history ? last.count : null;
    const what = n === null ? "all its entries" : `its ${n} entr${n === 1 ? "y" : "ies"}`;
    if (await modal(`Clear node ${id}'s error history (0x1003)? The device deletes ${what}.`,
      [["clear", "Clear", { danger: true }], ["cancel", "Cancel"]]) !== "clear") return;
    const forceText = `Node ${id} is OPERATIONAL and the PLC program drives it. Clear its error history anyway (force)?`;
    const askForce = async () => await modal(forceText, [["force", "Clear anyway", { danger: true }], ["cancel", "Cancel"]]) === "force";
    const body = { node: id, port: diagPort() };
    let forced = false;
    if (nodeRunning(id)) {
      if (!(await askForce())) return;
      forced = true;
    }
    try {
      let r;
      try { r = await api("POST", "/api/online/error_field_clear", Object.assign({}, body, forced ? { force: true } : {})); } catch (e) {
        if (forced || !(e.body && e.body.force)) throw e;
        if (!(await askForce())) return;
        r = await api("POST", "/api/online/error_field_clear", Object.assign({}, body, { force: true }));
      }
      banner(`Node ${id}: error history (0x1003) cleared.`);
      show(r);
    } catch (e) {
      banner(e.message, true);
      read();
    }
  };
  // Read at once only from a node the master has booted and that answers SDO
  // (PRE-OPERATIONAL or OPERATIONAL), or with no status to tell; otherwise
  // Refresh reads it.
  const st = S.onlineLast && S.onlineLast.status;
  const sn = st ? (st.nodes || []).find((x) => x.node_id === id) : null;
  if (!st || (sn && sn.booted !== false && (sn.state === 5 || sn.state === 127))) read();
  else { box.replaceChildren(); say("info", `Node ${id} has not booted; Refresh reads its error history.`); }
  return el("fieldset", null, el("legend", null, "Error history (0x1003)"), slot, box,
    el("div", { class: "toolbar" },
      el("button", { type: "button", dataset: { online: "error-field-refresh" }, onclick: () => read() }, "Refresh"),
      el("button", { type: "button", disabled: !allow, title: allow ? null : NO_CHANGES, dataset: { online: "error-field-clear" },
        onclick: () => clear() }, "Clear")));
}

// The monitored TPDOs of a node in the status answer: timeout, timed out
// now, timeouts so far, time since the last PDO.
function pdoTimeoutTable(n) {
  const list = (n && n.pdo_timeouts) || [];
  if (!list.length) return el("p", { class: "muted" }, "No TPDO of this node has a receive timeout.");
  // The plugin times a PDO out only while the node is OPERATIONAL.
  const up = n.state === 5;
  return el("table", null,
    el("thead", null, el("tr", null, thCells(["TPDO", "Timeout", "Now", "Timeouts", "Last PDO"]))),
    el("tbody", null, list.map((t) => el("tr", { dataset: { pdoTimeoutRow: t.tpdo } },
      el("td", null, String(t.tpdo)), el("td", null, `${t.timeout_ms} ms`),
      el("td", { class: t.timed_out ? "bad" : up ? null : "muted" }, t.timed_out ? "timed out" : up ? "receiving" : `not monitored (node ${stateName(n.state)})`),
      el("td", null, String(t.count)),
      el("td", null, t.since_ms === null || t.since_ms === undefined ? "never" : `${t.since_ms} ms ago`)))));
}

// An SDO write and NMT other than START to an OPERATIONAL node, and a scan
// while a node is OPERATIONAL, need force: the PLC program drives the node.
// The page asks first ("node N is running; send anyway?"), when the last
// status shows the node OPERATIONAL or the plugin refuses for that reason,
// and only then sends the request with force.
function nodeRunning(id) {
  const st = S.onlineLast && S.onlineLast.status;
  const n = st ? (st.nodes || []).find((x) => x.node_id === id) : null;
  return !!n && n.state === 5;
}
const RUNNING_TEXT = (id) => `Node ${id} is running (OPERATIONAL) and the PLC program drives it. Send anyway?`;
async function askRunning(text) {
  return await modal(text, [["send", "Send anyway", true], ["cancel", "Cancel"]]) === "send";
}
// api() for a request that needs force on a running node; null when the
// user said no (nothing was sent). `asked`: the question was already put.
async function apiRunning(path, body, text, asked) {
  if (asked) return api("POST", path, Object.assign({}, body, { force: true }));
  try { return await api("POST", path, body); } catch (e) {
    if (!(e.body && e.body.force)) throw e;
    if (!(await askRunning(`${upperFirst(e.message.replace(/;?\s*force needed\s*$/, ""))}. ${text}`))) return null;
    return api("POST", path, Object.assign({}, body, { force: true }));
  }
}
// The sentence a write dialog starts with when the node is OPERATIONAL.
function runningNote(id, running) {
  return running ? `Node ${id} is running (OPERATIONAL) and the PLC program drives it. ` : "";
}
async function apiNodeChange(id, path, body) {
  const running = nodeRunning(id);
  if (running && !(await askRunning(RUNNING_TEXT(id)))) return null;
  return apiRunning(path, body, "Send anyway?", running);
}

function nmtButtons(id, allow) {
  const send = async (command, label, confirm) => {
    // START never needs force; the others ask once, naming a running node.
    const running = command !== "start" && nodeRunning(id);
    if (confirm || running) {
      const text = running ? `Node ${id} is running (OPERATIONAL) and the PLC program drives it. ${confirm || ""} Send anyway?` : confirm;
      const v = await modal(text, [[running ? "send" : "go", running ? "Send anyway" : label, true], ["cancel", "Cancel"]]);
      if (v !== "go" && v !== "send") return;
    }
    try {
      const body = { node: id, command, port: diagPort() };
      const r = command === "start" ? await api("POST", "/api/online/nmt", body)
        : await apiRunning("/api/online/nmt", body, "Send anyway?", running);
      if (!r) return;
      banner(`Node ${id}: ${label} sent.` + (r.note ? " " + r.note + "." : ""));
    } catch (e) { banner(e.message, true); }
  };
  const btn = (command, label, confirm) => el("button", { type: "button", disabled: !allow, title: allow ? null : NO_CHANGES,
    dataset: { nmt: command }, onclick: () => send(command, label, confirm) }, label);
  // Sends nothing, so it works without "Allow changes".
  const pick = el("select", { "aria-label": "Command for the ST call", dataset: { online: "nmt-st-command" } },
    Object.keys(NMT_CODES).map((c) => el("option", { value: c }, `${NMT_CODES[c][1]} (${NMT_CODES[c][0]})`)));
  const copy = async () => {
    const v = pick.value;
    await copyText(stNmtCall(id, v));
    banner(`Copied the CO_NMT call (${NMT_CODES[v][1]} to node ${id}). Enable the canworks library in the editor project to use it.`);
  };
  return el("div", null, allow ? null : lockedNote("no-changes", "[data-nmt=start]"), el("div", { class: "toolbar" },
    btn("start", "Start"),
    btn("stop", "Stop", `Stop node ${id}? Its PDOs stop and it stays STOPPED, also after a reboot, until you start it or the program changes its NMT command byte.`),
    btn("preop", "Pre-operational", `Set node ${id} pre-operational? Its PDOs stop until it is started again, by you or by the program's NMT command byte.`),
    btn("reset", "Reset node", `Reset node ${id}? It reboots and the master configures it again.`),
    btn("reset-comm", "Reset communication", `Reset node ${id}'s communication? It comes back pre-operational and the master configures it again.`),
    pick, el("button", { type: "button", dataset: { online: "nmt-st" }, title: "Copy as ST call (CO_NMT block)", onclick: copy },
      "Copy as ST call")),
  hint("Stop and pre-operational hold the node until you start it, or until the program changes the node's NMT command byte or sends a CO_NMT command."));
}

function sdoPanel(id, n, allow) {
  const eds = n ? edsFor(n) : null;
  let objects = eds && eds.objects ? eds.objects : [];
  let from = "the EDS";
  const filter = el("input", { type: "text", placeholder: "Filter objects", "aria-label": "Filter objects" });
  const pick = el("select", { "aria-label": "Object", dataset: { online: "object" } });
  const ix = el("input", { type: "text", class: "index", placeholder: "0x1018", "aria-label": "Index", dataset: { online: "index" } });
  const sub = el("input", { type: "text", class: "short", placeholder: "0", "aria-label": "Subindex", dataset: { online: "subindex" } });
  const type = el("select", { "aria-label": "Type", dataset: { online: "type" } },
    el("option", { value: "" }, "hex bytes"), SDO_TYPES.map((t) => el("option", { value: t }, t)));
  const value = el("input", { type: "text", placeholder: "value", "aria-label": "Value", dataset: { online: "value" } });
  const out = el("div", { class: "sdo-result", dataset: { online: "sdo-result" } });
  const typeNames = { 1: "BOOLEAN", 2: "INTEGER8", 3: "INTEGER16", 4: "INTEGER32", 5: "UNSIGNED8", 6: "UNSIGNED16",
    7: "UNSIGNED32", 8: "REAL32", 9: "VISIBLE_STRING", 10: "OCTET_STRING", 11: "UNICODE_STRING", 15: "DOMAIN",
    16: "INTEGER24", 17: "REAL64", 21: "INTEGER64", 22: "UNSIGNED24", 27: "UNSIGNED64" };
  const fill = () => {
    const f = filter.value.trim().toLowerCase();
    pick.replaceChildren(el("option", { value: "" }, objects.length ? `Pick an object from ${from}…` : "No EDS objects (type index and subindex)"),
      ...objects.filter((o) => !f || `${o.index}:${o.subindex} ${o.name}`.toLowerCase().includes(f)).map((o) =>
        el("option", { value: `${o.index}:${o.subindex}` }, `${o.index}:${o.subindex} ${o.name} (${typeNames[o.type_code] || o.type || "?"}, ${o.access})`)));
  };
  fill();
  filter.addEventListener("input", fill);
  // No EDS in the config: the node's picked EDS or its standard dictionary, as the object dictionary tab has them.
  if (!objects.length && odSource(id)) {
    odEntries(id).then((data) => {
      objects = data.entries.map((e) => ({ index: hex4(e.index), subindex: e.subindex, name: e.name, type: e.type, access: e.access }));
      from = data.standard ? "the standard objects" : "the EDS";
      fill();
    }).catch(() => {});
  }
  pick.addEventListener("change", () => {
    const o = objects.find((x) => `${x.index}:${x.subindex}` === pick.value);
    if (!o) return;
    ix.value = o.index;
    sub.value = String(o.subindex);
    type.value = typeNames[o.type_code] || (SDO_TYPES.includes(o.type) ? o.type : "");
  });
  const target = () => {
    const index = num(ix.value.trim()), subindex = sub.value.trim() === "" ? 0 : num(sub.value.trim());
    if (!(index >= 0 && index <= 0xFFFF) || !(subindex >= 0 && subindex <= 255)) {
      out.replaceChildren(el("span", { class: "field-msg" }, "Give the index as 0x… (or pick an object) and the subindex as 0-255."));
      return null;
    }
    return { node: id, index, subindex, type: type.value || null, port: diagPort() };
  };
  const show = (r, what) => {
    if (r.success) {
      out.replaceChildren(what === "read"
        ? el("span", null, el("strong", null, r.decoded.text), r.decoded.hex && r.decoded.text !== r.decoded.hex ? el("span", { class: "muted" }, "  bytes " + r.decoded.hex) : null)
        : el("span", { class: "ok-text" }, "Written."));
    } else {
      out.replaceChildren(el("span", { class: "field-msg" }, r.abort_code !== undefined ? `Abort ${hex8(r.abort_code)}: ${r.abort_text}` : r.reason));
    }
  };
  const read = async () => {
    const t = target();
    if (!t) return;
    out.replaceChildren(el("span", { class: "muted" }, "Reading…"));
    try { show(await api("POST", "/api/online/sdo_read", t), "read"); } catch (e) { out.replaceChildren(el("span", { class: "field-msg" }, e.message)); }
  };
  const write = async () => {
    const t = target();
    if (!t) return;
    if (!onlineIsSlave() && nodeSource(id)) await odEntries(id).catch(() => null);  // its PDO marks
    const warn = [];
    warn.push(...ownWriteWarnings(t.index, t.subindex));
    const owner = n && (n.sdo_variables || []).find((v) => (v.direction || "read") === "write" && sameObject(v.index, v.subindex, t.index, t.subindex));
    if (owner) warn.push(`SDO variable ${owner.name || hex4(owner.index)} writes this object from the program; the program's value wins at its next write.`);
    const startup = n && (n.sdo || []).find((s) => sameObject(s.index, s.subindex, t.index, t.subindex));
    if (startup) warn.push(`The config writes ${startup.value} to this object at every boot (startup SDO).`);
    if (warn.length) {
      const v = await modal(warn.join(" ") + " Write anyway?", [["write", "Write", true], ["cancel", "Cancel"]]);
      if (v !== "write") return;
    }
    out.replaceChildren(el("span", { class: "muted" }, "Writing…"));
    try {
      const r = await apiNodeChange(id, "/api/online/sdo_write", Object.assign(t, { value: value.value }));
      if (!r) { out.replaceChildren(el("span", { class: "muted" }, "Not written.")); return; }
      if (r.success) odTake(id, null, [odKey(t.index, t.subindex)]);
      show(r, "write");
    } catch (e) { out.replaceChildren(el("span", { class: "field-msg" }, e.message)); }
  };
  return el("fieldset", { dataset: { online: "sdo" } }, el("legend", null, "SDO"),
    el("div", { class: "toolbar" }, filter, pick),
    el("div", { class: "toolbar" },
      el("label", { class: "inline" }, "Index ", ix), el("label", { class: "inline" }, "Sub ", sub),
      el("label", { class: "inline" }, "Type ", type),
      el("button", { type: "button", class: "primary", dataset: { online: "read" }, onclick: read }, "Read")),
    el("div", { class: "toolbar" }, el("label", { class: "inline" }, "Value ", value),
      el("button", { type: "button", disabled: !allow, title: allow ? null : NO_CHANGES, dataset: { online: "write" }, onclick: write }, "Write")),
    hint("Numbers in decimal or 0x hex; VISIBLE_STRING as text; OCTET_STRING, DOMAIN and \"hex bytes\" as hex such as 1E 00."),
    out);
}

// ---------------------------------------------------------------------------
// Device parameters (canopen-device-parameters): the object dictionary tab
// and the parameters tab of a node. The long operations run as jobs in the
// configurator server, so a page reload finds a running job again. Nothing
// here ever writes 0x1010 except the separate Store on device dialog.

// replaceChildren without the null/false placeholders of optional parts.
function put(target, ...kids) { target.replaceChildren(...kids.flat().filter((c) => c !== null && c !== undefined && c !== false)); }

const OD_GROUPS = [["communication", "Communication (0x1000-0x1FFF)"], ["manufacturer", "Manufacturer (0x2000-0x5FFF)"],
  ["profile", "Device profile (0x6000-0x9FFF)"], ["other", "Other"]];
const WATCH_MAX = 32;
const WATCH_PERIODS = [500, 1000, 2000, 5000];
const JOB_NAMES = { read: "Reading all", backup: "Backing up", compare: "Comparing", restore_plan: "Reading the device", restore: "Restoring",
  configure_plan: "Reading the device", configure: "Writing the configuration", configure_verify: "Verifying" };

// Where the server gets a node's EDS: the draft config for a configured
// node, else the EDS a scan row opened it with.
function nodeSource(id) {
  if (onlineIsSlave()) {
    const s = onlineSlaveCfg();
    return s && s.eds ? { node: id, config: fileConfig(), port: diagPort() } : null;
  }
  const n = configNode(id);
  if (n && n.eds) return { node: id, config: fileConfig(), port: diagPort() };
  const p = (S.onlineEds || {})[id];
  return p ? { node: id, eds_path: p, port: diagPort() } : null;
}

function noEds(id) {
  return notice("info", `Node ${id} has no EDS here: add it to the configuration, or open it from a scan row with a matching EDS.`,
    { live: false, dataset: { online: "no-eds" } });
}

async function odEntries(id) {
  const src = odSource(id);
  const own = src.config ? onlineSlaveCfg() || configNode(id) : null;
  const key = src.standard ? JSON.stringify(["standard", src.device_type ?? null, src.rpdos || 4, src.tpdos || 4])
    : JSON.stringify([src.config ? own.eds : src.eds_path, own ? own.sdo || own.objects : null,
      own ? own.sdo_variables || (onlineSlaveCfg() ? S.model.top.gateway : null) : null]);
  S.odEntries = S.odEntries || {};
  const cached = S.odEntries[id];
  if (cached && cached.key === key) return cached.data;
  const data = await api("POST", "/api/online/od_entries", src);
  S.odEntries[id] = { key, data };
  return data;
}

// A node's object dictionary entry when its entries were loaded, else null.
function odEntryCached(id, index, sub) {
  const c = (S.odEntries || {})[id];
  return c ? c.data.entries.find((e) => sameObject(e.index, e.subindex, index, sub)) || null : null;
}

function nodeLive(id) {
  const st = S.onlineLast && S.onlineLast.status;
  return st ? (st.nodes || []).find((x) => x.node_id === id) || null : null;
}

function odKey(index, sub) { return `${index}:${sub}`; }

function hexBytes(h) { return (h || "").split(/\s+/).filter(Boolean).map((x) => parseInt(x, 16)); }

// Whether two values (hex bytes) of an EDS type are equal: numbers by value,
// strings without trailing NULs, anything else byte for byte.
function sameValue(a, b, type) {
  let A = hexBytes(a), B = hexBytes(b);
  const m = /^(INTEGER|UNSIGNED)(\d+)$/.exec(type || "");
  if (m || type === "BOOLEAN") {
    const val = (bytes) => {
      let v = 0n;
      bytes.forEach((x, k) => { v |= BigInt(x) << BigInt(8 * k); });
      if (m && m[1] === "INTEGER" && bytes.length && bytes[bytes.length - 1] & 0x80) v -= 1n << BigInt(8 * bytes.length);
      return v;
    };
    return val(A) === val(B);
  }
  if (type === "VISIBLE_STRING") {
    while (A.length && A[A.length - 1] === 0) A.pop();
    while (B.length && B[B.length - 1] === 0) B.pop();
  }
  return A.join(",") === B.join(",");
}

// A job's own message (failed, cancelled): a bar in the section's slot when
// the status has one (status.noticeSlot), else in the status itself, which then
// sits at the top of its section (consistent-message-bars).
function jobSay(status, kind, text, data) {
  const slot = status.noticeSlot;
  if (slot) { setNotice(slot, "job", kind, text, data ? { dataset: data } : null); return; }
  if (kind) status.append(notice(kind, text, data ? { dataset: data } : null));
}

// Follows a job until it ends, with progress and Cancel in `status`.
// onDone(job, resumed) gets the finished job (also a cancelled one).
async function followJob(j, status, onDone, resumed) {
  jobSay(status, null);
  const text = el("span", { class: "muted", dataset: { online: "job-progress" }, "aria-live": "polite" });
  const bar = el("progress", { max: 1, value: 0, "aria-label": JOB_NAMES[j.kind] || j.kind });
  const cancel = el("button", { type: "button", dataset: { online: "job-cancel" }, onclick: async () => {
    cancel.disabled = true;
    try { await api("POST", "/api/online/job", { id: j.id, cancel: true, port: diagPort() }); } catch (e) { /* shown by the next poll */ }
  } }, "Cancel");
  put(status, text, " ", bar, " ", cancel);
  while (j.state === "running") {
    text.textContent = `${JOB_NAMES[j.kind] || j.kind}: ${j.done} of ${j.total || "?"}${j.cancel_requested ? " (cancelling…)" : ""}`;
    bar.max = j.total || 1;
    bar.value = j.done;
    await new Promise((r) => setTimeout(r, 250));
    if (!status.isConnected) return null;  // the page moved on; the job goes on in the server
    try {
      j = (await api("POST", "/api/online/job", { id: j.id, port: diagPort() })).job;
    } catch (e) {
      put(status);
      jobSay(status, "error", e.message);
      return null;
    }
  }
  S.seenJobs = S.seenJobs || {};
  if (!S.seenJobs[j.id] && typeof commLogJob === "function") commLogJob(j);
  S.seenJobs[j.id] = true;
  put(status);
  if (j.state === "failed") {
    jobSay(status, "error", j.error, { online: "job-error" });
    return j;
  }
  if (j.state === "cancelled") jobSay(status, "info", "Cancelled.");
  if (j.result) onDone(j, !!resumed);
  return j;
}

async function startJob(path, body, status, onDone) {
  let r;
  try { r = await api("POST", path, body); } catch (e) {
    put(status);
    jobSay(status, "error", e.message);
    return null;
  }
  return followJob(r.job, status, onDone, false);
}

// A job for this node that is still running, or that ended while the page
// was not looking (a reload): followed again.
async function resumeJob(id, kinds, status, onDone) {
  let r;
  try { r = await api("POST", "/api/online/job", { port: diagPort() }); } catch (e) { return; }
  const j = r.job;
  if (!j || j.node !== id || !kinds.includes(j.kind) || (S.seenJobs || {})[j.id]) return;
  followJob(j, status, onDone, true);
}

function fileBase64(file) {
  return new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(r.result.split(",")[1] || "");
    r.onerror = () => reject(r.error);
    r.readAsDataURL(file);
  });
}

function downloadBase64(data, name, type) {
  const bytes = Uint8Array.from(atob(data), (c) => c.charCodeAt(0));
  const url = URL.createObjectURL(new Blob([bytes], { type: type || "application/octet-stream" }));
  const a = el("a", { href: url, download: name });
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 10000);
}

// -- object dictionary tab ----------------------------------------------------
// A tree of the node's EDS objects (improve-od-browser): one row per object,
// foldable ARRAY/RECORD objects, filters, value formats and bit views, PDO and
// compare marks, a watch list kept on this PC with a graph, and "Keep in
// configuration" after a live write.

// Bit names of known bit-field objects (CiA 301, and CiA 402 when 0x1000 says so).
// -- device notes (canopen-device-notes): a text, unit, scale, value names and
// bit names per object, from canworks' built-in CiA notes and the EDS's own
// notes file (<eds>.notes.json). Unsaved edits live in S.model.notes, so they
// mark the draft changed, undo like other edits and go with Save.
const NOTE_FIELDS = ["text", "details", "unit", "scale", "values", "bits", "manual"];
const NOTE_INHERITED = ["text", "details", "unit", "scale", "manual"];

function noteKey(index, sub) { return sub === null || sub === undefined ? hex4(num(index)) : `${hex4(num(index))}:${num(sub)}`; }
function noteEdits(name) { return (S.model && S.model.notes && S.model.notes[name]) || null; }
function notesOf(name) {
  const e = name && S.state && S.state.eds ? S.state.eds[name] : null;
  return e && e.notes ? e.notes : null;
}
function notesEditable(name) { const b = notesOf(name); return !!(b && b.editable && !b.error && !S.state.commission); }

// The device table with the page's unsaved edits: an edit replaces the
// entry's note fields and keeps its other keys (name, hand-written extras).
// A field of null clears the built-in or inherited field.
function applyNoteEdits(table, edits) {
  const out = Object.assign({}, table || {});
  for (const [k, v] of Object.entries(edits || {})) {
    if (v === null) { delete out[k]; continue; }
    const entry = {};
    for (const [f, x] of Object.entries(out[k] || {})) if (!NOTE_FIELDS.includes(f)) entry[f] = x;
    for (const f of NOTE_FIELDS) if (v[f] !== undefined && v[f] !== "") entry[f] = v[f];
    out[k] = entry;
  }
  return out;
}

// One table's note of a sub-object, with what it takes from its object's
// entry (a VAR's object entry is its own).
function noteLayer(table, index, sub, isVar) {
  const own = table[noteKey(index, sub)], obj = table[noteKey(index)];
  if (isVar && num(sub) === 0) return Object.assign({}, obj || {}, own || {});
  const out = {};
  if (obj) for (const f of NOTE_INHERITED) if (obj[f] !== undefined) out[f] = obj[f];
  return Object.assign(out, own || {});
}

// The merged note of a sub-object: device over built-in, field by field.
// `block` is an EDS's notes (state or od_entries), `name` the EDS whose
// unsaved edits apply (null: none).
function noteFor(block, name, index, sub, isVar) {
  if (!block) return {};
  const device = block.error ? {} : applyNoteEdits(block.device, name ? noteEdits(name) : null);
  const m = Object.assign(noteLayer(block.builtin || {}, index, sub, isVar), noteLayer(device, index, sub, isVar));
  const out = {};
  for (const f of NOTE_FIELDS) if (m[f] !== undefined && m[f] !== null && m[f] !== "") out[f] = m[f];
  return out;
}

function noteNumber(x) { return typeof x === "number" && !Number.isInteger(x) ? String(Number(x.toPrecision(6))) : String(x); }

// What a raw value means by a note: its name, else the scaled value with its
// unit, else the value with its unit; "" when the note says nothing.
function noteMeaning(note, raw) {
  if (raw === null || raw === undefined || !note) return "";
  if (note.values && note.values[String(raw)] !== undefined) return note.values[String(raw)];
  const unit = note.unit || "";
  if (typeof note.scale === "number" && note.scale !== 1 && note.scale !== 0) return noteNumber(Number(raw) * note.scale) + (unit ? " " + unit : "");
  return unit ? `${noteNumber(Number(raw))} ${unit}` : "";
}

// A value text with its meaning: "3 (profile velocity)" for a named value,
// "1234 (12.34 bar)" for a scaled one; the text as it is otherwise.
function withMeaning(note, text) {
  const m = /^(-?\d+(?:\.\d+)?)/.exec(String(text ?? ""));
  if (!m) return text ?? "";
  const raw = m[1].includes(".") ? parseFloat(m[1]) : parseInt(m[1], 10);
  const what = noteMeaning(note, raw);
  if (!what) return text;
  return note.values && note.values[String(raw)] !== undefined ? `${m[1]} (${what})` : `${text} (${what})`;
}

// A list of the note's named values for a value field, with "Other value…"
// for any other; null when the note names no values.
function valuePicker(note, input, set) {
  if (!note || !note.values || !Object.keys(note.values).length) return null;
  const entries = Object.entries(note.values).sort((a, b) => Number(a[0]) - Number(b[0]));
  const sel = el("select", { "aria-label": "Named value", dataset: { valuePick: "1" } },
    entries.map(([k, t]) => el("option", { value: k }, `${k} ${t}`)), el("option", { value: "" }, "Other value…"));
  const cur = String(input.value).trim();
  sel.value = entries.some(([k]) => k === cur) ? cur : "";
  sel.addEventListener("change", () => { if (sel.value !== "") set(sel.value); else input.focus(); });
  input.addEventListener("input", () => { const t = input.value.trim(); sel.value = entries.some(([k]) => k === t) ? t : ""; });
  return sel;
}

// What a note says about values, as one line: "unit bar; ×0.01; 0 = off,
// 1 = on" or "bit 0 = ready, ...". Long lists stop after six; `full` has all.
// null when the note gives no unit, scale, named values or bits.
const NOTE_LIST_MAX = 6;
function noteSummary(note) {
  if (!note) return null;
  const list = (m, pre) => Object.entries(m || {}).sort((a, b) => Number(a[0]) - Number(b[0])).map(([k, v]) => `${pre}${k} = ${v}`);
  const head = [];
  if (note.unit) head.push("unit " + note.unit);
  if (typeof note.scale === "number" && note.scale !== 1 && note.scale !== 0) head.push("×" + noteNumber(note.scale));
  const lists = [list(note.values, ""), list(note.bits, "bit ")].filter((l) => l.length);
  if (!head.length && !lists.length) return null;
  const full = head.concat(lists.map((l) => l.join(", "))).join("; ");
  const short = head.concat(lists.map((l) => l.length > NOTE_LIST_MAX ? l.slice(0, NOTE_LIST_MAX).join(", ") + ", …" : l.join(", "))).join("; ");
  return { short, full };
}

// The note under an object's name: its text, then what it says about values
// (noteSummary); details, manual and a cut value list in full on hover.
function noteLine(note) {
  if (!note) return null;
  const sum = noteSummary(note);
  if (!note.text && !note.details && !note.manual && !sum) return null;
  const title = [note.details, note.manual ? "Manual: " + note.manual : "", sum && sum.short !== sum.full ? sum.full : ""].filter(Boolean).join("\n");
  return el("div", { class: "muted note-text", title: title || null, dataset: { note: "text" } },
    note.text || (sum ? null : "More in the note"),
    sum ? el("div", { class: "note-meaning", dataset: { note: "meaning" } }, sum.short) : null);
}

// A picker row matches the filter text by index, name or note text.
function objectMatches(o, f, note) {
  return !f || o.index.toLowerCase().includes(f) || (o.name || "").toLowerCase().includes(f)
    || !!(note && note.text && note.text.toLowerCase().includes(f));
}

function noteLines(map) { return Object.entries(map || {}).map(([k, v]) => `${k} = ${v}`).join("\n"); }

// "3 = profile velocity" lines as {"3": "profile velocity"}; throws on a bad line.
function parseNoteLines(text, what, pattern) {
  const out = {};
  for (const line of text.split(/\r?\n/)) {
    if (!line.trim()) continue;
    const m = /^\s*(-?\d+)\s*[=:]\s*(.+?)\s*$/.exec(line);
    if (!m || !pattern.test(m[1])) throw new Error(`${what}: "${line.trim()}" is not "number = meaning".`);
    out[String(parseInt(m[1], 10))] = m[2];
  }
  return out;
}

// The note editor of one object or sub-object of an EDS. Only the fields
// that differ from the built-in note are kept in the device notes.
// The note a sub-object shows without its own device entry: built-in, and
// what it inherits from its object's device entry. What the editor clears.
function noteUnder(block, name, index, sub, isVar, key) {
  const edits = Object.assign({}, name ? noteEdits(name) || {} : {}, { [key]: null });
  const device = block.error ? {} : applyNoteEdits(block.device, edits);
  const m = Object.assign(noteLayer(block.builtin || {}, index, sub, isVar), noteLayer(device, index, sub, isVar));
  const out = {};
  for (const f of NOTE_FIELDS) if (m[f] !== undefined && m[f] !== null && m[f] !== "") out[f] = m[f];
  return out;
}

const NOTE_TEXT = { values: noteLines, bits: noteLines };

// `commit` (Commission a device): writes the change at once instead of the
// draft; resolves to whether it was written.
async function editNote(name, block, index, sub, isVar, label, commit) {
  const key = isVar && num(sub) === 0 ? noteKey(index) : noteKey(index, sub);
  const cur = noteFor(block, name, index, sub, isVar);
  const base = noteUnder(block, name, index, sub, isVar, key);
  const shown = (f, v) => v === undefined ? "" : NOTE_TEXT[f] ? NOTE_TEXT[f](v) : String(v);
  const hiddenHint = (f) => `${shown(f, base[f]).split("\n")[0]}${NOTE_TEXT[f] && Object.keys(base[f]).length > 1 ? " …" : ""} (built-in, hidden)`;
  // A field that shows a built-in or inherited value: emptied, it is saved as
  // null (hidden); its placeholder then names the hidden value and "Use
  // built-in" puts it back.
  const restore = {};
  const hint = (f, x) => {
    if (base[f] === undefined) return;
    const btn = el("button", { type: "button", class: "link", dataset: { noteRestore: f }, title: "Show the built-in value again",
      onclick: () => { x.value = shown(f, base[f]); sync(); } }, "Use built-in");
    const sync = () => { const empty = !x.value.trim(); x.placeholder = empty ? hiddenHint(f) : ""; x.classList.toggle("note-hidden", empty); btn.hidden = x.value === shown(f, base[f]); };
    x.addEventListener("input", sync);
    restore[f] = { btn, sync };
  };
  const input = (f, attrs) => { const x = el("input", Object.assign({ type: "text", dataset: { noteField: f } }, attrs || {})); x.value = shown(f, cur[f]); hint(f, x); return x; };
  const area = (f, value, rows) => { const x = el("textarea", { rows, dataset: { noteField: f } }); x.value = value; hint(f, x); return x; };
  const withRestore = (f, labelText, x) => el("label", null, labelText, x, restore[f] ? restore[f].btn : null);
  const f = {
    text: input("text", { maxlength: 200 }), details: area("details", cur.details || "", 3), unit: input("unit", { maxlength: 20, class: "short" }),
    scale: input("scale", { class: "short", placeholder: "1" }), values: area("values", noteLines(cur.values), 4),
    bits: area("bits", noteLines(cur.bits), 4), manual: input("manual"),
  };
  // Why the note was not taken: a bar at the top of the dialog's form.
  const msg = noticeSlot();
  const form = el("div", { class: "note-editor", dataset: { noteEditor: key } }, msg,
    withRestore("text", "Text (one line)", f.text), withRestore("details", "Details", f.details),
    el("div", { class: "row" }, withRestore("unit", "Unit", f.unit), withRestore("scale", "Scale (shown = raw × scale)", f.scale)),
    withRestore("values", "Value meanings, one per line: 3 = profile velocity", f.values),
    withRestore("bits", "Bit names, one per line: 0 = ready", f.bits),
    withRestore("manual", "Manual reference", f.manual),
    Object.keys(base).length
      ? el("p", { class: "muted" }, "Starts from canworks' built-in note; only what you change is kept in " + (block.file || name + ".notes.json") + ". Empty a field to hide its built-in value.") : null);
  for (const r of Object.values(restore)) r.sync();
  for (;;) {
    const v = await modal(`Note for ${label}`, [["cancel", "Cancel"], ["clear", "Remove my note"], ["save", "Keep note", true]], form);
    if (v !== "save" && v !== "clear") return false;
    let entry = {};
    if (v === "save") {
      try {
        const scale = f.scale.value.trim();
        if (scale !== "" && (!Number.isFinite(Number(scale)) || Number(scale) === 0)) throw new Error("Scale must be a number other than 0.");
        const got = { text: f.text.value.replace(/[\r\n]+/g, " ").trim(), details: f.details.value.trim(), unit: f.unit.value.trim(),
          scale: scale === "" ? undefined : Number(scale), values: parseNoteLines(f.values.value, "Value meanings", /^-?\d+$/),
          bits: parseNoteLines(f.bits.value, "Bit names", /^([0-9]|[1-5][0-9]|6[0-3])$/), manual: f.manual.value.trim() };
        if (!Object.keys(got.values).length) got.values = undefined;
        if (!Object.keys(got.bits).length && !(base.bits && !Object.keys(base.bits).length)) got.bits = undefined;
        for (const k of NOTE_FIELDS) {
          const x = got[k];
          if (x === undefined || x === "") {
            if (base[k] !== undefined && !(k === "bits" && !Object.keys(base.bits).length)) entry[k] = null;  // hidden
            continue;
          }
          if (JSON.stringify(x) === JSON.stringify(base[k])) continue;
          entry[k] = x;
        }
      } catch (e) { setNotice(msg, "save", "error", e.message); continue; }
    }
    if (commit) return commit({ [key]: entry }, label);
    S.model.notes = S.model.notes || {};
    S.model.notes[name] = S.model.notes[name] || {};
    S.model.notes[name][key] = entry;
    changed(false);
    return true;
  }
}

const OD_FILTERS = [["lacking", "Hide objects the device lacks"], ["changed", "Changed from default"], ["writable", "Writable"],
  ["owned", "Set by config or SDO variable"], ["pdo", "In a PDO"], ["failed", "Not readable"], ["compare", "Different in last compare"]];
const OD_NUMERIC = ["BOOLEAN", "INTEGER8", "INTEGER16", "INTEGER32", "INTEGER64", "UNSIGNED8", "UNSIGNED16",
  "UNSIGNED32", "UNSIGNED64", "REAL32", "REAL64"];  // the startup SDO types (co_type)
const WATCH_HISTORY_MS = 10 * 60 * 1000;

function odState(id) {
  S.od = S.od || {};
  return S.od[id] || (S.od[id] = { values: {}, watch: [], period: 1000, filter: "", filters: [], formats: {},
    bitsOpen: {}, openGroups: [], openObjects: [], at: {}, changedAt: {}, mm: {}, hist: [], keep: {}, selected: null });
}

// Puts an od_read answer's values and failures into a node's tab state.
function odStore(st, res, watchRound) {
  const now = Date.now();
  for (const v of res.values || []) {
    const key = odKey(v.index, v.subindex);
    const old = st.values[key];
    if (watchRound && old && !old.error && old.data !== v.data) st.changedAt[key] = now;
    st.values[key] = { data: v.data, text: v.text };
    st.at[key] = now;
  }
  for (const f of res.failures || []) {
    if (st.standard && (f.abort_code === SDO_NO_OBJECT || f.abort_code === SDO_NO_SUB)) {
      st.values[odKey(f.index, f.subindex)] = { error: "Not on this device", lacking: true, code: f.abort_code };
      st.at[odKey(f.index, f.subindex)] = now;
      continue;
    }
    st.values[odKey(f.index, f.subindex)] = { error: (f.abort_code !== null && f.abort_code !== undefined ? `Abort ${hex8(f.abort_code)}: ` : "") + f.error };
    st.at[odKey(f.index, f.subindex)] = now;
  }
}

// The standard dictionary: how many sub-indices object `o` has, from its
// sub-index 0 as read; null when not read (or not readable).
function odCount(st, o) {
  const v = st.values[odKey(o.index, 0)];
  if (!v || v.error || !v.data) return null;
  return parseInt(v.data.split(" ")[0], 16);
}

// The entries of a standard object that are shown: up to the count read
// from its sub-index 0; before that an ARRAY's 0 and 1, a RECORD's all.
function odLimited(st, o) {
  const all = o.all || o.entries;
  if (o.type === "VAR" || !all.length || all[0].subindex !== 0) return all;
  const count = odCount(st, o);
  if (count === null) return o.type === "ARRAY" ? all.filter((e) => e.subindex <= 1) : all;
  return all.filter((e) => e.subindex <= count);
}

// The objects of the standard dictionary the device lacks: a read of one
// of their entries was refused as "object does not exist".
function odLackSet(st, objects) {
  const out = new Set();
  for (const o of objects) {
    for (const x of o.all || o.entries) {
      const w = st.values[odKey(x.index, x.subindex)];
      if (w && w.code === SDO_NO_OBJECT) { out.add(o.index); break; }
    }
  }
  return out;
}

// After a write, a restore or a compare: the values it read (an od_read
// answer, or null) and the keys it wrote, whose shown value is no longer
// the device's; the open object dictionary tab shows them at once.
function odTake(id, res, written) {
  const st = odState(id);
  for (const key of written || []) { delete st.values[key]; delete st.at[key]; }
  if (res) odStore(st, res);
  if (st.refreshMarks) st.refreshMarks();
}

function intInfo(type) {
  const m = /^(INTEGER|UNSIGNED)(\d+)$/.exec(type || "");
  return m ? { signed: m[1] === "INTEGER", bytes: Number(m[2]) / 8 } : null;
}

// The value of hex bytes as a BigInt (integers), a Number (REAL, BOOLEAN) or null.
function odNumber(data, type) {
  const bytes = hexBytes(data);
  const it = intInfo(type);
  if (it) {
    if (!bytes.length) return null;
    let v = 0n;
    bytes.forEach((x, k) => { v |= BigInt(x) << BigInt(8 * k); });
    if (it.signed && bytes[bytes.length - 1] & 0x80) v -= 1n << BigInt(8 * bytes.length);
    return v;
  }
  if (type === "BOOLEAN") return bytes.length ? (bytes[0] ? 1 : 0) : null;
  if ((type === "REAL32" && bytes.length === 4) || (type === "REAL64" && bytes.length === 8)) {
    const dv = new DataView(new Uint8Array(bytes).buffer);
    return type === "REAL32" ? dv.getFloat32(0, true) : dv.getFloat64(0, true);
  }
  return null;
}

function odPlain(v) { return typeof v === "bigint" ? Number(v) : v; }

// A read value as text in the entry's chosen format: dec (the decoded text),
// hex or bin (two's complement bits for INTEGER types).
function odText(v, e, fmt) {
  if (!v || v.error) return v ? v.error : "";
  const it = intInfo(e.type);
  if (!it || fmt === "dec" || !fmt) return v.text;
  const bytes = hexBytes(v.data);
  let u = 0n;
  bytes.forEach((x, k) => { u |= BigInt(x) << BigInt(8 * k); });
  const width = bytes.length || it.bytes;
  if (fmt === "hex") return "0x" + u.toString(16).toUpperCase().padStart(width * 2, "0");
  return "0b" + u.toString(2).padStart(width * 8, "0").replace(/(.{4})(?=.)/g, "$1 ");
}

// The merged notes of an online node, as (index, sub) -> note: its config
// EDS's (with unsaved edits), else the EDS its object dictionary was read with.
function nodeNotes(id) {
  const src = nodeSource(id);
  const cfgNode = src && src.config && !onlineSlaveCfg() ? configNode(id) : null;
  const name = cfgNode && cfgNode.eds ? cfgNode.eds : null;
  const cached = S.odEntries && S.odEntries[id] ? S.odEntries[id].data : null;
  const block = (name && notesOf(name)) || (cached && cached.notes) || null;
  const vars = {};
  const eds = name ? (S.state.eds || {})[name] : null;
  if (eds && eds.objects) for (const o of eds.objects) vars[num(o.index)] = !!o.var;
  else if (cached) for (const e of cached.entries) vars[e.index] = e.object_type === "VAR";
  return (index, sub) => noteFor(block, name, index, sub, !!vars[num(index)]);
}

// The names of the set bits of an entry whose note names its bits, or null.
function odBitNames(e, v, note) {
  if (!note || !note.bits || !v || v.error) return null;
  const it = intInfo(e.type);
  if (!it) return null;
  let n = odNumber(v.data, e.type);
  if (n === null) return null;
  if (n < 0n) n += 1n << BigInt(8 * it.bytes);
  const out = [];
  for (let b = 0; b < it.bytes * 8; b++) if ((n >> BigInt(b)) & 1n) out.push(note.bits[String(b)] || `bit ${b}`);
  return out;
}

function odPdoText(m) {
  return `${m.pdo} ` + (m.bits[0] === m.bits[1] ? `bit ${m.bits[0]}` : `bits ${m.bits[0]}-${m.bits[1]}`) + (m.location ? `, ${m.location}` : "");
}

function odLimitText(e) {
  const lo = e.low_limit, hi = e.high_limit;
  if (lo === undefined && hi === undefined) return "";
  return `EDS limits: ${lo !== undefined ? lo : "…"} to ${hi !== undefined ? hi : "…"}`;
}

// Why "Keep in configuration" cannot be offered for an entry, or null.
function keepReason(e, n) {
  if (e.sdo_variable) return "An SDO variable writes this entry from the program.";
  if (pluginObject(e.index)) return `The plugin sets ${hex4(e.index)} itself` +
    (e.index === 0x1017 ? " from the node's heartbeat setting." : e.index >= 0x1400 && e.index <= 0x1BFF ? " from the node's PDO settings." : ".");
  if (!OD_NUMERIC.includes(e.type)) return "Startup SDOs take numbers only.";
  if (!["rw", "rwr", "rww", "wo"].includes(e.access)) return "The entry is not writable.";
  if (e.config && !(n.sdo || []).some((s) => sameObject(s.index, s.subindex, e.index, e.subindex)))
    return "Another setting of the configuration writes this entry at boot.";
  return null;
}

// The startup SDO value of a read value: a JSON number, a decimal string for
// 64-bit integers past 2^53, true/false for BOOLEAN.
function keepValue(e, v) {
  const n = odNumber(v.data, e.type);
  if (n === null) return null;
  if (e.type === "BOOLEAN") return !!n;
  if (typeof n === "bigint") return n >= -(2n ** 53n) && n <= 2n ** 53n ? Number(n) : n.toString();
  return n;
}

function keepInConfig(id, e, v) {
  const i = (S.config.nodes || []).findIndex((x) => num(x.node_id) === id);
  const n = S.config.nodes[i];
  const value = i < 0 ? null : keepValue(e, v);
  if (value === null) return false;
  n.sdo = n.sdo || [];
  const j = n.sdo.findIndex((s) => sameObject(s.index, s.subindex, e.index, e.subindex));
  if (j >= 0) n.sdo[j].value = value;
  else n.sdo.push({ index: hex4(e.index), subindex: e.subindex, type: e.type, value });
  changed();
  banner(`Node ${id}: startup SDO ${hex4(e.index)}:${e.subindex} = ${value} ${j >= 0 ? "changed" : "added"} in the configuration. Save to keep it.`);
  return true;
}

function csvField(s) { s = String(s ?? ""); return /[",\n\r]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s; }

function odPanel(id, n, allow) {
  const box = el("div", { class: "od-panel", dataset: { online: "od" } });
  if (!odSource(id)) { put(box, noEds(id)); return box; }
  put(box, el("p", { class: "muted" }, "Loading the object dictionary…"));
  odEntries(id).then((data) => odBuild(box, id, n, allow, data))
    .catch((e) => put(box, notice("error", e.message)));
  return box;
}

function odBuild(box, id, n, allow, data) {
  const st = odState(id);
  const build = {};
  st.build = build;
  const byKey = {};
  for (const e of data.entries) byKey[odKey(e.index, e.subindex)] = e;
  const objects = [];  // {index, group, name, type, entries}
  for (const e of data.entries) {
    const last = objects[objects.length - 1];
    if (last && last.index === e.index) { last.entries.push(e); continue; }
    objects.push({ index: e.index, group: e.group, type: e.object_type || "VAR", name: e.object || e.sub_name || e.name, entries: [e] });
  }
  // The standard dictionary (no EDS): an ARRAY or RECORD shows the
  // sub-indices up to what its sub-index 0 says once read (an ARRAY 0 and 1
  // before that); objects the device lacks are hidden by a filter, on by default.
  st.standard = !!data.standard;
  if (data.standard) {
    st.standardType = odSource(id).device_type ?? null;
    if (!st.lackInit) { st.lackInit = true; if (!st.filters.includes("lacking")) st.filters.push("lacking"); }
    for (const o of objects) {
      o.all = o.entries;
      o.entries = odLimited(st, o);
    }
  }
  let lackSet = new Set();  // objects the device lacks (sub-index 0 or the object refused as not existing)
  const limitSig = () => objects.map((o) => (o.all ? odLimited(st, o).length : "")).join(",");
  const sig = limitSig();
  const cells = {};  // key: {tr, value, marks, edit, editing}
  const objRows = {};  // index: {tr, sub rows, summary}
  // The tab's messages (standard dictionary, locked, the EDS's note, Read all's end) at its top.
  const slot = noticeSlot({ dataset: { online: "od-notices" } });
  const status = el("div", { class: "job-status", dataset: { online: "od-status" } });
  status.noticeSlot = slot;
  const summary = el("div", { class: "muted", dataset: { online: "od-summary" } });
  // Notes: the config node's EDS (with unsaved edits; written on the Notes tab), else the EDS the view was opened with.
  const notesCfg = odSource(id).config && !onlineSlaveCfg() ? configNode(id) : null;
  const notesName = notesCfg && notesCfg.eds ? notesCfg.eds : null;
  const notesBlock = () => (notesName && notesOf(notesName)) || data.notes;
  const noteOf = (e) => noteFor(notesBlock(), notesName, e.index, e.subindex, e.object_type === "VAR");
  if (st.plot) { st.plot.destroy(); st.plot = null; }
  // A slave's own dictionary: its PDO marks from the mappings in force.
  const slaveNow = data.slave && S.onlineLast && S.onlineLast.status && S.onlineLast.status.slave;
  if (slaveNow) {
    const marks = slavePdoMarks(slaveNow);
    for (const e of data.entries) e.pdo = marks[odKey(e.index, e.subindex)];
  }

  const marksOf = (e) => {
    const key = odKey(e.index, e.subindex);
    const v = st.values[key];
    const out = [];
    if (e.config) out.push(["set by config", "The configuration writes this entry when the node boots.", "mark-config"]);
    if (e.sdo_variable) out.push(["SDO variable" + (typeof e.sdo_variable === "string" ? " " + e.sdo_variable : ""), "An SDO variable of the program writes this entry.", "mark-sdo-var"]);
    for (const m of e.pdo || []) out.push([odPdoText(m), "Carried in this PDO; values shown here are read over SDO.", "mark-pdo"]);
    if (e.slave_bind) {
      out.push(e.slave_bind.route ? ["route " + e.slave_bind.route, "A gateway route's object on this slave.", "mark-slave-bind"]
        : [[e.slave_bind.iec_location, e.slave_bind.name].filter(Boolean).join(" "), "Bound to this PLC location in the configuration.", "mark-slave-bind"]);
    }
    if (v && !v.error && e.default_data !== null && e.default_data !== undefined && !sameValue(v.data, e.default_data, e.type))
      out.push(["≠ default", "The EDS default is " + e.default, "differs", true]);
    const c = st.compare && st.compare.rows[key];
    if (c) {
      if (c.result === "different") out.push([`≠ ${st.compare.short}: ${c.reference ?? ""}`, `Different from ${st.compare.label} in the last compare`, "mark-compare", true]);
      else if (c.result === "equal") out.push([`= ${st.compare.short}`, `Equal to ${st.compare.label} in the last compare`, "mark-compare"]);
      else if (c.result === "not readable") out.push(["not readable in compare", c.error || "", "mark-compare", true]);
    }
    return out;
  };
  const passes = (e, f) => {
    const key = odKey(e.index, e.subindex);
    const v = st.values[key];
    if (f === "changed") return !!(v && !v.error && e.default_data != null && !sameValue(v.data, e.default_data, e.type));
    if (f === "writable") return !!e.writable;
    if (f === "owned") return !!(e.config || e.sdo_variable || e.slave_bind);
    if (f === "pdo") return !!(e.pdo && e.pdo.length);
    if (f === "failed") return !!(v && v.error);
    if (f === "compare") return !!(st.compare && st.compare.rows[key] && st.compare.rows[key].result !== "equal");
    if (f === "lacking") { const v = st.values[odKey(e.index, e.subindex)]; return !(v && v.lacking) && !lackSet.has(e.index); }
    return true;
  };

  const showValue = (key) => {
    const c = cells[key];
    const e = byKey[key];
    if (!c) return;
    put(c.marks, marksOf(e).map(([t, title, ds, warn]) => el("span", { class: "tag" + (warn ? " warn-tag" : ""), title, dataset: { online: ds } }, t)));
    if (c.editing) return;
    const v = st.values[key];
    put(c.value);
    c.value.className = "od-value";
    if (!v) return;
    if (v.error) { c.value.append(el("span", { class: "field-msg" }, v.error)); return; }
    if (e.default_data != null && !sameValue(v.data, e.default_data, e.type)) c.value.classList.add("differs");
    c.value.append(el("strong", { dataset: { online: "od-shown" } }, odText(v, e, st.formats[key])));
    const note = noteOf(e);
    const raw = odNumber(v.data, e.type);
    const what = raw === null ? "" : noteMeaning(note, typeof raw === "bigint" && raw >= -(2n ** 53n) && raw <= 2n ** 53n ? Number(raw) : raw);
    if (what) c.value.append(" ", el("span", { class: "muted", dataset: { online: "od-meaning" } }, `(${what})`));
    const it = intInfo(e.type);
    const bits = odBitNames(e, v, note);
    const tools = el("span", { class: "od-tools" });
    if (it) {
      const fmt = el("select", { class: "od-format", "aria-label": "Format", dataset: { online: "od-format" } },
        [["dec", "dec"], ["hex", "hex"], ["bin", "bin"]].map(([k, l]) => el("option", { value: k }, l)));
      fmt.value = st.formats[key] || "dec";
      fmt.addEventListener("change", () => { st.formats[key] = fmt.value; showValue(key); renderWatch(); });
      tools.append(fmt);
    }
    if (bits) {
      tools.append(el("button", { type: "button", class: "small", dataset: { online: "od-bits" },
        onclick: () => { st.bitsOpen[key] = !st.bitsOpen[key]; showValue(key); } }, st.bitsOpen[key] ? "Hide bits" : "Bits"));
    }
    if (tools.childNodes.length) c.value.append(" ", tools);
    // The entry's bit channels in the configuration: each with its name and state.
    const channels = it && notesCfg ? bitChannelsOf(notesCfg, e) : [];
    let raw64 = channels.length ? odNumber(v.data, e.type) : null;
    if (typeof raw64 === "bigint") {
      if (raw64 < 0n) raw64 += 1n << BigInt(8 * it.bytes);
      c.value.append(el("div", { class: "od-bits", dataset: { online: "od-bit-channels" } }, channels.map((ch) => {
        const on = ((raw64 >> BigInt(ch.bit)) & 1n) === 1n;
        return el("span", { class: "tag" + (on ? " bit-on" : ""), title: `Bit ${ch.bit}: ${on ? "on" : "off"}`, dataset: { bitChannel: ch.name, state: on ? "on" : "off" } },
          `${ch.name} ${on ? "on" : "off"}`);
      })));
    }
    if (bits && st.bitsOpen[key]) {
      c.value.append(el("div", { class: "od-bits", dataset: { online: "od-bit-list" } },
        bits.length ? bits.map((b) => el("span", { class: "tag" }, b)) : el("span", { class: "muted" }, "no bit set")));
    }
    if (st.keep[key] && n && !data.slave) {
      const why = keepReason(e, n);
      c.value.append(el("div", { class: "od-keep" }, why
        ? el("span", { class: "muted", dataset: { online: "od-keep-reason" } }, "Not kept in the configuration: " + why)
        : el("button", { type: "button", class: "small", dataset: { online: "od-keep" }, title: "Add this value as a startup SDO, so the node gets it at every boot (nothing is stored on the device)",
          onclick: () => {
            // The value written, not the read-back: a PDO may have overwritten that.
            const kept = typeof st.keep[key] === "string" ? { data: st.keep[key] } : v;
            delete st.keep[key];
            if (keepInConfig(id, e, kept)) e.config = true;
            showValue(key);
            applyFilter();
          } }, "Keep in configuration")));
    }
  };
  const updateObject = (index) => {
    const o = objRows[index];
    if (!o || !o.summary) return;
    let differs = 0, failed = 0, read = 0;
    for (const e of o.obj.entries) {
      const v = st.values[odKey(e.index, e.subindex)];
      if (!v) continue;
      if (v.error) failed++;
      else {
        read++;
        if (e.default_data != null && !sameValue(v.data, e.default_data, e.type)) differs++;
      }
    }
    put(o.summary, read || failed ? el("span", { class: "muted" }, `${read} read`) : null,
      differs ? el("span", { class: "tag warn-tag", dataset: { online: "od-obj-differs" } }, `${differs} ≠ default`) : null,
      failed ? el("span", { class: "tag warn-tag" }, `${failed} not readable`) : null);
  };
  const setReading = (res, watchRound) => {
    odStore(st, res, watchRound);
    // A later build of this tab (a sub-index 0 read changed what it shows) draws the values.
    if (st.build !== build) { if (st.refreshMarks) st.refreshMarks(); return; }
    if (data.standard && limitSig() !== sig) { odBuild(box, id, n, allow, data); return; }
    const touched = new Set();
    for (const v of (res.values || []).concat(res.failures || [])) { showValue(odKey(v.index, v.subindex)); touched.add(v.index); }
    for (const i of touched) updateObject(i);
    renderWatch();
  };
  const readKeys = async (keys, watchRound) => {
    const res = await api("POST", "/api/online/od_read", Object.assign(odSource(id), { keys }));
    setReading(res, watchRound);
    return res;
  };
  const readObject = async (o) => {
    if (o.all && o.type !== "VAR" && o.all[0].subindex === 0 && o.all[0].readable) {
      // Sub-index 0 first: it says how many of the others the device has.
      await readKeys([[o.index, 0]]);
      const count = odCount(st, o);
      if (count === null) return;
      const rest = o.all.filter((e) => e.readable && e.subindex > 0 && e.subindex <= count).map((e) => [e.index, e.subindex]);
      for (let i = 0; i < rest.length; i += 64) await readKeys(rest.slice(i, i + 64));
      return;
    }
    const keys = o.entries.filter((e) => e.readable).map((e) => [e.index, e.subindex]);
    for (let i = 0; i < keys.length; i += 64) await readKeys(keys.slice(i, i + 64));
  };

  // -- watch list: kept on this PC per project and node; values, age, min/max and a graph.
  const watchBox = el("div", { dataset: { online: "watch" } });
  // The watch list's warnings at its top; the time a round of reads takes is a figure under its toolbar.
  const watchInfo = noticeSlot({ dataset: { online: "watch-info" } });
  const watchStat = el("div", { class: "muted", dataset: { online: "watch-stat" } });
  const graphBox = el("div", { class: "watch-graph", dataset: { online: "watch-graph" } });
  const period = el("select", { "aria-label": "Watch period", dataset: { online: "watch-period" } },
    WATCH_PERIODS.map((p) => el("option", { value: p }, p < 1000 ? `${p} ms` : `${p / 1000} s`)));
  const saveWatch = () => {
    api("POST", "/api/online/watch", { node: id, keys: st.watch.map((k) => k.split(":").map(Number)), period_ms: st.period })
      .catch((e) => banner(e.message, true));
  };
  period.addEventListener("change", () => { st.period = Number(period.value); saveWatch(); renderWatch(); });
  const numericKey = (key) => { const e = byKey[key]; return !!e && (!!intInfo(e.type) || ["BOOLEAN", "REAL32", "REAL64"].includes(e.type)); };
  const sdoVarsNote = () => n && (n.sdo_variables || []).some((v) => (v.direction || "read") === "read" && num(v.period_ms) > 0);
  const graphButton = el("button", { type: "button", class: "small", dataset: { online: "watch-graph-toggle" },
    onclick: () => { st.graphOpen = !st.graphOpen; renderWatch(); } });
  const resetButton = el("button", { type: "button", class: "small", dataset: { online: "watch-reset" },
    onclick: () => { st.mm = {}; renderWatch(); } }, "Reset min/max");
  const fmtNum = (x) => (x === undefined || x === null ? "" : typeof x === "number" && !Number.isInteger(x) ? x.toPrecision(6) : String(x));
  // The Watch list card only while something is watched; a hint line under the filters before that.
  const watchHint = el("p", { class: "muted", dataset: { online: "watch-hint" } },
    `Tick Watch on an entry to read it again and again (up to ${WATCH_MAX} entries).`);
  const watchCard = el("fieldset", { dataset: { online: "watch-card" } }, el("legend", null, "Watch list"), watchInfo,
    el("div", { class: "toolbar" }, el("label", { class: "inline" }, "Every ", period), graphButton, resetButton), watchStat, watchBox, graphBox);
  const renderWatch = () => {
    graphButton.textContent = st.graphOpen ? "Hide graph" : "Graph";
    watchCard.hidden = !st.watch.length;
    watchHint.hidden = !!st.watch.length;
    if (!st.watch.length) {
      put(watchBox);
      put(watchInfo);
      put(watchStat);
      put(graphBox);
      if (st.plot) { st.plot.destroy(); st.plot = null; }
      return;
    }
    const now = Date.now();
    put(watchBox, el("table", { class: "od watch" },
      el("thead", null, el("tr", null, thCells(["Entry", "Name", "Value", "Age", "Min", "Max", ""]))),
      el("tbody", null, st.watch.map((key) => {
        const e = byKey[key];
        const v = st.values[key];
        const mm = st.mm[key] || {};
        const age = st.at[key] ? ((now - st.at[key]) / 1000).toFixed(1) + " s" : "";
        return el("tr", { class: st.changedAt[key] && now - st.changedAt[key] < 3000 ? "changed" : null, dataset: { watchKey: key } },
          el("td", { class: "mono" }, `${hex4(e.index)}:${e.subindex}`), el("td", { class: "od-name" }, e.name),
          el("td", { class: "od-value" }, v ? (v.error ? el("span", { class: "field-msg" }, v.error) : el("strong", null, odText(v, e, st.formats[key]))) : ""),
          el("td", { dataset: { online: "watch-age" } }, age), el("td", { dataset: { online: "watch-min" } }, fmtNum(mm.min)),
          el("td", { dataset: { online: "watch-max" } }, fmtNum(mm.max)),
          el("td", null, el("button", { type: "button", class: "small", "aria-label": "Stop watching", title: "Stop watching",
            onclick: () => setWatched(key, false) }, "×")));
      }))));
    const slow = st.lastRound !== undefined && st.lastRound > st.period;
    put(watchStat, st.lastRound !== undefined && !slow ? el("span", { dataset: { online: "watch-round" } }, `A round of reads takes ${st.lastRound} ms.`) : null);
    put(watchInfo, byKind([
      slow ? noteBar("warning", `A round of reads takes ${st.lastRound} ms, longer than the chosen ${st.period >= 1000 ? st.period / 1000 + " s" : st.period + " ms"}.`,
        { online: "watch-round" }) : null,
      sdoVarsNote() ? noteBar("warning",
        "This node has SDO variables the program reads periodically; watch reads go before them on the bus and may delay them.", { online: "watch-sdo-vars" }) : null]));
    drawGraph();
  };
  const drawGraph = () => {
    if (!st.graphOpen) { put(graphBox); if (st.plot) { st.plot.destroy(); st.plot = null; } return; }
    const keys = st.watch.filter(numericKey);
    if (!keys.length) { put(graphBox, el("p", { class: "muted" }, "No numeric entry is watched.")); return; }
    const t0 = st.hist.length ? st.hist[0].t : Date.now();
    const x = st.hist.map((h) => (h.t - t0) / 1000);
    const data = [x, ...keys.map((k) => st.hist.map((h) => (h.v[k] === undefined ? null : h.v[k])))];
    const sig = keys.join(",");
    const width = Math.max(300, (graphBox.clientWidth || box.clientWidth || 600) - 4);
    if (st.plot && st.plotKeys === sig && graphBox.contains(st.plot.root)) { st.plot.setData(data); return; }
    if (st.plot) st.plot.destroy();
    put(graphBox);
    const muted = themeColor("--muted"), line = themeColor("--line"), colors = seriesColors();
    st.plotKeys = sig;
    st.plot = new uPlot({ width, height: 220, legend: { show: true, live: true },
      series: [{ label: "t (s)" }].concat(keys.map((k, i) => ({ label: `${hex4(byKey[k].index)}:${byKey[k].subindex} ${byKey[k].sub_name || byKey[k].name}`,
        stroke: colors[i % colors.length], width: 1.5, spanGaps: true }))),
      scales: { x: { time: false } },
      axes: [{ stroke: muted, grid: { stroke: line, width: 1 }, ticks: { stroke: line }, label: "seconds", labelSize: 18 },
        { stroke: muted, grid: { stroke: line, width: 1 }, ticks: { stroke: line }, size: 60 }] }, data, graphBox);
    graphBox.dataset.points = String(x.length);
  };
  const recordRound = () => {
    const now = Date.now();
    const vals = {};
    for (const key of st.watch) {
      const v = st.values[key];
      const e = byKey[key];
      if (!v || v.error || !numericKey(key)) continue;
      const x = odPlain(odNumber(v.data, e.type));
      if (x === null || Number.isNaN(x)) continue;
      vals[key] = x;
      const mm = st.mm[key] || (st.mm[key] = {});
      if (mm.min === undefined || x < mm.min) mm.min = x;
      if (mm.max === undefined || x > mm.max) mm.max = x;
    }
    st.hist.push({ t: now, v: vals });
    while (st.hist.length && now - st.hist[0].t > WATCH_HISTORY_MS) st.hist.shift();
    if (graphBox.isConnected) graphBox.dataset.points = String(st.hist.length);
  };
  const watchLoop = async (token) => {
    while (st.watchToken === token && st.watch.length && box.isConnected && onlineViews().includes(S.view) && S.onlineNode === id) {
      const t = performance.now();
      try { await readKeys(st.watch.map((k) => k.split(":").map(Number)), true); } catch (e) { banner(e.message, true); break; }
      st.lastRound = Math.round(performance.now() - t);
      recordRound();
      renderWatch();
      await new Promise((r) => setTimeout(r, Math.max(0, st.period - st.lastRound)));
    }
    if (st.watchToken === token) st.watchToken = null;
  };
  st.watchToken = null;  // a loop of an earlier render of this tab ends
  const startWatch = () => {
    if (st.watchToken || !st.watch.length) return;
    st.watchToken = {};
    watchLoop(st.watchToken);
  };
  const setWatched = (key, on) => {
    if (on) {
      if (st.watch.includes(key)) return true;
      if (st.watch.length >= WATCH_MAX) { banner(`The watch list holds at most ${WATCH_MAX} entries.`, true); return false; }
      st.watch.push(key);
    } else {
      st.watch = st.watch.filter((k) => k !== key);
    }
    const c = cells[key];
    if (c) c.watch.checked = st.watch.includes(key);
    saveWatch();
    renderWatch();
    startWatch();
    return true;
  };

  // -- the tree
  const filter = el("input", { type: "search", placeholder: "Search index or name", "aria-label": "Search the object dictionary", dataset: { online: "od-filter" } });
  filter.value = st.filter;
  const chips = el("div", { class: "kind-chips od-filters", dataset: { online: "od-filters" } });
  const compareNote = el("div", { dataset: { online: "od-compare" } });
  const groups = [];
  // The selected row: the one the user clicked or tabbed into, so it is clear
  // which entry the row's buttons act on. Key "index:sub", or "obj:index" for
  // a foldable object's row; kept in the tab state across renders.
  const selRows = {};
  const selectRow = (key) => {
    st.selected = key && selRows[key] ? key : null;
    for (const tr of box.querySelectorAll("tr.od-selected")) { tr.classList.remove("od-selected"); tr.removeAttribute("aria-current"); }
    const tr = st.selected && selRows[st.selected];
    if (tr) { tr.classList.add("od-selected"); tr.setAttribute("aria-current", "true"); }
  };
  const rowOf = (ev) => { const tr = ev.target.closest && ev.target.closest("tr[data-od-sel]"); return tr && tr.dataset.odSel; };
  const selectable = (table) => {
    table.addEventListener("pointerdown", (ev) => { const k = rowOf(ev); if (k && k !== st.selected) selectRow(k); });
    table.addEventListener("focusin", (ev) => { const k = rowOf(ev); if (k && k !== st.selected) selectRow(k); });
    table.addEventListener("keydown", (ev) => {
      if (ev.key === "Escape" && st.selected && !ev.target.closest("input, select, textarea")) selectRow(null);
    });
    return table;
  };
  const entryRow = (e, isSub) => {
    const key = odKey(e.index, e.subindex);
    const value = el("td", { class: "od-value", dataset: { online: "od-value" } });
    const marks = el("div", { class: "od-marks" });
    const watch = el("input", { type: "checkbox", "aria-label": "Watch", disabled: !e.readable, dataset: { online: "od-watch" } });
    watch.checked = st.watch.includes(key);
    watch.addEventListener("change", () => { if (!setWatched(key, watch.checked)) watch.checked = false; });
    const read = el("button", { type: "button", class: "small", disabled: !e.readable, dataset: { online: "od-read" },
      onclick: async () => { try { await readKeys([[e.index, e.subindex]]); } catch (err) { banner(err.message, true); } } }, "Read");
    const edit = el("button", { type: "button", class: "small", disabled: !allow || !e.writable, dataset: { online: "od-edit" },
      title: !allow ? NO_CHANGES : !e.writable ? "Read-only in the EDS (" + e.access + ")" : null,
      onclick: () => {
        selectRow(key);
        odEdit(id, n, e, cells[key], readKeys, noteOf(e), (wrote) => {
          cells[key].editing = false;
          if (wrote) st.keep[key] = wrote;
          showValue(key);
        });
      } }, "Edit");
    const noteBox = el("div", { dataset: { online: "od-note" } }, noteLine(noteOf(e)));
    const tr = el("tr", { class: isSub ? "od-sub" : "od-var", dataset: { odKey: key, odObject: String(e.index), odSel: key } },
      el("td", { class: "mono" }, isSub ? `:${e.subindex}` : `${hex4(e.index)}:${e.subindex}`),
      el("td", { class: "od-name" }, el("div", null, isSub ? e.sub_name || e.name : e.name), noteBox, marks),
      el("td", { class: "od-type" }, e.type || "?", " ", el("span", { class: "muted" }, e.access),
        e.default ? el("div", { class: "muted", title: "EDS default" }, "default " + e.default) : null),
      value, el("td", { class: "actions" }, read, edit,
        el("button", { type: "button", class: "small", disabled: data.slave || (!e.readable && !e.writable),
          title: data.slave ? NO_ST_SLAVE : "Copy as ST call (CO_SDO_* block)",
          dataset: { online: "od-st" }, onclick: () => copyStCall(id, e.index, e.subindex, e.type, e.readable, e.writable) }, "ST")),
      el("td", { class: "od-watch" }, watch));
    selRows[key] = tr;
    cells[key] = { tr, value, marks, watch, text: `${hex4(e.index)}:${e.subindex} ${e.index.toString(16)} ${e.name} ${noteOf(e).text || ""}`.toLowerCase() };
    return tr;
  };
  for (const [g, title] of OD_GROUPS) {
    const list = objects.filter((o) => o.group === g);
    if (!list.length) continue;
    const rows = [];
    for (const o of list) {
      if (o.type === "VAR" && o.entries.length === 1) {
        rows.push(entryRow(o.entries[0], false));
        objRows[o.index] = { obj: o, tr: null, subs: [] };
        continue;
      }
      const toggle = el("button", { type: "button", class: "small od-toggle", "aria-label": "Fold or unfold", dataset: { online: "od-toggle" } });
      const objSummary = el("div", { class: "od-marks" });
      const readObj = el("button", { type: "button", class: "small", disabled: !o.entries.some((e) => e.readable), dataset: { online: "od-read-object" },
        onclick: async () => { try { await readObject(o); } catch (err) { banner(err.message, true); } } }, "Read");
      const tr = el("tr", { class: "od-object", dataset: { odObjectRow: String(o.index), odSel: "obj:" + o.index } },
        el("td", { class: "mono" }, toggle, " ", hex4(o.index)),
        el("td", { class: "od-name" }, el("div", null, el("strong", null, o.name)), objSummary),
        el("td", { class: "od-type muted" }, `${o.type}, ${o.entries.length} entries`), el("td"),
        el("td", { class: "actions" }, readObj), el("td"));
      const subs = o.entries.map((e) => entryRow(e, true));
      toggle.addEventListener("click", () => {
        const open = st.openObjects.includes(o.index);
        st.openObjects = open ? st.openObjects.filter((x) => x !== o.index) : st.openObjects.concat([o.index]);
        applyFilter();
      });
      objRows[o.index] = { obj: o, tr, subs, toggle, summary: objSummary };
      selRows["obj:" + o.index] = tr;
      rows.push(tr, ...subs);
    }
    const det = el("details", { dataset: { odGroup: g } }, el("summary", null, `${title} (${list.length} objects)`),
      el("div", { class: "table-scroll", dataset: { box: "od_table", boxLabel: "the object dictionary" } }, selectable(el("table", { class: "od od-tree" },
        el("colgroup", null, ["c-entry", "c-name", "c-type", "c-value", "c-actions", "c-watch"].map((c) => el("col", { class: c }))),
        el("thead", null, el("tr", null, thCells(["Entry", "Name", "Type", "Value", "", "Watch"]))),
        el("tbody", null, rows)))));
    det.open = st.openGroups.includes(g);
    det.addEventListener("toggle", () => {
      if (filtering()) return;
      st.openGroups = det.open ? [...new Set(st.openGroups.concat([g]))] : st.openGroups.filter((x) => x !== g);
    });
    groups.push([det, g, list]);
  }
  const filtering = () => !!filter.value.trim() || st.filters.length > 0;
  const entryMatches = (e, f, objText) => {
    const key = odKey(e.index, e.subindex);
    if (f && !objText && !cells[key].text.includes(f)) return false;
    return st.filters.every((x) => passes(e, x));
  };
  const applyFilter = () => {
    if (data.standard) lackSet = odLackSet(st, objects);
    const f = filter.value.trim().toLowerCase();
    st.filter = filter.value;
    const on = filtering();
    st.shown = [];
    for (const [det, g, list] of groups) {
      let shown = 0;
      for (const o of list) {
        const r = objRows[o.index];
        const objText = !!f && !!r.tr && `${hex4(o.index)} ${o.index.toString(16)} ${o.name}`.toLowerCase().includes(f);
        const match = o.entries.map((e) => entryMatches(e, f, objText));
        const any = match.some(Boolean);
        o.entries.forEach((e, k) => { if (match[k]) st.shown.push(odKey(e.index, e.subindex)); });
        if (!r.tr) {
          cells[odKey(o.entries[0].index, o.entries[0].subindex)].tr.hidden = !any;
        } else {
          const open = on ? any : st.openObjects.includes(o.index);
          r.tr.hidden = !any;
          r.toggle.textContent = open ? "▾" : "▸";
          r.toggle.setAttribute("aria-expanded", String(open));
          r.subs.forEach((tr, k) => { tr.hidden = !(open && match[k]); });
        }
        if (any) shown++;
      }
      det.hidden = shown === 0;
      if (on) det.open = shown > 0;
      else det.open = st.openGroups.includes(g);
    }
  };
  filter.addEventListener("input", applyFilter);
  const renderChips = () => {
    put(chips, OD_FILTERS.filter(([k]) => (k !== "compare" || st.compare) && (k !== "lacking" || data.standard)).map(([k, label]) => {
      const cb = el("input", { type: "checkbox", dataset: { odFilter: k } });
      cb.checked = st.filters.includes(k);
      cb.addEventListener("change", () => {
        st.filters = cb.checked ? st.filters.concat([k]) : st.filters.filter((x) => x !== k);
        applyFilter();
      });
      return el("label", { class: "chip" }, cb, label);
    }));
    if (!st.compare) st.filters = st.filters.filter((x) => x !== "compare");
    put(compareNote, st.compare ? el("p", { class: "muted" }, `Compare marks: against ${st.compare.label}. `,
      el("button", { type: "button", class: "small", dataset: { online: "od-compare-clear" }, onclick: () => {
        st.compare = null;
        renderChips();
        for (const key of Object.keys(cells)) showValue(key);
        applyFilter();
      } }, "Clear")) : null);
  };

  // -- copy and CSV of the shown rows
  const tableRows = () => [["Entry", "Name", "Type", "Access", "EDS default", "Value", "Marks"]].concat(
    (st.shown || []).map((key) => {
      const e = byKey[key];
      return [`${hex4(e.index)}:${e.subindex}`, e.name, e.type || "", e.access, e.default || "",
        odText(st.values[key], e, st.formats[key]), marksOf(e).map((m) => m[0]).join("; ")];
    }));
  const copyRows = async () => {
    const text = tableRows().map((r) => r.map((x) => String(x ?? "").replace(/[\t\n]/g, " ")).join("\t")).join("\n") + "\n";
    try { await navigator.clipboard.writeText(text); }
    catch (e) {
      const ta = el("textarea", null);
      ta.value = text;
      document.body.append(ta);
      ta.select();
      document.execCommand("copy");
      ta.remove();
    }
    banner(`${tableRows().length - 1} rows copied.`);
  };
  const saveCsv = () => {
    const text = tableRows().map((r) => r.map(csvField).join(",")).join("\r\n") + "\r\n";
    const b64 = btoa(String.fromCharCode(...new TextEncoder().encode(text)));
    downloadBase64(b64, `node${id}-object-dictionary.csv`, "text/csv");
  };

  // -- read or write any entry
  const anyIx = el("input", { type: "text", class: "index", placeholder: "0x2100", "aria-label": "Index", dataset: { online: "od-any-index" } });
  const anySub = el("input", { type: "text", class: "short", placeholder: "0", "aria-label": "Subindex", dataset: { online: "od-any-sub" } });
  const anyType = el("select", { "aria-label": "Type", dataset: { online: "od-any-type" } },
    el("option", { value: "" }, "hex bytes"), SDO_TYPES.map((t) => el("option", { value: t }, t)));
  const anyValue = el("input", { type: "text", placeholder: "value", "aria-label": "Value", dataset: { online: "od-any-value" } });
  const anyOut = el("span", { class: "sdo-result", dataset: { online: "od-any-result" } });
  const anyTarget = () => {
    const index = num(anyIx.value.trim()), subindex = anySub.value.trim() === "" ? 0 : num(anySub.value.trim());
    if (!(index >= 0 && index <= 0xFFFF) || !(subindex >= 0 && subindex <= 255)) {
      put(anyOut, el("span", { class: "field-msg" }, "Give the index as 0x… and the subindex as 0-255."));
      return null;
    }
    return { node: id, index, subindex, type: anyType.value || null, port: diagPort() };
  };
  const anyShow = (r, what) => put(anyOut, r.success
    ? (what === "read" ? el("strong", null, r.decoded.text) : el("span", { class: "ok-text" }, "Written."))
    : el("span", { class: "field-msg" }, r.abort_code !== undefined ? `Abort ${hex8(r.abort_code)}: ${r.abort_text}` : r.reason));
  const anyRead = async () => {
    const t = anyTarget();
    if (!t) return;
    try { anyShow(await api("POST", "/api/online/sdo_read", t), "read"); } catch (e) { put(anyOut, el("span", { class: "field-msg" }, e.message)); }
  };
  const anyWrite = async () => {
    const t = anyTarget();
    if (!t) return;
    const e = byKey[odKey(t.index, t.subindex)];
    if (e) { put(anyOut, el("span", { class: "muted" }, "This entry is in the EDS: use its Edit button below.")); return; }
    try {
      const r = await apiNodeChange(id, "/api/online/sdo_write", Object.assign(t, { value: anyValue.value }));
      if (r) anyShow(r, "write"); else put(anyOut, el("span", { class: "muted" }, "Not written."));
    } catch (err) { put(anyOut, el("span", { class: "field-msg" }, err.message)); }
  };

  const readAll = el("button", { type: "button", class: "primary", dataset: { online: "od-read-all" }, onclick: () => {
    summary.textContent = "";
    startJob("/api/online/od_read", Object.assign(odSource(id), { all: true }), status, showAll);
  } }, "Read all");
  const showAll = (j) => {
    const r = j.result;
    const lacking = (r.failures || []).filter((f) => f.abort_code === SDO_NO_OBJECT || f.abort_code === SDO_NO_SUB).length;
    st.allSummary = `${r.read} read, ${data.standard ? `${lacking} not on this device, ${r.failed - lacking}` : r.failed} not readable` +
      `${r.cancelled ? ", cancelled" : ""}.` + (r.stopped ? " Stopped: " + r.stopped + "." : "");
    // More PDOs than the standard dictionary lists: it is fetched again with them.
    const pdos = st.pdos || { rpdos: 4, tpdos: 4 };
    if (data.standard && (r.rpdos > pdos.rpdos || r.tpdos > pdos.tpdos)) {
      st.pdos = { rpdos: Math.max(r.rpdos, pdos.rpdos), tpdos: Math.max(r.tpdos, pdos.tpdos) };
      odStore(st, r);
      if (box.isConnected) renderOnlineNode();
      return;
    }
    setReading(r);
    // Read all shows what it read: the groups that got values unfold, and the
    // objects holding an entry that differs from its EDS default.
    const got = (e) => { const v = st.values[odKey(e.index, e.subindex)]; return !!v && !v.error; };
    st.openGroups = [...new Set(st.openGroups.concat(objects.filter((o) => o.entries.some(got)).map((o) => o.group)))];
    st.openObjects = [...new Set(st.openObjects.concat(objects.filter((o) => o.entries.some((e) => passes(e, "changed"))).map((o) => o.index)))];
    const cur = st.build === build ? summary : document.querySelector("[data-online=od-summary]");
    if (cur) cur.textContent = st.allSummary;
    if (st.refreshMarks) st.refreshMarks();
  };
  st.refreshMarks = () => {
    if (!box.isConnected) return;
    renderChips();
    for (const key of Object.keys(cells)) showValue(key);
    for (const i of Object.keys(objRows)) updateObject(Number(i));
    applyFilter();
    renderWatch();
  };
  if (st.allSummary) summary.textContent = st.allSummary;
  slot.append(...byKind([data.standard ? standardNote(id, data) : null,
    allow ? null : lockedNote("od-read-only", null, "Read-only:"),
    data.note ? notice("warning", data.note, { live: false }) : null]));
  put(box, slot,
    el("div", { class: "toolbar" }, filter, readAll,
      el("button", { type: "button", dataset: { online: "od-copy" }, onclick: copyRows }, "Copy"),
      el("button", { type: "button", dataset: { online: "od-csv" }, onclick: saveCsv }, "Save CSV"), status),
    chips, watchHint, summary, compareNote, watchCard,
    el("details", { class: "od-any", dataset: { online: "od-any" } }, el("summary", null, "Read or write any entry"),
      el("div", { class: "toolbar" }, el("label", { class: "inline" }, "Index ", anyIx), el("label", { class: "inline" }, "Sub ", anySub),
        el("label", { class: "inline" }, "Type ", anyType),
        el("button", { type: "button", dataset: { online: "od-any-read" }, onclick: anyRead }, "Read"),
        el("label", { class: "inline" }, "Value ", anyValue),
        el("button", { type: "button", disabled: !allow, title: allow ? null : NO_CHANGES, dataset: { online: "od-any-write" }, onclick: anyWrite }, "Write"),
        el("button", { type: "button", disabled: data.slave, title: data.slave ? NO_ST_SLAVE : "Copy as ST call (CO_SDO_* block)", dataset: { online: "od-any-st" }, onclick: () => {
          const t = anyTarget();
          if (t) copyStCall(id, t.index, t.subindex, t.type || "", true, true);
        } }, "Copy as ST call"),
        anyOut)),
    ...groups.map(([det]) => det));
  renderChips();
  for (const key of Object.keys(cells)) showValue(key);
  for (const i of Object.keys(objRows)) updateObject(Number(i));
  applyFilter();
  selectRow(st.selected);
  const begin = () => {
    st.watch = st.watch.filter((k) => byKey[k] && byKey[k].readable);
    period.value = String(st.period);
    for (const key of Object.keys(cells)) cells[key].watch.checked = st.watch.includes(key);
    renderWatch();
    startWatch();
  };
  if (st.watchLoaded) begin();
  else {
    renderWatch();
    api("POST", "/api/online/watch", { node: id }).then((r) => {
      st.watchLoaded = true;
      if (!st.watch.length) { st.watch = r.keys.map((k) => odKey(k[0], k[1])); st.period = r.period_ms; }
      if (box.isConnected) begin();
    }).catch(() => { st.watchLoaded = true; if (box.isConnected) begin(); });
  }
  const ticker = setInterval(() => { if (!box.isConnected) clearInterval(ticker); else if (st.watch.length && !st.watchToken) renderWatch(); }, 1000);
  resumeJob(id, ["read"], status, showAll);
}

// In-place edit of one entry: the SDO panel's checks, the EDS limits, a write
// and a read-back. done(true) after a successful write.
function odEdit(id, n, e, cell, readKeys, note, done) {
  cell.editing = true;
  const v = (S.od[id].values[odKey(e.index, e.subindex)] || {});
  const input = el("input", { type: "text", class: "od-input", "aria-label": "New value", dataset: { online: "od-input" } });
  input.value = v.text ? v.text.replace(/ \(0x[0-9A-F]+\)$/, "") : "";
  const pick = valuePicker(note, input, (x) => { input.value = x; });
  const limits = odLimitText(e);
  const msg = el("span", { class: "field-msg" });
  const write = async () => {
    const warn = [];
    warn.push(...ownWriteWarnings(e.index, e.subindex));
    if (e.sdo_variable) warn.push(`SDO variable ${typeof e.sdo_variable === "string" ? e.sdo_variable : ""} writes this entry from the program; the program's value wins at its next write.`);
    if (e.config && !pluginObject(e.index)) warn.push("The configuration writes this entry at every boot; your value lasts until the next boot.");
    const x = Number(input.value.trim());
    if (input.value.trim() !== "" && !Number.isNaN(x) && ((e.low_limit !== undefined && x < e.low_limit) || (e.high_limit !== undefined && x > e.high_limit)))
      warn.push(`The EDS allows ${e.low_limit !== undefined ? e.low_limit : "…"} to ${e.high_limit !== undefined ? e.high_limit : "…"}; ${input.value.trim()} is outside.`);
    if (warn.length) {
      const ans = await modal(warn.join(" ") + " Write anyway?", [["write", "Write", true], ["cancel", "Cancel"]]);
      if (ans !== "write") return;
    }
    msg.textContent = "Writing…";
    let written;
    try {
      const r = await apiNodeChange(id, "/api/online/sdo_write", { node: id, index: e.index, subindex: e.subindex, type: e.type, value: input.value, port: diagPort() });
      if (!r) { msg.textContent = "Not written."; return; }
      if (!r.success) { msg.textContent = r.abort_code !== undefined ? `Abort ${hex8(r.abort_code)}: ${r.abort_text}` : r.reason; return; }
      written = r.data;
    } catch (err) { msg.textContent = err.message; return; }
    try { await readKeys([[e.index, e.subindex]]); } catch (err) { banner(err.message, true); }
    done(written || true);
  };
  input.addEventListener("keydown", (ev) => { if (ev.key === "Enter") write(); if (ev.key === "Escape") done(false); });
  put(cell.value, pick, input, el("button", { type: "button", class: "small primary", dataset: { online: "od-write" }, onclick: write }, "Write"),
    el("button", { type: "button", class: "small", onclick: () => done(false) }, "Cancel"),
    limits ? el("div", { class: "muted", dataset: { online: "od-limits" } }, limits) : null, msg);
  input.focus();
}

// -- parameters tab ---------------------------------------------------------------

// A styled file button (the input inside, invisible) with the picked file's name after it.
function fileButton(label, input) {
  const name = el("span", { class: "muted", dataset: { fileName: input.dataset.online || "" } }, "no file chosen");
  input.addEventListener("change", () => { name.textContent = input.files[0] ? input.files[0].name : "no file chosen"; });
  return el("span", { class: "row" }, el("label", { class: "file-button" }, label, input), name);
}

function paramsPanel(id, n, allow) {
  const box = el("div", { dataset: { online: "params" } });
  if (!nodeSource(id)) { put(box, paramsNeedEds(id)); return box; }
  const status = el("div", { class: "job-status", dataset: { online: "params-status" } });
  const out = el("div", { dataset: { online: "params-result" } });
  const why = allow ? null : NO_CHANGES;

  // Back up
  const showBackup = (j, resumed) => {
    const r = j.result;
    if (!r) return;
    if (!resumed) downloadBase64(r.data, r.name);
    put(out, byKind([notice("done", `${r.name}: ${r.read} entries read, ${r.failed} not read.`, { dataset: { online: "backup-done" },
      actions: [el("button", { type: "button", class: "small", onclick: () => downloadBase64(r.data, r.name) }, resumed ? "Download" : "Download again")] }),
    r.stopped ? notice("error", "Stopped: " + r.stopped) : null,
    r.boot_state ? notice("warning", `Read while the node was ${r.boot_state}.`) : null,
    ...(r.lint || []).map((m) => notice("warning", m))]));
  };
  const backup = async () => {
    const live = nodeLive(id);
    if (live && !live.booted && !S.state.commission) {  // a USB adapter has no master to configure it
      const v = await modal(`Node ${id} has not booted successfully, so the master may not have configured it yet. Back up anyway?`,
        [["go", "Back up anyway", true], ["cancel", "Cancel"]]);
      if (v !== "go") return;
    }
    put(out);
    startJob("/api/online/backup", nodeSource(id), status, showBackup);
  };

  // Compare
  const ref = el("select", { "aria-label": "Compare against", dataset: { online: "compare-ref" } },
    el("option", { value: "file" }, "a backup file"),
    n && !S.state.commission ? el("option", { value: "config" }, "the configuration") : null,
    el("option", { value: "eds" }, "the EDS defaults"));
  const cmpFile = el("input", { type: "file", accept: ".dcf,.DCF,.eds,.EDS", "aria-label": "Backup file", dataset: { online: "compare-file" } });
  const ro = el("input", { type: "checkbox", dataset: { online: "compare-ro" } });
  const showEqual = el("input", { type: "checkbox", dataset: { online: "compare-equal" } });
  ref.addEventListener("change", () => { cmpFile.hidden = ref.value !== "file"; });
  let lastCompare = null;
  const showCompare = (j) => {
    lastCompare = j.result;
    const r = j.result;
    const s = r.summary;
    const rows = r.rows.filter((x) => showEqual.checked || x.result !== "equal");
    const noteAt = nodeNotes(id);
    put(out, r.stopped ? notice("error", "Stopped: " + r.stopped) : null,
    notice(s.different ? "warning" : "done", `${s.different} different, ${s["not readable"]} not readable, ${s.equal} equal, ${s["no reference"]} without a reference.`,
      { dataset: { online: "compare-summary" } }),
    rows.length ? el("table", { class: "od compare-rows" },
      el("thead", null, el("tr", null, thCells(["Entry", "Name", "Result", r.reference === "file" ? "Backup" : r.reference === "config" ? "Configuration" : "EDS default", "Device"]))),
      el("tbody", null, rows.map((x) => el("tr", { class: x.result === "different" ? "bad" : x.result === "equal" ? "muted" : null },
        el("td", { class: "mono" }, `${hex4(x.index)}:${x.subindex}`), el("td", null, x.name, noteLine(noteAt(x.index, x.subindex))), el("td", null, x.result),
        el("td", null, withMeaning(noteAt(x.index, x.subindex), x.reference ?? "")),
        el("td", null, x.device !== null && x.device !== undefined ? withMeaning(noteAt(x.index, x.subindex), x.device) : (x.error || "")))))) : null);
  };
  showEqual.addEventListener("change", () => { if (lastCompare) showCompare({ result: lastCompare }); });
  // The result also marks the object dictionary tab's entries.
  let compareName = "";
  const compareDone = (j) => {
    showCompare(j);
    const r = j.result;
    const st = odState(id);
    const rows = {};
    for (const x of r.rows) rows[odKey(x.index, x.subindex)] = x;
    if (r.reading) odStore(st, r.reading);  // the values the compare read
    st.compare = { rows, label: r.reference === "file" ? (compareName || "a backup file") : r.reference === "config" ? "the configuration" : "the EDS defaults",
      short: r.reference === "file" ? "backup" : r.reference === "config" ? "config" : "EDS default" };
    if (st.refreshMarks) st.refreshMarks();
  };
  const compare = async () => {
    const body = Object.assign(nodeSource(id), { reference: ref.value, read_only: ro.checked });
    if (ref.value === "file") {
      const f = cmpFile.files[0];
      if (!f) { banner("Choose the backup file to compare with.", true); return; }
      body.file = await fileBase64(f);
      body.file_name = f.name;
    }
    compareName = ref.value === "file" ? body.file_name : "";
    put(out);
    startJob("/api/online/compare", body, status, compareDone);
  };

  // Restore
  const resFile = el("input", { type: "file", accept: ".dcf,.DCF", "aria-label": "Backup file to restore", dataset: { online: "restore-file" } });
  const comm = el("input", { type: "checkbox", dataset: { online: "restore-comm" } });
  const restore = async () => {
    const f = resFile.files[0];
    if (!f) { banner("Choose the backup file to restore.", true); return; }
    const body = Object.assign(nodeSource(id), { file: await fileBase64(f), file_name: f.name, include_comm: comm.checked });
    put(out);
    startJob("/api/online/restore_plan", body, status, (j) => restoreDialog(id, j, status, out));
  };

  // Store on device (0x1010): only when the EDS has it.
  const storeBox = el("div", { dataset: { online: "store-box" } });
  odEntries(id).then((data) => {
    const defaults = restoreDefaultsBox(id, data, allow);
    const defaultsHint = defaults ? hint("Factory defaults writes \"load\" to 0x1011: the device takes its factory values at its next reset, and what was stored on it is lost.") : null;
    if (!data.has_store) {
      put(storeBox, el("p", { class: "muted" }, "The EDS has no store object (0x1010), so values cannot be stored on this device from here."), defaults, defaultsHint);
      return;
    }
    const names = { 1: "all parameters", 2: "communication parameters", 3: "application parameters" };
    const sub = el("select", { "aria-label": "What to store", dataset: { online: "store-sub" } },
      data.store_subindices.map((s) => el("option", { value: s }, `sub ${s}: ${names[s] || "manufacturer-specific"}`)));
    put(storeBox, el("div", { class: "toolbar" }, sub,
      el("button", { type: "button", disabled: !allow, title: why, dataset: { online: "store" }, onclick: () => storeDialog(id, Number(sub.value), names[Number(sub.value)]) }, "Store on device…")),
    hint("Writes \"save\" to 0x1010 so the device keeps its current values over a power cycle. Never done by restore. Each store wears the device's flash memory."),
    defaults, defaultsHint);
  }).catch((e) => put(storeBox, notice("error", e.message)));

  // A job's progress, its messages and its result at the top of the tab, under the lock.
  put(box,
    allow ? null : lockedNote("params-read-only", null, "Restore and store are off:"),
    status, out,
    el("fieldset", null, el("legend", null, "Back up"),
      el("div", { class: "toolbar" }, el("button", { type: "button", class: "primary", dataset: { online: "backup" }, onclick: backup }, "Back up")),
      hint("Reads every readable entry of the node's EDS and downloads a DCF with the values (ParameterValue), which other CANopen tools can open too.")),
    el("fieldset", null, el("legend", null, "Compare"),
      el("div", { class: "toolbar" }, el("label", { class: "inline" }, "Against ", ref), fileButton("Choose file…", cmpFile),
        el("label", { class: "inline" }, ro, " include read-only entries"),
        el("button", { type: "button", dataset: { online: "compare" }, onclick: compare }, "Compare"),
        el("label", { class: "inline" }, showEqual, " show equal entries"))),
    el("fieldset", null, el("legend", null, "Restore from a backup"),
      el("div", { class: "toolbar" }, fileButton("Choose backup…", resFile), el("label", { class: "inline" }, comm, " include communication objects (0x1000-0x1FFF)"),
        el("button", { type: "button", disabled: !allow, title: why, dataset: { online: "restore" }, onclick: restore }, "Restore from backup…")),
      hint("Shows what would be written first. Writes only differing manufacturer and profile entries; PDO objects, store/restore commands and what the configuration writes at boot are left out. Restored values are not stored on the device.")),
    onlineIsSlave() ? null : configureBox(id, n, allow, status, out),
    // What changes the device's own memory, apart from the rest.
    el("fieldset", { class: "changes-device", dataset: { online: "device-memory" } }, el("legend", null, "Device memory (changes the device)"), storeBox));
  resumeJob(id, ["backup", "compare", "restore_plan", "restore", "configure", "configure_verify"], status, (j, resumed) => {
    if (j.kind === "backup") showBackup(j, resumed);
    else if (j.kind === "compare") compareDone(j);
    else if (j.kind === "restore") showRestore(j.result, out, id);
    else if (j.kind === "configure") showConfigure(j.result, out, id);
    else if (j.kind === "configure_verify") showVerify(j.result, out);
    else restoreDialog(id, j, status, out);
  });
  return box;
}

async function restoreDialog(id, j, status, out) {
  const p = j.result;
  const ids = p.identity || [];
  const refuse = ids.filter((i) => i.level === "refuse");
  const hold = el("input", { type: "checkbox", dataset: { online: "restore-hold" } });
  const other = el("input", { type: "checkbox", dataset: { online: "restore-other" } });
  const noteAt = nodeNotes(id);
  const writes = p.writes.length ? el("table", { class: "od" },
    el("thead", null, el("tr", null, thCells(["Entry", "Name", "Backup", "Device now"]))),
    el("tbody", null, p.writes.map((w) => el("tr", null, el("td", { class: "mono" }, `${hex4(w.index)}:${w.subindex}`), el("td", null, w.name, noteLine(noteAt(w.index, w.subindex))),
      el("td", null, withMeaning(noteAt(w.index, w.subindex), w.backup)),
      el("td", null, w.device !== null && w.device !== undefined ? withMeaning(noteAt(w.index, w.subindex), w.device) : "not readable"))))) : null;
  const skipped = p.skipped.length ? el("details", null, el("summary", null, `${p.skipped.length} entries left out`),
    el("table", { class: "od" }, el("tbody", null, p.skipped.map((s) => el("tr", null, el("td", { class: "mono" }, `${hex4(s.index)}:${s.subindex}`),
      el("td", null, s.name), el("td", { class: "muted" }, s.reason)))))) : null;
  // The dialog's messages at the top of its body: identity, the plan's note, locked, nothing to write.
  const extra = el("div", { class: "restore-preview", dataset: { online: "restore-preview" } },
    el("div", { class: "notice-slot" }, byKind([
      ...ids.map((i) => notice(i.level === "refuse" ? "error" : i.level === "warning" ? "warning" : "info", i.text, { live: false })),
      p.note ? notice("warning", p.note, { live: false }) : null,
      p.allow_changes ? null : notice("warning", NO_CHANGES, { live: false, dataset: { online: "restore-locked" } }),
      p.writes.length ? null : notice("info", "Nothing to write: the device already has the backup's values.", { live: false, dataset: { online: "restore-nothing" } }),
      p.configured ? null : notice("info", "The node is not in the configuration, so nothing is left out as written by the configuration.", { live: false })])),
    writes, skipped,
    el("p", { class: "muted" }, `${p.unchanged.length} entries already equal.`),
    p.writes.length ? el("label", { class: "check" }, hold, " Hold the node in PRE-OPERATIONAL while writing (needed when the device refuses writes with abort 0x08000022)") : null,
    refuse.length ? el("label", { class: "check" }, other, " Restore to a different product anyway") : null);
  const can = p.writes.length && p.allow_changes;
  const running = nodeRunning(id);
  const go = modal(`${runningNote(id, running)}Restore ${p.writes.length} value${p.writes.length === 1 ? "" : "s"} to node ${id}?`,
    can ? [["cancel", "Cancel"], ["restore", "Restore", { danger: true }]] : [["cancel", "Close"]], extra);
  const btn = document.querySelector('#modal-buttons button[data-value="restore"]');
  if (btn && refuse.length) {
    btn.disabled = true;
    other.addEventListener("change", () => { btn.disabled = !other.checked; });
  }
  if (await go !== "restore") return;
  startJob("/api/online/restore", Object.assign(nodeSource(id), { plan: j.id, hold: hold.checked, ignore_identity: other.checked },
    running ? { force: true } : {}), status,
    (r) => showRestore(r.result, out, id));
}

function showRestore(r, out, id) {
  if (!r) return;
  odTake(id, null, r.written.concat(r.failed).map((w) => odKey(w.index, w.subindex)));
  put(out, byKind([notice(r.failed.length ? "error" : "done", [el("p", null, `${r.written.length} written, ${r.failed.length} failed${r.cancelled ? ", cancelled" : ""}.`),
    ...r.failed.map((f) => el("p", null, `${hex4(f.index)}:${f.subindex} ${f.name}: ${f.error}`))], { dataset: { online: "restore-done" } }),
  r.released === false ? notice("error", `The node is still held in PRE-OPERATIONAL (${r.release_error}); release it with Start.`) : null,
  notice("warning", r.note.charAt(0).toUpperCase() + r.note.slice(1) + ".", { dataset: { online: "restore-note" } })]));
}

async function storeDialog(id, sub, what) {
  const running = nodeRunning(id);
  const v = await modal(`${runningNote(id, running)}Store node ${id}'s current ${what || "values"} in its non-volatile memory (write "save" to 0x1010 sub ${sub})? ` +
    "The device then keeps these values over a power cycle. Each store wears the device's flash memory.",
  [["cancel", "Cancel"], ["store", "Store on device", { danger: true }]]);
  if (v !== "store") return;
  try {
    const r = await apiRunning("/api/online/store", Object.assign(nodeSource(id), { subindex: sub }), "Store anyway?", running);
    if (!r) return;
    if (r.stored) banner(`Node ${id}: stored (0x1010 sub ${sub}).`);
    else banner(`Node ${id} did not store: ${r.error}`, true);
  } catch (e) { banner(e.message, true); }
}

// ---------------------------------------------------------------------------
// Scan the bus (Commission a device, Nodes page)

function kbitText(k) { return k >= 1000 ? `${k / 1000} Mbit/s` : `${k} kbit/s`; }

// `forced`: the user already agreed to scan a running network (startScan).
async function runScan(start, forced) {
  const seq = S.onlineSeq;
  clearTimeout(S.scanTimer);
  let r;
  try {
    const body = { start, config: fileConfig(), port: diagPort(), network: onlineNetwork() || undefined };
    r = start ? await apiRunning("/api/online/scan", body, "Scan anyway?", !!forced) : await api("POST", "/api/online/scan", body);
  } catch (e) {
    if (seq === S.onlineSeq) banner(e.message, true);
    return;
  }
  const progress = document.querySelector("[data-online=scan-progress]");
  if (!r) {
    if (progress && seq === S.onlineSeq) progress.textContent = "Scan not started.";
    return;
  }
  if (seq !== S.onlineSeq || !onlineViews().includes(S.view) || !progress) return;
  if (start && typeof jobsKick === "function") jobsKick();
  const cancel = document.querySelector("[data-online=scan-cancel]");
  const button = document.querySelector("[data-online=scan]");
  cancel.hidden = !r.running;
  button.disabled = !!r.running;
  if (r.running) {
    progress.textContent = `Scanning… ${r.done} of ${r.total} node IDs`;
    S.scanTimer = setTimeout(() => runScan(false), 300);
    return;
  }
  if (!r.nodes) { progress.textContent = "No scan has run on this connection yet."; return; }
  const note = r.note ? ` ${upperFirst(r.note)}.` : "";
  const how = r.error ? `Stopped after ${r.done} of ${r.total} node IDs: ${r.error}.`
    : r.stopped ? `Cancelled after ${r.done} of ${r.total} node IDs.` : "";
  progress.textContent = how || `Scanned ${String(r.finished_at || "").replace("T", " ").replace(/\.\d+Z$/, " UTC")} in ${Number(r.seconds || 0).toFixed(1)} s.${note}`;
  S.scanResult = r;
  const live = $("#online-live");
  if (!live) return;
  if (S.state.commission) patchLive(live, [commNodeTable(S.onlineLast && S.onlineLast.status)]);
  else onlineRedraw();
}

// A device of the Nodes page opened with an EDS: the matching one from the
// library, or a picked or added file.
function openScannedOd(d, match) {
  setPageEds(d, match);
  S.onlineNode = d.node_id;
  S.onlineTab = "od";
  if (S.view === "nodes") render();
  else showView("nodes");
}

// The EDS a node uses on this page (a match, a library file or one picked
// here), logged when it replaces another.
function setPageEds(d, match) {
  const before = (S.onlineEdsName || {})[d.node_id] || null;
  if (before !== match.name || (S.onlineEds || {})[d.node_id] !== match.path) {
    dropOdState(d.node_id);
    if (before) commLog(d.node_id, `Change EDS ${before} → ${match.name}`, "on this page");
  }
  commNodes()[d.node_id] = Object.assign(commNodes()[d.node_id] || {}, { eds_path: match.path, eds_name: match.name });
  Object.assign(commDevice(), { node_id: d.node_id, vendor_id: d.vendor_id, product_code: d.product_code, revision_number: d.revision_number,
    serial_number: d.serial_number, eds_path: match.path, eds_name: match.name });
  S.onlineEds = Object.assign(S.onlineEds || {}, { [d.node_id]: match.path });
  S.onlineEdsName = Object.assign(S.onlineEdsName || {}, { [d.node_id]: match.name });
}

function readBase64(file) {
  return new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(r.result.split(",")[1] || "");
    r.onerror = () => reject(r.error);
    r.readAsDataURL(file);
  });
}

// `stay`: added from the Commission workspace's comparison; the page stays there.
// `imported`: the EDS already imported (carried from Commission a device).
async function addScannedNode(d, match, file, identity, lss, stay, imported) {
  let res = imported;
  try {
    if (res) {
      // already in the draft
    } else if (match) {
      res = await api("POST", "/api/online/use_eds", { path: match.path, eds_lint: edsLint() });
    } else {
      const data = await readBase64(file);
      res = await api("POST", "/api/eds", { name: file.name, data, on_conflict: "keep_both", eds_lint: edsLint() });
    }
  } catch (e) { banner(e.message, true); return false; }
  S.state.eds = S.state.eds || {};
  S.state.eds[res.name] = res.summary;
  const base = (d.device_name || res.name.replace(/\.eds$/i, "")).replace(/[^A-Za-z0-9_]+/g, "_").toLowerCase().replace(/^_+|_+$/g, "");
  const node = { node_id: d.node_id, name: base || "node" + d.node_id, eds: res.name };
  if (identity) {
    if (d.revision_number) node.revision_number = d.revision_number;
    if (d.serial_number) node.serial_number = d.serial_number;
  }
  // LSS assignment only for a device whose EDS has LSS.
  const noLss = lss && !((res.summary || {}).device || {}).lss_supported;
  if (lss) node.serial_number = d.serial_number;
  if (lss && !noLss) node.lss = { assign: true };
  if (stay) {
    const net = onlineConfig();
    superviseNewNode(node, res.summary, S.model.networks.indexOf(net));
    net.nodes = net.nodes || [];
    net.nodes.push(node);
    banner(el("div", null, el("div", null, `Added node ${d.node_id} (${res.name}) to the config. Save to keep it; map its PDOs in Configure. `,
      noLss ? el("span", { dataset: { lssNote: "" } }, "No LSS assignment: its EDS has no LSS (LSS_Supported=1 missing). ") : null,
      el("button", { type: "button", class: "link", dataset: { undo: "1" }, onclick: () => undo(false) }, "Undo")), importReport(res)));
    changed(false);
    edsNotesArrived(res);
    return true;
  }
  S.config.nodes = S.config.nodes || [];
  superviseNewNode(node, res.summary, S.net);
  S.config.nodes.push(node);
  // The new node's page opens; after LSS, with a way back to the online view.
  S.view = "node:" + (S.config.nodes.length - 1);
  S.focusName = S.config.nodes.length - 1;
  banner(el("div", null, el("div", null, `Added node ${d.node_id} (${res.name}). Map its PDOs here, then save. `,
    noLss ? el("span", { dataset: { lssNote: "" } }, "No LSS assignment: its EDS has no LSS (LSS_Supported=1 missing). ") : null,
    lss ? el("button", { type: "button", class: "link", dataset: { online: "back-to-online" }, onclick: () => showView("online") }, "Back to Nodes") : null),
  importReport(res)));
  changed(true);
  edsNotesArrived(res);
}

// ---------------------------------------------------------------------------
// Edits

// An EDS file picked with Browse… into the project, asking on a name
// conflict. Returns the /api/eds answer, or null.
async function importEdsFile(file) {
  const data = await readBase64(file);
  try {
    return await api("POST", "/api/eds", { name: file.name, data, eds_lint: edsLint() });
  } catch (e) {
    if (e.status === 409 && e.body.conflict) {
      const v = await modal(e.message + ". Replace it, or keep both under a new name?",
        [["cancel", "Cancel"], ["replace", "Replace", { danger: true }], ["keep_both", "Keep both", true]]);
      if (!v || v === "cancel") return null;
      try { return await api("POST", "/api/eds", { name: file.name, data, on_conflict: v, eds_lint: edsLint() }); }
      catch (e2) { banner(e2.message, true); return null; }
    }
    banner(e.message, true);
    return null;
  }
}

// -- the Add node dialog (add-node-dialog) -------------------------------------

// The lowest node ID the open network has free (not a node's, not the master's).
function freeNodeId() {
  const used = new Set([num(S.config.master && S.config.master.node_id), ...(S.config.nodes || []).map((n) => num(n.node_id))]);
  for (let id = 1; id <= 127; id++) if (!used.has(id)) return id;
  return null;
}

// Why a node ID cannot be used on the open network, or "".
function nodeIdProblem(text) {
  const id = /^[0-9]+$/.test(text.trim()) ? Number(text.trim()) : NaN;
  if (!Number.isInteger(id) || id < 1 || id > 127) return "A node ID is 1 to 127.";
  if (id === num(S.config.master && S.config.master.node_id)) return `${id} is the master's node ID.`;
  const n = (S.config.nodes || []).find((x) => num(x.node_id) === id);
  return n ? `${id} is taken by ${n.name || "another node"}.` : "";
}

// An identifier from a product or file name, unique among the network's nodes.
function nodeNameFor(text) {
  let base = String(text || "").replace(/\.eds$/i, "").replace(/[^A-Za-z0-9_]+/g, "_").replace(/^_+|_+$/g, "").toLowerCase();
  if (!base) base = "node";
  if (/^[0-9]/.test(base)) base = "n" + base;
  const taken = new Set((S.config.nodes || []).map((n) => n.name));
  let name = base;
  for (let k = 2; taken.has(name); k++) name = `${base}_${k}`;
  return name;
}

// The project's EDS files a node can use: not a slave network's own description.
function projectEdsChoices() {
  const own = new Set(Object.keys((S.state && S.state.slave_descriptions) || {}));
  const uses = {};
  for (const net of S.model ? S.model.networks : [S.config]) {
    for (const n of net.nodes || []) if (n.eds) uses[n.eds] = (uses[n.eds] || 0) + 1;
  }
  return Object.entries((S.state && S.state.eds) || {}).filter(([name, e]) => !own.has(name) && e && !e.error)
    .map(([name, e]) => ({ name, product: (e.device && e.device.product_name) || "", uses: uses[name] || 0 }))
    .sort((a, b) => (a.product || a.name).localeCompare(b.product || b.name));
}

// "+ Add node…": the device description (the project's EDS files, the EDS
// library, Browse…), the node ID, the name and the default PDOs, then Add.
// `picked`: an EDS just imported (a file dropped on #eds-input).
async function addNodeDialog(picked) {
  const err = msgBar({ addNode: "msg" }, "");
  let finish = () => {};
  const eds = edsList({ current: picked, lint: edsLint(), dataset: { addNode: "eds" },
    onBrowsed: () => { nameTyped = false; update(); eds.list.focus(); },
    onFill: () => update(),
    onEnter: () => finish() });
  const list = eds.list;
  eds.browse.dataset.addNode = "browse";
  eds.empty.dataset.addNode = "empty";
  const id = el("input", { type: "text", inputmode: "numeric", class: "short", "aria-label": "Node ID", dataset: { addNode: "id" } });
  id.value = String(freeNodeId() ?? "");
  const idMsg = el("span", { class: "field-msg", dataset: { addNode: "id-msg" }, "aria-live": "polite" });
  const name = el("input", { type: "text", spellcheck: "false", "aria-label": "Name", dataset: { addNode: "name" } });
  let nameTyped = false;
  name.addEventListener("input", () => { nameTyped = true; });
  const mapBox = el("input", { type: "checkbox", checked: true, dataset: { addNode: "map" } });
  const locations = usedBy("nodes.tx_pdos.entries.iec_location");
  const update = () => {
    const c = eds.choice();
    if (!nameTyped) name.value = nodeNameFor(c ? c.product || c.name : "");
    const p = nodeIdProblem(id.value);
    idMsg.textContent = p;
    id.setAttribute("aria-invalid", p ? "true" : "false");
  };
  list.addEventListener("change", update);
  id.addEventListener("input", update);
  const add = el("button", { type: "button", class: "primary", dataset: { addNode: "add" } }, "Add");
  const cancel = el("button", { type: "button", dataset: { addNode: "cancel" } }, "Cancel");
  const dlg = el("dialog", { class: "add-node-dialog", "aria-labelledby": "add-node-title", dataset: { addNode: "dialog" } },
    el("h2", { id: "add-node-title" }, `Add a node to ${netName(S.config) || "the network"}`),
    err,
    el("div", { class: "grid" },
      el("label", { class: "wide" }, "Device description", list, el("div", { class: "row" }, eds.browse), eds.empty),
      el("label", null, "Node ID", id, idMsg),
      el("label", null, "Name", name, hint("The node's name in the config and the PLC variable names.")),
      el("div", { class: "check-field wide" }, el("label", { class: "check" }, mapBox, " Map the EDS's default PDOs"),
        hint(locations ? "Every PDO the device sends or receives by default, with its default mapping and a free PLC location for each entry."
          : "Every PDO the device sends or receives by default, with its default mapping and a variable name for each entry."))),
    el("menu", null, cancel, add));
  update();
  const opener = document.activeElement;
  document.body.append(dlg);
  const answer = await new Promise((resolve) => {
    finish = () => {
      const c = eds.choice();
      if (!c) { err.say("Pick the device's EDS file, or Browse… for it."); list.focus(); return; }
      const p = nodeIdProblem(id.value);
      if (p) { err.say(p); id.focus(); return; }
      if (!name.value.trim()) { err.say("Give the node a name."); name.focus(); return; }
      if ((S.config.nodes || []).some((n) => n.name === name.value.trim())) { err.say(`${name.value.trim()} is the name of another node of this network.`); name.focus(); return; }
      resolve({ choice: c, id: Number(id.value.trim()), name: name.value.trim(), map: mapBox.checked });
    };
    add.onclick = finish;
    for (const x of [id, name]) x.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); add.click(); } });
    cancel.onclick = () => resolve(null);
    dlg.addEventListener("cancel", (e) => { e.preventDefault(); resolve(null); });
    dlg.showModal();
    (list.options.length ? list : eds.browse).focus();
  });
  const done = () => { dlg.close(); dlg.remove(); };
  if (!answer) { done(); S.addedReport = null; if (opener && opener.isConnected) opener.focus(); return; }
  // The dialog stays, its Add busy, until the node and its PDOs are in.
  add.disabled = cancel.disabled = true;
  add.textContent = "Adding…";
  try {
    const c = answer.choice;
    // A file dropped on #eds-input before the dialog: its import report.
    if (!c.res && S.addedReport && S.addedReport.name === c.name) c.res = S.addedReport;
    const res = await edsIntoDraft(c, edsLint());
    if (!res) return;
    await addNode(res.name, answer.id, answer.name, answer.map, res, done);
    edsNotesArrived(res);
  } catch (e) {
    banner(e.message, true);
  } finally {
    S.addedReport = null;
    if (dlg.isConnected) done();
  }
}

// Adds the node, maps the EDS's default PDOs when asked, and opens it on
// PDOs (General when nothing was mapped). `report`: the EDS import's answer,
// whose findings are shown in words; a clean EDS shows nothing.
// `closeFirst`: closes the dialog before the page draws the node, so the
// focus goes to the node page, not back to what opened the dialog.
async function addNode(edsName, id, name, map, report, closeFirst) {
  const eds = (S.state.eds || {})[edsName];
  S.config.nodes = S.config.nodes || [];
  const node = { node_id: id, name, eds: edsName };
  superviseNewNode(node, eds, S.net);
  S.config.nodes.push(node);
  const i = S.config.nodes.length - 1;
  const { count: mapped, eventDriven } = map ? await mapDefaultPdos(i, eds) : { count: 0, eventDriven: [] };
  S.view = "node:" + i;
  S.nodeTab = mapped ? "pdos" : "general";
  if (!mapped) S.focusName = i;
  const shown = report && report.name === edsName ? importReport(report) : null;
  if (shown) for (const x of shown.querySelectorAll('[data-report="readable"]')) x.remove();
  if (eventDriven.length) {
    const line = el("div", { dataset: { report: "event-driven" } }, `${eventDriven.join(", ")} ${eventDriven.length === 1 ? "has" : "have"} ` +
      "transmission type 255 (event-driven): the EDS gives a synchronous type, and this network has no SYNC.");
    if (shown) shown.append(line);
    else banner(el("span", { dataset: { timed: "1" } }, line), "info");
  }
  if (shown && shown.childElementCount) banner(shown, "info");
  else if (!eventDriven.length) banner("");
  if (closeFirst) closeFirst();
  changed(true);
}

// The default mapping of every PDO the EDS turns on by default, without
// dummy entries; a free PLC location for each entry, or a variable name
// when the target has no locations. On a network without SYNC, a mapped
// PDO whose EDS type needs SYNC gets 255, unless the EDS fixes the type.
// Returns how many PDOs were mapped and the ones made event-driven.
async function mapDefaultPdos(i, eds) {
  const n = S.config.nodes[i];
  const locations = usedBy("nodes.tx_pdos.entries.iec_location");
  const names = new Set();
  const eventDriven = [];
  let count = 0;
  for (const [dir, key] of [["input", "tx_pdos"], ["output", "rx_pdos"]]) {
    const total = eds && eds.pdo_count ? eds.pdo_count[dir] : 0;
    for (let number = 1; number <= total; number++) {
      const m = pdoMap(eds, dir, number);
      if (!m || !m.enabled || !m.has_default) continue;
      const entries = [];
      for (const d of m.defaults) {
        if (isDummy(d)) continue;
        const info = objectInfo(eds, d.index, d.subindex);
        if (!info || !info.type) continue;
        const e = { index: info.index, subindex: info.subindex, type: info.type };
        if (locations) {
          // A location per entry, placed against the config as it grows.
          n[key] = n[key] || [];
          let p = n[key].find((q) => num(q.number) === number);
          if (!p) { p = { number, entries: [] }; n[key].push(p); }
          const r = await api("POST", "/api/place", { config: fileConfig(), network: S.net, node: i, direction: dir, type: info.type });
          e.iec_location = r.location;
          p.entries.push(e);
        } else {
          let v = nodeNameFor(info.name || `${info.index}_${info.subindex}`).replace(/^node$/, "value");
          for (let k = 2; names.has(v); k++) v = `${v}_${k}`;
          names.add(v);
          e.name = v;
          entries.push(e);
        }
      }
      if (!locations && entries.length) { n[key] = n[key] || []; n[key].push({ number, entries }); }
      const p = (n[key] || []).find((q) => num(q.number) === number);
      if (p && p.entries.length) count++;
      else if (p) n[key].splice(n[key].indexOf(p), 1);
      if (p && p.entries.length && !syncSource(S.config.master)) {
        const t = commSub(eds, dir, number, 2);
        if (t && t.writable && Number.isInteger(t.value) && (t.value <= 240 || t.value === 252)) {
          p.transmission = 255;
          eventDriven.push(`${dir === "input" ? "TPDO" : "RPDO"} ${number}`);
        }
      }
    }
  }
  return { count, eventDriven };
}

async function addEntry(i, o, dir, into) {
  const n = S.config.nodes[i];
  const key = dir === "input" ? "tx_pdos" : "rx_pdos";
  // An object of a device mapping goes into that PDO; else into the PDO
  // whose "Add entry…" opened the picker.
  const number = devicePdoFor(i, dir, o) ?? into ?? null;
  if (number !== null) {
    await addToPdo(i, dir, number, o);
    changed(true);
    return;
  }
  const r = await api("POST", "/api/place", { config: fileConfig(), network: S.net, node: i, direction: dir, type: o.type });
  if (r.pdo === null || r.pdo === undefined) { banner(`Cannot add ${o.index}:${o.subindex}: ${r.reason}.`, true); return; }
  n[key] = n[key] || [];
  if (r.pdo === n[key].length) n[key].push({ entries: [] });
  n[key][r.pdo].entries = n[key][r.pdo].entries || [];
  n[key][r.pdo].entries.push({ index: o.index, subindex: o.subindex, type: o.type, iec_location: r.location });
  changed(true);
}

function removeEntry(i, key, j, k) {
  const pdos = S.config.nodes[i][key];
  const number = pdos[j].number ?? j + 1;
  const [e] = pdos[j].entries.splice(k, 1);
  if (!pdos[j].entries.length) dropPdo(pdos, j);
  changed(true);
  removedBanner(`${e.index}:${e.subindex ?? 0} from ${key === "tx_pdos" ? "TPDO" : "RPDO"} ${number}`);
}

// Takes PDO j out of the list. The PDOs after it keep their numbers: one
// numbered by its place gets its number written.
function dropPdo(pdos, j) {
  for (let x = j + 1; x < pdos.length; x++) if (pdos[x].number === undefined) pdos[x].number = x + 1;
  pdos.splice(j, 1);
}

async function removePdo(i, key, j) {
  const pdos = S.config.nodes[i][key];
  const number = pdos[j].number ?? j + 1;
  if (key === "tx_pdos" && !(await dropLinksOf(S.config.nodes[i], num(number)))) return;
  dropPdo(pdos, j);
  changed(true);
  removedBanner(`${key === "tx_pdos" ? "TPDO" : "RPDO"} ${number}`);
}

function moveEntry(i, key, j, k, to) {
  const pdos = S.config.nodes[i][key];
  const [e] = pdos[j].entries.splice(k, 1);
  if (to === "new") pdos.push({ entries: [e] });
  else pdos[Number(to)].entries.push(e);
  if (!pdos[j].entries.length) dropPdo(pdos, j);
  changed(true);
}

async function removeNode(i) {
  const n = S.config.nodes[i];
  const id = num(n.node_id);
  // What names the node: listed, and removed with it unless kept to point elsewhere.
  const u = Number.isInteger(id) ? nodeUses(id) : { routes: [], from: [], to: [], watches: [] };
  const own = new Set((n.heartbeat_watch || []));
  const watches = u.watches.filter((h) => !own.has(h));
  const links = new Set(u.from.concat(linkList().filter((l) => (l.to || []).some((c) => u.to.includes(c)))));
  const uses = [];
  if (links.size) uses.push([...links].map((l) => linkName(l, linkList().indexOf(l))).join(", "));
  if (u.routes.length) uses.push(u.routes.map((r) => `gateway route ${r.name || S.model.top.gateway.routes.indexOf(r) + 1}`).join(", "));
  const watchers = S.config.nodes.filter((m) => m !== n && (m.heartbeat_watch || []).some((h) => watches.includes(h)));
  if (watchers.length) uses.push(`the heartbeat watch of ${watchers.map(nodeText).join(", ")}`);
  const text = `Remove node ${n.node_id} ${n.name || ""}? Its EDS file stays in the folder.` +
    (uses.length ? ` It is used by ${uses.join("; ")}.` : "");
  const v = await modal(text, uses.length
    ? [["cancel", "Keep the node"], ["node", "Remove the node only"], ["remove", "Remove node and its uses", { danger: true }]]
    : [["cancel", "Keep the node"], ["remove", "Remove node", { danger: true }]]);
  if (v !== "remove" && v !== "node") return;
  if (v === "remove" && uses.length) {
    // Its links as producer go; as consumer it leaves the link's consumers.
    const keep = linkList().filter((l) => !u.from.includes(l));
    for (const l of keep) if (Array.isArray(l.to)) l.to = l.to.filter((c) => !u.to.includes(c));
    if (keep.length) S.config.links = keep; else delete S.config.links;
    const g = S.model.top.gateway;
    if (g && u.routes.length) g.routes = g.routes.filter((r) => !u.routes.includes(r));
    for (const m of S.config.nodes) {
      if (m === n || !m.heartbeat_watch) continue;
      m.heartbeat_watch = m.heartbeat_watch.filter((h) => !watches.includes(h));
      if (!m.heartbeat_watch.length) delete m.heartbeat_watch;
    }
  }
  S.config.nodes.splice(i, 1);
  S.supervision = {};
  S.view = "bus";
  changed(true);
  removedBanner(`node ${n.node_id} ${n.name || ""}`.trim());
}

// A startup write runs at every boot: storing (0x1010) would wear the
// device's flash each time, restoring (0x1011) would reset it to factory
// values each time. Never listed, refused when typed.
const NO_STORE_WRITE = {
  0x1010: "0x1010 (store parameters) is never a startup write: it would store at every boot and wear the device's memory. Use Store on device on the node's Parameters tab, once, when you mean it.",
  0x1011: "0x1011 (restore defaults) is never a startup write: it would reset the device to factory values at every boot. Use Factory defaults on the node's Parameters tab, or the master's Restore before configure.",
};

async function addSdo(i, index, subindex) {
  const n = S.config.nodes[i];
  const eds = edsFor(n);
  const ix = num(index), sx = num(String(subindex));
  if (isNaN(ix) || ix > 0xFFFF || isNaN(sx) || sx > 255) { banner("Give the index as 0x… and the subindex as 0–255.", true); return; }
  if (ix === 0x1010 || ix === 0x1011) { banner(NO_STORE_WRITE[ix], true); return; }
  const info = objectInfo(eds, ix, sx);
  let type;
  if (info) {
    if (!info.writable) {
      banner(`${hex4(ix)}:${sx} (${info.name}) cannot be written: its AccessType is ${info.access}.`, true);
      return;
    }
    if (!info.type) { banner(`${hex4(ix)}:${sx} has a data type the config does not support.`, true); return; }
    type = info.type;
  } else {
    // The plugin checks every startup SDO against the EDS and refuses the config otherwise.
    banner(`${hex4(ix)}:${sx} is not in ${n.eds || "the node's EDS"}; the plugin only writes objects the EDS defines.`, true);
    return;
  }
  n.sdo = n.sdo || [];
  const value = info && info.default && /^(0x[0-9a-f]+|-?[0-9]+)$/i.test(info.default) ? info.default : 0;
  const listed = n.sdo.some((o) => sameObject(o.index, o.subindex, ix, sx));
  n.sdo.push({ index: hex4(ix), subindex: sx, type, value });
  banner(listed ? `${hex4(ix)}:${sx} is already written at startup; added again, and the last write wins.` : "", "warning");
  changed(true);
  const field = document.querySelector(`#view input[data-path="nodes[${i}].sdo[${n.sdo.length - 1}].value"]`);
  if (field) field.focus();
}

async function addSdoVar(i, index, subindex, direction) {
  const n = S.config.nodes[i];
  const ix = num(index), sx = num(String(subindex));
  if (isNaN(ix) || ix > 0xFFFF || isNaN(sx) || sx > 255) { banner("Give the index as 0x… and the subindex as 0–255.", true); return; }
  const info = objectInfo(edsFor(n), ix, sx);
  const write = direction === "write";
  if (!info) {
    // The plugin checks every SDO variable against the EDS and refuses the config otherwise.
    banner(`${hex4(ix)}:${sx} is not in ${n.eds || "the node's EDS"}; SDO variables must name objects the EDS defines.`, true);
    return;
  }
  if (write ? !info.writable : !info.readable) {
    banner(`${hex4(ix)}:${sx} (${info.name}) cannot be ${write ? "written" : "read"}: its AccessType is ${info.access}.`, true);
    return;
  }
  if (!info.type) { banner(`${hex4(ix)}:${sx} has a data type the config does not support.`, true); return; }
  const r = await api("POST", "/api/place", { config: fileConfig(), network: S.net, node: i, direction: write ? "sdo_write" : "sdo_read", type: info.type });
  n.sdo_variables = n.sdo_variables || [];
  n.sdo_variables.push({ index: hex4(ix), subindex: sx, type: info.type, direction, iec_location: r.location });
  banner("");
  changed(true);
}

function moveSdo(i, j, d) {
  const list = S.config.nodes[i].sdo;
  [list[j], list[j + d]] = [list[j + d], list[j]];
  changed(true);
  // The focus stays with the moved write: on the same arrow, or the other one at the end of the list.
  const row = document.querySelector(`#view tr[data-path="nodes[${i}].sdo[${j + d}]"]`);
  const arrow = (t) => row && row.querySelector(`button[title="${t}"]:not(:disabled)`);
  const b = arrow(d < 0 ? "Up" : "Down") || arrow(d < 0 ? "Down" : "Up");
  if (b) b.focus();
}

// ---------------------------------------------------------------------------
// Checks

function scheduleCheck() {
  document.body.dataset.checking = "1";
  clearTimeout(S.checkTimer);
  S.checkTimer = setTimeout(runCheck, 250);
  updateSave();
}

async function runCheck() {
  const seq = ++S.checkSeq;
  try {
    const cfg = fileConfig();
    const r = await api("POST", "/api/check", { config: cfg, allow_overlap: $("#allow-overlap").checked,
      task_interval: S.taskInterval || undefined, notes: S.model.notes });
    if (seq !== S.checkSeq) return;
    S.check = normCheck(r, fileVersion(cfg));
    if (S.view === "declarations") {
      const ti = $("#task-interval");
      if (ti && (S.taskIntervalDirty || document.activeElement === ti))
        S.taskIntervalTyping = { value: ti.value, caret: ti.selectionStart ?? ti.value.length };
      render();
    } else applyCheck();
    // The register map follows the draft (bridge.js).
    if (S.view === "bridge") await bridgeRefreshMap();
  } catch (e) {
    banner(e.message, true);
  }
  if (seq === S.checkSeq) document.body.dataset.checking = "0";
}

// The open tab's network name when the draft has several (exports name it).
function tabNetwork() { return several() ? netName(S.config) : null; }
// A network with DCFs: a CANopen master network.
function dcfNetwork(net) { return !!net && !isSlave(net) && !isJ1939(net); }

// Exports the draft (saved or not) as CiA 306 DCF files: one node's file,
// or every node's in a zip. With several networks: the open tab's nodes, or
// every network in a folder per network. Problems go to the Problems pane,
// and nothing is downloaded.
async function exportDcf(nodeId, network) {
  const one = nodeId !== undefined;
  if (one && !Number.isInteger(nodeId)) { banner("Give the node a node ID first.", true); return; }
  if (!one && several() && dcfNetwork(S.config)) {
    const label = netLabel(S.config, S.net);
    const v = await modal(`Export the DCF files of network ${label}, or of every network (a folder per network in the zip)?`,
      [["tab", `Network ${label}`], ["all", "All networks", true], ["cancel", "Cancel"]]);
    if (v !== "tab" && v !== "all") return;
    network = v === "tab" ? netName(S.config) : null;
  }
  try {
    const cfg = fileConfig();
    const body = { config: cfg };
    if (one) body.node = nodeId;
    if (network) body.network = network;
    const r = await api("POST", "/api/export_dcf", body);
    if (r.errors) { exportStopped("DCF", r, cfg); return; }
    const bytes = Uint8Array.from(atob(r.data), (c) => c.charCodeAt(0));
    const url = URL.createObjectURL(new Blob([bytes], { type: r.content_type }));
    const a = el("a", { href: url, download: r.name });
    document.body.append(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 10000);
    banner(`Exported ${r.name}${one ? "" : ` (${r.files.join(", ")})`}, checked against CiA 306.`);
  } catch (e) {
    banner(e.message, true);
  }
}

// Exports the draft (saved or not) as one HTML document of every network.
// Errors go to the Problems pane and nothing is downloaded; warnings go there
// after the download.
async function exportHtml() {
  try {
    const cfg = fileConfig();
    const r = await api("POST", "/api/export_html", { config: cfg, notes: S.model.notes });
    if (r.errors) { exportStopped("Documentation", r, cfg); return; }
    exportCheck(r, cfg);
    const bytes = Uint8Array.from(atob(r.data), (c) => c.charCodeAt(0));
    const url = URL.createObjectURL(new Blob([bytes], { type: r.content_type }));
    const a = el("a", { href: url, download: r.name });
    document.body.append(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 10000);
    banner(`Exported ${r.name}${warnedText(r)}.`);
  } catch (e) {
    banner(e.message, true);
  }
}

// Download for CODESYS (a CODESYS project's header and CODESYS page): the
// draft's CANopen master networks as node DCFs, the plan and
// import_canworks.py in one zip. Problems go to the Problems pane, and
// nothing is downloaded.
async function exportCodesys() {
  if (handoffRefused(document.querySelector("[data-codesys-download]"))) return;
  try {
    const cfg = fileConfig();
    const r = await api("POST", "/api/export_codesys", { config: cfg });
    if (r.errors) { exportStopped("CODESYS", r, cfg); return; }
    const bytes = Uint8Array.from(atob(r.data), (c) => c.charCodeAt(0));
    const url = URL.createObjectURL(new Blob([bytes], { type: r.content_type }));
    const a = el("a", { href: url, download: r.name });
    document.body.append(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 10000);
    const device = getPath("codesys.device");
    banner(`Exported ${r.name}: unzip it and run import_canworks.py in CODESYS (Tools > Scripting > Execute Script File) on your project. ` +
      (device ? `The bus goes to device ${device}.` : "The bus goes to the project's active device."));
  } catch (e) {
    banner(e.message, true);
  }
}

// Downloads the notes of one EDS with unsaved edits: merged with the built-in
// ones, or with `own` the user's own only.
async function exportNotes(name, own) {
  try {
    const r = await api("POST", "/api/export_notes", { config: fileConfig(), eds: name, notes: S.model.notes, own: !!own });
    const url = URL.createObjectURL(new Blob([r.data], { type: "application/json" }));
    const a = el("a", { href: url, download: r.name });
    document.body.append(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 10000);
    banner(`Exported ${r.name}.`);
  } catch (e) {
    banner(e.message, true);
  }
}

// Exports the draft (saved or not) as a DBC file for CAN bus tools, with
// the SDO frames chosen next to the button: the open tab's network. Errors go to the Problems pane
// and nothing is downloaded; warnings go there after the download.
async function exportDbc() {
  try {
    const cfg = fileConfig();
    const body = { config: cfg, sdo: $("#dbc-sdo").value, notes: S.model.notes };
    if (several()) body.network = netName(S.config);
    const r = await api("POST", "/api/export_dbc", body);
    if (r.errors) { exportStopped("DBC", r, cfg); return; }
    exportCheck(r, cfg);
    const bytes = Uint8Array.from(atob(r.data), (c) => c.charCodeAt(0));
    const url = URL.createObjectURL(new Blob([bytes], { type: r.content_type }));
    const a = el("a", { href: url, download: r.name });
    document.body.append(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 10000);
    banner(`Exported ${r.name}${warnedText(r)}.`);
  } catch (e) {
    banner(e.message, true);
  }
}

// An export's check result replaces the Problems pane (it includes the
// config check), so the count stays the number of distinct problems; the
// next edit-time check restores the usual list.
// An export's check in the Problems pane: the config check's items stay as
// they are (the export repeats them, without the warnings) and the export's
// own findings join them, so the count does not jump; the previous check's
// declarations stay too, so the declarations page and the "declared as"
// hints do not go blank.
function exportProblems(r, cfg) {
  const fresh = normCheck(r, fileVersion(cfg));
  // The config check's, not an earlier export's: a failed export's findings
  // replace the previous export's.
  const prev = (S.check && S.check.base) || S.check || {};
  fresh.base = prev;
  const key = (it) => readable(it.message) + "|" + JSON.stringify(it.paths || []);
  if (prev.items) {
    const seen = new Set(prev.items.map(key));
    fresh.items = prev.items.concat((fresh.items || []).filter((it) => !seen.has(key(it))));
    fresh.errors = fresh.items.filter((it) => it.level === "error").length;
  }
  for (const k of ["declared", "declarations", "block"]) if (fresh[k] === undefined && prev[k] !== undefined) fresh[k] = prev[k];
  return fresh;
}

function exportCheck(r, cfg) {
  const prevErrors = S.check ? S.check.errors : 0;
  const items = r.items || [];
  if (items.length || r.errors) {
    S.check = exportProblems(r, cfg);
    applyCheck();
    if (items.length) openProblems();
  } else if (prevErrors) {
    scheduleCheck();
  }
}

// " with 2 warnings" for a successful export's message; Problems lists them.
function warnedText(r) {
  const n = (r.items || []).length;
  return n ? ` with ${n} warning${n === 1 ? "" : "s"}` : "";
}

// A stopped export reports in Problems only (export-problems-one-place):
// its findings join the list under a summary bar at the top of the panel,
// the panel opens and comes into view, and the page's message bar stays
// empty. Focus stays where it is; the summary is an alert. Where Problems is
// not shown, the message bar says it instead.
function exportStopped(label, r, cfg) {
  S.check = exportProblems(r, cfg);
  S.check.export = label;
  applyCheck();
  const panel = $("#problems");
  if (!panel || panel.hidden || $("#bottom").hidden) {
    banner(`${label} export stopped: ${r.errors} problem${r.errors === 1 ? "" : "s"}. Nothing was downloaded.`, true);
    return;
  }
  banner("");
  openProblems();
}

// The errors that stop a hand-off step (spec "Hand-off steps need a config
// without errors"): the check's errors and the warnings it marks as
// stopping a hand-off (a network without nodes). Allowed overlaps are
// warnings, so they do not count.
function handoffErrors() {
  return ((S.check && S.check.items) || []).filter((it) => it.level === "error" || it.handoff).length;
}

// Refuses a hand-off step while the config has errors: one line next to
// `control` (or the message bar without one) naming the count, with a link
// that opens Problems. Returns whether it refused.
function handoffRefused(control, count) {
  const n = count ?? handoffErrors();
  const box = control && (control.closest(".toolbar") || control.parentElement);
  const old = box && box.parentElement && box.parentElement.querySelector(":scope > [data-handoff-refused]");
  if (!n) { if (old) old.remove(); return false; }
  const text = `The saved config has ${counted(n, "error", "errors")}: fix ${n === 1 ? "it" : "them"} first.`;
  const link = () => el("button", { type: "button", class: "link", dataset: { openProblems: "1" }, onclick: openProblems }, "Open Problems");
  if (!box) { banner(el("span", { dataset: { handoffRefused: "1" } }, text + " ", link()), true); return true; }
  const line = el("p", { class: "field-msg handoff-msg", role: "alert", dataset: { handoffRefused: "1" } }, text + " ", link());
  if (old) old.replaceWith(line); else box.after(line);
  return true;
}

// Opens the Problems panel and brings it into view.
function openProblems() {
  const box = $("#problems-box");
  if (!box || $("#problems").hidden) return;
  box.open = true;
  box.scrollIntoView({ block: "nearest" });
}

// The summary bar of a stopped export at the top of Problems, while its findings are listed.
function problemsSummary() {
  const slot = $("#problems-bars");
  if (!slot) return;
  const label = S.check && S.check.export;
  if (slot.dataset.export === (label || "")) return;
  slot.dataset.export = label || "";
  slot.replaceChildren(...(label ? [notice("error",
    `${label} export stopped. Nothing was downloaded. Fix the problems below and export again.`,
    { dataset: { exportStopped: label } })] : []));
}

// The SDO choice for the DBC export, kept with the theme in the settings folder.
async function wireDbc() {
  const sel = $("#dbc-sdo");
  try { sel.value = (await api("GET", "/api/ui")).dbc_sdo || "none"; } catch (e) { /* keep the default */ }
  sel.onchange = async () => {
    try { await api("POST", "/api/ui", { dbc_sdo: sel.value }); } catch (e) { banner(e.message, true); }
  };
}

function applyCheck() {
  for (const x of document.querySelectorAll(".invalid, .warned")) x.classList.remove("invalid", "warned");
  for (const x of document.querySelectorAll(".field-msg[data-for]")) x.textContent = "";
  // One name per entry: the Variable placeholder is the name the declarations
  // use; "declared as" only when the editor project declares it otherwise.
  const prefix = fileVersion(fileConfig()) === 2 ? `networks[${S.net}].` : "";
  for (const x of document.querySelectorAll(".decl")) {
    const name = declaredAs(x.dataset.declFor);
    const d = ((S.check && S.check.declarations) || []).find((y) => y.path === prefix + x.dataset.declFor);
    x.textContent = name && (!d || d.name !== name) ? ` declared as ${name}` : "";
  }
  for (const x of document.querySelectorAll("input[data-entry-variable]")) {
    x.placeholder = entryVariable(x.dataset.entryVariable, prefix);
    x.title = x.placeholder;
  }
  // A bit's default name follows its entry's name (and the declaration's, when declared).
  for (const x of document.querySelectorAll("input[data-bit-of]")) {
    const prefix = fileVersion(fileConfig()) === 2 ? `networks[${S.net}].` : "";
    const d = ((S.check && S.check.declarations) || []).find((y) => y.kind === "pdo" && y.path === prefix + x.dataset.path.replace(/\.name$/, ".iec_location"));
    if (d) x.placeholder = d.entry_name;
  }
  problemsSummary();
  const list = $("#problem-list");
  const focused = document.activeElement && document.activeElement.closest("#problem-list li");
  const focusedAt = focused ? [...list.children].indexOf(focused) : -1;
  list.replaceChildren();
  const items = (S.check && S.check.items) || [];
  for (const it of items) {
    const where = it.where || (it.paths || []).map((p) => ({ net: S.net, path: p }));
    const li = el("li", { class: it.level }, el("button", { type: "button", title: it.message,
      onclick: () => focusPath(where[0]) }, Icons.stateIcon(it.level === "error" ? "error" : "warning", { label: false }), problemText(it, where[0])));
    const fixes = problemFixes(it, where[0]);
    if (fixes.length) li.append(el("span", { class: "problem-fixes", dataset: { problemFixes: "1" } }, ...fixes));
    list.append(li);
    for (const w of where) {
      // Fields of another network's tab are not on the page.
      if (w.net !== null && w.net !== S.net) continue;
      const p = w.path;
      const input = pathTarget(p);
      if (input && (input.tagName === "INPUT" || input.tagName === "SELECT")) input.classList.add(it.level === "error" ? "invalid" : "warned");
      const msg = document.querySelector(`.field-msg[data-for="${CSS.escape(p)}"]`);
      if (msg) {
        msg.textContent = (msg.textContent ? msg.textContent + " " : "") + fieldText(it, where[0], w);
        msg.classList.toggle("warning", it.level !== "error");
      }
    }
  }
  if (!items.length && S.check) list.append(el("li", { class: "ok" }, Icons.stateIcon("ok", { label: false }), "No problems."));
  if (focusedAt >= 0) { const b = list.children[Math.min(focusedAt, list.children.length - 1)]; if (b && b.firstChild && b.firstChild.focus) b.firstChild.focus(); }
  // The overlap override goes with the overlap errors, and stays while ticked.
  const overlaps = items.some((it) => it.overlap || it.overlap_allowed);
  $("#overlap-box").hidden = !(S.state && S.state.mode === "project" && (overlaps || $("#allow-overlap").checked));
  fillCounts(countProblems());
  stripProblems(items.length);
  updateSave();
}

// Problems is a one-line strip while there is nothing in it (compact-chrome):
// it folds when the count drops to none and unfolds, as the user left it,
// when problems come back. A fold or unfold by hand in between stays.
function stripProblems(n) {
  const box = $("#problems-box");
  if (!box || workspace() !== "configure" || !S.check) return;
  const had = S.problemsShown;
  S.problemsShown = n;
  if (had !== undefined && (had > 0) === (n > 0)) return;
  const want = n > 0 && S.panelOpen !== false;
  if (box.open !== want) { S.panelAuto = true; box.open = want; }
}

// The problem counts from the last check, in one place: all, errors, per
// node of the open network and errors per network.
function countProblems() {
  const items = (S.check && S.check.items) || [];
  const counts = {};
  const netErrors = {};
  let errors = 0;
  for (const it of items) {
    if (it.level === "error") errors++;
    const where = it.where || (it.paths || []).map((p) => ({ net: S.net, path: p }));
    if (it.level === "error") for (const k of new Set(where.map((w) => w.net))) if (k !== null) netErrors[k] = (netErrors[k] || 0) + 1;
    for (const w of where) {
      if (w.net !== null && w.net !== S.net) continue;
      const m = /^nodes\[(\d+)\]/.exec(w.path);
      if (m && it.level === "error") counts[m[1]] = (counts[m[1]] || 0) + 1;
    }
  }
  return { n: items.length, errors, counts, netErrors, checked: !!S.check };
}

function fillCounts(c) {
  $("#problem-count").textContent = c.checked ? (c.n ? `${c.n} problem${c.n === 1 ? "" : "s"}` : "none") : "";
  renderTree();
  if (typeof nodeTabBadges === "function") nodeTabBadges();
}

// A check message without the parts meant for the command line: the file
// name, the config path ("nodes[2]: tx_pdos[1]: entries[0]: ") and the node
// the place label already names.
const CONFIG_PATH_LEAD = /^(?:[A-Za-z]:)?[^:]*canworks\.json: /;
function readable(m) {
  // The config file's path first, a Windows one with its drive letter too.
  let t = m.replace(CONFIG_PATH_LEAD, "");
  while (/^[a-z_]+(\[\d+\])?(\.[a-z_]+(\[\d+\])?)*: /.test(t)) t = t.replace(/^[^:]*: /, "");
  t = t.replace(/^node \d+( \([^)]*\))?( [TR]PDO \d+)?(, |: )/, "");
  t = t.replace(/^object (0x[0-9A-Fa-f]+:\d+): /, "$1: ");
  // The link the place names already, and a watch's config path in words.
  t = t.replace(/^link [A-Za-z0-9_]+: /, "");
  t = t.replace(/^heartbeat_watch(\[\d+\])?: /, "heartbeat watch: ");
  return t;
}

// A check message from somewhere else on the page (a trace or Frame lab
// note, a dialog) in the Problems pane's words: the config path it starts
// with ("nodes[2]: tx_pdos[1]: entries[0]: ") becomes the place, and a
// "decoding without …:" lead stays in front.
function humanise(m) {
  if (typeof m !== "string") return m;
  const lead = /^(decoding without the config's (?:PDOs|nodes)|the configuration cannot be read for names and PDO mappings): ([\s\S]*)$/.exec(m);
  const head = lead ? lead[1].charAt(0).toUpperCase() + lead[1].slice(1) + ": " : "";
  let rest = lead ? lead[2] : m;
  if (/field 'nodes' lists no slave nodes/.test(rest)) return head + NO_NODES_TEXT;
  rest = rest.replace(CONFIG_PATH_LEAD, "");
  const segs = [];
  let mm;
  while ((mm = /^([a-z_]+(?:\[\d+\])?): /.exec(rest))) { segs.push(mm[1]); rest = rest.slice(mm[0].length); }
  const path = segs.join(".");
  const place = path && S.model ? placeOf({ net: S.net, path }) : [];
  let text = readable(rest);
  const obj = /^(0x[0-9A-Fa-f]+:\d+): /.exec(text);
  if (obj && place.length && place[place.length - 1] === obj[1]) text = text.slice(obj[0].length);
  return head + (place.length ? `${place.join(", ")}: ${text}` : text);
}

// A problem at one of its fields. At a field away from the node the problem
// is about (the master's node ID, for a node that has it) the text names
// that node, unless it already does.
function fieldText(it, first, w) {
  const text = readable(it.message);
  if (!first || w === first || (w.net ?? S.net) !== (first.net ?? S.net)) return text;
  const m = /^nodes\[(\d+)\]/.exec(first.path);
  if (!m || w.path.startsWith(m[0])) return text;
  const net = first.net === null || first.net === undefined ? S.config : S.model.networks[first.net];
  const n = ((net && net.nodes) || [])[Number(m[1])];
  if (!n || new RegExp(`\\bnode ${n.node_id}\\b`).test(text)) return text;
  return `Node ${n.node_id ?? "?"}${n.name ? " " + n.name : ""}: ${text}`;
}

// "Node 5 rtd, TPDO 2, 0x6150:1: type UNSIGNED8 ...", with the network first
// when the draft has several.
const NO_NODES_TEXT = "No nodes yet. Add a node from its EDS, or find the devices on the bus in Commission a device.";

// The plugin's refusal of a node without supervision (contract.supervision_message).
const NO_SUPERVISION = /has no heartbeat or guarding \(its EDS heartbeat 0x1017 defaults to 0\)/;

function problemText(it, w) {
  const where = placeOf(w);
  if (/field 'nodes' lists no slave nodes/.test(it.message)) return where.length ? `${where.join(", ")}: ${NO_NODES_TEXT}` : NO_NODES_TEXT;
  if (NO_SUPERVISION.test(it.message)) {
    const text = "has no heartbeat or guarding, so its loss would never be detected. Set the heartbeat period on Supervision.";
    return where.length ? `${where.join(", ")} ${text}` : upperFirst(text);
  }
  let text = readable(it.message);
  if (!where.length) return text;
  const obj = /^(0x[0-9A-Fa-f]+:\d+): /.exec(text);
  if (obj) {
    if (where[where.length - 1] !== obj[1]) where.push(obj[1]);
    text = text.slice(obj[0].length);
  }
  return `${where.join(", ")}: ${text}`;
}

// The buttons that fix a problem in one step (spec "Quick fixes in
// Problems"): each is one undo step.
function problemFixes(it, w) {
  if (!w || !NO_SUPERVISION.test(it.message)) return [];
  const m = /^nodes\[(\d+)\]/.exec(w.path || "");
  if (!m) return [];
  const net = w.net === null || w.net === undefined ? S.net : w.net;
  const i = Number(m[1]);
  const node = () => ((S.model.networks[net] || {}).nodes || [])[i];
  const n = node();
  if (!n) return [];
  const fix = (label, key, apply) => el("button", { type: "button", class: "small", dataset: { problemFix: key }, onclick: () => {
    const target = node();
    if (!target) return;
    if (net !== S.net) openNet(net);
    apply(target);
    S.supervision = {};
    changed(true);
  } }, label);
  const kind = newNodeSupervision(edsFor(n));
  return [
    kind === "guarding"
      ? fix("Use guarding", "guarding", (t) => { t.guard_time_ms = 1000; t.life_time_factor = 3; })
      : fix("Use heartbeat 1000 ms", "heartbeat", (t) => { t.heartbeat_ms = 1000; }),
    fix("Accept no supervision", "none", (t) => { t.heartbeat_ms = 0; }),
  ];
}

// A new node whose EDS heartbeat default is 0 would be unsupervised: it
// gets a heartbeat (or guarding) from the start, and Supervision says so.
function superviseNewNode(node, eds, net) {
  const hb = edsDefault(eds, 0x1017, 0);
  const kind = hb === 0 || hb === null ? newNodeSupervision(eds) : null;
  if (kind === "heartbeat") node.heartbeat_ms = 1000;
  if (kind === "guarding") { node.guard_time_ms = 1000; node.life_time_factor = 3; }
  if (kind) (S.addedSupervision = S.addedSupervision || new Set()).add(`${net}|${num(node.node_id)}`);
}

// The supervision a node added from `eds` gets when its EDS heartbeat
// default is 0 (spec "Supervision of a new node"): "heartbeat" when 0x1017
// is writable, "guarding" when 0x100C and 0x100D are, else null.
function newNodeSupervision(eds) {
  const writable = (ix) => { const o = objectInfo(eds, ix, 0); return !!(o && o.writable); };
  if (writable("0x1017")) return "heartbeat";
  if (writable("0x100C") && writable("0x100D")) return "guarding";
  return null;
}

// Where a check path ({ net, path }) is, in the page's words:
// ["Node 5 rtd", "TPDO 2"], led by "Network io" when there are several.
function placeOf(w) {
  if (!w || !w.path) return [];
  const net = w.net === null ? null : S.model.networks[w.net];
  const lead = several() && net ? [upperFirst(netNamed(net, w.net))] : [];
  const path = w.path;
  if (path.startsWith("master.diagnostics")) return ["Online access"];
  if (path.startsWith("master.cia309")) return ["Online access", "CiA 309-3 gateway"];
  if (path.startsWith("gateway")) {
    const r = /^gateway\.routes\[(\d+)\]/.exec(path);
    const rt = r && ((S.model.top.gateway || {}).routes || [])[Number(r[1])];
    return ["Gateway"].concat(rt ? [`route ${rt.name || Number(r[1]) + 1}`] : []);
  }
  if (path.startsWith("codesys")) return w.net === null || w.net === undefined ? ["CODESYS"] : lead.concat(["CODESYS"]);
  if (path.startsWith("bridge")) {
    const r = /^bridge\.live_lists\[(\d+)\]/.exec(path);
    const e = r && ((S.model.top.bridge || {}).live_lists || [])[Number(r[1])];
    return ["Modbus bridge"].concat(r ? [`live list ${(e && e.network) || Number(r[1]) + 1}`] : []);
  }
  if (!net) return [];
  if (path.startsWith("slave")) {
    const o = /^slave\.objects\[(\d+)\]/.exec(path);
    const b = o && ((net.slave || {}).objects || [])[Number(o[1])];
    return lead.concat(["Slave device"], b ? [`${b.index}:${b.subindex ?? 0}`] : []);
  }
  if (path.startsWith("adapter")) return lead.concat(["CAN adapter"]);
  if (path.startsWith("j1939")) return lead.concat(j1939Place(net, path));
  if (path.startsWith("raw")) {
    // "Received Status, signal Temp" for a CAN message's check path.
    const r = /^raw\.(rx|tx)\[(\d+)\](?:\.signals\[(\d+)\])?/.exec(path);
    const e = r && (((net.raw || {})[r[1]]) || [])[Number(r[2])];
    if (!e) return lead.concat(["CAN messages"]);
    const parts = [`${r[1] === "rx" ? "Received" : "Sent"} ${e.name || rawHex(e.id)}`];
    const sg = r[3] !== undefined ? (e.signals || [])[Number(r[3])] : null;
    if (sg) parts.push(`signal ${sg.name || Number(r[3]) + 1}`);
    return lead.concat(parts);
  }
  if (path.startsWith("master")) return lead.concat(["Master"]);
  if (path.startsWith("links")) return lead.concat(linkPlace(net, path));
  const m = /^nodes\[(\d+)\](?:\.(tx_pdos|rx_pdos|sdo|sdo_variables)\[(\d+)\](?:\.entries\[(\d+)\])?)?/.exec(path);
  const n = m && (net.nodes || [])[Number(m[1])];
  if (!n) return lead;
  const parts = lead.concat([`Node ${n.node_id ?? "?"}${n.name ? " " + n.name : ""}`]);
  const j = Number(m[3]);
  if (m[2] === "tx_pdos" || m[2] === "rx_pdos") {
    const p = (n[m[2]] || [])[j] || {};
    parts.push(`${m[2] === "tx_pdos" ? "TPDO" : "RPDO"} ${p.number ?? j + 1}`);
    const e = m[4] !== undefined ? (p.entries || [])[Number(m[4])] : null;
    if (e) parts.push(`${e.index}:${e.subindex ?? 0}`);
  } else if (m[2] === "sdo") {
    const x = (n.sdo || [])[j];
    parts.push("startup SDO" + (x ? ` ${x.index}:${x.subindex ?? 0}` : ""));
  } else if (m[2] === "sdo_variables") {
    const v = (n.sdo_variables || [])[j];
    parts.push("SDO variable" + (v ? " " + (v.name || `${v.index}:${v.subindex ?? 0}`) : ""));
  }
  return parts;
}

// The element of a check path: the field bound to it, else, for a part of a
// signal's mux ("signals[1].mux.values[0]", ".mux.on" without a switch
// picker), the signal's Page cell.
function pathTarget(p) {
  const q = (x) => document.querySelector(`[data-path="${CSS.escape(x)}"]`);
  const hit = q(p);
  if (hit) return hit;
  const m = /^(.*\.signals\[\d+\]\.mux)[.[]/.exec(p);
  return m ? q(m[1]) : null;
}

function focusPath(w) {
  if (!w || !w.path) return;
  if (w.net !== null && w.net !== S.net && S.model.networks[w.net]) switchNet(w.net);
  const path = w.path;
  const [entry, tab] = entryOfPath(w);
  unfoldFor(entry);
  const m = /^nodes\[(\d+)\]/.exec(path);
  if (m && tab) { const have = nodeTabs(Number(m[1])).map(([k]) => k); setNodeTab(have.includes(tab) ? tab : "general"); }
  const want = m ? "node:" + m[1] : entry === "project" ? "project" : path.startsWith("gateway") ? "gateway" : path.startsWith("bridge") ? "bridge"
    : entry === "codesys" ? "codesys" : path.startsWith("links") ? "links"
    : (path.startsWith("adapter") || path.startsWith("master") || path.startsWith("slave") || path.startsWith("j1939") ||
      path.startsWith("codesys") || path === "role" || path === "protocol" ? "bus" : S.view);
  if (workspace() !== "configure" && !isTool(want)) switchWorkspace("configure");
  // A CAN message's field is in its editor, which opens for it.
  const raw = /^raw\.(rx|tx)\[(\d+)\]/.exec(path);
  if (raw && (S.view !== "raw" || !S.rawOpen || S.rawOpen.kind !== raw[1] || S.rawOpen.index !== Number(raw[2]))) {
    S.rawOpen = { kind: raw[1], index: Number(raw[2]) };
    if (S.view === "raw") render(); else showView("raw");
  } else if (want !== S.view || m) showView(want);
  const target = pathTarget(path);
  if (!target) return;
  // A folded section opens for its field.
  for (let d = target.closest("details"); d; d = d.parentElement && d.parentElement.closest("details")) d.open = true;
  target.scrollIntoView({ block: "center" });
  // A field takes the focus; a block (an SDO variable, a PDO) hands it to its first field.
  const field = target.matches("input, select, textarea, button") ? target : target.querySelector("input:not([type=hidden]), select, textarea, button");
  (field || target).focus();
}

// The Save button: "Saved" and disabled when the draft equals the file,
// "Save" when it is dirty, disabled with the error count in its tooltip
// when the draft has errors (the count itself is in the Problems pane).
// A view that redraws replaces the focused control with a new one: the
// keyboard focus moves to the new control of the same id or data attributes
// instead of dropping to the page body (visual-refresh).
const FOCUS = { last: null, sig: null };
function focusSignature(e) {
  if (e.id) return "#" + CSS.escape(e.id);
  const attrs = [...e.attributes].filter((a) => a.name.startsWith("data-") && !/^data-(busy|disabled-reason|title-before)$/.test(a.name) || a.name === "aria-label" || a.name === "name");
  if (!attrs.length) return null;
  return e.tagName.toLowerCase() + attrs.map((a) => `[${a.name}="${CSS.escape(a.value)}"]`).join("");
}
document.addEventListener("focusin", (ev) => {
  const e = ev.target;
  // A dialog gives focus back itself when it closes: remember the control outside it.
  if (!(e instanceof Element) || e === document.body || e.closest("dialog")) return;
  FOCUS.last = e;
  FOCUS.sig = focusSignature(e);
});
function refocus() {
  const a = document.activeElement;
  if ((a && a !== document.body) || !FOCUS.last || document.querySelector("dialog[open]")) return;
  const last = FOCUS.last;
  if (last.isConnected) {
    // Disabled or hidden in place (a Scan button while it scans): next door.
    if ((last.disabled || !last.getClientRects().length) && !last.dataset.busy) focusNear(last);
    return;
  }
  const next = FOCUS.sig && document.querySelector(FOCUS.sig);
  if (next && !next.disabled && next.getClientRects().length) next.focus();
}
new MutationObserver(refocus).observe(document.documentElement, { childList: true, subtree: true, attributes: true, attributeFilter: ["disabled", "hidden"] });
// Focus can also drop with no change to the page (a dialog closing onto a removed control).
setInterval(refocus, 250);

// Focus for a control that just became disabled or hidden: the nearest
// usable control before it in its group (then after it), never the page body.
function focusNear(ctl) {
  const box = ctl.closest("header, [role=toolbar], .toolbar, menu, #conn-bar") || ctl.parentElement;
  const all = [...box.querySelectorAll("button, summary, input, select, [tabindex]")]
    .filter((e) => e === ctl || (!e.disabled && e.tabIndex >= 0 && e.getClientRects().length > 0 &&
      !(e.closest("details:not([open])") && e.tagName !== "SUMMARY")));
  const k = all.indexOf(ctl);
  const to = all.slice(0, k).reverse()[0] || all[k + 1];
  if (to) to.focus();
}

function updateSave() {
  const btn = $("#btn-save");
  if (btn.dataset.busy) return;
  // Save always saves: errors are listed in Problems and refused by the
  // steps that hand the config over, not here.
  const n = S.check ? (S.check.items || []).length : 0;
  btn.disabled = !S.dirty;
  btn.title = S.dirty ? "" : n ? `No unsaved changes; ${counted(n, "problem", "problems")} in Problems` : "No unsaved changes";
  btn.textContent = S.dirty ? "Save" : n ? `Saved, ${counted(n, "problem", "problems")}` : "Saved";
  const mark = document.querySelector("[data-unsaved]");
  if (mark) mark.hidden = !S.dirty;
}

async function save(overwrite) {
  const cfg = fileConfig();
  try {
    const r = await api("POST", "/api/save", { config: cfg, allow_overlap: $("#allow-overlap").checked, overwrite: !!overwrite,
      notes: S.model.notes });
    S.state = r.state;
    setModel(S.state.config);
    S.dirty = false;
    await checkToken();
    render();
    // After render: a test (or a quick user) acting on "Saved" acts on the new page.
    // Settings the target does not use are left out (canopen-configurator
    // "Settings the target does not use are left out on save").
    const left = r.left_out ? ` (${r.left_out} setting${r.left_out === 1 ? "" : "s"} ${TARGET_LABEL[projectTarget()]} does not use left out)` : "";
    if (r.errors) banner(`Saved with ${counted(r.errors, "error", "errors")}: ${TARGET_RUNNER[projectTarget()]} refuses this config until ${r.errors === 1 ? "it is" : "they are"} fixed. See Problems.`, "warning");
    else banner("Saved " + r.written.join(", ") + left);
    runCheck();
  } catch (e) {
    if (e.status === 409 && e.body.changed_on_disk) {
      const v = await modal("canworks.json changed on disk after it was loaded here (edited elsewhere?).",
        [["cancel", "Cancel"], ["reload", "Reload from disk"], ["overwrite", "Overwrite it", { danger: true }]]);
      if (v === "overwrite") return save(true);
      if (v === "reload") return reload(true);
    } else {
      banner(e.message, true);
    }
  }
}

// Whether anything on the page would be lost: draft edits, the simulation
// file, or a recording that was neither saved nor downloaded.
function unsavedWork() {
  if (TRACE_WINDOW) return traceWinUnsaved();  // the config is the main window's
  return S.dirty || (typeof simDirty === "function" && simDirty()) || (typeof traceWinUnsaved === "function" && traceWinUnsaved());
}

async function reload(force) {
  if (unsavedWork() && !force) {
    const v = await modal("Discard the unsaved changes and reload from disk?", [["cancel", "Keep editing"], ["reload", "Discard and reload", { danger: true }]]);
    if (v !== "reload") return;
  }
  await api("POST", "/api/reload");
  await loadState();
}

async function closeFolder() {
  if (!(await leaveCommission("closing"))) return;
  if (unsavedWork()) {
    const what = typeof traceUnsaved === "function" && traceUnsaved() && !S.dirty && !simDirty()
      ? "Close? The recording was neither saved to the traces folder nor downloaded, and is lost."
      : "Close without saving? The unsaved changes are lost.";
    const v = await modal(what, [["cancel", "Cancel"], ["close", "Close without saving", { danger: true }]]);
    if (v !== "close") return;
  }
  stopOnline(false);
  stopSim(false);
  await api("POST", "/api/close");
  // The closed folder's scan and online picks are not the next one's: a
  // device commissioned next showed the project's nodes as configured.
  S.scanResult = null;
  S.lssFound = null;
  S.onlineNet = null;
  S.onlineNode = null;
  S.onlineEds = null;
  S.onlineEdsName = null;
  S.identity = null;
  S.lssDevice = null;
  await loadState();
}

async function moveIntoProject() {
  if (S.dirty) { banner("Save the config before moving it into a project.", true); return; }
  const input = el("input", { type: "text", spellcheck: "false", "aria-label": "Editor project folder", class: "wide" });
  input.value = S.state.home;
  const v = await modal("Editor project folder to copy this config into (its canworks/ folder):",
    [["move", "Move into project", true], ["cancel", "Cancel"]], input);
  if (v !== "move") return;
  const project = input.value.trim();
  let r;
  try {
    r = await api("POST", "/api/move", { project });
  } catch (e) {
    if (e.status === 409 && e.body.exists) {
      const w = await modal(`${project} already has a canworks/ folder. Replace it?`, [["cancel", "Cancel"], ["replace", "Replace", { danger: true }]]);
      if (w !== "replace") return;
      try { r = await api("POST", "/api/move", { project, replace: true }); } catch (e2) { banner(e2.message, true); return; }
    } else { banner(e.message, true); return; }
  }
  S.state = r.state;
  setModel(S.state.config);
  if (typeof simLoad === "function") simLoad();
  S.dirty = false;
  S.view = "bus";
  render();
  banner("Moved into " + project + ": " + r.written.join(", "));
  runCheck();
}

// A new editor project around the saved standalone config: openplc-cli create,
// the target set, main declaring every CANopen location, the config copied in.
async function newEditorProject() {
  if (S.dirty) { banner("Save the config before creating a project from it.", true); return; }
  const field = (label, value, aria) => {
    const input = el("input", { type: "text", spellcheck: "false", "aria-label": aria, class: "wide" });
    input.value = value;
    return [el("label", null, label, input), input];
  };
  const [pl, parent] = field("Folder to create it in", S.state.home, "Parent folder");
  const [nl, name] = field("Project name (its folder: new, or an existing empty one)", "", "Project name");
  const [il, interval] = field("Task interval", "T#20ms", "Task interval");
  const blocks = el("input", { type: "checkbox", "aria-label": "Enable the canworks function blocks", dataset: { newProject: "blocks" } });
  const sl = el("label", { class: "inline", title: "Enables the canworks function block library (CANopen, CiA 402, CAN and J1939 blocks) in the project and installs it into the editor" },
    blocks, " Enable the canworks function blocks");
  const form = el("div", { class: "new-project" }, pl, nl, il, sl,
    el("p", { class: "hint" }, "The program main declares every CANopen location once. Later config changes do not " +
      "change it: declare new locations from Variable declarations."));
  let text = "New OpenPLC Editor project (target OpenPLC Runtime v4) with this config in its canworks/ folder:";
  for (;;) {
    const v = await modal(text, [["create", "Create project", true], ["cancel", "Cancel"]], form);
    if (v !== "create") return;
    let r;
    const finish = modalWorking("Creating the editor project…");
    try {
      r = await api("POST", "/api/new_project", { parent: parent.value.trim(), name: name.value.trim(),
        interval: interval.value.trim(), blocks: blocks.checked });
      finish();
    } catch (e) {
      finish();
      text = "Not created: " + e.message;
      continue;
    }
    S.state = r.state;
    setModel(S.state.config);
    if (typeof simLoad === "function") simLoad();
    S.dirty = false;
    S.view = "bus";
    render();
    banner(`Created ${r.project} with ${r.declared} CANopen variable${r.declared === 1 ? "" : "s"} declared in main. ` +
      "Open it in the editor with Open Project." + (r.library ? " " + r.library[0].toUpperCase() + r.library.slice(1) + "." : ""),
      r.library_ok === false);
    runCheck();
    return;
  }
}

// ---------------------------------------------------------------------------
// Theme: Light, Dark or Auto (the OS setting), kept by the server in the
// settings folder and put into the page before it is drawn.

const THEMES = ["light", "dark", "auto"];

function showTheme(theme) {
  if (!THEMES.includes(theme)) theme = "auto";
  document.documentElement.dataset.theme = theme;
  for (const b of document.querySelectorAll("[data-theme-choice]")) b.setAttribute("aria-pressed", String(b.dataset.themeChoice === theme));
}

function wireTheme() {
  showTheme(document.documentElement.dataset.theme);
  // The legend of the state icons, drawn from icons.js so it never drifts from the views.
  $("#legend").replaceChildren(Icons.legend());
  for (const b of document.querySelectorAll("[data-theme-choice]")) {
    b.onclick = async () => {
      showTheme(b.dataset.themeChoice);
      try { await api("POST", "/api/ui", { theme: b.dataset.themeChoice }); } catch (e) { banner(e.message, true); }
    };
  }
}

// ---------------------------------------------------------------------------

function wire() {
  $("#start-open").onclick = $("#start-first-open").onclick = () => startOpen();
  $("#start-new").onclick = $("#start-first-new").onclick = () => newConfig();
  $("#start-commission").onclick = $("#start-first-commission").onclick = commissionDevice;
  $("#start-devices").onclick = $("#start-first-devices").onclick = devicesOnlyStart;
  // busy() restores the caption it found ("Save"); the button's real state follows the save.
  $("#btn-save").onclick = () => busy($("#btn-save"), "Saving…", () => save(false)).then(() => {
    const had = document.activeElement === $("#btn-save");
    updateSave();
    if (had && $("#btn-save").disabled) focusNear($("#btn-save"));
  });
  // The menu closes on a pick: its caption shows that the export runs.
  const exporting = (id, fn) => { $(id).onclick = () => busy($("#menu-export > summary"), "Exporting…", fn); };
  exporting("#btn-export-all", () => exportDcf());
  exporting("#btn-export-node", () => {
    const n = S.view.startsWith("node:") ? S.config.nodes[Number(S.view.slice(5))] : null;
    return n ? exportDcf(n.node_id, tabNetwork()) : undefined;
  });
  exporting("#btn-export-dbc", exportDbc);
  exporting("#btn-export-html", exportHtml);
  $("#btn-codesys-build").onclick = () => busy($("#btn-codesys-build"), "Building…", codesysBuild);
  $("#btn-codesys-download").onclick = () => busy($("#menu-target > summary"), "…", exportCodesys);
  $("#btn-bridge-install").onclick = () => switchWorkspace("devices");
  wireDbc();
  wireMenus();
  $("#btn-reload").onclick = () => reload(false);
  $("#btn-close").onclick = () => (S.devicesOnly && !(S.state && S.state.mode) ? devicesOnlyClose() : closeFolder());
  $("#btn-move").onclick = () => busy($("#btn-move"), "Moving…", moveIntoProject);
  $("#btn-new-project").onclick = () => busy($("#btn-new-project"), "Creating…", newEditorProject);
  $("#allow-overlap").onchange = runCheck;
  $("#eds-input").addEventListener("change", (e) => {
    const f = e.target.files[0];
    e.target.value = "";
    // A file given straight to the input (a drop): imported, then the Add node dialog with it picked.
    if (f) busy($("#eds-input").closest("label"), "Adding…", async () => {
      const res = await importEdsFile(f);
      if (!res) return;
      S.state.eds = S.state.eds || {};
      S.state.eds[res.name] = res.summary;
      S.addedReport = res;
      await addNodeDialog(res.name);
    });
  });
  wireTree();
  $("#banner-close").onclick = () => banner("");
  $("#modal").addEventListener("cancel", (e) => { if ($("#modal").dataset.working) e.preventDefault(); });
  $("#modal").addEventListener("cancel", () => { const r = modalResolve; modalResolve = null; if (r) r(null); });
  // Enter in a dialog's field picks its primary button (never a danger
  // one); a dialog closed any other way still answers, with null.
  $("#modal form").addEventListener("submit", (e) => {
    e.preventDefault();
    const primary = $("#modal-buttons").querySelector("button.primary:not(.danger)");
    if (primary) primary.click();
  });
  $("#modal").addEventListener("close", () => {
    if ($("#modal").open) return; // the close event of a dialog since opened again
    const r = modalResolve; modalResolve = null; if (r) r(null);
  });
  // A dialog opened from a menu item: the menu closed, so focus goes to its summary.
  $("#modal").addEventListener("close", () => {
    let o = $("#modal").opener;
    const menu = o && o.closest ? o.closest("details.menu") : null;
    if (menu && !menu.open) o = menu.querySelector("summary");
    const a = document.activeElement;
    const lost = !a || a === document.body || a.offsetParent === null || a.closest("dialog");
    if (lost && o && o.isConnected && o.offsetParent !== null) o.focus();
  });
  document.addEventListener("keydown", undoKeys);
  wireTheme();
  wireShell();
  wireLife();  // Quit, the heartbeat and the leave-page question (life.js)
}

// The header's Project and Export menus: native details elements, one
// open at a time, closed by Escape, a pick or a click elsewhere, the
// arrow keys moving between the items.
function wireMenus() {
  const menus = [...document.querySelectorAll("details.menu")];
  const close = (m) => { m.open = false; };
  for (const m of menus) {
    m.addEventListener("toggle", () => {
      m.querySelector("summary").setAttribute("aria-expanded", String(m.open));
      // A menu inside another (Settings under ⋯) leaves its parent open.
      if (m.open) for (const o of menus) if (o !== m && !o.contains(m)) close(o);
    });
    m.addEventListener("keydown", (e) => {
      const items = [...m.querySelectorAll(".item")].filter((b) => !b.disabled && b.offsetParent !== null);
      const k = items.indexOf(document.activeElement);
      if (e.key === "Escape") { e.preventDefault(); close(m); m.querySelector("summary").focus(); }
      else if (e.key === "ArrowDown" || (e.key === "ArrowUp" && k < 0)) { e.preventDefault(); if (!m.open) m.open = true; (items[k + 1] || items[0]).focus(); }
      else if (e.key === "ArrowUp") { e.preventDefault(); (items[k - 1] || items[items.length - 1]).focus(); }
    });
    m.addEventListener("click", (e) => { const b = e.target.closest(".item"); if (b && m.contains(b)) close(m); });
    // Tab out of an open menu closes it.
    m.addEventListener("focusout", (e) => { if (m.open && !(e.relatedTarget && m.contains(e.relatedTarget))) close(m); });
  }
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") for (const m of menus) if (m.open && !m.contains(document.activeElement)) close(m);
  });
  document.addEventListener("click", (e) => {
    for (const m of menus) if (m.open && !m.contains(e.target)) close(m);
  });
}

// The page starts in boot.js, after every script is loaded.
