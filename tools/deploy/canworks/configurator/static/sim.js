// Simulation view (canopen-configurator "Simulation view" and "Scenarios in
// the configurator"; docs/simulator.md): live values, overrides, value
// sources, faults and scenarios of simulated devices, through the runtime's
// diagnostics channel or a standalone canworks-sim, and the draft of
// canworks/simulation.json. Loaded after app.js and uses its helpers (el, api,
// banner, modal, put, S, ...).
"use strict";

const SIM_POLL_MS = 400;
const SIM_INT_RANGE = {
  INTEGER8: [-128, 127], INTEGER16: [-32768, 32767], INTEGER24: [-8388608, 8388607],
  INTEGER32: [-2147483648, 2147483647], INTEGER64: [-Number.MAX_SAFE_INTEGER, Number.MAX_SAFE_INTEGER],
  UNSIGNED8: [0, 255], UNSIGNED16: [0, 65535], UNSIGNED24: [0, 16777215], UNSIGNED32: [0, 4294967295],
  UNSIGNED64: [0, Number.MAX_SAFE_INTEGER],
};
const SIM_BITS = { UNSIGNED8: 8, UNSIGNED16: 16 };
const SOURCE_TYPES = [["constant", "Constant"], ["sine", "Sine"], ["triangle", "Triangle"], ["sawtooth", "Sawtooth"],
  ["square", "Square"], ["ramp", "Ramp"], ["steps", "Step sequence"], ["random_walk", "Random walk"],
  ["counter", "Counter"], ["csv", "CSV time series"], ["expr", "Expression"]];
const WAVE = [["min", "Min", true], ["max", "Max", true], ["period_s", "Period (s)", true], ["phase_deg", "Phase (°)"]];
const SOURCE_FIELDS = {
  sine: WAVE, triangle: WAVE, sawtooth: WAVE, square: WAVE.concat([["duty", "Duty (0-1)"]]),
  ramp: [["from", "From", true], ["to", "To", true], ["duration_s", "Duration (s)", true]],
  random_walk: [["min", "Min", true], ["max", "Max", true], ["max_step", "Max step per tick", true], ["start", "Start"]],
  counter: [["start", "Start"], ["step", "Step"], ["min", "Min"], ["max", "Max"]],
  csv: [["column", "Column"], ["time_scale", "Time scale"]],
};
// Fault buttons: [key, label, form?]. The ones without a form act at once.
const FAULT_KINDS = [["emcy", "EMCY…", true], ["heartbeat", "Heartbeat stop"], ["power_off", "Power off"],
  ["power_on", "Power on"], ["power_cycle", "Power cycle…", true], ["reset_node", "Reset node"],
  ["reset_comm", "Reset communication"], ["nmt_state", "NMT state…", true], ["sdo_abort", "SDO abort…", true],
  ["sdo_delay", "SDO delay…", true], ["refuse_write_operational", "Refuse writes while operational"],
  ["tpdo_stop", "TPDO stop…", true], ["identity", "Identity…", true], ["device_type", "Device type…", true],
  ["forget_node_id", "Forget node ID"], ["drive_input", "Drive inputs…", true]];
const FAULT_FIXED = { heartbeat: { heartbeat: "stop" }, power_off: { power: "off" }, power_on: { power: "on" },
  reset_node: { reset: "node" }, reset_comm: { reset: "comm" }, refuse_write_operational: { refuse_write_operational: true },
  forget_node_id: { forget_node_id: true } };
const CLEAR_NAMES = ["all", "emcy", "heartbeat", "power", "sdo_abort", "sdo_delay", "refuse_write_operational", "tpdo_stop",
  "identity", "device_type", "drive_input"];
const IDENTITY_KEYS = [["vendor_id", "Vendor ID"], ["product_code", "Product code"], ["revision_number", "Revision"],
  ["serial_number", "Serial number"]];
const DRIVE_INPUTS = [["blocked", "Blocked"], ["positive_limit", "Positive limit"], ["negative_limit", "Negative limit"],
  ["home_switch", "Home switch"]];
const DRIVE_FIELDS = [["max_velocity", "Max velocity (counts/s)", "100000"], ["max_acceleration", "Max acceleration (counts/s²)", "1000000"],
  ["lag_ms", "Lag (ms)", "5"], ["start_position", "Start position", "0"],
  ["torque_accel", "Torque gain (counts/s² per ‰)", "10000"]];
const STEP_ACTIONS = [["set", "Set"], ["override", "Override"], ["release", "Release"], ["source", "Source"], ["fault", "Fault"],
  ["clear", "Clear"], ["wait", "Wait"], ["expect", "Expect"], ["log", "Log"], ["repeat", "Repeat"]];
const NODE_ACTIONS = ["set", "override", "release", "source", "fault", "clear"];
const COND_OPS = [["eq", "="], ["ne", "≠"], ["lt", "<"], ["le", "≤"], ["gt", ">"], ["ge", "≥"]];
const SCENARIO_NAME = /^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$/;
const SIM_STATES = { idle: "idle", running: "running", passed: "passed", failed: "failed", stopped: "stopped" };

const SIM = {
  settings: null,  // /api/sim/settings: target, address, token_set, pins
  doc: null,       // the draft simulation file
  saved: "",       // JSON text of the file as loaded or saved
  tab: "live",     // "live" | "file" | "scenarios"
  node: null,      // the device shown on the live tab (node ID or extra device name)
  last: null,      // last /api/sim/poll answer
  connected: false,
  open: false,
  seq: 0,
  timer: null,
  rowKeys: "",
  rows: new Map(),
  editing: null,   // object whose source editor is open on the live tab
  scenario: null,  // name of the scenario in the step editor
  runs: {},        // name -> { state, start, end } seen by the page
  problems: [],
  checkTimer: null,
  scenSig: "",
};

function simClone(x) { return JSON.parse(JSON.stringify(x)); }

// The simulation file as the project has it (on load and reload). SIM.file
// is the whole file; SIM.doc the part the view edits: the file itself
// (version 1), or the shown network's section (version 2).
function simLoad() {
  const sim = (S.state && S.state.simulation) || {};
  SIM.file = simClone(sim.doc || { schema_version: 1 });
  SIM.saved = simFileText();
  SIM.converted = null;
  SIM.problems = [];
  SIM.scenario = null;
  simBind();
  if (sim.error) banner(sim.error, true);
}

function simVersion() { return Number.isInteger(SIM.file.schema_version) ? SIM.file.schema_version : 1; }

// The section name of the shown network (as the plugin: its name, or its
// interface).
function simSectionName() {
  return netName(S.config) || (S.config.adapter && typeof S.config.adapter.interface === "string" ? S.config.adapter.interface : "");
}

// Points SIM.doc at the shown network's part. A version 1 file of a config
// with several networks becomes version 2 here, its content in the first
// network's section; the save asks before writing that.
function simBind() {
  if (simVersion() < 2 && several()) {
    const first = netName(S.model.networks[0]) || ((S.model.networks[0].adapter || {}).interface || "");
    const body = {};
    for (const k of ["nodes", "extra_devices", "scenarios"]) if (SIM.file[k] !== undefined) body[k] = SIM.file[k];
    const out = { schema_version: 2 };
    if (SIM.file.tick_ms !== undefined) out.tick_ms = SIM.file.tick_ms;
    if (SIM.file.raw_devices !== undefined) out.raw_devices = SIM.file.raw_devices;
    out.networks = Object.keys(body).length ? { [first]: body } : {};
    if (Object.keys(body).length) SIM.converted = first;
    SIM.file = out;
  }
  if (simVersion() >= 2) {
    const name = simSectionName();
    if (!SIM.file.networks || typeof SIM.file.networks !== "object") SIM.file.networks = {};
    if (!SIM.file.networks[name]) SIM.file.networks[name] = {};
    SIM.doc = SIM.file.networks[name];
  } else {
    SIM.doc = SIM.file;
  }
}

// The file as it would be saved: empty sections left out.
function simFileOut() {
  const out = simClone(SIM.file);
  if (out.networks && typeof out.networks === "object") {
    for (const k of Object.keys(out.networks)) {
      const v = out.networks[k];
      if (v && typeof v === "object" && !Object.keys(v).length) delete out.networks[k];
    }
  }
  return out;
}
function simFileText() { return JSON.stringify(simFileOut()); }

function simDirty() { return !!SIM.file && simFileText() !== SIM.saved; }

function stopSim(keepConnection) {
  clearTimeout(SIM.timer);
  SIM.timer = null;
  SIM.seq++;
  if (SIM.open && !keepConnection) api("POST", "/api/sim/close", {}).catch(() => {});
  if (!keepConnection) SIM.open = false;
  SIM.connected = false;
}

// ---------------------------------------------------------------------------
// Objects, devices and values

function simKey(o) {
  if (typeof o !== "string") return String(o);
  const m = /^\s*(?:0x)?([0-9a-f]{1,4})(?::(0x[0-9a-f]+|\d+))?\s*$/i.exec(o);
  if (!m) return o.trim();
  const sub = m[2] === undefined ? 0 : (m[2].toLowerCase().startsWith("0x") ? parseInt(m[2], 16) : parseInt(m[2], 10));
  return "0x" + parseInt(m[1], 16).toString(16).toUpperCase().padStart(4, "0") + ":" + sub;
}

function simSplit(key) {
  const m = /^0x([0-9A-F]{4}):(\d+)$/.exec(key);
  return m ? [parseInt(m[1], 16), Number(m[2])] : [NaN, NaN];
}

// The keys of a status list or object (sources, overrides).
function simKeys(x) {
  if (!x) return [];
  if (Array.isArray(x)) return x.map((o) => simKey(typeof o === "object" && o ? o.object : o));
  return Object.keys(x).map(simKey);
}

function simRef(d) { return d.node ? d.node : d.name; }
function simRefText(ref) { return typeof ref === "number" || /^\d+$/.test(String(ref)) ? `Node ${ref}` : String(ref); }

// The simulation file's entry for a device: nodes["5"], or the extra device.
function simEntry(ref, create) {
  const doc = SIM.doc;
  const extra = (doc.extra_devices || []).find((d) => (d.node && String(d.node) === String(ref)) || (!d.node && d.name === ref));
  if (extra) return extra;
  if (!/^\d+$/.test(String(ref))) return null;
  if (!doc.nodes || !doc.nodes[String(ref)]) {
    if (!create) return null;
    doc.nodes = doc.nodes || {};
    doc.nodes[String(ref)] = {};
  }
  return doc.nodes[String(ref)];
}

// Drops empty parts of a device entry, so a file stays minimal.
function simTidy(ref) {
  const doc = SIM.doc;
  const e = doc.nodes && doc.nodes[String(ref)];
  if (e) {
    if (e.sources && !Object.keys(e.sources).length) delete e.sources;
    if (e.faults && !e.faults.length) delete e.faults;
    if (e.drive && !Object.keys(e.drive).length) delete e.drive;
    if (!Object.keys(e).length) delete doc.nodes[String(ref)];
    if (doc.nodes && !Object.keys(doc.nodes).length) delete doc.nodes;
  }
  for (const d of doc.extra_devices || []) {
    if (d.sources && !Object.keys(d.sources).length) delete d.sources;
    if (d.faults && !d.faults.length) delete d.faults;
    if (d.drive && !Object.keys(d.drive).length) delete d.drive;
  }
}

// The EDS summary of a device: the config node's, or the extra device's.
function simEds(ref) {
  const eds = S.state.eds || {};
  const n = (S.config.nodes || []).find((x) => String(num(x.node_id)) === String(ref));
  if (n) return eds[n.eds] || null;
  const d = (SIM.doc.extra_devices || []).find((x) => (x.node && String(x.node) === String(ref)) || (!x.node && x.name === ref));
  if (d) return eds[d.eds] || null;
  const live = simDevice(ref);
  return live && live.eds ? eds[live.eds] || eds[String(live.eds).split("/").pop()] || null : null;
}

function simObjInfo(ref, key) {
  const [index, sub] = simSplit(key);
  return objectInfo(simEds(ref), index, sub);
}

function simProfile(ref) {
  const live = simDevice(ref);
  if (live && live.profile !== undefined) return Number(live.profile);
  const o = objectInfo(simEds(ref), 0x1000, 0);
  const v = o ? num(String(o.default).replace(/\$NODEID\+?/i, "")) : NaN;
  return Number.isNaN(v) ? null : v & 0xFFFF;
}

function simDevice(ref) {
  const st = SIM.last && SIM.last.status;
  return st ? (st.devices || []).find((d) => String(simRef(d)) === String(ref)) || null : null;
}

// Every device the view can name: the config's nodes, the extra devices, and
// what the simulator reports.
function simDeviceRefs() {
  const refs = [];
  const add = (r) => { if (r !== undefined && r !== null && r !== "" && !refs.some((x) => String(x) === String(r))) refs.push(r); };
  for (const n of S.config.nodes || []) if (Number.isInteger(num(n.node_id))) add(num(n.node_id));
  for (const d of SIM.doc.extra_devices || []) add(d.node ? d.node : d.name);
  for (const d of ((SIM.last && SIM.last.status) || {}).devices || []) add(simRef(d));
  return refs;
}

