// The Trace tab's transmit list (canopen-configurator: "Transmit list",
// "Sending from the transmit list", "Cyclic send jobs", "Transmit list
// storage and files", "Send… adds to the transmit list"). The rows are kept
// on this PC per folder and network (/api/trace/transmit); frames go out
// with send_frame through the page's connection. Cyclic jobs keep running
// when the Trace tab is left; closing the page stops them. Loaded after
// trace.js.
"use strict";

const TX = {
  rows: [], net: undefined, loaded: false, seq: 0, timer: null, saveTimer: null, nextKey: 1,
  state: {},      // row key -> {text, error, sent, job}
  jobs: [],       // cyclic jobs started here: {job, network, key, id, period_ms, count, sent}
  previews: {},   // candump text -> preview line
  errors: {},     // row key -> {field: message}
  focusKey: null, firstSend: true, open: true, height: 220,
  pending: [],    // rows added by Send… before the stored list was read
};

const TX_FIELDS = ["name", "id", "ext", "rtr", "dlc", "data", "period_ms", "count"];

function txKeyed(r) { return Object.assign({ _k: TX.nextKey++ }, r); }

function txPlain(r) {
  const o = {};
  for (const f of TX_FIELDS) o[f] = r[f] === undefined ? null : r[f];
  return o;
}

// The checks the server makes, as the user types (transmit.check_row).
function txCheck(r) {
  const err = {};
  const id = String(r.id || "").trim().replace(/^0x/i, "");
  if (!/^[0-9a-fA-F]+$/.test(id)) err.id = "the identifier must be hex, e.g. 205";
  else if (parseInt(id, 16) > (r.ext ? 0x1FFFFFFF : 0x7FF)) err.id = `out of range for a ${r.ext ? "29" : "11"}-bit identifier`;
  if (r.rtr) {
    const d = Number(r.dlc);
    if (!Number.isInteger(d) || d < 0 || d > 8) err.dlc = "DLC must be 0-8";
  } else {
    const t = String(r.data || "").replace(/\s+/g, "");
    if (t.length % 2) err.data = "the data needs whole bytes (two hex digits each)";
    else if (t && !/^[0-9a-fA-F]+$/.test(t)) err.data = "the data must be hex bytes, e.g. 0F 01";
    else if (t.length > 16) err.data = "at most 8 data bytes";
  }
  if (r.period_ms !== null && r.period_ms !== "" && r.period_ms !== undefined) {
    const p = Number(r.period_ms);
    if (!Number.isInteger(p) || p < 10 || p > 60000) err.period_ms = "the period must be 10 to 60000 ms";
  }
  if (r.count !== null && r.count !== "" && r.count !== undefined) {
    const c = Number(r.count);
    if (!Number.isInteger(c) || c < 1) err.count = "the count must be at least 1";
  }
  return err;
}

function txCandump(r) {
  const id = String(r.id || "").trim().replace(/^0x/i, "").toUpperCase();
  if (r.rtr) return `${r.ext ? id.padStart(8, "0") : id}#R${r.dlc ? r.dlc : ""}`;
  return `${r.ext ? id.padStart(8, "0") : id}#${String(r.data || "").replace(/\s+/g, "").toUpperCase()}`;
}

function txCyclic(r) { return r.period_ms !== null && r.period_ms !== "" && r.period_ms !== undefined; }

// Why sending is not possible now, or null.
function txBlocked() {
  if (typeof sendBlocked === "function") return sendBlocked();
  return null;
}

async function txLoad() {
  const net = onlineNetwork();
  if (TX.loaded && TX.net === net) return;
  const my = ++TX.seq;
  let r;
  try { r = await api("POST", "/api/trace/transmit", {}); } catch (e) { banner(e.message, true); return; }
  if (my !== TX.seq) return;
  TX.net = net;
  TX.loaded = true;
  TX.rows = r.frames.map(txKeyed).concat(TX.pending);
  TX.state = {};
  TX.errors = {};
  if (TX.pending.length) {
    TX.focusKey = TX.pending[TX.pending.length - 1]._k;
    TX.pending = [];
    txSave();
  }
  txDraw();
}

