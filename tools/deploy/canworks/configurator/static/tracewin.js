// The trace in its own window (canopen-configurator "Trace in its own
// window" and the requirements after it). The trace window is this page at
// /?window=trace showing only the Trace view; the recording, decoding and
// transmit jobs are on the local server, so both windows see the same trace.
// The windows talk over a BroadcastChannel:
//   trace window -> main: open (also every 2 s), closed, goto (Frame lab),
//                         net (picked in the trace window), ensure (open the runtime connection)
//   main -> trace window: ping, conn (folder, connection and network; also every 2 s),
//                         select (Back to trace from Frame lab), bring-back
// Loaded after trace.js and uses its helpers (T, render, showView, ...).
"use strict";

const TRACE_WINDOW = new URLSearchParams(location.search).get("window") === "trace";
const TRACE_WINDOW_NAME = "canworks-trace";
const TW = {
  ch: typeof BroadcastChannel === "function" ? new BroadcastChannel("canworks-trace") : null,
  seen: 0,        // main: when the trace window last said it is open
  mainSeen: 0,    // trace window: when a main window last spoke
  pending: [],    // trace window: goto messages waiting for a main window
  conn: "",       // the last connection message, sent or applied
  timer: null,
  win: null,       // main: the trace window this page opened
};

// The unsaved recording is asked about only by the last window that shows it:
// the main window while no trace window is open, the trace window when no
// main window is left.
function traceWinUnsaved() {
  if (!traceUnsaved()) return false;
  return TRACE_WINDOW ? Date.now() - TW.mainSeen >= 5000 : !traceWinElsewhere();
}

function traceWinPost(msg) { if (TW.ch) TW.ch.postMessage(msg); }

// Main window: whether the trace is shown in its own window now.
function traceWinElsewhere() { return !TRACE_WINDOW && Date.now() - TW.seen < 5000; }

function traceWinKey() { return S.state ? `${S.state.commission ? "commission" : "config"}|${S.state.folder || ""}` : ""; }

// What the trace window takes from the main window: the folder, the
// connection (the connection bar's choices live in the main page) and the network.
function traceWinConn() {
  return { type: "conn", key: traceWinKey(), runtimeOn: !!S.runtimeOn, runtimeOff: !!S.runtimeOff, adapterOn: !!S.adapterOn,
    simOn: !!S.simOn, onlineNet: S.onlineNet || null, runtimeNets: S.runtimeNets || [], host: (S.online && S.online.host) || null };
}

// Main window: sends the connection when it changed, and every 2 s while a trace window is open.
function traceWinSendConn(force) {
  if (TRACE_WINDOW || !TW.ch) return;
  const msg = traceWinConn();
  const text = JSON.stringify(msg);
  if (!force && text === TW.conn) return;
  TW.conn = text;
  traceWinPost(msg);
}

// -- the button and the main window's Trace tab -----------------------------

function traceWinButton() {
  if (TRACE_WINDOW || !TW.ch || window.innerWidth < SPLIT_PHONE) return null;
  return el("button", { type: "button", class: "trace-win-open", dataset: { trace: "open-window" },
    title: "Open the trace in a separate window, to watch it while sending from this one", onclick: traceWinOpen }, "⧉ Open in new window");
}

function traceWinOpen() {
  const p = T.prefs || {};
  const w = Math.min(p.window_w || 1200, screen.availWidth || 1200);
  const h = Math.min(p.window_h || 800, screen.availHeight || 800);
  // An open trace window is only brought to the front: opening the name with a URL would load it again.
  const win = traceWinElsewhere() ? window.open("", TRACE_WINDOW_NAME)
    : window.open("/?window=trace", TRACE_WINDOW_NAME, `popup,width=${Math.round(w)},height=${Math.round(h)}`);
  if (!win) { banner("The browser did not open the window; allow pop-ups for this page.", true); return; }
  TW.win = win;
  win.focus();
  if (!traceWinElsewhere()) {
    TW.seen = Date.now();
    traceWinSwitched();
  }
}

// The main window's Trace tab while the trace has its own window.
function renderTraceElsewhere(view) {
  view.append(el("h2", null, "Trace"),
    notice("info", "Trace is open in its own window.", { live: false, dataset: { trace: "elsewhere" } }),
    el("div", { class: "toolbar" },
      el("button", { type: "button", class: "primary", dataset: { trace: "show-window" }, onclick: traceWinOpen }, "Show trace window"),
      el("button", { type: "button", dataset: { trace: "bring-back" }, onclick: () => {
        traceWinPost({ type: "bring-back" });
        // The window this page opened closes from here; one opened from another page closes itself.
        const w = TW.win && !TW.win.closed ? TW.win : window.open("", TRACE_WINDOW_NAME);
        if (w) w.close();
        TW.win = null;
        TW.seen = 0;
        traceWinSwitched();
      } }, "Bring trace back here")));
}

// The trace moved to its own window or back: the Trace tab draws again.
function traceWinSwitched() {
  if (S.view !== "trace") return;
  stopTrace();
  render();
}

// -- the trace window ---------------------------------------------------------

