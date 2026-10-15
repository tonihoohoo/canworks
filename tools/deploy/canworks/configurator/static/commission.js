"use strict";
// Commission a device (add-device-commissioning, rework-commission-and-trim-
// configurator, ui-shell-and-connection): the USB adapter form of the connect
// panel (with its bit rate check), the Nodes page (heard, scanned and added
// devices, LSS, the node page), the commissioning log in the bottom panel and
// "Add to a config…"; Write
// configuration and Restore defaults in a node's Parameters tab and the PDO
// test tab. Loaded after app.js and uses its helpers.

// -- commissioning log ------------------------------------------------------------
// Every change made through the page in Commission a device: UTC time, node,
// what and the result. Kept in the page for this commissioning session only:
// no host names or tokens, never written to a project.

// commission-workspace: the same log in the Commission workspace of a
// config (changes and bus events, never in Configure); in Commission a
// device it is also the commissioning record that Save log writes.
function commLogOn() {
  return !!(S.state && S.state.mode) && workspace() === "commission";
}

function commLog(node, what, result) {
  if (!commLogOn()) return;
  S.commLog = S.commLog || [];
  S.commLog.push({ time: new Date().toISOString().replace(/\.\d+Z$/, "Z"), node, net: connAdapter() ? null : onlineNetwork(),
    what, result, kind: "change" });
  refreshLog();
}

function logChanges() { return (S.commLog || []).filter((e) => e.kind !== "event"); }

// The device the log is about: the latest node something was done to.
function commDevice() {
  S.commDevice = S.commDevice || {};
  return S.commDevice;
}

// Devices of this commissioning session that were not heard or scanned:
// added from an EDS, or given a node ID by LSS. {node_id: {eds_path, eds_name, identity…}}
function commNodes() {
  S.commNodes = S.commNodes || {};
  return S.commNodes;
}

function upperFirst(t) { return t ? t.charAt(0).toUpperCase() + t.slice(1) : t; }

// Called by api() after each request: the changes for the log.
function commLogApi(path, body, ok, data) {
  const route = path.replace(/^\/api\/online\//, "");
  if (route === path) return;
  body = body || {};
  const fail = ok ? null : (data && data.error) || "failed";
  const node = body.node ?? null;
  if (route === "sdo_write") {
    const r = fail || (data.success ? "written" : data.abort_code !== undefined ? `abort ${hex8(data.abort_code)}: ${data.abort_text}` : data.reason || "failed");
    commLog(node, `SDO write ${hex4(num(body.index))} sub ${num(body.subindex || 0)} = ${body.value}`, r);
  } else if (route === "nmt") {
    commLog(node, `NMT ${body.command}`, fail || "sent");
  } else if (route === "error_field_clear") {
    commLog(node, "Clear error history (0x1003 sub 0 = 0)", fail || "cleared");
  } else if (route === "lss_set_id") {
    const a = body.address || {};
    commLog(node, `LSS set node ID ${node} (serial number ${hex8(a.serial_number)})${body.store ? " and store" : ""}`,
      fail || (data.stored ? "set and stored" : "set"));
    if (!fail) {
      Object.assign(commDevice(), { node_id: node, vendor_id: a.vendor_id, product_code: a.product_code,
        revision_number: a.revision_number, serial_number: a.serial_number, lss: true });
    }
  } else if (route === "lss_set_bitrate") {
    commLog(null, `LSS set bit rate ${body.bitrate_kbit} kbit/s${body.store ? " and store" : ""}`, fail || (data.stored ? "set and stored" : "set"));
  } else if (route === "store") {
    commLog(node, `Store on device (0x1010 sub ${body.subindex})`, fail || (data.stored ? "stored" : `not stored: ${data.error}`));
  } else if (route === "restore_defaults") {
    commLog(node, `Restore defaults (0x1011 sub ${body.subindex || 1})${body.reset ? " and reset" : ""}`,
      fail || (data.restored ? (data.reset ? "restored, node reset" : "restored") : `not restored: ${data.error}`));
  }
}

// Called by followJob() when a job ends: jobs that change the device.
function commLogJob(j) {
  const r = j.result;
  if (j.kind === "configure") {
    if (j.state === "failed") { commLog(j.node, "Write configuration", j.error); return; }
    if (!r) return;
    const what = `Write configuration from ${r.plan ? r.plan.source.name : "a source"}${r.restored ? " (defaults restored first)" : ""}`;
    const res = `${r.written.length} written, ${r.failed.length} failed, ${r.cancelled ? "cancelled" : r.verified ? "read-back verified" : "read-back differs"}`;
    commLog(j.node, what, res);
    if (r.store) commLog(j.node, "Store on device (0x1010)", r.store.stored ? "stored" : `not stored: ${r.store.error}`);
    if (r.plan && r.plan.source.identity) Object.assign(commDevice(), { node_id: j.node });
  } else if (j.kind === "restore") {
    if (j.state === "failed") { commLog(j.node, "Restore from a backup", j.error); return; }
    if (r) commLog(j.node, "Restore from a backup", `${r.written.length} written, ${r.failed.length} failed${r.cancelled ? ", cancelled" : ""}`);
  }
}

function downloadText(text, name) {
  const url = URL.createObjectURL(new Blob([text], { type: "text/plain" }));
  const a = el("a", { href: url, download: name });
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 10000);
}

function commLogText() {
  const d = commDevice();
  const log = S.commLog || [];
  const node = d.node_id ?? (log.length ? log[log.length - 1].node : null) ?? S.onlineNode ?? null;
  const lines = ["CANopen commissioning log", ""];
  lines.push(`Device: ${node !== null ? "node " + node : "node not known"}`);
  const ids = [["vendor_id", "Vendor ID"], ["product_code", "Product code"], ["revision_number", "Revision"], ["serial_number", "Serial number"]]
    .filter(([k]) => d[k] !== undefined && d[k] !== null).map(([k, label]) => `${label} ${hex8(d[k])}`);
  if (ids.length) lines.push("Identity: " + ids.join(", "));
  const eds = d.eds_name || (node !== null && (S.onlineEdsName || {})[node]) || (node !== null && configNode(node) ? configNode(node).eds : null);
  lines.push(`EDS: ${eds || "not known"}`);
  const st = S.onlineLast && S.onlineLast.status;
  if (st && st.local && st.bitrate) lines.push(`Bit rate: ${Math.round(st.bitrate / 1000)} kbit/s`);
  lines.push("");
  const shown = S.logEvents ? log : log.filter((e) => e.kind !== "event");
  for (const e of shown) lines.push(`${e.time}  ${e.node !== null && e.node !== undefined ? "node " + e.node : "bus"}  ${e.kind === "event" ? "(bus) " : ""}${e.what}: ${e.result}`);
  if (!shown.some((e) => e.kind !== "event")) lines.push("No change was made.");
  return { text: lines.join("\n") + "\n", node };
}

// With a config: the session's changes (and bus events when ticked) of the runtime's network.
function commissionLogText() {
  const log = S.commLog || [];
  const shown = S.logEvents ? log : log.filter((e) => e.kind !== "event");
  const lines = [`Commission log of ${S.state.name || S.state.folder || "the config"}`, ""];
  const net = onlineNetwork();
  if (net) lines.push(`Network: ${net}`, "");
  for (const e of shown) lines.push(`${e.time}  ${e.node !== null && e.node !== undefined ? "node " + e.node : "bus"}  ${e.kind === "event" ? "(bus) " : ""}${e.what}: ${e.result}`);
  if (!shown.length) lines.push(S.logEvents ? "Nothing happened." : "No change was made.");
  return lines.join("\n") + "\n";
}

