"use strict";
// The Devices workspace (device-install; docs/devices.md): this PC's Linux
// devices, what each has against what the open project needs (or, with no
// config, what the user picks it to run), one main action, and install jobs
// that run on the device by themselves. SSH, the
// probe and the jobs are the server's (/api/devices/*); this page asks the
// questions (host key, password, sudo password) and never keeps an answer.
// Loaded after app.js and uses its helpers (el, api, modal, busy, notice,
// banner, S, ...).

const DEV = {
  ctx: undefined,     // the open config's folder the list was read for; null with no config
  list: null,         // /api/devices: { devices, target, instance, pc_version, jobs }
  sel: null,          // the selected device's id
  probes: {},         // device id -> the last probe answer of this page ({ probe, plan, latest })
  errors: {},         // device id -> the last connection error
  unreached: {},      // device id -> true when the last error was "can't reach"
  jobs: {},           // device id -> the job this page follows
  found: null,        // devices runtime discovery found, not in the list
  keyOffered: {},     // device ids offered key login in this session
  loading: false,
};
const DEV_POLL_MS = 1500;
const DEV_PART_ICON = { ok: "operational", warn: "warning", off: "unknown" };
const DEV_ACTION_DONE = {
  install_bridge: "The bridge runs this project's saved config.",
  install_bridge_only: "The bridge is installed. It starts with a config when that config's Devices page installs it here.",
  bridge_config: "The bridge runs this project's saved config.",
  uninstall_bridge: "The Modbus bridge was uninstalled.",
  remove_all: "canworks was removed from the device.",
  link_on: "The remote link is on. PCs pair with it as before, by logging in to the runtime on the local network.",
  link_off: "The remote link is off. Its key and paired PCs stay on the device for when it is turned on again.",
  link_start: "The remote link was started.",
  discovery_on: "The device is advertised on the local network again.",
  discovery_off: "The device is no longer advertised on the local network; typing its address still works.",
  adapter_on: "The remote CAN adapter is on. This PC keeps its token: Connect from this PC connects in one click.",
  adapter_change: "The remote CAN adapter runs with the new settings and the same token.",
  adapter_token: "The remote CAN adapter has a new token, kept on this PC. Other PCs must enter it again (Copy token).",
  adapter_off: "The remote CAN adapter is off; the interface is free on the device again.",
};
const DEV_ACTION_NAME = {
  install_bridge: "Install the bridge",
  bridge_config: "Start this project's bridge", uninstall_bridge: "Uninstall the bridge",
  remove_all: "Remove everything", link_on: "Turn on the remote link", link_off: "Turn off the remote link",
  link_start: "Start the remote link", discovery_on: "Advertise on the local network",
  discovery_off: "Stop advertising on the local network", adapter_on: "Turn on the remote CAN adapter",
  adapter_change: "Change the remote CAN adapter", adapter_token: "New token for the remote CAN adapter",
  adapter_off: "Turn off the remote CAN adapter",
};
const DEV_BITRATES = [10, 20, 50, 100, 125, 250, 500, 800, 1000];

// The host key file's name part of an SSH key type (ssh-ed25519 -> ed25519).
function devKeyFile(type) {
  if (/^ecdsa/.test(type || "")) return "ecdsa";
  return (type || "ssh-ed25519").replace(/^ssh-/, "");
}

// Another config (or none): the plans were for another target, the list is read again.
function devContext(key) {
  if (DEV.ctx === key) return;
  DEV.ctx = key;
  DEV.list = null;
  DEV.probes = {};
  DEV.sel = null;
  DEV.found = null;
}

// The main action or a part's own Install (no config) that starts `action`.
function devActionOf(id, plan, action) {
  const main = plan ? plan.main : null;
  if (main && main.action === action) return main;
  return ((plan && plan.rows) || []).flatMap((r) => r.actions || []).find((m) => m.action === action) || null;
}

// The start page's Install on a device: Devices with no config open.
function devicesOnlyStart() {
  banner("");
  S.devicesOnly = true;
  S.view = "devices";
  devContext(null);
  render();
}

function devicesOnlyClose() {
  S.devicesOnly = false;
  S.view = "bus";
  render();
  const to = $("#start-devices");
  if (to && !to.closest("[hidden]")) to.focus();
}

function renderDevicesOnly() {
  if (typeof CONN !== "undefined") { CONN.key = null; connStop(); }
  document.body.classList.add("devices-only");
  for (const id of ["#tool-tabs", "#conn-bar", "#bottom", "#ws", "#sim-banner"]) $(id).hidden = true;
  $("#start").hidden = true;
  $("#editor").hidden = false;
  $("#editor").classList.remove("commission");
  $("#editor").classList.add("tool-view");
  $("#actions").hidden = false;
  fitHeaderMore();
  const badge = $("#mode");
  badge.hidden = false;
  badge.title = "";
  badge.replaceChildren(el("span", { class: "mode-name" }, "Devices · no config"));
  const view = $("#view");
  view.replaceChildren();
  view.classList.remove("wide-cols");
  renderDevices(view);
}

function devItem(id) { return ((DEV.list && DEV.list.devices) || []).find((d) => d.id === id) || null; }
function devLabel(d) { return d ? (d.user ? `${d.user}@${d.id}` : d.id) : ""; }

