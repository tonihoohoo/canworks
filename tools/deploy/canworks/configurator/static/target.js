// Project targets (canopen-configurator "Project target", "Only what the
// target uses is shown", "Switching the target", "CODESYS settings",
// "CODESYS actions"; docs/configurator.md): OpenPLC through Modbus, the
// Modbus bridge or CODESYS; a config of the bridge can still be
// opened and switched to OpenPLC through Modbus. The server's relevance table (S.state.targets, targets.py) says
// what each target uses; the page hides the rest, and a value the target
// does not use but the config still has stays shown, marked, with Remove.
// Loaded after app.js and bridge.js and uses their helpers.
"use strict";

const TARGET_CHOICES = [
  { value: "openplc_modbus", label: "OpenPLC",
    help: "canworks-bridge runs the networks next to the OpenPLC Runtime, and OpenPLC's own Modbus master reads and writes the values on 127.0.0.1:1502. Save writes the remote device and two programs into the editor project. Locations are byte addresses, as for the Modbus bridge." },
  { value: "bridge", label: "Modbus bridge",
    help: "canworks-bridge runs the networks and serves the values as Modbus TCP registers, with no PLC. Locations are byte addresses: %IW0 is bytes 0 and 1, input register 0." },
  { value: "codesys", label: "CODESYS",
    help: "A CODESYS PLC runs the CANopen master networks: canworks builds the bus, the nodes and their named I/O channels into a CODESYS project. No PLC locations: each PDO entry's variable name names its channel." },
];
// A config of the removed OpenPLC plugin (no bridge or codesys key) opens
// read-only with the switch to OpenPLC through Modbus.
const TARGET_PLUGIN_CHOICE = { value: "plugin", label: "OpenPLC plugin (removed)",
  help: "The canworks plugin inside the OpenPLC Runtime was removed. OpenPLC through Modbus runs the same networks in canworks-bridge." };
const TARGET_TITLE = { plugin: "OpenPLC plugin", openplc_modbus: "OpenPLC", bridge: "Modbus bridge", codesys: "CODESYS" };
const TARGET_LABEL = { plugin: "the removed OpenPLC plugin", openplc_modbus: "OpenPLC through Modbus", bridge: "the Modbus bridge", codesys: "CODESYS" };
// What refuses a config with errors, per target (a save with errors says so).
const TARGET_RUNNER = { plugin: "nothing", openplc_modbus: "the bridge", bridge: "the bridge", codesys: "the CODESYS build" };

// Whether a target runs the networks in canworks-bridge (the Modbus bridge
// page, byte locations, register numbers).
function bridgeTarget(tgt) {
  tgt = tgt || projectTarget();
  return tgt === "bridge" || tgt === "openplc_modbus";
}
// The top-level `codesys` keys; the network's own are net_id and interface.
const CODESYS_TOP_KEYS = ["project", "device", "create", "variables"];

