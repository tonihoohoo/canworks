"use strict";
// The Commission workspace's home (commission-workspace): the Nodes table
// and what hangs on it. Not connected, it says to connect in the connection
// bar; with a config, a scan is compared with the config
// (Match, Missing, Not in config, Identity differs) and a found device goes
// into the draft from its row. Also the live state on the network tree, the
// session log's bus events, Unlock… on a locked control, and the simulated
// device panel of a node's Status tab. Loaded after app.js, connection.js
// and commission.js and uses their helpers.

// ---------------------------------------------------------------------------
// Not connected: one line in place of the table's rows (one-connect-place)

function nodesNotConnected() {
  return connNeeds(connAdapter() ? "Listing the devices on the bus" : "The Nodes table", { dataset: { conn: "needs", nodes: "not-connected" } });
}

// ---------------------------------------------------------------------------
// The comparison of a scan with the config

const COMPARE_TEXT = { match: "Match", missing: "Missing", not_in_config: "Not in config", identity_differs: "Identity differs",
  heard: "Heard", not_heard: "Not heard" };
const COMPARE_CLASS = { missing: "bad", not_in_config: "warn-text", identity_differs: "warn-text" };
const IDENTITY_LABEL = { vendor_id: "vendor", product_code: "product", revision_number: "revision", serial_number: "serial number" };

function compareOn() { return !connAdapter() && workspace() === "commission" && !onlineIsSlave(); }

// What the draft expects of node `id` of the online network: vendor and
// product from its EDS, revision and serial number where the node sets them.
function expectedOf(n) {
  const out = {};
  const dev = n && n.eds && (S.state.eds || {})[n.eds] ? (S.state.eds[n.eds].device || {}) : {};
  if (Number.isInteger(dev.vendor_id)) out.vendor_id = dev.vendor_id;
  if (Number.isInteger(dev.product_code)) out.product_code = dev.product_code;
  for (const k of ["revision_number", "serial_number"]) {
    const v = num(n && n[k]);
    if (Number.isInteger(v) && v) out[k] = v;
  }
  return out;
}

// The state of a scanned device against the draft (as the server's
// compare_scanned, but on the draft as it is now, so an add or an Undo
// shows at once).
function compareDevice(d) {
  const n = configNode(d.node_id);
  if (!n) return { state: "not_in_config", differs: [] };
  const exp = expectedOf(n);
  const differs = Object.keys(IDENTITY_LABEL).filter((k) => Number.isInteger(exp[k]) && Number.isInteger(d[k]) && (d[k] >>> 0) !== (exp[k] >>> 0))
    .map((k) => ({ field: k, expected: exp[k], found: d[k] }));
  return { state: differs.length ? "identity_differs" : "match", differs };
}

// {node_id: {state, differs, device}} for the configured nodes and the
// scanned ones; before a scan, from what the status says was heard.
function comparison(st) {
  const out = {};
  const heard = new Map(((st && st.nodes) || []).map((n) => [n.node_id, n]));
  const scan = S.scanResult && S.scanResult.nodes ? S.scanResult : null;
  const found = new Map(((scan && scan.nodes) || []).map((d) => [d.node_id, d]));
  // Devices given a node ID by LSS in this session count as found.
  for (const d of S.lssFound || []) if (!found.has(d.node_id)) found.set(d.node_id, d);
  for (const n of onlineConfig().nodes || []) {
    const id = num(n.node_id);
    if (!Number.isInteger(id)) continue;
    const h = heard.get(id);
    const alive = !!h && h.state !== 0 && h.state !== null && h.state !== undefined;
    if (found.has(id)) out[id] = Object.assign(compareDevice(found.get(id)), { device: found.get(id) });
    else if (scan) out[id] = { state: alive ? "match" : "missing", differs: [] };
    else out[id] = { state: alive ? "heard" : "not_heard", differs: [] };
  }
  for (const [id, d] of found) if (!out[id]) out[id] = Object.assign(compareDevice(d), { device: d });
  return out;
}

function compareCounts(cmp) {
  const c = {};
  for (const v of Object.values(cmp)) c[v.state] = (c[v.state] || 0) + 1;
  return c;
}