// Seconds as "4 min 05 s" or "35 s".
function devDuration(s) {
  s = Math.max(0, Math.round(s));
  if (s < 60) return `${s} s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m} min ${String(s % 60).padStart(2, "0")} s`;
  return `${Math.floor(m / 60)} h ${String(m % 60).padStart(2, "0")} min`;
}

function devWhen(epoch) {
  if (!epoch) return "never";
  const d = new Date(epoch * 1000);
  const today = new Date().toDateString() === d.toDateString();
  return today ? d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : d.toLocaleString([], { dateStyle: "short", timeStyle: "short" });
}

async function devLoad() {
  try { DEV.list = await api("GET", "/api/devices"); }
  catch (e) { DEV.list = { devices: [], error: e.message }; }
  for (const d of DEV.list.devices || []) if (d.plan && !DEV.probes[d.id]) DEV.probes[d.id] = { plan: d.plan, latest: d.latest, at: d.probe_at };
  if (DEV.sel && !devItem(DEV.sel)) DEV.sel = null;
}

// A request to a device. Answers the server's questions in dialogs (a new
// host key, a changed one, the SSH password) and sends the request again;
// null when the user cancelled.
async function devCall(path, body) {
  let extra = {};
  for (;;) {
    try { return await api("POST", path, Object.assign({}, body, extra)); }
    catch (e) {
      const b = e.body || {};
      const d = devItem(body.device);
      if (b.need === "trust") {
        const v = await modal(`${d ? d.id : "This device"} is new to this PC. Connect only if this is the device's own key ` +
          `(on the device: ssh-keygen -lf /etc/ssh/ssh_host_${devKeyFile(b.key_type)}_key.pub).`,
          [["cancel", "Cancel"], ["trust", "Trust and connect", true]],
          el("p", { class: "fingerprint", dataset: { devices: "fingerprint" } }, el("code", null, b.fingerprint || "")));
        if (v !== "trust") return null;
        extra = Object.assign({}, extra, { trust: b.fingerprint });
        continue;
      }
      if (b.need === "forget_key") {
        const v = await modal(e.message, [["cancel", "Do not connect"], ["forget", "Forget key", { danger: true }]]);
        if (v !== "forget") return null;
        await api("POST", "/api/devices/forget_key", { device: body.device });
        extra = {};
        continue;
      }
      if (b.need === "password") {
        const input = el("input", { type: "password", autocomplete: "off", "aria-label": "SSH password", dataset: { devices: "password" } });
        const v = await modal(e.message + " It is used for this connection only and is not kept.",
          [["cancel", "Cancel"], ["login", "Log in", true]], input);
        if (v !== "login") return null;
        extra = Object.assign({}, extra, { password: input.value });
        continue;
      }
      throw e;
    }
  }
}

// -- the page ---------------------------------------------------------------------

function renderDevices(view) {
  view.append(el("h2", null, "Devices"),
    el("p", { class: "muted" }, (DEV.ctx ? "Install this project's Modbus bridge on a Linux device over SSH, from the newest release. "
      : "Install the Modbus bridge, its remote link and local network discovery on a Linux device over SSH, from the newest release, or turn on its remote CAN adapter. ") +
      "Passwords are asked when needed and never kept. Devices added here are listed for every project on this PC."));
  const slot = noticeSlot({ dataset: { devices: "bars" } });
  view.append(slot);
  if (!DEV.list) {
    view.append(el("p", { class: "muted" }, "Reading the devices…"));
    devLoad().then(() => { if (S.view === "devices" || S.devicesOnly) render(); });
    return;
  }
  if (DEV.list.error) slot.append(notice("error", DEV.list.error, { live: false }));
  const layout = el("div", { class: "devices-layout" }, devListPane(), devPagePane());
  view.append(layout);
}

function devListPane() {
  const items = DEV.list.devices || [];
  const add = el("button", { type: "button", class: items.length ? null : "primary", dataset: { devices: "add" }, onclick: () => devAdd() }, "Add device…");
  const list = el("ul", { class: "devices-list", role: "listbox", "aria-label": "Devices" }, items.map((d) => {
    const p = DEV.probes[d.id];
    const job = DEV.jobs[d.id];
    const state = job && !job.done ? "busy" : DEV.errors[d.id] ? "error" : !p ? "unknown" : p.plan.main ? "warning" : "operational";
    const sub = job && !job.done ? "Install running" : DEV.errors[d.id] ? "Not reached" : !p ? "Not checked yet"
      : p.plan.main && p.plan.main.hint ? "Nothing installed yet" : p.plan.main ? p.plan.main.label : DEV.list.target === "codesys" ? "Nothing to install" : "Up to date";
    // With a config open, the other projects' devices are listed after its own, muted.
    const other = DEV.ctx && !d.mine;
    const cls = [d.id === DEV.sel ? "active" : null, other ? "devices-other" : null].filter(Boolean).join(" ") || null;
    return el("li", { role: "option", tabindex: "0", "aria-selected": String(d.id === DEV.sel), class: cls,
      dataset: { device: d.id, mine: d.mine ? "1" : null }, onclick: () => devSelect(d.id),
      onkeydown: (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); devSelect(d.id); } } },
    Icons.stateIcon(state === "busy" ? "busy" : state, { label: false, spinning: state === "busy" }),
    el("span", { class: "devices-name" }, devLabel(d)), el("span", { class: "muted" }, sub),
    d.summary ? el("span", { class: "muted devices-summary", dataset: { devices: "summary" } }, d.summary) : null);
  }));
  const pane = el("section", { class: "devices-pane", "aria-label": "Device list" }, el("div", { class: "toolbar" }, add),
    items.length ? list : el("p", { class: "muted", dataset: { devices: "empty" } }, "No devices yet. Add the device by its host name or address."));
  pane.append(devFound());
  return pane;
}