function txSave() {
  if (!TX.loaded) return;  // nothing to overwrite the stored list with yet
  clearTimeout(TX.saveTimer);
  const body = { frames: null };
  if (TX.net !== null && TX.net !== undefined) body.network = TX.net;  // the list's own network
  TX.saveTimer = setTimeout(async () => {
    body.frames = TX.rows.filter((r) => !Object.keys(txCheck(r)).length).map(txPlain);
    try { await api("POST", "/api/trace/transmit", body); } catch (e) { banner(e.message, true); }
  }, 300);
}

function txPane() {
  const d = el("details", { class: "tx-pane", id: "tx-pane", dataset: { trace: "transmit" }, open: TX.open ? true : null });
  d.addEventListener("toggle", () => { TX.open = d.open; tracePrefs({ pane_open: d.open }); });
  d.append(el("summary", { id: "tx-summary" }, txSummaryText()), el("div", { id: "tx-body", class: "tx-body" }));
  d.style.setProperty("--tx-height", TX.height + "px");
  txLoad().then(() => { txDraw(); txPollJobs(); });
  return d;
}

function txSummaryText() {
  const running = TX.jobs.filter((j) => j.network === onlineNetwork() || j.network == null).length;
  const all = TX.jobs.length;
  return `Transmit list (${TX.rows.length} frame${TX.rows.length === 1 ? "" : "s"}` +
    (all ? `, ${all} cyclic job${all === 1 ? "" : "s"} running${all !== running ? ` (${all - running} on other networks)` : ""}` : "") + ")";
}

function txDraw() {
  const s = $("#tx-summary");
  if (s) s.textContent = txSummaryText();
  const body = $("#tx-body");
  if (!body) return;
  const active = document.activeElement;
  const focus = active && active.closest && active.closest("[data-tx-key]") ?
    { key: active.closest("[data-tx-key]").dataset.txKey, field: active.dataset.tx } : null;
  const blocked = txBlocked();
  const fileInput = el("input", { type: "file", accept: ".json", dataset: { tx: "open-input" } });
  fileInput.addEventListener("change", () => {
    const f = fileInput.files[0];
    fileInput.value = "";
    if (f) txOpenFile(f);
  });
  body.replaceChildren(...[
    el("div", { class: "toolbar" },
      el("button", { type: "button", dataset: { tx: "add" }, onclick: () => txAdd({ id: "", data: "" }, true) }, "Add frame"),
      el("button", { type: "button", dataset: { tx: "stop-all" }, disabled: !TX.jobs.length && "Nothing is being sent.", onclick: () => txStop(null) }, "Stop all"),
      el("button", { type: "button", dataset: { tx: "save" }, disabled: !TX.rows.length && "The list is empty.", onclick: txSaveFile }, "Save list…"),
      el("label", { class: "file-button", title: "Open a transmit list file (.transmit.json)" }, "Open list…", fileInput),
      el("button", { type: "button", dataset: { tx: "clear" }, disabled: !TX.rows.length && "The list is empty.", onclick: txClear }, "Clear list")),
    blocked ? el("p", { class: "field-msg warning", dataset: { tx: "blocked" } }, blocked + ". The list can still be edited and saved.") : null,
    TX.rows.length ? el("div", { class: "tx-table", role: "table", "aria-label": "Transmit list" },
      el("div", { class: "tx-row tx-head", role: "row" }, ["Name", "ID (hex)", "Ext", "RTR", "Data / DLC", "Period ms", "Count", "Decoded", "State", "Actions"]
        .map((h) => el("div", { role: "columnheader" }, h))),
      TX.rows.map((r, i) => txRow(r, i, blocked)))
      : el("p", { class: "muted", dataset: { tx: "empty" } }, "No frames. Add frame, or pick Send… on a trace row or in the Frame lab.")]
    .filter(Boolean));
  if (focus) {
    const e = body.querySelector(`[data-tx-key="${focus.key}"] [data-tx="${focus.field}"]`);
    if (e) e.focus();
  } else if (TX.focusKey != null) {
    const e = body.querySelector(`[data-tx-key="${TX.focusKey}"] [data-tx=send]`);
    TX.focusKey = null;
    if (e) { e.focus(); e.scrollIntoView({ block: "nearest" }); }
  }
}

