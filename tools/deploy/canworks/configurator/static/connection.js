"use strict";
// The connection (ui-shell-and-connection, one-connect-place): one
// connection for every view, shown in the connection bar under the header
// and made only in the connect panel that the bar's Connect… opens.
// Commission a device connects through a USB adapter on this PC (with the
// bit rate check), a config to its runtime or to a standalone simulator.
// The Commission pages, Trace, Simulation and the PDO test all use it; no
// page has a connect form or button of its own. Loaded after app.js and
// shell.js and uses their helpers.
//
// S.adapterOn / S.adapterEnded: the adapter connection is open / why the
// last one was refused or ended (commission.js). S.runtimeOn: the runtime
// connection is open; S.runtimeOff: the user disconnected it, so nothing
// opens it again until Connect. S.simOn: the standalone simulator is the
// connection (only the Simulation view uses it); one connection at a time.

const CONN = { timer: null, seq: 0, error: null, entered: false, target: null };

function connAdapter() { return !!(S.state && S.state.commission); }

// The target is set up: an adapter and its bit rate, or a runtime host
// and this PC's token for the config.
function connReady() {
  if (connAdapter()) return !!(S.online && S.online.adapter && S.online.adapter_bitrate);
  return !!(diagConfig() && S.online && S.online.host && S.online.token && S.online.tokenOk);
}

function connIsOn() { return connAdapter() ? !!S.adapterOn : !!S.runtimeOn; }

// The standalone simulator is the connection (a config only).
function connSimOn() { return !connAdapter() && !!S.simOn; }

function simAddress() {
  return (typeof SIM !== "undefined" && SIM.settings && SIM.settings.address) || "127.0.0.1:7532";
}

// What a page says in place of what needs a connection: one line, no
// button; Connect… in the connection bar is the one place to connect.
function connNeeds(what, attrs) {
  const text = connSimOn()
    ? `${what} needs a connection to the runtime; the connection bar is connected to a standalone simulator.`
    : `${what} needs a connection. Connect with Connect… in the connection bar above.`;
  return el("p", Object.assign({ class: "muted", dataset: { conn: "needs" } }, attrs || {}), text);
}

// A view that needs the runtime opens the connection when it is set up
// and the user did not disconnect it; an adapter always needs Connect.
function connEnsure() {
  if (connIsOn()) { connStart(); return true; }
  if (connAdapter() || S.runtimeOff || S.simOn || !connReady()) return false;
  S.runtimeOn = true;
  connKick();
  return true;
}

// Entering Commission: the connection opens when it can by itself; else
// the Nodes table shows the connect form (commission-workspace).
function connEnter() {
  connEnsure();
}

// Another folder, or another commissioning session: a fresh start, with
// the connect panel offered again on entering Commission.
function connSession() {
  const key = `${S.state.commission ? "commission" : "config"}|${S.state.folder || ""}`;
  if (key === CONN.key) return;
  CONN.key = key;
  CONN.entered = false;
  CONN.error = null;
  S.runtimeOn = false;
  S.runtimeOff = false;
  S.simOn = false;
  connStop();
}

function connStart() { if (!CONN.timer && connIsOn()) connTick(); }

function connStop() {
  clearTimeout(CONN.timer);
  CONN.timer = null;
  CONN.seq++;
}

// Polls now: after a connect, or a view that needs fresh data at once.
function connKick() {
  connStop();
  connTick();
}