// Runtimes discovery finds on the local network, not in the list yet.
function devFound() {
  const box = el("div", { class: "devices-found", dataset: { devices: "found" } });
  if (DEV.found === null) {
    DEV.found = [];
    api("GET", "/api/devices/discovered").then((r) => {
      DEV.found = r.discovered || [];
      if (S.view === "devices" && DEV.found.length) render();
    }).catch(() => {});
    return box;
  }
  if (!DEV.found.length) return box;
  box.append(el("h3", { class: "side-caption" }, "Found on this network"),
    el("ul", { class: "folders" }, DEV.found.map((f) => el("li", null,
      el("span", null, f.name || f.host, f.name ? el("span", { class: "muted" }, ` ${f.host}`) : null), " ",
      el("button", { type: "button", class: "small", dataset: { devicesAddFound: f.host }, onclick: () => devAdd(f.host) }, "Add")))));
  return box;
}

function devPagePane() {
  const pane = el("section", { class: "devices-page", "aria-label": "Device", dataset: { devices: "page" } });
  const d = devItem(DEV.sel);
  if (!d) {
    pane.append(el("p", { class: "muted" }, (DEV.list.devices || []).length
      ? (DEV.ctx ? "Pick a device to see what it has and what this project needs." : "Pick a device to see what it has.")
      : "A device is a Linux computer this PC reaches over SSH."));
    return pane;
  }
  const p = DEV.probes[d.id];
  const job = DEV.jobs[d.id];
  const check = el("button", { type: "button", dataset: { devices: "check" }, disabled: job && !job.done ? "An install is running." : null,
    onclick: (e) => busy(e.currentTarget, "Checking…", () => devProbe(d.id, true)) }, "Check again");
  const menu = el("details", { class: "menu", dataset: { devices: "menu" } }, el("summary", { "aria-haspopup": "menu" }, "Actions"),
    el("div", { role: "menu", "aria-label": "Actions" },
      el("button", { type: "button", class: "item", role: "menuitem", dataset: { devices: "remove-all" },
        disabled: !p || (job && !job.done) ? "Check the device first." : null, onclick: () => devStart(d.id, "remove_all") }, "Remove everything…"),
      el("button", { type: "button", class: "item", role: "menuitem", dataset: { devices: "remove" }, onclick: () => devRemove(d.id) }, "Remove device")));
  pane.append(el("div", { class: "devices-head" }, el("h3", null, devLabel(d)), el("span", { class: "spacer" }), check, menu));
  const head = [p && p.plan.header, p ? `checked ${devWhen(p.at)}` : null].filter(Boolean).join(" · ");
  if (head) pane.append(el("p", { class: "muted", dataset: { devices: "header" } }, head));
  const slot = noticeSlot({ dataset: { devices: "device-bars" } });
  pane.append(slot);
  if (DEV.errors[d.id]) {
    // Not reached: one sentence and what to check, without the socket's text.
    const text = !DEV.unreached[d.id] ? DEV.errors[d.id] : el("div", { dataset: { devices: "unreached" } }, DEV.errors[d.id],
      el("ul", { class: "checklist" }, el("li", null, "SSH is on in the device."),
        el("li", null, "This PC and the device are on the same network."),
        el("li", null, "The host name or address is right; try the address if the name is not found."),
        el("li", null, `The SSH port is right (${d.port || 22}).`)));
    slot.append(notice("error", text, { live: false }));
  }
  if (!p) {
    pane.append(el("p", { class: "muted" }, DEV.errors[d.id] ? "Check the device again once it is reachable." : "Checking the device…"));
    return pane;
  }
  const plan = p.plan;
  for (const n of plan.notes || []) slot.append(notice("info", n, { live: false }));
  if (plan.pc_older) {
    const o = plan.pc_older;
    slot.append(notice("info", `canworks on this device (${o.device}) is newer than these PC tools (${o.pc}). `
      + "Update the PC tools so they know everything the device can do.", { live: false, dataset: { devices: "pc-older" },
      actions: [el("button", { type: "button", dataset: { devices: "update-pc" },
        onclick: (e) => updatePcTools(e.currentTarget) }, "Update PC tools…")] }));
  }
  pane.append(devRows(d, plan, job));
  if (job) pane.append(devJobView(d, job));
  if (!job || job.done) pane.append(devMain(d, plan));
  return pane;
}

