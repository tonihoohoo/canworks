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
  role: {},           // device id -> the role picked for a device with nothing of canworks (no config)
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
  install_openplc: "canworks is installed. It switches on with the next upload: the editor's Build and upload, or canworks-deploy.",
  install_plugin: "canworks is installed. It switches on with the next upload: the editor's Build and upload, or canworks-deploy.",
  install_bridge: "The bridge runs this project's saved config.",
  install_bridge_only: "The bridge is installed. It starts with a config when that config's Devices page installs it here.",
  bridge_config: "The bridge runs this project's saved config.",
  uninstall_plugin: "The canworks plugin was uninstalled.",
  uninstall_bridge: "The Modbus bridge was uninstalled.",
  remove_all: "canworks was removed from the device.",
};
const DEV_ACTION_NAME = {
  install_openplc: "Install OpenPLC Runtime and canworks", install_plugin: "Install canworks", install_bridge: "Install the bridge",
  bridge_config: "Start this project's bridge", uninstall_plugin: "Uninstall the plugin", uninstall_bridge: "Uninstall the bridge",
  remove_all: "Remove everything",
};

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

// The main action shown: the plan's, or with no config the picked role's.
function devMainOf(id, plan) {
  if (!plan) return null;
  if (!plan.roles) return plan.main;
  const pick = plan.roles.find((r) => r.role === DEV.role[id]) || plan.roles[0];
  return pick.main;
}

// The main action or a part's own Install (no config) that starts `action`.
function devActionOf(id, plan, action) {
  const main = devMainOf(id, plan);
  if (main && main.action === action) return main;
  return ((plan && plan.rows) || []).map((r) => r.install).find((m) => m && m.action === action) || null;
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
    el("p", { class: "muted" }, (DEV.ctx ? "Install canworks on a Linux device over SSH: what this project needs, from the newest release. "
      : "Install the OpenPLC Runtime, canworks or the Modbus bridge on a Linux device over SSH, from the newest release. ") +
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
      : p.plan.roles ? "Nothing installed yet" : p.plan.main ? p.plan.main.label : DEV.list.target === "codesys" ? "Nothing to install" : "Up to date";
    // With a config open, the other projects' devices are listed after its own, muted.
    const other = DEV.ctx && !d.mine;
    const cls = [d.id === DEV.sel ? "active" : null, other ? "devices-other" : null].filter(Boolean).join(" ") || null;
    return el("li", { role: "option", tabindex: "0", "aria-selected": String(d.id === DEV.sel), class: cls,
      dataset: { device: d.id, mine: d.mine ? "1" : null }, onclick: () => devSelect(d.id),
      onkeydown: (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); devSelect(d.id); } } },
    Icons.stateIcon(state === "busy" ? "busy" : state, { label: false, spinning: state === "busy" }),
    el("span", { class: "devices-name" }, devLabel(d)), el("span", { class: "muted" }, sub),
    (d.tags || []).length ? el("span", { class: "muted devices-tags", dataset: { devices: "tags" } }, d.tags.join(" · ")) : null);
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
        onclick: () => devStart(d.id, r.part === "plugin" ? "uninstall_plugin" : "uninstall_bridge") }, "Uninstall…")
        : r.install ? el("button", { type: "button", class: "small", dataset: { devicesInstall: r.part },
          disabled: running || plan.blocked ? (plan.blocked || "An install is running.") : null, title: plan.blocked || null,
          onclick: () => devStart(d.id, r.install.action) }, "Install…") : null)))));
}

function devMain(d, plan) {
  const box = el("div", { class: "devices-main", dataset: { devices: "main" } });
  if (plan.roles) {
    // Nothing of canworks on the device and no config to say what it needs: the user picks.
    const picked = (plan.roles.find((r) => r.role === DEV.role[d.id]) || plan.roles[0]).role;
    box.append(el("fieldset", { class: "devices-roles", dataset: { devices: "roles" } },
      el("legend", null, "What should this device run?"),
      plan.roles.map((r) => {
        const radio = el("input", { type: "radio", name: "devices-role", value: r.role, dataset: { devicesRole: r.role } });
        radio.checked = r.role === picked;
        radio.onchange = () => { DEV.role[d.id] = r.role; render(); const back = document.querySelector(`[data-devices-role="${r.role}"]`); if (back) back.focus(); };
        return el("label", { class: "choice" }, radio, el("strong", null, r.label), el("span", null, r.text));
      })));
  }
  const m = devMainOf(d.id, plan);
  if (!m) {
    if (plan.up_to_date) box.append(notice("done", "Up to date.", { live: false, dataset: { devices: "up-to-date" } }));
    return box;
  }
  const go = el("button", { type: "button", class: "primary", dataset: { devices: "start", action: m.action }, disabled: plan.blocked || null,
    onclick: () => devStart(d.id, m.action) }, m.label);
  box.append(el("div", { class: "toolbar" }, go, plan.blocked ? el("span", { class: "field-msg warning", dataset: { devices: "blocked" } }, plan.blocked) : null));
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
      // The device's link serves another config (the PLC's): the bridge install leaves it.
      box2.append(el("div", { class: "check-field" }, el("label", { class: "check" },
        el("input", { type: "checkbox", disabled: true, dataset: { devicesOption: "link" } }), " Remote link"),
        hint("The device's remote link serves another config (the PLC's) and stays as it is.")));
    } else {
      box2.append(opt("link", "Remote link", "canworks-link: reach this device from a PC on another network (docs/remote-access.md)."));
    }
    if (m.action !== "install_bridge") box2.append(opt("discovery", "Found on the local network", "The device announces itself, so the connect panel lists it."));
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
  if (action === "uninstall_plugin") return ["The plugin is removed and canworks stops on this device; the OpenPLC runtime and its programs stay."];
  if (action === "uninstall_bridge") return ["The bridges on this device stop and the bridge is removed; their configs stay in /etc/canworks-bridge."];
  if (action === "remove_all") return ["The canworks plugin, the bridge, the remote link and their settings are removed from the device. The OpenPLC runtime stays."];
  return [];
}