// The one poller of /api/online/status. Each answer goes to the connection
// bar, and to the online views when one is shown.
async function connTick() {
  CONN.timer = null;
  const seq = CONN.seq;
  if (!S.state || !S.state.mode || !connIsOn()) { connBar(); return; }
  let r = null;
  let err = null;
  try {
    r = await api("POST", "/api/online/status", { port: diagPort() });
  } catch (e) { err = e; }
  // The settings may still be loading at the first answer.
  if (r && r.recent && S.online) S.online.recent = r.recent;
  if (seq !== CONN.seq || !connIsOn()) return;
  if (err && !CONN.error && !connAdapter() && typeof commEvent === "function" && commLogOn()) commEvent(null, onlineNetwork(), "Connection to the runtime lost", err.message);
  CONN.error = err;
  if (r) {
    S.onlineLast = r;
    S.onlineLastAt = Date.now();
    // The log and the tree's marks must never stop the connection itself.
    try {
      if (typeof logEvents === "function") logEvents(r.status);
      if (typeof identitySeen === "function") identitySeen(r.status);
      if (typeof treeLive === "function" && !onlineViews().includes(S.view)) treeLive(r.status);
      if (typeof pdoAutoRead === "function") pdoAutoRead(r);
    } catch (e) { console.error(e); }
  }
  if (err && connAdapter()) { adapterLost(err.message); return; }
  connBar();
  if (typeof jobsSeen === "function") jobsSeen(r);
  if (onlineViews().includes(S.view) && $("#online-live")) onlineApply(r, err);
  CONN.timer = setTimeout(connTick, err ? 2000 : 500);
}

// Disconnect: closes the adapter or the runtime connection with every job
// on it (trace recording, transmit list jobs, scan, PDO test).
async function connDisconnect() {
  if (connAdapter()) return disconnectAdapter();
  if (S.simOn) {
    S.simOn = false;
    S.runtimeOff = true;
    if (typeof SIM !== "undefined") { SIM.connErr = null; SIM.last = null; }
    api("POST", "/api/sim/close", {}).catch(() => {});
    render();
    return;
  }
  await runtimeClose();
  render();
}

// Closes the runtime connection (Disconnect, or the standalone simulator
// taking its place).
async function runtimeClose() {
  connStop();
  try { await api("POST", "/api/online/disconnect", {}); } catch (e) { banner(e.message, true); }
  S.runtimeOn = false;
  S.runtimeOff = true;
  S.onlineOpen = false;
  S.onlineLast = null;
  S.logPrev = null;
  S.identity = null;
  if (typeof treeLiveClear === "function") treeLiveClear();
  CONN.error = null;
  S.lssAllow = undefined;
}

// ---------------------------------------------------------------------------
// The connection bar

const ADAPTER_STATES_BAD = ["passive", "error_passive", "bus_off", "bus-off", "stopped"];
const BUS_STATES_BAD = ["error-passive", "bus-off", "no bus"];

function lastAge() {
  return S.onlineLastAt ? Math.max(0, Math.round((Date.now() - S.onlineLastAt) / 1000)) : null;
}

// Bus-off (and no bus) is broken; error passive or warning needs a look.
function busIcon(state) {
  return /off|^4$|^0$|no bus/i.test(String(state)) ? "error" : "warning";
}