// "12 match · 1 missing · 2 not in config · 1 differs", each part a filter.
function compareSummary(cmp) {
  const c = compareCounts(cmp);
  const order = [["match", "match"], ["missing", "missing"], ["not_in_config", "not in config"], ["identity_differs", "differs"]];
  if (!S.scanResult || !S.scanResult.nodes) return el("p", { class: "muted", dataset: { nodes: "summary" } }, "Scan the bus to compare it with the config.");
  const parts = order.filter(([k]) => c[k]).map(([k, label]) => el("button", { type: "button", class: "link" + (S.nodesFilter === k ? " active" : ""),
    "aria-pressed": String(S.nodesFilter === k), dataset: { nodesFilter: k }, title: "Show only these",
    onclick: () => { S.nodesFilter = S.nodesFilter === k ? null : k; onlineRedraw(); } }, `${c[k]} ${label}`));
  const kids = [];
  parts.forEach((p, k) => { if (k) kids.push(" · "); kids.push(p); });
  if (S.nodesFilter) kids.push(" ", el("button", { type: "button", class: "small", dataset: { nodesFilter: "all" }, onclick: () => { S.nodesFilter = null; onlineRedraw(); } }, "Show all"));
  return el("p", { class: "nodes-summary", dataset: { nodes: "summary" }, "aria-live": "polite" }, ...kids);
}

// The comparison of one row in words (colour is never the only cue), the
// differing fields, and the actions it offers.
function compareCell(c, id) {
  if (!c) return el("td");
  const why = c.differs && c.differs.length ? c.differs.map((x) => `${upperFirst(IDENTITY_LABEL[x.field])} ${hex8(x.found)} on the bus, ${hex8(x.expected)} in the config`).join("; ") : "";
  const actions = compareActions(id, c);
  return el("td", { class: COMPARE_CLASS[c.state] || "muted", dataset: { compare: c.state } },
    COMPARE_TEXT[c.state] || c.state, why ? el("div", { class: "muted", dataset: { differs: "1" } }, why) : null,
    actions ? el("div", { class: "actions" }, actions) : null);
}

// The actions a row's comparison offers: Add to config, Use matching EDS,
// Take serial number.
function compareActions(id, c) {
  if (!c || !c.device) return null;
  const d = c.device;
  const out = [];
  if (c.state === "not_in_config") {
    out.push(el("label", { class: "check", title: "Tick several to add them at once" },
      el("input", { type: "checkbox", "aria-label": `Pick node ${id}`, checked: (S.nodesPicked || new Set()).has(id),
        dataset: { nodesPick: id }, onchange: (e) => { S.nodesPicked = S.nodesPicked || new Set(); if (e.target.checked) S.nodesPicked.add(id); else S.nodesPicked.delete(id); onlineRedraw(); } })),
    el("button", { type: "button", class: "small", dataset: { nodesAdd: id }, onclick: () => addFound([d]) }, "Add to config"));
  } else if (c.state === "identity_differs") {
    const onlySerial = c.differs.every((x) => x.field === "serial_number");
    const n = configNode(id);
    const match = (d.eds_matches || []).find((m) => !n || m.name !== n.eds);
    if (onlySerial) out.push(el("button", { type: "button", class: "small", dataset: { nodesSerial: id }, onclick: () => takeSerial(id, d) }, "Take serial number"));
    else if (match) out.push(el("button", { type: "button", class: "small", dataset: { nodesUseEds: id }, title: match.name, onclick: () => useMatchingEds(id, d) }, "Use matching EDS"));
  }
  return out.length ? out : null;
}

// Rows for devices the scan found that are not configured (with a config).
function notInConfigRows(cmp, columns) {
  return Object.entries(cmp).filter(([, c]) => c.state === "not_in_config").map(([k, c]) => {
    const id = Number(k);
    const d = c.device;
    const what = [d.device_name, d.vendor_id !== undefined ? `vendor ${hex8(d.vendor_id)}` : "", d.product_code !== undefined ? `product ${hex8(d.product_code)}` : ""].filter(Boolean).join(", ");
    const lss = (S.lssFound || []).some((x) => x.node_id === id) && !(S.scanResult && (S.scanResult.nodes || []).some((x) => x.node_id === id));
    const cells = [el("td", null, String(id)), el("td", null, what), el("td", { class: "muted" }, lss ? "node ID set by LSS here" : "found by the scan")];
    while (cells.length < columns - 1) cells.push(el("td"));
    return el("tr", { dataset: { onlineNode: id, notInConfig: id } }, ...cells, compareCell(c, id));
  });
}

function nodesToolbar() {
  const picked = [...(S.nodesPicked || [])];
  const progress = el("span", { class: "muted", dataset: { online: "scan-progress" }, "aria-live": "polite" });
  const scan = el("button", { type: "button", class: "primary", dataset: { online: "scan" }, onclick: () => startScan() }, "Scan the bus");
  const cancel = el("button", { type: "button", hidden: true, dataset: { online: "scan-cancel" }, onclick: stopScan }, "Cancel");
  const addPicked = picked.length ? el("button", { type: "button", dataset: { nodesAddPicked: "1" },
    onclick: () => addFound(picked.map((id) => ((S.scanResult && S.scanResult.nodes) || []).find((d) => d.node_id === id)).filter(Boolean)) },
  `Add ${picked.length} to config`) : null;
  return el("div", { class: "toolbar", dataset: { nodes: "toolbar" } }, scan, cancel, progress, el("div", { class: "spacer" }), addPicked);
}

