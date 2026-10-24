"use strict";
// The configurator's life (configurator-quit-and-background): Quit in the
// header, the page's heartbeat and its pagehide beacon (the configurator
// stops when its last page is closed), the leave-page question, a second
// canworks-config's PATH, and the notice when the configurator has gone
// (configurator-survive-sleep). Loaded after app.js and uses its helpers.

const LIFE = {
  page: (window.crypto && crypto.randomUUID) ? crypto.randomUUID() : String(Math.random()).slice(2) + String(Date.now()),
  timer: null,
  stopped: false,
  unsaved: false,  // as the last heartbeat told the server
  epoch: null,  // the server's count of folders a second start opened: a change reloads the page
  asked: null,  // the second start's request this page asked about
  beating: false,  // a heartbeat waits for its answer
  misses: 0,  // heartbeats in a row the configurator did not answer
};
const HEARTBEAT_MS = 30000;
const HEARTBEAT_WAIT_MS = 5000;  // no answer in this long: a miss
const HEARTBEAT_RETRY_MS = 2000;  // after one miss, the next beat comes this soon

// Every 30 s, on becoming visible, getting focus and coming back from the
// back/forward cache. The answer may carry a second start's PATH. A beat the
// configurator does not answer (refused, reset, or nothing in 5 s) is a
// miss; an HTTP error is an answer. Two misses in a row, 2 s apart, mean the
// configurator has gone: the page says so (showStopped). One alone says
// nothing.
async function heartbeat() {
  if (LIFE.stopped || LIFE.beating) return;  // the beat on its way tells
  clearTimeout(LIFE.timer);
  LIFE.timer = setTimeout(heartbeat, HEARTBEAT_MS);
  LIFE.beating = true;
  let r;
  LIFE.unsaved = !!unsavedWork();
  const ctl = typeof AbortController === "function" ? new AbortController() : null;
  const wait = ctl ? setTimeout(() => ctl.abort(), HEARTBEAT_WAIT_MS) : null;
  try {
    const res = await fetch("/api/heartbeat", {
      method: "POST",
      headers: { "X-CANopen-Token": TOKEN, "Content-Type": "application/json" },
      body: JSON.stringify({ page: LIFE.page, unsaved: LIFE.unsaved }),
      signal: ctl ? ctl.signal : undefined,
    });
    LIFE.misses = 0;  // it answered
    if (res.status === 403) {
      let why = null;
      try { why = (await res.json()).error; } catch (e) { /* no body */ }
      if (why === SESSION_REFUSED) { showStopped("restarted"); return; }
    }
    if (!res.ok) return;
    try { r = await res.json(); } catch (e) { return; }  // an answer all the same
  } catch (e) {
    if (LIFE.stopped) return;
    LIFE.misses += 1;
    if (LIFE.misses >= 2) {
      showStopped("gone");
      return;
    }
    clearTimeout(LIFE.timer);
    LIFE.timer = setTimeout(heartbeat, HEARTBEAT_RETRY_MS);
    return;
  } finally {
    clearTimeout(wait);
    LIFE.beating = false;
  }
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
  const update = updateOnQuitText();
  const after = (stops ? " " + stops : "") + (update ? " " + update : "");
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

// "canworks 1.2.3 is installed after it stops.", when Update when I quit was chosen (update.js).
function updateOnQuitText() {
  const v = typeof UPD !== "undefined" ? UPD.view : null;
  return v && v.on_quit ? `canworks ${v.on_quit} is installed after it stops.` : "";
}

// After Quit, or when the configurator has gone ("gone": it did not answer
// two heartbeats; "restarted": it answers with another session, so this
// tab's token is refused): the page says so; nothing on it asks the server
// any more. Gone with unsaved changes, the draft config can still be downloaded.
function showStopped(how) {
  if (LIFE.stopped) return;
  const restarted = how === "restarted";
  const gone = how === "gone" || restarted;
  const unsaved = gone && !!unsavedWork();
  const draft = unsaved && !TRACE_WINDOW && S.model && S.dirty ? fileConfig() : null;
  LIFE.stopped = true;
  clearTimeout(LIFE.timer);
  if (typeof JOBS !== "undefined") clearTimeout(JOBS.timer);
  for (const d of document.querySelectorAll("dialog[open]")) d.close();
  document.title = "canworks configurator (stopped)";
  document.body.dataset.stopped = "1";
  const again = "To start it again, open the canworks configurator shortcut, or run canworks-config in a terminal: it opens a new tab.";
  const box = restarted
    ? el("main", { id: "stopped", class: "stopped", role: "alert", dataset: { restarted: "1" } },
      el("h1", null, "This configurator was restarted."),
      el("p", null, "This tab belongs to the one before, so it stopped. Open the new tab, or the canworks configurator shortcut. " +
        "Once the new configurator has opened in this browser, this tab can join it:"),
      el("p", null, el("button", { type: "button", id: "stopped-reload", onclick: () => location.reload() }, "Open it again in this tab")))
    : gone
    ? el("main", { id: "stopped", class: "stopped", role: "alert", dataset: { gone: "1" } },
      el("h1", null, "canworks-config is not running any more."),
      el("p", null, "It may have been stopped from another tab, by the system, or because this page was away too long."),
      el("p", null, again))
    : el("main", { id: "stopped", class: "stopped", role: "status" },
      el("h1", null, "canworks-config has stopped. You can close this tab."),
      updateOnQuitText() ? el("p", { dataset: { updateOnQuit: "1" } }, updateOnQuitText().replace(" after it stops.",
        " now; give it a minute before you start the configurator again.")) : null,
      el("p", null, again));
  if (unsaved) {
    box.append(el("p", { class: "stopped-unsaved" }, "This page's unsaved changes could not be saved."));
    if (draft) {
      box.append(el("p", null, el("button", { type: "button", class: "primary", id: "stopped-download",
        onclick: () => downloadDraft(draft) }, "Download canworks.json")),
      el("p", null, "It holds this page's config with its unsaved changes; put it in the config folder (or open its folder) "
        + "in a new configurator. It does not hold EDS and notes files imported since the last save, or the simulation's unsaved edits."));
    }
  }
  document.body.append(box);
}

// Saves the page's draft config as canworks.json (the configurator has gone).
function downloadDraft(config) {
  const url = URL.createObjectURL(new Blob([JSON.stringify(config, null, 2) + "\n"], { type: "application/json" }));
  const a = el("a", { href: url, download: "canworks.json" });
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 10000);
}

function wireLife() {
  $("#btn-quit").onclick = () => quitConfigurator();
  window.addEventListener("beforeunload", (e) => {
    if (leaveAsks()) { e.preventDefault(); e.returnValue = ""; }
  });
  window.addEventListener("pagehide", pageClosed);
  // Coming back (visible again, focus, back/forward cache) asks at once
  // whether the configurator still runs.
  window.addEventListener("pageshow", () => heartbeat());
  window.addEventListener("focus", () => heartbeat());
  document.addEventListener("visibilitychange", () => { if (document.visibilityState === "visible") heartbeat(); });
  // The server knows at once when the page gets or loses unsaved changes: a
  // second canworks-config PATH opens at once only without them.
  setInterval(() => { if (!LIFE.stopped && !!unsavedWork() !== LIFE.unsaved) heartbeat(); }, 1000);
  heartbeat();
}