// The one-line bar over the trace: folder, network and connection.
function traceWinBar() {
  const bar = $("#trace-win-bar");
  if (!bar) return;
  const st = S.state || {};
  const folder = st.commission ? "Commission a device" : st.name || st.folder || "";
  const net = onlineNetwork();
  const conn = st.commission ? (S.adapterOn ? "USB adapter" + (S.online && S.online.adapter ? " " + S.online.adapter : "") : "not connected")
    : connSimOn() ? "standalone simulator" : S.runtimeOn ? "runtime " + ((S.online && S.online.host) || "") : "not connected";
  bar.replaceChildren(el("strong", null, "Trace"), el("span", null, folder),
    net ? el("span", null, "network " + net) : null, el("span", { dataset: { trace: "window-conn" } }, conn));
  document.title = "Trace – " + (st.commission ? "commissioning" : st.name || (st.folder || "").split(/[\\/]/).pop() || "canworks");
}

// Without an open folder the trace window waits for the main window to open one.
function renderTraceWindowEmpty() {
  for (const id of ["#start", "#bottom", "#tool-tabs", "#conn-bar"]) $(id).hidden = true;
  $("#editor").hidden = false;
  $("#view").replaceChildren(el("p", { class: "muted", dataset: { trace: "window-empty" } },
    "No folder is open. Open a project or start commissioning in the main window; the trace shows here."));
  traceWinBar();
}

// Explain in Frame lab from the trace window: the main window does it.
function traceWinGoto(msg) {
  if (Date.now() - TW.mainSeen < 5000) traceWinPost(msg);
  else {
    TW.pending.push(msg);
    // No main window: the main page opens and takes the message when it is ready.
    window.open("/", "_blank");
  }
  if (window.opener && !window.opener.closed) try { window.opener.focus(); } catch (e) { /* another page */ }
}

function traceWinApply(msg) {
  if (!S.state) return;  // still loading: the next message (every 2 s) comes after
  if (msg.key !== traceWinKey()) { location.reload(); return; }
  if (!S.state.mode) return;
  const netBefore = onlineNetwork();
  Object.assign(S, { runtimeOn: msg.runtimeOn, runtimeOff: msg.runtimeOff, adapterOn: msg.adapterOn, simOn: msg.simOn,
    runtimeNets: msg.runtimeNets });
  if (S.online && msg.host) S.online.host = msg.host;
  if (msg.onlineNet && msg.onlineNet !== S.onlineNet && S.model) {
    const i = S.model.networks.findIndex((n) => netName(n) === msg.onlineNet);
    if (i >= 0 && i !== S.net) openNet(i);
    S.onlineNet = msg.onlineNet;
  }
  if (onlineNetwork() !== netBefore) { stopTrace(); render(); }
  else traceWinBar();
}

// The trace window's own network picker tells the main window.
function traceWinNet(name) { if (TRACE_WINDOW) traceWinPost({ type: "net", name }); }

// Start in the trace window: the main window opens the runtime connection it has set up.
function traceWinEnsure() { traceWinPost({ type: "ensure" }); }

function traceWinMessage(e) {
  const m = e.data || {};
  if (TRACE_WINDOW) {
    if (["ping", "conn", "main-ready"].includes(m.type)) {
      TW.mainSeen = Date.now();
      if (m.type === "ping") traceWinPost({ type: "open" });
      if (m.type === "main-ready") for (const g of TW.pending.splice(0)) traceWinPost(g);
    }
    if (m.type === "conn") traceWinApply(m);
    if (m.type === "select") traceBackFrom(m.src);
    if (m.type === "bring-back") window.close();
    return;
  }
  if (m.type === "open") {
    const was = traceWinElsewhere();
    TW.seen = Date.now();
    if (!was) { traceWinSwitched(); traceWinSendConn(true); }
  } else if (m.type === "closed") {
    TW.seen = 0;
    traceWinSwitched();
  } else if (m.type === "goto") {
    if (m.kind === "explain") traceExplainInLab(m.seq, m.tab);
    else if (m.kind === "text") traceExplainText(m.text);
  } else if (m.type === "net") {
    if (S.model && m.name !== onlineNetwork()) pickNetwork(m.name);
  } else if (m.type === "ensure") {
    if (!(S.state && S.state.commission)) connEnsure();
    traceWinSendConn(true);
  }
}

function traceWinStart() {
  if (!TW.ch) return;
  TW.ch.addEventListener("message", traceWinMessage);
  if (TRACE_WINDOW) {
    document.body.classList.add("trace-window");
    $("#top").prepend(el("div", { id: "trace-win-bar", class: "trace-win-bar", dataset: { trace: "window-bar" } }));
    traceWinPost({ type: "open" });
    TW.timer = setInterval(() => traceWinPost({ type: "open" }), 2000);
    window.addEventListener("pagehide", () => traceWinPost({ type: "closed" }));
    let sizeTimer = null;
    window.addEventListener("resize", () => {
      clearTimeout(sizeTimer);
      sizeTimer = setTimeout(() => tracePrefs({ window_w: clampTo(window.outerWidth, [300, 10000]), window_h: clampTo(window.outerHeight, [200, 10000]) }), 500);
    });
    return;
  }
  traceWinPost({ type: "ping" });
  traceWinPost({ type: "main-ready" });
  TW.timer = setInterval(() => {
    if (traceWinElsewhere()) traceWinSendConn(true);
    else if (TW.seen && S.view === "trace" && !$("#trace-source")) { TW.seen = 0; traceWinSwitched(); }  // closed without a word
  }, 2000);
}

traceWinStart();