// The online table drawn again from the last answer (a filter, a tick, an add).
function onlineRedraw() {
  if (S.onlineLast && $("#online-live") && !CONN.error) onlineApply(S.onlineLast, null);
}

// Scan the bus. With a config through the runtime: a running network is
// named first, and the scan goes with force only after the user agrees.
async function startScan() {
  if (!(await askSlowPath("The bus scan"))) return;
  const st = S.onlineLast && S.onlineLast.status;
  const running = !connAdapter() && st ? (st.nodes || []).filter((n) => n.state === 5).map((n) => n.node_id) : [];
  if (running.length) {
    const names = running.map((id) => { const n = configNode(id); return `${id}${n && n.name ? " " + n.name : ""}`; });
    const v = await modal(`Scanning sends SDO requests to every node ID while the PLC program runs node${running.length === 1 ? "" : "s"} ${names.join(", ")}. Scan anyway?`,
      [["cancel", "Cancel", true], ["scan", "Scan anyway"]]);
    if (v !== "scan") { const p = document.querySelector("[data-online=scan-progress]"); if (p) p.textContent = "Scan not started."; return; }
    return runScan(true, true);
  }
  return runScan(true);
}

// Found devices into the draft: the matching EDS (a picker when several
// match, a file when none does), the product name, the serial number, and
// LSS assignment when the ID was given by LSS here and the EDS has LSS.
async function addFound(devices) {
  const before = S.check ? (S.check.errors || 0) + (S.check.warnings || 0) : 0;
  let added = 0;
  for (const d of devices) {
    if (configNode(d.node_id)) continue;
    const matches = d.eds_matches || [];
    let match = matches[0] || null;
    let imported = null;
    // Several matches or none: the EDS dialog for this device (one-eds-picker).
    if (matches.length !== 1) {
      const a = await chooseEds({ title: `Node ${d.node_id}: ` + (matches.length ? `${matches.length} EDS files match this device. Which one?`
        : "no EDS file in the project or the EDS library matches this device. Pick its EDS file."),
      matches, lint: edsLint(), main: "Add node", cancelLabel: "Skip", dataset: { nodes: "eds-pick" } });
      if (!a || !a.choice) continue;
      const c = a.choice;
      match = null;
      if (c.kind === "match" || c.kind === "library") match = { path: c.path, name: c.name };
      else imported = await edsIntoDraft(c, edsLint());
      if (!match && !imported) continue;
    }
    const lss = !!(S.lssSet && S.lssSet[d.node_id]);
    if (await addScannedNode(d, match, null, true, lss, true, imported)) { added++; commLog(d.node_id, "Add to config", "added to the draft (unsaved)"); }
  }
  S.nodesPicked = new Set();
  if (!added) { onlineRedraw(); return; }
  render();
  // The Add button went with its row: the focus goes to the node's new row, else to Undo.
  if (document.activeElement === document.body) {
    const last = devices[devices.length - 1];
    const to = (last && document.querySelector(`tr[data-draft-node="${last.node_id}"] :is(button, input, select)`)) || document.querySelector("#banner button");
    if (to) to.focus();
  }
  problemsAfterCheck(before);
}

async function useMatchingEds(id, d) {
  const n = configNode(id);
  const match = (d.eds_matches || []).find((m) => m.name !== n.eds);
  if (!n || !match) return;
  const before = S.check ? (S.check.errors || 0) + (S.check.warnings || 0) : 0;
  let res;
  try { res = await api("POST", "/api/online/use_eds", { path: match.path, eds_lint: edsLint() }); } catch (e) { banner(e.message, true); return; }
  S.state.eds = S.state.eds || {};
  S.state.eds[res.name] = res.summary;
  n.eds = res.name;
  commLog(id, `Use matching EDS ${res.name}`, "changed in the draft (unsaved)");
  banner(`Node ${id} now uses ${res.name}. Save to keep it; mapped objects the new EDS lacks are listed under Problems.`);
  changed(true);
  problemsAfterCheck(before);
}

function takeSerial(id, d) {
  const n = configNode(id);
  if (!n) return;
  n.serial_number = d.serial_number;
  commLog(id, `Take serial number ${hex8(d.serial_number)}`, "changed in the draft (unsaved)");
  banner(`Node ${id}: serial number set to ${hex8(d.serial_number)}. Save to keep it.`);
  changed(true);
}