async function devStart(id, action) {
  const d = devItem(id);
  const plan = (DEV.probes[id] || {}).plan || {};
  const effects = devConfirmText(d, action);
  const sudo = plan.sudo === "password";
  const main = devActionOf(id, plan, action);
  const title = main ? main.label : DEV_ACTION_NAME[action];
  let pw = null;
  let wrong = false;
  for (;;) {
    if (effects.length || sudo) {
      const field = sudo ? el("input", { type: "password", autocomplete: "off", dataset: { devices: "sudo" }, "aria-label": `sudo password of ${d.user || "the SSH user"}` }) : null;
      const err = msgBar({ devices: "sudo-error" }, wrong ? "sudo on the device did not accept the password." : "");
      const extra = el("div", null, err, effects.map((t) => el("p", { dataset: { devices: "effect" } }, t)),
        sudo ? el("label", null, `sudo password of ${d.user || "the SSH user"} on the device`, field,
          hint("Used to start this job only; not kept.")) : null);
      const danger = action.startsWith("uninstall") || action === "remove_all";
      const v = await modal(`${title} on ${d.id}?`, [["cancel", "Cancel"], ["go", danger ? DEV_ACTION_NAME[action].replace("…", "") : "Start", danger ? { danger: true } : true]], extra);
      if (v !== "go") return;
      pw = field ? field.value : null;
    }
    try {
      const r = await devCall("/api/devices/start", { device: id, action, options: DEV.options || {}, sudo_password: pw || undefined });
      if (!r) return;
      devFollowStart(id, r.job, action);
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

function devFollowStart(id, jobId, action) {
  const old = DEV.jobs[id];
  if (old && old.timer) clearTimeout(old.timer);
  DEV.jobs[id] = { id: jobId, action, offset: 0, steps: [], lines: [], exit: null, state: "active", done: false, started: null, failure: null };
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
  if (j.exit === 0 && j.action === "install_openplc") devFirstUser(id);
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
  if (total) box.append(el("p", { class: "muted" }, `Step ${steps[steps.length - 1].n} of ${total}`));
  if (j.done) {
    if (!failed && j.exit === 0) {
      const docker = ((DEV.probes[d.id] || {}).plan || {}).rows;
      const dockerRt = docker && /Docker/.test((docker.find((r) => r.part === "runtime") || {}).have || "");
      let text = DEV_ACTION_DONE[j.action] || "The job ended.";
      if ((j.action === "install_plugin" || j.action === "install_openplc") && dockerRt) text += " Until then the PLC has no program.";
      const projectBridge = (j.action === "install_bridge" || j.action === "bridge_config") && DEV.list.instance;
      if (projectBridge) text = `The bridge runs this project's saved config as ${DEV.list.instance}.`;
      else if (j.action === "install_bridge") text = DEV_ACTION_DONE.install_bridge_only;
      const open = projectBridge
        ? el("button", { type: "button", dataset: { devices: "open-commission" }, onclick: () => switchWorkspace("commission") }, "Open in Commission") : null;
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

// After Install OpenPLC Runtime and canworks: the runtime's first user.
async function devFirstUser(id) {
  const d = devItem(id);
  const name = el("input", { type: "text", spellcheck: "false", autocomplete: "off", dataset: { devices: "runtime-user" } });
  name.value = "admin";
  const pw = el("input", { type: "password", autocomplete: "new-password", dataset: { devices: "runtime-password" } });
  const pw2 = el("input", { type: "password", autocomplete: "new-password", dataset: { devices: "runtime-password2" } });
  const err = msgBar({ devices: "runtime-user-error" });
  const form = el("div", { class: "grid" }, err, el("label", null, "User name", name),
    el("label", null, "Password", pw, hint("At least 8 characters.")), el("label", null, "Password again", pw2));
  for (;;) {
    const v = await modal(`The OpenPLC runtime on ${d.id} has no user yet. Create the first one: the editor and canworks-deploy log in with it. The password is not kept on this PC.`,
      [["cancel", "Later"], ["create", "Create user", true]], form);
    if (v !== "create") return;
    if (pw.value !== pw2.value) { err.say("The two passwords differ."); continue; }
    try {
      if (!await devCall("/api/devices/runtime_user", { device: id, user: name.value.trim(), user_password: pw.value })) return;
      banner(`The runtime on ${d.id} has the user ${name.value.trim()}.`);
      return;
    } catch (e) {
      if (/already has a user/.test(e.message)) { banner(e.message, "info"); return; }
      err.say(e.message);
    }
  }
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