function simDeviceName(ref) {
  const n = (S.config.nodes || []).find((x) => String(num(x.node_id)) === String(ref));
  if (n) return n.name || "";
  const d = (SIM.doc.extra_devices || []).find((x) => (x.node && String(x.node) === String(ref)) || (!x.node && x.name === ref));
  if (d) return d.name || "";
  const live = simDevice(ref);
  return live ? live.name || "" : "";
}

function simValueText(v, type) {
  if (v === undefined || v === null) return "";
  if (type === "BOOLEAN") return v === true || Number(v) ? "TRUE" : "FALSE";
  if (typeof v === "number" && SIM_BITS[type]) return `${v} (0x${v.toString(16).toUpperCase().padStart(SIM_BITS[type] / 4, "0")})`;
  return String(v);
}

// A typed value: a number when it reads as one, else the text.
function simParseValue(t) {
  t = String(t).trim();
  if (/^-?(\d+\.?\d*|\.\d+)(e[+-]?\d+)?$/i.test(t)) return Number(t);
  if (/^0x[0-9a-f]+$/i.test(t)) return parseInt(t, 16);
  if (t === "true") return true;
  if (t === "false") return false;
  return t;
}

// "0x5000" stays as written, "20480" becomes a number (the file takes both).
function simCode(t, what, optional) {
  t = String(t || "").trim();
  if (!t) { if (optional) return undefined; throw new Error(`Give the ${what}.`); }
  if (/^0x[0-9a-f]{1,8}$/i.test(t)) return t;
  if (/^\d+$/.test(t)) return Number(t);
  throw new Error(`The ${what} must be a number, decimal or 0x hex.`);
}

function simInt(t, what, optional, lo, hi) {
  t = String(t || "").trim();
  if (!t) { if (optional) return undefined; throw new Error(`Give the ${what}.`); }
  if (!/^-?\d+$/.test(t)) throw new Error(`The ${what} must be a whole number.`);
  const v = Number(t);
  if ((lo !== undefined && v < lo) || (hi !== undefined && v > hi)) throw new Error(`The ${what} must be ${lo}-${hi}.`);
  return v;
}

function simNum(t, what, optional) {
  t = String(t || "").trim();
  if (!t) { if (optional) return undefined; throw new Error(`Give the ${what}.`); }
  if (!/^-?(\d+\.?\d*|\.\d+)(e[+-]?\d+)?$/i.test(t)) throw new Error(`The ${what} must be a number.`);
  return Number(t);
}

// One sentence for a source (the file tab, the live tags).
function sourceText(src) {
  if (!src || typeof src !== "object") return "none";
  const type = SOURCE_TYPES.map((x) => x[0]).find((k) => k in src);
  if (!type) return "?";
  const p = src[type];
  let text = type;
  if (type === "constant") text = `constant ${p}`;
  else if (type === "expr") text = `expression ${p}`;
  else if (["sine", "triangle", "sawtooth", "square"].includes(type)) text = `${type} ${p.min} to ${p.max}, ${p.period_s} s`;
  else if (type === "ramp") text = `ramp ${p.from} to ${p.to} in ${p.duration_s} s`;
  else if (type === "steps") text = `steps (${(p.values || []).length})`;
  else if (type === "random_walk") text = `random walk ${p.min} to ${p.max}`;
  else if (type === "csv") text = `CSV ${p.file}`;
  return text + (src.noise ? ` + noise ${src.noise}` : "");
}

function faultName(f) {
  if (typeof f === "string") return f;
  return Object.keys(f || {}).find((k) => k !== "off_ms") || "?";
}

function faultText(f) {
  if (typeof f === "string") return f;
  const k = faultName(f);
  const v = f[k];
  if (v === true) return k;
  if (typeof v !== "object") return `${k} ${v}${f.off_ms ? ` (${f.off_ms} ms)` : ""}`;
  return `${k} ` + Object.entries(v).map(([a, b]) => `${a} ${b}`).join(", ");
}

// ---------------------------------------------------------------------------
// The view

function simAllow() { return !!(SIM.last && SIM.last.allow_changes); }

function simNoChanges() {
  if (SIM.last && SIM.last.target === "runtime") {
    return "Read-only: the runtime does not allow changes (turn on \"Allow changes\" under Online access on Bus and master, then save and upload). Values are still shown.";
  }
  return "Read-only: not connected to the simulated devices.";
}

async function loadSimSettings() {
  try { SIM.settings = await api("GET", "/api/sim/settings"); }
  catch (e) { SIM.settings = { target: "runtime", address: "127.0.0.1:7532", token_set: false, pins: {} }; }
}

async function renderSimulation(view) {
  document.querySelector("#editor").classList.add("wide-view");
  if (!SIM.file) simLoad(); else simBind();
  const seq = SIM.seq;
  if (!SIM.settings) await loadSimSettings();
  if (seq !== SIM.seq || S.view !== "simulation") return;
  // The Machine tab shows only when the shown network's section names a
  // machine file; another network falls back to Live values.
  const pages = [["live", "Live values"], ["file", "Simulation file"], ["scenarios", "Scenarios"]];
  if (machineName()) pages.push(["machine", "Machine"]);
  else if (SIM.tab === "machine") SIM.tab = "live";
  const tabList = tabs(pages, SIM.tab,
    (k) => { SIM.tab = k; SIM.rowKeys = ""; SIM.scenSig = ""; render(); }, { dataset: "simTab", panel: "sim-body", label: "Simulation pages" });
  view.append(
    el("div", { class: "toolbar" }, el("h2", null, "Simulation"), el("div", { class: "spacer" }), simSaveBar()),
    simConnectBox(),
    el("div", { id: "sim-conn", class: "online-conn" }, "Not connected."),
    el("p", { id: "sim-readonly", class: "field-msg warning", hidden: true, dataset: { sim: "readonly" } }),
    tabList,
    el("div", { id: "sim-body", role: "tabpanel", "aria-labelledby": "sim-body-tab-" + SIM.tab }));
  simRenderTab();
  if (simCanConnect()) {
    SIM.open = true;
    $("#sim-conn").textContent = "Connecting…";
    simPoll(SIM.seq);
  }
}

function simCanConnect() {
  if (SIM.settings.target === "simulator") return true;
  return !!(diagConfig() && S.online && S.online.host && S.online.token && S.online.tokenOk);
}

function simSaveBar() {
  const state = el("span", { class: "muted", dataset: { sim: "file-state" } });
  const btn = el("button", { type: "button", class: "primary", dataset: { sim: "save" }, onclick: () => simSave(false) }, "Save to simulation file");
  simShowFileState(state);
  return el("span", { class: "row" }, state, btn);
}

function simShowFileState(target) {
  const t = target || document.querySelector('[data-sim="file-state"]');
  if (!t) return;
  const exists = S.state.simulation && S.state.simulation.exists;
  const n = SIM.problems.length;
  t.textContent = (simDirty() ? "Unsaved changes" : exists ? "Saved" : "No simulation file yet") +
    (n ? ` · ${n} problem${n === 1 ? "" : "s"}` : "") + ` (${(S.state.mode === "project" ? "canworks/" : "") + "simulation.json"})`;
  t.classList.toggle("field-msg", n > 0);
}

function simConnectBox() {
  const target = SIM.settings.target;
  const choose = async (t) => {
    try { SIM.settings = await api("POST", "/api/sim/settings", { target: t }); } catch (e) { banner(e.message, true); return; }
    SIM.last = null;
    render();
  };
  const seg = el("div", { class: "segmented", role: "group", "aria-label": "Connect to" },
    [["runtime", "Runtime"], ["simulator", "Standalone simulator"]].map(([k, label]) =>
      el("button", { type: "button", "aria-pressed": String(k === target), dataset: { simTarget: k }, onclick: () => choose(k) }, label)));
  const box = el("fieldset", { dataset: { sim: "connect" } }, el("legend", null, "Connect to"), el("div", { class: "toolbar" }, seg));
  if (target === "runtime") {
    if (!diagConfig()) {
      box.append(el("p", null, "Online access is off for this config. Turn it on under ",
        el("a", { href: "#", onclick: (e) => { e.preventDefault(); showView("bus"); } }, "Bus and master"),
        " (simulating a node or the network does this), save, and upload the program to the runtime."));
    } else if (!simCanConnect()) {
      box.append(el("p", null, "The runtime's simulated devices are reached through online access. Enter the runtime host and the token in the ",
        el("a", { href: "#", onclick: (e) => { e.preventDefault(); showView("online"); } }, "Online"), " view first."));
    } else {
      box.append(hint(`The simulated devices of the runtime ${S.online.host}, through online access (port ${diagPort()} unless the host gives one).`));
    }
    return box;
  }
  const address = el("input", { type: "text", spellcheck: "false", placeholder: "127.0.0.1:7532", "aria-label": "Simulator address", dataset: { sim: "address" } });
  address.value = SIM.settings.address || "";
  const token = el("input", { type: "password", autocomplete: "off", placeholder: SIM.settings.token_set ? "kept on this PC" : "none", "aria-label": "Simulator token", dataset: { sim: "token" } });
  const connect = async () => {
    const body = { address: address.value.trim() };
    if (token.value.trim()) body.token = token.value.trim();
    try { SIM.settings = await api("POST", "/api/sim/settings", body); } catch (e) { banner(e.message, true); return; }
    banner("");
    render();
  };
  box.append(el("div", { class: "grid" },
    el("label", null, "Simulator address", address, hint("HOST[:PORT] of a running canworks-sim, port 7532 when not given. Kept on this PC, not in the project.")),
    el("label", null, "Token", token, hint("Only when the simulator was started with a token."))),
  el("div", { class: "toolbar" },
    el("button", { type: "button", class: "primary", dataset: { sim: "connect" }, onclick: connect }, "Connect"),
    SIM.settings.token_set ? el("button", { type: "button", onclick: async () => {
      try { SIM.settings = await api("POST", "/api/sim/settings", { token: "" }); } catch (e) { banner(e.message, true); return; }
      render();
    } }, "Forget token") : null));
  return box;
}

async function simPoll(seq) {
  let r = null;
  let err = null;
  const node = SIM.tab === "live" ? SIM.node : null;
  try {
    r = await api("POST", "/api/sim/poll", { port: diagPort(), node, objects: node === null ? [] : simExtraObjects(node) });
  } catch (e) { err = e; }
  if (seq !== SIM.seq || S.view !== "simulation") return;
  const conn = $("#sim-conn");
  if (err) {
    SIM.connected = false;
    const msg = err.message || "";
    const why = /nothing simulated/.test(msg) ? "nothing simulated"
      : { closed: "port closed", unreachable: "host unreachable", token: "wrong token", timeout: "no answer",
        protocol: "not a CANopen diagnostics port", refused: "refused" }[err.body && err.body.kind] || "error";
    conn.className = "online-conn error";
    conn.textContent = why === "nothing simulated"
      ? "Connected, but nothing is simulated there: the configuration the runtime runs has no simulated network or node (save and upload this one). Retrying…"
      : `Not connected (${why}): ${msg}. Retrying…`;
    simReadonly();
    SIM.timer = setTimeout(() => simPoll(seq), 2000);
    return;
  }
  const first = !SIM.connected;
  SIM.connected = true;
  SIM.last = r;
  const st = r.status || {};
  const devices = st.devices || [];
  if (SIM.node === null && devices.length) SIM.node = simRef(devices[0]);
  const where = r.target === "simulator" ? `the simulator at ${(SIM.settings && SIM.settings.address) || "its address"}` : S.online.host;
  conn.className = "online-conn ok";
  conn.replaceChildren(`Connected to ${where}: ` +
    (st.simulated_network ? "simulated network" : `real network ${st.interface || ""}`.trim()) +
    `, ${devices.length} simulated device${devices.length === 1 ? "" : "s"}, ` + (r.allow_changes ? "changes allowed." : "read-only."));
  simReadonly();
  // The live tab is drawn once connected; the others keep what is being typed.
  if (first && SIM.tab === "live") simRenderTab();
  else simUpdate();
  SIM.timer = setTimeout(() => simPoll(seq), SIM_POLL_MS);
}

function simReadonly() {
  const p = $("#sim-readonly");
  if (!p) return;
  const show = SIM.connected && !simAllow();
  p.hidden = !show;
  p.textContent = show ? simNoChanges() : "";
}

// Objects read besides the PDO ones: those with a source or an override,
// and the pinned ones.
function simExtraObjects(ref) {
  const d = simDevice(ref);
  const keys = new Set([...simKeys(d && d.sources), ...simKeys(d && d.overrides), ...simPins(ref)]);
  return [...keys];
}

function simPins(ref) { return ((SIM.settings && SIM.settings.pins) || {})[String(ref)] || []; }