// The Problems tab opens by itself when an action of the comparison made new problems.
function problemsAfterCheck(before) {
  const wait = () => {
    if (document.body.dataset.checking === "1") { setTimeout(wait, 100); return; }
    const now = S.check ? (S.check.errors || 0) + (S.check.warnings || 0) : 0;
    if (now > before) { const box = $("#problems-box"); if (box) box.open = true; }
  };
  setTimeout(wait, 50);
}

// ---------------------------------------------------------------------------
// Live state on the network tree

// [mark class, word] of a node in a status answer.
function liveMark(n, cmp, flagged) {
  let m;
  if (!n || n.state === 0 || n.state === null || n.state === undefined) m = n && n.booted === false && n.boot_error ? ["st-lost", "not answering"] : ["st-unheard", "not heard"];
  else if (n.boot_error) m = ["st-lost", "boot failed"];
  else if (n.state === 5) m = ["st-op", "operational"];
  else if (n.state === 127) m = ["st-preop", "pre-operational"];
  else if (n.state === 4) m = ["st-stop", "stopped"];
  else m = ["st-unheard", stateName(n.state)];
  const words = [m[1]];
  let cls = m[0];
  if (cmp && (cmp.state === "missing" || cmp.state === "identity_differs")) { cls += " cmp-" + cmp.state; words.push(COMPARE_TEXT[cmp.state].toLowerCase()); }
  if (flagged === "cleared") { cls += " flag-cleared"; words.push("error cleared"); }
  else if (flagged) { cls += " flag"; words.push("new error entry"); }
  return [cls, words.join(", ")];
}

// Each status answer of a config's runtime: the state marks of the tree's
// nodes, and a polite announcement when a node's state changes.
function treeLive(st) {
  if (!S.model || connAdapter() || !st || st.local || st.role === "slave" || (st.protocol && st.protocol !== "canopen")) return;
  const net = onlineConfig();
  const name = netName(net);
  const cmp = comparison(st);
  const byId = new Map((st.nodes || []).map((n) => [n.node_id, n]));
  S.treeWords = S.treeWords || {};
  const said = [];
  for (const n of net.nodes || []) {
    const id = num(n.node_id);
    if (!Number.isInteger(id)) continue;
    const [cls, word] = liveMark(byId.get(id), cmp[id], S.emcyNew && S.emcyNew[id]);
    const key = `${name}/${id}`;
    const old = S.treeWords[key];
    if (old !== undefined && old.split(",")[0] !== word.split(",")[0]) said.push(`${id} ${n.name || ""}`.trim() + ", " + word.split(",")[0]);
    S.treeWords[key] = word;
    setNodeMark(name, id, "live " + cls + (nodeSimulated(n, net) ? " sim" : ""), word + (nodeSimulated(n, net) ? ", simulated" : ""));
  }
  const live = $("#tree-live");
  if (live && said.length) live.textContent = said.join("; ");
}

// The tree's marks back to the config's own (disconnected, another network).
function treeLiveClear() {
  if (!S.nodeMarks) return;
  for (const key of Object.keys(S.nodeMarks)) {
    const at = key.lastIndexOf("/");
    setNodeMark(key.slice(0, at), Number(key.slice(at + 1)), null);
  }
  S.treeWords = {};
}

// ---------------------------------------------------------------------------
// The session log's bus events (commission.js keeps the log)

const EVENTS_MAX = 5000;