// Page texts that differ per target (canopen-configurator "Only what the
// target uses is shown"): { bridge, codesys }; OpenPLC through Modbus and a
// missing one use the bridge's (the bridge runs the networks). The texts do
// not speak of the PLC scan or PLC locations.
const TARGET_TEXT = {
  role_master: {
    bridge: "Default. The bridge is the network's master: it boots and configures the nodes listed here.",
    codesys: "Default. The CODESYS CANopen manager is the network's master: it boots and configures the nodes listed here.",
  },
  sim_network: {
    bridge: "A virtual bus inside the bridge: no CAN interface or serial device is used and nothing needs installing. Every node is a simulated device unless switched off (then it is absent). The adapter settings below are kept for switching back.",
  },
  sim_plain: {
    bridge: "A virtual bus inside the bridge: no CAN interface is used. Plain CAN devices from the simulation file (simulation.json) send and answer on it. The adapter settings below are kept for switching back.",
  },
  interface: {
    bridge: "Required. The interface on the computer that runs the bridge, not necessarily this one: can0 for the first CAN interface, vcan0 for a virtual bus.",
  },
  configure_link: {
    bridge: "Bridge sets up the link (bit rate, up)",
  },
  restart: {
    bridge: "Empty: keep the interface's own setting. 0 turns automatic restart after bus-off off. Used only when the bridge sets up the link.",
  },
  lint_communication: {
    bridge: "Default. Only lint findings in the objects 0x1000-0x1FFF that dcfgen writes keep the bridge from starting, not findings only about limits. Other findings are logged as one warning per EDS.",
  },
  lint_all: {
    bridge: "The bridge does not start on any lint finding, as dcfgen's strict check does. Many vendor EDS files fail it.",
  },
  lint_off: {
    bridge: "The bridge always starts; lint findings are logged as one warning per EDS.",
  },
  bus_off_count: {
    bridge: "Bus-off events since the bridge started. Empty: none.",
  },
  sdo_hidden: {
    bridge: "communication objects the bridge sets from the node's settings",
    codesys: "communication objects CODESYS sets from the node's settings",
  },
  raw_rx: {
    bridge: "Messages the bridge reads from the bus. Their signals go to input registers.",
  },
  raw_tx: {
    bridge: "Messages the bridge sends. Their signals come from holding registers.",
  },
  free_location: {
    bridge: "Each signal gets a free register location of the right size.",
  },
  links: {
    bridge: "the data no longer passes through the bridge. " +
      "The master configures both ends at boot and keeps receiving the TPDO, so Modbus clients can still read it.",
    codesys: "the data no longer passes through the PLC program. " +
      "The consumers' DCFs carry the link, so CODESYS configures both ends at boot.",
  },
  location_column: {
    bridge: "Location",
  },
  pdo_inputs: {
    bridge: "Inputs (TPDOs, device to Modbus registers)",
  },
  pdo_outputs: {
    bridge: "Outputs (RPDOs, Modbus registers to device)",
  },
  set_by_runtime: {
    bridge: "none: the bridge sets it",
  },
  diag_port: {
    bridge: "Off by default; the bridge opens no port without it.",
  },
  links_none: {
    bridge: "No links yet. A link copies a PDO from one node straight to another, without the bridge; add one with Add link.",
    codesys: "No links yet. A link copies a PDO from one node straight to another, without the PLC program; add one with Add link.",
  },
};

function targetText(key) {
  const t = TARGET_TEXT[key];
  const tgt = projectTarget();
  return t[tgt] || t.bridge;
}

// The target of a config (or of the draft's top-level keys).
function targetOf(cfg) {
  const obj = (v) => !!v && typeof v === "object" && !Array.isArray(v);
  if (cfg && obj(cfg.bridge)) return obj(cfg.bridge.openplc) ? "openplc_modbus" : "bridge";
  if (cfg && obj(cfg.codesys)) return "codesys";
  return "plugin";
}

function projectTarget() { return S.model ? targetOf(S.model.top) : "openplc_modbus"; }

function targetRow(key) { return ((S.state && S.state.targets) || []).find((r) => r.key === key) || null; }

// Whether the project's target (or `tgt`) uses a key of the table; a key
// the table does not list is used by every target.
function usedBy(key, tgt) {
  const r = targetRow(key);
  return !r || r.targets.includes(tgt || projectTarget());
}

// The table row of a page path ("nodes[2].tx_pdos[0].timeout_ms"), from the
// most specific key down; null when no row covers it.
function pathRow(path) {
  const p = String(path).replace(/\[\d+\]/g, "");
  if (p === "gateway" || p.startsWith("gateway.")) return targetRow("/gateway");
  const parts = p.split(".");
  for (let i = parts.length; i > 0; i--) {
    const r = targetRow(parts.slice(0, i).join("."));
    if (r) return r;
  }
  return null;
}

// Why the target does not use a path, or null when it does.
function unusedWhy(path, tgt) {
  tgt = tgt || projectTarget();
  const r = pathRow(path);
  if (!r || r.targets.includes(tgt)) return null;
  return r.reasons[tgt] || "";
}