async function simSetPins(ref, list) {
  const pins = Object.assign({}, SIM.settings.pins || {});
  if (list.length) pins[String(ref)] = list; else delete pins[String(ref)];
  try { SIM.settings = await api("POST", "/api/sim/settings", { pins }); } catch (e) { banner(e.message, true); }
  SIM.rowKeys = "";
  simUpdate();
}

async function simRequest(op, fields, done) {
  try {
    const r = await api("POST", "/api/sim/request", Object.assign({ op, port: diagPort() }, fields));
    if (done) banner(done);
    return r.result || {};
  } catch (e) {
    banner(e.message, true);
    return null;
  }
}

function simRenderTab() {
  const body = $("#sim-body");
  if (!body) return;
  SIM.rowKeys = "";
  SIM.scenSig = "";
  if (SIM.tab === "machine") { simMachineTab(body); return; }
  if (SIM.tab === "file") put(body, simFileTab());
  else if (SIM.tab === "scenarios") put(body, simScenariosTab());
  else put(body, simLiveTab());
  simUpdate();
}

function simUpdate() {
  if (SIM.tab === "live") { simUpdateDevices(); simUpdateValues(); simUpdateFaults(); }
  else if (SIM.tab === "scenarios") simUpdateScenarios();
}

// ---------------------------------------------------------------------------
// Live values

function simLiveTab() {
  if (!SIM.connected) {
    return el("p", { class: "muted" }, simCanConnect()
      ? "The live values show once the view is connected. The simulation file and the scenarios can be edited without a connection."
      : "Connect to see live values. The simulation file and the scenarios can be edited without a connection.");
  }
  return el("div", null,
    el("table", { class: "online-nodes", dataset: { sim: "devices" } },
      el("thead", null, el("tr", null, thCells(["Device", "Name", "Network", "NMT", "Power", "Conflict", "Faults", "Sources / overrides"]))),
      el("tbody", { id: "sim-devices" })),
    el("div", { id: "sim-device" }));
}

function simUpdateDevices() {
  const tb = $("#sim-devices");
  if (!tb || !SIM.last) return;
  const st = SIM.last.status || {};
  const devices = st.devices || [];
  tb.replaceChildren(...(devices.length ? devices.map((d) => {
    const ref = simRef(d);
    return el("tr", rowAttrs(() => { SIM.node = ref; SIM.editing = null; simUpdateDevices(); simDevicePanel(); },
      { class: "clickable" + (String(ref) === String(SIM.node) ? " active" : ""), dataset: { simDevice: String(ref) }, "aria-label": `Open device ${d.node || ref}` }),
    el("td", null, d.node ? String(d.node) : "none"), el("td", null, simDeviceName(ref) || d.name || ""),
    el("td", null, st.simulated_network ? "simulated" : `real ${st.interface || ""}`.trim()),
    el("td", null, d.nmt || ""), el("td", { class: d.power === "off" ? "bad" : null }, d.power || ""),
    el("td", { class: d.conflict ? "bad" : null }, d.conflict ? "node ID conflict" : ""),
    el("td", null, (d.faults || []).map(faultText).join(", ")),
    el("td", null, `${simKeys(d.sources).length} / ${simKeys(d.overrides).length}`));
  }) : [el("tr", null, el("td", { colspan: 8, class: "muted" }, "No simulated devices."))]));
  if (!$("#sim-device").dataset.ref || $("#sim-device").dataset.ref !== String(SIM.node)) simDevicePanel();
  const line = document.querySelector('[data-sim="device-state"]');
  if (line && SIM.node !== null) line.textContent = simDeviceState(SIM.node);
}

function simDeviceState(ref) {
  const d = simDevice(ref) || {};
  const st = (SIM.last && SIM.last.status) || {};
  return `${st.simulated_network ? "On the simulated network" : `On the real network ${st.interface || ""}`.trim()}. ` +
    `NMT ${d.nmt || "?"}, power ${d.power || "?"}` +
    (d.conflict ? ". Node ID conflict: a real device with this node ID is on the bus, so this one is powered off." : ".");
}

function simDevicePanel() {
  const box = $("#sim-device");
  if (!box) return;
  SIM.rowKeys = "";
  const ref = SIM.node;
  box.dataset.ref = ref === null ? "" : String(ref);
  if (ref === null) { box.replaceChildren(); return; }
  const allow = simAllow();
  box.replaceChildren(
    el("h2", null, `${simRefText(ref)} ${simDeviceName(ref)}`),
    el("p", { class: "muted", dataset: { sim: "device-state" } }, simDeviceState(ref)),
    el("fieldset", null, el("legend", null, "Values"),
      el("div", { class: "table-scroll" }, el("table", { class: "od sim-values", dataset: { sim: "values" } },
        el("thead", null, el("tr", null, thCells(["Object", "Name", "Value", "Control", ""]))),
        el("tbody", { id: "sim-rows" }))),
      simPinPicker(ref),
      hint("Objects in the device's PDOs, and those with a source, an override or a pin. A slider, switch or bit holds its value as an override until Release; Set writes it once (a source moves it again).")),
    el("fieldset", { dataset: { sim: "faults" } }, el("legend", null, "Faults"),
      el("div", { class: "toolbar sim-fault-buttons" }, FAULT_KINDS.filter(([k]) => k !== "drive_input" || simProfile(ref) === 402).map(([k, label, form]) =>
        el("button", { type: "button", disabled: !allow, title: allow ? null : simNoChanges(), dataset: { simFault: k },
          onclick: () => (form ? simFaultForm(ref, k) : simInject(ref, FAULT_FIXED[k], label)) }, label))),
      el("div", { id: "sim-fault-form" }),
      el("h3", null, "Active faults"),
      el("div", { id: "sim-active-faults" })));
  simUpdateValues();
  simUpdateFaults();
}

async function simInject(ref, fault, label) {
  await simRequest("sim_fault", { node: ref, fault }, `${simRefText(ref)}: ${label} injected.`);
}

function simFaultForm(ref, kind) {
  const box = $("#sim-fault-form");
  const f = faultFields(kind, null, ref);
  const label = FAULT_KINDS.find((x) => x[0] === kind)[1].replace("…", "");
  const msg = el("span", { class: "field-msg" });
  put(box, el("div", { class: "sim-form", dataset: { simForm: kind } }, el("strong", null, label), f.el, el("div", { class: "toolbar" },
    el("button", { type: "button", class: "primary", dataset: { sim: "inject" }, onclick: () => {
      let fault;
      try { fault = f.value(); } catch (e) { msg.textContent = e.message; return; }
      simInject(ref, fault, label);
    } }, "Inject"),
    el("button", { type: "button", dataset: { sim: "at-start" }, title: "Add this fault to the device's faults at start in the simulation file", onclick: () => {
      let fault;
      try { fault = f.value(); } catch (e) { msg.textContent = e.message; return; }
      const e = simEntry(ref, true);
      if (!e) { msg.textContent = "This device is not in the configuration or the simulation file."; return; }
      e.faults = e.faults || [];
      e.faults.push(fault);
      simChanged();
      banner(`${simRefText(ref)}: ${label} added to the faults at start. Save to simulation file to keep it.`);
    } }, "Add to faults at start"),
    el("button", { type: "button", onclick: () => put(box) }, "Cancel"), msg)));
}

function simUpdateFaults() {
  const box = $("#sim-active-faults");
  if (!box) return;
  const d = simDevice(SIM.node);
  const faults = (d && d.faults) || [];
  const allow = simAllow();
  const sig = JSON.stringify([faults, allow]);
  if (box.dataset.sig === sig) return;
  box.dataset.sig = sig;
  const clear = (f) => {
    const name = faultName(f);
    const fields = { node: SIM.node, fault: name };
    if (typeof f === "object" && name === "sdo_abort" && f.sdo_abort && f.sdo_abort.object) fields.object = f.sdo_abort.object;
    if (typeof f === "object" && name === "tpdo_stop") fields.tpdo = f.tpdo_stop;
    simRequest("sim_clear", fields, `${simRefText(SIM.node)}: ${name} cleared.`);
  };
  put(box, faults.length ? el("ul", { class: "sim-faults" }, faults.map((f) => el("li", null, faultText(f), " ",
    el("button", { type: "button", class: "small", disabled: !allow, title: allow ? null : simNoChanges(), dataset: { simClear: faultName(f) }, onclick: () => clear(f) }, "Clear"))))
    : el("p", { class: "muted" }, "None."),
  el("button", { type: "button", disabled: !allow, title: allow ? null : simNoChanges(), dataset: { simClear: "all" },
    onclick: () => simRequest("sim_clear", { node: SIM.node, fault: "all" }, `${simRefText(SIM.node)}: every fault cleared and the device powered on.`) }, "Clear all"));
}

function simPinPicker(ref) {
  const eds = simEds(ref);
  const objects = eds && eds.objects ? eds.objects.filter((o) => o.type) : [];
  const filter = el("input", { type: "text", placeholder: "Filter objects", "aria-label": "Filter objects" });
  const pick = el("select", { "aria-label": "Object to pin", dataset: { sim: "pin-object" } });
  const typed = el("input", { type: "text", class: "index", placeholder: "0x2000:1", "aria-label": "Object", dataset: { sim: "pin-typed" } });
  const fill = () => {
    const f = filter.value.trim().toLowerCase();
    pick.replaceChildren(el("option", { value: "" }, objects.length ? "Pick an object from the EDS…" : "No EDS objects (type one)"),
      ...objects.filter((o) => !f || `${o.index}:${o.subindex} ${o.name}`.toLowerCase().includes(f)).map((o) =>
        el("option", { value: simKey(`${o.index}:${o.subindex}`) }, `${o.index}:${o.subindex} ${o.name} (${o.type})`)));
  };
  fill();
  filter.addEventListener("input", fill);
  return el("div", { class: "toolbar" }, filter, pick, typed,
    el("button", { type: "button", dataset: { sim: "pin" }, onclick: () => {
      const key = simKey(typed.value.trim() || pick.value);
      if (!/^0x[0-9A-F]{4}:\d+$/.test(key)) { banner("Pick an object, or type it as 0xIIII:S.", true); return; }
      const pins = simPins(ref);
      if (!pins.includes(key)) simSetPins(ref, pins.concat([key]));
      typed.value = "";
    } }, "Pin"));
}

function simUpdateValues() {
  const tb = $("#sim-rows");
  if (!tb || !SIM.last) return;
  const ref = SIM.node;
  const d = simDevice(ref) || {};
  const values = (SIM.last.values || []).filter((v) => String(v.node) === String(ref));
  const byKey = new Map();
  for (const v of values) byKey.set(simKey(v.object), v);
  for (const k of simExtraObjects(ref)) if (!byKey.has(k)) byKey.set(k, { node: ref, object: k });
  const keys = [...byKey.keys()].sort();
  // Rebuilt when the objects change, or a type becomes known (a pinned object).
  const sig = keys.map((k) => k + "=" + (byKey.get(k).type || "")).join(",") + "|" + simAllow() + "|" + SIM.editing;
  if (sig !== SIM.rowKeys) {
    SIM.rowKeys = sig;
    SIM.rows = new Map();
    const rows = [];
    for (const k of keys) {
      const row = simRow(ref, k, byKey.get(k));
      SIM.rows.set(k, row);
      rows.push(row.tr);
      if (SIM.editing === k) rows.push(simSourceRow(ref, k, row));
    }
    tb.replaceChildren(...(rows.length ? rows : [el("tr", null, el("td", { colspan: 5, class: "muted" },
      SIM.last.pdo_error ? SIM.last.pdo_error : "No objects in this device's PDOs; pin one below."))]));
  }
  const sources = d.sources || {};
  const overrides = simKeys(d.overrides);
  for (const [k, row] of SIM.rows) {
    const src = Array.isArray(sources) ? (sources.map(simKey).includes(k) ? true : null)
      : Object.entries(sources).find(([o]) => simKey(o) === k);
    row.update(byKey.get(k), overrides.includes(k), src === true ? true : src ? src[1] : null);
  }
}