// Each status answer: what changed since the last one, per node.
function logEvents(st) {
  if (!st || !commLogOn() || st.role === "slave") return;
  const prev = S.logPrev || {};
  const next = {};
  const net = connAdapter() ? null : onlineNetwork();
  for (const n of st.nodes || []) {
    const id = n.node_id;
    const p = prev[id];
    const cur = { state: n.state ?? null, emcy: n.emcy ? n.emcy.count || 0 : 0, boot: n.boot_error || null,
      boots: n.boots ?? null, timeouts: (n.pdo_timeouts || []).filter((t) => t.timed_out).map((t) => t.tpdo).join(",") };
    next[id] = cur;
    if (!p) continue;  // the first answer is the starting point, not a change
    if (p.state !== cur.state) {
      const text = cur.state === 0 || cur.state === null ? "not answering" : stateName(cur.state);
      commEvent(id, net, `State ${p.state === 0 || p.state === null ? "not answering" : stateName(p.state)} → ${text}`, cur.state === 0 ? "lost" : "ok");
    }
    if (cur.emcy > p.emcy && n.emcy) {
      commEvent(id, net, `EMCY ${hex4(n.emcy.code)} ${emcyClass(n.emcy.code)}`, `error register 0x${Number(n.emcy.error_register || 0).toString(16).toUpperCase().padStart(2, "0")}`);
      S.emcyNew = S.emcyNew || {};
      // EMCY 0x0000 (error reset or no error) clears the diagnosis: a pending flag turns grey, none is raised.
      if (n.emcy.code === 0) {
        if (S.emcyNew[id] || cur.emcy - p.emcy > 1) S.emcyNew[id] = "cleared";
      } else if (S.onlineNode !== id || (S.onlineTab || "status") !== "status") S.emcyNew[id] = "pending";
    }
    // A reset and boot can both fall between two answers, leaving state and
    // boot result as they were: the bridge's boot count still goes up.
    const rebooted = cur.boots !== null && p.boots !== null && cur.boots > p.boots;
    if (cur.boot !== p.boot || (rebooted && !cur.boot)) commEvent(id, net, cur.boot ? `Boot failed: error ${cur.boot} ${n.boot_error_text || ""}`.trim() : "Booted", cur.boot ? "failed" : "ok");
    if (cur.timeouts !== p.timeouts && cur.timeouts) commEvent(id, net, `TPDO ${cur.timeouts} timed out`, "timeout");
  }
  S.logPrev = next;
}

function commEvent(node, net, what, result) {
  S.commLog = S.commLog || [];
  S.commLog.push({ time: new Date().toISOString().replace(/\.\d+Z$/, "Z"), node, net, what, result, kind: "event" });
  let events = S.commLog.filter((e) => e.kind === "event").length;
  while (events > EVENTS_MAX) {
    const k = S.commLog.findIndex((e) => e.kind === "event");
    S.commLog.splice(k, 1);
    events--;
  }
  refreshLog();
}

// ---------------------------------------------------------------------------
// Unlock… on a control disabled because changes are not allowed

const LOCKED_TEXT = "Locked. Changes are not allowed on this connection.";

// The warning bar at the top of a section with locked controls: the reason
// and Unlock…. `focus` is a selector of the control to focus once it is enabled.
function lockedNote(dataKey, focus, prefix) {
  const btn = el("button", { type: "button", class: "small", dataset: { unlock: dataKey }, onclick: () => unlock(focus || null, btn) }, "Unlock…");
  return notice("warning", (prefix ? prefix + " " : "") + LOCKED_TEXT + " " + NO_CHANGES, { class: "locked", live: false, actions: [btn], dataset: { online: dataKey } });
}

async function unlock(focus, btn) {
  const c = S.onlineLast && S.onlineLast.conn;
  if (!connAdapter() || (c && c.allow_changes_source && c.allow_changes_source !== "switch")) {
    await modal("This runtime decides whether changes are allowed. Turn on Allow changes in Configure → Project → Online access, save and upload the config; it takes effect after the upload.",
      [["ok", "OK", true]]);
    if (btn && btn.isConnected) btn.focus();
    return;
  }
  const v = await modal("Allow changes on this adapter connection? SDO writes, NMT commands, LSS and restore then go to the bus. Saving to a device's non-volatile memory still asks each time.",
    [["allow", "Allow changes", true], ["cancel", "Cancel"]]);
  if (v !== "allow") { if (btn && btn.isConnected) btn.focus(); return; }
  if (!(await saveOnline({ allow_changes: true }))) return;
  if (S.onlineLast && S.onlineLast.conn) S.onlineLast.conn.allow_changes = true;
  if (S.onlineLast && S.onlineLast.status) S.onlineLast.status.allow_changes = true;
  if (S.onlineLast && S.onlineLast.hello) S.onlineLast.hello.allow_changes = true;
  render();
  connKick();
  // The control is drawn again on the next status answer: focus it once it is enabled.
  if (!focus) return;
  const until = Date.now() + 5000;
  const settle = () => {
    const t = document.querySelector(focus);
    if (t && !t.disabled) { t.focus(); return; }
    if (Date.now() < until) setTimeout(settle, 50);
  };
  settle();
}

// ---------------------------------------------------------------------------
// A simulated node's Status tab: its simulated device (power, faults, values)

const SIM_PANEL_FAULTS = [["heartbeat", "Heartbeat stop"], ["power_off", "Power off"], ["power_on", "Power on"],
  ["reset_node", "Reset node"], ["reset_comm", "Reset communication"]];

function simulatedNode(id) {
  if (connAdapter() || !S.model) return false;
  const n = configNode(id);
  return !!n && nodeSimulated(n, onlineConfig());
}