// The page after a render: every bound field the target does not use is
// hidden, set or not (save leaves its value out); options of a choice the
// target does not use are left out; a section left with no field is hidden.
function applyTarget(root) {
  if (!root || !S.model || !S.state || !S.state.targets) return;
  const tgt = projectTarget();
  for (const x of root.querySelectorAll("input[data-path], select[data-path], textarea[data-path]")) {
    const path = x.dataset.path;
    if (x.tagName === "SELECT") pruneOptions(x, path, tgt);
    if (unusedWhy(path, tgt) === null) continue;
    const box = x.closest(".check-field") || x.closest("label") || x.closest("td") || x.parentElement;
    if (box.tagName === "TD") x.hidden = true;
    else box.hidden = true;
  }
  // A section is empty when it had settings and no control is left: a
  // control of its own (Method, Watch a node…) keeps it.
  const gone = (f) => f.hidden || !!f.closest("[hidden]");
  for (const fs of root.querySelectorAll("fieldset, details.advanced, .pdo-row")) {
    const fields = [...fs.querySelectorAll("input[data-path], select[data-path], textarea[data-path]")];
    if (fields.length && fields.every(gone) && [...fs.querySelectorAll("input, select, textarea, button")].every(gone)) fs.hidden = true;
  }
  // A node tab left with nothing says so instead of staying blank.
  const panel = root.querySelector("#node-panel");
  if (panel && panel.children.length && [...panel.children].every((c) => c.hidden)) {
    panel.append(el("p", { class: "muted", dataset: { tabEmpty: "1" } },
      `${TARGET_TITLE[tgt]} does not use the settings on this tab` + (tgt === "codesys" ? ": CODESYS supervises the node and reads its emergencies itself." : ".")));
  }
}

// The options of a choice that the target does not use ("PLC cycle" for the
// bridge, J1939 for CODESYS) are left out, except the one the config has
// (a network's kind stays, and the check says why).
function pruneOptions(sel, path, tgt) {
  const base = String(path).replace(/\[\d+\]/g, "");
  for (const o of [...sel.options]) {
    if (o.value === "") continue;
    const r = targetRow(`${base}=${o.value}`);
    if (!r || r.targets.includes(tgt)) continue;
    if (o.value !== sel.value) o.remove();
  }
  // One choice left: shown as text, not as a dropdown with nothing to pick.
  if (sel.options.length === 1 && !sel.nextElementSibling?.matches(".single-choice")) {
    sel.hidden = true;
    sel.after(el("span", { class: "single-choice", dataset: { singleFor: path } }, sel.options[0].textContent));
  }
}

// The check's warnings for values the target does not use that can go:
// not problems, since save leaves them out (canopen-configurator "Settings
// the target does not use are left out on save").
function isUnusedItem(it) { return !!(it && it.unused && it.removable); }

// -- the Project target field ---------------------------------------------------

function targetField() {
  const tgt = projectTarget();
  const plugin = tgt === "plugin";
  return el("fieldset", { dataset: { bridgeTarget: "1", projectTarget: "1" } }, el("legend", null, "Project target"),
    plugin ? notice("warning", "This config is for the OpenPLC plugin, which was removed, so it cannot be saved. Switch to OpenPLC through Modbus: canworks-bridge runs the same networks next to the OpenPLC Runtime.",
      { live: false, dataset: { pluginTarget: "1" }, actions: [el("button", { type: "button", class: "primary", dataset: { switchModbus: "1" },
        onclick: () => switchTarget("openplc_modbus") }, "Switch to OpenPLC through Modbus")] }) : null,
    el("div", { class: "grid" }, choice("Target", "", plugin ? [TARGET_PLUGIN_CHOICE].concat(TARGET_CHOICES) : TARGET_CHOICES,
      { noPath: true, dataset: { target: "1" }, current: tgt, onChange: switchTarget })),
    tgt === "openplc_modbus" ? openplcModbusFacts() : null);
}

// The Project page's facts of OpenPLC through Modbus (S.state.openplc, from
// the saved config): what Save writes into the editor project and how often
// OpenPLC polls.
function openplcModbusFacts() {
  const o = S.state && S.state.openplc;
  if (!o) return el("p", { class: "muted", dataset: { openplcFacts: "none" } }, "The editor files are made once the config has no errors. See Problems.");
  const editor = S.state.mode === "project";
  const rows = [
    ["Remote device", `${o.remote_device}, 127.0.0.1:${o.port}`],
    ["Poll", `every ${o.poll_ms} ms, ${o.requests} Modbus request${o.requests === 1 ? "" : "s"} per poll`],
    ["Writer lost after", `${o.watchdog_ms} ms`],
    ["Map hash", o.map_hash],
  ];
  if (o.iec_base !== null && o.iec_base !== undefined) rows.push(["Locations in the editor", `from %IW${o.iec_base} and %QW${o.iec_base}`]);
  return el("div", { dataset: { openplcFacts: "1" } },
    el("table", { class: "od" }, el("tbody", null, rows.map(([k, v]) => el("tr", null, el("th", null, k), el("td", null, v))))),
    o.warning ? notice("warning", o.warning, { live: false, dataset: { openplcWarning: "1" } }) : null,
    el("p", { class: "muted" }, editor
      ? "Save writes " + o.files.join(", ") + " and the canworks variable list into this editor project. An open OpenPLC Editor must reopen the project before Build."
      : "Open the OpenPLC Editor project as a project here: Save then writes the remote device, the canworks_in and canworks_out programs and the canworks variable list into it."));
}

