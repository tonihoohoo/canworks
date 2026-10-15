"use strict";
// The connection (ui-shell-and-connection): one connection for every view,
// shown in the connection bar under the header, made in the connect panel.
// Commission a device connects through a USB adapter on this PC (with the
// bit rate check), a config to its runtime. The Commission pages, Trace,
// Simulation's Runtime target and the PDO test all use it. Loaded after
// app.js and shell.js and uses their helpers.
//
// S.adapterOn / S.adapterEnded: the adapter connection is open / why the
// last one was refused or ended (commission.js). S.runtimeOn: the runtime
// connection is open; S.runtimeOff: the user disconnected it, so nothing
// opens it again until Connect.

const CONN = { timer: null, seq: 0, error: null, entered: false };

function connAdapter() { return !!(S.state && S.state.commission); }

// The target is set up: an adapter and its bit rate, or a runtime host
// and this PC's token for the config.
function connReady() {
  if (connAdapter()) return !!(S.online && S.online.adapter && S.online.adapter_bitrate);
  return !!(diagConfig() && S.online && S.online.host && S.online.token && S.online.tokenOk);
}

function connIsOn() { return connAdapter() ? !!S.adapterOn : !!S.runtimeOn; }

// A view that needs the runtime opens the connection when it is set up
// and the user did not disconnect it; an adapter always needs Connect.
function connEnsure() {
  if (connIsOn()) { connStart(); return true; }
  if (connAdapter() || S.runtimeOff || !connReady()) return false;
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
    if (r && r.recent) S.online.recent = r.recent;
  } catch (e) { err = e; }
  if (seq !== CONN.seq || !connIsOn()) return;
  if (err && !CONN.error && !connAdapter() && typeof commEvent === "function" && commLogOn()) commEvent(null, onlineNetwork(), "Connection to the runtime lost", err.message);
  CONN.error = err;
  if (r) {
    S.onlineLast = r;
    S.onlineLastAt = Date.now();
    if (typeof logEvents === "function") logEvents(r.status);
    if (typeof treeLive === "function" && !onlineViews().includes(S.view)) treeLive(r.status);
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
  connStop();
  try { await api("POST", "/api/online/disconnect", {}); } catch (e) { banner(e.message, true); }
  S.runtimeOn = false;
  S.runtimeOff = true;
  S.onlineOpen = false;
  S.onlineLast = null;
  S.logPrev = null;
  if (typeof treeLiveClear === "function") treeLiveClear();
  CONN.error = null;
  S.lssAllow = undefined;
  render();
}

// ---------------------------------------------------------------------------
// The connection bar

const ADAPTER_STATES_BAD = ["passive", "error_passive", "bus_off", "bus-off", "stopped"];
const BUS_STATES_BAD = ["error-passive", "bus-off", "no bus"];

function lastAge() {
  return S.onlineLastAt ? Math.max(0, Math.round((Date.now() - S.onlineLastAt) / 1000)) : null;
}