function connBar() {
  const bar = $("#conn-bar");
  if (!bar) return;
  // Wherever a connection is used: Commission, and Trace and Simulation in Configure.
  const show = !!(S.state && S.state.mode) &&
    (workspace() === "commission" || connIsOn() || connSimOn() || S.view === "trace" || S.view === "simulation");
  bar.hidden = !show;
  if (!show) return;
  const parts = [];
  let fault = false;
  const on = connIsOn() || connSimOn();
  const c = on && S.onlineLast && S.onlineLast.conn;
  const simErr = connSimOn() && typeof SIM !== "undefined" ? SIM.connErr : null;
  if (connSimOn()) {
    fault = !!simErr;
    parts.push(simErr ? Icons.stateIcon("error", { label: false }) : Icons.stateIcon("operational", { label: "Connected" }));
    parts.push(el("strong", { dataset: { conn: "target" } }, `Standalone simulator ${simAddress()}`));
    if (simErr) parts.push(el("span", { dataset: { conn: "state" } }, `not answering (${simErr}), retrying`));
    parts.push(el("button", { type: "button", class: "small", dataset: { conn: "change" }, onclick: () => openConnect() }, "Change…"));
    parts.push(el("button", { type: "button", class: "small", dataset: { conn: "disconnect" }, onclick: connDisconnect }, "Disconnect"));
  } else if (!on) {
    const ended = connAdapter() ? S.adapterEnded : null;
    if (ended) { fault = true; parts.push(Icons.stateIcon("ended", { label: false }), el("span", { dataset: { conn: "ended" } }, upperFirst(ended) + ".")); }
    else parts.push(Icons.stateIcon("unknown", { label: false }), el("span", { class: "muted", dataset: { conn: "state" } }, "Not connected"));
    parts.push(el("button", { type: "button", class: "small primary", dataset: { conn: "connect" }, onclick: () => openConnect() }, "Connect…"));
  } else if (CONN.error && !connAdapter()) {
    fault = true;
    const age = lastAge();
    const why = { closed: "port closed", unreachable: "host unreachable", token: "wrong token", timeout: "no answer",
      protocol: "not a CANopen diagnostics port", refused: "refused" }[CONN.error.body && CONN.error.body.kind] || "error";
    parts.push(Icons.stateIcon("error", { label: false }));
    parts.push(el("span", { dataset: { conn: "state" } }, `${S.online.host}: not answering (${why}), retrying` +
      (age !== null && S.onlineLast ? `, last data ${age} s ago` : "")));
    parts.push(el("button", { type: "button", class: "small", dataset: { conn: "change" }, onclick: () => openConnect() }, "Change…"));
    parts.push(el("button", { type: "button", class: "small", dataset: { conn: "disconnect" }, onclick: connDisconnect }, "Disconnect"));
  } else if (!c) {
    parts.push(Icons.stateIcon("busy", { label: false, spinning: true }));
    parts.push(el("span", { dataset: { conn: "state" } }, connAdapter()
      ? `Connecting to ${S.online.adapter} at ${S.online.adapter_bitrate} kbit/s: checking the bit rate…`
      : `Connecting to ${S.online.host}…`));
    parts.push(el("button", { type: "button", class: "small", dataset: { conn: "cancel" }, onclick: connDisconnect }, "Cancel"));
  } else {
    const bus = c.bus || {};
    parts.push(Icons.stateIcon("operational", { label: "Connected" }));
    parts.push(el("strong", { dataset: { conn: "target" } }, c.kind === "adapter" ? c.target : (c.name ? `${c.name} (${c.target})` : c.target)));
    if (c.kind === "adapter") {
      const kbit = Math.round((c.bitrate || 0) / 1000);
      parts.push(el("span", { dataset: { conn: "rate" } }, `${kbit} kbit/s` + (c.check ? `, confirmed by ${CHECK_TEXT[c.check.how] || c.check.how}` : "")));
      const bad = ADAPTER_STATES_BAD.includes(String(bus.state || "").toLowerCase());
      fault = fault || bad;
      if (bad) parts.push(Icons.stateIcon(busIcon(bus.state), { label: false }));
      parts.push(el("span", { class: bad ? "bad" : null, dataset: { conn: "bus" } }, `bus ${bus.state || "active"}`));
      parts.push(el("span", { class: "muted", dataset: { conn: "frames" } }, `${bus.frames ?? 0} frames, ${bus.error_frames ?? 0} error frames`));
    } else {
      const badge = pathBadge(c);
      if (badge) parts.push(badge);
      if (c.rtt_ms > SLOW_RTT_MS) fault = true;
      if (c.networks && c.networks.length > 1) parts.push(netPicker());
      const bad = BUS_STATES_BAD.includes(String(bus.state || ""));
      fault = fault || bad;
      if (bad) parts.push(Icons.stateIcon(busIcon(bus.state), { label: false }));
      parts.push(el("span", { class: bad ? "bad" : null, dataset: { conn: "bus" } },
        `${bus.interface || "bus"} ${bus.state || "?"}` + (bus.tx_errors !== undefined && bus.tx_errors !== null ? `, TX/RX errors ${bus.tx_errors}/${bus.rx_errors}` : "")));
    }
    if (c.other_master) {
      fault = true;
      const o = c.other_master;
      parts.push(Icons.stateIcon("warning", { label: false }));
      parts.push(el("span", { class: "bad", dataset: { conn: "other" } },
        `Another master on the bus (${o.what}, since ${String(o.first_at || "").replace("T", " ").replace(/\.\d+Z$/, " UTC")})`));
    }
    parts.push(allowControl(c));
    parts.push(el("button", { type: "button", class: "small", dataset: { conn: "disconnect" }, onclick: connDisconnect }, "Disconnect"));
  }
  const line = el("div", { class: "conn-line" }, ...parts);
  // Rewritten only when it changes, so the live region speaks only then and a focused control keeps focus.
  // The network picker's value is not in the HTML: the picked network is part of the signature.
  const sig = line.innerHTML + "|" + (typeof onlineNetwork === "function" ? onlineNetwork() : "");
  if (bar.dataset.html !== sig) {
    const focused = document.activeElement && bar.contains(document.activeElement) ? document.activeElement.dataset.conn : null;
    bar.dataset.html = sig;
    bar.replaceChildren(...line.childNodes);
    if (focused) {
      // The same control again, or the bar's main action when it is gone (Disconnect becomes Connect…).
      const again = bar.querySelector(`[data-conn="${focused}"]`) || bar.querySelector('[data-conn="connect"], [data-conn="disconnect"], button');
      if (again) again.focus();
    }
  }
  bar.classList.toggle("fault", fault);
  bar.setAttribute("role", fault && (!on || CONN.error || simErr) ? "alert" : "status");
  bar.setAttribute("aria-label", "Connection");
}