// Switches the project target in one undo step, without asking: the server
// adds the target's marker, removes what the new target does not use and
// packs the locations (/api/switch_target); a message says what was done,
// and Undo takes it back.
async function switchTarget(target) {
  const from = projectTarget();
  if (target === from) return;
  let r;
  try {
    r = await api("POST", "/api/switch_target", { config: fileConfig(), target });
  } catch (e) {
    banner(`The switch to ${TARGET_TITLE[target]} failed: ${e.message}. The target is still ${TARGET_TITLE[from]}.`, true);
    render();
    return;
  }
  bridgeReplaceDraft(r.config);
  if ((S.view === "bridge" && !bridgeTarget(target)) || (S.view === "codesys" && target !== "codesys")) S.view = "bus";
  changed(true);
  const done = [];
  if (r.removed) done.push(`${r.removed} setting${r.removed === 1 ? "" : "s"} ${TARGET_LABEL[target]} does not use removed`);
  if (r.located) done.push(`${r.located} PDO entr${r.located === 1 ? "y" : "ies"} got a location`);
  const page = target === "bridge" ? " See the Modbus bridge page."
    : target === "openplc_modbus" ? " Save writes the editor files; see the Project page." : target === "codesys" ? " See the CODESYS page." : "";
  banner(el("span", { dataset: { switchDone: target } },
    `The project targets ${TARGET_TITLE[target]} now` + (done.length ? ": " + done.join(", ") + "." : ".") + page + " ",
    el("button", { type: "button", class: "link", dataset: { undo: "1" }, onclick: () => undo(false) }, "Undo")));
}

// -- the CODESYS page -------------------------------------------------------------

function codesysOn() { return projectTarget() === "codesys"; }

// The network's CODESYS settings on a CANopen master network's Bus page.
function codesysNetworkFieldset() {
  return el("fieldset", { dataset: { codesysNetwork: "1" } }, el("legend", null, "CODESYS"),
    el("div", { class: "grid" },
      field("Network number", "codesys.net_id", "intstr", { placeholder: "from the interface name",
        hint: "The CANbus's network number in CODESYS, 0 to 255. Empty: the number the interface name ends in (can1 is 1), else 0." }),
      field("CAN interface object", "codesys.interface", "text", { placeholder: "the device's only one",
        hint: "The CAN interface object of the CODESYS device that gets this bus. Empty: the device's only CAN interface, or the one whose name ends in the network number." })));
}

function renderCodesys(view) {
  const found = !!(S.state && S.state.codesys_found);
  view.append(el("h2", null, "CODESYS"),
    el("p", { class: "muted" }, "A CODESYS PLC runs this config's CANopen master networks. canworks builds the CANbus, the CANopen manager, the nodes with their DCFs and the named I/O channels into the CODESYS project. Each network's number and CAN interface object are on its Bus page."),
    el("fieldset", { dataset: { codesysProject: "1" } }, el("legend", null, "Project"),
      el("div", { class: "grid" },
        codesysProjectField(),
        field("Device", "codesys.device", "text", { placeholder: "the active application's device",
          hint: "The device's name in the project tree that gets the CANbus. Empty: the device of the project's active application, or its only device." }),
        codesysCreateField(),
        checkbox("Name the I/O channels", "codesys.variables", true,
          "On: every mapped PDO entry's channel gets its variable name (<node>_<entry>), so the program uses the names."))),
    el("fieldset", null, el("legend", null, "Build"),
      el("p", { class: "muted" }, found
        ? "Build into CODESYS project runs CODESYS on this PC without its window, with the saved config, and shows CODESYS's report."
        : "CODESYS was not found on this PC. Download for CODESYS gives the files and a script to run in CODESYS on another PC (Tools > Scripting > Execute Script File)."),
      el("div", { class: "toolbar" }, codesysBuildButton(), codesysDownloadButton())));
}

