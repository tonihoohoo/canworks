"use strict";
// The network tree (network-tree-and-node-tabs): the only navigation of a
// config's workspace tab. Every network at once, with its Bus and master,
// nodes, PDO links and CAN messages; the config-wide Online access, Gateway
// and Modbus bridge after them. Each entry carries its problem counts; a
// node its simulated or absent mark. Follows the WAI-ARIA tree view pattern:
// one tab stop, arrow keys, type-ahead. Loaded after app.js.

// Which networks the user folded, by name (or "#<index>" without one); kept on this PC.
S.treeFolded = S.treeFolded || new Set();

function netKey(net, k) { return netName(net) || "#" + k; }

// The entry an open page is: "<net>:bus", "<net>:node:<i>", "<net>:raw",
// "<net>:links", "access", "gateway", "bridge"; Commission: "<net>" or
// "<net>:node:<i>".
function selectedEntry() {
  if (workspace() === "commission") {
    const k = S.net;
    const id = S.onlineNode;
    if (id !== null && id !== undefined) {
      const i = (S.config.nodes || []).findIndex((n) => num(n.node_id) === id);
      if (i >= 0) return `${k}:node:${i}`;
    }
    return String(k);
  }
  const v = S.wsView && isTool(S.view) ? S.wsView.configure : S.view;
  if (v === "access" || v === "gateway" || v === "bridge") return v;
  if (v && v.startsWith("node:")) return `${S.net}:${v}`;
  if (v === "bus" || v === "raw" || v === "links") return `${S.net}:${v}`;
  return `${S.net}:bus`;
}

// The tree's place of a check path ({ net, path }): [entry, node tab or null].
function entryOfPath(w) {
  const path = typeof w.path === "string" ? w.path : "";
  if (path.startsWith("master.diagnostics") || path.startsWith("master.cia309") || (w.net === null && path.startsWith("cia309"))) return ["access", null];
  if (path.startsWith("gateway")) return ["gateway", null];
  if (path.startsWith("bridge")) return ["bridge", null];
  if (w.net === null || w.net === undefined) return [null, null];
  const k = w.net;
  const m = /^nodes\[(\d+)\](?:\.(.*))?$/.exec(path);
  if (m) return [`${k}:node:${m[1]}`, nodeTabOfPath(m[2] || "")];
  if (path.startsWith("raw")) return [`${k}:raw`, null];
  if (path.startsWith("links")) return [`${k}:links`, null];
  if (path.startsWith("adapter") || path.startsWith("master") || path.startsWith("slave") || path.startsWith("j1939") ||
    path === "role" || path === "protocol" || path === "name") return [`${k}:bus`, null];
  return [String(k), null];
}