function txRow(r, i, blocked) {
  const err = txCheck(r);
  TX.errors[r._k] = err;
  const st = TX.state[r._k] || {};
  const job = TX.jobs.find((j) => j.key === r._k);
  const input = (field, label, width, attrs) => {
    const e = el("input", Object.assign({ type: "text", spellcheck: "false", autocomplete: "off", "aria-label": label,
      dataset: { tx: field }, "aria-invalid": err[field] ? "true" : null }, attrs || {}));
    e.value = r[field] == null ? "" : String(r[field]);
    e.style.width = width;
    e.addEventListener("change", () => { r[field] = e.value.trim(); txEdited(r); });
    e.addEventListener("input", () => { r[field] = e.value.trim(); txMessages(r); });
    return e;
  };
  const check = (field, label) => {
    const c = el("input", { type: "checkbox", checked: !!r[field], "aria-label": label, dataset: { tx: field } });
    c.onchange = () => { r[field] = c.checked; txChanged(r); };
    return c;
  };
  const invalid = Object.keys(err).length > 0;
  const cyclic = txCyclic(r);
  let action;
  if (cyclic && job) {
    action = el("button", { type: "button", dataset: { tx: "stop" }, onclick: () => txStop(job) }, "Stop");
  } else {
    action = el("button", { type: "button", class: "primary", dataset: { tx: "send" }, disabled: !!blocked || invalid,
      title: blocked || (invalid ? "Fix the row first" : null), onclick: () => txSend(r, false) }, cyclic ? "Start" : "Send");
  }
  const state = job ? `running, ${job.sent} sent${job.count ? " of " + job.count : ""}` : st.error ? `refused: ${st.error}` : st.text || "idle";
  const msgs = Object.values(err);
  return el("div", { class: "tx-row" + (job ? " running" : "") + (st.error ? " refused" : ""), role: "row", dataset: { txKey: r._k } },
    el("div", { role: "cell" }, input("name", "Name", "14ch", { placeholder: "name" })),
    el("div", { role: "cell" }, input("id", "Identifier (hex)", "10ch", { placeholder: "60A", class: "mono" })),
    el("div", { role: "cell" }, check("ext", "Extended (29-bit)")),
    el("div", { role: "cell" }, check("rtr", "Remote frame")),
    el("div", { role: "cell" }, r.rtr ? input("dlc", "DLC", "5ch", { placeholder: "0" })
      : input("data", "Data bytes (hex)", "24ch", { placeholder: "40 18 10 01", class: "mono" })),
    el("div", { role: "cell" }, input("period_ms", "Period in ms (empty: one frame)", "8ch", { placeholder: "once" })),
    el("div", { role: "cell" }, input("count", "Count (empty: no limit)", "7ch", { placeholder: "∞", disabled: !cyclic && "Only for a cyclic frame: set a period first." })),
    el("div", { role: "cell", class: "tx-preview muted", dataset: { tx: "preview" } }, txPreview(r, invalid)),
    el("div", { role: "cell", class: "tx-state", dataset: { tx: "state" } }, state),
    el("div", { role: "cell", class: "tx-actions" }, action,
      el("details", { class: "menu tx-more" }, el("summary", { "aria-label": "More actions for this frame", title: "More" }, "⋯"),
        el("div", { role: "menu", class: "menu-panel" },
          el("button", { type: "button", class: "item", role: "menuitem", dataset: { tx: "explain" }, disabled: invalid && "Fix the row first.",
            onclick: () => { txCloseMenus(); traceExplainText(txCandump(r)); } }, "Explain in Frame lab"),
          el("button", { type: "button", class: "item", role: "menuitem", dataset: { tx: "duplicate" },
            onclick: () => { txCloseMenus(); TX.rows.splice(i + 1, 0, txKeyed(txPlain(r))); txSave(); txDraw(); } }, "Duplicate"),
          el("button", { type: "button", class: "item", role: "menuitem", dataset: { tx: "up" }, disabled: i === 0 && "Already the first frame.",
            onclick: () => { txCloseMenus(); txMove(i, -1); } }, "Move up"),
          el("button", { type: "button", class: "item", role: "menuitem", dataset: { tx: "down" }, disabled: i === TX.rows.length - 1 && "Already the last frame.",
            onclick: () => { txCloseMenus(); txMove(i, 1); } }, "Move down"),
          el("button", { type: "button", class: "item", role: "menuitem", dataset: { tx: "remove" },
            onclick: () => { txCloseMenus(); txRemove(i); } }, "Remove")))),
    msgs.length ? el("div", { class: "tx-msg field-msg error", role: "alert", dataset: { tx: "msg" } }, msgs.join("; ")) : null);
}