// The project file with Browse… (the folder dialog in file mode); a name
// without an extension gets .project when the field is left.
function codesysProjectField() {
  const f = field("Project file", "codesys.project", "text", { placeholder: "e.g. C:\\Projects\\cell.project",
    hint: "The CODESYS project that Build into CODESYS project updates, or creates when it does not exist yet." });
  const input = f.querySelector("input");
  const settle = () => {
    const v = input.value.trim();
    const p = v ? codesysProjectPath(v) : "";
    if (p !== v) { input.value = p; setPath("codesys.project", p); }
    refreshCodesysCreate();
  };
  input.addEventListener("change", settle);
  const browse = el("button", { type: "button", dataset: { codesysBrowse: "1" }, onclick: async () => {
    const p = await chooseFolder({ title: "Choose the CODESYS project", start: splitPath(input.value.trim())[0] || "",
      files: ".project", newName: "New project name",
      note: "Pick an existing project, or name a new one: Build creates it with the PLC device you pick." });
    if (p === null) return;
    input.value = p;
    setPath("codesys.project", p);
    refreshCodesysCreate();
  } }, "Browse…");
  const row = el("div", { class: "row" });
  input.replaceWith(row);
  row.append(input, browse);
  f.classList.add("span2");
  return f;
}

// `.project` added to a name without an extension (as canworks-deploy does).
function codesysProjectPath(p) {
  const name = p.replace(/[\\/]+$/, "").split(/[\\/]/).pop();
  return /\.[^.]+$/.test(name) ? p : p + ".project";
}

// The PLC devices installed in CODESYS on this PC (/api/codesys/devices),
// and whether the project file exists; asked once per project path.
async function codesysDevices(project) {
  const key = project || "";
  if (S.codesysDevs && S.codesysDevs.key === key) return S.codesysDevs.r;
  let r;
  try {
    r = await api("GET", "/api/codesys/devices" + (key ? "?project=" + encodeURIComponent(key) : ""));
  } catch (e) {
    r = { devices: [], exists: null };
  }
  S.codesysDevs = { key, r };
  return r;
}

const codesysDeviceText = (d) => `${d.type}:${d.id}:${d.version}`;

// A PLC device picker: the installed PLCs by name and version, and Other…
// for typing TYPE:ID:VERSION; a text field when none are known. onPick
// gets the TYPE:ID:VERSION text ("" for none).
function codesysDevicePicker(devices, value, onPick, id) {
  const text = el("input", { type: "text", spellcheck: "false", id: devices.length ? null : id, dataset: { codesysDeviceText: "1" },
    placeholder: "e.g. 4096:0000 0004:3.5.22.40", "aria-label": "PLC device as TYPE:ID:VERSION" });
  text.value = value || "";
  text.addEventListener("input", () => onPick(text.value.trim()));
  if (!devices.length) return text;
  const known = devices.some((d) => codesysDeviceText(d) === value);
  const sel = el("select", { id, dataset: { codesysDevice: "1" }, "aria-label": "PLC device" },
    el("option", { value: "" }, "Choose the PLC…"),
    ...devices.map((d) => el("option", { value: codesysDeviceText(d) }, `${d.name} ${d.version}`)),
    el("option", { value: "other" }, "Other (type TYPE:ID:VERSION)…"));
  sel.value = !value ? "" : known ? value : "other";
  text.hidden = sel.value !== "other";
  sel.addEventListener("change", () => {
    text.hidden = sel.value !== "other";
    if (sel.value === "other") { text.focus(); onPick(text.value.trim()); } else onPick(sel.value);
  });
  return el("div", { class: "codesys-device" }, sel, text);
}

// "PLC device for a new project": shown while the project file does not
// exist; an existing project says the bus is added to it.
function codesysCreateField() {
  const box = el("div", { dataset: { codesysCreate: "1" } });
  fillCodesysCreate(box);
  return box;
}

function refreshCodesysCreate() {
  const box = document.querySelector("[data-codesys-create]");
  if (box) fillCodesysCreate(box);
}