function devRows(d, plan, job) {
  const running = job && !job.done;
  // With no config there is no project to need anything: no column for it.
  const project = !!DEV.ctx;
  return el("table", { class: "devices-rows", dataset: { devices: "rows" } },
    el("thead", null, el("tr", null, thCells(project ? ["Part", "On the device", "This project", ""] : ["Part", "On the device", ""]))),
    el("tbody", null, plan.rows.map((r) => el("tr", { class: r.used ? null : "muted-row", dataset: { part: r.part } },
      el("td", null, Icons.stateIcon(DEV_PART_ICON[r.state] || "unknown", { label: false }), " ", r.label),
      el("td", null, r.have, r.hint ? el("div", { class: "muted", dataset: { devices: "hint" } }, r.hint) : null),
      project ? el("td", null, r.needs) : null,
      el("td", null, r.uninstall ? el("button", { type: "button", class: "small", dataset: { devicesUninstall: r.part },
        disabled: running ? "An install is running." : null,
        onclick: () => devStart(d.id, "uninstall_bridge") }, "Uninstall…")
        : (r.actions || []).map((a) => el("button", { type: "button", class: "small",
          dataset: Object.assign({ devicesAction: a.action }, a.action.startsWith("install") ? { devicesInstall: r.part } : {},
            a.adapter ? { devicesAdapter: a.adapter } : {}),
          // Connect and Copy token run on this PC: neither a job nor a blocked device stops them.
          disabled: a.local ? null : running || plan.blocked ? (plan.blocked || "An install is running.") : null,
          title: a.local ? null : plan.blocked || null,
          onclick: (e) => a.action === "adapter_connect" ? devAdapterConnect(d, a.port)
            : a.action === "adapter_copy_token" ? busy(e.currentTarget, "Copying…", () => devAdapterCopyToken(d, a.port))
              : devStart(d.id, a.action, a) }, a.button)))))));
}

function devMain(d, plan) {
  const box = el("div", { class: "devices-main", dataset: { devices: "main" } });
  const m = plan.main;
  if (!m) {
    if (plan.up_to_date) box.append(notice("done", "Up to date.", { live: false, dataset: { devices: "up-to-date" } }));
    return box;
  }
  const go = el("button", { type: "button", class: "primary", dataset: { devices: "start", action: m.action }, disabled: plan.blocked || null,
    onclick: () => devStart(d.id, m.action) }, m.label);
  box.append(el("div", { class: "toolbar" }, go, plan.blocked ? el("span", { class: "field-msg warning", dataset: { devices: "blocked" } }, plan.blocked) : null));
  if (m.hint) box.append(el("p", { class: "muted", dataset: { devices: "main-hint" } }, m.hint));
  // The options, folded: the remote link and discovery are on unless switched off.
  // A bridge installed with no config has no instance to link or announce: no options.
  if (m.action !== "bridge_config" && !(m.action === "install_bridge" && !DEV.list.instance)) {
    const o = DEV.options || (DEV.options = { link: true, discovery: true });
    const box2 = el("details", { class: "devices-options", dataset: { devices: "options" } }, el("summary", null, "Options"));
    const opt = (key, label, help) => {
      const c = el("input", { type: "checkbox", dataset: { devicesOption: key } });
      c.checked = o[key] !== false;
      c.onchange = () => { o[key] = c.checked; };
      return el("div", { class: "check-field" }, el("label", { class: "check" }, c, " ", label), hint(help));
    };
    if (m.link_kept) {
      // The device's link serves another config: the bridge install leaves it.
      box2.append(el("div", { class: "check-field" }, el("label", { class: "check" },
        el("input", { type: "checkbox", disabled: true, dataset: { devicesOption: "link" } }), " Remote link"),
        hint("The device's remote link serves another config and stays as it is.")));
    } else {
      box2.append(opt("link", "Remote link", "canworks-link: reach this device from a PC on another network (docs/remote-access.md)."));
    }
    box2.append(opt("discovery", "Found on the local network", "The device announces itself, so the connect panel lists it."));
    box.append(box2);
  }
  return box;
}

// -- adding, selecting, probing ---------------------------------------------------

async function devAdd(host) {
  const h = el("input", { type: "text", spellcheck: "false", autocomplete: "off", placeholder: "line3.local or 192.168.1.20", dataset: { devices: "host" } });
  const u = el("input", { type: "text", spellcheck: "false", autocomplete: "off", placeholder: "from ~/.ssh/config, or this PC's user", dataset: { devices: "user" } });
  const p = el("input", { type: "text", inputmode: "numeric", placeholder: "22", dataset: { devices: "port" } });
  if (host) h.value = host;
  const err = msgBar({ devices: "add-error" });
  // A refused field says so under itself; anything else in the bar.
  const msgs = { host: el("span", { class: "field-msg", dataset: { devicesMsg: "host" } }),
    user: el("span", { class: "field-msg", dataset: { devicesMsg: "user" } }),
    port: el("span", { class: "field-msg", dataset: { devicesMsg: "port" } }) };
  const inputs = { host: h, user: u, port: p };
  const form = el("div", { class: "grid" }, err,
    el("label", null, "Host", h, msgs.host), el("label", null, "SSH user", u, msgs.user), el("label", null, "SSH port", p, msgs.port));
  for (;;) {
    const v = await modal("Add a device: a Linux computer this PC reaches over SSH.", [["cancel", "Cancel"], ["add", "Add", true]], form);
    if (v !== "add") return;
    try {
      const r = await api("POST", "/api/devices/add", { host: h.value.trim(), user: u.value.trim(), port: p.value.trim() || undefined });
      DEV.sel = r.device;
      DEV.found = null;
      await devLoad();
      render();
      devProbe(r.device);
      return;
    } catch (e) {
      const f = e.body && e.body.field;
      err.say(f && msgs[f] ? "" : e.message);
      for (const [k, m] of Object.entries(msgs)) {
        m.textContent = k === f ? e.message : "";
        inputs[k].setAttribute("aria-invalid", String(k === f));
      }
      if (f && inputs[f]) setTimeout(() => inputs[f].focus(), 0);
    }
  }
}

