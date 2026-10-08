// CANopen configurator page. Holds the draft config; every check, suggestion
// and write goes through the local server (server.py), which uses the same
// Python modules as openplc-canopen-deploy.
"use strict";

const TOKEN = document.querySelector('meta[name="canopen-token"]').content;
const BITRATES = [10000, 20000, 50000, 125000, 250000, 500000, 800000, 1000000];
const TYPES = ["BOOLEAN", "INTEGER8", "INTEGER16", "INTEGER32", "INTEGER64", "UNSIGNED8", "UNSIGNED16",
  "UNSIGNED32", "UNSIGNED64", "REAL32", "REAL64"];

const S = {
  state: null,      // last /api/state
  model: null,      // the draft: { top, networks, diagnostics } (see toModel)
  net: 0,           // the open network tab
  config: null,     // the open network of the draft (adapter, master, nodes)
  dirty: false,
  view: "bus",      // "bus" | "node:<i>" | "declarations" | "online" | "scan" | "trace" | "simulation"
  check: null,      // last /api/check
  startMode: "project",
  browserPath: null,
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
    else if (v === true) e.setAttribute(k, "");
    else e.setAttribute(k, v);
  }
  for (const c of children.flat()) {
    if (c === null || c === undefined || c === false) continue;
    e.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return e;
}

async function api(method, path, body) {
  // Requests to the runtime name the picked network; the server passes it
  // on only to a plugin that runs several.
  const net = onlineNetwork();
  if (net !== null && body && body.network === undefined && (path.startsWith("/api/online/") || path.startsWith("/api/trace/") || path.startsWith("/api/sim/"))) {
    body = Object.assign({ network: net }, body);
  }
  const res = await fetch(path, {
    method,
    headers: Object.assign({ "X-CANopen-Token": TOKEN }, body ? { "Content-Type": "application/json" } : {}),
    body: body ? JSON.stringify(body) : undefined,
  });
  let data = {};
  try { data = await res.json(); } catch (e) { /* empty body */ }
  if (method === "POST" && typeof commLogApi === "function") commLogApi(path, body, res.ok, data);
  if (!res.ok) {
    const err = new Error(data.error || res.statusText);
    err.status = res.status;
    err.body = data;
    throw err;
  }
  return data;
}

// A confirmation. buttons: [value, label, options] where options is true
// (the primary button) or { primary, danger }. The safe choice, the button
// with value "cancel", is always drawn first and gets focus, so Enter never
// removes, discards or overwrites anything; a dialog with a form focuses
// its first field instead. Escape resolves null. One cancel listener is
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
        dataset: { value }, onclick: () => done(value) }, label));
    }
    dlg.showModal();
    const field = extra && extra.querySelector ? extra.querySelector("input:not([type=checkbox]), select, textarea") : null;
    (field || menu.firstElementChild).focus();
  });
}

// A control that runs a request: disabled with a busy label until the
// request settles, so a second click meanwhile does nothing.
async function busy(button, label, fn) {
  if (!button || button.dataset.busy) return undefined;
  // Only the caption changes: a file button keeps its input.
  const node = [...button.childNodes].find((c) => c.nodeType === Node.TEXT_NODE && c.textContent.trim()) || button;
  const text = node.textContent;
  const wasDisabled = button.disabled;
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
    onclick: () => onPick(key),
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

// The message bar. text: a string, or an element (the EDS import report).
// A string closes by itself after BANNER_MS; errors and reports stay until
// closed, replaced, or the user switches view. An element with
// data-timed closes like a string. Information is a status, an error an
// alert, so assistive technology reads both.
const BANNER_MS = 6000;
function banner(text, isError) {
  const b = $("#banner");
  clearTimeout(S.bannerTimer);
  b.hidden = !text;
  if (text instanceof Node) $("#banner-text").replaceChildren(text);
  else $("#banner-text").textContent = text || "";
  b.className = isError ? "error" : "";
  b.setAttribute("role", isError ? "alert" : "status");
  const timed = typeof text === "string" ? !!text : !!(text && text.dataset && text.dataset.timed);
  if (timed && !isError) S.bannerTimer = setTimeout(() => banner(""), BANNER_MS);
}

// "Removed 0x6150:1 from TPDO 2." with an Undo action, shown for BANNER_MS.
function removedBanner(what) {
  banner(el("span", { dataset: { timed: "1", removed: "1" } }, `Removed ${what}. `,
    el("button", { type: "button", class: "link", dataset: { undo: "1" }, onclick: () => undo(false) }, "Undo")));
}

// Switches view on the user's request; a message about the last view goes.
function showView(view) {
  if (view !== S.view) banner("");
  S.view = view;
  render();
}

// The EDS lint setting the draft uses (strict_eds was migrated on load).
function edsLint() { return (S.config && S.config.master && S.config.master.eds_lint) || "communication"; }

// What the PLC's checks before dcfgen said about an imported EDS: readable,
// the corrections the PLC makes, and the accepted lint findings, collapsed
// and grouped by object.
function importReport(res) {
  const lint = res.lint || { corrections: [], accepted: [] };
  const lines = [];
  if (res.converted) lines.push(el("div", null, `${res.name} was converted to UTF-8 (the editor sends project files as UTF-8).`));
  const fixes = lint.corrections.filter((c) => c.kind !== "utf8");
  if (fixes.length) {
    lines.push(el("div", { dataset: { report: "corrections" } }, "The PLC reads it through a corrected copy: " +
      fixes.map((c) => c.text + " (" + c.count + ")" + (c.kind === "string"
        ? ": " + c.items.map((i) => `[${i.section}] ${i.key} was "${i.old}"`).join(", ") : "")).join("; ") + "."));
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
// "gateway…" the top of the draft.
function pathRoot(path) {
  const parts = path.match(/[^.[\]]+/g);
  if (parts[0] === "master" && parts[1] === "diagnostics") return [S.model, parts.slice(1)];
  if (parts[0] === "gateway") return [S.model.top, parts];
  return [S.config, parts];
}

// Writes a value at a JSON path in the draft ("" or undefined deletes it).
function setPath(path, value) {
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
  S.dirty = true;
  if (rerender) render();
  else {
    updateSimBanner();
    if (path && /^nodes\[\d+\]\.(name|node_id)$/.test(path)) renderSide();
  }
  scheduleCheck();
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
  S.dirty = JSON.stringify(S.model) !== S.savedJson;
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
    if (t === "") v = undefined;
    else if (opts.parse) v = opts.parse(t);
    else if (kind === "int") v = /^-?[0-9]+$/.test(t) ? parseInt(t, 10) : t;
    else if (kind === "intstr") v = /^[0-9]+$/.test(t) ? parseInt(t, 10) : t;
    else v = t;
    setPath(path, v);
  });
  return el("label", null, label, input, hint(opts.hint), el("span", { class: "field-msg", dataset: { for: path } }));
}

function hint(text) { return text ? el("span", { class: "hint" }, text) : null; }

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
const NETWORK_KEYS = ["name", "adapter", "master", "nodes"];

// The draft of a file as the server sent it (version 1 or 2).
function toModel(cfg) {
  cfg = JSON.parse(JSON.stringify(cfg || {}));
  const top = {};
  let networks;
  let diagnostics;
  if (cfg.schema_version === 2 && Array.isArray(cfg.networks)) {
    for (const [k, v] of Object.entries(cfg)) if (k !== "networks" && k !== "diagnostics") top[k] = v;
    networks = cfg.networks.map((n) => (n && typeof n === "object" && !Array.isArray(n) ? n : {}));
    diagnostics = cfg.diagnostics;
  } else {
    const net = {};
    for (const [k, v] of Object.entries(cfg)) {
      if (k === "adapter" || k === "master" || k === "nodes") net[k] = v;
      else top[k] = v;
    }
    if (net.master && typeof net.master === "object" && "diagnostics" in net.master) {
      diagnostics = net.master.diagnostics;
      delete net.master.diagnostics;
    }
    networks = [net];
  }
  if (!networks.length) networks.push({ adapter: { type: "socketcan", bitrate: 250000 }, master: { node_id: 1 }, nodes: [] });
  return { top, networks, diagnostics };
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

function customName(net) {
  return typeof net.name === "string" && net.name !== "" && !(net.adapter && net.name === net.adapter.interface);
}

// The draft as a file: version 1 when it holds one network without a name
// of its own, else version 2.
function fileConfig() {
  const m = S.model;
  const out = {};
  const swapSchema = (from, to) => {
    if (typeof out.$schema === "string" && out.$schema.endsWith(`canopen.v${from}.schema.json`)) {
      out.$schema = out.$schema.slice(0, -`canopen.v${from}.schema.json`.length) + `canopen.v${to}.schema.json`;
    }
  };
  const net = m.networks[0];
  if (m.networks.length === 1 && !customName(net) && Object.keys(net).every((k) => NETWORK_KEYS.includes(k))) {
    for (const [k, v] of Object.entries(m.top)) out[k] = k === "schema_version" && v === 2 ? 1 : v;
    for (const k of ["adapter", "master", "nodes"]) if (k in net) out[k] = net[k];
    if (m.diagnostics !== undefined) out.master = Object.assign({}, net.master, { diagnostics: m.diagnostics });
    swapSchema(2, 1);
    return out;
  }
  out.schema_version = 2;
  for (const [k, v] of Object.entries(m.top)) out[k] = k === "schema_version" ? 2 : v;
  out.networks = m.networks;
  if (m.diagnostics !== undefined) out.diagnostics = m.diagnostics;
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
    if (p === "diagnostics" || p.startsWith("diagnostics.")) return { net: null, path: "master." + p };
    return { net: null, path: p };
  }
  if (p.startsWith("master.diagnostics")) return { net: null, path: p };
  return { net: 0, path: p };
}

// A /api/check shaped answer with its paths in the page's terms: `where` on
// each item, and the declared map keyed by "<network index>|<path>".
function normCheck(r, version) {
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

function renderNetBar() {
  const bar = $("#net-bar");
  if (!bar || !S.model) return;
  const nets = S.model.networks;
  put(bar,
    several() ? el("div", { class: "net-tabs", role: "tablist", "aria-label": "Networks" }, nets.map((n, i) =>
      el("button", { type: "button", role: "tab", class: "net-tab" + (i === S.net ? " active" : ""),
        "aria-selected": String(i === S.net), dataset: { net: i }, title: n.adapter && n.adapter.interface ? "Interface " + n.adapter.interface : null,
        onclick: () => switchNet(i) }, netLabel(n, i), el("span", { class: "count" })))) : null,
    el("div", { class: "net-actions" },
      nets.length < MAX_NETWORKS ? el("button", { type: "button", dataset: { netAction: "add" }, onclick: addNetwork,
        title: "Another CANopen network with its own CAN interface, master and nodes" }, "Add network") : null,
      several() ? el("button", { type: "button", dataset: { netAction: "rename" }, onclick: renameNetwork }, "Rename") : null,
      several() ? el("button", { type: "button", dataset: { netAction: "remove" }, onclick: removeNetwork }, "Remove") : null));
}

// Opens a network's tab. The online and scan views follow it; a node page
// goes to the new tab's Bus and master.
function switchNet(i) {
  if (i === S.net) return;
  openNet(i);
  S.onlineNet = null;
  S.onlineNode = null;
  S.scanResult = null;
  S.lssDevice = null;
  S.supervision = {};
  if (S.view.startsWith("node:")) S.view = "bus";
  render();
}

function addNetwork() {
  const first = S.model.networks[0];
  const rate = first && first.adapter && Number.isInteger(first.adapter.bitrate) ? first.adapter.bitrate : 250000;
  // No interface: the user picks it (each network needs its own).
  S.model.networks.push({ adapter: { type: "socketcan", bitrate: rate }, master: { node_id: 1, sync_period_us: 10000 }, nodes: [] });
  openNet(S.model.networks.length - 1);
  S.onlineNet = null;
  S.view = "bus";
  banner(`Added network ${S.model.networks.length}. Enter its CAN interface (each network needs its own), then add its nodes.`);
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
  if (!name || name === iface) delete net.name;
  else net.name = name;
  changed(true);
}

async function removeNetwork() {
  const label = netLabel(S.config, S.net);
  const k = (S.config.nodes || []).length;
  const v = await modal(`Remove network ${label}` + (k ? ` and its ${k} node${k === 1 ? "" : "s"}` : "") +
    "? Its EDS files stay in the folder.", [["cancel", "Keep the network"], ["remove", "Remove network", { danger: true }]]);
  if (v !== "remove") return;
  S.model.networks.splice(S.net, 1);
  openNet(Math.min(S.net, S.model.networks.length - 1));
  S.onlineNet = null;
  S.onlineNode = null;
  S.scanResult = null;
  if (S.view.startsWith("node:")) S.view = "bus";
  banner(`Removed network ${label}.`);
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
function onlineConfig() {
  const name = onlineNetwork();
  if (name === null) return S.config;
  return S.model.networks.find((n) => netName(n) === name) || { nodes: [] };
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
  S.onlineNode = null;
  S.scanResult = null;
  S.lssDevice = null;
  render();
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
  if (S.state.mode) {
    setModel(S.state.config);
    await loadOnlineSettings();
    // A migrated file (an old setting rewritten on load) differs from the draft: there is something to save.
    S.dirty = !!(S.state.notices && S.state.notices.length);
    S.supervision = {};
    if (S.view.startsWith("node:") && !(S.config.nodes || [])[Number(S.view.slice(5))]) S.view = "bus";
    if (typeof simLoad === "function") simLoad();
    if (S.state.load_error) banner(S.state.load_error, true);
    else if (S.state.notices && S.state.notices.length) banner(S.state.notices.join(" "));
    else banner("");
  }
  render();
  if (S.state.mode) runCheck();
}

function renderStart() {
  $("#start").hidden = false;
  $("#editor").hidden = true;
  $("#actions").hidden = true;
  $("#mode").hidden = true;
  $("#sim-banner").hidden = true;
  for (const [id, mode] of [["#start-project", "project"], ["#start-standalone", "standalone"], ["#start-new", "new"]]) {
    $(id).classList.toggle("selected", S.startMode === mode);
  }
  $("#browser-title").textContent = {
    project: "Choose the editor project folder",
    standalone: "Choose the standalone config folder",
    new: "Choose where the new config goes (a new or empty folder)",
  }[S.startMode];
  const recent = $("#recent");
  recent.replaceChildren(...(S.state.recent.length ? S.state.recent.map((r) =>
    el("li", { onclick: () => openFolder(r.path, r.mode) }, r.path,
      el("span", { class: "tag" }, r.mode === "project" ? "project" : "standalone")))
    : [el("li", { class: "muted" }, "Nothing opened yet")]));
  if (!S.browserPath) browse(S.state.home);
}

async function browse(path) {
  const typed = $("#browser-path").value;
  try {
    const r = await api("GET", "/api/folders?path=" + encodeURIComponent(path));
    S.browserPath = r.path;
    // A path typed while the listing loaded (the first one, of the home
    // folder, starts with the page) stays: Open uses the field.
    if ($("#browser-path").value === typed) $("#browser-path").value = r.path;
    $("#browser-up").disabled = !r.parent;
    $("#browser-up").onclick = () => browse(r.parent);
    $("#browser-list").replaceChildren(...r.entries.map((e) => el("li", {
      ondblclick: () => browse(e.path), onclick: () => browse(e.path), title: e.path,
    }, "📁 " + e.name, e.project ? el("span", { class: "tag" }, "editor project") : null,
    e.config ? el("span", { class: "tag" }, "canopen.json") : null)));
    if (!r.entries.length) $("#browser-list").append(el("li", { class: "muted" }, "No subfolders"));
  } catch (e) {
    banner(e.message, true);
  }
}

async function openFolder(path, mode) {
  try {
    banner("");
    await api("POST", "/api/open", { path, mode });
    S.view = "bus";
    await loadState();
  } catch (e) {
    if (e.body && e.body.not_a_project) {
      const v = await modal(e.message + ".", [["standalone", "Open as standalone config", true], ["cancel", "Cancel"]]);
      if (v === "standalone") return openFolder(path, "standalone");
    } else if (e.body && e.body.is_project) {
      const v = await modal(e.message + ".", [["project", "Open as project", true], ["cancel", "Cancel"]]);
      if (v === "project") return openFolder(path, "project");
    } else {
      banner(e.message, true);
    }
  }
}

function startOpen() {
  const path = $("#browser-path").value.trim();
  if (!path) return;
  openFolder(path, S.startMode === "project" ? "project" : "standalone");
}

// ---------------------------------------------------------------------------
// Editor

function render() {
  if (!S.state || !S.state.mode) return renderStart();
  $("#start").hidden = true;
  $("#editor").hidden = false;
  $("#actions").hidden = false;
  const badge = $("#mode");
  badge.hidden = false;
  badge.textContent = S.state.commission ? "commissioning a device (nothing here is saved to a project)"
    : S.state.mode === "project" ? "project " + S.state.name : "standalone " + S.state.folder;
  badge.title = S.state.config_path;
  // Commissioning a device: no config, so nothing that edits, saves or checks one.
  const commission = !!S.state.commission;
  document.body.classList.toggle("commission", commission);
  $("#editor").classList.toggle("commission", commission);
  $("#menu-project").hidden = S.state.mode !== "standalone" || commission;
  $("#btn-export-node").disabled = !S.view.startsWith("node:");
  if (commission && !["online", "scan", "trace", "framelab"].includes(S.view)) S.view = "online";
  renderSide();
  updateSimBanner();
  // The online view, the scan page and the simulation view share one connection.
  const keep = ["online", "scan", "simulation"].includes(S.view);
  stopOnline(keep);
  stopSim(keep);
  stopMachine();
  stopTrace();
  if (S.view !== "trace" && typeof sendLeave === "function") sendLeave();
  const view = $("#view");
  view.replaceChildren();
  view.classList.toggle("indexed", S.view.startsWith("node:"));
  if (S.view === "bus") renderBus(view);
  else if (S.view === "declarations") renderDeclarations(view);
  else if (S.view === "online") renderOnline(view);
  else if (S.view === "scan") renderScan(view);
  else if (S.view === "trace") renderTrace(view);
  else if (S.view === "gateway") renderGateway(view);
  else if (S.view === "simulation") renderSimulation(view);
  else if (S.view === "machine") renderMachine(view);
  else if (S.view === "framelab") renderFrameLab(view);
  else renderNode(view, Number(S.view.slice(5)));
  applyCheck();
}

function renderSide() {
  renderNetBar();
  for (const b of document.querySelectorAll(".nav-item")) b.classList.toggle("active", b.dataset.view === S.view);
  // The node list: one button per node (name and error count, nothing
  // else), the open node marked as current.
  const list = $("#node-list");
  const item = (active, attrs, ...kids) => el("li", null, el("button", Object.assign({ type: "button",
    class: "nav-item" + (active ? " active" : ""), "aria-current": active ? "true" : null }, attrs), ...kids));
  list.replaceChildren(...(S.config.nodes || []).map((n, i) => item(S.view === "node:" + i,
    { dataset: { node: i }, onclick: () => showView("node:" + i) },
    el("span", { class: "name" }, `${n.node_id ?? "?"} ${n.name || ""}`), simBadge(n), el("span", { class: "count" }))));
  if (isSlave(S.config)) {
    const s = S.config.slave || {};
    list.append(item(S.view === "bus", { dataset: { slave: "1" }, onclick: () => showView("bus") },
      el("span", { class: "name" }, `${s.node_id === null ? "LSS" : s.node_id ?? "?"} slave device (this PLC)`)));
  } else if (!(S.config.nodes || []).length) list.append(el("li", { class: "muted" }, "No nodes yet"));
  fillCounts(countProblems());
  $("#eds-input").closest("label").hidden = isSlave(S.config);
  $("#nav-machine").hidden = !machineName();
  $("#nav-gateway").hidden = !(S.model.top.gateway || (S.model.networks.some(isSlave) && S.model.networks.some((n) => !isSlave(n))));
  const unused = S.state.unused_eds || [];
  $("#unused-eds").replaceChildren(...(unused.length ? [el("h2", { class: "side-caption" }, "Unused EDS files"),
    el("p", { class: "muted" }, unused.join(", ") + " (left in place, never deleted)")] : []));
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
    "Bus-off events since the PLC started, also those shorter than a scan. Empty: none."],
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

function simNetwork(net = S.config) { return !!(net && net.adapter && net.adapter.simulate === true); }
function nodeSimulated(n, net = S.config) { return n.simulate === undefined ? simNetwork(net) : n.simulate === true; }
function netSimulates(net) { return simNetwork(net) || (net.nodes || []).some((n) => nodeSimulated(n, net)); }
function anySimulated() { return !!S.model && S.model.networks.some(netSimulates); }
function nodeIds(list) { return list.map((n) => n.node_id ?? "?").join(", "); }
function plural(list, one, many) { return list.length === 1 ? one : many; }

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
    .map(([net, i]) => `Network ${netLabel(net, i)}: ${netSimSummary(net)}`);
  if (!parts.length) return "";
  return parts.join(" ");
}

// The banner on every page while anything is simulated.
function updateSimBanner() {
  const b = $("#sim-banner");
  if (!b) return;
  const text = S.state && S.state.mode ? simSummary() : "";
  b.hidden = !text;
  b.textContent = text ? text + " This configuration must not be uploaded to a machine as it is: its simulated devices control nothing." : "";
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
    banner("Online access is now on with Allow changes, so the Simulation view can control the simulated devices. Save and upload to use it.");
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
          help: "A virtual bus inside the plugin: no CAN interface or serial device is used and nothing needs installing. Every node is a simulated device unless switched off (then it is absent). The adapter settings below are kept for switching back." },
      ], { onChange: (v) => setNetwork(v === true) })),
    el("div", { class: "toolbar" },
      el("span", { dataset: { sim: "nodes" } }, nodes.length
        ? (sim.length ? `Simulated: ${plural(sim, "node", "nodes")} ${nodeIds(sim)}.` : "No node is simulated.") : "No nodes yet."),
      el("button", { type: "button", dataset: { sim: "all" }, disabled: !nodes.length, onclick: () => simulateAll(true) }, "Simulate all"),
      el("button", { type: "button", dataset: { sim: "none" }, disabled: !nodes.length, onclick: () => simulateAll(false) }, "Simulate none")),
    hint("A simulated device is built from the node's EDS. Its behaviour, faults and scenarios are set in the Simulation view (simulation.json)."));
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