// One object's row: value, control, Set / Override / Release, Source…
function simRow(ref, key, first) {
  const info = simObjInfo(ref, key);
  const type = (first && first.type) || (info && info.type) || "";
  const allow = simAllow();
  const off = { disabled: !allow, title: allow ? null : simNoChanges() };
  const value = el("strong", { dataset: { sim: "value" } });
  const tags = el("span", { class: "od-marks" });
  const input = el("input", Object.assign({ type: "text", class: "od-input", "aria-label": `Value of ${key}`, dataset: { sim: "input" } }, off));
  let slider = null;
  let toggle = null;
  const bits = [];
  const range = SIM_INT_RANGE[type];
  const lo = info && info.low_limit !== undefined ? info.low_limit : range ? range[0] : null;
  const hi = info && info.high_limit !== undefined ? info.high_limit : range ? range[1] : null;
  const control = el("div", { class: "sim-control" });
  const send = async (op, v) => {
    if (v === "" || v === undefined || (typeof v === "number" && Number.isNaN(v))) { banner("Enter a value first.", true); return; }
    const r = await simRequest(op, { node: ref, values: { [key]: v } });
    if (r) banner(`${simRefText(ref)} ${key}: ${op === "sim_set" ? "set to" : "held at"} ${v}${op === "sim_override" ? " until Release" : ""}.`);
  };
  if (type === "BOOLEAN") {
    toggle = el("input", Object.assign({ type: "checkbox", "aria-label": `Switch ${key}`, dataset: { sim: "switch" } }, off));
    toggle.addEventListener("change", () => send("sim_override", toggle.checked ? 1 : 0));
    control.append(el("label", { class: "check" }, toggle, " on"));
  } else if (SIM_BITS[type]) {
    const wrap = el("span", { class: "sim-bits" });
    for (let b = SIM_BITS[type] - 1; b >= 0; b--) {
      const cb = el("input", Object.assign({ type: "checkbox", "aria-label": `${key} bit ${b}`, title: `bit ${b}`, dataset: { simBit: b } }, off));
      cb.addEventListener("change", () => {
        let v = 0;
        for (const x of bits) if (x.checked) v |= 1 << Number(x.dataset.simBit);
        send("sim_override", v >>> 0);
      });
      bits.push(cb);
      wrap.append(cb);
      if (b % 4 === 0 && b) wrap.append(el("span", { class: "sim-bit-gap" }));
    }
    control.append(wrap);
  }
  if (type !== "BOOLEAN" && type !== "VISIBLE_STRING" && (range || /^REAL/.test(type))) {
    let l = lo, h = hi;
    if (l === null || h === null) {
      const cur = first && typeof first.value === "number" ? Math.abs(first.value) : 0;
      h = Math.max(1000, cur * 2);
      l = -h;
    }
    slider = el("input", Object.assign({ type: "range", min: String(l), max: String(h), step: /^REAL/.test(type) ? "any" : "1",
      "aria-label": `Slider ${key}`, dataset: { sim: "slider" } }, off));
    slider.addEventListener("input", () => { input.value = slider.value; });
    slider.addEventListener("change", () => send("sim_override", Number(slider.value)));
    control.append(slider, el("span", { class: "muted" }, `${l} … ${h}${info && (info.low_limit !== undefined || info.high_limit !== undefined) ? " (EDS)" : ""}`));
  }
  const release = el("button", Object.assign({ type: "button", class: "small", dataset: { sim: "release" },
    onclick: async () => { if (await simRequest("sim_release", { node: ref, objects: [key] })) banner(`${simRefText(ref)} ${key}: override released.`); } }, off), "Release");
  const pinned = simPins(ref).includes(key);
  const actions = el("td", { class: "actions" },
    el("button", Object.assign({ type: "button", class: "small", dataset: { sim: "set" }, onclick: () => send("sim_set", simParseValue(input.value)) }, off), "Set"), " ",
    el("button", Object.assign({ type: "button", class: "small", dataset: { sim: "override" }, onclick: () => send("sim_override", simParseValue(input.value)) }, off), "Override"), " ",
    release, " ",
    el("button", Object.assign({ type: "button", class: "small", dataset: { sim: "source" }, onclick: () => { SIM.editing = SIM.editing === key ? null : key; simUpdateValues(); } }, off), "Source…"), " ",
    pinned ? el("button", { type: "button", class: "small", dataset: { sim: "unpin" }, onclick: () => simSetPins(ref, simPins(ref).filter((x) => x !== key)) }, "Unpin") : null);
  const tr = el("tr", { dataset: { simObject: key } },
    el("td", { class: "mono" }, key), el("td", { class: "od-name" }, info ? info.name : "", el("div", { class: "muted" }, type)),
    el("td", { class: "od-value" }, value, tags), el("td", null, control, input), actions);
  const busy = (x) => x && document.activeElement === x;
  return {
    tr, type,
    update(v, overridden, source) {
      if (v && v.error) { value.textContent = v.error; value.classList.add("bad"); return; }
      value.classList.remove("bad");
      const raw = v ? v.value : undefined;
      value.textContent = simValueText(raw, type);
      put(tags, overridden ? el("span", { class: "tag warn-tag", dataset: { sim: "overridden" } }, "override") : null,
        source ? el("span", { class: "tag", dataset: { sim: "sourced" } }, "source: " + (source === true ? "yes" : sourceText(source))) : null,
        pinned ? el("span", { class: "tag" }, "pinned") : null);
      release.disabled = !allow || !overridden;
      if (raw === undefined || raw === null) return;
      if (toggle && !busy(toggle)) toggle.checked = raw === true || Number(raw) !== 0;
      if (bits.length) for (const b of bits) if (!busy(b)) b.checked = !!((Number(raw) >>> Number(b.dataset.simBit)) & 1);
      if (slider && !busy(slider)) slider.value = String(raw);
      if (!busy(input) && !(slider && busy(slider))) input.value = String(raw);
    },
  };
}

function simSourceRow(ref, key, row) {
  const e = simEntry(ref, false);
  const current = e && e.sources ? Object.entries(e.sources).find(([o]) => simKey(o) === key) : null;
  const ed = sourceEditor(current ? simClone(current[1]) : { constant: 0 }, ref);
  const msg = el("span", { class: "field-msg" });
  const apply = async () => {
    let src;
    try { src = ed.value(); } catch (err) { msg.textContent = err.message; return; }
    const r = await simRequest("sim_source", { node: ref, object: key, source: src });
    if (!r) return;
    const entry = simEntry(ref, true);
    if (entry) {
      entry.sources = entry.sources || {};
      for (const o of Object.keys(entry.sources)) if (simKey(o) === key) delete entry.sources[o];
      entry.sources[key] = src;
      simChanged();
    }
    banner(`${simRefText(ref)} ${key}: source ${sourceText(src)} given` + (entry ? ". Save to simulation file to keep it for the next start." : "."));
    SIM.editing = null;
    simUpdateValues();
  };
  const remove = async () => {
    const r = await simRequest("sim_source", { node: ref, object: key, source: null });
    if (!r) return;
    const entry = simEntry(ref, false);
    if (entry && entry.sources) {
      for (const o of Object.keys(entry.sources)) if (simKey(o) === key) delete entry.sources[o];
      simTidy(ref);
      simChanged();
    }
    banner(`${simRefText(ref)} ${key}: source removed.`);
    SIM.editing = null;
    simUpdateValues();
  };
  return el("tr", { class: "sim-source-row", dataset: { simSourceFor: key } }, el("td", { colspan: 5 },
    el("div", { class: "sim-form" }, el("strong", null, `Value source of ${key}`), ed.el,
      el("div", { class: "toolbar" },
        el("button", { type: "button", class: "primary", dataset: { sim: "apply-source" }, onclick: apply }, "Apply"),
        el("button", { type: "button", dataset: { sim: "remove-source" }, onclick: remove }, "Remove source"),
        el("button", { type: "button", onclick: () => { SIM.editing = null; simUpdateValues(); } }, "Cancel"), msg))));
}

// ---------------------------------------------------------------------------
// Editors shared by the tabs: value sources, faults, expressions, conditions

function simInput(label, value, data, opts) {
  opts = opts || {};
  const input = el("input", { type: "text", spellcheck: "false", "aria-label": label, placeholder: opts.placeholder,
    class: opts.cls, dataset: { simField: data } });
  input.value = value === undefined || value === null ? "" : String(value);
  if (opts.onInput) input.addEventListener("input", () => opts.onInput(input.value));
  return [el("label", null, label, input), input];
}

// An expression field, checked as the user types: by the simulator when
// connected, else on this PC.
function exprField(label, value, node, onInput) {
  const input = el("input", { type: "text", spellcheck: "false", class: "mono sim-expr", "aria-label": label, dataset: { simField: "expr" } });
  input.value = value || "";
  const msg = el("div", { class: "sim-expr-msg", dataset: { sim: "expr-msg" } });
  let timer = null;
  let seq = 0;
  const check = async () => {
    const text = input.value;
    const mine = ++seq;
    if (!text.trim()) { put(msg); return; }
    let r;
    try {
      r = await api("POST", "/api/sim/check_expr", { node: node === undefined || node === "" ? null : node, expr: text, online: SIM.connected,
        port: diagPort(), doc: SIM.doc });
    } catch (e) { if (mine === seq) put(msg, el("span", { class: "field-msg" }, e.message)); return; }
    if (mine !== seq) return;
    if (!r.checked) {
      put(msg, el("span", { class: "muted", dataset: { sim: "expr-unchecked" } }, "Not checked: connect to the simulated devices to check expressions as you type; the simulator checks it again when it is given."));
    } else if (r.ok) {
      put(msg, el("span", { class: "ok-text", dataset: { sim: "expr-ok" } }, "The expression is valid."));
    } else {
      const pos = Number.isInteger(r.position) ? r.position : null;
      put(msg, el("span", { class: "field-msg", dataset: { sim: "expr-error", position: pos === null ? "" : String(pos) } },
        pos === null ? r.error : `At position ${pos}: ${r.error}`),
      pos === null ? null : el("pre", { class: "sim-caret mono" }, text + "\n" + " ".repeat(Math.max(0, pos)) + "^"));
    }
  };
  input.addEventListener("input", () => {
    if (onInput) onInput(input.value);
    clearTimeout(timer);
    timer = setTimeout(check, 250);
  });
  if (input.value) setTimeout(check, 0);
  return el("label", { class: "span2 sim-expr-field" }, label, input, msg);
}

// A value source form: { el, value() } where value() throws a message.
function sourceEditor(src, node) {
  src = src && typeof src === "object" ? src : { constant: 0 };
  let type = SOURCE_TYPES.map((x) => x[0]).find((k) => k in src) || "constant";
  const box = el("div", { class: "sim-source" });
  const sel = el("select", { "aria-label": "Source type", dataset: { sim: "source-type" } }, SOURCE_TYPES.map(([k, label]) => el("option", { value: k }, label)));
  sel.value = type;
  const fields = el("div", { class: "grid" });
  const [noiseL, noise] = simInput("Noise (±)", src.noise, "noise", { placeholder: "none" });
  const [tickL, tick] = simInput("Tick (ms)", src.tick_ms, "tick_ms", { placeholder: "the device's" });
  let get = () => ({});
  const draw = () => {
    const p = src[type] !== undefined ? src[type] : {};
    const inputs = {};
    const parts = [];
    if (type === "constant") {
      const [l, i] = simInput("Value", typeof p === "object" ? "" : p, "constant");
      parts.push(l);
      get = () => { if (!i.value.trim()) throw new Error("Give the value."); return simParseValue(i.value); };
    } else if (type === "expr") {
      let text = typeof p === "string" ? p : "";
      parts.push(exprField("Expression", text, node, (v) => { text = v; }));
      get = () => { if (!text.trim()) throw new Error("Give the expression."); return text; };
    } else if (type === "steps") {
      const v = (p.values || []).map((x) => x.join(" ")).join(", ");
      const [l, i] = simInput("Values: value duration_s, …", v, "steps", { placeholder: "0 2, 100 5" });
      const rep = el("input", { type: "checkbox", dataset: { simField: "repeat" } });
      rep.checked = p.repeat !== false;
      parts.push(l, el("label", { class: "check" }, rep, " Repeat"));
      get = () => {
        const values = i.value.split(",").map((x) => x.trim()).filter(Boolean).map((x) => {
          const [a, b] = x.split(/\s+/);
          return [simNum(a, "step value"), simNum(b, "step duration")];
        });
        if (!values.length) throw new Error("Give at least one step as: value duration_s.");
        const out = { values };
        if (!rep.checked) out.repeat = false;
        return out;
      };
    } else {
      if (type === "csv") {
        const [l, i] = simInput("File (relative to simulation.json)", p.file, "file", { placeholder: "data/temp.csv" });
        inputs.file = i;
        parts.push(l);
      }
      for (const [k, label, req] of SOURCE_FIELDS[type] || []) {
        const [l, i] = simInput(label + (req ? "" : " (optional)"), p[k], k);
        inputs[k] = [i, req];
        parts.push(l);
      }
      let then = null, interp = null, loop = null;
      if (type === "ramp") {
        then = el("select", { "aria-label": "Then", dataset: { simField: "then" } }, [["hold", "hold"], ["repeat", "repeat"], ["reverse", "reverse"]].map(([k, l]) => el("option", { value: k }, l)));
        then.value = p.then || "hold";
        parts.push(el("label", null, "Then", then));
      }
      if (type === "csv") {
        interp = el("select", { "aria-label": "Interpolate", dataset: { simField: "interpolate" } }, ["linear", "step"].map((k) => el("option", { value: k }, k)));
        interp.value = p.interpolate || "linear";
        loop = el("input", { type: "checkbox", dataset: { simField: "loop" } });
        loop.checked = !!p.loop;
        parts.push(el("label", null, "Interpolate", interp), el("label", { class: "check" }, loop, " Loop"));
      }
      get = () => {
        const out = {};
        if (type === "csv") {
          if (!inputs.file.value.trim()) throw new Error("Give the CSV file.");
          out.file = inputs.file.value.trim();
        }
        for (const [k, label] of SOURCE_FIELDS[type] || []) {
          const [i, req] = inputs[k];
          const v = k === "column" ? simInt(i.value, label.toLowerCase(), !req, 1) : simNum(i.value, label.toLowerCase(), !req);
          if (v !== undefined) out[k] = v;
        }
        if (then && then.value !== "hold") out.then = then.value;
        if (interp && interp.value !== "linear") out.interpolate = interp.value;
        if (loop && loop.checked) out.loop = true;
        return out;
      };
    }
    put(fields, el("label", null, "Type", sel), parts, noiseL, tickL);
  };
  sel.addEventListener("change", () => { type = sel.value; draw(); });
  draw();
  box.append(fields);
  return {
    el: box,
    value() {
      const out = { [type]: get() };
      const n = simNum(noise.value, "noise", true);
      if (n !== undefined) out.noise = n;
      const t = simInt(tick.value, "tick", true, 1, 60000);
      if (t !== undefined) out.tick_ms = t;
      return out;
    },
  };
}