function txCloseMenus() { for (const m of document.querySelectorAll(".tx-more[open]")) m.open = false; }

// Only the messages and the Send button while typing, so focus stays put.
function txMessages(r) {
  const row = document.querySelector(`[data-tx-key="${r._k}"]`);
  if (!row) return;
  const err = txCheck(r);
  let m = row.querySelector("[data-tx=msg]");
  const msgs = Object.values(err);
  if (msgs.length) {
    if (!m) { m = el("div", { class: "tx-msg field-msg error", role: "alert", dataset: { tx: "msg" } }); row.append(m); }
    m.textContent = msgs.join("; ");
  } else if (m) m.remove();
  for (const f of ["id", "data", "dlc", "period_ms", "count"]) {
    const e = row.querySelector(`[data-tx=${f}]`);
    if (e) e.setAttribute("aria-invalid", err[f] ? "true" : "false");
  }
  const send = row.querySelector("[data-tx=send]");
  if (send) Icons.setDisabled(send, txBlocked() || (msgs.length > 0 && "Fix the row first"));
}

// A text box was left: the row is updated in place, so Tab and clicks reach
// the next box (a redraw here would drop the focus).
function txEdited(r) {
  delete TX.state[r._k];
  txSave();
  txMessages(r);
  const row = document.querySelector(`[data-tx-key="${r._k}"]`);
  if (!row) return;
  const err = txCheck(r);
  const invalid = Object.keys(err).length > 0;
  const cyclic = txCyclic(r);
  const send = row.querySelector("[data-tx=send]");
  if (send) send.textContent = cyclic ? "Start" : "Send";
  const count = row.querySelector("[data-tx=count]");
  if (count) Icons.setDisabled(count, !cyclic && "Only for a cyclic frame: set a period first.");
  const preview = row.querySelector("[data-tx=preview]");
  if (preview) preview.textContent = txPreview(r, invalid);
  const state = row.querySelector("[data-tx=state]");
  if (state && !TX.jobs.some((j) => j.key === r._k)) state.textContent = "idle";
  row.classList.remove("refused");
  const explain = row.querySelector("[data-tx=explain]");
  if (explain) Icons.setDisabled(explain, invalid && "Fix the row first.");
}

function txChanged(r) {
  delete TX.state[r._k];
  txSave();
  txDraw();
}

function txPreview(r, invalid) {
  if (invalid || !r.id) return "";
  const text = txCandump(r);
  const p = TX.previews[text];
  if (p !== undefined) return p;
  TX.previews[text] = "…";
  api("POST", "/api/explain", Object.assign(typeof fxLabBody === "function" ? fxLabBody({}) : {}, { frame: text }))
    .then((res) => {
      const m = res.explanation;
      const used = m.kind && !["other", "raw"].includes(m.kind) && m.kind !== "error";
      TX.previews[text] = (m.title || m.meaning || "") + (used ? " · identifier in use: sending asks first" : "");
    })
    .catch((e) => { TX.previews[text] = ""; })
    .then(() => {
      for (const c of document.querySelectorAll(`[data-tx-key] [data-tx=preview]`)) {
        const row = TX.rows.find((x) => String(x._k) === c.closest("[data-tx-key]").dataset.txKey);
        if (row && txCandump(row) === text) c.textContent = TX.previews[text];
      }
    });
  return "…";
}

function txMove(i, d) {
  const j = i + d;
  if (j < 0 || j >= TX.rows.length) return;
  [TX.rows[i], TX.rows[j]] = [TX.rows[j], TX.rows[i]];
  txSave();
  txDraw();
}