function devSelect(id) {
  DEV.sel = id;
  render();
  // Opening a device reads it again: its state, and a job that runs there.
  if (!DEV.jobs[id] || DEV.jobs[id].done) devProbe(id);
}

async function devProbe(id, refresh) {
  delete DEV.errors[id];
  delete DEV.unreached[id];
  let r;
  try { r = await devCall("/api/devices/probe", { device: id, refresh: !!refresh }); }
  catch (e) { DEV.errors[id] = e.message; DEV.unreached[id] = !!(e.body && e.body.unreachable); if (S.view === "devices") render(); return; }
  if (!r) { DEV.errors[id] = "Not connected."; if (S.view === "devices") render(); return; }
  DEV.probes[id] = { plan: r.plan, latest: r.latest, at: Date.now() / 1000 };
  const job = r.probe.install_job;
  // A job running there (started by this PC before a restart, or by another PC), or this PC's last job
  // that ended while nobody watched: followed from its start.
  const d = devItem(id);
  const mine = d && d.job && job && d.job.id === job.id ? d.job : null;
  if (job && (job.state === "active" || job.state === "activating" || (mine && !mine.done)) && (!DEV.jobs[id] || DEV.jobs[id].id !== job.id)) {
    devFollowStart(id, job.id, mine ? mine.action : null);
  }
  await devLoad();
  if (S.view === "devices") render();
  if (r.offer_key_login && !DEV.keyOffered[id]) {
    DEV.keyOffered[id] = true;
    devOfferKeyLogin(id);
  }
}

async function devOfferKeyLogin(id) {
  const d = devItem(id);
  const v = await modal(`Use key login for ${devLabel(d)} from now on? This PC adds its own canworks key to ~/.ssh/authorized_keys on the device ` +
    "and then logs in without a password.", [["cancel", "Not now"], ["key", "Use key login from now on", true]]);
  if (v !== "key") return;
  try { if (await devCall("/api/devices/key_login", { device: id })) banner(`Key login set up for ${devLabel(d)}.`); }
  catch (e) { banner(e.message, true); }
}

async function devRemove(id) {
  const d = devItem(id);
  const v = await modal(`Remove ${devLabel(d)} from this PC's devices? It goes from every project's list; nothing changes on the device.`,
    [["cancel", "Cancel"], ["remove", "Remove device", { danger: true }]]);
  if (v !== "remove") return;
  try { await api("POST", "/api/devices/remove", { device: id }); } catch (e) { banner(e.message, true); return; }
  delete DEV.probes[id]; delete DEV.jobs[id]; delete DEV.errors[id];
  DEV.sel = null;
  DEV.found = null;
  await devLoad();
  render();
}

// -- starting a job ------------------------------------------------------------------

// What the confirmation says: the plan's sentences for the main action,
// one sentence for an uninstall.
function devConfirmText(d, action) {
  const p = DEV.probes[d.id];
  const plan = p && p.plan;
  const main = devActionOf(d.id, plan, action);
  if (main) return main.confirm || [];
  if (action === "uninstall_bridge") return ["The bridges on this device stop and the bridge is removed; their configs stay in /etc/canworks-bridge."];
  if (action === "remove_all") return ["The bridge, its configs, the remote link, the remote CAN adapter and their settings are removed from the device. Nothing else on it changes."];
  return [];
}

async function devStart(id, action, act) {
  const d = devItem(id);
  const plan = (DEV.probes[id] || {}).plan || {};
  const main = act || devActionOf(id, plan, action);
  const effects = act ? act.confirm || [] : devConfirmText(d, action);
  const sudo = plan.sudo === "password";
  // The remote CAN adapter's settings, in the same dialog as the sudo password.
  const form = main && main.dialog ? devAdapterForm(main) : null;
  const title = main ? main.label : DEV_ACTION_NAME[action];
  // Several bridge configs and nothing saying which: the link serves the picked one.
  const choose = main && main.choose;
  const pickField = choose ? el("select", { dataset: { devices: "link-instance" }, "aria-label": "Bridge config the link serves" },
    choose.map((n) => el("option", { value: n }, n))) : null;
  let pw = null;
  let wrong = false;
  for (;;) {
    if (effects.length || sudo || choose || form) {
      const field = sudo ? el("input", { type: "password", autocomplete: "off", dataset: { devices: "sudo" }, "aria-label": `sudo password of ${d.user || "the SSH user"}` }) : null;
      const err = msgBar({ devices: "sudo-error" }, wrong ? "sudo on the device did not accept the password." : "");
      const extra = el("div", null, err, form ? form.el : null, effects.map((t) => el("p", { dataset: { devices: "effect" } }, t)),
        choose ? el("label", null, "The bridge config the link serves", pickField) : null,
        sudo ? el("label", null, `sudo password of ${d.user || "the SSH user"} on the device`, field,
          hint("Used to start this job only; not kept.")) : null);
      const danger = action.startsWith("uninstall") || action === "remove_all" || action === "adapter_off";
      const v = await modal(`${title} on ${d.id}?`, [["cancel", "Cancel"], ["go", danger ? DEV_ACTION_NAME[action].replace("…", "") : "Start", danger ? { danger: true } : true]], extra);
      if (v !== "go") return;
      pw = field ? field.value : null;
      if (form && form.error()) { wrong = false; continue; }
    }
    try {
      const options = Object.assign({}, DEV.options || {}, pickField ? { link_instance: pickField.value } : {},
        main && main.adapter ? { adapter: main.adapter, port: main.port } : {}, form ? form.values() : {});
      const r = await devCall("/api/devices/start", { device: id, action, options, sudo_password: pw || undefined });
      if (!r) return;
      devFollowStart(id, r.job, action, options.adapter ? { adapter: options.adapter, port: options.port } : null);
      render();
      return;
    } catch (e) {
      const b = e.body || {};
      if (b.need === "sudo" && sudo) { wrong = true; continue; }
      if (b.unsaved) {
        banner("Save the config first: the bridge starts with the saved config.", "warning");
        return;
      }
      if (b.config_errors) {
        handoffRefused(null, b.config_errors);
        return;
      }
      banner(e.message, true);
      return;
    }
  }
}