async function fillCodesysCreate(box) {
  const project = (getPath("codesys.project") || "").trim();
  const r = await codesysDevices(project);
  if (project && r.exists) {
    box.replaceChildren(el("label", null, "PLC device for a new project",
      el("p", { class: "muted", dataset: { codesysExisting: "1" } }, "Existing project: Build adds the bus to it.")));
    return;
  }
  const picker = codesysDevicePicker(r.devices || [], getPath("codesys.create") || "", (v) => setPath("codesys.create", v), "codesys-create");
  box.replaceChildren(el("label", { for: "codesys-create" }, "PLC device for a new project", picker,
    hint(r.devices && r.devices.length
      ? "The PLC of the new project, from the devices installed in CODESYS on this PC."
      : "TYPE:ID:VERSION from CODESYS's device repository: the new project gets this PLC device."),
    el("span", { class: "field-msg", dataset: { for: "codesys.create" } })));
}

function codesysBuildButton() {
  const b = el("button", { type: "button", class: "primary", dataset: { codesysBuild: "1" },
    title: "Build the saved config into the CODESYS project with CODESYS on this PC" }, "Build into CODESYS project…");
  b.onclick = () => busy(b, "Building…", codesysBuild);
  return b;
}

function codesysDownloadButton() {
  const b = el("button", { type: "button", dataset: { codesysDownload: "1" },
    title: "The node DCFs and a script that builds the bus in CODESYS, as one zip" }, "Download for CODESYS");
  b.onclick = () => busy(b, "Exporting…", exportCodesys);
  return b;
}

// Build into CODESYS project: the saved config through canworks-deploy
// --codesys-import, CODESYS's report in a dialog and the log.
async function codesysBuild() {
  if (!(S.state && S.state.codesys_found)) {
    const v = await modal("CODESYS was not found on this PC, so the project cannot be built here. Download for CODESYS gives the files and a script to run in CODESYS.",
      [["cancel", "Close"], ["download", "Download for CODESYS", true]]);
    if (v === "download") await exportCodesys();
    return;
  }
  if (!getPath("codesys.project")) {
    banner("Give the CODESYS project file on the CODESYS page first.", true);
    if (S.view !== "codesys") showView("codesys");
    return;
  }
  // A project that does not exist yet needs its PLC: asked here rather than failing in CODESYS.
  S.codesysDevs = null;
  const devs = await codesysDevices(getPath("codesys.project"));
  if (devs.exists === false && !getPath("codesys.create")) {
    let pickedDevice = "";
    const picker = codesysDevicePicker(devs.devices || [], "", (v) => { pickedDevice = v; }, "codesys-new-device");
    const extra = el("div", { class: "field", dataset: { codesysNew: "1" } },
      el("label", { for: "codesys-new-device" }, "PLC device"), picker,
      hint("The new project gets this PLC device, and canworks adds the bus to it."));
    let text = `${getPath("codesys.project")} does not exist. Create a new CODESYS project?`;
    for (;;) {
      const v = await modal(text, [["cancel", "Cancel"], ["create", "Create and build", true]], extra);
      if (v !== "create") return;
      if (pickedDevice) break;
      text = "Pick the PLC device of the new project.";
    }
    // Create and build is the go-ahead to save: no second question.
    setPath("codesys.create", pickedDevice);
    if (S.view === "codesys") render();
    await save();
    if (S.dirty) return;
  }
  if (S.dirty) {
    const v = await modal("Build uses the saved config. Save the changes first?", [["cancel", "Cancel"], ["save", "Save and build", true]]);
    if (v !== "save") return;
    await save();
    if (S.dirty) return;
    await runCheck();
  }
  if (handoffRefused(document.querySelector("[data-codesys-build]"))) return;
  let r;
  try {
    r = await api("POST", "/api/codesys/build", {});
  } catch (e) {
    banner(e.message, true);
    return;
  }
  const report = r.output || r.report || "";
  const device = codesysReportDevice(report);
  const text = r.ok ? `CODESYS built the bus into ${device || "the project"}.`
    : "The CODESYS build failed" + (device ? ` on ${device}` : "") + "." + (r.hint ? " " + r.hint : "");
  await modal(text, [["close", "Close", true]], el("pre", { class: "codesys-report", dataset: { codesysReport: "1" } }, report));
  banner(text, !r.ok);
}

// The device the CODESYS report's device line names, with its reason:
// "device   ExampleApp (active application)" -> "ExampleApp (active application)".
function codesysReportDevice(report) {
  const m = /^device\s+(.+?)\s*$/m.exec(report || "");
  return m ? m[1] : "";
}