function saveCommLog() {
  const t = new Date().toISOString().replace(/[-:]/g, "").replace(/\.\d+Z$/, "Z").replace("T", "-");
  if (S.state.commission) {
    const { text, node } = commLogText();
    downloadText(text, `node${node ?? "x"}-commissioning-${t}.txt`);
  } else {
    const stem = String(S.state.name || (S.state.folder || "config").split(/[\\/]/).filter(Boolean).pop() || "config").replace(/[^A-Za-z0-9_.-]+/g, "_");
    downloadText(commissionLogText(), `${stem}-commission-${t}.txt`);
  }
  for (const e of S.commLog || []) e.saved = true;
  refreshLog();
}

function unsavedLog() { return logChanges().filter((e) => !e.saved).length; }

// Leaving Commission a device (Close, "Add to a config…"): asks to save the
// log when it has unsaved entries, then starts the next session's log
// empty. False when the user cancels.
async function leaveCommission(what) {
  if (!commLogOn()) return true;
  // With a config the log lives in this page only; it is not a record to keep.
  const n = S.state.commission ? unsavedLog() : 0;
  if (n) {
    const v = await modal(`The commissioning log has ${n} change${n === 1 ? "" : "s"} that ${n === 1 ? "was" : "were"} not saved. Save it before ${what}?`,
      [["save", "Save log", true], ["discard", "Don't save"], ["cancel", "Cancel"]]);
    if (!v || v === "cancel") return false;
    if (v === "save") saveCommLog();
  }
  S.commLog = [];
  S.commLogSaved = 0;
  S.logPrev = null;
  S.commDevice = {};
  S.commNodes = {};
  S.adapterOn = false;
  S.adapterEnded = null;
  return true;
}

function logText() {
  const n = logChanges().length;
  const u = unsavedLog();
  return `${n} change${n === 1 ? "" : "s"} in the log` + (n ? (u ? `, ${u} not saved` : ", saved") : "");
}

const LOG_FILTERS = [["all", "All"], ["changes", "Changes"], ["events", "Events"]];

function logFiltered() {
  const log = S.commLog || [];
  if (S.logFilter === "changes") return log.filter((e) => e.kind !== "event");
  if (S.logFilter === "events") return log.filter((e) => e.kind === "event");
  return log;
}

function logBox() {
  const include = el("input", { type: "checkbox", checked: !!S.logEvents, dataset: { online: "log-events" } });
  include.addEventListener("change", () => { S.logEvents = include.checked; });
  return el("div", { dataset: { online: "log" } },
    el("div", { class: "toolbar" },
      el("div", { class: "segmented", role: "group", "aria-label": "Show", dataset: { online: "log-filter" } },
        LOG_FILTERS.map(([k, label]) => el("button", { type: "button", "aria-pressed": String((S.logFilter || "all") === k), dataset: { logFilter: k },
          onclick: () => { S.logFilter = k; refreshLog(); } }, label))),
      el("span", { class: "muted", dataset: { online: "log-count" } }, logText()),
      el("div", { class: "spacer" }),
      el("label", { class: "check", title: "Save log writes the changes; tick to add the bus events (state changes, EMCY, timeouts)" }, include, " Include bus events"),
      el("button", { type: "button", dataset: { online: "save-log" }, onclick: saveCommLog }, "Save log")),
    hint(S.state && S.state.commission
      ? "Every change made on this page (SDO writes, NMT, LSS, Write configuration, store, restore) and what the bus did, with its time and result. It stays on this page until you save it; leaving Commission a device asks first."
      : "What happened on the bus in this session (state changes, EMCY, boot results, timeouts) and every change made in Commission. Kept on this page only, never in the project."),
    el("ol", { class: "log-list", dataset: { online: "log-list" } }));
}

function refreshLog() {
  for (const c of document.querySelectorAll("[data-online=log-count]")) c.textContent = logText();
  const n = (S.commLog || []).length;
  const count = $("#log-count");
  if (count) count.textContent = n ? String(n) : "";
  const counts = { all: n, changes: logChanges().length, events: n - logChanges().length };
  for (const b of document.querySelectorAll("[data-log-filter]")) {
    const k = b.dataset.logFilter;
    b.setAttribute("aria-pressed", String((S.logFilter || "all") === k));
    b.textContent = `${LOG_FILTERS.find((x) => x[0] === k)[1]} ${counts[k]}`;
  }
  const list = document.querySelector("[data-online=log-list]");
  if (list) list.replaceChildren(...logFiltered().map((e) => el("li", { class: e.kind === "event" ? "event" : "change" }, logLine(e))));
  // The open node's Log tab, and its count on the tab.
  const nodeLog = document.querySelector("[data-node-log]");
  if (nodeLog && S.onlineNode !== null && S.onlineNode !== undefined) nodeLog.replaceWith(nodeLogTab(S.onlineNode));
  const tab = document.querySelector('[data-online-tab="log"]');
  if (tab && S.onlineNode !== null && S.onlineNode !== undefined) {
    const k = (S.commLog || []).filter((e) => e.node === S.onlineNode).length;
    tab.textContent = k ? `Log ${k}` : "Log";
  }
}

// -- The USB adapter connection: the connect panel's form ---------------------------
// S.adapterOn: Connect was pressed and the bit rate check passed; the
// connection is open. S.adapterEnded: why the last connection was refused
// or ended, shown in the connection bar.

const CHECK_TEXT = { traffic: "frames on the bus", "probe acknowledged": "a device acknowledged the probe" };