// Allow changes: a switch on an adapter connection, the runtime's own
// setting (read-only) on a runtime.
function allowControl(c) {
  if (c.allow_changes_source !== "switch") {
    return el("span", { class: "muted", dataset: { conn: "allow" },
      title: "Set in Configure → Online access, then upload" },
    c.allow_changes ? "🔓 Changes allowed (runtime setting)" : "🔒 Read-only (runtime setting)");
  }
  const box = el("input", { type: "checkbox", checked: !!c.allow_changes, dataset: { conn: "allow" } });
  box.addEventListener("change", async () => {
    if (box.checked) {
      const v = await modal("Allow changes on this adapter connection? SDO writes, NMT commands, LSS and restore then go to the bus. Saving to a device's non-volatile memory still asks each time.",
        [["allow", "Allow changes", true], ["cancel", "Cancel"]]);
      if (v !== "allow") { box.checked = false; return; }
    }
    if (!(await saveOnline({ allow_changes: box.checked }))) { box.checked = !box.checked; return; }
    if (S.onlineLast && S.onlineLast.conn) S.onlineLast.conn.allow_changes = box.checked;
    if (S.onlineLast && S.onlineLast.status) S.onlineLast.status.allow_changes = box.checked;
    render();
  });
  return el("label", { class: "check", title: "Off for every new connection. Switching it keeps the connection open." },
    box, c.allow_changes ? " Changes allowed" : " Read-only");
}

// ---------------------------------------------------------------------------
// The connect panel

function openConnect(message) {
  const dlg = $("#conn-dialog");
  // The panel remembers the last target of a config (Runtime or Standalone simulator).
  if (!connAdapter() && typeof SIM !== "undefined" && !SIM.settings) {
    loadSimSettings().then(() => openConnect(message));
    return;
  }
  if (!connAdapter() && !dlg.open) CONN.target = connSimOn() ? "simulator" : (CONN.target || simSavedTarget());
  connPanel(message);
  if (!dlg.dataset.wired) {
    dlg.dataset.wired = "1";
    dlg.addEventListener("close", () => {
      connBar();
      // The control that opened the panel may be gone (the bar is redrawn, or the
      // panel opened by itself): focus goes to the bar, never to the page body.
      setTimeout(() => {
        const a = document.activeElement;
        if (a && a !== document.body && a.isConnected) return;
        const to = document.querySelector('#conn-bar [data-conn="disconnect"], #conn-bar [data-conn="connect"], #conn-bar button');
        if (to) to.focus();
      }, 0);
    });
  }
  if (!dlg.open) dlg.showModal();
  const body = $("#conn-dialog-body");
  const first = body.querySelector("[data-conn-recent], [data-online=adapter-list], [data-online=runtime-list], [data-online=host], [data-sim=address], input, select, button");
  if (first) first.focus();
}