function simPanel(id) {
  const box = el("fieldset", { dataset: { simPanel: id } }, el("legend", null, "Simulated device"),
    el("div", { class: "muted", dataset: { simPanelState: id } }, "Reading the simulated device…"),
    el("div", { class: "toolbar sim-fault-buttons", dataset: { simPanelFaults: id } }),
    el("div", { dataset: { simPanelActive: id } }),
    el("div", { class: "table-scroll", dataset: { box: "sim_values", boxLabel: "the values" } }, el("table", { class: "od sim-values" },
      el("thead", null, el("tr", null, thCells(["Object", "Name", "Value", "Set to", ""]))),
      el("tbody", { dataset: { simPanelRows: id } }))),
    hint("Override holds a value until Release. The simulation file is under Configure → Simulation file; scenarios and the other faults are in the Simulation tab."));
  S.simPanelSeq = (S.simPanelSeq || 0) + 1;
  simPanelPoll(id, S.simPanelSeq);
  return box;
}

async function simPanelPoll(id, seq) {
  let r;
  try { r = await api("POST", "/api/sim/poll", { port: diagPort(), node: id, objects: [], target: "runtime" }); }
  catch (e) {
    const p = document.querySelector(`[data-sim-panel-state="${id}"]`);
    if (!p || seq !== S.simPanelSeq) return;
    // Why it cannot be read: a bar at the top of the section, in the state line's place.
    p.replaceChildren(/nothing simulated/.test(e.message) ? notice("warning", "The runtime simulates nothing: upload this config to it.", { live: false })
      : notice("error", e.message, { live: false }));
    setTimeout(() => simPanelPoll(id, seq), 2000);
    return;
  }
  const state = document.querySelector(`[data-sim-panel-state="${id}"]`);
  if (!state || seq !== S.simPanelSeq) return;
  const allow = !!r.allow_changes;
  const d = ((r.status || {}).devices || []).find((x) => String(x.node) === String(id)) || {};
  state.replaceChildren(`NMT ${d.nmt || "?"}, power ${d.power || "?"}` + (d.conflict ? ", node ID conflict" : "") + ".");
  const off = { disabled: !allow, title: allow ? null : "Changes are not allowed on this connection" };
  const req = async (op, fields, done) => {
    try { await api("POST", "/api/sim/request", Object.assign({ op, port: diagPort(), target: "runtime" }, fields)); banner(done); }
    catch (e) { banner(e.message, true); }
  };
  const faults = document.querySelector(`[data-sim-panel-faults="${id}"]`);
  const fsig = String(allow);
  if (faults.dataset.sig !== fsig) {
    faults.dataset.sig = fsig;
    faults.replaceChildren(...SIM_PANEL_FAULTS.map(([k, label]) => el("button", Object.assign({ type: "button", dataset: { simPanelFault: k },
      onclick: () => req("sim_fault", { node: id, fault: FAULT_FIXED[k] }, `Node ${id}: ${label} injected.`) }, off), label)));
  }
  const active = document.querySelector(`[data-sim-panel-active="${id}"]`);
  const list = d.faults || [];
  const asig = JSON.stringify([list, allow]);
  if (active.dataset.sig !== asig) {
    active.dataset.sig = asig;
    put(active, list.length ? el("p", null, "Active faults: ", list.map((f) => el("span", { class: "row" }, faultText(f), " ",
      el("button", Object.assign({ type: "button", class: "small", dataset: { simPanelClear: faultName(f) },
        onclick: () => req("sim_clear", { node: id, fault: faultName(f) }, `Node ${id}: ${faultName(f)} cleared.`) }, off), "Clear"), " "))) : null,
    list.length ? el("button", Object.assign({ type: "button", class: "small", dataset: { simPanelClear: "all" },
      onclick: () => req("sim_clear", { node: id, fault: "all" }, `Node ${id}: every fault cleared and the device powered on.`) }, off), "Clear all") : null);
  }
  const rows = document.querySelector(`[data-sim-panel-rows="${id}"]`);
  const values = (r.values || []).filter((v) => String(v.node) === String(id));
  const overrides = simKeys(d.overrides);
  const rsig = values.map((v) => simKey(v.object)).join(",") + "|" + allow;
  if (rows.dataset.sig !== rsig) {
    rows.dataset.sig = rsig;
    rows.replaceChildren(...(values.length ? values.map((v) => {
      const key = simKey(v.object);
      const input = el("input", Object.assign({ type: "text", class: "od-input", "aria-label": `Value of ${key}`, dataset: { simPanelInput: key } }, off));
      return el("tr", { dataset: { simPanelObject: key } }, el("td", { class: "mono" }, key), el("td", null, v.name || ""),
        el("td", null, el("strong", { dataset: { simPanelValue: key } })), el("td", null, input),
        el("td", { class: "actions" },
          el("button", Object.assign({ type: "button", class: "small", dataset: { simPanelOverride: key },
            onclick: () => { const x = simParseValue(input.value); if (x === "" || Number.isNaN(x)) { banner("Enter a value first.", true); return; } req("sim_override", { node: id, values: { [key]: x } }, `Node ${id} ${key}: held at ${x} until Release.`); } }, off), "Override"), " ",
          el("button", Object.assign({ type: "button", class: "small", dataset: { simPanelRelease: key },
            onclick: () => req("sim_release", { node: id, objects: [key] }, `Node ${id} ${key}: override released.`) }, off), "Release")));
    }) : [el("tr", null, el("td", { colspan: 5, class: "muted" }, r.pdo_error || "No objects in this device's PDOs."))]));
  }
  for (const v of values) {
    const key = simKey(v.object);
    const cell = rows.querySelector(`[data-sim-panel-value="${key}"]`);
    if (cell) cell.textContent = simValueText(v.value, v.type) + (overrides.includes(key) ? " (override)" : "");
  }
  setTimeout(() => simPanelPoll(id, seq), SIM_POLL_MS);
}