async function txRemove(i) {
  const r = TX.rows[i];
  const job = TX.jobs.find((j) => j.key === r._k);
  if (job) await txStop(job);
  TX.rows.splice(i, 1);
  txSave();
  txDraw();
}

async function txClear() {
  const v = await modal(`Remove all ${TX.rows.length} frames from the transmit list? Running cyclic jobs are stopped.`,
    [["cancel", "Keep the list"], ["clear", "Clear the list", { danger: true }]]);
  if (v !== "clear") return;
  if (TX.jobs.length) await txStop(null);
  TX.rows = [];
  txSave();
  txDraw();
}

// Send… elsewhere: the frame becomes the list's last row, nothing is sent.
function txAdd(frame, focusId) {
  const r = txKeyed({ name: frame.name || "", id: String(frame.id || "").replace(/^0x/i, "").toUpperCase(), ext: !!frame.ext,
    rtr: !!frame.rtr, dlc: frame.rtr ? (frame.dlc || 0) : null, data: frame.rtr ? "" : (frame.data || ""), period_ms: null, count: null });
  if (!TX.loaded || TX.net !== onlineNetwork()) {
    TX.pending.push(r);  // txLoad appends it to the stored list
    TX.open = true;
    return r;
  }
  TX.rows.push(r);
  TX.open = true;
  const pane = $("#tx-pane");
  if (pane) pane.open = true;
  if (!focusId) TX.focusKey = r._k;
  txSave();
  txDraw();
  if (focusId) {
    const e = document.querySelector(`[data-tx-key="${r._k}"] [data-tx=id]`);
    if (e) e.focus();
  }
  return r;
}

function sendButton(frame) {
  const blocked = txBlocked();
  return el("button", { type: "button", dataset: { trace: "send-this" }, disabled: !!blocked,
    title: blocked ? `${blocked}.` : "Add this frame to the transmit list; it is sent when you press Send there",
    "aria-description": blocked ? `${blocked}.` : null, onclick: () => traceSendTo(typeof frame === "function" ? frame() : frame) }, "Send…");
}

async function txSend(r, force) {
  const body = { id: String(r.id).replace(/^0x/i, ""), ext: !!r.ext, rtr: !!r.rtr, port: diagPort() };
  if (r.rtr) body.dlc = Number(r.dlc || 0);
  else body.data = r.data || "";
  if (txCyclic(r)) {
    body.period_ms = Number(r.period_ms);
    if (r.count) body.count = Number(r.count);
  }
  if (force) body.force = true;
  let res;
  try {
    res = await api("POST", "/api/online/send_frame", body);
  } catch (e) {
    if (e.body && e.body.force && !force) {
      const v = await modal(`The runtime refused this frame: "${e.message}". Send it anyway?`,
        [["force", "Send anyway", true], ["cancel", "Cancel"]]);
      if (v === "force") return txSend(r, true);
      TX.state[r._k] = { text: "not sent" };
      txDraw();
      return;
    }
    TX.state[r._k] = { error: e.message };
    txDraw();
    return;
  }
  const now = new Date();
  const time = now.toLocaleTimeString() + "." + String(now.getMilliseconds()).padStart(3, "0");
  if (res.job !== undefined && res.job !== null) {
    TX.jobs.push({ job: res.job, network: onlineNetwork(), key: r._k, id: body.id, ext: body.ext, rtr: body.rtr,
      dlc: body.dlc, data: body.data, period_ms: res.period_ms, count: res.count, sent: 0 });
    TX.state[r._k] = { text: `started ${time}` };
    txPollJobs();
  } else {
    TX.state[r._k] = { text: `sent ${time}` + (force ? " (forced)" : "") };
  }
  txDraw();
}