function simSavedTarget() {
  return typeof SIM !== "undefined" && SIM.settings && SIM.settings.target === "simulator" ? "simulator" : "runtime";
}

// The panel's content: the recent connections first, then (with a config)
// the Runtime / Standalone simulator choice and the chosen target's form.
function connPanel(message) {
  const body = $("#conn-dialog-body");
  const sim = !connAdapter() && CONN.target === "simulator";
  $("#conn-dialog-title").textContent = connAdapter() ? "Connect to a USB adapter" : sim ? "Connect to a standalone simulator" : "Connect to the runtime";
  const form = connAdapter() ? adapterBox(message) : sim ? simulatorBox(message) : runtimeBox(message);
  const choice = connAdapter() ? null : el("div", { class: "segmented", role: "group", "aria-label": "Connect to", dataset: { conn: "targets" } },
    [["runtime", "Runtime"], ["simulator", "Standalone simulator"]].map(([k, label]) =>
      el("button", { type: "button", "aria-pressed": String(k === CONN.target), dataset: { connTarget: k },
        onclick: () => { CONN.target = k; connPanel(); const b = body.querySelector(`[data-conn-target="${k}"]`); if (b) b.focus(); } }, label)));
  // replaceChildren() writes null as the text "null": leave the empty parts out.
  body.replaceChildren(...[recentBox(form), choice ? el("div", { class: "toolbar" }, choice) : null, form,
    el("menu", { class: "toolbar" }, el("button", { type: "button", dataset: { conn: "close-panel" }, onclick: () => $("#conn-dialog").close() }, "Close"))].filter(Boolean));
}

// Up to three connections this PC made last (online.json `recent`), one click each.
function recentConnections() {
  const list = (S.online && S.online.recent) || [];
  return list.filter((r) => connAdapter() ? r.kind === "adapter" : r.kind === "runtime");
}

function recentText(r) {
  if (r.kind === "adapter") return `${r.adapter} at ${r.bitrate_kbit} kbit/s` + (r.check_node ? `, check node ${r.check_node}` : "");
  return r.name ? `${r.name} (${r.host})` : r.host;
}

function recentBox() {
  const recent = recentConnections();
  if (!recent.length) return null;
  return el("div", { class: "toolbar conn-recent", dataset: { conn: "recent" } },
    el("span", { class: "muted" }, "Recent:"),
    recent.map((r, k) => el("button", { type: "button", dataset: { connRecent: k },
      title: r.kind === "adapter" ? "Connects with Allow changes off, after the bit rate check" : "Connects to this runtime",
      onclick: () => connectRecent(r) }, recentText(r))));
}

// One click on a recent connection: the form is filled in and its Connect
// pressed, so the bit rate check (adapter) or the token prompt (runtime)
// runs as from the form, and Allow changes starts off.
function connectRecent(r) {
  if (r.kind === "runtime" && CONN.target !== "runtime") { CONN.target = "runtime"; connPanel(); }
  const box = $("#conn-dialog-body");
  if (r.kind === "adapter") {
    box.querySelector("[data-online=adapter]").value = r.adapter;
    box.querySelector("[data-online=adapter-bitrate]").value = String(r.bitrate_kbit);
    box.querySelector("[data-online=check-node]").value = r.check_node ? String(r.check_node) : "";
    const allow = box.querySelector("[data-online=adapter-allow]");
    if (allow) allow.checked = false;
  } else {
    box.querySelector("[data-online=host]").value = r.host;
  }
  box.querySelector("[data-online=connect]").click();
}