// ---------------------------------------------------------------------------
// Small helpers of the table

// The Last EMCY column: code, class and count; EMCY 0x0000 in neutral words.
function lastEmcyText(n) {
  if (!n || !n.emcy || !n.emcy.count) return "";
  if (n.emcy.code === 0) return el("span", { class: "muted", dataset: { emcyCleared: n.node_id } }, `cleared (0x0000) (${n.emcy.count})`);
  return `${hex4(n.emcy.code)} ${emcyClass(n.emcy.code)} (${n.emcy.count})`;
}

function lastHeardText(n) {
  if (!n) return "-";
  if (Number.isFinite(n.last_heard_s)) return `${n.last_heard_s.toFixed(1)} s ago`;
  if (Number.isFinite(n.last_heard_ms)) return `${(n.last_heard_ms / 1000).toFixed(1)} s ago`;
  return n.state === 0 || n.state === null || n.state === undefined ? "not heard" : "-";
}

// A row of the Nodes table opens the node in the tree, on its Status tab.
// The selected tab is kept from node to node, so stepping through nodes on
// the Object dictionary stays there; the first node opens on Status.
function openOnlineNode(id) {
  S.onlineNode = id;
  S.onlineTab = S.onlineTab || "status";
  renderOnlineNode();
  pollHighlight();
  onlineTop();
  const t = document.querySelector("#online-node [role=tablist] [aria-selected=true]");
  if (t) t.focus();
}

// Master and detail (commission-master-detail): a network entry shows the
// network's page (bus, SYNC, the Nodes table, LSS), a node entry only the
// node's page. A slave network's own device stays under its status.
function onlineLayout() {
  const node = $("#online-node");
  if (!node) return;
  const open = S.onlineNode !== null && S.onlineNode !== undefined;
  const both = open && !S.state.commission && onlineIsSlave();
  for (const p of document.querySelectorAll("[data-online-part=net]")) p.hidden = open && !both;
  node.hidden = !open;
}

// A page or tab opens at its top, with the tab row in view.
function onlineTop() {
  const view = $("#view");
  if (view) view.scrollTop = 0;
  if (document.scrollingElement) document.scrollingElement.scrollTop = 0;
}

// The Nodes table's selected row: the open node, or the node the user came back from.
function onlineRowActive(id) {
  return S.onlineNode === id || ((S.onlineNode === null || S.onlineNode === undefined) && S.onlineBackFrom === id);
}

// The node header's "← Nodes": the network's page, with the node's row selected.
function backToNodes() {
  S.onlineBackFrom = S.onlineNode;
  S.onlineNode = null;
  put($("#online-node"));
  if (typeof renderTree === "function") renderTree();
  onlineLayout();
  pollHighlight();
  onlineTop();
  const b = document.querySelector(`[data-open-node="${S.onlineBackFrom}"]`);
  if (b) b.focus();
}

