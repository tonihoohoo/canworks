"use strict";
// The status bar (ui-shell-and-connection): the running jobs of this page
// (scan, LSS find, Read all, back up, compare, restore, write configuration,
// trace recording, PDO test, SYNC, cyclic sends) with their progress and
// Cancel, on every page; and, while connected, the frame rate and the
// estimated bus load. Loaded after app.js and uses its helpers.

const JOBS = { timer: null, list: [], frames: null, rate: null };
const JOBS_FAST_MS = 1000;
const JOBS_SLOW_MS = 5000;
const BITS_PER_FRAME = 125;  // an 11-bit frame with 8 data bytes and typical stuffing

function jobsStart() {
  clearTimeout(JOBS.timer);
  jobsTick();
}

// Polls quickly while something runs, slowly otherwise, only with a folder open.
async function jobsTick() {
  JOBS.timer = null;
  if (!S.state || !S.state.mode) { JOBS.list = []; renderJobs(); return; }
  try {
    JOBS.list = (await api("POST", "/api/online/jobs", { port: diagPort() })).jobs || [];
  } catch (e) { JOBS.list = []; }
  renderJobs();
  JOBS.timer = setTimeout(jobsTick, JOBS.list.length ? JOBS_FAST_MS : JOBS_SLOW_MS);
}

// A job that was just started: the status bar shows it at once.
function jobsKick() {
  clearTimeout(JOBS.timer);
  JOBS.timer = setTimeout(jobsTick, 150);
}

function jobProgress(j) {
  if (j.done === null || j.done === undefined) return "";
  const unit = j.unit ? ` ${j.unit}` : "";
  return j.total ? `${Number(j.done).toLocaleString()}/${Number(j.total).toLocaleString()}${unit}` : `${Number(j.done).toLocaleString()}${unit}`;
}

async function cancelJob(j, button) {
  if (!j.stop) return;
  if (j.confirm) {
    const v = await modal(j.confirm, [["cancel", "Keep it running"], ["stop", "Cancel it", { danger: true }]]);
    if (v !== "stop") return;
  }
  await busy(button, "Cancelling…", async () => {
    try { await api("POST", j.stop.path, Object.assign({ port: diagPort() }, j.stop.body)); }
    catch (e) { banner(e.message, true); }
  });
  jobsKick();
}

function jobItem(j) {
  const progress = jobProgress(j);
  const bar = j.total ? el("progress", { max: j.total, value: j.done || 0, "aria-hidden": "true" }) : null;
  const cancel = j.stop ? el("button", { type: "button", class: "small", dataset: { jobCancel: j.id }, "aria-label": `Cancel ${j.label}` }, "Cancel") : null;
  if (cancel) cancel.onclick = () => cancelJob(j, cancel);
  return el("span", { class: "job", dataset: { job: j.id } }, el("span", { class: "spinner", "aria-hidden": "true" }),
    el("span", null, j.label + (progress ? ` – ${progress}` : "")), bar, cancel);
}

function renderJobs() {
  const host = $("#jobs");
  if (!host) return;
  const list = JOBS.list;
  // Rebuilt only when the jobs or their progress change, so a focused Cancel keeps focus.
  const sig = JSON.stringify(list.map((j) => [j.id, j.done, j.total, !!j.stop]));
  if (host.dataset.sig === sig) return;
  host.dataset.sig = sig;
  const focused = document.activeElement && host.contains(document.activeElement) ? document.activeElement.dataset.jobCancel : null;
  if (!list.length) host.replaceChildren();
  else if (list.length <= 2) host.replaceChildren(...list.map(jobItem));
  else {
    const open = !!(host.querySelector("details") || {}).open;
    host.replaceChildren(el("details", { class: "jobs-more", open }, el("summary", null, `${list.length} jobs running`),
      el("div", { class: "jobs-list" }, ...list.map(jobItem))));
  }
  if (focused) { const b = host.querySelector(`[data-job-cancel="${focused}"]`); if (b) b.focus(); }
}

// Each status answer of the connection (connection.js): the frame rate and
// the estimated bus load where the connection counts frames (a USB adapter).
function jobsSeen(r) {
  const info = $("#bus-info");
  if (!info) return;
  const c = r && r.conn;
  if (!c || !connIsOn()) { info.textContent = ""; JOBS.frames = null; return; }
  const frames = c.bus && Number.isFinite(c.bus.frames) ? c.bus.frames : null;
  const now = Date.now();
  if (frames !== null && JOBS.frames && frames >= JOBS.frames.n && now > JOBS.frames.at) {
    JOBS.rate = (frames - JOBS.frames.n) * 1000 / (now - JOBS.frames.at);
  }
  if (frames !== null) JOBS.frames = { n: frames, at: now };
  const parts = [];
  if (JOBS.rate !== null && frames !== null) {
    parts.push(`${Math.round(JOBS.rate)} frames/s`);
    if (c.bitrate) parts.push(`bus load about ${Math.min(100, Math.round(JOBS.rate * BITS_PER_FRAME * 100 / c.bitrate))} %`);
  }
  info.textContent = parts.join(" · ");
}
