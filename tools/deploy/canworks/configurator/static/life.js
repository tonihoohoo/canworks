"use strict";
// The configurator's life (configurator-quit-and-background): Quit in the
// header, the page's heartbeat and its pagehide beacon (the configurator
// stops when its last page is closed), the leave-page question, and a second
// canworks-config's PATH. Loaded after app.js and uses its helpers.

const LIFE = {
  page: (window.crypto && crypto.randomUUID) ? crypto.randomUUID() : String(Math.random()).slice(2) + String(Date.now()),
  timer: null,
  stopped: false,
  unsaved: false,  // as the last heartbeat told the server
  epoch: null,  // the server's count of folders a second start opened: a change reloads the page
  asked: null,  // the second start's request this page asked about
};
const HEARTBEAT_MS = 30000;

// Every 30 s, on becoming visible and when the page comes back from the
// back/forward cache. The answer may carry a second start's PATH.
async function heartbeat() {
  if (LIFE.stopped) return;
  clearTimeout(LIFE.timer);
  LIFE.timer = setTimeout(heartbeat, HEARTBEAT_MS);
  let r;
  LIFE.unsaved = !!unsavedWork();
  try {
    const res = await fetch("/api/heartbeat", {
      method: "POST",
      headers: { "X-CANopen-Token": TOKEN, "Content-Type": "application/json" },
      body: JSON.stringify({ page: LIFE.page, unsaved: LIFE.unsaved }),
    });
    if (!res.ok) return;
    r = await res.json();
  } catch (e) { return; }  // the configurator has stopped, or is busy: the next beat tells
  if (LIFE.epoch !== null && r.epoch !== LIFE.epoch && !unsavedWork() && !TRACE_WINDOW) {
    LIFE.epoch = r.epoch;
    await loadState();  // a second canworks-config opened a folder
  }
  LIFE.epoch = r.epoch;
  if (r.waiting && !TRACE_WINDOW) {
    banner(`canworks-config was started again with ${r.waiting}. Another tab of the configurator has unsaved changes: it asks there first.`, "info");
  }
  if (r.open && !TRACE_WINDOW && (!LIFE.asked || LIFE.asked !== r.open.id)) {
    LIFE.asked = r.open.id;
    secondStartOpen(r.open);
  }
}

// canworks-config PATH while this page has unsaved changes: asks first.
async function secondStartOpen(req) {
  let go = true;
  if (unsavedWork()) {
    const canSave = S.dirty && S.state && S.state.mode && !S.state.commission;
    const v = await modal(`canworks-config was started again to open ${req.path}. This page has unsaved changes.`,
      canSave ? [["cancel", "Cancel"], ["save", "Save and open", true], ["open", "Open without saving", { danger: true }]]
        : [["cancel", "Cancel"], ["open", "Open without saving", { danger: true }]]);
    if (v === "save") {
      await save(false);
      go = !S.dirty;
    } else go = v === "open";
  }
  if (go && typeof leaveCommission === "function") go = await leaveCommission("opening " + req.path);
  try { await api("POST", "/api/second_start/done", { id: req.id }); } catch (e) { /* stopped meanwhile */ }
  if (go) await openFolder(req.path);
}

// The page is going away (closed, reloaded, another address): the
// configurator stops 10 s later unless a page beats again.
function pageClosed() {
  if (LIFE.stopped || !navigator.sendBeacon) return;
  navigator.sendBeacon("/api/page/closed", JSON.stringify({ page: LIFE.page }));
}

// Closing or reloading always asks (it stops the configurator when this is
// its last page); browsers ask only after the user clicked or typed on the
// page, and in their own words. The trace window, and the main window while
// the trace window is open, ask only about unsaved work: the other one keeps
// the configurator running.
function leaveAsks() {
  if (LIFE.stopped) return false;
  if (TRACE_WINDOW || (typeof traceWinElsewhere === "function" && traceWinElsewhere())) return unsavedWork();
  return true;
}

// What stops with the configurator: the adapter connection and the jobs
// in the status bar, as one sentence, or "".
async function quitStops() {
  const parts = [];
  if (S.state && S.state.mode && typeof connAdapter === "function" && connAdapter() && connIsOn()) parts.push("the adapter connection");
  let jobs = [];
  if (S.state && S.state.mode && typeof diagPort === "function") {
    try { jobs = (await api("POST", "/api/online/jobs", { port: diagPort() })).jobs || []; } catch (e) { jobs = JOBS.list || []; }
  }
  if (jobs.length === 1) parts.push(jobs[0].label.charAt(0).toLowerCase() + jobs[0].label.slice(1));
  else if (jobs.length) parts.push(`${jobs.length} jobs (${jobs.map((j) => j.label).join(", ")})`);
  if (!parts.length) return "";
  const s = parts.join(" and ");
  return s.charAt(0).toUpperCase() + s.slice(1) + " will stop.";
}

async function quitConfigurator() {
  const stops = await quitStops();
  const after = stops ? " " + stops : "";
  const canSave = S.dirty && S.state && S.state.mode && !S.state.commission;
  let v;
  if (unsavedWork()) {
    v = await modal("Quit canworks-config? There are unsaved changes." + after,
      canSave ? [["cancel", "Cancel"], ["save", "Save and quit", true], ["quit", "Quit without saving", { danger: true }]]
        : [["cancel", "Cancel"], ["quit", "Quit without saving", { danger: true }]]);
  } else {
    v = await modal("Quit canworks-config?" + after, [["cancel", "Cancel"], ["quit", "Quit", true]]);
  }
  if (v === "save") {
    await save(false);
    if (S.dirty) return;  // not saved: the page stays, with why
  } else if (v !== "quit") return;
  try {
    await api("POST", "/api/quit");
  } catch (e) {
    banner(e.message, true);
    return;
  }
  showStopped();
}

// After Quit: the page says so; nothing on it asks the server any more.
function showStopped() {
  LIFE.stopped = true;
  clearTimeout(LIFE.timer);
  if (typeof JOBS !== "undefined") clearTimeout(JOBS.timer);
  for (const d of document.querySelectorAll("dialog[open]")) d.close();
  document.title = "canworks configurator (stopped)";
  document.body.dataset.stopped = "1";
  document.body.append(el("main", { id: "stopped", class: "stopped", role: "status" },
    el("h1", null, "canworks-config has stopped. You can close this tab."),
    el("p", null, "To start it again, run canworks-config in a terminal, or open the canworks configurator shortcut.")));
}

function wireLife() {
  $("#btn-quit").onclick = () => quitConfigurator();
  window.addEventListener("beforeunload", (e) => {
    if (leaveAsks()) { e.preventDefault(); e.returnValue = ""; }
  });
  window.addEventListener("pagehide", pageClosed);
  window.addEventListener("pageshow", (e) => { if (e.persisted) heartbeat(); });
  document.addEventListener("visibilitychange", () => { if (document.visibilityState === "visible") heartbeat(); });
  // The server knows at once when the page gets or loses unsaved changes: a
  // second canworks-config PATH opens at once only without them.
  setInterval(() => { if (!LIFE.stopped && !!unsavedWork() !== LIFE.unsaved) heartbeat(); }, 1000);
  heartbeat();
}