// -- following a job -------------------------------------------------------------------

function devFollowStart(id, jobId, action, served) {
  const old = DEV.jobs[id];
  if (old && old.timer) clearTimeout(old.timer);
  DEV.jobs[id] = { id: jobId, action, served: served || null, offset: 0, steps: [], lines: [], exit: null, state: "active", done: false, started: null, failure: null };
  if (typeof jobsKick === "function") jobsKick();
  devFollow(id);
}

async function devFollow(id) {
  const j = DEV.jobs[id];
  if (!j || j.done) return;
  j.timer = null;
  try {
    const r = await api("POST", "/api/devices/job", { device: id, job: j.id, offset: j.offset });
    j.error = null;
    if (r.found) {
      j.offset = r.offset;
      if (r.started) j.started = r.started;
      for (const s of r.steps || []) j.steps.push(s);
      for (const l of r.lines || []) j.lines.push(l);
      if (j.lines.length > 2000) j.lines.splice(0, j.lines.length - 2000);
      if (r.exit !== null && r.exit !== undefined) j.exit = r.exit;
      j.state = r.state;
      if (r.failure) j.failure = r.failure;
      if (r.done) {
        j.done = true;
        j.ended = Date.now() / 1000;
        devJobEnded(id, j);
      }
    }
  } catch (e) {
    // The connection dropped (the PC slept): the job goes on there; this page tries again.
    j.error = e.status === 409 ? "Not connected: check the device again to follow the job." : e.message;
    if (e.status === 409) { if (S.view === "devices") devRedrawJob(id); return; }
  }
  if (S.view === "devices") devRedrawJob(id);
  if (!j.done) j.timer = setTimeout(() => devFollow(id), document.hidden ? DEV_POLL_MS * 4 : DEV_POLL_MS);
}

async function devJobEnded(id, j) {
  if (typeof jobsKick === "function") jobsKick();
  // A finished job may have made the device the project's runtime host (Online access).
  if (j.exit === 0 && S.state && S.state.mode) await loadOnlineSettings();
  await devProbe(id);
}

// Redraws the job box only (the log keeps its scroll and fold).
function devRedrawJob(id) {
  if (id !== DEV.sel) { const li = document.querySelector(`.devices-list [data-device="${CSS.escape(id)}"]`); if (li) render(); return; }
  const old = document.querySelector("[data-devices=job]");
  const d = devItem(id);
  if (!old || !d) { render(); return; }
  const j = DEV.jobs[id];
  if (j.done) { render(); return; }
  old.replaceWith(devJobView(d, j));
}