function connBar() {
  const bar = $("#conn-bar");
  if (!bar) return;
  const show = !!(S.state && S.state.mode) && (workspace() === "commission" || connIsOn());
  bar.hidden = !show;
  if (!show) return;
  const parts = [];
  let fault = false;
  const on = connIsOn();
  const c = on && S.onlineLast && S.onlineLast.conn;
  if (!on) {
    const ended = connAdapter() ? S.adapterEnded : null;
    if (ended) { fault = true; parts.push(el("span", { dataset: { conn: "ended" } }, upperFirst(ended) + ".")); }
    else parts.push(el("span", { class: "muted", dataset: { conn: "state" } }, "Not connected"));
    parts.push(el("button", { type: "button", class: "small primary", dataset: { conn: "connect" }, onclick: () => openConnect() }, "Connect…"));
  } else if (CONN.error && !connAdapter()) {
    fault = true;
    const age = lastAge();
    const why = { closed: "port closed", unreachable: "host unreachable", token: "wrong token", timeout: "no answer",
      protocol: "not a CANopen diagnostics port", refused: "refused" }[CONN.error.body && CONN.error.body.kind] || "error";
    parts.push(el("span", { dataset: { conn: "state" } }, `${S.online.host}: not answering (${why}), retrying` +
      (age !== null && S.onlineLast ? `, last data ${age} s ago` : "")));
    parts.push(el("button", { type: "button", class: "small", dataset: { conn: "change" }, onclick: () => openConnect() }, "Change…"));
    parts.push(el("button", { type: "button", class: "small", dataset: { conn: "disconnect" }, onclick: connDisconnect }, "Disconnect"));
  } else if (!c) {
    parts.push(el("span", { dataset: { conn: "state" } }, connAdapter()
      ? `Connecting to ${S.online.adapter} at ${S.online.adapter_bitrate} kbit/s: checking the bit rate…`
      : `Connecting to ${S.online.host}…`));
    parts.push(el("button", { type: "button", class: "small", dataset: { conn: "cancel" }, onclick: connDisconnect }, "Cancel"));
  } else {
    const bus = c.bus || {};
    parts.push(el("span", { class: "dot ok", "aria-hidden": "true" }));
    parts.push(el("strong", { dataset: { conn: "target" } }, c.kind === "adapter" ? c.target : (c.name ? `${c.name} (${c.target})` : c.target)));
    if (c.kind === "adapter") {
      const kbit = Math.round((c.bitrate || 0) / 1000);
      parts.push(el("span", { dataset: { conn: "rate" } }, `${kbit} kbit/s` + (c.check ? `, confirmed by ${CHECK_TEXT[c.check.how] || c.check.how}` : "")));
      const bad = ADAPTER_STATES_BAD.includes(String(bus.state || "").toLowerCase());
      fault = fault || bad;
      parts.push(el("span", { class: bad ? "bad" : null, dataset: { conn: "bus" } }, `bus ${bus.state || "active"}`));
      parts.push(el("span", { class: "muted", dataset: { conn: "frames" } }, `${bus.frames ?? 0} frames, ${bus.error_frames ?? 0} error frames`));
    } else {
      const badge = pathBadge(c);
      if (badge) parts.push(badge);
      if (c.rtt_ms > SLOW_RTT_MS) fault = true;
      if (c.networks && c.networks.length > 1) parts.push(netPicker());
      const bad = BUS_STATES_BAD.includes(String(bus.state || ""));
      fault = fault || bad;
      parts.push(el("span", { class: bad ? "bad" : null, dataset: { conn: "bus" } },
        `${bus.interface || "bus"} ${bus.state || "?"}` + (bus.tx_errors !== undefined && bus.tx_errors !== null ? `, TX/RX errors ${bus.tx_errors}/${bus.rx_errors}` : "")));
    }
    if (c.other_master) {
      fault = true;
      const o = c.other_master;
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
    if (focused) { const again = bar.querySelector(`[data-conn="${focused}"]`); if (again) again.focus(); }
  }
  bar.classList.toggle("fault", fault);
  bar.setAttribute("role", fault && (!on || CONN.error) ? "alert" : "status");
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
  const body = $("#conn-dialog-body");
  $("#conn-dialog-title").textContent = connAdapter() ? "Connect to a USB adapter" : "Connect to the runtime";
  body.replaceChildren(connAdapter() ? adapterBox(message) : runtimeBox(message),
    el("menu", { class: "toolbar" }, el("button", { type: "button", dataset: { conn: "close-panel" }, onclick: () => dlg.close() }, "Close")));
  if (!dlg.dataset.wired) {
    dlg.dataset.wired = "1";
    dlg.addEventListener("close", () => { connBar(); });
  }
  if (!dlg.open) dlg.showModal();
  const first = body.querySelector("[data-online=adapter-list], [data-online=runtime-list], [data-online=host], input, select, button");
  if (first) first.focus();
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
    S.runtimeOff = false;
    S.runtimeOn = true;
    S.onlineLast = null;
    CONN.error = null;
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