// The fields of one fault kind: { el, value() } (value() throws a message).
function faultFields(kind, f, ref) {
  f = f || {};
  const box = el("div", { class: "grid" });
  if (FAULT_FIXED[kind]) return { el: box, value: () => simClone(FAULT_FIXED[kind]) };
  const p = f[kind] || {};
  if (kind === "emcy") {
    const [cl, code] = simInput("Error code", p.code, "code", { placeholder: "0x5000" });
    const [rl, reg] = simInput("Error register", p.register, "register", { placeholder: "0" });
    const [ml, msef] = simInput("Manufacturer bytes (10 hex digits)", p.msef, "msef", { placeholder: "0000000000" });
    const [pl, period] = simInput("Repeat every (ms)", p.period_ms, "period_ms", { placeholder: "once" });
    box.append(cl, rl, ml, pl);
    return { el: box, value() {
      const out = { code: simCode(code.value, "error code") };
      const r = simCode(reg.value, "error register", true);
      if (r !== undefined) out.register = typeof r === "number" && r > 255 ? (() => { throw new Error("The error register is one byte (0-255)."); })() : r;
      if (msef.value.trim()) {
        if (!/^[0-9a-f]{10}$/i.test(msef.value.trim())) throw new Error("Give the manufacturer bytes as 10 hex digits.");
        out.msef = msef.value.trim();
      }
      const per = simInt(period.value, "period", true, 10, 3600000);
      if (per !== undefined) out.period_ms = per;
      return { emcy: out };
    } };
  }
  if (kind === "power_cycle") {
    const [l, i] = simInput("Off for (ms)", f.off_ms, "off_ms", { placeholder: "1000" });
    box.append(l);
    return { el: box, value() { const v = simInt(i.value, "off time", true, 1, 3600000); return v === undefined ? { power: "cycle" } : { power: "cycle", off_ms: v }; } };
  }
  if (kind === "nmt_state") {
    const sel = el("select", { "aria-label": "NMT state", dataset: { simField: "nmt_state" } }, [["stopped", "STOPPED"], ["preop", "PRE-OPERATIONAL"], ["operational", "OPERATIONAL"]].map(([k, l]) => el("option", { value: k }, l)));
    if (f.nmt_state) sel.value = f.nmt_state;
    box.append(el("label", null, "State", sel));
    return { el: box, value: () => ({ nmt_state: sel.value }) };
  }
  if (kind === "sdo_abort") {
    const [ol, obj] = simInput("Object", p.object, "object", { placeholder: "0x2000:1" });
    const [cl, code] = simInput("Abort code", p.code, "code", { placeholder: "0x08000020" });
    const on = el("select", { "aria-label": "On", dataset: { simField: "on" } }, ["both", "read", "write"].map((k) => el("option", { value: k }, k)));
    on.value = p.on || "both";
    const [nl, count] = simInput("Times", p.count, "count", { placeholder: "until cleared" });
    box.append(ol, cl, el("label", null, "On", on), nl);
    return { el: box, value() {
      if (!obj.value.trim()) throw new Error("Give the object.");
      const out = { object: simKey(obj.value), code: simCode(code.value, "abort code") };
      if (on.value !== "both") out.on = on.value;
      const c = simInt(count.value, "count", true, 1);
      if (c !== undefined) out.count = c;
      return { sdo_abort: out };
    } };
  }
  if (kind === "sdo_delay") {
    const [ml, ms] = simInput("Delay (ms)", p.ms, "ms", { placeholder: "500" });
    const [ol, obj] = simInput("Object (optional)", p.object, "object", { placeholder: "all" });
    box.append(ml, ol);
    return { el: box, value() {
      const out = { ms: simInt(ms.value, "delay", false, 1, 60000) };
      if (obj.value.trim()) out.object = simKey(obj.value);
      return { sdo_delay: out };
    } };
  }
  if (kind === "tpdo_stop") {
    const [l, i] = simInput("TPDO number", f.tpdo_stop, "tpdo", { placeholder: "1" });
    box.append(l);
    return { el: box, value: () => ({ tpdo_stop: simInt(i.value, "TPDO number", false, 1, 512) }) };
  }
  if (kind === "identity") {
    const inputs = IDENTITY_KEYS.map(([k, label]) => { const [l, i] = simInput(label, p[k], k, { placeholder: "as in the EDS" }); box.append(l); return [k, label, i]; });
    return { el: box, value() {
      const out = {};
      for (const [k, label, i] of inputs) { const v = simCode(i.value, label.toLowerCase(), true); if (v !== undefined) out[k] = v; }
      if (!Object.keys(out).length) throw new Error("Give at least one identity value.");
      return { identity: out };
    } };
  }
  if (kind === "device_type") {
    const [l, i] = simInput("Device type (0x1000)", f.device_type, "device_type", { placeholder: "0x00000191" });
    box.append(l);
    return { el: box, value: () => ({ device_type: simCode(i.value, "device type") }) };
  }
  if (kind === "drive_input") {
    const boxes = DRIVE_INPUTS.map(([k, label]) => {
      const cb = el("input", { type: "checkbox", dataset: { simField: k } });
      cb.checked = !!p[k];
      box.append(el("label", { class: "check" }, cb, " " + label));
      return [k, cb];
    });
    return { el: box, value() { const out = {}; for (const [k, cb] of boxes) out[k] = cb.checked; return { drive_input: out }; } };
  }
  return { el: box, value() { throw new Error("Unknown fault " + kind); } };
}

// The fault kind of a fault object, as FAULT_KINDS names it.
function faultKind(f) {
  const k = faultName(f);
  if (k === "power") return f.power === "cycle" ? "power_cycle" : f.power === "off" ? "power_off" : "power_on";
  if (k === "reset") return f.reset === "comm" ? "reset_comm" : "reset_node";
  return k;
}

// ---------------------------------------------------------------------------
// The simulation file tab

function simChanged() {
  simShowFileState();
  clearTimeout(SIM.checkTimer);
  SIM.checkTimer = setTimeout(simCheck, 300);
}

async function simCheck() {
  try {
    const r = await api("POST", "/api/sim/check", { doc: simFileOut() });
    SIM.problems = r.problems || [];
  } catch (e) { return; }
  simShowFileState();
  simShowProblems();
}

// Problems at paths of the part the view shows: a version 2 file's paths
// lose the shown section's "networks.NAME." in front; other sections'
// problems show in the file-wide box only.
function simLocalProblems() {
  if (simVersion() < 2) return SIM.problems;
  const own = "networks." + simSectionName();
  return SIM.problems.map((p) => {
    if (p.path === own) return Object.assign({}, p, { path: "" });
    if (p.path.startsWith(own + ".")) return Object.assign({}, p, { path: p.path.slice(own.length + 1) });
    return Object.assign({}, p, { other: true });
  });
}

function simShowProblems() {
  const problems = simLocalProblems();
  for (const box of document.querySelectorAll("[data-sim-problems]")) {
    const prefix = box.dataset.simProblems;
    const list = problems.filter((p) => !p.other || !prefix).filter((p) => !prefix || p.path === prefix || p.path.startsWith(prefix + ".") || p.path.startsWith(prefix + "["));
    put(box, list.length ? el("ul", { class: "sim-problems" }, list.map((p) => el("li", { class: "field-msg" }, (p.path ? p.path + ": " : "") + p.message))) : null);
  }
}

async function simSave(overwrite) {
  if (SIM.converted !== null && SIM.converted !== undefined && !overwrite) {
    const v = await modal(`simulation.json is a version 1 file, which a configuration with several networks does not use. ` +
      `Save it as version 2, with its content in the section of network ${SIM.converted}?`,
      [["convert", "Save as version 2", true], ["cancel", "Cancel"]]);
    if (v !== "convert") return;
  }
  try {
    const r = await api("POST", "/api/sim/save", { doc: simFileOut(), overwrite: !!overwrite });
    S.state = r.state;
    SIM.saved = simFileText();
    SIM.converted = null;
    SIM.problems = [];
    banner("Saved " + r.written.join(", ") + ". The next simulated start uses it.");
    renderSide();
    simShowFileState();
    simShowProblems();
  } catch (e) {
    if (e.status === 409 && e.body.changed_on_disk) {
      const v = await modal("simulation.json changed on disk after it was loaded here (edited elsewhere?).",
        [["cancel", "Cancel"], ["reload", "Reload from disk"], ["overwrite", "Overwrite it", { danger: true }]]);
      if (v === "overwrite") return simSave(true);
      if (v === "reload") return reload(true);
    } else if (e.status === 422 && e.body.problems) {
      SIM.problems = e.body.problems;
      simShowFileState();
      simShowProblems();
      banner(e.message, true);
    } else banner(e.message, true);
  }
}

function simFileTab() {
  const refs = [];
  for (const n of S.config.nodes || []) if (Number.isInteger(num(n.node_id))) refs.push([num(n.node_id), n]);
  const extra = SIM.doc.extra_devices || [];
  const tick = el("input", { type: "text", class: "short", placeholder: "10", "aria-label": "Tick (ms)", dataset: { simField: "file-tick" } });
  tick.value = SIM.file.tick_ms === undefined ? "" : String(SIM.file.tick_ms);
  tick.addEventListener("input", () => {
    const t = tick.value.trim();
    if (!t) delete SIM.file.tick_ms; else SIM.file.tick_ms = /^\d+$/.test(t) ? Number(t) : t;
    simChanged();
  });
  return el("div", null,
    el("p", { class: "muted" }, "What the simulated devices do from the start, saved in simulation.json next to canworks.json. Sources given on the Live values tab land here too. Nothing here needs a connection."),
    simVersion() >= 2 ? el("p", { class: "muted", dataset: { sim: "file-section" } },
      `Network ${simSectionName()}: this is its section of the file (version 2, one section per network). The tick is shared by all networks.`) : null,
    el("div", { dataset: { simProblems: "" } }),
    el("div", { class: "toolbar" }, el("label", { class: "inline" }, "Tick (ms) ", tick), hint("How often sources and models run, 1-60000 ms (default 10).")),
    refs.map(([id, n]) => simDeviceFile(id, `Node ${id} ${n.name || ""}`, nodeSimulated(n) ? null : "not simulated in this configuration: the entry is kept and does nothing")),
    extra.map((d) => simDeviceFile(d.node ? d.node : d.name, `Extra device ${d.node ? d.node : "without node ID"} ${d.name || ""}`, null)),
    simExtraDevices(),
    simRawDevices());
}

// The plain CAN devices of the file (raw_devices) on the shown network:
// what each sends and answers. They are edited in simulation.json
// (docs/simulator.md, "Plain CAN devices"); scenarios stop them or change
// their DLC with "device" steps.
function simRawDevices() {
  const name = simSectionName();
  const mine = (SIM.file.raw_devices || []).filter((d) => d && (!d.network || d.network === name || !several()));
  if (!mine.length) return null;
  const hex = (id, ext) => "0x" + Number(id).toString(16).toUpperCase().padStart(ext ? 8 : 3, "0");
  const rows = mine.map((d) => {
    const sends = (d.send || []).map((m) => `${m.name ? m.name + " " : ""}${hex(m.id, m.extended)} every ${m.period_ms} ms` +
      ((m.signals || []).length ? ` (${m.signals.map((g) => g.name || "bit " + g.start_bit).join(", ")})` : ""));
    const replies = (d.replies || []).map((r) => `answers ${hex(r.on.id, r.on.extended)} with ${hex(r.send.id, r.send.extended)}`);
    return el("tr", { dataset: { simRaw: d.name } }, el("td", null, d.name), el("td", null, sends.join("; ") || "-"),
      el("td", null, replies.join("; ") || "-"));
  });
  return el("fieldset", { dataset: { sim: "raw-devices" } }, el("legend", null, "Plain CAN devices"),
    el("p", { class: "muted" }, "Devices without CANopen that send frames and answer requests, from raw_devices in simulation.json. " +
      "A scenario stops one with {\"device\": NAME, \"fault\": {\"stop\": true}} or changes its frames' length with {\"wrong_dlc\": N}."),
    el("table", { class: "online-nodes" },
      el("thead", null, el("tr", null, el("th", null, "Device"), el("th", null, "Sends"), el("th", null, "Replies"))),
      el("tbody", null, rows)));
}