function devJobView(d, j) {
  const now = Date.now() / 1000;
  const start = j.started || (j.steps[0] && j.steps[0].at) || null;
  const end = j.done ? (j.ended || now) : now;
  const typical = d.job_seconds && j.action && d.job_seconds[j.action];
  const failed = j.done && j.exit !== 0;
  const box = el("section", { class: "devices-job", dataset: { devices: "job", job: j.id }, "aria-label": "Install job" });
  const title = DEV_ACTION_NAME[j.action] || "Install job";
  const time = start ? (j.done ? `took ${devDuration(end - start)}` : `running for ${devDuration(end - start)}`) : "";
  const stop = !j.done ? el("button", { type: "button", dataset: { devices: "stop" }, onclick: (e) => devStop(d.id, e.currentTarget) }, "Stop") : null;
  box.append(el("div", { class: "devices-head" }, el("h3", null, title), el("span", { class: "muted", dataset: { devices: "elapsed" } },
    [time, !j.done && typical ? `typically about ${devDuration(typical)}` : null].filter(Boolean).join(" · ")), el("span", { class: "spacer" }), stop));
  if (j.error) box.append(notice("warning", j.error, { live: false }));
  const steps = j.steps;
  const total = steps.length ? steps[steps.length - 1].of : null;
  box.append(el("ol", { class: "devices-steps", dataset: { devices: "steps" } }, steps.map((s, i) => {
    const next = steps[i + 1];
    const current = !next && !j.done;
    const took = s.at && (next ? next.at : j.done ? end : now);
    const icon = current ? Icons.stateIcon("busy", { label: false, spinning: true })
      : !next && failed ? Icons.stateIcon("error", { label: false }) : Icons.stateIcon("operational", { label: false });
    return el("li", { dataset: { step: s.n }, "aria-current": current ? "step" : null }, icon, " ", s.text,
      took ? el("span", { class: "muted" }, ` ${devDuration(took - s.at)}`) : null);
  }), !steps.length && !j.done ? el("li", null, Icons.stateIcon("busy", { label: false, spinning: true }), " Starting…") : null));
  if (total && !j.done) box.append(el("p", { class: "muted" }, `Step ${steps[steps.length - 1].n} of ${total}`));
  if (j.done) {
    if (!failed && j.exit === 0) {
      let text = DEV_ACTION_DONE[j.action] || "The job ended.";
      const projectBridge = ["install_bridge", "bridge_config"].includes(j.action) && DEV.list.instance;
      if (projectBridge) text = `The bridge runs this project's saved config as ${DEV.list.instance}.`;
      else if (j.action === "install_bridge") text = DEV_ACTION_DONE.install_bridge_only;
      const open = projectBridge
        ? el("button", { type: "button", dataset: { devices: "open-commission" }, onclick: () => switchWorkspace("commission") }, "Open in Commission")
        : j.served && ["adapter_on", "adapter_change", "adapter_token"].includes(j.action)
          ? el("button", { type: "button", dataset: { devices: "adapter-connect" }, onclick: () => devAdapterConnect(d, j.served.port) }, "Connect from this PC") : null;
      box.append(notice("done", text, { live: true, actions: [open], dataset: { devices: "done" } }));
    } else {
      const stopped = j.exit === null;
      const f = j.failure || {};
      box.append(notice("error", [stopped ? "The job was stopped." : `The job failed with exit status ${j.exit}.`,
        f.hint ? " " + f.hint : ""], { live: true, dataset: { devices: "failed" } }));
      if (f.tail && f.tail.length) box.append(el("pre", { class: "devices-tail", dataset: { devices: "tail" } }, f.tail.join("\n")));
    }
  }
  const log = el("details", { class: "devices-log", dataset: { devices: "log" } }, el("summary", null, `Log (${j.lines.length} lines)`),
    el("pre", { tabindex: "0", "aria-label": "Job log" }, j.lines.slice(-500).join("\n")));
  const was = document.querySelector("[data-devices=log]");
  if (was && was.open) log.open = true;
  box.append(log);
  if (log.open) setTimeout(() => { const pre = log.querySelector("pre"); if (pre) pre.scrollTop = pre.scrollHeight; }, 0);
  return box;
}

async function devStop(id, button) {
  const d = devItem(id);
  const j = DEV.jobs[id];
  const plan = (DEV.probes[id] || {}).plan || {};
  const sudo = plan.sudo === "password";
  const field = sudo ? el("input", { type: "password", autocomplete: "off", dataset: { devices: "sudo" }, "aria-label": "sudo password" }) : null;
  const v = await modal(`Stop the install on ${d.id}? What it changed so far stays; check the device and start again afterwards.`,
    [["cancel", "Keep it running"], ["stop", "Stop", { danger: true }]],
    sudo ? el("label", null, `sudo password of ${d.user || "the SSH user"} on the device`, field) : null);
  if (v !== "stop") return;
  await busy(button, "Stopping…", async () => {
    try { await devCall("/api/devices/stop", { device: id, job: j.id, sudo_password: field ? field.value : undefined }); }
    catch (e) { banner(e.message, true); }
  });
}

// -- the remote CAN adapter (add-devices-adapter-server) -----------------------------------