// The standalone simulator: a running canworks-sim by address and token,
// both kept on this PC (online.json, per project folder).
function simulatorBox(message) {
  const st = (typeof SIM !== "undefined" && SIM.settings) || {};
  const address = el("input", { type: "text", spellcheck: "false", placeholder: "127.0.0.1:7532", "aria-label": "Simulator address", dataset: { sim: "address" } });
  address.value = st.address || "";
  const token = el("input", { type: "password", autocomplete: "off", placeholder: st.token_set ? "kept on this PC" : "none", "aria-label": "Simulator token", dataset: { sim: "token" } });
  const msg = el("p", { class: "field-msg", dataset: { online: "connect-msg" } }, message || "");
  const connect = el("button", { type: "button", class: "primary", dataset: { online: "connect" }, onclick: async () => {
    const body = { target: "simulator", address: address.value.trim() };
    if (token.value.trim()) body.token = token.value.trim();
    try { SIM.settings = await api("POST", "/api/sim/settings", body); } catch (e) { msg.textContent = e.message; address.focus(); return; }
    // One connection at a time: the simulator takes the runtime's place.
    if (S.runtimeOn) await runtimeClose();
    S.runtimeOff = true;
    S.simOn = true;
    Object.assign(SIM, { connErr: null, last: null });
    banner("");
    closeConnect();
    render();
  } }, "Connect");
  return el("div", { dataset: { conn: "simulator-box" } },
    el("div", { class: "grid" },
      el("label", null, "Simulator address", address, hint("HOST[:PORT] of a running canworks-sim, port 7532 when not given. Kept on this PC, not in the project.")),
      el("label", null, "Token", token, hint("Only when the simulator was started with a token."))),
    msg,
    el("div", { class: "toolbar" },
      st.token_set ? el("button", { type: "button", dataset: { sim: "forget-token" }, onclick: async () => {
        try { SIM.settings = await api("POST", "/api/sim/settings", { token: "" }); } catch (e) { msg.textContent = e.message; return; }
        connPanel();
      } }, "Forget token") : null,
      connect));
}

function closeConnect() {
  const dlg = $("#conn-dialog");
  if (dlg.open) dlg.close();
}

// The runtime: found and remembered runtimes, the host, the local simulator
// runtime, and the token when this PC has none that matches the config.
function runtimeBox(message) {
  if (!diagConfig()) {
    return el("div", { dataset: { conn: "no-access" } }, el("p", null, "Online access is off for this config. Turn it on in Configure → ",
      el("a", { href: "#", onclick: (e) => { e.preventDefault(); closeConnect(); switchWorkspace("configure"); showView("access"); } }, "Online access"),
      ", save, and upload the program to the runtime."));
  }
  const host = hostField(true);
  const msg = el("p", { class: "field-msg", dataset: { online: "connect-msg" } },
    message || (S.online.token && !S.online.tokenOk ? "The token on this PC does not match the config." : ""));
  const connect = el("button", { type: "button", class: "primary", dataset: { online: "connect" }, onclick: async () => {
    const value = host.querySelector("input").value.trim();
    if (!value) {
      msg.textContent = "Enter the runtime's host name or address first, for example plc.local.";
      host.querySelector("input").focus();
      return;
    }
    if (!(await saveHost(value))) { msg.textContent = "The host was not saved; see the message at the top."; return; }
    msg.textContent = "";
    if (!S.online.tokenOk && !(await enterToken())) {
      msg.textContent = S.online.token
        ? "The token on this PC does not match the config. Enter the token of this project to connect."
        : "Enter the access token of this project to connect (Copy token on the PC that turned online access on).";
      return;
    }
    S.simOn = false;
    S.runtimeOff = false;
    S.runtimeOn = true;
    S.onlineLast = null;
    CONN.error = null;
    if (typeof SIM !== "undefined") {
      SIM.last = null;
      try { SIM.settings = await api("POST", "/api/sim/settings", { target: "runtime" }); } catch (e) { /* the choice is only remembered */ }
    }
    closeConnect();
    render();
    connKick();
  } }, "Connect");
  return el("div", { dataset: { conn: "runtime-box" } },
    el("div", { class: "grid" }, host), msg,
    el("div", { class: "toolbar" },
      !S.online.tokenOk ? el("button", { type: "button", onclick: async () => { await enterToken(); openConnect(); } }, "Enter token…") : null,
      connect));
}