function simDeviceFile(ref, title, note) {
  const box = el("fieldset", { dataset: { simFile: String(ref) } });
  const draw = () => {
    const cur = simEntry(ref, false) || {};
    const dflt = el("input", { type: "checkbox", dataset: { simField: "default_behaviour" } });
    dflt.checked = cur.default_behaviour !== false;
    dflt.addEventListener("change", () => {
      const entry = simEntry(ref, true);
      if (dflt.checked) delete entry.default_behaviour; else entry.default_behaviour = false;
      simTidy(ref);
      simChanged();
    });
    const sources = Object.entries(cur.sources || {});
    const faults = cur.faults || [];
    const profile = simProfile(ref);
    const srcBox = el("div");
    const faultBox = el("div");
    put(box, el("legend", null, title), note ? el("p", { class: "muted" }, note) : null,
      el("div", { class: "check-field" }, el("label", { class: "check" }, dflt, " Default behaviour"),
        hint(profile === 401 ? "CiA 401: outputs loop back to inputs." : profile === 404 ? "CiA 404: mapped inputs move slowly (a sine)." : profile === 402 ? "CiA 402: the drive model." : "This device's profile has no default behaviour.")),
      el("h3", null, "Value sources"),
      sources.length ? el("table", { class: "od" }, el("tbody", null, sources.map(([o, s]) => el("tr", { dataset: { simFileSource: o } },
        el("td", { class: "mono" }, o), el("td", null, (simObjInfo(ref, simKey(o)) || {}).name || ""), el("td", null, sourceText(s)),
        el("td", { class: "actions" },
          el("button", { type: "button", class: "small", onclick: () => simEditFileSource(ref, o, srcBox, draw) }, "Edit"), " ",
          el("button", { type: "button", class: "small", dataset: { sim: "remove-file-source" }, onclick: () => {
            delete simEntry(ref, false).sources[o];
            simTidy(ref);
            simChanged();
            draw();
          } }, "Remove")))))) : el("p", { class: "muted" }, "None."),
      simAddFileSource(ref, srcBox, draw), srcBox,
      el("h3", null, "Faults at start"),
      faults.length ? el("ul", { class: "sim-faults" }, faults.map((f, k) => el("li", null, faultText(f), " ",
        el("button", { type: "button", class: "small", onclick: () => { simEntry(ref, false).faults.splice(k, 1); simTidy(ref); simChanged(); draw(); } }, "Remove")))) : el("p", { class: "muted" }, "None."),
      simAddFileFault(ref, faultBox, draw), faultBox,
      profile === 402 ? simDriveFields(ref) : null);
  };
  draw();
  return box;
}

function simAddFileSource(ref, target, redraw) {
  const eds = simEds(ref);
  const objects = eds && eds.objects ? eds.objects.filter((o) => o.type) : [];
  const pick = el("select", { "aria-label": "Object", dataset: { sim: "file-source-object" } }, el("option", { value: "" }, "Object…"),
    objects.map((o) => el("option", { value: simKey(`${o.index}:${o.subindex}`) }, `${o.index}:${o.subindex} ${o.name}`)));
  const typed = el("input", { type: "text", class: "index", placeholder: "0x6401:1", "aria-label": "Object", dataset: { sim: "file-source-typed" } });
  return el("div", { class: "toolbar" }, pick, typed, el("button", { type: "button", dataset: { sim: "add-file-source" }, onclick: () => {
    const key = simKey(typed.value.trim() || pick.value);
    if (!/^0x[0-9A-F]{4}:\d+$/.test(key)) { banner("Pick an object, or type it as 0xIIII:S.", true); return; }
    simEditFileSource(ref, key, target, redraw);
  } }, "Add source…"));
}

function simEditFileSource(ref, key, target, redraw) {
  const cur = simEntry(ref, false);
  const ed = sourceEditor(cur && cur.sources && cur.sources[key] ? simClone(cur.sources[key]) : { sine: {} }, ref);
  const msg = el("span", { class: "field-msg" });
  put(target, el("div", { class: "sim-form" }, el("strong", null, `Value source of ${key}`), ed.el, el("div", { class: "toolbar" },
    el("button", { type: "button", class: "primary", dataset: { sim: "keep-source" }, onclick: () => {
      let src;
      try { src = ed.value(); } catch (e) { msg.textContent = e.message; return; }
      const entry = simEntry(ref, true);
      entry.sources = entry.sources || {};
      entry.sources[key] = src;
      simChanged();
      redraw();
    } }, "Keep"),
    el("button", { type: "button", onclick: () => put(target) }, "Cancel"), msg)));
}

function simAddFileFault(ref, target, redraw) {
  const sel = el("select", { "aria-label": "Fault", dataset: { sim: "file-fault-kind" } }, el("option", { value: "" }, "Fault…"),
    FAULT_KINDS.map(([k, label]) => el("option", { value: k }, label.replace("…", ""))));
  sel.addEventListener("change", () => {
    if (!sel.value) { put(target); return; }
    const f = faultFields(sel.value, null, ref);
    const msg = el("span", { class: "field-msg" });
    put(target, el("div", { class: "sim-form" }, f.el, el("div", { class: "toolbar" },
      el("button", { type: "button", class: "primary", dataset: { sim: "add-file-fault" }, onclick: () => {
        let fault;
        try { fault = f.value(); } catch (e) { msg.textContent = e.message; return; }
        const entry = simEntry(ref, true);
        entry.faults = entry.faults || [];
        entry.faults.push(fault);
        simChanged();
        redraw();
      } }, "Add"), msg)));
  });
  return el("div", { class: "toolbar" }, sel);
}

function simDriveFields(ref) {
  const cur = (simEntry(ref, false) || {}).drive || {};
  return el("div", null, el("h3", null, "Drive model"), el("div", { class: "grid" }, DRIVE_FIELDS.map(([k, label, dflt]) => {
    const [l, i] = simInput(label, cur[k], "drive-" + k, { placeholder: dflt });
    i.addEventListener("input", () => {
      const entry = simEntry(ref, true);
      entry.drive = entry.drive || {};
      const t = i.value.trim();
      if (!t) delete entry.drive[k]; else entry.drive[k] = /^-?\d+(\.\d+)?$/.test(t) ? Number(t) : t;
      simTidy(ref);
      simChanged();
    });
    return l;
  }), simWatchdogField(ref, cur)));
}

// "sync_watchdog": false switches the drive's SYNC watchdog off (cyclic modes).
function simWatchdogField(ref, cur) {
  const box = el("input", { type: "checkbox", dataset: { sim: "drive-sync_watchdog" } });
  box.checked = cur.sync_watchdog !== false;
  box.addEventListener("change", () => {
    const entry = simEntry(ref, true);
    entry.drive = entry.drive || {};
    if (box.checked) delete entry.drive.sync_watchdog; else entry.drive.sync_watchdog = false;
    simTidy(ref);
    simChanged();
  });
  return el("label", null, box, " SYNC watchdog (cyclic modes)");
}

function simExtraDevices() {
  const list = SIM.doc.extra_devices || [];
  const edsSel = el("select", { "aria-label": "EDS file", dataset: { sim: "extra-eds" } },
    el("option", { value: "" }, "EDS file…"), (S.state.sim_eds || []).map((n) => el("option", { value: n }, n)));
  const file = el("input", { type: "file", accept: ".eds,.EDS,.dcf,.DCF", dataset: { sim: "extra-file" } });
  file.addEventListener("change", async () => {
    const f = file.files[0];
    file.value = "";
    if (!f) return;
    try {
      const data = await fileBase64(f);
      const res = await api("POST", "/api/eds", { name: f.name, data, on_conflict: "keep_both", eds_lint: edsLint() });
      S.state.eds = S.state.eds || {};
      S.state.eds[res.name] = res.summary;
      S.state.sim_eds = (S.state.sim_eds || []).concat([res.name]);
      edsSel.append(el("option", { value: res.name }, res.name));
      edsSel.value = res.name;
      banner(`${res.name} is ready for the extra device; it is written to the config folder with the simulation file.`);
    } catch (e) { banner(e.message, true); }
  });
  const [nl, node] = simInput("Node ID", "", "extra-node", { placeholder: "0: none (waits for LSS)" });
  const [ml, name] = simInput("Name", "", "extra-name", { placeholder: "needed without node ID" });
  const msg = el("span", { class: "field-msg" });
  const add = () => {
    msg.textContent = "";
    let id;
    try { id = simInt(node.value, "node ID", true, 0, 127) || 0; } catch (e) { msg.textContent = e.message; return; }
    const nm = name.value.trim();
    if (!edsSel.value) { msg.textContent = "Pick the EDS file."; return; }
    if (!id && !nm) { msg.textContent = "A device without node ID needs a name."; return; }
    if (nm && !/^[A-Za-z][A-Za-z0-9_-]{0,31}$/.test(nm)) { msg.textContent = "The name starts with a letter and has letters, digits, _ and - only (up to 32)."; return; }
    if (id && ((S.config.nodes || []).some((n) => num(n.node_id) === id) || list.some((d) => d.node === id))) { msg.textContent = `Node ID ${id} is already used.`; return; }
    const d = { node: id };
    if (nm) d.name = nm;
    d.eds = edsSel.value;
    SIM.doc.extra_devices = list.concat([d]);
    simChanged();
    banner(`Extra device ${id || nm} added. Save to simulation file; it takes effect at the next start of the simulation.`);
    simRenderTab();
  };
  return el("fieldset", { dataset: { sim: "extra-devices" } }, el("legend", null, "Extra devices"),
    el("p", { class: "muted" }, "Devices simulated without being in the configuration: to try a bus scan, LSS commissioning or an identity check. They are saved to the simulation file and take effect at the next start of the simulation."),
    list.length ? el("table", { class: "od" }, el("thead", null, el("tr", null, thCells(["Node ID", "Name", "EDS", ""]))),
      el("tbody", null, list.map((d, k) => el("tr", { dataset: { simExtra: String(k) } }, el("td", null, d.node ? String(d.node) : "none"),
        el("td", null, d.name || ""), el("td", null, d.eds || ""),
        el("td", null, el("button", { type: "button", class: "small", dataset: { sim: "remove-extra" }, onclick: () => {
          SIM.doc.extra_devices.splice(k, 1);
          if (!SIM.doc.extra_devices.length) delete SIM.doc.extra_devices;
          simChanged();
          simRenderTab();
        } }, "Remove")))))) : el("p", { class: "muted" }, "None."),
    el("div", { class: "grid" }, el("label", null, "EDS", edsSel, el("span", { class: "file-button small-file" }, "Pick EDS file… ", file)), nl, ml),
    el("div", { class: "toolbar" }, el("button", { type: "button", dataset: { sim: "add-extra" }, onclick: add }, "Add extra device"), msg));
}

// ---------------------------------------------------------------------------
// Scenarios

function simScenarios() { return SIM.doc.scenarios || {}; }

function simSavedScenario(name) {
  try {
    const saved = JSON.parse(SIM.saved);
    const part = simVersion() >= 2 ? (saved.networks || {})[simSectionName()] || {} : saved;
    return (part.scenarios || {})[name];
  } catch (e) { return undefined; }
}

function simScenariosTab() {
  const nameIn = el("input", { type: "text", spellcheck: "false", placeholder: "sensor-break", "aria-label": "New scenario name", dataset: { sim: "new-scenario" } });
  const create = () => {
    const name = nameIn.value.trim();
    if (!SCENARIO_NAME.test(name)) { banner("A scenario name starts with a letter or digit and has letters, digits, _, . and - only (up to 64).", true); return; }
    if (simScenarios()[name]) { banner(`There is already a scenario ${name}.`, true); return; }
    SIM.doc.scenarios = Object.assign({}, simScenarios(), { [name]: { steps: [] } });
    SIM.scenario = name;
    simChanged();
    simRenderTab();
  };
  return el("div", null,
    el("table", { class: "online-nodes", dataset: { sim: "scenarios" } },
      el("thead", null, el("tr", null, thCells(["Scenario", "In file", "State", "Step", "Time", "Result", ""]))),
      el("tbody", { id: "sim-scenario-rows" })),
    el("div", { class: "toolbar" }, nameIn, el("button", { type: "button", dataset: { sim: "create-scenario" }, onclick: create }, "New scenario")),
    el("div", { id: "sim-scenario-editor" }, SIM.scenario && simScenarios()[SIM.scenario] ? simScenarioEditor(SIM.scenario) : null));
}