// The Turn on… / Change… fields: interface, bit rate (never guessed),
// Allow changes from PCs and Advertise. values() is the job's options;
// error() says what is missing under the field and is true then.
function devAdapterForm(act) {
  const choices = act.choices || [];
  const cur = act.current || null;
  const pick = el("select", { dataset: { devices: "adapter-interface" }, "aria-label": "Interface", disabled: cur ? true : null },
    choices.map((c) => el("option", { value: c.adapter, disabled: c.refused ? true : null }, c.refused ? `${c.label} (in use)` : c.label)));
  const first = choices.find((c) => !c.refused);
  if (first) pick.value = first.adapter;
  const rate = el("select", { dataset: { devices: "adapter-bitrate" }, "aria-label": "Bit rate" },
    el("option", { value: "" }, "Pick the bus's bit rate"), DEV_BITRATES.map((k) => el("option", { value: String(k) }, `${k} kbit/s`)));
  const rateMsg = el("span", { class: "field-msg", dataset: { devicesMsg: "adapter-bitrate" } });
  const note = el("div", { class: "muted", dataset: { devices: "adapter-note" }, "aria-live": "polite" });
  const allow = el("input", { type: "checkbox", dataset: { devices: "adapter-allow" } });
  allow.checked = cur ? !!cur.allow_changes : true;
  const adv = el("input", { type: "checkbox", dataset: { devices: "adapter-discovery" } });
  adv.checked = cur ? !!cur.discovery : true;
  const chosen = () => choices.find((c) => c.adapter === pick.value) || null;
  const show = () => {
    const c = chosen();
    if (cur && cur.bitrate_kbit && !(c && c.locked)) rate.value = String(cur.bitrate_kbit);
    else if (c && c.bitrate_kbit) rate.value = String(c.bitrate_kbit);
    rate.disabled = !!(c && c.locked);
    note.textContent = c ? (c.refused || c.note || "") : "";
  };
  pick.addEventListener("change", show);
  show();
  // Interface and bit rate side by side, the switches under them.
  const box = el("div", { dataset: { devices: "adapter-form" } }, el("div", { class: "grid" },
    choices.length > 1 || !cur ? el("label", null, "Interface", pick) : el("p", null, `Interface: ${(choices[0] || {}).label || ""}`),
    el("label", null, "Bit rate", rate, rateMsg, hint("The bus's bit rate: the server checks it when the first PC connects and never guesses it."))),
    note,
    el("div", { class: "check-field" }, el("label", { class: "check" }, allow, " Allow changes from PCs"),
      hint("Each PC still connects read-only and allows changes for its own session, as with a USB adapter. Off: no PC can make changes.")),
    el("div", { class: "check-field" }, el("label", { class: "check" }, adv, " Advertise on the local network"),
      hint("The connect panel then lists this adapter.")));
  return {
    el: box,
    values: () => ({ adapter: cur ? act.adapter : pick.value, port: act.port, bitrate_kbit: Number(rate.value) || null,
      allow_changes: allow.checked, discovery: adv.checked }),
    error: () => {
      const c = chosen();
      const why = !cur && (!c || c.refused) ? "Pick an interface that is free." : !rate.value ? "Pick the bus's bit rate: it is never guessed." : "";
      rateMsg.textContent = why;
      rate.setAttribute("aria-invalid", String(!!why));
      return !!why;
    },
  };
}

// HOST or HOST:PORT for the connect panel (port 7536 when not given).
function devAdapterAddress(host, port) {
  const h = host.includes(":") ? `[${host}]` : host;
  return port && port !== 7536 ? `${h}:${port}` : h;
}

// Connect from this PC: the connect panel on Adapter on another machine with
// the device filled in (Commission a CANopen device with no config open).
async function devAdapterConnect(d, port) {
  if (S.devicesOnly) {
    S.devicesOnly = false;
    document.body.classList.remove("devices-only");
    await commissionDevice();
  } else if (!(S.state && S.state.commission) && workspace() !== "commission") {
    switchWorkspace("commission");
  }
  if (!(await saveOnline({ remote_adapter: true, remote_host: devAdapterAddress(d.host, port) }))) return;
  CONN.target = "remote";
  openConnect();
}

async function devAdapterCopyToken(d, port) {
  let r;
  try { r = await devCall("/api/devices/adapter_token", { device: d.id, port }); }
  catch (e) { banner(e.message, true); return; }
  if (!r) return;
  try { await navigator.clipboard.writeText(r.token); banner("Copied the remote CAN adapter's token. Give it only to people who may use the bus."); }
  catch (e) { await modal("The remote CAN adapter's token:", [["ok", "Close", true]], el("code", { dataset: { devices: "adapter-token" } }, r.token)); }
}

// -- entry points ------------------------------------------------------------------------

// Opens the Devices workspace, on a device when one is named (the status bar's Show).
function openDevices(id) {
  if (id) DEV.sel = id;
  if (workspace() !== "devices") switchWorkspace("devices");
  else render();
  if (id && (!DEV.jobs[id] || DEV.jobs[id].done)) devProbe(id);
}

// "Install canworks on a device…" and "Install on device…": the Devices
// workspace with the device of `host` picked, added when it is not listed.
async function installOnDevice(host) {
  await devLoad();
  const known = host && (DEV.list.devices || []).find((d) => d.host === host);
  if (known) { openDevices(known.id); return; }
  openDevices(null);
  devAdd(host || undefined);
}

// HOST of a runtime host field's HOST or HOST:PORT ([v6]:PORT).
function devHostOnly(text) {
  const t = (text || "").trim();
  const m = /^\[(.*)\](?::\d+)?$/.exec(t) || /^([^:]*):\d+$/.exec(t);
  return m ? m[1] : t;
}

// Online access: the runtime host as a device of this project, with the way
// to the Devices workspace.
function devHostState() {
  const host = devHostOnly(S.online && S.online.host);
  if (!host || host === "local") return null;
  if (!DEV.list) {
    devLoad().then(() => { if (S.view === "project") render(); });
    return null;
  }
  const d = DEV.list && (DEV.list.devices || []).find((x) => x.host === host);
  const p = d && DEV.probes[d.id];
  const text = !d ? `${host} is not in Devices yet.` : !p ? `${host} is in Devices, not checked yet.`
    : p.plan.main ? `${host}: ${p.plan.main.label}.` : `${host}: up to date.`;
  return el("div", { class: "toolbar", dataset: { devices: "host-state" } }, el("span", { class: "muted" }, text),
    el("button", { type: "button", class: "small", dataset: { devices: "open-host" }, onclick: () => installOnDevice(host) },
      d ? "Open in Devices" : "Install canworks on it…"));
}