// The node page's Simulated switch.
function simSwitch(i) {
  const n = S.config.nodes[i];
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

// SYNC source: the timer's period and the PLC cycle count exclude each other.
function switchSyncSource(source) {
  const m = S.config.master || (S.config.master = {});
  if (source === "plc_cycle") {
    m.sync_source = "plc_cycle";
    delete m.sync_period_us;
  } else {
    delete m.sync_source;
    delete m.sync_cycles;
  }
  changed(true);
}

function renderBus(view) {
  const a = "adapter";
  const slcan = getPath("adapter.type") === "slcan";
  const plcCycle = getPath("master.sync_source") === "plc_cycle";
  const slave = isSlave(S.config);
  const rateSel = el("select", { dataset: { path: "adapter.bitrate" }, "aria-label": "Bit rate" },
    BITRATES.map((r) => el("option", { value: r }, (r >= 1000000 ? r / 1000000 + " Mbit/s" : r / 1000 + " kbit/s"))));
  const rate = getPath("adapter.bitrate");
  if (rate !== undefined && !BITRATES.includes(rate)) rateSel.prepend(el("option", { value: rate }, String(rate) + " (not CiA 301)"));
  rateSel.value = rate === undefined ? "" : String(rate);
  rateSel.addEventListener("change", () => setPath("adapter.bitrate", Number(rateSel.value)));
  view.append(
    el("h2", null, (slave ? "Bus and slave device" : "Bus and master") + (several() ? `: network ${netLabel(S.config, S.net)}` : "")),
    roleField(),
    slave ? slaveNetworkSettings() : networkSettings(),
    el("fieldset", null, el("legend", null, "CAN adapter"),
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
          hint: slcan ? "Required. The name the plugin gives the interface it creates, such as can0. Nothing else may use that name (stop an old slcand service)."
            : "Required. The interface on the PLC (the Pi), not on this computer: can0 for the first CAN HAT, vcan0 for a virtual bus." }),
        el("label", null, "Bit rate", rateSel, hint("Required. Every node on the bus must use the same rate."),
          el("span", { class: "field-msg", dataset: { for: "adapter.bitrate" } })),
        slcan ? field("Serial speed (baud)", a + ".serial_baudrate", "int", { placeholder: "leave as is",
          hint: "Only for adapters behind a real serial port, such as the FTDI-based Lawicel CANUSB. A CANable ignores it." }) : null,
        slcan ? el("p", { class: "hint wide" },
          "slcan firmware does not report the CAN error state: the bus state input shows only whether the link is up, and the error counters read 0. For error state and counters, flash a CANable with candleLight firmware and use SocketCAN.") : null,
        slcan ? null : checkbox("Plugin sets up the link (bit rate, up)", a + ".configure_link", true,
          "Off: the interface must already be up at the right rate, for example from the OS network setup."),
        slcan ? null : field("Bus-off restart (ms)", a + ".restart_ms", "intstr", { placeholder: "not set",
          hint: "Empty: keep the interface's own setting. 0 turns automatic restart after bus-off off. Used only when the plugin sets up the link." })),
      el("datalist", { id: "ifaces" }, ["can0", "can1", "vcan0"].map((v) => el("option", { value: v })))),
    ...(slave ? slaveFieldsets() : [el("fieldset", null, el("legend", null, "Master"),
      el("div", { class: "grid" },
        field("Node ID", "master.node_id", "intstr", { placeholder: "1",
          hint: "Required, 1 to 127, and not used by any slave. New configs start with 1." }),
        choice("SYNC source", "master.sync_source", [
          { value: undefined, label: "Timer",
            help: "Default. The master sends SYNC at a fixed period of its own, independent of the PLC cycle." },
          { value: "plc_cycle", label: "PLC cycle",
            help: "One SYNC at the start of every PLC cycle (or every N cycles): inputs are one cycle old and outputs reach the devices after a fixed delay. The SYNC period is the PLC task interval; give every task an interval that is a multiple of the fastest one." },
        ], { onChange: switchSyncSource }),
        plcCycle ? field("Every N PLC cycles", "master.sync_cycles", "intstr", { placeholder: "1",
          hint: "1 to 1000. Empty: a SYNC every PLC cycle." }) :
        field("SYNC period (ms)", "master.sync_period_us", "int", {
          show: (us) => (typeof us === "number" ? us / 1000 : us),
          parse: (t) => (/^[0-9]+(\.[0-9]+)?$/.test(t) ? Math.round(parseFloat(t) * 1000) : t),
          placeholder: "off",
          hint: "How often the master sends SYNC; synchronous PDOs move at this rate. Empty: no SYNC, and every PDO " +
            "needs an event-driven transmission type (254 or 255). New configs start with 10 ms.",
        }),
        field("Master heartbeat (ms)", "master.heartbeat_ms", "intstr", { placeholder: "off",
          hint: "Empty: off. Set it when slaves should watch the master." }),
        choice("EDS lint (dcfgen)", "master.eds_lint", [
          { value: undefined, label: "Communication objects",
            help: "Default. The PLC stops only on lint findings in the objects 0x1000-0x1FFF that dcfgen writes, and not on findings only about limits. Other findings are logged as one warning per EDS." },
          { value: "all", label: "Every object", help: "The PLC stops on any lint finding, as dcfgen's strict check does. Many vendor EDS files fail it." },
          { value: "off", label: "Off", help: "The PLC never stops on a lint finding; findings are logged as one warning per EDS." },
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
          hint(help),
          el("span", { class: "field-msg", dataset: { for: path } }),
          declNote(path));
      })))]),
    onlineAccessSettings(),
    ...(slave ? [] : [masterAdvanced()]));
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
      checkbox("Master goes operational", m + "start", true,
        "Off: the master stays pre-operational and no PDOs move until something starts it."),
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
  if (path === "adapter.interface" && several()) renderNetBar();  // the tab shows the interface's name
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
      { value: undefined, label: "Master", help: "Default. The plugin is the network's master: it boots and configures the nodes listed here." },
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
      const v = await modal(`Make network ${netLabel(net, S.net)} a slave network? Its master settings` +
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
      const v = await modal(`Make network ${netLabel(net, S.net)} a master network again? The slave settings and ` +
        "bindings are dropped. The EDS file stays in the folder.", [["master", "Make it a master", true], ["cancel", "Cancel"]]);
      if (v !== "master") { render(); return; }
    }
    delete net.role;
    delete net.slave;
    net.master = { node_id: 1, sync_period_us: 10000 };
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
  const edsSel = el("select", { dataset: { path: base + ".eds" }, "aria-label": "Slave EDS file" },
    el("option", { value: "" }, "(none yet)"),
    Object.keys(S.state.eds || {}).map((name) => el("option", { value: name }, name)));
  edsSel.value = s.eds || "";
  edsSel.addEventListener("change", () => { setPath(base + ".eds", edsSel.value || ""); render(); });
  const edsFile = el("input", { type: "file", accept: ".eds,.EDS" });
  edsFile.addEventListener("change", () => { const f = edsFile.files[0]; edsFile.value = ""; if (f) useSlaveEdsFile(f); });
  return [
    el("fieldset", null, el("legend", null, "Slave device"),
      el("div", { class: "grid" },
        lss ? el("label", null, "Node ID", el("input", { type: "text", disabled: true, value: "assigned by LSS", "aria-label": "Node ID" }),
          hint("The node starts without an ID and waits for the master's LSS to assign one."))
          : field("Node ID", base + ".node_id", "intstr", { hint: "Required, 1 to 127: the ID the other master expects." }),
        el("div", { class: "check-field" }, el("label", { class: "check" }, lssBox, " Node ID by LSS"),
          hint("On: no node ID in the config; an LSS master assigns it at start. Default: off.")),
        el("label", null, "EDS", el("span", { class: "row" }, edsSel,
          el("button", { type: "button", dataset: { exportEds: "1" }, onclick: exportSlaveEds,
            title: "The EDS the plugin runs, for import into the other master's configuration tool" }, "Export EDS")),
          hint("The slave's object dictionary. Build one below, or use an EDS file."),
          el("span", { class: "field-msg", dataset: { for: base + ".eds" } })),
        el("label", { class: "file-button" }, "Use an EDS file… ", edsFile),
        choice("Inputs when the master is lost", base + ".inputs_on_loss", [
          { value: undefined, label: "Hold", help: "Default. Inputs keep their last value while the node is not operational or the master's heartbeat is lost." },
          { value: "zero", label: "Zero", help: "Inputs read 0 while the node is not operational or the master's heartbeat is lost." },
        ]),
        choice("EDS lint (dcfgen)", base + ".eds_lint", [
          { value: undefined, label: "Communication objects", help: "Default. The PLC stops only on lint findings in 0x1000-0x1FFF." },
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
      el("td", null, info ? info.type || "" : ""),
      el("td", null, info ? `${info.access}: ` + (dir === "input" ? "master writes, PLC input (%I)" : dir === "output" ? "PLC writes, master reads (%Q)" : "cannot be bound") : ""),
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
    el("div", { class: "objects" }, el("table", null,
      el("thead", null, el("tr", null, thCells(["Object", "EDS name", "Type", "Direction", "PLC location", "Name", ""]))),
      el("tbody", null, rows.length ? rows : el("tr", null, el("td", { colspan: 7, class: "muted" }, "No objects bound yet."))))),
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
    el("td", null, sel(o, "direction", "Direction", [["from_master", "from the master (PLC input)"], ["to_master", "to the master (PLC output)"]])),
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
      "(on Save), with the same generator as openplc-canopen-deploy slave-eds, and offers to bind every object."),
    el("div", { class: "grid" },
      el("label", null, "Device name", input(d, "device_name", "Device name"), hint("Also names the exported EDS.")),
      el("label", null, "Vendor ID", input(d, "vendor_id", "Vendor ID", "num", { placeholder: "0" })),
      el("label", null, "Product code", input(d, "product_code", "Product code", "num", { placeholder: "0" })),
      el("label", null, "Revision number", input(d, "revision_number", "Revision number", "num", { placeholder: "from the content" }),
        hint("Empty: derived from the objects, so a changed dictionary gets a new revision.")),
      el("label", null, "Heartbeat (ms)", input(d, "heartbeat_ms", "Heartbeat", "num", { placeholder: "1000" })),
      el("label", null, "Layout", layoutSel,
        hint(cia401 ? "Device type 401: digital I/O as UNSIGNED8 (0x6000/0x6200), analog as INTEGER16 (0x6401/0x6411)."
          : "From the master in 0x2000 and up, to the master in 0x2100 and up, one ARRAY per type."))),
    el("div", { class: "objects" }, el("table", null,
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
  const v = await modal(`Generated ${r.name}: ${r.objects.length} object${r.objects.length === 1 ? "" : "s"}, revision number ` +
    `${hex8(r.revision_number)}. Bind ${r.bindings.length === 1 ? "the object" : `all ${r.bindings.length} objects`} to the suggested locations` +
    ` (${r.bindings.map((b) => `${b.name} ${b.iec_location}`).join(", ")})?`,
    [["bind", "Bind all", true], ["keep", "Keep the bindings"]]);
  if (v === "bind") s.objects = r.bindings;
  banner(`Generated ${r.name}; it is written with the config on Save.`);
  changed(true);
}

async function useSlaveEdsFile(file) {
  try {
    const data = await fileBase64(file);
    let res;
    try {
      res = await api("POST", "/api/eds", { name: file.name, data, eds_lint: (S.config.slave || {}).eds_lint });
    } catch (e) {
      if (!(e.status === 409 && e.body.conflict)) throw e;
      const v = await modal(e.message + ". Replace it, or keep both under a new name?",
        [["replace", "Replace"], ["keep_both", "Keep both", true], ["cancel", "Cancel"]]);
      if (!v || v === "cancel") return;
      res = await api("POST", "/api/eds", { name: file.name, data, on_conflict: v, eds_lint: (S.config.slave || {}).eds_lint });
    }
    S.state.eds = S.state.eds || {};
    S.state.eds[res.name] = res.summary;
    S.config.slave.eds = res.name;
    banner(importReport(res));
    changed(true);
  } catch (e) {
    banner(e.message, true);
  }
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
          { value: undefined, label: "Hold", help: "Default. Routed field outputs keep their last values." },
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
    rt.slave = rt.slave || {};
    rt.field = rt.field || {};
    const objSel = el("select", { dataset: { path: path + ".slave" }, "aria-label": "Slave object" },
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
    const netSel = el("select", { dataset: { path: path + ".field.network" }, "aria-label": "Field network" },
      el("option", { value: "" }, "(pick)"), masters.map((n) => el("option", { value: netName(n) }, netName(n))));
    netSel.value = rt.field.network || "";
    netSel.addEventListener("change", () => { rt.field = { network: netSel.value }; changed(true); });
    const net = masters.find((n) => netName(n) === rt.field.network);
    const nodes = net ? net.nodes || [] : [];
    const nodeSel = el("select", { dataset: { path: path + ".field.node" }, "aria-label": "Field node" },
      el("option", { value: "" }, "(pick)"), nodes.map((n) => el("option", { value: n.node_id }, `${n.node_id} ${n.name || ""}`)));
    nodeSel.value = rt.field.node === undefined ? "" : String(rt.field.node);
    nodeSel.addEventListener("change", () => {
      rt.field = { network: rt.field.network, node: nodeSel.value === "" ? undefined : Number(nodeSel.value) };
      changed(true);
    });
    const node = nodes.find((n) => num(n.node_id) === num(rt.field.node));
    const entries = node ? fieldEntries(node) : [];
    const entrySel = el("select", { dataset: { path: path + ".field" }, "aria-label": "Field PDO entry" },
      el("option", { value: "" }, "(pick)"), entries.map((e, k) => el("option", { value: k }, e.label)));
    const ce = entries.findIndex((e) => sameObject(e.index, e.subindex, rt.field.index, rt.field.subindex));
    entrySel.value = ce >= 0 ? String(ce) : "";
    entrySel.addEventListener("change", () => {
      const e = entries[Number(entrySel.value)];
      Object.assign(rt.field, e ? { index: e.index, subindex: e.subindex } : { index: undefined, subindex: undefined });
      changed(true);
    });
    const e = ce >= 0 ? entries[ce] : null;
    return el("tr", { dataset: { route: j } },
      el("td", null, field("", path + ".name", "text", { placeholder: `route${j + 1}` }).querySelector("input")),
      el("td", null, objSel), el("td", null, netSel), el("td", null, nodeSel), el("td", null, entrySel),
      el("td", null, e ? (e.dir === "up" ? "up: node to upper master" : "down: upper master to node") : ""),
      el("td", null, el("button", { type: "button", onclick: () => { g.routes.splice(j, 1); changed(true); } }, "Remove"),
        el("span", { class: "field-msg", dataset: { for: path } })));
  });
  return el("fieldset", null, el("legend", null, "Routes"),
    el("p", { class: "muted" }, "Each route copies one value: a field TPDO entry up to a slave object the upper master reads (ro), " +
      "or a slave object the upper master writes (rww) down to a field RPDO entry, of the same type. An RPDO entry a route writes " +
      "needs no PLC location: one writer per object."),
    upperEds ? null : el("p", { class: "field-msg" }, "Build or pick the upper network's EDS to pick slave objects."),
    el("div", { class: "objects" }, el("table", null,
      el("thead", null, el("tr", null, thCells(["Name", "Slave object", "Network", "Node", "PDO entry", "Direction", ""]))),
      el("tbody", null, rows.length ? rows : el("tr", null, el("td", { colspan: 7, class: "muted" }, "No routes yet."))))),
    el("div", { class: "toolbar" }, el("button", { type: "button", dataset: { addRoute: "1" },
      onclick: () => { g.routes.push({ slave: {}, field: {} }); changed(true); } }, "Add route")));
}

function edsFor(n) { return (S.state.eds || {})[n.eds] || null; }

function objectInfo(eds, index, sub) {
  if (!eds || !eds.objects) return null;
  return eds.objects.find((o) => sameObject(o.index, o.subindex, index, sub)) || null;
}

function declaredAs(path) { return S.check && S.check.declared ? S.check.declared[`${S.net}|${path}`] : null; }

function renderNode(view, i) {
  const n = S.config.nodes[i];
  const base = `nodes[${i}]`;
  const eds = edsFor(n);
  const edsSel = el("select", { dataset: { path: base + ".eds" }, "aria-label": "EDS file" },
    Object.keys(S.state.eds || {}).map((name) => el("option", { value: name }, name)));
  edsSel.value = n.eds || "";
  edsSel.addEventListener("change", () => { setPath(base + ".eds", edsSel.value); render(); });
  const suggestBtn = (direction, key) => el("button", { type: "button", dataset: { suggest: direction },
    onclick: async () => {
      const r = await api("POST", "/api/place", { config: fileConfig(), network: S.net, node: i, direction });
      setPath(base + "." + key, r.location);
      render();
    } }, "Suggest");
  const statusBtn = suggestBtn("status", "status_location");
  const stateBtn = suggestBtn("state", "state_location");
  const bootErrBtn = suggestBtn("boot_error", "boot_error_location");
  const nodeInput = (label, direction, key, placeholder, help) =>
    el("label", null, label, el("span", { class: "row" },
      field("", base + "." + key, "text", { placeholder }).querySelector("input"), suggestBtn(direction, key)),
      hint(help),
      el("span", { class: "field-msg", dataset: { for: base + "." + key } }),
      declNote(base + "." + key));
  const exportBtn = el("button", { type: "button", dataset: { exportDcf: i }, title: "This node as a CiA 306 DCF file, checked",
    onclick: () => busy(exportBtn, "Exporting…", () => exportDcf(n.node_id, tabNetwork())) }, "Export DCF");
  const sections = [];  // [id, label, element]: the section index, in page order
  const section = (id, label, element) => { if (element) { element.id = "sec-" + id; sections.push([element.id, label]); } return element; };
  const index = el("nav", { class: "section-index", "aria-label": "Sections of this node" });
  view.append(
    el("div", { class: "toolbar" }, el("h2", null, `Node ${n.node_id ?? "?"} ${n.name || ""}`),
      el("div", { class: "spacer" }), exportBtn,
      el("button", { type: "button", dataset: { removeNode: i }, onclick: () => removeNode(i) }, "Remove node")),
    index,
    section("node", "Node", el("fieldset", null, el("legend", null, "Node"),
      el("div", { class: "grid" },
        field("Node ID", base + ".node_id", "intstr"),
        field("Name", base + ".name", "text"),
        el("label", null, "EDS", edsSel, el("span", { class: "field-msg", dataset: { for: base + ".eds" } })),
        simSwitch(i)))),
    section("supervision", "Supervision", el("fieldset", null, el("legend", null, "Supervision"),
      el("div", { class: "grid" }, supervisionFields(i),
        el("label", null, "Status bit", el("span", { class: "row" },
          field("", base + ".status_location", "text", { placeholder: "%IX…" }).querySelector("input"), statusBtn),
          hint("Optional. TRUE while the node is configured and running. Empty: no status bit."),
          el("span", { class: "field-msg", dataset: { for: base + ".status_location" } }),
          declNote(base + ".status_location")),
        el("label", null, "State byte", el("span", { class: "row" },
          field("", base + ".state_location", "text", { placeholder: "%IB…" }).querySelector("input"), stateBtn),
          hint("Optional. The node's NMT state: 5 operational, 127 pre-operational, 4 stopped, 0 no contact. Kept current by heartbeat or guarding. Empty: no state byte."),
          el("span", { class: "field-msg", dataset: { for: base + ".state_location" } }),
          declNote(base + ".state_location")),
        nodeInput("NMT command", "nmt", "nmt_command_location", "%QB…",
          "Optional output byte the program uses to command the node: 0 or 1 run (1 also starts a node with boot off), 2 keep STOPPED, 128 keep PRE-OPERATIONAL, a change to 129 resets the node and to 130 its communication (once). Empty: none."),
        el("label", null, "Boot error byte", el("span", { class: "row" },
          field("", base + ".boot_error_location", "text", { placeholder: "%IB…" }).querySelector("input"), bootErrBtn),
          hint("Optional. Why the last boot failed, as a CiA 302 letter code (66 B no answer, 77 M wrong product code, 74 J configuration refused, ...); 0 once the node boots. Empty: none."),
          el("span", { class: "field-msg", dataset: { for: base + ".boot_error_location" } }),
          declNote(base + ".boot_error_location"))))),
    section("emcy", "Emergency", el("fieldset", null, el("legend", null, "Emergency (EMCY)"),
      el("div", { class: "grid" },
        nodeInput("EMCY code", "emcy", "emcy_code_location", "%IW…",
          "Optional. Error code of the node's latest emergency message, 0 when no error is active (after its error reset or a restart). Every EMCY is also logged. Empty: not mapped."),
        nodeInput("Error register", "errreg", "error_register_location", "%IB…",
          "Optional. Error register (object 0x1001 bits) from the latest emergency message, 0 after a restart. Empty: not mapped.")))),
    section("axis", "Axis", axisFields(i, eds)),
    section("advanced", "Advanced", nodeAdvanced(i, eds)));
  if (eds && eds.error) view.append(el("p", { class: "field-msg" }, eds.error));
  for (const [key, dir, title, id] of [["tx_pdos", "input", "Inputs (TPDOs, slave to PLC)", "inputs"],
    ["rx_pdos", "output", "Outputs (RPDOs, PLC to slave)", "outputs"]]) {
    view.append(section(id, id === "inputs" ? "Inputs" : "Outputs", renderPdos(i, key, dir, title, eds)));
  }
  view.append(section("sdo", "Startup SDO writes", renderSdos(i, eds)), section("vars", "SDO variables", renderSdoVars(i, eds)));
  // The section index: an entry per section, the one in view marked as the page scrolls.
  const links = sections.map(([id, label]) => el("a", { href: "#" + id, dataset: { section: id },
    onclick: (e) => { e.preventDefault(); const t = document.getElementById(id); if (t) { t.scrollIntoView({ block: "start" }); markSection(id); } } }, label));
  index.append(...links);
  if (S.sectionObserver) S.sectionObserver.disconnect();
  if (typeof IntersectionObserver === "function") {
    const seen = new Map();
    S.sectionObserver = new IntersectionObserver((entries) => {
      for (const e of entries) seen.set(e.target.id, e.isIntersecting ? e.boundingClientRect.top : null);
      let best = null;
      for (const [id] of sections) if (seen.get(id) !== null && seen.get(id) !== undefined && (best === null || seen.get(id) < seen.get(best))) best = id;
      if (best) markSection(best);
    }, { rootMargin: `-${$("#top").offsetHeight + 40}px 0px -55% 0px`, threshold: 0 });
    for (const [id] of sections) S.sectionObserver.observe(document.getElementById(id));
  }
  // A node just added from an EDS gets its name field.
  if (S.focusName === i) { S.focusName = null; const name = view.querySelector(`input[data-path="${base}.name"]`); if (name) name.focus(); }
}

function markSection(id) {
  for (const a of document.querySelectorAll(".section-index a")) a.setAttribute("aria-current", a.dataset.section === id ? "true" : "false");
}

// A section of the node page that can be empty: collapsed when it is, with
// its count and its add action in the summary, open when it has entries
// or a problem; the user's own open or close wins for the open node.
function collapsible(key, i, label, count, body, summaryExtra) {
  const k = `node${i}.${key}`;
  const path = `nodes[${i}].${key}`;
  const problem = ((S.check && S.check.items) || []).some((it) =>
    (it.where || []).some((w) => (w.net === null || w.net === S.net) && typeof w.path === "string" && w.path.startsWith(path)));
  const open = S.sectionOpen[k] !== undefined ? S.sectionOpen[k] : count > 0 || problem;
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
  const box = el("input", { type: "checkbox", dataset: { path: base + ".axis" } });
  box.checked = on;
  box.addEventListener("change", () => { setPath(base + ".axis", box.checked ? {} : undefined); render(); });
  const fs = el("fieldset", { dataset: { axis: base } }, el("legend", null, "CiA 402 axis"),
    el("div", { class: "check-field" },
      el("label", { class: "check" }, box, " Use as a CiA 402 axis"),
      hint("The generated program declares an axis (AXIS_REF_SM3) for this node and calls the editor's CiA 402 drive bridge first in every scan, so MC_Power, MC_MoveAbsolute, MC_MoveVelocity and the other motion blocks drive it. Default: off."),
      el("span", { class: "field-msg", dataset: { for: base + ".axis" } })));
  if (!on) return fs;
  const dt = objectInfo(eds, "0x1000", 0);
  const value = dt ? num(dt.default) : NaN;
  if (eds && !eds.error && !(Number.isFinite(value) && (value & 0xFFFF) === 402))
    fs.append(el("p", { class: "field-msg warning", dataset: { axisProfile: "" } },
      "The EDS device type (0x1000) does not say device profile 402. Check that this device is a CiA 402 drive."));
  if (!n.status_location)
    fs.append(el("p", { class: "field-msg", dataset: { axisStatus: "" } },
      "An axis needs the status bit (under Supervision): the axis goes into error stop when the drive is lost."));
  fs.append(el("div", { class: "grid" },
    field("Scale numerator", base + ".axis.scale_numerator", "int", { placeholder: "1",
      hint: "Drive increments for 'denominator' units of the program (10: a move of 25 units is 250 increments). Empty: 1." }),
    field("Scale denominator", base + ".axis.scale_denominator", "intstr", { placeholder: "1",
      hint: "Program units the numerator's increments stand for. Empty: 1." }),
    field("Scale factor", base + ".axis.scale_factor", "text", { placeholder: "1.0",
      parse: (t) => (/^-?[0-9]*\.?[0-9]+(e-?[0-9]+)?$/i.test(t) ? Number(t) : t), hint: "The motion library's extra scale factor on that ratio. Empty: 1.0." })));
  fs.append(cyclicFields(base, n));
  const result = el("div", { dataset: { axisResult: "" } });
  fs.append(el("div", { class: "toolbar" },
    el("button", { type: "button", dataset: { mapCia402: base }, disabled: !eds || !!eds.error, onclick: async () => {
      const r = await api("POST", "/api/map_cia402", { config: fileConfig(), network: S.net, node: i });
      S.config.nodes[i] = r.node;
      S.axisResult = { node: i, mapped: r.mapped, missing: r.missing, changes: r.changes || [] };
      changed(true);
    } }, "Map CiA 402 objects"),
    hint(n.axis.cyclic === true
      ? "Puts the drive's objects that are not mapped yet into its PDOs for cyclic use: controlword, modes and target position in one RPDO, the other set-points in the next, statusword, modes display and actual position in one TPDO, with transmission type 1 (every SYNC)."
      : "Puts the drive's controlword, statusword, modes, positions, velocities and torques that are not mapped yet into its PDOs, with suggested locations, as the drive's own default mapping has them where it can.")),
    result);
  const last = S.axisResult && S.axisResult.node === i ? S.axisResult : null;
  if (last) {
    const lines = [];
    lines.push(el("p", { class: "muted" }, last.mapped.length
      ? "Mapped: " + last.mapped.map((m) => m.index ? `${m.index} ${m.name} (${m.pdo}, ${m.location})` : `${m.name} ${m.location}`).join("; ") + "."
      : "Nothing new to map."));
    if (last.changes && last.changes.length)
      lines.push(el("p", { class: "muted", dataset: { axisChanges: "" } }, "Transmission type 1 (every SYNC) for the cyclic axis: " +
        last.changes.map((c) => `${c.pdo} (was ${c.was === null || c.was === undefined ? "not set" : c.was})`).join(", ") + "."));
    if (last.missing.length)
      lines.push(el("ul", { class: "field-msg warning" }, ...last.missing.map((m) => el("li", null, `${m.index} ${m.name}: ${m.reason}`))));
    result.append(...lines);
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
      hint("The program sends a set-point every cycle (CSP, CSV, CST) with the CO402_Cyclic* blocks of the openplc_canopen library; the drive interpolates between them. Needs SYNC from the PLC cycle and synchronous PDOs. Default: off."),
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

function nodeAdvanced(i, eds) {
  const base = `nodes[${i}]`;
  const n = S.config.nodes[i];
  const keys = ["mandatory", "boot", "reset_communication", "revision_number", "serial_number", "lss", "heartbeat_consumer",
    "retry_factor", "time_cob_id", "error_behavior", "restore_configuration", "config_check", "store_configuration",
    "software_file", "software_version"];
  const dflt = (index, sub, fmt) => {
    const v = edsDefault(eds, index, sub);
    return v === null ? "EDS default" : `EDS default (${fmt ? fmt(v) : v})`;
  };
  const hex8 = (v) => "0x" + v.toString(16).toUpperCase().padStart(8, "0");
  const ltf = num(n.life_time_factor);
  return advanced("node" + i, "Advanced node settings", base, keys,
    el("p", { class: "muted" }, "dcfgen's node options. Empty node-side fields write nothing, so the node keeps its EDS values."),
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
      choice("Watches the master heartbeat", base + ".heartbeat_consumer", [
        { value: undefined, label: "EDS default", help: "Nothing is written: the node keeps its 0x1016 entries from the EDS." },
        { value: true, label: "On", help: "The node watches the master's heartbeat (needs a master heartbeat)." },
        { value: false, label: "Off", help: "The node's entry for the master is cleared." },
      ]),
      field("TIME COB-ID", base + ".time_cob_id", "intstr", { placeholder: dflt(0x1012, 0, hex8),
        hint: "0x1012. Bit 31 (0x80000000) set makes the node consume TIME." }),
      field("Restore configuration", base + ".restore_configuration", "intstr", { placeholder: "none",
        hint: "Sub-index of 0x1011 the master restores before configuring (1 all, 2 communication, 3 application). Empty: none." }),
      errorBehaviorField("Error behavior", base + ".error_behavior",
        "0x1029 as sub=value pairs, e.g. 1=0 (0 pre-operational, 1 no change, 2 stopped). Empty: EDS default.")),
    el("h3", null, "Configuration check"),
    el("div", { class: "grid" }, configCheckField(i, eds), storeConfigurationField(i, eds)),
    el("h3", null, "Program download"),
    el("div", { class: "grid" },
      field("Program file", base + ".software_file", "text", { placeholder: "none",
        hint: "The node's program (firmware), relative to canopen/. The master downloads it when the node reports another version." }),
      field("Program version", base + ".software_version", "intstr", { placeholder: "none",
        hint: "Expected 0x1F56 sub 1. Needs a program file." })));
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
  store.disabled = !assign.checked && !store.checked;
  store.addEventListener("change", () => set("store", store.checked));
  const dev = eds && eds.device;
  const warn = dev && !dev.lss_supported
    ? el("p", { class: "field-msg warning", dataset: { lssWarning: "" } },
      "The EDS does not say LSS_Supported=1; LSS assignment may not work with this device. Check its manual.")
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
  input.disabled = !!why && !on;
  input.addEventListener("change", () => {
    if (!input.checked) setPath(base + ".store_configuration", undefined);
    setPath(base + ".config_check", input.checked ? true : undefined);
    render();
  });
  return el("div", { class: "check-field" },
    el("label", { class: "check" }, input, " Skip download when unchanged (0x1020)"),
    hint(why || "After a download the master writes a stamp of this node's configuration to 0x1020, and at later boots " +
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
  if (why && !set) {
    f.querySelector("select").disabled = true;
    f.querySelector(".hint").textContent = why;
  }
  return f;
}

const SUPERVISION = [
  { value: "none", label: "EDS default", help: "Nothing is written to the slave: it keeps the heartbeat its EDS gives (object 0x1017), and the master watches that heartbeat when it is not 0. With 0 a node that drops off the bus is not noticed; pick Heartbeat and set 0 to switch a default heartbeat off." },
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
  return out;
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
  pdos.forEach((p, j) => {
    const pb = `nodes[${i}].${key}[${j}]`;
    const bits = (p.entries || []).reduce((s, e) => s + (S.state.type_bits[e.type] || 0), 0);
    const number = num(p.number) || j + 1;
    const box = el("div", { class: "pdo", dataset: { path: pb } },
      el("div", { class: "pdo-title" },
        el("strong", null, `${dir === "input" ? "TPDO" : "RPDO"} ${p.number ?? j + 1}`),
        el("span", { class: "muted" }, `${(p.entries || []).length}/8 entries, ${bits}/64 bits`),
        el("span", { class: "field-msg", dataset: { for: pb } }),
        eds && eds.objects ? el("button", { type: "button", class: "small", dataset: { addEntry: pb },
          title: `Pick an object for ${dir === "input" ? "TPDO" : "RPDO"} ${number}`,
          onclick: () => { S.pickerTarget = { dir, number }; S.pickerOpen[dir] = true; render(); focusPicker(dir); } }, "Add entry…") : null),
      el("div", { class: "pdo-grid" },
        pdoField("Number", pb + ".number", String(j + 1)),
        cobIdField(pb, n, dir, p, j),
        transmissionField(pb, dir, p, eds)),
      timingLine(pb, dir, p, eds),
      dir === "input" ? timeoutLine(i, pb, p, eds) : null,
      mappingLine(i, key, dir, p, j, eds));
    const rows = (p.entries || []).map((e, k) => {
      const ep = `${pb}.entries[${k}]`;
      const info = objectInfo(eds, e.index, e.subindex);
      const loc = el("input", { type: "text", spellcheck: "false", dataset: { path: ep + ".iec_location" },
        "aria-label": "Location of " + (info ? info.name : e.index) });
      loc.value = e.iec_location || "";
      loc.addEventListener("input", () => setPath(ep + ".iec_location", loc.value.trim()));
      const move = el("select", { "aria-label": "Move to PDO" },
        pdos.map((_, x) => el("option", { value: x }, `PDO ${pdos[x].number ?? x + 1}`)),
        pdos.length < count ? el("option", { value: "new" }, "new PDO") : null);
      move.value = String(j);
      move.addEventListener("change", () => moveEntry(i, key, j, k, move.value));
      return el("tr", { dataset: { path: ep } },
        el("td", null, `${e.index}:${e.subindex ?? 0}`), el("td", null, info ? info.name : "?"), el("td", null, e.type),
        el("td", null, loc, el("span", { class: "field-msg", dataset: { for: ep + ".iec_location" } }),
          el("span", { class: "field-msg", dataset: { for: ep } }), el("span", { class: "field-msg", dataset: { for: ep + ".type" } }),
          declNote(ep + ".iec_location")),
        el("td", null, move),
        el("td", null, el("button", { type: "button", title: "Remove", "aria-label": `Remove ${e.index}:${e.subindex ?? 0} from the PDO`,
          onclick: () => removeEntry(i, key, j, k) }, "✕")));
    });
    box.append(el("table", null, el("thead", null, el("tr", null, thCells(["Object", "Name", "Type", "PLC location", "PDO", ""]))),
      el("tbody", null, rows)));
    fs.append(box);
  });
  fs.append(objectPicker(i, eds, dir));
  return fs;
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
  return el("label", null, label, input, hint(help || (dflt ? "Empty: " + dflt : null)));
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
      setPath(pb + ".on_timeout", undefined);
      setPath(pb + ".timeout_location", undefined);
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
  const d = el("details", { class: "picker", open: S.pickerOpen[dir] || null, dataset: { picker: dir } },
    el("summary", null, "Add entry…"));
  d.addEventListener("toggle", () => { S.pickerOpen[dir] = d.open; if (!d.open) S.pickerTarget = null; });
  const filter = el("input", { type: "text", placeholder: "Filter by index or name", "aria-label": `Filter ${dir} objects` });
  filter.value = S.objectFilter;
  const body = el("tbody");
  const fill = () => {
    const f = S.objectFilter.toLowerCase();
    body.replaceChildren(...objects
      .filter((o) => !f || o.index.toLowerCase().includes(f) || (o.name || "").toLowerCase().includes(f))
      .map((o) => el("tr", null, el("td", null, `${o.index}:${o.subindex}`), el("td", null, o.name), el("td", null, o.type),
        el("td", null, o.access),
        el("td", null, isMapped(i, o) ? el("span", { class: "muted" }, "mapped") :
          el("button", { type: "button", dataset: { add: `${o.index}:${o.subindex}` }, "aria-label": `Add ${o.index}:${o.subindex} ${o.name || ""}`,
            onclick: (e) => busy(e.currentTarget, "Adding…", () => addEntry(i, o, dir, target)) }, "Add")))));
  };
  filter.addEventListener("input", () => { S.objectFilter = filter.value; fill(); });
  fill();
  d.append(el("div", null,
    el("div", { class: "toolbar" }, filter,
      el("span", { class: "muted", dataset: { pickerTarget: dir } }, target !== null
        ? `Adding to ${label} ${target}. ` : `${objects.length} ${dir}-direction object${objects.length === 1 ? "" : "s"} the EDS lets a ${label} carry. `),
      target !== null ? el("button", { type: "button", class: "small", onclick: () => { S.pickerTarget = null; render(); } }, "Any PDO") : null),
    el("div", { class: "objects" }, el("table", null,
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
  const fs = el("fieldset", { dataset: { path: `nodes[${i}].sdo` } }, el("legend", null, "Startup SDO writes"),
    el("p", { class: "muted" }, "Written in this order every time the node is configured at boot, after the PDO parameters. Only objects the EDS marks writable can be added."));
  const rows = list.map((s, j) => {
    const sp = `nodes[${i}].sdo[${j}]`;
    const info = objectInfo(eds, s.index, s.subindex);
    const value = el("input", { type: "text", dataset: { path: sp + ".value" }, "aria-label": "Value",
      placeholder: info && info.default ? info.default : null });
    value.value = s.value === undefined ? "" : String(s.value);
    value.addEventListener("input", () => {
      const t = value.value.trim();
      let v = t;
      if (/^-?[0-9]+$/.test(t)) v = parseInt(t, 10);
      else if (/^-?[0-9]*\.[0-9]+$/.test(t)) v = parseFloat(t);
      else if (t === "true" || t === "false") v = t === "true";
      setPath(sp + ".value", t === "" ? undefined : v);
    });
    const typeCell = info && info.type ? s.type : (() => {
      const sel = el("select", { dataset: { path: sp + ".type" }, "aria-label": "Type" }, TYPES.map((t) => el("option", { value: t }, t)));
      sel.value = s.type || "";
      sel.addEventListener("change", () => setPath(sp + ".type", sel.value));
      return sel;
    })();
    return el("tr", { dataset: { path: sp } },
      el("td", null, `${s.index}:${s.subindex ?? 0}`),
      el("td", null, info ? info.name : el("span", { class: "field-msg warning" }, "not in the EDS")),
      el("td", null, typeCell),
      el("td", null, value, el("span", { class: "field-msg", dataset: { for: sp + ".value" } }),
        el("span", { class: "field-msg", dataset: { for: sp } }), el("span", { class: "field-msg", dataset: { for: sp + ".type" } }),
        info && info.default ? el("span", { class: "muted" }, " EDS default " + info.default) : null),
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
  const filter = el("input", { type: "text", placeholder: "Filter writable objects", "aria-label": "Filter SDO objects" });
  filter.value = S.sdoFilter;
  const body = el("tbody");
  const hidden = el("span", { class: "muted" });
  const all = el("input", { type: "checkbox", "aria-label": "Show all writable objects" });
  all.checked = S.sdoShowAll;
  all.addEventListener("change", () => { S.sdoShowAll = all.checked; fill(); });
  const fill = () => {
    const f = S.sdoFilter.toLowerCase();
    const writable = ((eds && eds.objects) || []).filter((o) => o.writable && o.type);
    const why = { signal: 0, plugin: 0, listed: 0 };
    const shown = S.sdoShowAll ? writable : writable.filter((o) => {
      const r = sdoHiddenReason(list, o);
      if (r) why[r]++;
      return !r;
    });
    const parts = [];
    if (why.signal) parts.push(`${why.signal} process signal${why.signal === 1 ? "" : "s"} (PDO-mappable, map them in a PDO)`);
    if (why.plugin) parts.push(`${why.plugin} communication object${why.plugin === 1 ? "" : "s"} the plugin sets from the node's settings`);
    if (why.listed) parts.push(`${why.listed} already in the list`);
    hidden.textContent = parts.length ? "Hidden: " + parts.join(", ") + "." : "";
    body.replaceChildren(...shown
      .filter((o) => !f || o.index.toLowerCase().includes(f) || (o.name || "").toLowerCase().includes(f))
      .slice(0, 400)
      .map((o) => el("tr", null, el("td", null, `${o.index}:${o.subindex}`), el("td", null, o.name),
        el("td", null, o.type || "?"), el("td", null, o.access), el("td", null, o.default),
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
  el("div", { class: "objects" }, el("table", null,
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
  const fs = el("fieldset", { dataset: { path: `nodes[${i}].sdo_variables` } }, el("legend", null, "SDO variables"),
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
  const filter = el("input", { type: "text", placeholder: "Filter objects", "aria-label": "Filter SDO variable objects" });
  filter.value = S.varFilter;
  const body = el("tbody");
  const fill = () => {
    const f = S.varFilter.toLowerCase();
    const write = S.varDirection === "write";
    body.replaceChildren(...((eds && eds.objects) || [])
      .filter((o) => o.type && (write ? o.writable : o.readable))
      .filter((o) => !f || o.index.toLowerCase().includes(f) || (o.name || "").toLowerCase().includes(f))
      .slice(0, 400)
      .map((o) => el("tr", null, el("td", null, `${o.index}:${o.subindex}`), el("td", null, o.name),
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
  el("div", { class: "objects" }, el("table", null,
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
  } else if (pluginObject(index)) {
    out.push(`The plugin configures ${hex4(index)} itself when the node boots; your value lasts until the next boot.`);
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
  input.value = S.taskInterval || "";
  input.addEventListener("change", () => { S.taskInterval = input.value.trim(); scheduleCheck(); });
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
    el("p", { class: "muted" }, "Paste this block into the editor's variables, in the global list or in a program. You can also type the rows below into a variables table. Entries the project already declares at the same location are left out."),
    el("div", { class: "toolbar" }, el("button", { type: "button", class: "primary", id: "copy-block", onclick: async () => {
      try { await navigator.clipboard.writeText(block); banner("Copied the declarations block."); }
      catch (e) { ta.select(); document.execCommand("copy"); banner("Copied the declarations block."); }
    } }, "Copy block")),
    cyclicInterval() || "",
    ta,
    el("table", null, el("thead", null, el("tr", null, thCells(["Name", "Location", "Type", "In the project"]))),
      el("tbody", null, decls.map((d) => el("tr", null, el("td", null, d.name), el("td", null, d.location), el("td", null, d.type),
        el("td", null, d.declared_as ? "declared as " + d.declared_as : "not yet"))))));
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
// canopen-configurator, Copy as ST call; the blocks are the openplc_canopen
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
  banner(`Copied the ${stBlock(type, write)} call. Enable the openplc_canopen library in the editor project to use it.`);
}
const NO_ST_SLAVE = "The program's SDO blocks address nodes of a master network; on a slave network the program has the bound locations instead.";
const RUNTIME_NO_CHANGES = "Online changes are not allowed in this configuration (turn on \"Allow changes\" under Online access, then upload).";
const ADAPTER_NO_CHANGES = "Changes are off for this USB adapter connection (tick \"Allow changes\" in the connection banner).";
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

async function saveHost(host) {
  try {
    S.online = Object.assign(S.online, await api("POST", "/api/online/settings", { host }));
    banner("");
    return true;
  } catch (e) { banner(e.message, true); return false; }
}

function hostField() {
  const input = el("input", { type: "text", spellcheck: "false", placeholder: "for example plc.local", "aria-label": "Runtime host",
    dataset: { online: "host" } });
  input.value = S.online.host || "";
  input.addEventListener("change", () => saveHost(input.value.trim()));
  const local = el("button", { type: "button", class: "small", dataset: { online: "local" },
    title: "The local simulator runtime started with openplc-canopen-sim-runtime start" }, "Local simulator runtime");
  local.addEventListener("click", () => { input.value = "local"; saveHost("local"); });
  return el("label", null, "Runtime host", input, local,
    hint(`The PLC running this config, as HOST or HOST:PORT (port ${diagPort()} when not given), or "local" for the local simulator runtime (openplc-canopen-sim-runtime). Kept on this PC, not in the project.`));
}

function onlineAccessSettings() {
  const d = diagConfig();
  const on = el("input", { type: "checkbox", dataset: { online: "enable" } });
  on.checked = !!d;
  on.addEventListener("change", () => enableOnline(on.checked));
  const fs = el("fieldset", { dataset: { section: "online" } }, el("legend", null, several() ? "Online access (all networks)" : "Online access"),
    el("p", { class: "muted" }, "Lets this configurator (and openplc-canopen-diag) watch the live network from this PC: node states, boot errors, emergencies, SDO values, and a scan of the bus. Off by default; the plugin opens no port without it."),
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
  el("div", { class: "toolbar" },
    el("span", { class: S.online.tokenOk && !old ? "ok-text" : "field-msg warning", dataset: { online: "token-state" } }, tokenState),
    old && S.online.tokenOk ? el("button", { type: "button", class: "primary", dataset: { online: "upgrade" }, onclick: upgradeToken }, "Upgrade") : null,
    S.online.token ? el("button", { type: "button", onclick: copyToken }, "Copy token") : null,
    el("button", { type: "button", onclick: enterToken }, "Enter token…"),
    el("button", { type: "button", onclick: newToken }, "New token")),
  el("p", { class: "muted" }, "Open the online view from the side bar once the config with online access is saved and uploaded to the runtime."));
  return fs;
}

// ---------------------------------------------------------------------------
// Online view

// Stops polling; closes the runtime connection too unless the next view
// uses it.
function stopOnline(keepConnection) {
  clearTimeout(S.onlineTimer);
  S.onlineTimer = null;
  S.onlineSeq = (S.onlineSeq || 0) + 1;
  if (S.onlineOpen && !keepConnection) api("POST", "/api/online/close", {}).catch(() => {});
  if (!keepConnection) S.onlineOpen = false;
}

// The online target in words, for the connection line.
function targetLabel() {
  return S.online.target === "adapter" ? `USB adapter ${S.online.adapter}` : S.online.host;
}

async function saveOnline(values) {
  try {
    S.online = Object.assign(S.online, await api("POST", "/api/online/settings", values));
    banner("");
    return true;
  } catch (e) { banner(e.message, true); return false; }
}

// Runtime or USB adapter: the choice above the connect form.
function targetChoice() {
  const box = el("div", { class: "toolbar", role: "radiogroup", "aria-label": "Connect to" });
  for (const [value, label] of [["runtime", "Runtime"], ["adapter", "USB adapter on this PC"]]) {
    const r = el("input", { type: "radio", name: "online-target", value, dataset: { online: "target-" + value } });
    r.checked = (S.online.target || "runtime") === value;
    r.addEventListener("change", async () => { if (await saveOnline({ target: value })) { S.onlineForm = true; render(); } });
    box.append(el("label", { class: "check" }, r, " " + label));
  }
  return box;
}

// The USB adapter form: adapter (found ones, or typed), bit rate, allow changes.
function adapterForm(view) {
  const list = el("select", { "aria-label": "Found adapters", dataset: { online: "adapter-list" } },
    el("option", { value: "" }, "Looking for adapters…"));
  const input = el("input", { type: "text", spellcheck: "false", placeholder: "slcan:COM5, slcan:/dev/tty.usbmodem14101, socketcan:can0",
    "aria-label": "Adapter", dataset: { online: "adapter" } });
  input.value = S.online.adapter || "";
  list.addEventListener("change", () => { if (list.value) input.value = list.value; });
  const fill = async () => {
    try {
      const r = await api("GET", "/api/online/adapters");
      list.replaceChildren(el("option", { value: "" }, r.adapters.length ? "Pick a found adapter…" : "No adapter found"),
        ...r.adapters.map((a) => el("option", { value: a.text }, `${a.text}  ${a.known || a.description || ""}`)));
    } catch (e) { list.replaceChildren(el("option", { value: "" }, "Could not list adapters")); }
  };
  const refresh = el("button", { type: "button", class: "small", onclick: fill }, "Refresh");
  fill();
  // Commissioning has no network of its own (its placeholder config's rate
  // is nobody's), and a guessed rate disturbs the bus: the user picks one.
  const cfgKbit = !S.state.commission && num(getPath("adapter.bitrate")) ? num(getPath("adapter.bitrate")) / 1000 : null;
  const rate = el("select", { "aria-label": "Bit rate", dataset: { online: "adapter-bitrate" } },
    el("option", { value: "" }, "Pick the bus's bit rate…"),
    LSS_BITRATES.map((b) => el("option", { value: b }, `${b} kbit/s${b === cfgKbit ? " (this network)" : ""}`)));
  rate.value = String(S.online.adapter_bitrate || cfgKbit || "");
  const allow = el("input", { type: "checkbox", dataset: { online: "adapter-allow" } });
  const msg = el("p", { class: "field-msg", dataset: { online: "connect-msg" } });
  const detectMsg = el("p", { class: "muted", dataset: { online: "adapter-detect-msg" } });
  const lone = loneBox();
  const detect = el("button", { type: "button", class: "small", dataset: { online: "adapter-detect" },
    title: "Listen at each bit rate without sending anything, and pick the one with traffic",
    onclick: async () => {
      const alone = lone.querySelector("input").checked;
      if (alone && !(await askLone())) return;
      adapterDetect(input, rate, detect, detectMsg, false, alone);
    } }, "Detect");
  view.append(el("fieldset", null, el("legend", null, "Connect"), targetChoice(),
    el("p", { class: "muted" }, "The PC talks to the bus itself through the adapter: no runtime is needed. It sends nothing until you act, never SYNC, heartbeat or NMT to all nodes, and warns when another master runs on the bus."),
    el("div", { class: "grid" },
      el("label", null, "Adapter", el("div", { class: "row" }, list, refresh), input,
        hint("TYPE:CHANNEL. slcan (for example a CANable) on Windows, macOS and Linux, socketcan on Linux; other python-can types are passed through untested. Kept on this PC.")),
      el("label", null, "Bit rate", el("div", { class: "row" }, rate, detect), lone, detectMsg,
        hint("The bus's bit rate. A wrong one disturbs the bus, so check it first: Detect listens at each rate in listen-only mode and sends nothing.")),
      el("div", { class: "check-field" }, el("label", { class: "check" }, allow, " Allow changes (SDO writes, NMT, LSS, restore)"),
        hint("Off by default and for every new connection: read-only."))),
    msg,
    el("div", { class: "toolbar" }, el("button", { type: "button", class: "primary", dataset: { online: "connect" }, onclick: async () => {
      if (!input.value.trim()) { msg.textContent = "Pick or type the adapter first."; input.focus(); return; }
      if (!rate.value) { msg.textContent = "Pick the bus's bit rate first, or press Detect."; rate.focus(); return; }
      if (!(await saveOnline({ adapter: input.value.trim(), adapter_bitrate: Number(rate.value) }))) return;
      if (allow.checked && !(await saveOnline({ allow_changes: true }))) return;
      S.onlineForm = false;
      render();
    } }, "Connect"))));
}

// "Detect" in the USB adapter form: a bit rate sweep on the picked adapter
// (listen-only, nothing sent); on "detected" it picks that rate.
// An adapter that does not confirm listen-only (slcan firmware that answers
// nothing to its silent mode command) is only swept after this question.
const DISTURB_TEXT = "The adapter did not confirm that it only listens: at a wrong bit rate it may send error frames that disturb the devices on the bus, which can make them error passive or bus-off for a moment.";
async function askDisturb() {
  return await modal(`${DISTURB_TEXT} Sweep anyway?`, [["go", "Sweep anyway", true], ["cancel", "Cancel"]]) === "go";
}
function needsDisturb(text) { return /disturb_bus needed\s*$/.test(text || ""); }

async function adapterDetect(input, rate, button, msg, disturb, alone) {
  if (!input.value.trim()) { msg.textContent = "Pick or type the adapter first."; input.focus(); return; }
  button.disabled = true;
  const show = (r) => {
    if (r.running) {
      msg.textContent = r.lone_device ? `Trying ${kbitText(r.rate_kbit || 0)} (${r.done} of ${r.total}) in normal mode…`
        : `Listening at ${kbitText(r.rate_kbit || 0)} (${r.done} of ${r.total})… nothing is sent.`;
      return false;
    }
    if (r.verdict === "detected") {
      rate.value = String(r.bitrate_kbit);
      msg.textContent = `${kbitText(r.bitrate_kbit)} detected and picked.` + (r.warning ? ` ${upperFirst(r.warning)}.` : "");
    } else if (r.verdict === "ambiguous") {
      msg.textContent = `Ambiguous: frames at ${(r.candidates || []).map(kbitText).join(", ")}. Detect again, or pick the bit rate yourself.`;
    } else if (r.verdict === "silent") {
      msg.textContent = r.lone_device ? "No answer at any bit rate: check the wiring, the termination and the device's power." : SILENT_TEXT;
    } else {
      msg.textContent = `The sweep failed: ${r.error || "no reason given"}.`;
    }
    msg.textContent += skippedText(r);
    return true;
  };
  try {
    let r = await api("POST", "/api/online/adapter_detect", Object.assign({ adapter: input.value.trim(), adapter_bitrate: Number(rate.value) },
      disturb ? { disturb_bus: true } : {}, alone ? { lone_device: true } : {}));
    while (!show(r)) {
      await new Promise((ok) => setTimeout(ok, 300));
      if (!button.isConnected) return;  // the form went away
      r = await api("POST", "/api/online/adapter_detect_status", {});
    }
  } catch (e) {
    if (e.body && e.body.disturb_bus && !disturb) {
      msg.textContent = "";
      button.disabled = false;
      if (await askDisturb()) return adapterDetect(input, rate, button, msg, true, alone);
      msg.textContent = `Not started: ${DISTURB_TEXT}`;
      return;
    }
    msg.textContent = `Not started: ${e.message}`;
  } finally {
    button.disabled = false;
  }
}

// What the online view and the scan page need before they can connect, or null.
function onlineSetup(view) {
  if (S.online.target === "adapter") {
    if (S.onlineForm || !S.online.adapter) { adapterForm(view); return false; }
    return true;
  }
  if (!diagConfig()) {
    view.append(el("fieldset", null, el("legend", null, "Connect"), targetChoice()));
    view.append(el("p", null, "Online access is off for this config. Turn it on under ",
      el("a", { href: "#", onclick: (e) => { e.preventDefault(); showView("bus"); } }, "Bus and master"),
      ", save, and upload the program to the runtime."));
    return false;
  }
  if (!S.online.host || !S.online.token || !S.online.tokenOk) {
    const host = hostField();
    const msg = el("p", { class: "field-msg", dataset: { online: "connect-msg" } },
      S.online.token && !S.online.tokenOk ? "The token on this PC does not match the config." : "");
    view.append(el("fieldset", null, el("legend", null, "Connect"), targetChoice(),
      el("div", { class: "grid" }, host),
      msg,
      el("div", { class: "toolbar" },
        !S.online.tokenOk ? el("button", { type: "button", onclick: enterToken }, "Enter token…") : null,
        el("button", { type: "button", class: "primary", dataset: { online: "connect" }, onclick: async () => {
          // Say what is missing instead of drawing the same form again.
          const value = host.querySelector("input").value.trim();
          if (!value) {
            msg.textContent = "Enter the runtime's host name or address first, for example plc.local.";
            host.querySelector("input").focus();
            return;
          }
          if (!(await saveHost(value))) {
            msg.textContent = "The host was not saved; see the message at the top.";
            return;
          }
          msg.textContent = "";
          if (!S.online.tokenOk && !(await enterToken())) {
            msg.textContent = S.online.token
              ? "The token on this PC does not match the config. Enter the token of this project to connect."
              : "Enter the access token of this project to connect (Copy token on the PC that turned online access on).";
            return;
          }
          render();
        } }, "Connect"))));
    return false;
  }
  return true;
}

function renderOnline(view) {
  view.append(el("h2", null, "Online"), stepsPanel() || "");
  if (!onlineSetup(view)) return;
  view.append(
    el("div", { class: "toolbar" }, netPicker(),
      el("button", { type: "button", class: "small", dataset: { online: "change-target" },
        onclick: () => { S.onlineForm = true; render(); } }, "Connection…")),
    el("div", { id: "online-conn", class: "online-conn" }, "Connecting to " + targetLabel() + "…"),
    el("div", { id: "online-live" }),
    el("div", { id: "online-lss" }),
    el("div", { id: "online-node" }));
  S.lssAllow = undefined;
  S.onlineOpen = true;
  pollOnline(S.onlineSeq);
  if (S.onlineNode) renderOnlineNode();
}

async function pollOnline(seq) {
  let r = null;
  let err = null;
  try {
    r = await api("POST", "/api/online/status", { port: diagPort() });
  } catch (e) { err = e; }
  if (seq !== S.onlineSeq || S.view !== "online") return;
  const conn = $("#online-conn");
  conn.setAttribute("aria-live", "polite");
  const live = $("#online-live");
  if (err) {
    const why = { closed: "port closed", unreachable: "host unreachable", token: "wrong token", timeout: "no answer",
      protocol: "not a CANopen diagnostics port", refused: "refused" }[err.body && err.body.kind] || "error";
    conn.className = "online-conn error";
    // Values from before the failure stay, greyed, with their age.
    const age = S.onlineLastAt ? Math.max(0, Math.round((Date.now() - S.onlineLastAt) / 1000)) : null;
    const text = `Not connected (${why}): ${err.message}. Retrying…`;
    delete conn.dataset.html;  // the next good poll rewrites the line
    put(conn, text, age !== null && live.childElementCount ? el("div", { class: "online-note", dataset: { online: "stale-age" } }, `Last data ${age} s ago; the values below are not live.`) : null);
    live.classList.toggle("stale", !!live.childElementCount);
    clearTimeout(S.onlineAgeTimer);
    if (age !== null) S.onlineAgeTimer = setTimeout(() => { if (seq === S.onlineSeq && S.view === "online") { const a = document.querySelector("[data-online=stale-age]"); if (a) a.textContent = `Last data ${age + 1} s ago; the values below are not live.`; } }, 1000);
    S.onlineTimer = setTimeout(() => pollOnline(seq), 2000);
    return;
  }
  S.onlineLast = r;
  S.onlineLastAt = Date.now();
  clearTimeout(S.onlineAgeTimer);
  live.classList.remove("stale");
  runtimeNetworks(r);
  const st = r.status;
  NO_CHANGES = st.local ? ADAPTER_NO_CHANGES : RUNTIME_NO_CHANGES;
  if (st.local) {
    localLive(r, conn);
    if (S.onlineNode !== undefined && S.onlineNode !== null && S.onlineNodeAllow !== r.hello.allow_changes) renderOnlineNode();
    if (S.lssAllow !== r.hello.allow_changes) renderLss(r.hello.allow_changes);
    S.onlineTimer = setTimeout(() => pollOnline(seq), 500);
    return;
  }
  const notes = [];
  const bus = st.bus || {};
  if (!st.session) notes.push(el("div", { class: "online-note error" }, `No CANopen session: the CAN interface ${bus.interface || "of this network"} is missing or down on the runtime.`));
  if (r.config === "different") notes.push(el("div", { class: "online-note warning", dataset: { online: "fingerprint" } },
    "The runtime runs a different configuration than the saved canopen.json (saved changes not uploaded yet, or another project). " +
    "Upload the saved config with the deploy tool (openplc-canopen deploy) or the editor's Build and upload with the CANopen hook."));
  if (S.dirty) notes.push(el("div", { class: "online-note" }, "This page has unsaved changes; the runtime runs what was uploaded."));
  if (st.simulation_forced) notes.push(el("div", { class: "online-note warning", dataset: { online: "forced" } },
    "This runtime simulates every network (the local simulator runtime): no CAN interface is used, whatever the adapter settings say."));
  conn.className = "online-conn ok";
  // The connection line is a live region: it is rewritten only when it changes.
  const line = el("div", null, `Connected to ${S.online.host}${r.network ? ", network " + r.network : ""}: plugin ${st.version || "?"}, CANopen session up ${Math.floor(st.uptime_s || 0)} s, ` +
    (r.hello.allow_changes ? "changes allowed." : "read-only."), ...notes);
  if (conn.dataset.html !== line.innerHTML) { conn.dataset.html = line.innerHTML; conn.replaceChildren(...line.childNodes); }
  if (st.role === "slave") {
    slaveLive(r);
    S.onlineTimer = setTimeout(() => pollOnline(seq), 500);
    return;
  }
  const nodeName = (id, fallback) => {
    const n = (onlineConfig().nodes || []).find((x) => num(x.node_id) === id);
    return n && n.name ? n.name : fallback;
  };
  const rows = (st.nodes || []).map((n) => {
    const boot = n.boot_error ? `error ${n.boot_error}: ${n.boot_error_text || ""}` : n.booted ? "booted" : "not booted";
    const hold = n.hold === "none" ? "" : `held ${n.hold === "stopped" ? "STOPPED" : "PRE-OPERATIONAL"} by ${n.hold_by === "operator" ? "operator" : "the program"}`;
    const em = n.emcy && n.emcy.count ? `${hex4(n.emcy.code)} ${emcyClass(n.emcy.code)} (${n.emcy.count})` : "";
    const vars = (n.sdo_variables || []).map((v) => `${v.name} = ${v.raw}${v.status > 1 ? " (" + sdoStatus(v) + ")" : ""}`).join(", ");
    const stale = (n.pdo_timeouts || []).filter((t) => t.timed_out).map((t) => `TPDO ${t.tpdo} timed out (${t.count})`);
    return el("tr", rowAttrs(() => { S.onlineNode = n.node_id; renderOnlineNode(); pollHighlight(); },
      { class: "clickable" + (S.onlineNode === n.node_id ? " active" : ""), dataset: { onlineNode: n.node_id }, "aria-label": `Open node ${n.node_id}` }),
    el("td", null, String(n.node_id)), el("td", null, nodeName(n.node_id, n.name)),
    el("td", { class: "state-" + n.state }, stateName(n.state)),
    el("td", { dataset: { onlineStatus: n.node_id } }, n.status ? "TRUE" : "FALSE",
      ...stale.map((t) => el("div", { class: "bad", dataset: { pdoTimeout: n.node_id } }, t))),
    el("td", { class: n.boot_error ? "bad" : null }, boot + (n.retry_pending ? " (retrying)" : "")),
    el("td", null, hold), el("td", null, em), el("td", null, vars));
  });
  $("#online-live").replaceChildren(
    el("table", { class: "online-bus" }, el("tbody", null,
      el("tr", null, el("th", null, "Bus"), el("td", { dataset: { online: "bus" } }, `${bus.interface || "?"}: ${BUS_STATES[bus.state] || bus.state || "?"}`),
        el("th", null, "TX / RX errors"), el("td", null, `${bus.tx_errors ?? "-"} / ${bus.rx_errors ?? "-"}`),
        el("th", null, "Bus-off"), el("td", null, String(bus.bus_off_count ?? "-")),
        el("th", null, "Master"), el("td", null, `node ${(st.master || {}).node_id ?? "?"}, ${stateName((st.master || {}).state)}`)),
      st.sync ? el("tr", null, el("th", null, "SYNC"),
        el("td", { colspan: 7, dataset: { online: "sync" } }, syncText(st.sync))) : null)),
    el("table", { class: "online-nodes" },
      el("thead", null, el("tr", null, thCells(["Node", "Name", "State", "Status bit", "Boot", "Hold", "Last EMCY", "SDO variables"]))),
      el("tbody", null, rows.length ? rows : [el("tr", null, el("td", { colspan: 8, class: "muted" }, "No nodes in the configuration the runtime runs."))])));
  const tbox = document.querySelector("[data-online='pdo-timeouts']");
  if (tbox) tbox.replaceChildren(pdoTimeoutTable((st.nodes || []).find((n) => n.node_id === S.onlineNode)));
  if (S.onlineNode !== undefined && S.onlineNode !== null && S.onlineNodeAllow !== r.hello.allow_changes) renderOnlineNode();
  if (S.lssAllow !== r.hello.allow_changes) renderLss(r.hello.allow_changes);
  S.onlineTimer = setTimeout(() => pollOnline(seq), 500);
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

function slavePdoTable(list, dir) {
  const title = dir === "tx" ? "TPDOs (sent by this device)" : "RPDOs (received from the master)";
  const rows = (list || []).map((p) => {
    const cob = Number(p.cob_id) >>> 0;
    const off = (cob & 0x80000000) !== 0;
    const entries = (p.entries || []).map((e) => {
      const bound = slaveBindText(e.index, e.subindex);
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
  $("#online-live").replaceChildren(
    el("p", { class: "muted", dataset: { online: "slave-note" } }, SLAVE_MASTER_ONLY),
    el("table", { class: "online-bus" }, el("tbody", null,
      el("tr", null, el("th", null, "Bus"), el("td", { dataset: { online: "bus" } }, st.bus.interface),
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
    slavePdoTable(s.tpdos, "tx"), slavePdoTable(s.rpdos, "rx"));
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

// A USB adapter on this PC in the online view: what the bus showed since
// connecting (heartbeats, EMCY), the adapter, and another master when one
// runs on the bus. No boot results, holds or SDO variables: no master here.
function localLive(r, conn) {
  const st = r.status;
  const kbit = Math.round((st.bitrate || 0) / 1000);
  const cfgKbit = r.config_bitrate ? Math.round(r.config_bitrate / 1000) : null;
  const notes = [];
  if (cfgKbit && cfgKbit !== kbit) notes.push(el("div", { class: "online-note warning", dataset: { online: "bitrate-differs" } },
    `The adapter runs at ${kbit} kbit/s; this network's config says ${cfgKbit} kbit/s.`));
  if (st.other_master_seen) notes.push(el("div", { class: "online-note warning", dataset: { online: "other-master" } },
    `Another master is active on this bus (${st.other_master_seen.what}, since ${st.other_master_seen.first_at.replace("T", " ").replace(/\.\d+Z$/, " UTC")}). ` +
    "Keep to reading; LSS asks before it runs."));
  if (st.untested_adapter) notes.push(el("div", { class: "online-note" }, "This adapter type is passed to python-can untested."));
  const allowBtn = el("button", { type: "button", class: "small", dataset: { online: "adapter-allow-toggle" }, onclick: async () => {
    if (!r.hello.allow_changes) {
      const v = await modal("Allow changes on this adapter connection? SDO writes, NMT commands, LSS and restore then go to the bus. Saving to a device's non-volatile memory still asks each time.",
        [["allow", "Allow changes", true], ["cancel", "Cancel"]]);
      if (v !== "allow") return;
    }
    await saveOnline({ allow_changes: !r.hello.allow_changes });
  } }, r.hello.allow_changes ? "Back to read-only" : "Allow changes…");
  conn.className = "online-conn ok";
  conn.replaceChildren(`Connected to USB adapter ${st.adapter}, ${kbit} kbit/s${cfgKbit && cfgKbit !== kbit ? ` (config: ${cfgKbit} kbit/s)` : ""}, ` +
    (r.hello.allow_changes ? "changes allowed. " : "read-only. "), allowBtn, ...notes);
  const rows = (st.nodes || []).map((n) => {
    const em = n.emcy && n.emcy.count ? `${hex4(n.emcy.code)} ${emcyClass(n.emcy.code)} (${n.emcy.count})` : "";
    return el("tr", rowAttrs(() => { S.onlineNode = n.node_id; renderOnlineNode(); pollHighlight(); },
      { class: "clickable" + (S.onlineNode === n.node_id ? " active" : ""), dataset: { onlineNode: n.node_id }, "aria-label": `Open node ${n.node_id}` }),
    el("td", null, String(n.node_id)), el("td", null, n.name || ""),
    el("td", { class: n.state === null ? "muted" : "state-" + n.state }, n.state === null ? "not heard" : stateName(n.state)),
    el("td", null, n.last_heard_s === null ? "-" : `${n.last_heard_s.toFixed(1)} s ago`), el("td", null, em));
  });
  $("#online-live").replaceChildren(
    el("table", { class: "online-nodes", dataset: { online: "local-nodes" } },
      el("thead", null, el("tr", null, thCells(["Node", "Name", "State", "Heard", "Last EMCY"]))),
      el("tbody", null, rows.length ? rows : [el("tr", null, el("td", { colspan: 5, class: "muted" },
        "No node heard yet. Nodes without a heartbeat show up in a scan (Scan the bus)."))])));
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

async function commissionDevice() {
  try {
    banner("");
    await api("POST", "/api/commission", {});
    S.view = "online";
    S.onlineForm = true;
    await loadState();
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
  const status = el("span", { class: "muted", dataset: { online: "lss-status" } });
  const result = el("div", { dataset: { online: "lss-result" } });
  const find = el("button", { type: "button", disabled: !allow, title: allow ? null : NO_CHANGES,
    dataset: { online: "lss-find" }, onclick: () => runLssFind(true) }, "Find a device without node ID");
  box.replaceChildren(el("fieldset", { dataset: { online: "lss" } }, el("legend", null, "Unconfigured devices (LSS)"),
    el("p", { class: "muted" }, "Devices without DIP switches get their node ID and bit rate over the bus (LSS, CiA 305). " +
      "Find one device that has no node ID yet, then set its node ID or bit rate. PDOs of the configured nodes keep running."),
    allow ? null : el("p", { class: "field-msg warning", dataset: { online: "lss-no-changes" } }, NO_CHANGES),
    el("div", { class: "toolbar" }, find, status), result));
  if (allow && S.lssDevice) showLssDevice(S.lssDevice);
}

async function runLssFind(start) {
  const seq = S.onlineSeq;
  const status = document.querySelector("[data-online=lss-status]");
  let r;
  try {
    r = start ? await apiForce("/api/online/lss_find", { start, port: diagPort() })
      : await api("POST", "/api/online/lss_find", { start, port: diagPort() });
  } catch (e) {
    if (seq === S.onlineSeq && status) status.textContent = e.message;
    return;
  }
  if (seq !== S.onlineSeq || S.view !== "online") return;
  const st = document.querySelector("[data-online=lss-status]");
  if (!st) return;
  if (r.running) {
    st.textContent = `Searching… ${Math.floor(r.seconds || 0)} s (up to about 15 s)`;
    setTimeout(() => runLssFind(false), 300);
    return;
  }
  if (r.error) { st.textContent = "The search failed: " + r.error; return; }
  if (!r.found || !r.device) {
    S.lssDevice = null;
    st.textContent = `No device without a node ID answered (${(r.seconds || 0).toFixed(1)} s).`;
    document.querySelector("[data-online=lss-result]").replaceChildren();
    return;
  }
  st.textContent = `Found in ${(r.seconds || 0).toFixed(1)} s.`;
  S.lssDevice = r.device;
  showLssDevice(r.device);
}

function showLssDevice(d) {
  const box = document.querySelector("[data-online=lss-result]");
  if (!box) return;
  const m = d.eds_matches || [];
  const vendorName = m.length ? m[0].vendor_name : "";
  const sel = m.length ? el("select", { "aria-label": "EDS file", dataset: { online: "lss-eds" } }, m.map((x, k) =>
    el("option", { value: k }, `${x.name} (${x.where === "project" ? "project" : "library"}${x.revision_match ? ", exact revision" : ""})`)))
    : el("span", { class: "muted" }, "No matching EDS");
  box.replaceChildren(el("table", { class: "scan" },
    el("thead", null, el("tr", null, thCells(["Vendor", "Product", "Revision", "Serial number", "Node ID", "EDS", ""]))),
    el("tbody", null, el("tr", { dataset: { lssDevice: d.serial_number } },
      el("td", null, hex8(d.vendor_id) + (vendorName ? " " + vendorName : "")), el("td", null, hex8(d.product_code)),
      el("td", null, hex8(d.revision_number)), el("td", null, `${d.serial_number} (${hex8(d.serial_number)})`),
      el("td", null, d.node_id === undefined || d.node_id === 255 ? "none" : String(d.node_id)),
      el("td", null, sel),
      el("td", null,
        el("button", { type: "button", dataset: { online: "lss-set-id" }, onclick: () => lssSetId(d, m.length ? m[Number(sel.value)] : null) }, "Set node ID…"),
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
  const v = await modal(`Set the node ID of the device with serial number ${hex8(d.serial_number)}.`,
    [["set", "Set node ID", true], ["cancel", "Cancel"]],
    el("div", null, el("label", { class: "inline" }, "Node ID ", idInput), el("div", null, store)));
  if (v !== "set") return;
  const node = Number(idInput.value);
  if (!(node >= 1 && node <= 127)) { banner("The node ID must be 1-127.", true); return; }
  let r;
  try {
    r = await apiForce("/api/online/lss_set_id", { address: lssAddress(d), node, store: store.querySelector("input").checked, port: diagPort() });
  } catch (e) { banner(e.message, true); return; }
  banner(`Node ID ${node} set${r.stored ? " and stored in the device" : ""}. ${r.note.charAt(0).toUpperCase() + r.note.slice(1)}.`);
  S.lssDevice = null;
  const box = document.querySelector("[data-online=lss-result]");
  if (box) box.replaceChildren();
  if (configNode(node) || S.state.commission) return;
  const add = await modal(`Add the device to the configuration as node ${node}` + (match ? ` with ${match.name}` : "") +
    "? It gets the device's serial number and LSS assignment, so the master gives it this node ID at every start.",
    [["add", "Add as node", true], ["no", "Not now"]]);
  if (add !== "add") return;
  if (!match) {
    banner(`No matching EDS was found. Add node ${node} from its EDS file, then set its serial number ${hex8(d.serial_number)} and tick LSS assignment.`, true);
    return;
  }
  await addScannedNode(Object.assign({}, d, { node_id: node }), match, null, false, true);
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
  for (const tr of document.querySelectorAll("tr[data-online-node]")) tr.classList.toggle("active", Number(tr.dataset.onlineNode) === S.onlineNode);
}

function sdoStatus(v) {
  return v.abort_code ? "abort " + hex8(v.abort_code) : "status " + v.status;
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
  const box = $("#online-node");
  if (!box || S.onlineNode === undefined || S.onlineNode === null) return;
  const id = S.onlineNode;
  const slave = onlineIsSlave() ? onlineSlaveCfg() || {} : null;
  // The slave's own device: its EDS stands in for a configured node's.
  const n = slave ? { node_id: id, name: "this PLC (slave device)", eds: slave.eds } : configNode(id);
  const allow = S.onlineLast ? S.onlineLast.hello.allow_changes : false;
  S.onlineNodeAllow = S.onlineLast ? allow : undefined;
  let tab = S.onlineTab || "overview";
  // The PDO test only on a USB adapter: on a runtime the PLC runs the PDOs.
  const pdoTab = !slave && pdoTestLocal();
  if ((slave && tab === "params") || (!pdoTab && tab === "pdo")) tab = "overview";
  const tabList = tabs([["overview", "Overview"], ["od", "Object dictionary"], ["params", "Parameters"], ["pdo", "PDO test"]]
    .filter(([k]) => (!slave || k !== "params") && (pdoTab || k !== "pdo")),
    tab, (k) => { S.onlineTab = k; renderOnlineNode(); }, { dataset: "onlineTab", panel: "online-node-panel", label: "Node pages" });
  const title = el("h2", null, `Node ${id} ${n && n.name ? n.name : (S.onlineEdsName || {})[id] || ""}`);
  const panel = (...kids) => el("div", { id: "online-node-panel", role: "tabpanel", "aria-labelledby": `online-node-panel-tab-${tab}` }, ...kids);
  // The object dictionary tab takes the problems pane's room, as the trace does.
  $("#editor").classList.toggle("wide-view", tab === "od");
  if (tab === "od") { put(box, title, tabList, panel(odPanel(id, n, allow))); return; }
  if (tab === "params") { put(box, title, tabList, panel(paramsPanel(id, n, allow))); return; }
  if (tab === "pdo") { put(box, title, tabList, panel(pdoTestPanel(id, n, allow))); return; }
  if (slave) { put(box, title, tabList, panel(sdoPanel(id, n, allow))); return; }
  const emcy = el("div", { dataset: { online: "emcy" } }, el("span", { class: "muted" }, "Loading…"));
  const last = S.onlineLast && S.onlineLast.status ? (S.onlineLast.status.nodes || []).find((x) => x.node_id === id) : null;
  const timeouts = last && (last.pdo_timeouts || []).length
    ? el("fieldset", null, el("legend", null, "Input PDO timeouts"), el("div", { dataset: { online: "pdo-timeouts" } }, pdoTimeoutTable(last)))
    : null;
  put(box, title, tabList, panel(
    el("fieldset", null, el("legend", null, "NMT"), nmtButtons(id, allow)),
    timeouts,
    sdoPanel(id, n, allow),
    el("fieldset", null, el("legend", null, "Emergency history (newest first)"), emcy,
      el("button", { type: "button", onclick: () => renderOnlineNode() }, "Refresh"))));
  try {
    const r = await api("POST", "/api/online/emcy", { node: id, port: diagPort() });
    emcy.replaceChildren(r.emcy.length ? el("table", null,
      el("thead", null, el("tr", null, thCells(["Time (UTC)", "Code", "Class", "Error register", "Manufacturer data"]))),
      el("tbody", null, r.emcy.map((e) => el("tr", null, el("td", null, e.time.replace("T", " ").replace("Z", "")),
        el("td", null, hex4(e.code)), el("td", null, e.class), el("td", null, "0x" + e.error_register.toString(16).toUpperCase().padStart(2, "0")),
        el("td", null, e.manufacturer))))) : el("p", { class: "muted" }, "No EMCY from this node since the CANopen session started."));
  } catch (e) {
    emcy.replaceChildren(el("p", { class: "field-msg" }, e.message));
  }
}

// The monitored TPDOs of a node in the status answer: timeout, timed out
// now, timeouts so far, time since the last PDO.
function pdoTimeoutTable(n) {
  const list = (n && n.pdo_timeouts) || [];
  if (!list.length) return el("p", { class: "muted" }, "No TPDO of this node has a receive timeout.");
  return el("table", null,
    el("thead", null, el("tr", null, thCells(["TPDO", "Timeout", "Now", "Timeouts", "Last PDO"]))),
    el("tbody", null, list.map((t) => el("tr", { dataset: { pdoTimeoutRow: t.tpdo } },
      el("td", null, String(t.tpdo)), el("td", null, `${t.timeout_ms} ms`),
      el("td", { class: t.timed_out ? "bad" : null }, t.timed_out ? "timed out" : "receiving"),
      el("td", null, String(t.count)),
      el("td", null, t.since_ms === null || t.since_ms === undefined ? "never" : `${t.since_ms} ms ago`)))));
}

function nmtButtons(id, allow) {
  const send = async (command, label, confirm) => {
    if (confirm) {
      const v = await modal(confirm, [["go", label, true], ["cancel", "Cancel"]]);
      if (v !== "go") return;
    }
    try {
      const r = await api("POST", "/api/online/nmt", { node: id, command, port: diagPort() });
      banner(`Node ${id}: ${label} sent.` + (r.note ? " " + r.note + "." : ""));
    } catch (e) { banner(e.message, true); }
  };
  const btn = (command, label, confirm) => el("button", { type: "button", disabled: !allow, title: allow ? null : NO_CHANGES,
    dataset: { nmt: command }, onclick: () => send(command, label, confirm) }, label);
  return el("div", null, el("div", { class: "toolbar" },
    btn("start", "Start"),
    btn("stop", "Stop", `Stop node ${id}? Its PDOs stop and it stays STOPPED, also after a reboot, until you start it or the program changes its NMT command byte.`),
    btn("preop", "Pre-operational", `Set node ${id} pre-operational? Its PDOs stop until it is started again, by you or by the program's NMT command byte.`),
    btn("reset", "Reset node", `Reset node ${id}? It reboots and the master configures it again.`),
    btn("reset-comm", "Reset communication", `Reset node ${id}'s communication? It comes back pre-operational and the master configures it again.`)),
  allow ? hint("Stop and pre-operational hold the node until you start it, or until the program changes the node's NMT command byte.")
    : el("p", { class: "field-msg warning", dataset: { online: "no-changes" } }, NO_CHANGES));
}

function sdoPanel(id, n, allow) {
  const eds = n ? edsFor(n) : null;
  const objects = eds && eds.objects ? eds.objects : [];
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
    pick.replaceChildren(el("option", { value: "" }, objects.length ? "Pick an object from the EDS…" : "No EDS objects (type index and subindex)"),
      ...objects.filter((o) => !f || `${o.index}:${o.subindex} ${o.name}`.toLowerCase().includes(f)).map((o) =>
        el("option", { value: `${o.index}:${o.subindex}` }, `${o.index}:${o.subindex} ${o.name} (${typeNames[o.type_code] || o.type || "?"}, ${o.access})`)));
  };
  fill();
  filter.addEventListener("input", fill);
  pick.addEventListener("change", () => {
    const o = objects.find((x) => `${x.index}:${x.subindex}` === pick.value);
    if (!o) return;
    ix.value = o.index;
    sub.value = String(o.subindex);
    type.value = typeNames[o.type_code] || "";
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
    try { show(await api("POST", "/api/online/sdo_write", Object.assign(t, { value: value.value })), "write"); }
    catch (e) { out.replaceChildren(el("span", { class: "field-msg" }, e.message)); }
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
  return el("p", { class: "muted", dataset: { online: "no-eds" } },
    `Node ${id} has no EDS here: add it to the configuration, or open it from a scan row with a matching EDS.`);
}

async function odEntries(id) {
  const src = nodeSource(id);
  const own = src.config ? onlineSlaveCfg() || configNode(id) : null;
  const key = JSON.stringify([src.config ? own.eds : src.eds_path, own ? own.sdo || own.objects : null,
    own ? own.sdo_variables || (onlineSlaveCfg() ? S.model.top.gateway : null) : null]);
  S.odEntries = S.odEntries || {};
  const cached = S.odEntries[id];
  if (cached && cached.key === key) return cached.data;
  const data = await api("POST", "/api/online/od_entries", src);
  S.odEntries[id] = { key, data };
  return data;
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

// Follows a job until it ends, with progress and Cancel in `status`.
// onDone(job, resumed) gets the finished job (also a cancelled one).
async function followJob(j, status, onDone, resumed) {
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
      put(status, el("span", { class: "field-msg" }, e.message));
      return null;
    }
  }
  S.seenJobs = S.seenJobs || {};
  if (!S.seenJobs[j.id] && typeof commLogJob === "function") commLogJob(j);
  S.seenJobs[j.id] = true;
  put(status);
  if (j.state === "failed") {
    status.append(el("span", { class: "field-msg", dataset: { online: "job-error" } }, j.error));
    return j;
  }
  if (j.state === "cancelled") status.append(el("span", { class: "muted" }, "Cancelled."));
  if (j.result) onDone(j, !!resumed);
  return j;
}

async function startJob(path, body, status, onDone) {
  let r;
  try { r = await api("POST", path, body); } catch (e) {
    put(status, el("span", { class: "field-msg" }, e.message));
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
const OD_BITS = {
  0x1001: { size: 1, names: ["generic error", "current", "voltage", "temperature", "communication error",
    "device profile specific", "reserved", "manufacturer specific"] },
  0x1002: { size: 4, names: null },
  0x6040: { size: 2, cia402: true, names: ["switch on", "enable voltage", "quick stop", "enable operation",
    "operation mode specific 4", "operation mode specific 5", "operation mode specific 6", "fault reset", "halt",
    "operation mode specific 9", "reserved", "manufacturer specific 11", "manufacturer specific 12",
    "manufacturer specific 13", "manufacturer specific 14", "manufacturer specific 15"] },
  0x6041: { size: 2, cia402: true, names: ["ready to switch on", "switched on", "operation enabled", "fault",
    "voltage enabled", "quick stop", "switch on disabled", "warning", "manufacturer specific 8", "remote",
    "target reached", "internal limit active", "operation mode specific 12", "operation mode specific 13",
    "manufacturer specific 14", "manufacturer specific 15"] },
};
// Value names of CiA 402 modes of operation (0x6060, and its display 0x6061).
const OD_MODES = { 1: "profile position", 2: "velocity", 3: "profile velocity", 4: "profile torque", 6: "homing",
  7: "interpolated position", 8: "cyclic sync position", 9: "cyclic sync velocity", 10: "cyclic sync torque" };
const OD_FILTERS = [["changed", "Changed from default"], ["writable", "Writable"], ["owned", "Set by config or SDO variable"],
  ["pdo", "In a PDO"], ["failed", "Not readable"], ["compare", "Different in last compare"]];
const OD_NUMERIC = ["BOOLEAN", "INTEGER8", "INTEGER16", "INTEGER32", "INTEGER64", "UNSIGNED8", "UNSIGNED16",
  "UNSIGNED32", "UNSIGNED64", "REAL32", "REAL64"];  // the startup SDO types (co_type)
const WATCH_HISTORY_MS = 10 * 60 * 1000;

function odState(id) {
  S.od = S.od || {};
  return S.od[id] || (S.od[id] = { values: {}, watch: [], period: 1000, filter: "", filters: [], formats: {},
    bitsOpen: {}, openGroups: [], openObjects: [], at: {}, changedAt: {}, mm: {}, hist: [], keep: {} });
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

function odIs402(id, byKey) {
  const st = odState(id);
  const v = st.values[odKey(0x1000, 0)];
  const data = v && v.data ? v.data : (byKey[odKey(0x1000, 0)] || {}).default_data;
  const n = data ? odNumber(data, "UNSIGNED32") : null;
  return n !== null && Number(n & 0xFFFFn) === 402;
}

// The names of the set bits of a known bit-field entry, or null.
function odBitNames(e, v, is402) {
  const t = OD_BITS[e.index];
  if (!t || e.subindex !== 0 || (t.cia402 && !is402) || !v || v.error) return null;
  const it = intInfo(e.type);
  if (!it || it.signed || it.bytes !== t.size) return null;
  const n = odNumber(v.data, e.type);
  if (n === null) return null;
  const out = [];
  for (let b = 0; b < t.size * 8; b++) if ((n >> BigInt(b)) & 1n) out.push(t.names ? t.names[b] : `bit ${b}`);
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
  const value = keepValue(e, v);
  if (i < 0 || value === null) return;
  n.sdo = n.sdo || [];
  const j = n.sdo.findIndex((s) => sameObject(s.index, s.subindex, e.index, e.subindex));
  if (j >= 0) n.sdo[j].value = value;
  else n.sdo.push({ index: hex4(e.index), subindex: e.subindex, type: e.type, value });
  changed();
  banner(`Node ${id}: startup SDO ${hex4(e.index)}:${e.subindex} = ${value} ${j >= 0 ? "changed" : "added"} in the configuration. Save to keep it.`);
}

function csvField(s) { s = String(s ?? ""); return /[",\n\r]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s; }

function odPanel(id, n, allow) {
  const box = el("div", { class: "od-panel", dataset: { online: "od" } });
  if (!nodeSource(id)) { put(box, noEds(id)); return box; }
  put(box, el("p", { class: "muted" }, "Loading the object dictionary…"));
  odEntries(id).then((data) => odBuild(box, id, n, allow, data))
    .catch((e) => put(box, el("p", { class: "field-msg" }, e.message)));
  return box;
}

function odBuild(box, id, n, allow, data) {
  const st = odState(id);
  const byKey = {};
  for (const e of data.entries) byKey[odKey(e.index, e.subindex)] = e;
  const objects = [];  // {index, group, name, type, entries}
  for (const e of data.entries) {
    const last = objects[objects.length - 1];
    if (last && last.index === e.index) { last.entries.push(e); continue; }
    objects.push({ index: e.index, group: e.group, type: e.object_type || "VAR", name: e.object || e.sub_name || e.name, entries: [e] });
  }
  const cells = {};  // key: {tr, value, marks, edit, editing}
  const objRows = {};  // index: {tr, sub rows, summary}
  const status = el("div", { class: "job-status", dataset: { online: "od-status" } });
  const summary = el("div", { class: "muted", dataset: { online: "od-summary" } });
  const is402 = () => odIs402(id, byKey);
  if (st.plot) { st.plot.destroy(); st.plot = null; }

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
    if ((e.index === 0x6060 || e.index === 0x6061) && is402()) {
      const m = odNumber(v.data, e.type);
      if (m !== null && OD_MODES[Number(m)]) c.value.append(" ", el("span", { class: "muted" }, OD_MODES[Number(m)]));
    }
    const it = intInfo(e.type);
    const bits = odBitNames(e, v, is402());
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
    if (bits && st.bitsOpen[key]) {
      c.value.append(el("div", { class: "od-bits", dataset: { online: "od-bit-list" } },
        bits.length ? bits.map((b) => el("span", { class: "tag" }, b)) : el("span", { class: "muted" }, "no bit set")));
    }
    if (st.keep[key] && n && !data.slave) {
      const why = keepReason(e, n);
      c.value.append(el("div", { class: "od-keep" }, why
        ? el("span", { class: "muted", dataset: { online: "od-keep-reason" } }, "Not kept in the configuration: " + why)
        : el("button", { type: "button", class: "small", dataset: { online: "od-keep" }, title: "Add this value as a startup SDO, so the node gets it at every boot (nothing is stored on the device)",
          onclick: () => { delete st.keep[key]; keepInConfig(id, e, v); showValue(key); } }, "Keep in configuration")));
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
    const now = Date.now();
    for (const v of res.values || []) {
      const key = odKey(v.index, v.subindex);
      const old = st.values[key];
      if (watchRound && old && !old.error && old.data !== v.data) st.changedAt[key] = now;
      st.values[key] = { data: v.data, text: v.text };
      st.at[key] = now;
    }
    for (const f of res.failures || []) {
      st.values[odKey(f.index, f.subindex)] = { error: (f.abort_code !== null && f.abort_code !== undefined ? `Abort ${hex8(f.abort_code)}: ` : "") + f.error };
      st.at[odKey(f.index, f.subindex)] = now;
    }
    const touched = new Set();
    for (const v of (res.values || []).concat(res.failures || [])) { showValue(odKey(v.index, v.subindex)); touched.add(v.index); }
    for (const i of touched) updateObject(i);
    renderWatch();
  };
  const readKeys = async (keys, watchRound) => {
    const res = await api("POST", "/api/online/od_read", Object.assign(nodeSource(id), { keys }));
    setReading(res, watchRound);
    return res;
  };
  const readObject = async (o) => {
    const keys = o.entries.filter((e) => e.readable).map((e) => [e.index, e.subindex]);
    for (let i = 0; i < keys.length; i += 64) await readKeys(keys.slice(i, i + 64));
  };

  // -- watch list: kept on this PC per project and node; values, age, min/max and a graph.
  const watchBox = el("div", { dataset: { online: "watch" } });
  const watchInfo = el("div", { class: "muted", dataset: { online: "watch-info" } });
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
  const renderWatch = () => {
    graphButton.textContent = st.graphOpen ? "Hide graph" : "Graph";
    if (!st.watch.length) {
      put(watchBox, el("p", { class: "muted" }, `Tick Watch on up to ${WATCH_MAX} entries to read them again and again.`));
      put(watchInfo);
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
    put(watchInfo,
      st.lastRound !== undefined ? el("span", { dataset: { online: "watch-round" }, class: st.lastRound > st.period ? "field-msg warning" : null },
        `A round of reads takes ${st.lastRound} ms` + (st.lastRound > st.period ? `, longer than the chosen ${st.period >= 1000 ? st.period / 1000 + " s" : st.period + " ms"}.` : ".")) : null,
      sdoVarsNote() ? el("div", { class: "field-msg warning", dataset: { online: "watch-sdo-vars" } },
        "This node has SDO variables the program reads periodically; watch reads go before them on the bus and may delay them.") : null);
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
    const muted = themeColor("--muted"), line = themeColor("--line");
    st.plotKeys = sig;
    st.plot = new uPlot({ width, height: 220, legend: { show: true, live: true },
      series: [{ label: "t (s)" }].concat(keys.map((k, i) => ({ label: `${hex4(byKey[k].index)}:${byKey[k].subindex} ${byKey[k].sub_name || byKey[k].name}`,
        stroke: SERIES_COLORS[i % SERIES_COLORS.length], width: 1.5, spanGaps: true }))),
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
    while (st.watchToken === token && st.watch.length && box.isConnected && S.view === "online" && S.onlineNode === id) {
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
      onclick: () => odEdit(id, n, e, cells[key], readKeys, (wrote) => {
        cells[key].editing = false;
        if (wrote) st.keep[key] = true;
        showValue(key);
      }) }, "Edit");
    const tr = el("tr", { class: isSub ? "od-sub" : "od-var", dataset: { odKey: key, odObject: String(e.index) } },
      el("td", { class: "mono" }, isSub ? `:${e.subindex}` : `${hex4(e.index)}:${e.subindex}`),
      el("td", { class: "od-name" }, el("div", null, isSub ? e.sub_name || e.name : e.name), marks),
      el("td", { class: "od-type" }, e.type || "?", " ", el("span", { class: "muted" }, e.access),
        e.default ? el("div", { class: "muted", title: "EDS default" }, "default " + e.default) : null),
      value, el("td", { class: "actions" }, read, edit,
        el("button", { type: "button", class: "small", disabled: data.slave || (!e.readable && !e.writable),
          title: data.slave ? NO_ST_SLAVE : "Copy as ST call (CO_SDO_* block)",
          dataset: { online: "od-st" }, onclick: () => copyStCall(id, e.index, e.subindex, e.type, e.readable, e.writable) }, "ST")),
      el("td", { class: "od-watch" }, watch));
    cells[key] = { tr, value, marks, watch, text: `${hex4(e.index)}:${e.subindex} ${e.index.toString(16)} ${e.name}`.toLowerCase() };
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
      const tr = el("tr", { class: "od-object", dataset: { odObjectRow: String(o.index) } },
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
      rows.push(tr, ...subs);
    }
    const det = el("details", { dataset: { odGroup: g } }, el("summary", null, `${title} (${list.length} objects)`),
      el("div", { class: "table-scroll" }, el("table", { class: "od od-tree" },
        el("colgroup", null, ["c-entry", "c-name", "c-type", "c-value", "c-actions", "c-watch"].map((c) => el("col", { class: c }))),
        el("thead", null, el("tr", null, thCells(["Entry", "Name", "Type", "Value", "", "Watch"]))),
        el("tbody", null, rows))));
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
    put(chips, OD_FILTERS.filter(([k]) => k !== "compare" || st.compare).map(([k, label]) => {
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
    try { anyShow(await api("POST", "/api/online/sdo_write", Object.assign(t, { value: anyValue.value })), "write"); }
    catch (err) { put(anyOut, el("span", { class: "field-msg" }, err.message)); }
  };

  const readAll = el("button", { type: "button", class: "primary", dataset: { online: "od-read-all" }, onclick: () => {
    summary.textContent = "";
    startJob("/api/online/od_read", Object.assign(nodeSource(id), { all: true }), status, showAll);
  } }, "Read all");
  const showAll = (j) => {
    setReading(j.result);
    const r = j.result;
    summary.textContent = `${r.read} read, ${r.failed} not readable${r.cancelled ? ", cancelled" : ""}.` + (r.stopped ? " Stopped: " + r.stopped + "." : "");
    applyFilter();
  };
  st.refreshMarks = () => { if (box.isConnected) { renderChips(); for (const key of Object.keys(cells)) showValue(key); applyFilter(); } };
  put(box,
    allow ? null : el("p", { class: "field-msg warning", dataset: { online: "od-read-only" } }, "Read-only: " + NO_CHANGES),
    data.note ? el("p", { class: "field-msg warning" }, data.note) : null,
    el("div", { class: "toolbar" }, filter, readAll,
      el("button", { type: "button", dataset: { online: "od-copy" }, onclick: copyRows }, "Copy"),
      el("button", { type: "button", dataset: { online: "od-csv" }, onclick: saveCsv }, "Save CSV"), status),
    chips, summary, compareNote,
    el("fieldset", null, el("legend", null, "Watch list"),
      el("div", { class: "toolbar" }, el("label", { class: "inline" }, "Every ", period), graphButton, resetButton), watchInfo, watchBox, graphBox),
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
function odEdit(id, n, e, cell, readKeys, done) {
  cell.editing = true;
  const v = (S.od[id].values[odKey(e.index, e.subindex)] || {});
  const input = el("input", { type: "text", class: "od-input", "aria-label": "New value", dataset: { online: "od-input" } });
  input.value = v.text ? v.text.replace(/ \(0x[0-9A-F]+\)$/, "") : "";
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
    try {
      const r = await api("POST", "/api/online/sdo_write", { node: id, index: e.index, subindex: e.subindex, type: e.type, value: input.value, port: diagPort() });
      if (!r.success) { msg.textContent = r.abort_code !== undefined ? `Abort ${hex8(r.abort_code)}: ${r.abort_text}` : r.reason; return; }
    } catch (err) { msg.textContent = err.message; return; }
    try { await readKeys([[e.index, e.subindex]]); } catch (err) { banner(err.message, true); }
    done(true);
  };
  input.addEventListener("keydown", (ev) => { if (ev.key === "Enter") write(); if (ev.key === "Escape") done(false); });
  put(cell.value, input, el("button", { type: "button", class: "small primary", dataset: { online: "od-write" }, onclick: write }, "Write"),
    el("button", { type: "button", class: "small", onclick: () => done(false) }, "Cancel"),
    limits ? el("div", { class: "muted", dataset: { online: "od-limits" } }, limits) : null, msg);
  input.focus();
}

// -- parameters tab ---------------------------------------------------------------

function paramsPanel(id, n, allow) {
  const box = el("div", { dataset: { online: "params" } });
  if (!nodeSource(id)) { put(box, noEds(id)); return box; }
  const status = el("div", { class: "job-status", dataset: { online: "params-status" } });
  const out = el("div", { dataset: { online: "params-result" } });
  const why = allow ? null : NO_CHANGES;

  // Back up
  const showBackup = (j, resumed) => {
    const r = j.result;
    if (!r) return;
    if (!resumed) downloadBase64(r.data, r.name);
    put(out, el("p", { dataset: { online: "backup-done" } }, `${r.name}: ${r.read} entries read, ${r.failed} not read. `,
      el("button", { type: "button", class: "small", onclick: () => downloadBase64(r.data, r.name) }, resumed ? "Download" : "Download again")),
    r.stopped ? el("p", { class: "field-msg" }, "Stopped: " + r.stopped) : null,
    r.boot_state ? el("p", { class: "field-msg warning" }, `Read while the node was ${r.boot_state}.`) : null,
    ...(r.lint || []).map((m) => el("p", { class: "field-msg warning" }, m)));
  };
  const backup = async () => {
    const live = nodeLive(id);
    if (live && !live.booted) {
      const v = await modal(`Node ${id} has not booted successfully, so the master may not have configured it yet. Back up anyway?`,
        [["go", "Back up anyway", true], ["cancel", "Cancel"]]);
      if (v !== "go") return;
    }
    put(out);
    startJob("/api/online/backup", nodeSource(id), status, showBackup);
  };

  // Compare
  const ref = el("select", { "aria-label": "Compare against", dataset: { online: "compare-ref" } },
    el("option", { value: "file" }, "a backup file"), el("option", { value: "config", disabled: !n }, "the configuration"),
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
    put(out, el("p", { dataset: { online: "compare-summary" } },
      `${s.different} different, ${s["not readable"]} not readable, ${s.equal} equal, ${s["no reference"]} without a reference.`),
    r.stopped ? el("p", { class: "field-msg" }, "Stopped: " + r.stopped) : null,
    rows.length ? el("table", { class: "od compare-rows" },
      el("thead", null, el("tr", null, thCells(["Entry", "Name", "Result", r.reference === "file" ? "Backup" : r.reference === "config" ? "Configuration" : "EDS default", "Device"]))),
      el("tbody", null, rows.map((x) => el("tr", { class: x.result === "different" ? "bad" : x.result === "equal" ? "muted" : null },
        el("td", { class: "mono" }, `${hex4(x.index)}:${x.subindex}`), el("td", null, x.name), el("td", null, x.result),
        el("td", null, x.reference ?? ""), el("td", null, x.device ?? (x.error || "")))))) : null);
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
    const defaultsHint = defaults ? hint("Restore defaults writes \"load\" to 0x1011: the device takes its factory values at its next reset.") : null;
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
  }).catch((e) => put(storeBox, el("p", { class: "field-msg" }, e.message)));

  put(box,
    allow ? null : el("p", { class: "field-msg warning", dataset: { online: "params-read-only" } }, "Restore and store are off: " + NO_CHANGES),
    el("fieldset", null, el("legend", null, "Back up"),
      el("div", { class: "toolbar" }, el("button", { type: "button", class: "primary", dataset: { online: "backup" }, onclick: backup }, "Back up")),
      hint("Reads every readable entry of the node's EDS and downloads a DCF with the values (ParameterValue), which other CANopen tools can open too.")),
    el("fieldset", null, el("legend", null, "Compare"),
      el("div", { class: "toolbar" }, el("label", { class: "inline" }, "Against ", ref), cmpFile,
        el("label", { class: "inline" }, ro, " include read-only entries"),
        el("button", { type: "button", dataset: { online: "compare" }, onclick: compare }, "Compare"),
        el("label", { class: "inline" }, showEqual, " show equal entries"))),
    el("fieldset", null, el("legend", null, "Restore"),
      el("div", { class: "toolbar" }, resFile, el("label", { class: "inline" }, comm, " include communication objects (0x1000-0x1FFF)"),
        el("button", { type: "button", disabled: !allow, title: why, dataset: { online: "restore" }, onclick: restore }, "Restore…")),
      hint("Shows what would be written first. Writes only differing manufacturer and profile entries; PDO objects, store/restore commands and what the configuration writes at boot are left out. Restored values are not stored on the device.")),
    onlineIsSlave() ? null : configureBox(id, n, allow, status, out),
    el("fieldset", null, el("legend", null, "Store on device"), storeBox),
    status, out);
  resumeJob(id, ["backup", "compare", "restore_plan", "restore", "configure", "configure_verify"], status, (j, resumed) => {
    if (j.kind === "backup") showBackup(j, resumed);
    else if (j.kind === "compare") compareDone(j);
    else if (j.kind === "restore") showRestore(j.result, out);
    else if (j.kind === "configure") showConfigure(j.result, out);
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
  const writes = p.writes.length ? el("table", { class: "od" },
    el("thead", null, el("tr", null, thCells(["Entry", "Name", "Backup", "Device now"]))),
    el("tbody", null, p.writes.map((w) => el("tr", null, el("td", { class: "mono" }, `${hex4(w.index)}:${w.subindex}`), el("td", null, w.name),
      el("td", null, w.backup), el("td", null, w.device ?? "not readable"))))) : el("p", { class: "muted" }, "Nothing to write: the device already has the backup's values.");
  const skipped = p.skipped.length ? el("details", null, el("summary", null, `${p.skipped.length} entries left out`),
    el("table", { class: "od" }, el("tbody", null, p.skipped.map((s) => el("tr", null, el("td", { class: "mono" }, `${hex4(s.index)}:${s.subindex}`),
      el("td", null, s.name), el("td", { class: "muted" }, s.reason)))))) : null;
  const extra = el("div", { class: "restore-preview", dataset: { online: "restore-preview" } },
    ids.map((i) => el("p", { class: i.level === "refuse" ? "field-msg" : i.level === "warning" ? "field-msg warning" : "muted" }, i.text)),
    p.note ? el("p", { class: "field-msg warning" }, p.note) : null,
    p.configured ? null : el("p", { class: "muted" }, "The node is not in the configuration, so nothing is left out as written by the configuration."),
    writes, skipped,
    el("p", { class: "muted" }, `${p.unchanged.length} entries already equal.`),
    p.writes.length ? el("label", { class: "check" }, hold, " Hold the node in PRE-OPERATIONAL while writing (needed when the device refuses writes with abort 0x08000022)") : null,
    refuse.length ? el("label", { class: "check" }, other, " Restore to a different product anyway") : null,
    p.allow_changes ? null : el("p", { class: "field-msg warning" }, NO_CHANGES));
  const can = p.writes.length && p.allow_changes;
  const go = modal(`Restore ${p.writes.length} value${p.writes.length === 1 ? "" : "s"} to node ${id}?`,
    can ? [["cancel", "Cancel"], ["restore", "Restore", { danger: true }]] : [["cancel", "Close"]], extra);
  const btn = document.querySelector('#modal-buttons button[data-value="restore"]');
  if (btn && refuse.length) {
    btn.disabled = true;
    other.addEventListener("change", () => { btn.disabled = !other.checked; });
  }
  if (await go !== "restore") return;
  startJob("/api/online/restore", Object.assign(nodeSource(id), { plan: j.id, hold: hold.checked, ignore_identity: other.checked }), status,
    (r) => showRestore(r.result, out));
}

function showRestore(r, out) {
  if (!r) return;
  put(out, el("p", { dataset: { online: "restore-done" } },
    `${r.written.length} written, ${r.failed.length} failed${r.cancelled ? ", cancelled" : ""}.`),
  ...r.failed.map((f) => el("p", { class: "field-msg" }, `${hex4(f.index)}:${f.subindex} ${f.name}: ${f.error}`)),
  r.released === false ? el("p", { class: "field-msg" }, `The node is still held in PRE-OPERATIONAL (${r.release_error}); release it with Start.`) : null,
  el("p", { class: "field-msg warning", dataset: { online: "restore-note" } }, r.note.charAt(0).toUpperCase() + r.note.slice(1) + "."));
}

async function storeDialog(id, sub, what) {
  const v = await modal(`Store node ${id}'s current ${what || "values"} in its non-volatile memory (write "save" to 0x1010 sub ${sub})? ` +
    "The device then keeps these values over a power cycle. Each store wears the device's flash memory.",
  [["cancel", "Cancel"], ["store", "Store on device", { danger: true }]]);
  if (v !== "store") return;
  try {
    const r = await api("POST", "/api/online/store", Object.assign(nodeSource(id), { subindex: sub }));
    if (r.stored) banner(`Node ${id}: stored (0x1010 sub ${sub}).`);
    else banner(`Node ${id} did not store: ${r.error}`, true);
  } catch (e) { banner(e.message, true); }
}

// ---------------------------------------------------------------------------
// Scan page

function renderScan(view) {
  view.append(el("h2", null, "Scan the bus"), stepsPanel() || "",
    el("p", { class: "muted" }, "Asks every node ID 1-127 for its identity (0x1018), device type and name, through the runtime or the USB adapter. Reads only; PDOs keep running. Devices that are STOPPED do not answer."));
  const lib = el("input", { type: "text", spellcheck: "false", class: "wide", placeholder: "a folder of vendor EDS files",
    "aria-label": "EDS library folder", dataset: { online: "library" } });
  lib.value = S.online.eds_library || "";
  lib.addEventListener("change", async () => {
    try { S.online = Object.assign(S.online, await api("POST", "/api/online/settings", { eds_library: lib.value.trim() })); banner(""); }
    catch (e) { banner(e.message, true); }
  });
  view.append(el("div", { class: "grid" }, el("label", null, "EDS library folder", lib,
    hint("Optional. Found devices are matched against the EDS files here (and its subfolders) and in the project's canopen folder. Kept on this PC."))));
  if (!onlineSetup(view)) return;
  if (onlineIsSlave()) {
    view.append(el("div", { class: "toolbar" }, netPicker()),
      el("p", { class: "field-msg warning", dataset: { online: "scan-slave" } }, "Scanning needs a master network: on a slave network the plugin is one of the nodes. " +
        "Pick a master network, or see this device in the Online view."));
    return;
  }
  const progress = el("span", { class: "muted", dataset: { online: "scan-progress" }, "aria-live": "polite" });
  view.append(el("div", { class: "toolbar" }, netPicker(),
    el("button", { type: "button", class: "primary", dataset: { online: "scan" }, onclick: () => runScan(true) }, "Scan the bus"), progress),
  el("div", { id: "scan-result" }));
  view.append(detectSection());
  S.onlineOpen = true;
  if (S.scanResult) showScan(S.scanResult);
  else runScan(false);
  const d = (S.detect || {})[onlineNetwork() ?? ""];
  if (d) { showDetect(d); if (d.running) pollDetect(S.onlineSeq); }
}

// -- bit rate detection (add-raw-frames-bitrate-detect) ---------------------
// The plugin stops CANopen on the network, listens at each bit rate in
// listen-only mode and starts CANopen again. S.detect keeps the last answer
// per network for this page.

// The rates a sweep left out because the adapter cannot be set to them.
function skippedText(r) {
  const k = r.skipped_kbit || [];
  return k.length ? ` Not tried: ${k.map(kbitText).join(", ")} (the adapter cannot be set to ${k.length === 1 ? "it" : "them"}).` : "";
}
const SILENT_TEXT = "The bus was silent. A listening adapter sends no acknowledge, so frames only count when another device acknowledges them: with one device on the bus, add a second device or a second adapter in normal mode, or, with a USB adapter on the PC and nothing else on the bus, use the lone-device sweep (\"Only this device is on the bus\", --lone-device). A device that only sends its boot-up message: power-cycle it during the sweep, or run more rounds.";

function detectSection() {
  const local = S.online.target === "adapter";
  // On a USB adapter the sweep only listens (no CANopen of ours to stop): no Allow changes needed.
  const allow = local || !!(diagConfig() && diagConfig().allow_changes);
  const rounds = el("select", { "aria-label": "Rounds", dataset: { online: "detect-rounds" } },
    [1, 2, 3, 5, 10].map((n) => el("option", { value: n }, n === 1 ? "1 round" : `${n} rounds`)));
  // The lone-device sweep sends (normal mode, LSS query): Allow changes on the adapter connection.
  const loneAllow = local && !!(S.onlineLast && S.onlineLast.hello && S.onlineLast.hello.allow_changes);
  const lone = local ? loneBox() : null;
  if (lone && !loneAllow) {
    lone.querySelector("input").disabled = true;
    lone.title = ADAPTER_NO_CHANGES;
  }
  return el("fieldset", { dataset: { online: "detect-box" } }, el("legend", null, "Detect bit rate"),
    el("p", { class: "muted" }, local ?
      "Finds the bit rate of the traffic on the bus: the USB adapter listens at 1000, 800, 500, 250, 125, 50, 20 and 10 kbit/s for a second each in listen-only mode, without sending anything, then goes back to its bit rate." :
      "Finds the bit rate of the traffic on this network's bus: the runtime stops CANopen on the network, listens at 1000, 800, 500, 250, 125, 50, 20 and 10 kbit/s for a second each without sending anything, then starts CANopen again. Other networks keep running."),
    allow ? null : el("p", { class: "field-msg warning", dataset: { online: "detect-blocked" } }, "Detecting the bit rate needs Allow changes in Online access"),
    el("div", { class: "toolbar" },
      el("button", { type: "button", dataset: { online: "detect" }, disabled: !allow,
        onclick: () => runDetect(Number(rounds.value), !!lone && lone.querySelector("input").checked) }, "Detect bit rate"),
      rounds, lone),
    el("div", { id: "detect-result" }));
}

// The draft network the scan page acts on.
function detectNet() {
  const name = onlineNetwork();
  if (name === null) return S.config;
  return S.model.networks.find((n) => netName(n) === name) || null;
}

async function runDetect(rounds, alone) {
  if (alone) { if (await askLone()) await startDetect(rounds, false, false, true); return; }
  if (S.online.target === "adapter") { await startDetect(rounds, false); return; }  // listens only
  const name = onlineNetwork();
  const v = await modal(`Detect the bit rate${name ? " of network " + name : ""}? CANopen on that network stops during the sweep (about ${8 * rounds} s): the program's PDOs and SDOs on it stop, and the nodes boot again afterwards. The runtime only listens; nothing is sent on the bus.`,
    [["detect", "Detect bit rate", true], ["cancel", "Cancel"]]);
  if (v !== "detect") return;
  await startDetect(rounds, false);
}

async function startDetect(rounds, force, disturb, alone) {
  const seq = S.onlineSeq;
  const net = onlineNetwork() ?? "";
  S.detectArgs = { rounds, force, alone };
  let r;
  try {
    r = await api("POST", "/api/online/detect_bitrate", Object.assign({ port: diagPort(), rounds }, force ? { force: true } : {},
      disturb ? { disturb_bus: true } : {}, alone ? { lone_device: true } : {}));
  } catch (e) {
    if (e.body && e.body.force && !force) {
      const v = await modal(`The runtime says: "${e.message}". Stop CANopen on this network for the sweep anyway?`,
        [["force", "Detect anyway", true], ["cancel", "Cancel"]]);
      if (v === "force") return startDetect(rounds, true, disturb, alone);
      return;
    }
    if (e.body && e.body.disturb_bus && !disturb) {
      if (await askDisturb()) return startDetect(rounds, force, true, alone);
      return;
    }
    const box = $("#detect-result");
    if (box) box.replaceChildren(el("p", { class: "field-msg", dataset: { online: "detect-error" } }, `Not started: ${e.message}`));
    return;
  }
  S.detect = Object.assign(S.detect || {}, { [net]: r });
  if (seq !== S.onlineSeq || S.view !== "scan") return;
  showDetect(r);
  if (r.running) pollDetect(seq);
}

async function pollDetect(seq) {
  clearTimeout(S.detectTimer);
  S.detectTimer = setTimeout(async () => {
    if (seq !== S.onlineSeq || S.view !== "scan") return;
    const net = onlineNetwork() ?? "";
    let r;
    try { r = await api("POST", "/api/online/detect_bitrate_status", { port: diagPort() }); }
    catch (e) {
      if (seq === S.onlineSeq) banner(e.message, true);
      return pollDetect(seq);
    }
    if (seq !== S.onlineSeq || S.view !== "scan") return;
    S.detect = Object.assign(S.detect || {}, { [net]: r });
    showDetect(r);
    if (r.running) pollDetect(seq);
  }, 300);
}

function kbitText(k) { return k >= 1000 ? `${k / 1000} Mbit/s` : `${k} kbit/s`; }

function showDetect(r) {
  const box = $("#detect-result");
  if (!box) return;
  const parts = [];
  if (r.running) {
    parts.push(el("p", { class: "sweep-progress", dataset: { online: "detect-progress" } },
      r.lone_device ? `Trying ${kbitText(r.rate_kbit)} (${r.done} of ${r.total}) in normal mode with the LSS query…`
        : `Listening at ${kbitText(r.rate_kbit)} (${r.done} of ${r.total}${r.total > 8 ? `, round ${r.round}` : ""})… CANopen on this network is stopped until the sweep ends.`));
  } else if (r.verdict) {
    const net = detectNet();
    const current = net && net.adapter ? net.adapter.bitrate : undefined;
    let text;
    let cls = "bad";
    if (r.verdict === "detected") {
      cls = "ok-text";
      const who = S.online.target === "adapter" ? "the USB adapter is set to" : "the runtime is configured for";
      text = `${kbitText(r.bitrate_kbit)} detected` + (r.matches_config ? `, the bit rate ${who}.` :
        r.configured_kbit ? `; ${who} ${kbitText(r.configured_kbit)}.` : ".") + (r.warning ? ` ${upperFirst(r.warning)}.` : "");
    } else if (r.verdict === "ambiguous") {
      text = `Ambiguous: frames at ${(r.candidates || []).map(kbitText).join(", ")}. Run the sweep again, with more rounds.`;
    } else if (r.verdict === "silent") {
      text = r.lone_device ? "No answer at any bit rate: check the wiring, the termination and the device's power." : SILENT_TEXT;
      cls = "field-msg warning";
    } else if (needsDisturb(r.error)) {
      text = `The sweep stopped before listening. ${DISTURB_TEXT}`;
      cls = "field-msg warning";
    } else {
      text = `The sweep failed: ${r.error || "no reason given"}.`;
    }
    parts.push(el("p", { class: cls, dataset: { online: "detect-verdict" } }, text + skippedText(r)));
    if (r.verdict === "failed" && needsDisturb(r.error)) {
      parts.push(el("div", { class: "toolbar" }, el("button", { type: "button", dataset: { online: "detect-disturb" },
        onclick: async () => {
          const a = S.detectArgs || { rounds: 1, force: false };
          if (await askDisturb()) startDetect(a.rounds, a.force, true, a.alone);
        } }, "Sweep anyway")));
    }
    if (r.verdict === "detected" && net && r.bitrate_kbit * 1000 !== current) {
      parts.push(el("div", { class: "toolbar" }, el("button", { type: "button", class: "primary", dataset: { online: "use-bitrate" },
        onclick: () => {
          net.adapter = net.adapter || {};
          net.adapter.bitrate = r.bitrate_kbit * 1000;
          changed();
          banner(`Bit rate set to ${kbitText(r.bitrate_kbit)}${several() ? " on network " + netName(net) : ""}. Save and upload to use it.`);
          showDetect(r);
        } }, `Use ${r.bitrate_kbit} kbit/s`)));
    }
  }
  const rows = (r.results || []).map((x) => el("tr", { dataset: { detectRate: x.bitrate_kbit } },
    el("td", null, kbitText(x.bitrate_kbit)), el("td", null, String(x.frames)), el("td", null, String(x.error_frames)),
    el("td", { class: "mono" }, (x.ids || []).map((i) => "0x" + i.toString(16).toUpperCase()).join(" ") + ((x.ids || []).length >= 16 ? " …" : ""))));
  if (rows.length) {
    parts.push(el("table", { class: "scan", dataset: { online: "detect-table" } },
      el("thead", null, el("tr", null, thCells(["Bit rate", "Frames", "Error frames", "Identifiers"]))),
      el("tbody", null, rows)));
  }
  box.replaceChildren(...parts);
}

async function runScan(start) {
  const seq = S.onlineSeq;
  let r;
  try {
    r = await api("POST", "/api/online/scan", { start, config: fileConfig(), port: diagPort() });
  } catch (e) {
    if (seq === S.onlineSeq) banner(e.message, true);
    return;
  }
  if (seq !== S.onlineSeq || S.view !== "scan") return;
  runtimeNetworks(r);
  const progress = document.querySelector("[data-online=scan-progress]");
  if (r.running) {
    progress.textContent = `Scanning… ${r.done} of ${r.total} node IDs`;
    S.onlineTimer = setTimeout(() => runScan(false), 300);
    return;
  }
  if (!r.nodes) { progress.textContent = "No scan has run on this runtime yet."; return; }
  const note = r.note ? ` ${r.note.charAt(0).toUpperCase() + r.note.slice(1)}.` : "";
  progress.textContent = `Scanned ${String(r.finished_at || "").replace("T", " ").replace(/\.\d+Z$/, " UTC")} in ${Number(r.seconds || 0).toFixed(1)} s.${note}`;
  S.scanResult = r;
  showScan(r);
}

function showScan(r) {
  const box = $("#scan-result");
  if (!box) return;
  const rows = [];
  for (const d of r.nodes) {
    const m = d.eds_matches || [];
    const vendorName = m.length ? m[0].vendor_name : "";
    const cells = [String(d.node_id),
      d.vendor_id !== undefined ? hex8(d.vendor_id) + (vendorName ? " " + vendorName : "") : "",
      d.product_code !== undefined ? hex8(d.product_code) : "",
      d.revision_number !== undefined ? hex8(d.revision_number) : "",
      d.serial_number !== undefined ? `${d.serial_number} (${hex8(d.serial_number)})` : "",
      d.device_name || ""];
    const match = el("td", { class: d.match === "configured" ? "ok-text" : d.match === "not configured" ? null : "bad" },
      d.match + (d.config_name ? ` as ${d.config_name}` : ""));
    rows.push(el("tr", { dataset: { scanNode: d.node_id } }, cells.map((c) => el("td", null, c)), match,
      el("td", null, scanAction(d), useForNode(d))));
  }
  box.replaceChildren(el("table", { class: "scan" },
    el("thead", null, el("tr", null, thCells(["Node", "Vendor", "Product", "Revision", "Serial number", "Device name", "Match", ""]))),
    el("tbody", null, rows.length ? rows : [el("tr", null, el("td", { colspan: 8, class: "muted" }, "No device answered."))])));
}

function scanAction(d) {
  if (d.match === "configured, different device") {
    const fields = [["vendor_id", "Vendor ID"], ["product_code", "Product code"], ["revision_number", "Revision"], ["serial_number", "Serial number"]];
    const exp = d.expected || {};
    return el("table", { class: "compare", dataset: { online: "compare" } },
      el("thead", null, el("tr", null, el("th", null, ""), el("th", null, "Config"), el("th", null, "Found"))),
      el("tbody", null, fields.map(([k, label]) => el("tr", { class: exp[k] !== undefined && d[k] !== undefined && exp[k] !== d[k] ? "bad" : null },
        el("th", null, label), el("td", null, exp[k] !== undefined ? hex8(exp[k]) : "any"),
        el("td", null, d[k] !== undefined ? hex8(d[k]) : "-")))));
  }
  if (d.match !== "not configured") return "";
  if (configNode(d.node_id)) return el("span", { class: "muted" }, "added (not saved yet)");
  const m = d.eds_matches || [];
  if (S.state.commission) {  // no config to add to: only the object dictionary
    if (!m.length) return el("span", { class: "muted" }, "No matching EDS in the EDS library.");
    const pick = el("select", { "aria-label": "EDS file", dataset: { online: "eds-match" } }, m.map((x, k) => el("option", { value: k }, x.name)));
    return el("div", null, pick, el("button", { type: "button", dataset: { online: "open-od" }, onclick: () => openScannedOd(d, m[Number(pick.value)]) }, "Object dictionary"));
  }
  if (!m.length) {
    const input = el("input", { type: "file", accept: ".eds,.EDS" });
    input.addEventListener("change", () => { const f = input.files[0]; if (f) addScannedNode(d, null, f, false); });
    return el("div", null, el("span", { class: "muted" }, "No matching EDS. "),
      el("label", { class: "file-button" }, "Pick EDS file…", input));
  }
  const sel = el("select", { "aria-label": "EDS file", dataset: { online: "eds-match" } }, m.map((x, k) =>
    el("option", { value: k }, `${x.name} (${x.where === "project" ? "project" : "library"}, revision ${x.revision_number !== null ? hex8(x.revision_number) : "?"}${x.revision_match ? ", exact" : ""})`)));
  const ident = el("input", { type: "checkbox" });
  return el("div", null, sel, el("label", { class: "inline" }, ident, " also check revision and serial number"),
    el("button", { type: "button", dataset: { online: "add-node" }, onclick: () => addScannedNode(d, m[Number(sel.value)], null, ident.checked) }, "Add as node"),
    el("button", { type: "button", dataset: { online: "open-od" }, onclick: () => openScannedOd(d, m[Number(sel.value)]) }, "Object dictionary"));
}

// A scanned device that is not in the configuration, opened in the online
// view's object dictionary and parameters tabs with the matching EDS.
function openScannedOd(d, match) {
  Object.assign(commDevice(), { node_id: d.node_id, vendor_id: d.vendor_id, product_code: d.product_code, revision_number: d.revision_number,
    serial_number: d.serial_number, eds_path: match.path, eds_name: match.name });
  stepDone("identity", `${hex8(d.vendor_id)} / ${hex8(d.product_code)}, ${match.name}`);
  S.onlineEds = Object.assign(S.onlineEds || {}, { [d.node_id]: match.path });
  S.onlineEdsName = Object.assign(S.onlineEdsName || {}, { [d.node_id]: d.device_name || match.name });
  S.onlineNode = d.node_id;
  S.onlineTab = "od";
  showView("online");
}

async function addScannedNode(d, match, file, identity, lss) {
  let res;
  try {
    if (match) {
      res = await api("POST", "/api/online/use_eds", { path: match.path, eds_lint: edsLint() });
    } else {
      const data = await new Promise((resolve, reject) => {
        const r = new FileReader();
        r.onload = () => resolve(r.result.split(",")[1] || "");
        r.onerror = () => reject(r.error);
        r.readAsDataURL(file);
      });
      res = await api("POST", "/api/eds", { name: file.name, data, on_conflict: "keep_both", eds_lint: edsLint() });
    }
  } catch (e) { banner(e.message, true); return; }
  S.state.eds = S.state.eds || {};
  S.state.eds[res.name] = res.summary;
  const base = (d.device_name || res.name.replace(/\.eds$/i, "")).replace(/[^A-Za-z0-9_]+/g, "_").toLowerCase().replace(/^_+|_+$/g, "");
  const node = { node_id: d.node_id, name: base || "node" + d.node_id, eds: res.name };
  if (identity) {
    if (d.revision_number) node.revision_number = d.revision_number;
    if (d.serial_number) node.serial_number = d.serial_number;
  }
  if (lss) {
    node.serial_number = d.serial_number;
    node.lss = { assign: true };
  }
  S.config.nodes = S.config.nodes || [];
  S.config.nodes.push(node);
  // The new node's page opens, with a way back to the scan (its results stay).
  S.view = "node:" + (S.config.nodes.length - 1);
  S.focusName = S.config.nodes.length - 1;
  banner(el("div", null, el("div", null, `Added node ${d.node_id} (${res.name}). Map its PDOs here, then save. `,
    el("button", { type: "button", class: "link", dataset: { online: "back-to-scan" }, onclick: () => showView("scan") }, "Back to the scan")),
  importReport(res)));
  changed(true);
}

// "Use for node…": a scanned device with a serial number replaces the device
// of a configured node with the same vendor ID and product code; the node
// gets its serial number and LSS assignment.
function useForNode(d) {
  if (d.serial_number === undefined || d.vendor_id === undefined || d.product_code === undefined) return null;
  const nodes = (S.config.nodes || []).map((n, i) => [n, i]).filter(([n]) => {
    const dev = (edsFor(n) || {}).device;
    if (!dev || dev.vendor_id !== d.vendor_id || dev.product_code !== d.product_code) return false;
    // Not the node this device already is.
    return !(num(n.node_id) === d.node_id && (d.match === "configured" || num(n.serial_number) === d.serial_number));
  });
  if (!nodes.length) return null;
  const sel = el("select", { "aria-label": "Node", dataset: { online: "use-for" } },
    el("option", { value: "" }, "Use for node…"),
    nodes.map(([n, i]) => el("option", { value: i }, `Node ${n.node_id}${n.name ? " " + n.name : ""}`)));
  sel.addEventListener("change", () => {
    if (sel.value === "") return;
    const i = Number(sel.value);
    const base = `nodes[${i}]`;
    setPath(base + ".serial_number", d.serial_number);
    setPath(base + ".lss", Object.assign({}, getPath(base + ".lss") || {}, { assign: true }));
    if (getPath(base + ".reset_communication") === false) setPath(base + ".reset_communication", undefined);
    const id = getPath(base + ".node_id");
    changed(false);
    banner(`Node ${id} now expects serial number ${hex8(d.serial_number)} and assigns its node ID by LSS: ` +
      `the device becomes node ${id} at the next PLC start (save and upload first).`);
    if (S.scanResult) showScan(S.scanResult);
  });
  return sel;
}

// ---------------------------------------------------------------------------
// Edits

async function addNodeFromEds(file) {
  const data = await new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(r.result.split(",")[1] || "");
    r.onerror = () => reject(r.error);
    r.readAsDataURL(file);
  });
  let res;
  try {
    res = await api("POST", "/api/eds", { name: file.name, data, eds_lint: edsLint() });
  } catch (e) {
    if (e.status === 409 && e.body.conflict) {
      const v = await modal(e.message + ". Replace it, or keep both under a new name?",
        [["cancel", "Cancel"], ["replace", "Replace", { danger: true }], ["keep_both", "Keep both", true]]);
      if (!v || v === "cancel") return;
      res = await api("POST", "/api/eds", { name: file.name, data, on_conflict: v, eds_lint: edsLint() });
    } else {
      banner(e.message, true);
      return;
    }
  }
  S.state.eds = S.state.eds || {};
  S.state.eds[res.name] = res.summary;
  const used = new Set([num(S.config.master && S.config.master.node_id), ...(S.config.nodes || []).map((n) => num(n.node_id))]);
  let id = 2;
  while (used.has(id) && id < 127) id++;
  const stem = res.name.replace(/\.eds$/i, "").replace(/[^A-Za-z0-9_]+/g, "_").toLowerCase();
  S.config.nodes = S.config.nodes || [];
  S.config.nodes.push({ node_id: id, name: stem, eds: res.name });
  S.view = "node:" + (S.config.nodes.length - 1);
  S.focusName = S.config.nodes.length - 1;
  banner(importReport(res));
  changed(true);
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
  const [e] = pdos[j].entries.splice(k, 1);
  if (!pdos[j].entries.length && j === pdos.length - 1) pdos.pop();
  changed(true);
  removedBanner(`${e.index}:${e.subindex ?? 0} from ${key === "tx_pdos" ? "TPDO" : "RPDO"} ${pdos[j] ? pdos[j].number ?? j + 1 : j + 1}`);
}

function moveEntry(i, key, j, k, to) {
  const pdos = S.config.nodes[i][key];
  const [e] = pdos[j].entries.splice(k, 1);
  if (to === "new") pdos.push({ entries: [e] });
  else pdos[Number(to)].entries.push(e);
  changed(true);
}

async function removeNode(i) {
  const n = S.config.nodes[i];
  const v = await modal(`Remove node ${n.node_id} ${n.name || ""}? Its EDS file stays in the folder.`,
    [["cancel", "Keep the node"], ["remove", "Remove node", { danger: true }]]);
  if (v !== "remove") return;
  S.config.nodes.splice(i, 1);
  S.supervision = {};
  S.view = "bus";
  changed(true);
  removedBanner(`node ${n.node_id} ${n.name || ""}`.trim());
}

async function addSdo(i, index, subindex) {
  const n = S.config.nodes[i];
  const eds = edsFor(n);
  const ix = num(index), sx = num(String(subindex));
  if (isNaN(ix) || ix > 0xFFFF || isNaN(sx) || sx > 255) { banner("Give the index as 0x… and the subindex as 0–255.", true); return; }
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
  n.sdo.push({ index: hex4(ix), subindex: sx, type, value });
  banner("");
  changed(true);
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
      task_interval: S.taskInterval || undefined });
    if (seq !== S.checkSeq) return;
    S.check = normCheck(r, fileVersion(cfg));
    if (S.view === "declarations") render(); else applyCheck();
  } catch (e) {
    banner(e.message, true);
  }
  if (seq === S.checkSeq) document.body.dataset.checking = "0";
}

// The open tab's network name when the draft has several (exports name it).
function tabNetwork() { return several() ? netName(S.config) : null; }

// Exports the draft (saved or not) as CiA 306 DCF files: one node's file,
// or every node's in a zip. With several networks: the open tab's nodes, or
// every network in a folder per network. Problems go to the Problems pane,
// and nothing is downloaded.
async function exportDcf(nodeId, network) {
  const one = nodeId !== undefined;
  if (one && !Number.isInteger(nodeId)) { banner("Give the node a node ID first.", true); return; }
  if (!one && several()) {
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
    if (r.errors) {
      S.check = exportProblems(r, cfg);
      applyCheck();
      banner(`DCF export stopped: ${r.errors} problem${r.errors === 1 ? "" : "s"} (see Problems). Nothing was downloaded.`, true);
      return;
    }
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
    const r = await api("POST", "/api/export_html", { config: cfg });
    exportCheck(r, cfg);
    if (r.errors) {
      banner(`Documentation export stopped: ${r.errors} problem${r.errors === 1 ? "" : "s"} (see Problems). Nothing was downloaded.`, true);
      return;
    }
    const bytes = Uint8Array.from(atob(r.data), (c) => c.charCodeAt(0));
    const url = URL.createObjectURL(new Blob([bytes], { type: r.content_type }));
    const a = el("a", { href: url, download: r.name });
    document.body.append(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 10000);
    banner(`Exported ${r.name}${r.items.length ? ` with ${r.items.length} warning${r.items.length === 1 ? "" : "s"} (see Problems)` : ""}.`);
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
    const body = { config: cfg, sdo: $("#dbc-sdo").value };
    if (several()) body.network = netName(S.config);
    const r = await api("POST", "/api/export_dbc", body);
    exportCheck(r, cfg);
    if (r.errors) {
      banner(`DBC export stopped: ${r.errors} problem${r.errors === 1 ? "" : "s"} (see Problems). Nothing was downloaded.`, true);
      return;
    }
    const bytes = Uint8Array.from(atob(r.data), (c) => c.charCodeAt(0));
    const url = URL.createObjectURL(new Blob([bytes], { type: r.content_type }));
    const a = el("a", { href: url, download: r.name });
    document.body.append(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 10000);
    banner(`Exported ${r.name}${r.items.length ? ` with ${r.items.length} warning${r.items.length === 1 ? "" : "s"} (see Problems)` : ""}.`);
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
  const prev = S.check || {};
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
  } else if (prevErrors) {
    scheduleCheck();
  }
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
  for (const x of document.querySelectorAll(".decl")) {
    const name = declaredAs(x.dataset.declFor);
    x.textContent = name ? ` declared as ${name}` : "";
  }
  const list = $("#problem-list");
  const focused = document.activeElement && document.activeElement.closest("#problem-list li");
  const focusedAt = focused ? [...list.children].indexOf(focused) : -1;
  list.replaceChildren();
  const items = (S.check && S.check.items) || [];
  for (const it of items) {
    const where = it.where || (it.paths || []).map((p) => ({ net: S.net, path: p }));
    const li = el("li", { class: it.level }, el("button", { type: "button", title: it.message,
      onclick: () => focusPath(where[0]) }, problemText(it, where[0])));
    list.append(li);
    for (const w of where) {
      // Fields of another network's tab are not on the page.
      if (w.net !== null && w.net !== S.net) continue;
      const p = w.path;
      const input = document.querySelector(`[data-path="${CSS.escape(p)}"]`);
      if (input && (input.tagName === "INPUT" || input.tagName === "SELECT")) input.classList.add(it.level === "error" ? "invalid" : "warned");
      const msg = document.querySelector(`.field-msg[data-for="${CSS.escape(p)}"]`);
      if (msg) {
        msg.textContent = (msg.textContent ? msg.textContent + " " : "") + readable(it.message);
        msg.classList.toggle("warning", it.level !== "error");
      }
    }
  }
  if (!items.length && S.check) list.append(el("li", { class: "ok" }, "No problems."));
  if (focusedAt >= 0) { const b = list.children[Math.min(focusedAt, list.children.length - 1)]; if (b && b.firstChild && b.firstChild.focus) b.firstChild.focus(); }
  // The overlap override goes with the overlap errors, and stays while ticked.
  const overlaps = items.some((it) => it.overlap || it.overlap_allowed);
  $("#overlap-box").hidden = !(S.state && S.state.mode === "project" && (overlaps || $("#allow-overlap").checked));
  fillCounts(countProblems());
  updateSave();
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
  for (const b of document.querySelectorAll("#node-list [data-node]")) {
    const k = c.counts[b.dataset.node];
    const span = b.querySelector(".count");
    if (span) span.textContent = k ? `${k} error${k === 1 ? "" : "s"}` : "";
  }
  for (const tab of document.querySelectorAll("#net-bar [data-net]")) {
    const k = c.netErrors[tab.dataset.net];
    const span = tab.querySelector(".count");
    if (span) span.textContent = k ? String(k) : "";
  }
}

// A check message without the parts meant for the command line: the file
// name, the config path ("nodes[2]: tx_pdos[1]: entries[0]: ") and the node
// the place label already names.
function readable(m) {
  let t = m.replace(/^[^:]*canopen\.json: /, "");
  while (/^[a-z_]+(\[\d+\])?(\.[a-z_]+(\[\d+\])?)*: /.test(t)) t = t.replace(/^[^:]*: /, "");
  t = t.replace(/^node \d+( \([^)]*\))?(, |: )/, "");
  t = t.replace(/^object (0x[0-9A-Fa-f]+:\d+): /, "$1: ");
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
  rest = rest.replace(/^[^:\s]*canopen\.json: /, "");
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

// "Node 5 rtd, TPDO 2, 0x6150:1: type UNSIGNED8 ...", with the network first
// when the draft has several.
const NO_NODES_TEXT = "No nodes yet. Add a node from its EDS, or turn on Online access for a scan-only configuration.";

function problemText(it, w) {
  const where = placeOf(w);
  if (/field 'nodes' lists no slave nodes/.test(it.message)) return where.length ? `${where.join(", ")}: ${NO_NODES_TEXT}` : NO_NODES_TEXT;
  let text = readable(it.message);
  if (!where.length) return text;
  const obj = /^(0x[0-9A-Fa-f]+:\d+): /.exec(text);
  if (obj) {
    if (where[where.length - 1] !== obj[1]) where.push(obj[1]);
    text = text.slice(obj[0].length);
  }
  return `${where.join(", ")}: ${text}`;
}

// Where a check path ({ net, path }) is, in the page's words:
// ["Node 5 rtd", "TPDO 2"], led by "Network io" when there are several.
function placeOf(w) {
  if (!w || !w.path) return [];
  const net = w.net === null ? null : S.model.networks[w.net];
  const lead = several() && net ? [`Network ${netLabel(net, w.net)}`] : [];
  const path = w.path;
  if (path.startsWith("master.diagnostics")) return ["Online access"];
  if (path.startsWith("gateway")) {
    const r = /^gateway\.routes\[(\d+)\]/.exec(path);
    const rt = r && ((S.model.top.gateway || {}).routes || [])[Number(r[1])];
    return ["Gateway"].concat(rt ? [`route ${rt.name || Number(r[1]) + 1}`] : []);
  }
  if (!net) return [];
  if (path.startsWith("slave")) {
    const o = /^slave\.objects\[(\d+)\]/.exec(path);
    const b = o && ((net.slave || {}).objects || [])[Number(o[1])];
    return lead.concat(["Slave device"], b ? [`${b.index}:${b.subindex ?? 0}`] : []);
  }
  if (path.startsWith("adapter")) return lead.concat(["CAN adapter"]);
  if (path.startsWith("master")) return lead.concat(["Master"]);
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

function focusPath(w) {
  if (!w || !w.path) return;
  if (w.net !== null && w.net !== S.net && S.model.networks[w.net]) switchNet(w.net);
  const path = w.path;
  const m = /^nodes\[(\d+)\]/.exec(path);
  const want = m ? "node:" + m[1] : path.startsWith("gateway") ? "gateway"
    : (path.startsWith("adapter") || path.startsWith("master") || path.startsWith("slave") || path === "role" ? "bus" : S.view);
  if (want !== S.view) showView(want);
  const target = document.querySelector(`[data-path="${CSS.escape(path)}"]`);
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
function updateSave() {
  const btn = $("#btn-save");
  if (btn.dataset.busy) return;
  const errors = S.check ? S.check.errors : 0;
  const allowed = !$("#overlap-box").hidden && $("#allow-overlap").checked;
  btn.disabled = errors > 0 || !S.dirty;
  btn.title = errors ? `${errors} error${errors === 1 ? "" : "s"} in Problems` : S.dirty ? "" : "No unsaved changes";
  btn.textContent = allowed && S.dirty ? "Save (overlaps allowed)" : (S.dirty ? "Save" : "Saved");
}

async function save(overwrite) {
  const cfg = fileConfig();
  try {
    const r = await api("POST", "/api/save", { config: cfg, allow_overlap: $("#allow-overlap").checked, overwrite: !!overwrite });
    S.state = r.state;
    setModel(S.state.config);
    S.dirty = false;
    await checkToken();
    render();
    // After render: a test (or a quick user) acting on "Saved" acts on the new page.
    banner("Saved " + r.written.join(", "));
    runCheck();
  } catch (e) {
    if (e.status === 409 && e.body.changed_on_disk) {
      const v = await modal("canopen.json changed on disk after it was loaded here (edited elsewhere?).",
        [["cancel", "Cancel"], ["reload", "Reload from disk"], ["overwrite", "Overwrite it", { danger: true }]]);
      if (v === "overwrite") return save(true);
      if (v === "reload") return reload(true);
    } else if (e.status === 422 && e.body.check) {
      S.check = exportProblems(e.body.check, cfg);
      applyCheck();
      banner(e.message, true);
    } else {
      banner(e.message, true);
    }
  }
}

// Whether anything on the page would be lost: draft edits, the simulation
// file, or a recording that was neither saved nor downloaded.
function unsavedWork() {
  return S.dirty || (typeof simDirty === "function" && simDirty()) || (typeof traceUnsaved === "function" && traceUnsaved());
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
  S.browserPath = null;
  // The closed folder's scan and online picks are not the next one's: a
  // device commissioned next showed the project's nodes as configured.
  S.scanResult = null;
  S.onlineNet = null;
  S.onlineNode = null;
  S.onlineEds = null;
  S.onlineEdsName = null;
  S.lssDevice = null;
  await loadState();
}

async function moveIntoProject() {
  if (S.dirty) { banner("Save the config before moving it into a project.", true); return; }
  const input = el("input", { type: "text", spellcheck: "false", "aria-label": "Editor project folder", class: "wide" });
  input.value = S.state.home;
  const v = await modal("Editor project folder to copy this config into (its canopen/ folder):",
    [["move", "Move into project", true], ["cancel", "Cancel"]], input);
  if (v !== "move") return;
  const project = input.value.trim();
  let r;
  try {
    r = await api("POST", "/api/move", { project });
  } catch (e) {
    if (e.status === 409 && e.body.exists) {
      const w = await modal(`${project} already has a canopen folder. Replace it?`, [["cancel", "Cancel"], ["replace", "Replace", { danger: true }]]);
      if (w !== "replace") return;
      try { r = await api("POST", "/api/move", { project, replace: true }); } catch (e2) { banner(e2.message, true); return; }
    } else { banner(e.message, true); return; }
  }
  S.state = r.state;
  setModel(S.state.config);
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
  const [nl, name] = field("Project name (its folder)", "", "Project name");
  const [il, interval] = field("Task interval", "T#20ms", "Task interval");
  const sdoBlocks = el("input", { type: "checkbox", "aria-label": "Enable CANopen SDO blocks", dataset: { newProject: "sdo-blocks" } });
  const sl = el("label", { class: "inline", title: "Enables the openplc_canopen library (CO_SDO_READ, CO_SDO_WRITE, ...) in the project and installs it into the editor" },
    sdoBlocks, " Enable CANopen SDO blocks");
  const form = el("div", { class: "new-project" }, pl, nl, il, sl,
    el("p", { class: "hint" }, "The program main declares every CANopen location once. Later config changes do not " +
      "change it: declare new locations from Variable declarations."));
  let text = "New OpenPLC Editor project (target OpenPLC Runtime v4) with this config in its canopen/ folder:";
  for (;;) {
    const v = await modal(text, [["create", "Create project", true], ["cancel", "Cancel"]], form);
    if (v !== "create") return;
    let r;
    try {
      r = await api("POST", "/api/new_project", { parent: parent.value.trim(), name: name.value.trim(),
        interval: interval.value.trim(), sdo_blocks: sdoBlocks.checked });
    } catch (e) {
      text = "Not created: " + e.message;
      continue;
    }
    S.state = r.state;
    setModel(S.state.config);
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
  for (const b of document.querySelectorAll("[data-theme-choice]")) {
    b.onclick = async () => {
      showTheme(b.dataset.themeChoice);
      try { await api("POST", "/api/ui", { theme: b.dataset.themeChoice }); } catch (e) { banner(e.message, true); }
    };
  }
}

// In a narrow window the Problems pane is a strip under the header that
// opens on request; in a wide one it is always open.
const NARROW = window.matchMedia("(max-width: 1100px)");
function wireProblems() {
  const box = $("#problems-box");
  const fit = () => { box.open = !NARROW.matches; };
  fit();
  NARROW.addEventListener("change", fit);
  box.querySelector("summary").addEventListener("click", (e) => { if (!NARROW.matches) e.preventDefault(); });
  // The message bar sits under the header, which wraps on narrow windows.
  new ResizeObserver(() => document.documentElement.style.setProperty("--header-h", $("#top").offsetHeight + "px")).observe($("#top"));
}

// ---------------------------------------------------------------------------

function wire() {
  $("#start-project").onclick = () => { S.startMode = "project"; renderStart(); };
  $("#start-standalone").onclick = () => { S.startMode = "standalone"; renderStart(); };
  $("#start-new").onclick = () => { S.startMode = "new"; renderStart(); };
  $("#start-commission").onclick = commissionDevice;
  $("#browser-go").onclick = () => browse($("#browser-path").value.trim());
  $("#browser-path").addEventListener("keydown", (e) => { if (e.key === "Enter") browse($("#browser-path").value.trim()); });
  $("#browser-open").onclick = startOpen;
  // busy() restores the caption it found ("Save"); the button's real state follows the save.
  $("#btn-save").onclick = () => busy($("#btn-save"), "Saving…", () => save(false)).then(updateSave);
  const exporting = (id, fn) => { $(id).onclick = () => busy($(id), "Exporting…", fn); };
  exporting("#btn-export-all", () => exportDcf());
  exporting("#btn-export-node", () => {
    const n = S.view.startsWith("node:") ? S.config.nodes[Number(S.view.slice(5))] : null;
    return n ? exportDcf(n.node_id, tabNetwork()) : undefined;
  });
  exporting("#btn-export-dbc", exportDbc);
  exporting("#btn-export-html", exportHtml);
  wireDbc();
  wireMenus();
  $("#btn-reload").onclick = () => reload(false);
  $("#btn-close").onclick = closeFolder;
  $("#btn-move").onclick = () => busy($("#btn-move"), "Moving…", moveIntoProject);
  $("#btn-new-project").onclick = () => busy($("#btn-new-project"), "Creating…", newEditorProject);
  $("#allow-overlap").onchange = runCheck;
  $("#eds-input").addEventListener("change", (e) => {
    const f = e.target.files[0];
    e.target.value = "";
    if (f) busy($("#eds-input").closest("label"), "Adding…", () => addNodeFromEds(f));
  });
  for (const b of document.querySelectorAll("#side .nav-item")) b.onclick = () => showView(b.dataset.view);
  $("#banner-close").onclick = () => banner("");
  $("#modal").addEventListener("cancel", () => { const r = modalResolve; modalResolve = null; if (r) r(null); });
  document.addEventListener("keydown", undoKeys);
  wireTheme();
  wireProblems();
  window.addEventListener("beforeunload", (e) => {
    if (unsavedWork()) { e.preventDefault(); e.returnValue = ""; }
  });
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
      if (m.open) for (const o of menus) if (o !== m) close(o);
    });
    m.addEventListener("keydown", (e) => {
      const items = [...m.querySelectorAll(".item")].filter((b) => !b.disabled && b.offsetParent !== null);
      const k = items.indexOf(document.activeElement);
      if (e.key === "Escape") { e.preventDefault(); close(m); m.querySelector("summary").focus(); }
      else if (e.key === "ArrowDown" || (e.key === "ArrowUp" && k < 0)) { e.preventDefault(); if (!m.open) m.open = true; (items[k + 1] || items[0]).focus(); }
      else if (e.key === "ArrowUp") { e.preventDefault(); (items[k - 1] || items[items.length - 1]).focus(); }
    });
    for (const b of m.querySelectorAll(".item")) b.addEventListener("click", () => close(m));
  }
  document.addEventListener("click", (e) => {
    for (const m of menus) if (m.open && !m.contains(e.target)) close(m);
  });
}

wire();
loadState().catch((e) => banner(e.message, true));