// The adapter (found ones, or typed), bit rate, the node ID for the check
// on adapters that cannot confirm a sent frame, Allow changes, Connect and
// Disconnect. The adapter, bit rate and node ID are fixed while connected.
function adapterBox(message) {
  const on = !!S.adapterOn;
  const list = el("select", { "aria-label": "Found adapters", disabled: on, dataset: { online: "adapter-list" } },
    el("option", { value: "" }, "Looking for adapters…"));
  const input = el("input", { type: "text", spellcheck: "false", disabled: on, placeholder: "gs_usb:0 or slcan:COM5",
    title: "For example gs_usb:0, slcan:COM5, slcan:/dev/tty.usbmodem14101 or socketcan:can0",
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
  const refresh = el("button", { type: "button", class: "small", disabled: on, onclick: fill }, "Refresh");
  if (!on) fill();
  const rate = el("select", { "aria-label": "Bit rate", disabled: on, dataset: { online: "adapter-bitrate" } },
    el("option", { value: "" }, "Pick the bus's bit rate…"), LSS_BITRATES.map((b) => el("option", { value: b }, `${b} kbit/s`)));
  rate.value = String(S.online.adapter_bitrate || "");
  const checkNode = el("input", { type: "number", min: 1, max: 127, class: "short", disabled: on, placeholder: "none",
    "aria-label": "Node ID for the bit rate check", dataset: { online: "check-node" } });
  checkNode.value = S.online.check_node ? String(S.online.check_node) : "";
  const allowed = on && S.onlineLast && S.onlineLast.status && S.onlineLast.status.local ? !!S.onlineLast.status.allow_changes : !!S.online.allow_changes;
  const allow = el("input", { type: "checkbox", checked: allowed, dataset: { online: "adapter-allow" } });
  allow.addEventListener("change", async () => {
    if (allow.checked && on) {
      const v = await modal("Allow changes on this adapter connection? SDO writes, NMT commands, LSS and restore then go to the bus. Saving to a device's non-volatile memory still asks each time.",
        [["allow", "Allow changes", true], ["cancel", "Cancel"]]);
      if (v !== "allow") { allow.checked = false; return; }
    }
    if (!(await saveOnline({ allow_changes: allow.checked }))) { allow.checked = !allow.checked; return; }
    if (on) render();
  });
  const msg = el("p", { class: "field-msg", dataset: { online: "connect-msg" } }, message ? upperFirst(message) + "." : "");
  const connect = el("button", { type: "button", class: "primary", hidden: on, dataset: { online: "connect" }, onclick: () => busy(connect, "Checking the bit rate…", async () => {
    if (!input.value.trim()) { msg.textContent = "Pick or type the adapter first."; input.focus(); return; }
    if (!rate.value) { msg.textContent = "Pick the bus's bit rate first."; rate.focus(); return; }
    const node = checkNode.value.trim() ? Number(checkNode.value) : null;
    if (node !== null && !(Number.isInteger(node) && node >= 1 && node <= 127)) { msg.textContent = "The node ID for the check must be 1-127."; checkNode.focus(); return; }
    if (!(await saveOnline({ adapter: input.value.trim(), adapter_bitrate: Number(rate.value), check_node: node }))) return;
    if (allow.checked && !(await saveOnline({ allow_changes: true }))) return;
    msg.textContent = "";
    S.adapterOn = true;
    S.adapterEnded = null;
    S.onlineLast = null;
    if (typeof pdoAutoReset === "function") pdoAutoReset();
    connStop();
    connBar();
    // The first status opens the adapter and runs the bit rate check: a
    // refusal keeps the panel open with the reason and the form filled in.
    try {
      const r = await api("POST", "/api/online/status", { port: diagPort() });
      if (r.recent) S.online.recent = r.recent;
      S.onlineLast = r;
      S.onlineLastAt = Date.now();
    } catch (e) {
      S.adapterOn = false;
      S.adapterEnded = e.message;
      msg.textContent = upperFirst(e.message) + ".";
      connBar();
      return;
    }
    closeConnect();
    render();
    connKick();
    // The form is gone once connected: the keyboard goes on with the scan.
    if (document.activeElement === document.body || !document.activeElement.isConnected) {
      const next = document.querySelector('#view [data-online="scan"]') || document.querySelector('#conn-bar [data-conn="disconnect"]');
      if (next) next.focus();
    }
  }) }, "Connect");
  const disconnect = el("button", { type: "button", hidden: !on, dataset: { online: "disconnect" }, onclick: async () => { closeConnect(); await disconnectAdapter(); } }, "Disconnect");
  return el("fieldset", { dataset: { online: "adapter-box" } }, el("legend", null, "USB adapter"),
    el("p", { class: "muted" }, "The PC talks to the bus itself through the adapter: no runtime is needed. Connect checks the bit rate first and refuses a wrong one; after that the PC sends nothing until you act, never SYNC, heartbeat or NMT to all nodes, and warns when another master runs on the bus."),
    el("div", { class: "grid" },
      el("label", null, "Adapter", el("div", { class: "row" }, list, refresh), input,
        hint("TYPE:CHANNEL. gs_usb (candleLight) and slcan (CANable) on Windows, macOS and Linux, socketcan on Linux; other python-can types are passed through untested. Kept on this PC.")),
      el("label", null, "Bit rate", rate,
        hint("The bus's bit rate. Connect listens first without sending: frames confirm the rate and error frames refuse it. On a silent bus it sends one LSS query, which a device acknowledges only at its own bit rate.")),
      el("label", null, "Node ID for the check", checkNode,
        hint("Only for an adapter that cannot tell whether its frame got out (slcan): on a silent bus, this node answers an SDO read of 0x1000 when the bit rate is right.")),
      el("div", { class: "check-field" }, el("label", { class: "check" }, allow, " Allow changes (SDO writes, NMT, LSS, restore)"),
        hint("Off by default and for every new connection: read-only. Turning it on or off keeps the connection open."))),
    msg, el("div", { class: "toolbar" }, connect, disconnect));
}

async function disconnectAdapter() {
  connStop();
  try {
    S.online = Object.assign(S.online, await api("POST", "/api/online/disconnect", {}));
  } catch (e) { banner(e.message, true); }
  S.adapterOn = false;
  S.adapterEnded = null;
  S.onlineOpen = false;
  S.onlineLast = null;
  S.lssAllow = undefined;
  if (typeof pdoAutoReset === "function") pdoAutoReset();
  render();
}

// A refused bit rate check or an ended connection: polling stops, the
// reason stays in the connection bar, and Connect checks again.
function adapterLost(message) {
  if (S.adapterOn && typeof commEvent === "function") commEvent(null, null, "Connection ended", message);
  S.logPrev = null;
  connStop();
  S.adapterOn = false;
  S.adapterEnded = message;
  if (typeof pdoAutoReset === "function") pdoAutoReset();
  S.onlineOpen = false;
  S.onlineLast = null;
  S.lssAllow = undefined;
  render();
}

function checkText(c) {
  if (!c) return "";
  const how = CHECK_TEXT[c.how] || c.how;
  return `bit rate ${c.bitrate_kbit} kbit/s confirmed (${how})`;
}

// The status answer on the commissioning pages: the connection line and
// the bus on Bus and master, the node table on Nodes.
function localLive(r, conn) {
  const st = r.status;
  const kbit = Math.round((st.bitrate || 0) / 1000);
  const allow = !!st.allow_changes;
  const other = st.other_master_seen;
  conn.className = "online-conn ok";
  const line = el("div", null, `Connected to USB adapter ${st.adapter} at ${kbit} kbit/s, ${checkText(st.bitrate_check) || "bit rate checked"}, ` +
    (allow ? "changes allowed." : "read-only."),
  other ? el("div", { class: "online-note warning", dataset: { online: "other-master" } },
    `Another master is active on this bus (${other.what}, since ${other.first_at.replace("T", " ").replace(/\.\d+Z$/, " UTC")}). ` +
    "Keep to reading; LSS asks before it runs.") : null,
  st.untested_adapter ? el("div", { class: "online-note" }, "This adapter type is passed to python-can untested.") : null);
  if (conn.dataset.html !== line.innerHTML) { conn.dataset.html = line.innerHTML; conn.replaceChildren(...line.childNodes); }
  const box = document.querySelector("[data-online=adapter-allow]");
  if (box && document.activeElement !== box) box.checked = allow;
  const live = $("#online-live");
  if (S.view === "nodes") { patchLive(live, [commNodeTable(st)]); return; }
  const bus = st.bus || {};
  patchLive(live, [el("table", { class: "online-bus", dataset: { online: "local-bus" } }, el("tbody", null,
    el("tr", null, el("th", null, "Adapter state"), el("td", { dataset: { online: "bus" } }, bus.adapter_state || "active"),
      el("th", null, "Frames"), el("td", { dataset: { online: "frames" } }, String(bus.frames ?? "-")),
      el("th", null, "Error frames"), el("td", { dataset: { online: "error-frames" } }, String(bus.error_frames ?? "-")),
      el("th", null, "Other master"), el("td", { dataset: { online: "other" } }, other ? other.what : "none seen"))))]);
}

// -- Nodes: heard, scanned and added devices ------------------------------------------

// What the EDS library holds, from the settings reply's bounded count.
function edsLibraryCount(o) {
  if (!o.eds_library) return "";
  if (o.eds_count_capped) return `Large folder: ${o.eds_count} EDS files found so far, scans may be slow.`;
  if (!o.eds_count) return "No EDS files in this folder or its subfolders.";
  return o.eds_count === 1 ? "1 EDS file (with subfolders)." : `${o.eds_count} EDS files (with subfolders).`;
}

// The EDS library folder (browse-eds-library-folder): the chosen folder as
// text, Choose folder… and Clear. A change re-matches the scanned devices.
function edsLibraryRow() {
  const row = el("div", { class: "eds-library-wrap", dataset: { online: "library-row" } });
  const set = async (path) => {
    try { S.online = Object.assign(S.online, await api("POST", "/api/online/settings", { eds_library: path })); banner(""); }
    catch (e) { banner(e.message, true); return; }
    draw();
    if (S.scanResult && S.adapterOn) runScan(false);  // the shown devices, matched against the new folder
  };
  const choose = el("button", { type: "button", dataset: { online: "library-choose" }, onclick: async () => {
    const path = await chooseFolder({ title: "Choose the EDS library folder", start: S.online.eds_library || "",
      note: "Scanned devices are matched against the EDS files in this folder and its subfolders." });
    if (path !== null) await set(path);
    choose.focus();
  } }, "Choose folder…");
  const clear = el("button", { type: "button", dataset: { online: "library-clear" }, onclick: async () => {
    await set("");
    choose.focus();
  } }, "Clear");
  const pathText = el("span", { class: "lib-path", dataset: { online: "library" } });
  const count = el("span", { class: "muted", dataset: { online: "library-count" }, "aria-live": "polite" });
  function draw() {
    const p = S.online.eds_library || "";
    pathText.textContent = p || "None chosen";
    pathText.title = p;
    pathText.classList.toggle("muted", !p);
    clear.hidden = !p;
    count.textContent = edsLibraryCount(S.online);
  }
  draw();
  row.append(el("div", { class: "eds-library", role: "group", "aria-labelledby": "eds-library-label" },
    el("strong", { id: "eds-library-label" }, "EDS library"), pathText, choose, clear, count),
  hint("Optional. Scanned devices are matched against the EDS files in this folder and its subfolders. Kept on this PC."));
  return row;
}

function renderCommNodes(view) {
  view.append(el("h2", null, "Nodes"));
  const lib = edsLibraryRow();
  const file = el("input", { type: "file", accept: ".eds,.EDS", dataset: { online: "add-eds-file" } });
  file.addEventListener("change", () => { const f = file.files[0]; file.value = ""; if (f) addCommNode(f); });
  const progress = el("span", { class: "muted", dataset: { online: "scan-progress" }, "aria-live": "polite" });
  const scan = el("button", { type: "button", class: "primary", hidden: !S.adapterOn, dataset: { online: "scan" }, onclick: () => startScan() }, "Scan the bus");
  const cancel = el("button", { type: "button", hidden: true, dataset: { online: "scan-cancel" }, onclick: stopScan }, "Cancel");
  view.append(
    el("div", { class: "toolbar" }, scan, cancel, progress,
      el("label", { class: "file-button", dataset: { online: "add-eds" } }, "Add node from EDS…", file)),
    lib,
    el("div", { id: "online-conn", class: "online-conn", hidden: true }),
    el("div", { id: "online-live" }, commNodeTable(null)),
    el("div", { id: "online-lss" }),
    el("div", { id: "online-node" }));
  if (!S.adapterOn) {
    view.querySelector("#online-live").before(nodesNotConnected());
    view.querySelector("#online-live").hidden = true;
    if (S.onlineNode) renderOnlineNode();
    return;
  }
  S.lssAllow = undefined;
  S.onlineOpen = true;
  connKick();
  runScan(false);
  if (S.onlineNode) renderOnlineNode();
}

// One row per node ID: heard on the bus (heartbeat, EMCY), found by the
// scan, given a node ID by LSS here, or added from an EDS here.
function commNodeTable(st) {
  const heard = new Map(((st && st.nodes) || []).map((n) => [n.node_id, n]));
  const scanned = new Map(((S.scanResult && S.scanResult.nodes) || []).map((d) => [d.node_id, d]));
  const added = commNodes();
  const ids = [...new Set([...heard.keys(), ...scanned.keys(), ...Object.keys(added).map(Number)])].sort((a, b) => a - b);
  const rows = ids.map((id) => {
    const n = heard.get(id);
    const d = scanned.get(id);
    const a = added[id];
    const em = n && n.emcy && n.emcy.count ? `${hex4(n.emcy.code)} ${emcyClass(n.emcy.code)} (${n.emcy.count})` : "";
    const device = d ? [d.device_name, d.vendor_id !== undefined ? `vendor ${hex8(d.vendor_id)}` : "", d.product_code !== undefined ? `product ${hex8(d.product_code)}` : ""]
      .filter(Boolean).join(", ") : a && a.lss ? `serial number ${hex8(a.serial_number)} (LSS)` : "";
    const found = [n && n.state !== null ? "heard" : "", d ? "scanned" : "", a ? (a.lss ? "LSS" : "added") : ""].filter(Boolean).join(", ");
    const eds = (S.onlineEdsName || {})[id] || (S.onlineEds || {})[id];
    // A button per row, not a clickable row: the EDS cell has controls of its own.
    return el("tr", { class: S.onlineNode === id ? "active" : null, dataset: { onlineNode: id } },
    el("td", null, el("button", { type: "button", class: "small", "aria-label": `Open node ${id}`, dataset: { openNode: id },
      onclick: () => openOnlineNode(id) }, String(id))),
    el("td", null, device),
    el("td", null, el("span", { class: "state-mark", "aria-hidden": "true" }, ...markIcons(liveMark(n)[0])),
      !n || n.state === null ? "not heard" : stateName(n.state)),
    el("td", null, n && n.last_heard_s !== null ? `${n.last_heard_s.toFixed(1)} s ago` : "-"), el("td", null, em),
    el("td", null, found),
    el("td", null, eds ? el("span", { dataset: { nodeEds: id } }, eds) : edsPick(d || { node_id: id })));
  });
  return el("table", { class: "online-nodes", dataset: { online: "comm-nodes" } },
    el("thead", null, el("tr", null, thCells(["Node", "Device", "State", "Heard", "Last EMCY", "Found by", "EDS"]))),
    el("tbody", null, rows.length ? rows : [el("tr", null, el("td", { colspan: 7, class: "muted" },
      "No device yet. Devices with a heartbeat show up here; scan the bus for the others, or add one from its EDS."))]));
}

// A device without an EDS: the library's matches from the scan, or an EDS file.
function edsPick(d) {
  const m = d.eds_matches || [];
  if (m.length) {
    const pick = el("select", { "aria-label": "EDS file", dataset: { online: "eds-match" } }, m.map((x, k) => el("option", { value: k }, x.name)));
    return el("div", null, pick, el("button", { type: "button", class: "small", dataset: { online: "use-eds" },
      onclick: () => openScannedOd(d, m[Number(pick.value)]) }, "Use"));
  }
  const input = el("input", { type: "file", accept: ".eds,.EDS", dataset: { online: "pick-eds" } });
  input.addEventListener("change", () => { const f = input.files[0]; if (f) openPickedOd(d, f); });
  return el("label", { class: "file-button small" }, "Pick EDS file…", input);
}

// "Add node from EDS…": a node ID and the device's EDS, for this page only.
async function addCommNode(file) {
  const idInput = el("input", { type: "number", min: 1, max: 127, class: "short", dataset: { online: "add-node-id" } });
  const msg = el("p", { class: "field-msg" });
  let id;
  for (;;) {
    const v = await modal(`Add a node with ${file.name}. It is on this page only, to read and write the device; "Add to a config…" on its page puts it in a config.`,
      [["add", "Add node", true], ["cancel", "Cancel"]], el("div", null, el("label", { class: "inline" }, "Node ID ", idInput), msg));
    if (v !== "add") return;
    id = Number(idInput.value);
    if (/^\s*\d+\s*$/.test(idInput.value) && id >= 1 && id <= 127) break;
    msg.textContent = "The node ID must be 1-127.";
  }
  let res;
  try {
    res = await api("POST", "/api/eds", { name: file.name, data: await readBase64(file), on_conflict: "keep_both", eds_lint: edsLint() });
  } catch (e) { banner(e.message, true); return; }
  commNodes()[id] = Object.assign(commNodes()[id] || {}, { eds_path: res.name, eds_name: res.name });
  openScannedOd({ node_id: id }, { path: res.name, name: res.name });
}

async function stopScan() {
  try { await api("POST", "/api/online/scan_stop", { port: diagPort() }); }
  catch (e) { banner(e.message, true); }
}

// The device of node `id` as this session knows it, for "Add to a config…".
function commDeviceOf(id) {
  const d = { node_id: id };
  const sc = ((S.scanResult && S.scanResult.nodes) || []).find((x) => x.node_id === id);
  if (sc) for (const k of LSS_KEYS) if (sc[k] !== undefined) d[k] = sc[k];
  Object.assign(d, commNodes()[id] || {});
  if (!d.eds_path && (S.onlineEds || {})[id]) { d.eds_path = S.onlineEds[id]; d.eds_name = (S.onlineEdsName || {})[id] || S.onlineEds[id]; }
  return d;
}

// "Add to a config…" on a node's page: opens a project or standalone config
// folder with the device added as an unsaved node, after asking to save the log.
async function addToConfig(id) {
  const d = commDeviceOf(id);
  const path = el("input", { type: "text", class: "wide", spellcheck: "false", id: "add-folder-path", dataset: { online: "add-folder" } });
  // Browse…: the folder dialog over this one; an editor project sets the kind.
  const browseBtn = el("button", { type: "button", dataset: { online: "add-folder-browse" }, onclick: async () => {
    const p = await chooseFolder({ title: "Choose the config folder", start: path.value.trim(),
      note: "A standalone config folder (with canworks.json) or an OpenPLC Editor project folder." });
    if (p === null) return;
    path.value = p;
    try {
      const r = await api("GET", "/api/folders?path=" + encodeURIComponent(p));
      if (r.project) mode.value = "project";
      else if (r.config) mode.value = "standalone";
    } catch (e) { /* checked again when the folder opens */ }
  } }, "Browse…");
  const mode = el("select", { "aria-label": "Folder kind", dataset: { online: "add-mode" } },
    el("option", { value: "standalone" }, "standalone config folder"), el("option", { value: "project" }, "editor project"));
  const file = d.eds_path ? null : el("input", { type: "file", accept: ".eds,.EDS", "aria-label": "EDS file", dataset: { online: "add-eds" } });
  const v = await modal(`Add node ${d.node_id} to a config. The folder opens with the device added as an unsaved node` +
    (d.lss ? " with its serial number and LSS assignment ticked." : "."),
  [["add", "Open and add", true], ["cancel", "Cancel"]],
  el("div", null, el("label", { for: "add-folder-path" }, "Folder"),
    el("div", { class: "folder-field" }, path, browseBtn), el("label", { class: "inline" }, " ", mode),
    file ? el("div", null, el("label", null, "The device's EDS file ", file)) : el("p", { class: "muted" }, `EDS: ${d.eds_name || d.eds_path}`)));
  if (v !== "add") return;
  const folder = path.value.trim();
  if (!folder) { banner("Type the config folder.", true); return; }
  const f = file ? file.files[0] : null;
  if (file && !f) { banner("Pick the device's EDS file.", true); return; }
  // Checked before the folder opens, so this page and its log stay.
  try {
    if ((await api("POST", "/api/folder_nodes", { path: folder })).nodes.includes(d.node_id)) {
      banner(`The config in ${folder} already has node ${d.node_id}: give the device another node ID (Set node ID), or pick another config.`, true);
      return;
    }
  } catch (e) { banner(e.message, true); return; }
  if (!(await leaveCommission("opening the config"))) return;
  try {
    banner("");
    stopOnline(false);
    await api("POST", "/api/open", { path: folder, mode: mode.value });
    S.view = "bus";
    S.scanResult = null;
    S.onlineNode = null;
    S.lssDevice = null;
    await loadState();
  } catch (e) { banner(e.message, true); return; }
  if (configNode(d.node_id)) { banner(`The config already has node ${d.node_id}.`, true); return; }
  const before = (S.config.nodes || []).length;
  await addScannedNode(d, d.eds_path ? { path: d.eds_path, name: d.eds_name } : null, f, false, !!d.lss);
  const node = (S.config.nodes || [])[before];
  if (node && d.serial_number !== undefined && d.serial_number !== null && node.serial_number === undefined) {
    node.serial_number = d.serial_number;
    changed(true);
  }
}

// -- Write configuration and Restore defaults in the Parameters tab --------------------

function configureBox(id, n, allow, status, out) {
  const why = allow ? null : NO_CHANGES;
  const nodes = onlineIsSlave() ? [] : (onlineConfig().nodes || []).filter((x) => x && x.eds);
  const own = nodes.find((x) => num(x.node_id) === id);
  const src = el("select", { "aria-label": "Source", dataset: { online: "configure-source" } },
    nodes.map((x) => el("option", { value: "node:" + num(x.node_id) }, `node ${num(x.node_id)}${x.name ? " " + x.name : ""} of this config`)),
    el("option", { value: "folder" }, "a node of a config folder…"),
    el("option", { value: "dcf" }, "a DCF file"));
  src.value = own ? "node:" + id : nodes.length ? "node:" + num(nodes[0].node_id) : "dcf";
  const file = el("input", { type: "file", accept: ".dcf,.DCF", "aria-label": "DCF file", dataset: { online: "configure-file" } });
  const folder = el("input", { type: "text", spellcheck: "false", class: "wide", placeholder: "config folder on this PC", "aria-label": "Config folder", dataset: { online: "configure-folder" } });
  const fromNode = el("input", { type: "number", min: 1, max: 127, class: "short", value: id, "aria-label": "Node in that config", dataset: { online: "configure-from" } });
  const folderBox = el("span", { class: "row" }, folder, el("label", { class: "inline" }, "node ", fromNode));
  const sync = () => { file.hidden = src.value !== "dcf"; folderBox.hidden = src.value !== "folder"; };
  src.addEventListener("change", sync);
  sync();
  const body = async () => {
    const b = { node: id, port: diagPort() };
    if (src.value === "dcf") {
      const f = file.files[0];
      if (!f) { banner("Choose the DCF file to write.", true); return null; }
      return Object.assign(b, { source: "dcf", file: await fileBase64(f), file_name: f.name });
    }
    if (src.value === "folder") {
      if (!folder.value.trim()) { banner("Type the config folder.", true); return null; }
      return Object.assign(b, { source: "config", config_path: folder.value.trim(), from_node: Number(fromNode.value) });
    }
    return Object.assign(b, { source: "config", from_node: Number(src.value.slice(5)), config: fileConfig() });
  };
  // A node of this page's draft: the server names the saved file, which
  // unsaved changes make the wrong name.
  const named = (j, b) => {
    if (b.config && S.dirty && j.result && j.result.source) j.result.source.name = `node ${b.from_node} of this page's configuration (unsaved changes)`;
    return j;
  };
  const write = async () => {
    const b = await body();
    if (!b) return;
    put(out);
    startJob("/api/online/configure_plan", b, status, (j) => configureDialog(id, named(j, b), b, status, out));
  };
  const verify = async () => {
    const b = await body();
    if (!b) return;
    put(out);
    startJob("/api/online/configure_verify", b, status, (j) => showVerify(named(j, b).result, out));
  };
  return el("fieldset", { dataset: { online: "configure-box" } }, el("legend", null, "Write configuration"),
    el("div", { class: "toolbar" }, el("label", { class: "inline" }, "From ", src), file, folderBox),
    el("div", { class: "toolbar" },
      el("button", { type: "button", disabled: !allow, title: why, dataset: { online: "configure" }, onclick: write }, "Write configuration…"),
      el("button", { type: "button", dataset: { online: "configure-verify" }, onclick: verify }, "Verify")),
    hint("Writes a node's configuration (PDOs, heartbeat, startup SDOs) to the device, for a device that keeps its own configuration. Shows the plan first. Verify compares without writing. Nothing is stored on the device unless you tick it."));
}

async function configureDialog(id, j, body, status, out) {
  const p = j.result;
  const refuse = (p.identity || []).filter((i) => i.level === "refuse");
  const hold = el("input", { type: "checkbox", checked: true, dataset: { online: "configure-hold" } });
  const restore = el("input", { type: "checkbox", dataset: { online: "configure-restore" } });
  const store = el("input", { type: "checkbox", dataset: { online: "configure-store" } });
  const other = el("input", { type: "checkbox", dataset: { online: "configure-other" } });
  const subs = p.store_subindices || [];
  const storeSub = subs.length > 1 ? el("select", { "aria-label": "What to store", dataset: { online: "configure-store-sub" } },
    subs.map((s) => el("option", { value: s }, `sub ${s}`))) : null;
  const rows = [];
  let group = null;
  for (const s of p.steps) {
    if (s.group !== group) {
      group = s.group;
      if (group) {
        const sending = p.steps.some((x) => x.group === group && x.send);
        rows.push(el("tr", { class: "group-row", dataset: { configureGroup: group } }, el("th", { colspan: 6, scope: "rowgroup" },
          sending ? `${group}: written as one sequence (switched off, mapped, switched on)` : `${group}: the device already has it`)));
      }
    }
    const role = { off: "switch off", clear: "clear mapping", on: "switch on" }[s.role];
    rows.push(el("tr", { class: s.send ? null : "muted", dataset: { configureStep: `${hex4(s.index)}:${s.subindex}` } },
      el("td", { class: "mono" }, `${hex4(s.index)}:${s.subindex}`),
      el("td", null, s.name, role ? el("span", { class: "muted" }, ` (${role})`) : null),
      el("td", null, s.comm ? "comm" : ""),
      el("td", null, s.value), el("td", null, s.device ?? "not readable"),
      el("td", null, s.send ? (s.role === "set" && !s.differs ? "write (same)" : "write") : "same")));
  }
  const skipped = p.skipped.length ? el("details", null, el("summary", null, `${p.skipped.length} entries left out`),
    el("table", { class: "od" }, el("tbody", null, p.skipped.map((s) => el("tr", null, el("td", { class: "mono" }, `${hex4(s.index)}:${s.subindex}`),
      el("td", null, s.name || ""), el("td", { class: "muted" }, s.reason)))))) : null;
  const extra = el("div", { class: "restore-preview", dataset: { online: "configure-preview" } },
    el("p", { class: "muted" }, `Source: ${p.source.name}.`),
    (p.identity || []).map((i) => el("p", { class: i.level === "refuse" ? "field-msg" : i.level === "warning" ? "field-msg warning" : "muted" }, upperFirst(i.text) + ".")),
    p.refused && !refuse.length ? el("p", { class: "field-msg", dataset: { online: "configure-refused" } }, upperFirst(p.refused) + ".") : null,
    (p.warnings || []).map((w) => el("p", { class: "field-msg warning" }, upperFirst(w) + ".")),
    rows.length ? el("table", { class: "od", dataset: { online: "configure-plan" } },
      el("thead", null, el("tr", null, thCells(["Entry", "Name", "", "Source", "Device now", "Action"]))), el("tbody", null, rows))
      : el("p", { class: "muted" }, "The source has nothing to write."),
    skipped,
    el("p", { class: "muted", dataset: { online: "configure-counts" } }, `${p.writes} to write, ${p.same} already the same.`),
    el("label", { class: "check" }, hold, " Hold the node in PRE-OPERATIONAL while writing"),
    p.has_restore ? el("label", { class: "check" }, restore, " Restore defaults first (0x1011 sub 1, then reset the node)") : null,
    p.has_store ? el("label", { class: "check" }, store, " Store on device afterwards (0x1010), only when everything was written and read back", storeSub ? " " : null, storeSub) : null,
    refuse.length ? el("label", { class: "check" }, other, " Write to a different product anyway") : null,
    p.allow_changes ? null : el("p", { class: "field-msg warning" }, NO_CHANGES));
  const blocked = !!p.refused && !refuse.length;
  const can = p.allow_changes && !blocked && (p.writes > 0 || p.has_restore);
  // A node that is OPERATIONAL is held or written only with force, after this question says so.
  const running = !!p.was_operational || nodeRunning(id);
  const go = modal(`${runningNote(id, running)}Write ${p.writes} value${p.writes === 1 ? "" : "s"} to node ${id}?`,
    can ? [["cancel", "Cancel"], ["write", "Write", { danger: true }]] : [["cancel", "Close"]], extra);
  const btn = document.querySelector('#modal-buttons button[data-value="write"]');
  if (btn) {
    const upd = () => { btn.disabled = (refuse.length && !other.checked) || (p.writes === 0 && !restore.checked); };
    other.addEventListener("change", upd);
    restore.addEventListener("change", upd);
    upd();
  }
  if (await go !== "write") return;
  startJob("/api/online/configure", { node: id, port: diagPort(), plan: j.id, hold: hold.checked, restore_defaults: restore.checked,
    store: store.checked, store_subindex: storeSub ? Number(storeSub.value) : (subs[0] || 1), ignore_identity: other.checked,
    ...(running ? { force: true } : {}) }, status,
  (r) => showConfigure(r.result, out, id));
}

function stepLine(s) { return `${hex4(s.index)}:${s.subindex} ${s.name}`; }

function showConfigure(r, out, id) {
  if (!r) return;
  odTake(id, null, r.written.concat(r.failed).map((w) => odKey(w.index, w.subindex)));
  put(out, el("p", { dataset: { online: "configure-done" } },
    `${r.written.length} written, ${r.failed.length} failed, ${r.same} already the same${r.cancelled ? ", cancelled" : ""}. `,
    r.cancelled ? null : el("strong", { class: r.verified ? "ok-text" : "bad" }, r.verified ? "Read-back verified." : "The read-back differs.")),
  r.restored ? el("p", { class: "muted" }, "Defaults were restored and the node reset before writing.") : null,
  ...r.failed.map((f) => el("p", { class: "field-msg" }, `${stepLine(f)}: ${f.error}`)),
  ...r.skipped.filter((s) => /stays switched off/.test(s.reason)).map((s) => el("p", { class: "field-msg warning" }, `${stepLine(s)}: ${s.reason}`)),
  r.readback.length ? diffTable(r.readback) : null,
  ...r.notes.map((t) => el("p", { class: "muted" }, upperFirst(t) + ".")),
  r.store ? el("p", { class: r.store.stored ? "ok-text" : "field-msg", dataset: { online: "configure-store" } },
    r.store.stored ? `Stored on the device (0x1010 sub ${r.store.subindex}).` : `Not stored: ${r.store.error}.`)
    : el("p", { class: "field-msg warning" }, "Not stored on the device: the values are lost at power off until Store on device is used."));
}

function diffTable(rows) {
  return el("table", { class: "od compare-rows", dataset: { online: "configure-diff" } },
    el("thead", null, el("tr", null, thCells(["Entry", "Name", "Source", "Device"]))),
    el("tbody", null, rows.map((x) => el("tr", { class: "bad" }, el("td", { class: "mono" }, `${hex4(x.index)}:${x.subindex}`),
      el("td", null, x.name), el("td", null, x.value), el("td", null, x.device ?? (x.error || ""))))));
}

function showVerify(r, out) {
  if (!r) return;
  put(out, el("p", { dataset: { online: "verify-done" } }, `${r.checked} entries checked: `,
    el("strong", { class: r.differences.length ? "bad" : "ok-text" }, r.differences.length ? `${r.differences.length} differ from ${r.source.name}.` : `no difference from ${r.source.name}.`)),
  r.stopped ? el("p", { class: "field-msg" }, "Stopped: " + r.stopped) : null,
  r.differences.length ? diffTable(r.differences) : null);
}

function restoreDefaultsBox(id, data, allow) {
  if (!data.has_restore) return null;
  const names = { 1: "all parameters", 2: "communication parameters", 3: "application parameters" };
  const sub = el("select", { "aria-label": "What to restore", dataset: { online: "defaults-sub" } },
    data.restore_subindices.map((s) => el("option", { value: s }, `sub ${s}: ${names[s] || "manufacturer-specific"}`)));
  return el("div", { class: "toolbar" }, sub,
    el("button", { type: "button", disabled: !allow, title: allow ? null : NO_CHANGES, dataset: { online: "restore-defaults" },
      onclick: () => restoreDefaultsDialog(id, Number(sub.value), names[Number(sub.value)]) }, "Restore defaults…"));
}

async function restoreDefaultsDialog(id, sub, what) {
  const reset = el("input", { type: "checkbox", checked: true, dataset: { online: "defaults-reset" } });
  const running = nodeRunning(id);
  const v = await modal(`${runningNote(id, running)}Restore node ${id}'s default ${what || "values"} (write "load" to 0x1011 sub ${sub})? ` +
    "The device takes its factory values at its next reset; what was stored on it is lost.",
  [["cancel", "Cancel"], ["restore", "Restore defaults", { danger: true }]],
  el("label", { class: "check" }, reset, " Reset the node afterwards"));
  if (v !== "restore") return;
  try {
    const r = await apiRunning("/api/online/restore_defaults", Object.assign(nodeSource(id), { subindex: sub, reset: reset.checked }),
      "Restore defaults anyway?", running);
    if (!r) return;
    if (r.restored) banner(`Node ${id}: defaults restored (0x1011 sub ${sub}). ${upperFirst(r.note)}.`);
    else banner(`Node ${id} did not restore its defaults: ${r.error}`, true);
  } catch (e) { banner(e.message, true); }
}

// -- PDO test tab (Commission a device only) ------------------------------------------------------

const SYNC_PERIODS = [10, 20, 50, 100, 200, 500, 1000];
const REPEATS = [0, 100, 200, 500, 1000];

// An online request that the adapter refuses while another master runs on
// the bus: ask with `question`, then send it again with force.
async function apiAsk(path, body, question) {
  try {
    return await api("POST", path, body);
  } catch (e) {
    if (!/another master is active/.test(e.message)) throw e;
    const v = await modal(e.message.replace(/; force needed\s*$/, "") + ". " + question,
      [["force", "Run anyway", true], ["cancel", "Cancel"]]);
    if (v !== "force") throw new Error("Not run: another master is active on this bus.");
    return api("POST", path, Object.assign({}, body, { force: true }));
  }
}

function pdoTestLocal() {
  const st = S.onlineLast && S.onlineLast.status;
  return st ? !!st.local : S.online && S.online.target === "adapter";
}

function pdoTestPanel(id, n, allow) {
  const box = el("div", { dataset: { online: "pdo-test" } });
  if (!nodeSource(id)) { put(box, noEds(id)); return box; }
  const why = allow ? null : NO_CHANGES;
  const start = el("input", { type: "checkbox", dataset: { online: "pdo-nmt-start" } });
  const sync = el("select", { "aria-label": "SYNC period", disabled: !allow, dataset: { online: "pdo-sync" } },
    el("option", { value: "0" }, "SYNC off"), SYNC_PERIODS.map((p) => el("option", { value: p }, `SYNC every ${p} ms`)));
  const msg = el("p", { class: "muted", dataset: { online: "pdo-msg" }, "aria-live": "polite" });
  const live = el("div", { dataset: { online: "pdo-live" } });
  const run = { on: false, rpdo: {} };
  const startBtn = el("button", { type: "button", class: "primary", disabled: !allow, title: why, dataset: { online: "pdo-start" } }, "Start PDO test");
  const stopBtn = el("button", { type: "button", disabled: true, dataset: { online: "pdo-stop" } }, "Stop");
  const nmtBtn = el("button", { type: "button", disabled: !allow, title: why, dataset: { online: "pdo-nmt" }, onclick: async () => {
    try { await api("POST", "/api/online/nmt", { node: id, command: "start", port: diagPort() }); msg.textContent = `NMT Start sent to node ${id}.`; }
    catch (e) { msg.textContent = e.message; }
  } }, "NMT Start");

  // asked: the slow path question was answered at Start already.
  const setSync = async (asked) => {
    if (!run.on) return;
    if (Number(sync.value) && asked !== true && !(await askSlowPath("The PDO test's SYNC"))) {
      sync.value = "0";
      return;
    }
    try {
      if (Number(sync.value)) await apiAsk("/api/online/sync_start", { node: id, period_ms: Number(sync.value), port: diagPort(), force: run.forced || undefined },
        "SYNC from this PC would fight it. Send SYNC anyway?");
      else await api("POST", "/api/online/sync_stop", { node: id, port: diagPort() });
    } catch (e) { msg.textContent = e.message; sync.value = "0"; }
  };
  sync.addEventListener("change", () => setSync(false));

  const stop = async (quiet) => {
    if (!run.on) return;
    run.on = false;
    clearTimeout(run.timer);
    try {
      await api("POST", "/api/online/pdo_test_stop", { node: id, port: diagPort() });
      await api("POST", "/api/online/sync_stop", { node: id, port: diagPort() });
    } catch (e) { /* the connection may be gone */ }
    if (!quiet && box.isConnected) {
      msg.textContent = "Stopped.";
      startBtn.disabled = !allow;
      stopBtn.disabled = true;
      sync.value = "0";
    }
  };
  S.pdoTestStop = stop;
  stopBtn.addEventListener("click", () => stop(false));

  const rpdoTable = (pdos) => el("table", { class: "od", dataset: { online: "pdo-rpdos" } },
    el("thead", null, el("tr", null, thCells(["RPDO", "Entry", "Value", "Last sent", ""]))),
    el("tbody", null, pdos.flatMap((p) => {
      const inputs = {};
      const repeat = el("select", { "aria-label": `${p.name} repeat`, disabled: !allow, dataset: { pdoRepeat: p.number } },
        REPEATS.map((r) => el("option", { value: r }, r ? `repeat every ${r} ms` : "send once")));
      const sent = el("span", { class: "muted", dataset: { pdoSent: p.number } }, "0 sent");
      const send = el("button", { type: "button", disabled: !allow, title: why, dataset: { pdoSend: p.number }, onclick: async () => {
        const values = {};
        for (const [k, inp] of Object.entries(inputs)) if (inp.value.trim() !== "") values[k] = inp.value.trim();
        if (!Object.keys(values).length) { msg.textContent = `Type a value for ${p.name} first.`; return; }
        try {
          const r = await api("POST", "/api/online/pdo_test_set", Object.assign({ node: id, rpdo: p.number, values, port: diagPort() },
            p.event ? { repeat_ms: Number(repeat.value) } : {}));
          msg.textContent = `${p.name} set${r.event ? "" : "; it goes out after each SYNC this PC sends"}.`;
        } catch (e) { msg.textContent = e.message; }
      } }, "Send");
      run.rpdo[p.number] = { sent };
      return p.values.map((v, k) => {
        const inp = el("input", { type: "text", class: "short", disabled: !allow, "aria-label": `${p.name} ${v.name}`, dataset: { pdoEntry: `${p.number}:${v.key}` } });
        inputs[v.key] = inp;
        return el("tr", { dataset: { pdoRow: `${p.name}:${v.key}` } },
          el("td", null, k === 0 ? `${p.name} ${"0x" + p.cob_id.toString(16).toUpperCase()}` : ""),
          el("td", null, `${v.name} (${v.type || v.bits + " bits"})`), el("td", null, inp),
          el("td", null, k === 0 ? sent : ""),
          el("td", null, k === 0 ? el("span", { class: "row" }, send, p.event ? repeat : el("span", { class: "muted" }, "after each SYNC")) : ""));
      });
    })));

  const tpdoTable = (pdos) => el("table", { class: "od", dataset: { online: "pdo-tpdos" } },
    el("thead", null, el("tr", null, thCells(["TPDO", "Received", "Period", "Values"]))),
    el("tbody", null, pdos.length ? pdos.map((p) => el("tr", { dataset: { pdoTpdo: p.number } },
      el("td", null, `${p.name} 0x${p.cob_id.toString(16).toUpperCase()}`),
      el("td", null, String(p.count)), el("td", null, p.period_ms ? `${p.period_ms} ms` : "-"),
      el("td", null, p.count ? p.values.map((v) => `${v.name} = ${v.value}`).join(", ") : el("span", { class: "muted" }, "nothing received yet")))) :
      [el("tr", null, el("td", { colspan: 4, class: "muted" }, "The node has no valid TPDO."))]));

  const tpdoBox = el("div");
  const poll = async () => {
    if (!run.on) return;
    if (!box.isConnected || S.onlineTab !== "pdo" || S.onlineNode !== id) { stop(true); return; }
    try {
      const st = await api("POST", "/api/online/pdo_test_status", { node: id, port: diagPort() });
      if (!run.on) return;
      if (!st.running) {
        msg.textContent = `The PDO test ended: ${st.ended || "stopped"}.`;
        run.on = false;
        startBtn.disabled = !allow;
        stopBtn.disabled = true;
        return;
      }
      put(tpdoBox, tpdoTable(st.tpdos));
      for (const p of st.rpdos) if (run.rpdo[p.number]) run.rpdo[p.number].sent.textContent = `${p.sent} sent`;
    } catch (e) { msg.textContent = e.message; }
    run.timer = setTimeout(poll, 500);
  };

  startBtn.addEventListener("click", async () => {
    startBtn.disabled = true;
    // With a SYNC period on a slow path: nothing is sent until the user confirms.
    if (Number(sync.value) && !(await askSlowPath("The PDO test with SYNC every " + sync.value + " ms"))) {
      msg.textContent = "Not started.";
      startBtn.disabled = !allow;
      return;
    }
    msg.textContent = "Reading the PDO layout…";
    let r;
    try {
      r = await apiAsk("/api/online/pdo_test_start", Object.assign(nodeSource(id), { start: start.checked }),
        "A PDO test from this PC would fight it. Run it anyway?");
    } catch (e) { msg.textContent = e.message; startBtn.disabled = !allow; return; }
    run.on = true;
    run.forced = !!r.forced;
    stopBtn.disabled = false;
    msg.textContent = `PDO test of node ${id}, layout ${r.source === "configuration" ? "from the configuration" : "read from the device"}.`;
    put(live, el("h3", null, "TPDOs (from the device)"), tpdoBox, el("h3", null, "RPDOs (to the device)"),
      r.rpdos.length ? rpdoTable(r.rpdos) : el("p", { class: "muted" }, "The node has no valid RPDO."));
    put(tpdoBox, tpdoTable(r.tpdos));
    await setSync(true);
    poll();
  });

  put(box,
    allow ? null : lockedNote("pdo-no-changes", null, "The PDO test sends on the bus:"),
    el("p", { class: "muted" }, "Shows the node's TPDOs and sends its RPDOs from this PC, for a device on the bench without a PLC. The layout comes from the configuration when the node is in it, otherwise from the device. SYNC is sent only when you pick a period; leaving this tab stops the test and the SYNC."),
    el("div", { class: "toolbar" }, startBtn, stopBtn, el("label", { class: "inline" }, start, " NMT Start the node first"), sync, nmtBtn),
    msg, live);
  return box;
}

// Closing the page ends a running PDO test and SYNC.
window.addEventListener("pagehide", () => {
  if (!S.pdoTestStop) return;
  for (const path of ["/api/online/pdo_test_stop", "/api/online/sync_stop"]) {
    try {
      fetch(path, { method: "POST", keepalive: true, headers: { "X-CANopen-Token": TOKEN, "Content-Type": "application/json" },
        body: JSON.stringify({ node: S.onlineNode, port: diagPort() }) });
    } catch (e) { /* the page is going away */ }
  }
});
