"use strict";
// Updates from inside the configurator (pc-tools-self-update): a chip in
// the header when a newer release exists, its dialog (What's new, Update
// now, Update when I quit, Skip this version; the install command to copy
// where this copy cannot update itself), the Settings switch and Check now,
// the page while the configurator updates, and the result after it. When
// the tools were reinstalled while this configurator runs, the chip offers
// a restart into the installed version instead. The server checks at start
// when its answer is over an hour old, and again before an update starts
// (update.py). Loaded after life.js.

const UPD = {
  view: null,
  polling: null,
  shownKey: "canworks-update-shown",  // sessionStorage: the result this tab has shown
};
const UPDATE_POLL_MS = 1000;
const UPDATE_GIVE_UP_MS = 180000;

async function updateLoad() {
  try { updateShow(await api("GET", "/api/update")); } catch (e) { /* an older or stopping configurator */ }
}

function updateWhen(t) {
  if (!t) return "never";
  const d = new Date(t * 1000);
  return d.toLocaleDateString(undefined, { day: "numeric", month: "short" }) + " " +
    d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
}

function updateShow(v) {
  UPD.view = v;
  const chip = $("#update-chip");
  const onQuit = v.on_quit && v.on_quit === v.latest;
  const restartOnly = v.restart && !v.newer;
  chip.hidden = !(restartOnly || (v.newer && (!v.dismissed || onQuit)));
  chip.textContent = restartOnly ? `Restart for ${v.installed}`
    : onQuit ? `Updates to ${v.latest} when you quit` : `Update: ${v.latest}`;
  chip.title = restartOnly ? `canworks ${v.installed} is installed; this configurator still runs ${v.version}`
    : onQuit ? "The configurator installs the new version when you quit it or close its last tab"
    : `canworks ${v.latest} is available (you have ${updateHave(v)})`;
  const check = $("#update-check");
  check.checked = v.off !== "setting" && v.off !== "env";
  check.disabled = v.off === "env";
  // Check now asks the same server: off with the reason while the environment turns the check off (UI-7).
  const now = $("#update-check-now");
  if (!now.dataset.busy) now.disabled = v.off === "env";
  now.title = v.off === "env" ? "Turned off by CANWORKS_NO_UPDATE_CHECK" : "";
  let status = `Version ${v.version}. ` + (v.checking ? "Checking…" : `Last check: ${updateWhen(v.checked_at)}.`);
  if (v.error && !v.checking) status += ` The check failed: ${v.error}.`;
  else if (v.latest && !v.checking) status += v.newer ? ` ${v.latest} is available.` : " This is the newest version.";
  if (v.restart) status += ` ${v.installed} is installed: restart the configurator to use it.`;
  if (v.off === "env") status += " Turned off by CANWORKS_NO_UPDATE_CHECK.";
  $("#update-status").textContent = status;
  updateResult(v);
}

// The last update's result, once per tab and only soon after it.
function updateResult(v) {
  const r = v.result;
  if (!r || !r.at || Date.now() / 1000 - r.at > 600) return;
  const key = `${v.boot}:${r.at}`;
  try { if (sessionStorage.getItem(UPD.shownKey) === key) return; sessionStorage.setItem(UPD.shownKey, key); } catch (e) { /* no storage */ }
  if (r.state === "ok" || r.state === "already") banner(r.message || `Updated to ${r.version}.`, "done");
  else banner(`${r.message} The details are in ${v.log}.`, r.state === "locked" ? "warning" : "error");
}

// The version this PC has: the installed one when it is newer than this configurator.
function updateHave(v) {
  return v.restart ? v.installed : v.version;
}

function updateLink(v) {
  return el("a", { href: v.release_url, target: "_blank", rel: "noopener noreferrer" }, `What's new in ${v.latest}`);
}