// The node tab that holds a node's key (the part after "nodes[i].").
const SUPERVISION_KEYS = /^(heartbeat(?!_consumer)|guard|life|status_location|state_location|nmt_command_location|boot_error_location|emcy|error_register_location|supervision)/;
function nodeTabOfPath(rest) {
  if (/^(tx_pdos|rx_pdos)/.test(rest)) return "pdos";
  if (/^(sdo|sdo_variables)(\[|$|\.)/.test(rest)) return "sdos";
  if (SUPERVISION_KEYS.test(rest)) return "supervision";
  if (/^axis/.test(rest)) return "cia402";
  if (rest === "" || /^(node_id|name|eds|simulate)$/.test(rest)) return "general";
  return "advanced";
}

// Problem counts per entry and per node tab: { "<entry>": { e, w }, "<entry>/<tab>": { e, w } }.
function treeCounts() {
  const out = {};
  const add = (key, level) => {
    const c = out[key] || (out[key] = { e: 0, w: 0 });
    if (level === "error") c.e++; else c.w++;
  };
  for (const it of (S.check && S.check.items) || []) {
    const keys = new Set();
    for (const w of it.where || []) {
      const [entry, tab] = entryOfPath(w);
      if (entry === null) continue;
      keys.add(entry);
      if (tab) keys.add(`${entry}/${tab}`);
    }
    for (const k of keys) add(k, it.level);
  }
  return out;
}

// "2✕ 1⚠" with "2 errors, 1 warning" for assistive technology; null without problems.
function badge(c) {
  if (!c || (!c.e && !c.w)) return null;
  const words = [c.e ? `${c.e} error${c.e === 1 ? "" : "s"}` : "", c.w ? `${c.w} warning${c.w === 1 ? "" : "s"}` : ""].filter(Boolean).join(", ");
  return el("span", { class: "tree-badge", dataset: { badge: words }, title: words },
    c.e ? el("span", { class: "err", "aria-hidden": "true" }, Icons.stateIcon("error", { label: false }), String(c.e)) : null,
    c.w ? el("span", { class: "warn", "aria-hidden": "true" }, Icons.stateIcon("warning", { label: false }), String(c.w)) : null,
    el("span", { class: "visually-hidden" }, words));
}

function sumCounts(counts, prefix) {
  const c = { e: 0, w: 0 };
  for (const [k, v] of Object.entries(counts)) {
    if (k.includes("/")) continue;
    if (k === prefix || k.startsWith(prefix + ":")) { c.e += v.e; c.w += v.w; }
  }
  return c;
}

// The state icon inside a node's .tree-mark (visual-refresh): the mark's class
// names the state (the live classes of liveMark() while connected, or "sim" /
// "absent" from the config); "sim" adds the simulated ring, "flag" the
// diagnosis flag, and a scan difference a warning or error icon. No class, no icon.
const LIVE_MARK = { "st-op": "operational", "st-preop": "preop", "st-stop": "stopped", "st-lost": "error", "st-unheard": "unknown", absent: "unknown" };
function markIcons(mark) {
  const parts = String(mark || "").split(/\s+/).filter(Boolean);
  const sim = parts.includes("sim");
  const state = parts.map((p) => LIVE_MARK[p]).find(Boolean) || (sim ? "unknown" : null);
  if (!state) return [];
  const out = [Icons.stateIcon(state, { label: false, simulated: sim, flag: parts.includes("flag") ? "pending" : null })];
  if (parts.includes("cmp-identity_differs")) out.push(Icons.stateIcon("warning", { label: false }));
  if (parts.includes("cmp-missing")) out.push(Icons.stateIcon("error", { label: false }));
  return out;
}
function fillMark(span, mark) {
  span.replaceChildren(...markIcons(mark));
  return span;
}

// A node's mark: hollow when simulated, dashed when absent from a simulated network.
function nodeMark(n, net) {
  const set = S.nodeMarks && S.nodeMarks[`${netName(net)}/${num(n.node_id)}`];
  if (set) return set;
  if (nodeSimulated(n, net)) return ["sim", "simulated"];
  if (simNetwork(net)) return ["absent", "absent"];
  return ["", ""];
}

// Sets the mark of a node's tree entry from outside the tree (the live
// state while connected, from commission-workspace): `mark` is a CSS class
// of .tree-mark and `word` its spoken name; null clears it back to the
// config's own mark. Only that entry's mark changes.
function setNodeMark(network, nodeId, mark, word) {
  S.nodeMarks = S.nodeMarks || {};
  const key = `${network}/${nodeId}`;
  if (mark === null || mark === undefined) delete S.nodeMarks[key]; else S.nodeMarks[key] = [mark, word || ""];
  if (!S.model) return;
  const k = S.model.networks.findIndex((n) => netName(n) === network);
  const net = S.model.networks[k];
  if (!net) return;
  const i = (net.nodes || []).findIndex((n) => num(n.node_id) === nodeId);
  const li = i < 0 ? null : document.querySelector(`#tree [data-key="${k}:node:${i}"]`);
  if (!li) return;
  const [m, w] = nodeMark(net.nodes[i], net);
  const span = li.querySelector(".tree-mark");
  if (span) { span.className = "tree-mark " + m; fillMark(span, m); if (w) span.dataset.simBadge = w; else delete span.dataset.simBadge; }
  const hidden = li.querySelector(".name .visually-hidden");
  if (hidden) hidden.textContent = w ? ` (${w})` : "";
  else if (w) li.querySelector(".name").append(el("span", { class: "visually-hidden" }, ` (${w})`));
}

function protocolText(net) {
  return isJ1939(net) ? "J1939" : isPlain(net) ? "Plain CAN" : isSlave(net) ? "CANopen slave" : "CANopen master";
}

function busLabel(net) {
  return isJ1939(net) ? "Bus and ECU" : isPlain(net) || isSlave(net) ? "Bus" : "Bus and master";
}

// The entries as a nested list: [{ key, label, level, kids, attrs, ... }].
function treeModel() {
  const commission = workspace() === "commission";
  const nets = S.model.networks;
  const out = [];
  nets.forEach((net, k) => {
    if (commission && (isJ1939(net) || isPlain(net))) {
      out.push({ key: String(k), label: netLabel(net, k), sub: protocolText(net), net: k, kids: [], attrs: { net: k } });
      return;
    }
    const kids = [];
    if (!commission) kids.push({ key: `${k}:bus`, label: busLabel(net), attrs: { view: "bus", net: k } });
    if (isSlave(net) && !commission) {
      const s = net.slave || {};
      kids.push({ key: `${k}:bus`, alias: true, label: `${s.node_id === null ? "LSS" : s.node_id ?? "?"} slave (this PLC)`, attrs: { slave: "1", net: k } });
    }
    const nodes = (net.nodes || []).map((n, i) => [n, i]);
    nodes.sort((a, b) => (num(a[0].node_id) || 999) - (num(b[0].node_id) || 999));
    for (const [n, i] of nodes) {
      const [mark, word] = nodeMark(n, net);
      kids.push({ key: `${k}:node:${i}`, label: `${n.node_id ?? "?"} ${n.name || ""}`.trim(), mark, word,
        attrs: { node: i, net: k } });
    }
    if (!commission) {
      if (!isSlave(net) && !isJ1939(net) && !isPlain(net)) {
        if (!nodes.length) kids.push({ key: `${k}:empty`, label: "No nodes yet", muted: true, attrs: { empty: "1", net: k } });
        kids.push({ key: `${k}:add`, label: "+ Add node…", action: true, attrs: { action: "add-node", net: k } });
      }
      if (linksNetwork(net)) kids.push({ key: `${k}:links`, label: "PDO links", attrs: { view: "links", net: k } });
      kids.push({ key: `${k}:raw`, label: "CAN messages", attrs: { view: "raw", net: k } });
    }
    out.push({ key: String(k), label: netLabel(net, k), sub: protocolText(net), net: k, kids, attrs: { net: k } });
  });
  if (!commission) {
    out.push({ key: "access", label: "Online access", attrs: { view: "access" }, id: "nav-access" });
    const gateway = S.model.top.gateway || (nets.some(isSlave) && nets.some((n) => !isSlave(n)));
    if (gateway) out.push({ key: "gateway", label: "Gateway", attrs: { view: "gateway" }, id: "nav-gateway" });
    if (S.model.top.bridge) out.push({ key: "bridge", label: "Modbus bridge", attrs: { view: "bridge" }, id: "nav-bridge" });
    if (nets.length < MAX_NETWORKS) out.push({ key: "addnet", label: "+ Add network…", action: true, attrs: { action: "add-network" } });
  }
  return out;
}

// A name with a line break opportunity after each _, so a long name wraps
// between its words (temperature_ / inputs_left) rather than mid-word.
function breakable(text) {
  return String(text).split(/(?<=_)/).flatMap((part, i) => i ? [el("wbr"), part] : [part]);
}

function renderTree() {
  const host = $("#tree");
  if (!host || !S.model) return;
  const counts = treeCounts();
  const sel = selectedEntry();
  const had = document.activeElement && host.contains(document.activeElement) ? document.activeElement.dataset.key : null;
  const focusKey = had || S.treeFocus || sel;
  const item = (e, level, setSize, pos) => {
    const folded = e.kids ? S.treeFolded.has(netKey(S.model.networks[e.net], e.net)) : false;
    const own = counts[e.key];
    const c = e.kids && folded ? sumCounts(counts, e.key) : own;
    const selected = !e.alias && e.key === sel;
    const li = el("li", Object.assign({ role: "treeitem", class: "tree-item" + (e.action ? " action" : "") + (e.muted ? " muted" : "") +
        (e.kids ? " net" : "") + (e.kids && e.net === S.net ? " open-net" : "") + (selected ? " selected" : ""),
      "aria-level": String(level), "aria-setsize": String(setSize), "aria-posinset": String(pos),
      "aria-selected": e.action || e.muted ? null : String(selected),
      "aria-expanded": e.kids && e.kids.length ? String(!folded) : null,
      tabindex: "-1", id: e.id || null, title: e.kids ? `${e.label} (${e.sub})` : e.label,
      dataset: Object.assign({ key: e.key }, e.attrs) }),
    el("span", { class: "tree-row" },
      e.kids && e.kids.length ? el("span", { class: "twist", "aria-hidden": "true", onclick: (ev) => { ev.stopPropagation(); toggleNet(e.net); } }, folded ? "▸" : "▾") : null,
      e.mark !== undefined ? fillMark(el("span", { class: "tree-mark " + e.mark, "aria-hidden": "true", dataset: e.word ? { simBadge: e.word } : {} }), e.mark) : null,
      e.kids ? el("span", { class: "tree-label" }, el("span", { class: "name" }, breakable(e.label)), el("span", { class: "muted proto" }, e.sub))
        : el("span", { class: "name" }, breakable(e.label), e.word ? el("span", { class: "visually-hidden" }, ` (${e.word})`) : null),
      badge(c),
      e.kids && workspace() === "configure" ? el("button", { type: "button", class: "small net-menu", tabindex: "-1",
        "aria-label": `Actions of ${netNamed(S.model.networks[e.net], e.net)}`, title: "Rename, role, remove",
        dataset: { netMenu: e.net }, onclick: (ev) => { ev.stopPropagation(); netMenu(e.net, ev.currentTarget); } }, "⋯") : null));
    li.addEventListener("click", (ev) => { ev.stopPropagation(); treeFocus(e.key); openEntry(e); });
    if (e.kids && e.kids.length && !folded) {
      li.append(el("ul", { role: "group" }, e.kids.map((x, j) => item(x, level + 1, e.kids.length, j + 1))));
    }
    return li;
  };
  const model = treeModel();
  S.treeEntries = new Map();
  const walk = (list) => { for (const e of list) { S.treeEntries.set(e.key, e); if (e.kids) walk(e.kids); } };
  walk(model);
  put(host, model.map((e, j) => item(e, 1, model.length, j + 1)));
  const items = treeVisible();
  const f = items.find((x) => x.dataset.key === focusKey) || items.find((x) => x.dataset.key === sel) || items[0];
  if (f) f.tabIndex = 0;
  if (had && f) f.focus();
  // The narrow window's tree button: the open entry and the error count.
  const btn = $("#tree-toggle");
  if (btn) {
    const e = S.treeEntries.get(sel);
    const errors = S.check ? S.check.errors || 0 : 0;
    btn.textContent = `${e ? e.label : "Network"} ▾` + (errors ? ` · ${errors}✕` : "");
    btn.setAttribute("aria-label", `Network tree: ${e ? e.label : "none"} open` + (errors ? `, ${errors} error${errors === 1 ? "" : "s"}` : ""));
  }
}

function treeVisible() { return [...document.querySelectorAll("#tree [role=treeitem]")]; }

function treeFocus(key) {
  S.treeFocus = key;
  for (const x of treeVisible()) x.tabIndex = x.dataset.key === key ? 0 : -1;
  const t = treeVisible().find((x) => x.dataset.key === key);
  if (t && document.activeElement !== t) t.focus();
}

function toggleNet(k, open) {
  const key = netKey(S.model.networks[k], k);
  const folded = S.treeFolded.has(key);
  if (open === undefined ? folded : open) S.treeFolded.delete(key); else S.treeFolded.add(key);
  saveFolded();
  renderTree();
}

function saveFolded() {
  api("POST", "/api/ui", { tree_folded: [...S.treeFolded] }).catch(() => {});
}

// Opens a tree entry: its network becomes the open one, then its page.
function openEntry(e) {
  closeTreePanel();
  const a = e.attrs || {};
  if (a.action === "add-network") return addNetwork();
  if (a.empty) return;
  if (workspace() === "commission") {
    const k = a.net;
    const net = S.model.networks[k];
    const name = netName(net);
    if (k !== S.net || (several() && S.onlineNet !== name)) {
      if (name && several()) pickNetwork(name); else { openNet(k); render(); }
    }
    S.onlineNode = a.node !== undefined ? num((net.nodes || [])[a.node].node_id) : null;
    if (S.view !== "online") showView("online");
    else { renderTree(); if (S.onlineNode !== null) { renderOnlineNode(); pollHighlight(); } else put($("#online-node")); }
    return;
  }
  if (a.net !== undefined && a.net !== S.net) {
    openNet(a.net);
    S.onlineNet = null;
    S.onlineNode = null;
    S.scanResult = null;
    S.lssFound = null;
    S.lssDevice = null;
    S.supervision = {};
  }
  if (a.action === "add-node") { $("#eds-input").click(); return; }
  if (a.node !== undefined) return showView("node:" + a.node);
  if (a.slave) return showView("bus");
  showView(a.view || "bus");
}

function treeKeys(ev) {
  const items = treeVisible();
  const cur = items.indexOf(document.activeElement);
  if (cur < 0) return;
  const li = items[cur];
  const e = S.treeEntries.get(li.dataset.key);
  const go = (i) => { const t = items[Math.max(0, Math.min(items.length - 1, i))]; if (t) treeFocus(t.dataset.key); };
  const parent = () => { const p = li.parentElement.closest("[role=treeitem]"); return p; };
  switch (ev.key) {
    case "ArrowDown": go(cur + 1); break;
    case "ArrowUp": go(cur - 1); break;
    case "Home": go(0); break;
    case "End": go(items.length - 1); break;
    case "ArrowRight":
      if (li.getAttribute("aria-expanded") === "false") toggleNet(e.net, true);
      else if (li.getAttribute("aria-expanded") === "true") go(cur + 1);
      break;
    case "ArrowLeft":
      if (li.getAttribute("aria-expanded") === "true") toggleNet(e.net, false);
      else { const p = parent(); if (p) treeFocus(p.dataset.key); }
      break;
    case "Enter": case " ": openEntry(e); break;
    case "F10":
      if (!ev.shiftKey || !e.kids || workspace() !== "configure") return;
      netMenu(e.net, li.querySelector(".net-menu"));
      break;
    case "ContextMenu":
      if (!e.kids || workspace() !== "configure") return;
      netMenu(e.net, li.querySelector(".net-menu"));
      break;
    default:
      if (ev.key.length !== 1 || ev.ctrlKey || ev.metaKey || ev.altKey) return;
      typeAhead(ev.key, items, cur);
      ev.preventDefault();
      return;
  }
  ev.preventDefault();
}

// Type-ahead: the typed text (kept for a second) against the entry names.
function typeAhead(ch, items, cur) {
  clearTimeout(S.typeTimer);
  S.typed = (S.typed || "") + ch.toLowerCase();
  S.typeTimer = setTimeout(() => { S.typed = ""; }, 1000);
  const text = (x) => (x.querySelector(".name") || x).textContent.trim().toLowerCase();
  const n = items.length;
  const start = S.typed.length > 1 ? cur : cur + 1;
  for (let j = 0; j < n; j++) {
    const x = items[(start + j) % n];
    if (text(x).startsWith(S.typed)) { treeFocus(x.dataset.key); return; }
  }
}

// The network menu: Rename…, Role (CANopen) and Remove…; the actions act on the open network.
async function netMenu(k, anchor) {
  if (k !== S.net) { openNet(k); if (S.view.startsWith("node:")) S.view = "bus"; render(); }
  const net = S.model.networks[k];
  const buttons = [["cancel", "Cancel"], ["rename", "Rename…"]];
  if (!isJ1939(net) && !isPlain(net)) buttons.push(["role", isSlave(net) ? "Make it a master network…" : "Make it a slave network…"]);
  if (S.model.networks.length > 1) buttons.push(["remove", "Remove…", { danger: true }]);
  const v = await modal(`${netNamed(net, k)} (${protocolText(net)})`, buttons);
  if (v === "rename") await renameNetwork();
  else if (v === "role") await switchRole(isSlave(net) ? "master" : "slave");
  else if (v === "remove") await removeNetwork();
  const back = treeVisible().find((x) => x.dataset.key === String(Math.min(k, S.model.networks.length - 1)));
  if (back) back.focus(); else if (anchor && anchor.isConnected) anchor.focus();
}

// Narrow windows: the tree opens over the page from its button.
function closeTreePanel() { document.body.classList.remove("tree-open"); const b = $("#tree-toggle"); if (b) b.setAttribute("aria-expanded", "false"); }

function wireTree() {
  $("#tree").addEventListener("keydown", treeKeys);
  $("#tree-toggle").addEventListener("click", () => {
    const open = !document.body.classList.contains("tree-open");
    document.body.classList.toggle("tree-open", open);
    $("#tree-toggle").setAttribute("aria-expanded", String(open));
    if (open) { const f = treeVisible().find((x) => x.tabIndex === 0); if (f) f.focus(); }
  });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && document.body.classList.contains("tree-open")) { closeTreePanel(); $("#tree-toggle").focus(); } });
}

// The folded networks kept on this PC, read once at the start.
async function loadTreeSettings() {
  try {
    const ui = await api("GET", "/api/ui");
    S.treeFolded = new Set(Array.isArray(ui.tree_folded) ? ui.tree_folded : []);
    if (typeof ui.node_tab === "string") S.nodeTab = ui.node_tab;
  } catch (e) { /* defaults */ }
}

// A network holding the open entry, or a new error, unfolds by itself.
function unfoldFor(entry) {
  if (!entry) return;
  const k = Number(String(entry).split(":")[0]);
  if (!Number.isInteger(k) || !S.model.networks[k]) return;
  const key = netKey(S.model.networks[k], k);
  if (S.treeFolded.has(key)) { S.treeFolded.delete(key); saveFolded(); }
}