function simRunState(name, live) {
  const run = SIM.runs[name] || (SIM.runs[name] = { state: null, start: null, end: null });
  const state = live ? live.state : null;
  if (state === "running" && run.state !== "running") { run.start = Date.now(); run.end = null; }
  if (state && state !== "running" && run.state === "running") run.end = Date.now();
  run.state = state;
  if (live && typeof live.elapsed_ms === "number") return live.elapsed_ms / 1000;
  if (!run.start) return null;
  return ((run.end || Date.now()) - run.start) / 1000;
}

function simUpdateScenarios() {
  const tb = $("#sim-scenario-rows");
  if (!tb) return;
  const live = ((SIM.last && SIM.last.status) || {}).scenarios || [];
  const names = [...new Set(Object.keys(simScenarios()).concat(live.map((x) => x.name)))].sort();
  const connected = SIM.connected;
  const allow = simAllow();
  const rows = names.map((name) => {
    const st = live.find((x) => x.name === name) || null;
    const elapsed = simRunState(name, st);
    const draft = simScenarios()[name];
    const saved = simSavedScenario(name);
    const inFile = draft ? (saved === undefined ? "not saved yet" : JSON.stringify(saved) === JSON.stringify(draft) ? "yes" : "edited, not saved") : "no";
    const state = st ? SIM_STATES[st.state] || st.state : "";
    const result = st && (st.state === "failed" || st.state === "passed" || st.message)
      ? [st.message || "", st.condition ? ` Condition: ${typeof st.condition === "string" ? st.condition : JSON.stringify(st.condition)}.` : "",
        st.value !== undefined ? ` Value seen: ${st.value}.` : ""].join("") : "";
    const stepText = st && st.step !== undefined && st.step !== null ? simStepLabel(draft, st.step) : "";
    return { name, inFile, state, stateClass: st && st.state === "failed" ? "bad" : st && st.state === "passed" ? "ok-text" : null,
      step: stepText, time: elapsed === null ? "" : elapsed.toFixed(1) + " s", result, running: st && st.state === "running", draft: !!draft };
  });
  // The times change every poll; they are written in place, so the buttons stay.
  const sig = JSON.stringify([rows.map((r) => Object.assign({}, r, { time: undefined })), connected, allow, SIM.scenario]);
  if (sig === SIM.scenSig) {
    for (const r of rows) {
      const cell = tb.querySelector(`tr[data-sim-scenario="${CSS.escape(r.name)}"] [data-sim="scenario-time"]`);
      if (cell) cell.textContent = r.time;
    }
    return;
  }
  SIM.scenSig = sig;
  const off = !connected || !allow;
  const why = !connected ? "Connect to the simulated devices to run scenarios." : simNoChanges();
  tb.replaceChildren(...(rows.length ? rows.map((r) => el("tr", { dataset: { simScenario: r.name }, class: r.name === SIM.scenario ? "active" : null },
    el("td", null, r.name), el("td", null, r.inFile), el("td", { class: r.stateClass, dataset: { sim: "scenario-state" } }, r.state),
    el("td", { dataset: { sim: "scenario-step" } }, r.step), el("td", { dataset: { sim: "scenario-time" } }, r.time),
    el("td", { class: r.stateClass === "bad" ? "bad" : null, dataset: { sim: "scenario-result" } }, r.result),
    el("td", { class: "actions" },
      r.draft ? el("button", { type: "button", class: "small", dataset: { sim: "edit-scenario" }, onclick: () => { SIM.scenario = r.name; simRenderTab(); } }, "Edit") : null, " ",
      el("button", { type: "button", class: "small", disabled: off || r.running, title: off ? why : null, dataset: { sim: "start-scenario" }, onclick: () => simStartScenario(r.name) }, "Start"), " ",
      el("button", { type: "button", class: "small", disabled: off || !r.running, title: off ? why : null, dataset: { sim: "stop-scenario" },
        onclick: () => simRequest("sim_scenario_stop", { name: r.name }, `Scenario ${r.name} stopped.`) }, "Stop"), " ",
      r.draft ? el("button", { type: "button", class: "small", dataset: { sim: "delete-scenario" }, onclick: async () => {
        const v = await modal(`Delete the scenario ${r.name} from the simulation file? It is gone once you save.`, [["cancel", "Keep the scenario"], ["delete", "Delete", { danger: true }]]);
        if (v !== "delete") return;
        delete SIM.doc.scenarios[r.name];
        if (!Object.keys(SIM.doc.scenarios).length) delete SIM.doc.scenarios;
        if (SIM.scenario === r.name) SIM.scenario = null;
        simChanged();
        simRenderTab();
      } }, "Delete") : null)))
    : [el("tr", null, el("td", { colspan: 7, class: "muted" }, "No scenarios yet."))]));
}

// "3: wait 5/0x6200:1 bit 2 = 1" for a running step (1-based), when the
// draft has it.
function simStepLabel(sc, step) {
  const steps = sc && sc.steps;
  const k = Number(step);
  if (!steps || !Number.isInteger(k) || k < 1 || k > steps.length) return String(step);
  return `${k} of ${steps.length}: ${simStepText(steps[k - 1])}`;
}

function simStepText(st) {
  const a = STEP_ACTIONS.map((x) => x[0]).find((k) => k in st) || "?";
  const v = st[a];
  const node = st.node !== undefined ? ` ${simRefText(st.node)}` : "";
  if (a === "set" || a === "override") return `${a}${node} ` + Object.entries(v || {}).map(([o, x]) => `${o} = ${x}`).join(", ");
  if (a === "wait" || a === "expect") return `${a} ${simCondText(v)}`;
  if (a === "fault") return `fault${node} ${faultText(v)}`;
  if (a === "log") return `log "${v}"`;
  if (a === "repeat") return `repeat ${v.count || "forever"} × ${(v.steps || []).length} steps`;
  return `${a}${node} ${typeof v === "string" ? v : Array.isArray(v) ? v.join(", ") : Object.keys(v || {}).join(", ")}`;
}

function simCondText(c) {
  if (!c) return "";
  if (c.expr) return c.expr;
  const op = COND_OPS.find(([k]) => k in c);
  return `${c.node}/${c.object}${c.bit !== undefined ? ` bit ${c.bit}` : ""} ${op ? op[1] + " " + c[op[0]] : ""}`;
}

async function simStartScenario(name) {
  const draft = simScenarios()[name];
  const saved = simSavedScenario(name);
  const fields = { name };
  if (draft && JSON.stringify(draft) !== JSON.stringify(saved)) fields.scenario = simClone(draft);
  SIM.runs[name] = { state: null, start: null, end: null };
  const r = await simRequest("sim_scenario_start", fields, `Scenario ${name} started` + (fields.scenario ? " (as edited here, not saved)." : "."));
  if (r) { SIM.scenSig = ""; simUpdateScenarios(); }
}

function simScenarioEditor(name) {
  const sc = simScenarios()[name];
  sc.steps = sc.steps || [];
  const flag = (key, label, help) => {
    const cb = el("input", { type: "checkbox", dataset: { simField: key } });
    cb.checked = !!sc[key];
    cb.addEventListener("change", () => { if (cb.checked) sc[key] = true; else delete sc[key]; simChanged(); });
    return el("div", { class: "check-field" }, el("label", { class: "check" }, cb, " " + label), hint(help));
  };
  const [dl] = simInput("Description", sc.description, "description", { onInput: (v) => { if (v.trim()) sc.description = v; else delete sc.description; simChanged(); } });
  const box = el("fieldset", { dataset: { simEditor: name } }, el("legend", null, `Scenario ${name}`),
    el("div", { class: "grid" }, dl,
      flag("autostart", "Start with the simulation", "Runs when the simulated devices start."),
      flag("test", "Test", "Run by canworks-sim test by default.")),
    el("h3", null, "Steps"),
    stepsEditor(sc.steps, () => simChanged()),
    el("div", { dataset: { simProblems: `scenarios.${name}` } }),
    el("div", { class: "toolbar" }, el("button", { type: "button", onclick: () => { SIM.scenario = null; simRenderTab(); } }, "Close editor"),
      hint("Start runs the scenario as edited here; Save to simulation file keeps it.")));
  setTimeout(simShowProblems, 0);
  return box;
}

function simDefaultNode() {
  const refs = simDeviceRefs();
  return refs.length ? refs[0] : 1;
}

function newStep(action) {
  const node = simDefaultNode();
  const cond = () => ({ node, object: "", eq: 0 });
  switch (action) {
    case "set": return { node, set: {} };
    case "override": return { node, override: {} };
    case "release": return { node, release: "all" };
    case "source": return { node, source: {} };
    case "fault": return { node, fault: { heartbeat: "stop" } };
    case "clear": return { node, clear: "all" };
    case "wait": return { wait: cond(), timeout_ms: 1000 };
    case "expect": return { expect: cond() };
    case "log": return { log: "" };
    case "repeat": return { repeat: { count: 1, steps: [] } };
    default: return { log: "" };
  }
}

function stepsEditor(steps, changedFn) {
  const box = el("div", { class: "sim-steps" });
  const draw = () => {
    const add = el("select", { "aria-label": "Step action", dataset: { sim: "step-action" } }, STEP_ACTIONS.map(([k, l]) => el("option", { value: k }, l)));
    put(box, steps.map((st, k) => stepBlock(steps, k, draw, changedFn)),
      el("div", { class: "toolbar" }, add, el("button", { type: "button", dataset: { sim: "add-step" }, onclick: () => {
        steps.push(newStep(add.value));
        changedFn();
        draw();
      } }, "Add step")));
  };
  draw();
  return box;
}

function deviceRefInput(value, onValue, label) {
  const listId = "sim-device-refs";
  if (!document.getElementById(listId)) document.body.append(el("datalist", { id: listId }));
  document.getElementById(listId).replaceChildren(...simDeviceRefs().map((r) => el("option", { value: String(r) })));
  const input = el("input", { type: "text", class: "short", list: listId, "aria-label": label || "Device", dataset: { simField: "node" } });
  input.value = value === undefined ? "" : String(value);
  input.addEventListener("input", () => {
    const t = input.value.trim();
    onValue(t === "" ? undefined : /^\d+$/.test(t) ? Number(t) : t);
  });
  return input;
}

function msField(label, value, data, onValue) {
  const input = el("input", { type: "text", class: "short", "aria-label": label, dataset: { simField: data } });
  input.value = value === undefined ? "" : String(value);
  input.addEventListener("input", () => {
    const t = input.value.trim();
    onValue(t === "" ? undefined : /^\d+$/.test(t) ? Number(t) : t);
  });
  return input;
}

function stepBlock(steps, k, redraw, changedFn) {
  const st = steps[k];
  const action = STEP_ACTIONS.map((x) => x[0]).find((a) => a in st) || "log";
  const set = (key, v) => { if (v === undefined) delete st[key]; else st[key] = v; changedFn(); };
  const timing = el("select", { "aria-label": "When", dataset: { simField: "timing" } },
    [["", "when the previous step ends"], ["at_ms", "at ms since the start"], ["after_ms", "ms after the previous step"]].map(([v, l]) => el("option", { value: v }, l)));
  timing.value = "at_ms" in st ? "at_ms" : "after_ms" in st ? "after_ms" : "";
  const ms = msField("Time (ms)", st.at_ms !== undefined ? st.at_ms : st.after_ms, "time_ms", (v) => {
    delete st.at_ms; delete st.after_ms;
    if (timing.value && v !== undefined) st[timing.value] = v;
    changedFn();
  });
  ms.hidden = !timing.value;
  timing.addEventListener("change", () => {
    const v = st.at_ms !== undefined ? st.at_ms : st.after_ms;
    delete st.at_ms; delete st.after_ms;
    if (timing.value) st[timing.value] = v !== undefined ? v : 0;
    ms.hidden = !timing.value;
    if (timing.value && ms.value === "") ms.value = "0";
    changedFn();
  });
  const move = (d) => { const j = k + d; if (j < 0 || j >= steps.length) return; [steps[k], steps[j]] = [steps[j], steps[k]]; changedFn(); redraw(); };
  const head = el("div", { class: "sim-step-head" },
    el("strong", null, `${k + 1}. ${STEP_ACTIONS.find((x) => x[0] === action)[1]}`),
    NODE_ACTIONS.includes(action) ? el("label", { class: "inline" }, "Device ", deviceRefInput(st.node, (v) => set("node", v))) : null,
    el("label", { class: "inline" }, "Starts ", timing), ms,
    el("span", { class: "spacer" }),
    el("button", { type: "button", class: "small", title: "Move up", onclick: () => move(-1) }, "↑"),
    el("button", { type: "button", class: "small", title: "Move down", onclick: () => move(1) }, "↓"),
    el("button", { type: "button", class: "small", title: "Remove the step", dataset: { sim: "remove-step" }, onclick: () => { steps.splice(k, 1); changedFn(); redraw(); } }, "✕"));
  return el("div", { class: "sim-step", dataset: { simStep: String(k), simAction: action } }, head, stepBody(st, action, changedFn));
}