async function updateDialog() {
  const v = UPD.view;
  if (v && v.restart && !v.newer) return restartDialog(v);
  if (!v || !v.newer) return;
  const intro = `canworks ${v.latest} is available. You have ${updateHave(v)}.`;
  if (v.kind !== "uv-tool") {
    const where = v.kind === "sandboxed"
      ? "Run this in your own PowerShell window (not one opened from inside another app):"
      : (navigator.platform || "").startsWith("Win") ? "Run this in PowerShell:" : "Run this in a terminal:";
    const extra = el("div", null, el("p", null, updateLink(v)),
      el("p", { class: "muted" }, `This copy cannot update itself: ${v.why}.`), el("p", null, where),
      updateCommand(v));
    const r = await modal(intro, [["cancel", "Close"], ["skip", "Skip this version"]], extra);
    if (r === "skip") await updateDismiss(v.latest);
    return;
  }
  const onQuit = v.on_quit === v.latest;
  const extra = el("div", null, el("p", null, updateLink(v)),
    el("p", { class: "muted" }, "Update now stops the configurator, installs the new version and starts it again; this tab comes back by itself in about a minute."));
  const r = await modal(intro, [["cancel", "Not now"], ["skip", "Skip this version"],
    onQuit ? ["noquit", "Don't update when I quit"] : ["quit", "Update when I quit"], ["now", "Update now", true]], extra);
  if (r === "skip") await updateDismiss(v.latest);
  else if (r === "quit") await updateOnQuit(v.latest, true);
  else if (r === "noquit") await updateOnQuit(v.latest, false);
  else if (r === "now") await updateNow(v.latest);
}

async function restartDialog(v) {
  const extra = el("p", { class: "muted" },
    "Restart stops this configurator and starts the installed version; this tab comes back by itself. Nothing is downloaded or installed.");
  const r = await modal(`canworks ${v.installed} is installed, and this configurator still runs ${v.version}. Restart to use ${v.installed}.`,
    [["cancel", "Not now"], ["now", "Restart", true]], extra);
  if (r === "now") await updateNow(v.installed);
}

async function updateDismiss(version) {
  try { updateShow(await api("POST", "/api/update/dismiss", { version })); } catch (e) { banner(e.message, true); }
}

async function updateOnQuit(version, on) {
  try {
    updateShow(await api("POST", "/api/update/start", { version, when: on ? "quit" : "cancel" }));
    banner(on ? `canworks ${version} is installed when you quit the configurator or close its last tab.` : "No update when you quit.", "info");
  } catch (e) { banner(e.message, true); }
}

async function updateNow(version) {
  // The server hears of this page's unsaved changes with the next heartbeat,
  // up to a second late: the page asks itself first.
  if (unsavedWork()) {
    heartbeat();
    return updateLater("Not now: there are unsaved changes.", version);
  }
  banner("Checking for the newest release…", "info");
  let r;
  try {
    r = await api("POST", "/api/update/start", { version, when: "now" });
  } catch (e) {
    if (e.body && e.body.on_quit) await updateLater(e.message, version);
    else banner(e.message, true);
    return;
  }
  updatingPage(r.version, r.boot, r.restart, r.version !== version);
}

async function updateLater(message, version) {
  const v = await modal(`${message} Save or finish the work first, or update when you quit.`,
    [["cancel", "Cancel"], ["quit", "Update when I quit", true]]);
  if (v === "quit") await updateOnQuit(version, true);
}