function txPollJobs() {
  clearTimeout(TX.timer);
  TX.timer = null;
  if (!TX.jobs.length) return;
  TX.timer = setTimeout(async () => {
    let r;
    try { r = await api("POST", "/api/online/send_jobs", { port: diagPort() }); } catch (e) { r = null; }
    if (r) {
      const byJob = new Map(r.jobs.map((j) => [`${j.network}|${j.job}`, j]));
      for (const j of TX.jobs) {
        const live = byJob.get(`${j.network}|${j.job}`);
        if (live) j.sent = live.sent;
      }
      for (const e of r.ended) {
        const j = TX.jobs.find((x) => x.job === e.job && x.network === e.network);
        if (!j) continue;
        TX.state[j.key] = e.reason === "count reached" ? { text: `done, ${e.sent} sent` } : { error: `${e.reason}, ${e.sent} sent` };
        if (e.reason !== "stopped" && e.reason !== "count reached") banner(`Cyclic job for ${sendFrameText(e)} ended: ${e.reason}, ${e.sent} sent.`, true);
      }
      const ended = new Set(r.ended.map((e) => `${e.network}|${e.job}`));
      TX.jobs = TX.jobs.filter((j) => byJob.has(`${j.network}|${j.job}`) && !ended.has(`${j.network}|${j.job}`));
      txDrawStates();
    }
    txPollJobs();
  }, 1000);
}

// Only the states and buttons, so a job update does not take the focus.
function txDrawStates() {
  const s = $("#tx-summary");
  if (s) s.textContent = txSummaryText();
  if (!$("#tx-body")) return;
  const focused = document.activeElement && document.activeElement.closest && document.activeElement.closest("#tx-body");
  if (!focused) { txDraw(); return; }
  for (const r of TX.rows) {
    const row = document.querySelector(`[data-tx-key="${r._k}"] [data-tx=state]`);
    const job = TX.jobs.find((j) => j.key === r._k);
    const st = TX.state[r._k] || {};
    if (row) row.textContent = job ? `running, ${job.sent} sent${job.count ? " of " + job.count : ""}` : st.error ? `refused: ${st.error}` : st.text || "idle";
  }
}

async function txStop(job) {
  try {
    const r = await api("POST", "/api/online/send_stop", job ? { job: job.job, network: job.network, port: diagPort() } : { port: diagPort() });
    for (const s of r.stopped || []) {
      const j = TX.jobs.find((x) => x.job === s.job && (x.network === s.network || s.network == null));
      if (j) TX.state[j.key] = { text: `stopped, ${s.sent} sent` };
    }
    TX.jobs = job ? TX.jobs.filter((j) => !(j.job === job.job && j.network === job.network)) : [];
  } catch (e) { banner(e.message, true); }
  txDraw();
}

async function txSaveFile() {
  try {
    const r = await api("POST", "/api/trace/transmit/dump", { frames: TX.rows.map(txPlain) });
    const url = URL.createObjectURL(new Blob([r.text], { type: "application/json" }));
    const a = el("a", { href: url, download: r.name });
    document.body.append(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 10000);
    banner(`Downloaded ${r.name}.`);
  } catch (e) { banner(e.message, true); }
}

async function txOpenFile(file) {
  let r;
  try { r = await api("POST", "/api/trace/transmit/load", { text: await file.text() }); } catch (e) { banner(e.message, true); return; }
  if (r.other_network) {
    const v = await modal(`${file.name} was saved for network ${r.network}. Use it on ${onlineNetwork()} anyway?`,
      [["cancel", "Cancel"], ["use", "Use it here"]]);
    if (v !== "use") return;
  }
  let how = "replace";
  if (TX.rows.length) {
    how = await modal(`Add the ${r.frames.length} frames of ${file.name} to the list, or replace the list's ${TX.rows.length} frames?`,
      [["cancel", "Cancel"], ["add", "Add to the list"], ["replace", "Replace the list", { danger: true }]]);
    if (how !== "add" && how !== "replace") return;
  }
  const rows = r.frames.map(txKeyed);
  TX.rows = how === "add" ? TX.rows.concat(rows) : rows;
  txSave();
  txDraw();
  banner(`Opened ${file.name}: ${r.frames.length} frame${r.frames.length === 1 ? "" : "s"}.`);
}

// Closing or reloading the page stops its jobs (keepalive outlives the page).
window.addEventListener("pagehide", () => {
  if (!TX.jobs.length) return;
  TX.jobs = [];
  fetch("/api/online/send_stop", { method: "POST", keepalive: true,
    headers: { "X-CANopen-Token": TOKEN, "Content-Type": "application/json" }, body: JSON.stringify({ port: diagPort() }) });
});