function valuesEditor(obj, changedFn) {
  const box = el("div", { class: "sim-pairs" });
  const draw = () => {
    const rows = Object.entries(obj).map(([o, v]) => {
      const oi = el("input", { type: "text", class: "index", placeholder: "0x6200:1", "aria-label": "Object", dataset: { simField: "pair-object" } });
      oi.value = o;
      const vi = el("input", { type: "text", class: "short", placeholder: "value", "aria-label": "Value", dataset: { simField: "pair-value" } });
      vi.value = String(v);
      let key = o;
      oi.addEventListener("change", () => {
        const nk = oi.value.trim();
        if (!nk || nk === key) return;
        const entries = Object.entries(obj).map(([a, b]) => (a === key ? [nk, b] : [a, b]));
        for (const a of Object.keys(obj)) delete obj[a];
        for (const [a, b] of entries) obj[a] = b;
        key = nk;
        changedFn();
      });
      vi.addEventListener("input", () => { obj[key] = simParseValue(vi.value); changedFn(); });
      return el("div", { class: "row" }, oi, "=", vi, el("button", { type: "button", class: "small", onclick: () => { delete obj[key]; changedFn(); draw(); } }, "✕"));
    });
    const no = el("input", { type: "text", class: "index", placeholder: "0x6200:1", "aria-label": "New object", dataset: { simField: "new-object" } });
    const nv = el("input", { type: "text", class: "short", placeholder: "value", "aria-label": "New value", dataset: { simField: "new-value" } });
    put(box, rows, el("div", { class: "row" }, no, "=", nv, el("button", { type: "button", class: "small", dataset: { sim: "add-pair" }, onclick: () => {
      const o = no.value.trim();
      if (!o) return;
      obj[o] = simParseValue(nv.value);
      changedFn();
      draw();
    } }, "Add")));
  };
  draw();
  return box;
}

function conditionEditor(cond, changedFn) {
  const box = el("div", { class: "sim-cond" });
  const mode = el("select", { "aria-label": "Condition", dataset: { simField: "cond-mode" } }, [["object", "object value"], ["expr", "expression"]].map(([k, l]) => el("option", { value: k }, l)));
  mode.value = "expr" in cond ? "expr" : "object";
  const replace = (obj) => { for (const k of Object.keys(cond)) delete cond[k]; Object.assign(cond, obj); };
  const draw = () => {
    if (mode.value === "expr") {
      put(box, el("div", { class: "row wrap" }, mode), el("div", { class: "grid" },
        exprField("Expression", cond.expr || "", typeof cond.node === "number" ? cond.node : simDefaultNode(), (v) => { cond.expr = v; changedFn(); })));
      return;
    }
    const op = el("select", { "aria-label": "Comparison", dataset: { simField: "cond-op" } }, COND_OPS.map(([k, l]) => el("option", { value: k }, l)));
    const cur = COND_OPS.find(([k]) => k in cond);
    op.value = cur ? cur[0] : "eq";
    const val = el("input", { type: "text", class: "short", "aria-label": "Compared value", dataset: { simField: "cond-value" } });
    val.value = cur ? String(cond[cur[0]]) : "";
    const obj = el("input", { type: "text", class: "index", placeholder: "0x6200:1", "aria-label": "Object", dataset: { simField: "cond-object" } });
    obj.value = cond.object || "";
    const bit = msField("Bit", cond.bit, "cond-bit", (v) => { if (v === undefined) delete cond.bit; else cond.bit = v; changedFn(); });
    bit.placeholder = "all";
    const setOp = () => {
      for (const [k] of COND_OPS) delete cond[k];
      cond[op.value] = simParseValue(val.value === "" ? "0" : val.value);
      changedFn();
    };
    op.addEventListener("change", setOp);
    val.addEventListener("input", setOp);
    obj.addEventListener("input", () => { cond.object = obj.value.trim(); changedFn(); });
    put(box, el("div", { class: "row wrap" }, mode,
      el("label", { class: "inline" }, "Device ", deviceRefInput(cond.node, (v) => { if (v === undefined) delete cond.node; else cond.node = v; changedFn(); })),
      el("label", { class: "inline" }, "Object ", obj), el("label", { class: "inline" }, "Bit ", bit), op, val));
  };
  mode.addEventListener("change", () => {
    if (mode.value === "expr") replace({ expr: "" });
    else replace({ node: simDefaultNode(), object: "", eq: 0 });
    changedFn();
    draw();
  });
  draw();
  return box;
}

function stepBody(st, action, changedFn) {
  if (action === "set" || action === "override") return valuesEditor(st[action], changedFn);
  if (action === "release") {
    const sel = el("select", { "aria-label": "Release", dataset: { simField: "release-mode" } }, [["all", "all overrides"], ["list", "these objects"]].map(([k, l]) => el("option", { value: k }, l)));
    sel.value = st.release === "all" ? "all" : "list";
    const list = el("input", { type: "text", placeholder: "0x7130:1, 0x7130:2", "aria-label": "Objects", dataset: { simField: "release-objects" } });
    list.value = Array.isArray(st.release) ? st.release.join(", ") : "";
    list.hidden = sel.value === "all";
    const upd = () => {
      list.hidden = sel.value === "all";
      st.release = sel.value === "all" ? "all" : list.value.split(",").map((x) => x.trim()).filter(Boolean);
      changedFn();
    };
    sel.addEventListener("change", upd);
    list.addEventListener("input", upd);
    return el("div", { class: "row wrap" }, sel, list);
  }
  if (action === "source") {
    const entries = Object.entries(st.source || {});
    let key = entries.length ? entries[0][0] : "";
    const src = entries.length ? entries[0][1] : null;
    const oi = el("input", { type: "text", class: "index", placeholder: "0x7130:1", "aria-label": "Object", dataset: { simField: "source-object" } });
    oi.value = key;
    const none = el("input", { type: "checkbox", dataset: { simField: "source-none" } });
    none.checked = entries.length > 0 && src === null;
    const ed = sourceEditor(src || { constant: 0 }, st.node);
    const msg = el("span", { class: "field-msg" });
    const upd = () => {
      msg.textContent = "";
      const k = oi.value.trim();
      st.source = {};
      if (!k) { changedFn(); return; }
      if (none.checked) st.source[k] = null;
      else {
        try { st.source[k] = ed.value(); } catch (e) { msg.textContent = e.message; }
      }
      changedFn();
    };
    oi.addEventListener("input", upd);
    none.addEventListener("change", () => { ed.el.hidden = none.checked; upd(); });
    ed.el.hidden = none.checked;
    ed.el.addEventListener("input", upd);
    ed.el.addEventListener("change", upd);
    return el("div", null, el("div", { class: "row wrap" }, el("label", { class: "inline" }, "Object ", oi), el("label", { class: "check" }, none, " Remove its source")), ed.el, msg);
  }
  if (action === "fault") {
    const kind = faultKind(st.fault || {});
    const sel = el("select", { "aria-label": "Fault", dataset: { simField: "fault-kind" } }, FAULT_KINDS.map(([k, label]) => el("option", { value: k }, label.replace("…", ""))));
    sel.value = FAULT_KINDS.some(([k]) => k === kind) ? kind : "heartbeat";
    const area = el("div");
    const msg = el("span", { class: "field-msg" });
    const draw = (initial) => {
      const f = faultFields(sel.value, initial, st.node);
      const upd = () => { msg.textContent = ""; try { st.fault = f.value(); } catch (e) { msg.textContent = e.message; } changedFn(); };
      f.el.addEventListener("input", upd);
      f.el.addEventListener("change", upd);
      put(area, f.el);
      upd();
    };
    sel.addEventListener("change", () => draw(null));
    draw(st.fault);
    return el("div", null, el("div", { class: "row" }, sel), area, msg);
  }
  if (action === "clear") {
    const sel = el("select", { "aria-label": "Clear", dataset: { simField: "clear" } }, CLEAR_NAMES.map((k) => el("option", { value: k }, k)));
    sel.value = st.clear || "all";
    sel.addEventListener("change", () => { st.clear = sel.value; changedFn(); });
    return el("div", { class: "row" }, sel);
  }
  if (action === "wait") {
    return el("div", null, conditionEditor(st.wait, changedFn), el("div", { class: "row" }, el("label", { class: "inline" }, "Time-out (ms) ",
      msField("Time-out (ms)", st.timeout_ms, "timeout_ms", (v) => { if (v === undefined) delete st.timeout_ms; else st.timeout_ms = v; changedFn(); })),
    hint("Without a time-out the step waits for ever.")));
  }
  if (action === "expect") {
    const how = el("select", { "aria-label": "Expect how", dataset: { simField: "expect-mode" } },
      [["", "now"], ["within_ms", "within ms"], ["for_ms", "for ms (the whole time)"]].map(([k, l]) => el("option", { value: k }, l)));
    how.value = "within_ms" in st ? "within_ms" : "for_ms" in st ? "for_ms" : "";
    const ms = msField("Time (ms)", st.within_ms !== undefined ? st.within_ms : st.for_ms, "expect_ms", (v) => {
      delete st.within_ms; delete st.for_ms;
      if (how.value && v !== undefined) st[how.value] = v;
      changedFn();
    });
    ms.hidden = !how.value;
    how.addEventListener("change", () => {
      const v = st.within_ms !== undefined ? st.within_ms : st.for_ms;
      delete st.within_ms; delete st.for_ms;
      if (how.value) st[how.value] = v !== undefined ? v : 1000;
      if (how.value && ms.value === "") ms.value = "1000";
      ms.hidden = !how.value;
      changedFn();
    });
    return el("div", null, conditionEditor(st.expect, changedFn), el("div", { class: "row" }, el("label", { class: "inline" }, "Holds ", how), ms));
  }
  if (action === "log") {
    const input = el("input", { type: "text", class: "wide", "aria-label": "Log text", dataset: { simField: "log" } });
    input.value = st.log || "";
    input.addEventListener("input", () => { st.log = input.value; changedFn(); });
    return input;
  }
  if (action === "repeat") {
    st.repeat.steps = st.repeat.steps || [];
    return el("div", null, el("label", { class: "inline" }, "Times (0: for ever) ",
      msField("Times", st.repeat.count, "repeat_count", (v) => { if (v === undefined) delete st.repeat.count; else st.repeat.count = v; changedFn(); })),
    el("div", { class: "sim-nested" }, stepsEditor(st.repeat.steps, changedFn)));
  }
  return el("span");
}

// ---------------------------------------------------------------------------
// Machine tab (canopen-machine-view): machine_view.js, loaded when the tab
// first opens, draws the machine named by the shown network's section.

const MACHINE = { seq: 0, view: null };

// The machine file the shown network's section names ("" when none).
function machineName() {
  const file = SIM.file || (S.state && S.state.simulation && S.state.simulation.doc) || {};
  const ver = Number.isInteger(file.schema_version) ? file.schema_version : 1;
  const sec = ver >= 2 ? ((file.networks || {})[simSectionName()] || {}) : file;
  return typeof sec.machine === "string" ? sec.machine : "";
}

function stopMachine() {
  MACHINE.seq++;
  if (MACHINE.view) MACHINE.view.stop();
  MACHINE.view = null;
}

// A drive's following error window (0x6065) in counts: the config's SDO
// write, else the EDS default.
function machineFeWindow(node) {
  const n = (S.config.nodes || []).find((x) => num(x.node_id) === node);
  if (!n) return null;
  const w = (n.sdo || []).find((s) => num(s.index) === 0x6065 && num(s.subindex || 0) === 0);
  if (w && Number.isFinite(num(w.value))) return num(w.value);
  const o = objectInfo(edsFor(n), 0x6065, 0);
  const v = o ? num(String(o.default)) : NaN;
  return Number.isFinite(v) ? v : null;
}

// The Machine tab of the Simulation view.
async function simMachineTab(body) {
  stopMachine();
  const seq = MACHINE.seq;
  const name = machineName();
  const host = el("div", { id: "machine-view" }, el("p", { class: "muted" }, "Loading the machine view…"));
  body.replaceChildren(host);
  let mod;
  try { mod = await import("./machine_view.js"); } catch (e) {
    if (seq === MACHINE.seq) host.replaceChildren(el("p", { class: "field-msg" }, `The machine view did not load: ${e.message}`));
    return;
  }
  if (seq !== MACHINE.seq || S.view !== "simulation" || SIM.tab !== "machine") return;
  const can = simCanConnect();
  MACHINE.view = mod.openMachineView(host, {
    network: simSectionName(), port: diagPort(), file: name, canConnect: can,
    notConnected: SIM.settings.target === "simulator" ? "Connect to the standalone simulator above."
      : diagConfig() ? "To see it live, enter the runtime host and the token in the Online view."
        : "Online access is off for this config: turn it on under Bus and master to see the machine live.",
    feWindow: machineFeWindow,
    openNode: (node) => {
      if (several()) S.onlineNet = simSectionName();
      S.onlineNode = node;
      showView("online");
    },
  });
}