// The configurator stopped to update (or to restart into the installed
// version): the page says so and waits for a configurator with another
// start id on this address, then reloads. `moved`: the release offered
// had been replaced by a newer one when Update was pressed.
function updatingPage(version, boot, restart, moved) {
  LIFE.stopped = true;  // no heartbeats, no "gone" notice, no leave-page question
  clearTimeout(LIFE.timer);
  if (typeof JOBS !== "undefined") clearTimeout(JOBS.timer);
  for (const d of document.querySelectorAll("dialog[open]")) d.close();
  document.title = "canworks configurator (updating)";
  document.body.dataset.stopped = "1";
  const text = el("p", null, restart ? "This tab comes back by itself in a few seconds."
    : "This tab comes back by itself when the new version runs, in about a minute.");
  const title = restart ? `Restarting canworks configurator in ${version}…` : `Updating canworks configurator to ${version}…`;
  document.body.append(el("main", { id: "stopped", class: "stopped", role: "status", dataset: { updating: "1" } },
    el("h1", null, title), moved ? el("p", null, `${version} is the newest release now, so this update installs it.`) : null, text));
  const t0 = Date.now();
  const poll = async () => {
    try {
      const res = await fetch("/api/update", { headers: { "X-CANopen-Token": TOKEN }, cache: "no-store" });
      if (res.ok) {
        const v = await res.json();
        if (v.boot && v.boot !== boot) { location.reload(); return; }
      }
    } catch (e) { /* not back yet */ }
    if (Date.now() - t0 > UPDATE_GIVE_UP_MS) {
      text.textContent = "The configurator did not come back on this address. If it opened in another tab, use that one; "
        + "otherwise open the canworks configurator shortcut, or run canworks-config. update.log in its settings folder says what happened.";
      return;
    }
    UPD.polling = setTimeout(poll, UPDATE_POLL_MS);
  };
  UPD.polling = setTimeout(poll, UPDATE_POLL_MS);
}

async function updateCheckNow() {
  try {
    updateShow(await api("POST", "/api/update/check"));
  } catch (e) { banner(e.message, true); return; }
  // The check runs in the background: its answer comes in a few seconds.
  for (let i = 0; i < 30 && UPD.view && UPD.view.checking; i++) {
    await new Promise((r) => setTimeout(r, 500));
    await updateLoad();
  }
}

// The result of Settings → Check now in the banner as well.
function updateCheckBanner(v) {
  if (!v || v.checking) return;
  if (v.error) banner(`The update check failed: ${v.error}.`, true);
  else if (v.newer) banner(`canworks ${v.latest} is available: the Update chip in the header has it.`, "info");
  else banner(`These PC tools (${v.version}) are the newest release.`, "done");
}

// "Update PC tools…" from elsewhere (the Devices page): check now, then the
// usual dialog; with no newer release to offer, the install command to copy.
async function updatePcTools(button) {
  if (button) await busy(button, "Checking…", updateCheckNow);
  else await updateCheckNow();
  const v = UPD.view;
  if (!v) return;
  if (v.newer) return updateDialog();
  if (!v.command) {
    banner(v.error ? `The update check failed: ${v.error}.` : `These PC tools (${v.version}) are the newest release.`, "info");
    return;
  }
  const extra = el("div", null, el("p", { class: "muted" },
    `No newer release than ${v.version} was found. Run this to install the newest one again:`), updateCommand(v));
  await modal("Update the PC tools", [["cancel", "Close"]], extra);
}

function updateCommand(v) {
  const cmd = el("textarea", { readonly: true, rows: 3, "aria-label": "Install command", spellcheck: "false" }, v.command);
  const copy = el("button", { type: "button", onclick: async () => {
    cmd.select();
    try { await navigator.clipboard.writeText(v.command); copy.textContent = "Copied"; } catch (e) { document.execCommand("copy"); }
  } }, "Copy");
  return el("div", { class: "update-command" }, cmd, copy);
}

function wireUpdate() {
  $("#update-chip").onclick = () => updateDialog();
  $("#update-check").onchange = async (e) => {
    try {
      await api("POST", "/api/ui", { update_check: e.target.checked ? "on" : "off" });
      await updateLoad();
    } catch (err) { banner(err.message, true); }
  };
  // Not a menu item: the menu stays open, so "Checking…" and the result show there (UI-6), and in the banner.
  $("#update-check-now").onclick = () => busy($("#update-check-now"), "Checking…", async () => {
    await updateCheckNow();
    updateCheckBanner(UPD.view);
  });
  updateLoad();
  // The check at start runs in the background: look again once it has had time.
  setTimeout(updateLoad, 8000);
}

wireUpdate();