// The live part of the node header: state as text and shape, last heard,
// boot result, hold and the simulated mark, in one line.
function nodeHeaderLive(id, sn) {
  const [cls, word] = liveMark(sn);
  const parts = [el("span", { dataset: { statusState: id } }, el("span", { class: "state-mark", "aria-hidden": "true" }, ...markIcons(cls)),
    sn && sn.state ? stateName(sn.state) : upperFirst(word)),
  el("span", { dataset: { online: "node-heard" } }, "last heard " + lastHeardText(sn))];
  if (sn && sn.heartbeat !== undefined) parts.push(el("span", null, "heartbeat " + String(sn.heartbeat)));
  if (sn && !connAdapter()) {
    const boot = sn.boot_error ? `boot error ${sn.boot_error}: ${sn.boot_error_text || ""}` : sn.booted ? "booted" : "not booted";
    parts.push(el("span", { class: sn.boot_error ? "bad" : null }, boot + (sn.retry_pending ? " (retrying)" : "")));
    if (sn.hold && sn.hold !== "none") parts.push(el("span", null, `held ${sn.hold === "stopped" ? "STOPPED" : "PRE-OPERATIONAL"} by ${sn.hold_by === "operator" ? "operator" : "the program"}`));
  }
  if (simulatedNode(id)) parts.push(el("span", { class: "tag" }, "simulated"));
  return el("span", { class: "node-live", dataset: { online: "node-status" } }, ...parts);
}

// Each poll keeps the header's live part current.
function refreshNodeHeader(st) {
  const box = document.querySelector('#online-node [data-online="node-status"]');
  if (!box || S.onlineNode === null || S.onlineNode === undefined) return;
  const sn = ((st && st.nodes) || []).find((n) => n.node_id === S.onlineNode);
  const fresh = nodeHeaderLive(S.onlineNode, sn);
  if (fresh.innerHTML !== box.innerHTML) box.replaceWith(fresh);
}

// ---------------------------------------------------------------------------
// A node's tabs in Commission

const COMMISSION_TABS = [["status", "Status"], ["od", "Object dictionary"], ["params", "Parameters"], ["pdo", "PDO test"],
  ["notes", "Notes"], ["log", "Log"]];

// The EDS whose notes a Commission node's Notes tab shows: (name, EDS) or nulls.
function commNotesEds(id, n) {
  const name = (n && n.eds) || (commNodes()[id] || {}).eds_name || (S.onlineEds || {})[id] || null;
  return [name, name ? (S.state.eds || {})[name] : null];
}

// The Notes tab's label: in Commission a device the count of the user's
// notes in the notes the object dictionary was read with.
function commNotesLabel(id, n) {
  if (!S.state.commission) return notesTabLabel(...commNotesEds(id, n));
  const c = (S.odEntries || {})[id];
  const device = c && c.data && c.data.notes && !c.data.notes.error ? c.data.notes.device || {} : {};
  const k = Object.values(device).filter(noteFilled).length;
  return k ? `Notes ${k}` : "Notes";
}

function commNotesTab(id, n) {
  const [name, eds] = commNotesEds(id, n);
  // With a config: the config's EDS, edited in the draft and written by Save.
  if (name && eds && !S.state.commission) return nodeNotesTab({ eds: name }, eds);
  const none = () => el("p", { class: "muted", dataset: { nodeNotes: "1" } }, "No notes: this node has no EDS on this page yet (pick one in the Nodes table).");
  if (!name) return none();
  // Commission a device: the notes the object dictionary is read with,
  // written at once to the notes file next to the EDS (there is no Save).
  const box = el("div", null, el("p", { class: "muted" }, "Loading…"));
  odEntries(id).then((data) => {
    if (!data || !data.notes || !data.entries) { box.replaceChildren(none()); return; }
    const objects = data.entries.map((e) => ({ index: hex4(e.index), subindex: e.subindex, name: e.sub_name || e.name, var: e.object_type === "VAR" }));
    const src = odSource(id);
    const live = S.state.commission && src.eds_path ? { id, path: src.eds_path, block: data.notes } : null;
    box.replaceChildren(nodeNotesTab({ eds: name }, { objects }, live ? null : data.notes, live));
  }).catch(() => box.replaceChildren(none()));
  return box;
}

function logLine(e) {
  const where = e.node !== null && e.node !== undefined ? "node " + e.node : "bus";
  return `${e.time.replace("T", " ").replace("Z", " UTC")}  ${where}  ${e.what}: ${e.result}`;
}

function nodeLogTab(id) {
  const list = (S.commLog || []).filter((e) => e.node === id);
  return el("div", { dataset: { nodeLog: id } },
    el("p", { class: "muted" }, "What happened to this node in this session: state changes, EMCY, boot results, timeouts, and every change made on this page. Kept on this page only."),
    list.length ? el("ol", { class: "log-list", dataset: { online: "node-log-list" } }, list.map((e) => el("li", { class: e.kind === "event" ? "event" : "change" }, logLine(e))))
      : el("p", { class: "muted", dataset: { online: "node-log-empty" } }, "Nothing yet."));
}
