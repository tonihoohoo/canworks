// Machine view (canopen-machine-view; docs/machine.md): the 3D machine of a
// network's machine file, drawn with three.js from machine_scene.js, and a
// panel beside it with the axes, the machine's I/O bits, counters, faults
// and the machine fault buttons. Offline it shows the machine at home from
// GET /api/sim/machine; online it polls POST /api/sim/machine (sim_machine)
// with one request in flight and draws a fixed delay behind the newest
// answer. Without WebGL only the panel runs. Loaded by sim.js (renderMachine)
// with a dynamic import; uses app.js helpers (el, api, banner).
import { THREE, JOINTS, buildMachine, machineSpec, homeSnapshot, SnapshotBuffer, toolPoint } from "./machine_scene.js";
import { OrbitControls } from "./three/addons/controls/OrbitControls.js";
import { RoomEnvironment } from "./three/addons/environments/RoomEnvironment.js";
import { EffectComposer } from "./three/addons/postprocessing/EffectComposer.js";
import { RenderPass } from "./three/addons/postprocessing/RenderPass.js";
import { GTAOPass } from "./three/addons/postprocessing/GTAOPass.js";
import { UnrealBloomPass } from "./three/addons/postprocessing/UnrealBloomPass.js";
import { SMAAPass } from "./three/addons/postprocessing/SMAAPass.js";
import { OutputPass } from "./three/addons/postprocessing/OutputPass.js";
import { CSS2DRenderer, CSS2DObject } from "./three/addons/renderers/CSS2DRenderer.js";

export const POLL_MS = 33;        // about 30 answers a second
export const NO_DATA_MS = 1000;   // "no data" after this long without an answer
export const RETRY_MS = 1000;     // after a failed request
const PANEL_MS = 100;
const QUALITY_KEY = "canopen-machine-quality";
const MODES = { 1: "PP", 3: "PV", 4: "PT", 6: "Homing", 7: "IP", 8: "CSP", 9: "CSV", 10: "CST" };
const COUNTERS = [["placed", "Placed"], ["picked", "Picked"], ["fed", "Fed"], ["misplaced", "Misplaced"], ["dropped", "Dropped"], ["pallets", "Pallets"]];
const TRAIL_N = 420;              // tool path samples, at 90 a second: the last 4.7 s
const reduceMotion = () => matchMedia("(prefers-reduced-motion: reduce)").matches;

// Settings of this page session; the quality preset is kept on this PC.
const prefs = { labels: true, path: true, camera: "overview" };

export function storedQuality() {
  try { return localStorage.getItem(QUALITY_KEY) === "low" ? "low" : "high"; } catch (e) { return "high"; }
}
function storeQuality(q) {
  try { localStorage.setItem(QUALITY_KEY, q); } catch (e) { /* storage off: the preset lasts this page */ }
}

// three.js needs WebGL 2.
export function hasWebGL() {
  try {
    const c = document.createElement("canvas");
    return !!(window.WebGL2RenderingContext && c.getContext("webgl2"));
  } catch (e) {
    return false;
  }
}

// The automatic fall back: fed the frame times, says "low" once the frame
// rate stayed under `fps` for `seconds` whole seconds on High.
export class FrameRateWatch {
  constructor(fps, seconds, warmupS) {
    this.min = fps === undefined ? 28 : fps;
    this.seconds = seconds === undefined ? 3 : seconds;
    this.warmup = warmupS === undefined ? 2 : warmupS;
    this.reset();
  }
  reset() { this.acc = 0; this.frames = 0; this.slow = 0; this.age = 0; this.fps = null; }
  frame(dtS) {
    this.age += dtS;
    if (this.age < this.warmup) return null;
    this.acc += dtS;
    this.frames++;
    if (this.acc < 1) return null;
    this.fps = this.frames / this.acc;
    this.slow = this.fps < this.min ? this.slow + 1 : 0;
    this.acc = 0;
    this.frames = 0;
    return this.slow >= this.seconds ? "low" : null;
  }
}

const hex = (v, n) => "0x" + (Number(v) >>> 0).toString(16).toUpperCase().padStart(n, "0");
const isNum = (v) => typeof v === "number" && Number.isFinite(v);
const fmt = (v, d) => (isNum(v) ? v.toFixed(d) : "–");
const stateText = (s) => (s === "off" || !s ? "No drive" : s.charAt(0).toUpperCase() + s.slice(1).replace(/_/g, " "));
const jointFault = (j) => !!j && (j.fault === true || j.state === "fault" || j.state === "fault_reaction_active");
const emcyOf = (j) => (j && isNum(j.emcy) ? j.emcy : j && isNum(j.error_code) ? j.error_code : null);
const bitText = (b) => (b && typeof b === "object" ? `node ${b.node} ${b.object} bit ${b.bit}` : "");

// The machine's I/O bits: what each bit is and its value in a snapshot.
export function ioBits(spec) {
  const out = [];
  const T = spec.tool;
  if (T.close) out.push({ name: "Gripper close", dir: "out", bit: T.close, value: (s) => !!(s.tool && s.tool.closed) });
  if (T.gripped) out.push({ name: "Part gripped", dir: "in", bit: T.gripped, value: (s) => !!(s.tool && s.tool.closed && s.tool.holding !== null && s.tool.holding !== undefined) });
  for (const c of spec.conveyors) if (c.run) out.push({ name: `${c.name} run`, dir: "out", bit: c.run, value: (s) => !!((s.conveyors || {})[c.name] || {}).running });
  for (const x of spec.sensors) if (x.output) out.push({ name: x.name, dir: "in", bit: x.output, value: (s) => !!(s.sensors || {})[x.name] });
  for (const f of spec.fixtures) {
    if (!f.change) continue;
    if (f.change.request) out.push({ name: `${f.name} change`, dir: "out", bit: f.change.request, value: (s) => !!((s.fixtures || {})[f.name] || {}).changing });
    if (f.change.ready) out.push({ name: `${f.name} ready`, dir: "in", bit: f.change.ready, value: (s) => !!((s.fixtures || {})[f.name] || {}).ready });
  }
  return out;
}

// The machine faults the view offers: [element, label, [[button, fault]...], clear name].
export function faultChoices(spec) {
  const out = [];
  for (const n of JOINTS) out.push({ element: n, label: `Joint ${n.toUpperCase()}`, faults: [["Jam", { jam: true }]], clear: "jam" });
  for (const s of spec.sensors) out.push({ element: s.name, label: `Sensor ${s.name}`, faults: [["Stuck on", { stuck: "on" }], ["Stuck off", { stuck: "off" }]], clear: "stuck" });
  if (spec.tool.present) out.push({ element: "tool", label: "Gripper", faults: [["Slip", { slip: true }]], clear: null });
  for (const c of spec.conveyors) {
    if (!c.feed) continue;
    out.push({ element: c.name, label: `Feeder ${c.name}`, faults: [["Stop", { feeder: "stop" }], ["Empty", { feeder: "empty" }]], clear: "feeder" });
    out.push({ element: c.name, label: `Next part on ${c.name}`, faults: [["Misaligned", "misaligned"]], clear: "misaligned_mm" });
  }
  return out;
}

export function openMachineView(host, ctx) {
  const v = new MachineView(host, ctx);
  v.start();
  return v;
}

export class MachineView {
  // ctx: { network, port, file (the machine file's name), canConnect,
  //   notConnected (why not), openNode(node), feWindow(node) (counts or null) }
  constructor(host, ctx) {
    this.host = host;
    this.ctx = ctx;
    this.buffer = new SnapshotBuffer();
    this.stopped = false;
    this.seq = 0;
    this.timer = null;
    this.inflight = false;
    this.live = false;          // an answer came since the view opened
    this.lastAnswer = null;     // performance.now() of the last answer
    this.error = null;
    this.hello = null;
    this.shown = null;          // the snapshot last drawn / shown
    this.events = [];           // last faults: { t, text }
    this.prevFaults = new Map();
    this.gl = null;
    this.quality = storedQuality();
    this.watch = new FrameRateWatch();
    window.machineView = this;  // for the page tests
  }

  async start() {
    const seq = this.seq;
    this.host.replaceChildren(el("p", { class: "muted" }, "Loading the machine…"));
    let res;
    try {
      res = await api("GET", "/api/sim/machine?network=" + encodeURIComponent(this.ctx.network || ""));
    } catch (e) {
      if (seq !== this.seq || this.stopped) return;
      this.host.replaceChildren(el("p", { class: "field-msg", dataset: { machine: "error" } }, `The machine file could not be read: ${e.message}`));
      return;
    }
    if (seq !== this.seq || this.stopped) return;
    this.offline = res;
    if (!res.machine) {
      const probs = (res.problems || []).map(problemText);
      this.host.replaceChildren(el("div", { dataset: { machine: "error" } },
        el("p", { class: "field-msg" }, `The machine file ${res.file || this.ctx.file || ""} cannot be drawn${probs.length ? ":" : "."}`),
        probs.length ? el("ul", null, probs.map((p) => el("li", null, p))) : null));
      return;
    }
    this.file = res.machine;
    this.spec = machineSpec(res.machine);
    this.home = homeSnapshot(this.spec);
    this.io = ioBits(this.spec);
    this.layout();
    if (hasWebGL()) {
      try { this.initGL(); } catch (e) { this.gl = null; this.noWebGL(`The 3D view could not start WebGL (${e.message}).`); }
    } else {
      this.noWebGL();
    }
    this.shown = this.home;
    this.updatePanel();
    this.panelTimer = setInterval(() => this.tick(), PANEL_MS);
    // Hidden (another tab, minimised): no polling and no frames until shown again.
    this.onVisible = () => {
      if (document.hidden || this.stopped || this.timer || this.inflight || !this.ctx.canConnect) return;
      if (this.live) this.lastAnswer = performance.now();  // no "no data" for the time it was hidden
      this.poll();
    };
    document.addEventListener("visibilitychange", this.onVisible);
    if (this.ctx.canConnect) this.poll();
    this.updateConn();
  }

  stop() {
    this.stopped = true;
    this.seq++;
    clearTimeout(this.timer);
    clearInterval(this.panelTimer);
    if (this.onVisible) document.removeEventListener("visibilitychange", this.onVisible);
    if (this.gl) this.disposeGL();
    if (window.machineView === this) window.machineView = null;
  }

  // ---- Polling ----
  schedule(ms) {
    clearTimeout(this.timer);
    this.timer = setTimeout(() => { this.timer = null; this.poll(); }, ms);
  }

  async poll() {
    if (this.stopped || this.inflight) return;
    if (document.hidden) return;  // visibilitychange starts it again
    const seq = this.seq;
    const t0 = performance.now();
    this.inflight = true;
    let r = null, err = null;
    try {
      r = await api("POST", "/api/sim/machine", { network: this.ctx.network, port: this.ctx.port });
    } catch (e) { err = e; }
    this.inflight = false;
    if (this.stopped || seq !== this.seq) return;
    if (r && r.machine && typeof r.machine === "object") {
      this.hello = r;
      this.error = null;
      this.live = true;
      this.lastAnswer = performance.now();
      if (this.buffer.push(r.machine, performance.now())) this.noteFaults(r.machine);
      this.schedule(Math.max(0, POLL_MS - (performance.now() - t0)));
    } else {
      this.error = err || new Error("the answer has no machine");
      this.schedule(RETRY_MS);
    }
    this.updateConn();
  }

  // The snapshot to draw now.
  current(now) {
    if (!this.live) return this.home;
    return this.buffer.sample(now) || this.home;
  }

  noData() { return this.live && performance.now() - this.lastAnswer > NO_DATA_MS; }

  tick() {
    if (!this.gl) this.shown = this.current(performance.now());
    this.updatePanel();
    this.updateConn();
  }

  // Drive faults and machine faults as they come and go, for "Last faults".
  noteFaults(s) {
    const t = isNum(s.t_us) ? (s.t_us / 1e6).toFixed(2) + " s" : "";
    const now = new Map();
    for (const [n, j] of Object.entries(s.joints || {})) {
      if (jointFault(j)) {
        const code = emcyOf(j);
        now.set("joint:" + n, `${n.toUpperCase()} axis, node ${j.node}: ${code !== null ? "EMCY " + hex(code, 4) : "fault"}`);
      }
    }
    for (const f of s.faults || []) {
      const k = Object.keys(f.fault || {})[0];
      now.set(`machine:${f.machine}:${k}`, `${f.machine}: ${k}${f.fault[k] === true ? "" : " " + f.fault[k]}`);
    }
    for (const [k, text] of now) if (!this.prevFaults.has(k)) this.events.unshift({ t, text, on: true });
    for (const [k, text] of this.prevFaults) if (!now.has(k)) this.events.unshift({ t, text: text + " cleared", on: false });
    this.events.length = Math.min(this.events.length, 6);
    this.prevFaults = now;
  }

  allowChanges() { return !!(this.live && !this.noData() && this.hello && this.hello.allow_changes); }

  changeReason() {
    if (!this.live || this.noData()) return "The machine is offline: machine faults need the running machine.";
    if (!this.hello.allow_changes) {
      return this.hello.target === "runtime" || !this.hello.target
        ? "Read-only: changes are not allowed on this runtime (turn on \"Allow changes\" under Online access on Bus and master, then save and upload)."
        : "Read-only: changes are not allowed.";
    }
    return "";
  }

  async fault(element, fault, button) {
    await busy(button, "…", async () => {
      try {
        await api("POST", "/api/sim/request", { op: "sim_fault", machine: element, fault, network: this.ctx.network, port: this.ctx.port });
        banner(`Fault set on ${element}.`);
      } catch (e) { banner(e.message, true); }
    });
  }

  async clear(element, name, button) {
    await busy(button, "…", async () => {
      try {
        await api("POST", "/api/sim/request", { op: "sim_clear", machine: element, fault: name, network: this.ctx.network, port: this.ctx.port });
        banner(element === "all" ? "Machine faults cleared." : `Fault cleared on ${element}.`);
      } catch (e) { banner(e.message, true); }
    });
  }

  // ---- Page layout ----
  layout() {
    const seg = (label, items, active, pick, key) => el("div", { class: "segmented", role: "group", "aria-label": label },
      items.map(([k, text]) => el("button", { type: "button", "aria-pressed": String(k === active), dataset: { [key]: k }, onclick: () => pick(k) }, text)));
    const toggle = (pref, text, key) => el("button", { type: "button", "aria-pressed": String(prefs[pref]), dataset: { machineShow: key },
      onclick: (e) => { prefs[pref] = !prefs[pref]; e.currentTarget.setAttribute("aria-pressed", String(prefs[pref])); this.applyShow(); } }, text);
    this.camBar = seg("Camera", [["overview", "Overview"], ["top", "Top"], ["tool", "Follow tool"]], prefs.camera, (k) => this.camera(k), "machineCam");
    this.qualityBar = seg("Quality", [["high", "High"], ["low", "Low"]], this.quality, (k) => this.setQuality(k, false), "machineQuality");
    this.stage = el("div", { class: "machine-stage", dataset: { machine: "stage" } },
      this.noticeEl = el("p", { class: "machine-notice", role: "status", dataset: { machine: "notice" }, hidden: true }),
      this.noDataEl = el("p", { class: "machine-nodata", dataset: { machine: "nodata" }, hidden: true }, "No data"),
      this.fpsEl = el("span", { class: "machine-fps", "aria-hidden": "true" }));
    this.panel = el("aside", { class: "machine-panel", "aria-label": "Machine values" });
    this.buildPanel();
    const problems = (this.offline.problems || []).map(problemText);
    this.host.replaceChildren(...[
      el("div", { class: "toolbar" },
        el("span", { class: "muted" }, `${this.spec.name || "Machine"} · ${this.offline.file || this.ctx.file || ""}`),
        el("div", { class: "spacer" }),
        this.camBar, this.qualityBar, toggle("labels", "Labels", "labels"), toggle("path", "Tool path", "path")),
      this.connEl = el("div", { class: "online-conn", dataset: { machine: "conn" } }),
      problems.length ? el("div", { class: "field-msg warning", dataset: { machine: "problems" } },
        `The machine file has problems; the drawing may not match the simulated machine: ${problems.join("; ")}`) : null,
      el("div", { class: "machine-main" }, this.stage, this.panel)].filter(Boolean));
  }

  noWebGL(why) {
    this.camBar.hidden = true;
    this.qualityBar.hidden = true;
    for (const b of this.host.querySelectorAll("[data-machine-show]")) b.hidden = true;
    this.stage.classList.add("no-webgl");
    this.stage.prepend(el("p", { class: "machine-nowebgl", dataset: { machine: "nowebgl" } },
      why || "The 3D view needs WebGL, which this browser has turned off or does not have.",
      " The panel shows the machine's values."));
  }

  buildPanel() {
    const S0 = this.spec;
    this.axisEls = {};
    const axes = JOINTS.map((n) => {
      const j = S0.joints[n];
      const e = {};
      const open = () => { if (j.node) this.ctx.openNode(j.node); };
      const row = el("div", { class: "machine-axis clickable", tabindex: "0", role: "button", dataset: { machineAxis: n },
        "aria-label": `Axis ${n.toUpperCase()}, node ${j.node}: open in the Online view`, onclick: open,
        onkeydown: (ev) => { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); open(); } } },
      el("div", { class: "machine-axis-head" },
        el("b", null, n.toUpperCase()), el("span", { class: "muted" }, `node ${j.node ?? "?"}`),
        e.state = el("span", { class: "pill", dataset: { k: "state" } })),
      e.pos = el("div", { class: "machine-pos", dataset: { k: "position" } }),
      e.meta = el("div", { class: "machine-meta", dataset: { k: "meta" } }));
      this.axisEls[n] = e;
      return row;
    });
    this.ioEls = this.io.map((b) => {
      const dot = el("span", { class: "dot", "aria-hidden": "true" });
      const val = el("span", { class: "visually-hidden" });
      const li = el("li", { dataset: { machineIo: b.name } }, dot, el("span", null, b.name), el("code", null, `${b.dir === "in" ? "in" : "out"} · ${bitText(b.bit)}`), val);
      return { b, li, dot, val };
    });
    this.counterEls = {};
    const counters = el("dl", { class: "machine-counters" }, COUNTERS.map(([k, label]) => el("div", null,
      el("dt", null, label), this.counterEls[k] = el("dd", { dataset: { machineCounter: k } }, "0"))));
    this.faultReason = el("p", { class: "hint", dataset: { machine: "fault-reason" } });
    this.faultButtons = [];
    const fb = (text, attrs, fn) => {
      const b = el("button", Object.assign({ type: "button", class: "small" }, attrs), text);
      b.addEventListener("click", () => fn(b));
      this.faultButtons.push(b);
      return b;
    };
    const rows = faultChoices(S0).map((c) => {
      let mmInput = null;
      const btns = c.faults.map(([text, f]) => {
        if (f === "misaligned") {
          mmInput = el("input", { type: "number", value: "20", step: "1", "aria-label": `Offset of the next part on ${c.element} (mm)`, class: "machine-mm" });
          this.faultButtons.push(mmInput);
          return fb(text, { dataset: { machineFault: `${c.element}:misaligned_mm` } }, (b) => this.fault(c.element, { misaligned_mm: Number(mmInput.value) || 0 }, b));
        }
        const k = Object.keys(f)[0];
        return fb(text, { dataset: { machineFault: `${c.element}:${k}${f[k] === true ? "" : ":" + f[k]}` } }, (b) => this.fault(c.element, f, b));
      });
      const clear = c.clear ? fb("Clear", { dataset: { machineClear: `${c.element}:${c.clear}` } }, (b) => this.clear(c.element, c.clear, b)) : null;
      return el("li", null, el("span", null, c.label), el("span", { class: "row" }, mmInput ? el("span", { class: "joined" }, mmInput, el("span", { class: "muted" }, " mm ")) : null, btns, clear));
    });
    const clearAll = fb("Clear all", { dataset: { machineClear: "all" } }, (b) => this.clear("all", "all", b));
    this.activeFaults = el("ul", { class: "machine-list", dataset: { machine: "active-faults" } });
    this.eventsEl = el("ul", { class: "machine-list", dataset: { machine: "events" } });
    this.stateEl = el("p", { class: "machine-state", dataset: { machine: "state" } });
    this.panel.replaceChildren(
      this.stateEl,
      el("section", null, el("h3", null, "Axes"), el("div", { class: "machine-axes" }, axes)),
      el("section", null, el("h3", null, "I/O"), this.ioEls.length ? el("ul", { class: "machine-io" }, this.ioEls.map((x) => x.li)) : el("p", { class: "muted" }, "The machine file binds no I/O bits.")),
      el("section", null, el("h3", null, "Counters"), counters),
      el("section", null, el("h3", null, "Last faults"), this.eventsEl, this.activeFaults),
      el("section", { dataset: { machine: "faults" } }, el("h3", null, "Machine faults"), this.faultReason,
        el("ul", { class: "machine-faults" }, rows), el("div", { class: "toolbar" }, clearAll)));
  }

  updateConn() {
    if (!this.connEl) return;
    const nodata = this.noData();
    const state = !this.live ? "offline" : nodata ? "nodata" : "live";
    this.host.dataset.machineState = state;
    if (this.noDataEl) this.noDataEl.hidden = state !== "nodata";
    let text, cls = "online-conn";
    if (state === "live") {
      const h = this.hello || {};
      text = `Live: the machine on network ${this.ctx.network || ""} from ${h.target === "simulator" ? "the standalone simulator" : "the runtime"}` +
        `, ${h.allow_changes ? "changes allowed" : "read-only"}.`;
      cls += " ok";
    } else if (state === "nodata") {
      const s = ((performance.now() - this.lastAnswer) / 1000).toFixed(1);
      text = `No data: no answer for ${s} s${this.error ? ` (${this.error.message})` : ""}. The view holds the last pose.`;
      cls += " error";
    } else {
      const why = !this.ctx.canConnect ? this.ctx.notConnected : this.error ? errorText(this.error) : "connecting…";
      text = `Offline preview: the machine at its home positions from ${this.offline.file || this.ctx.file || "the machine file"}. ${why}`;
    }
    if (this.connEl.textContent !== text) this.connEl.textContent = text;
    this.connEl.className = cls;
    this.stateEl.textContent = state === "live" ? "The machine is running." : state === "nodata" ? "No data from the machine." : "The machine is offline.";
    this.stateEl.className = "machine-state " + state;
    const allow = this.allowChanges();
    const reason = this.changeReason();
    this.faultReason.textContent = reason;
    for (const b of this.faultButtons) { b.disabled = !allow; b.title = reason; }
  }

  updatePanel() {
    const s = this.shown || this.home;
    const J = s.joints || {};
    for (const n of JOINTS) {
      const j = J[n] || {};
      const e = this.axisEls[n];
      const spec = this.spec.joints[n];
      const fault = jointFault(j);
      const code = emcyOf(j);
      e.state.textContent = fault ? (code !== null ? `Fault · EMCY ${hex(code, 4)}` : "Fault") : stateText(j.state);
      e.state.className = "pill " + (fault ? "bad" : j.state === "operation_enabled" ? "ok" : j.state && j.state !== "off" ? "warn" : "");
      e.pos.textContent = `${fmt(j.position, 2)} mm · ${isNum(j.actual_counts) ? j.actual_counts : "–"} counts`;
      const fe = isNum(j.demand) && isNum(j.position) ? j.demand - j.position : null;
      const win = spec.node && this.ctx.feWindow ? this.ctx.feWindow(spec.node) : null;
      const parts = [MODES[j.mode] || (j.mode ? `mode ${j.mode}` : "mode –"), `sw ${isNum(j.statusword) ? hex(j.statusword, 4) : "–"}`,
        `FE ${fe === null ? "–" : fe.toFixed(3)}${isNum(win) ? ` of ${(win / spec.counts_per_mm).toFixed(3)}` : ""} mm`];
      if (isNum(j.torque)) parts.push(`torque ${Math.round(j.torque)} ‰`);
      e.meta.textContent = parts.join(" · ");
      e.meta.classList.toggle("bad", isNum(win) && fe !== null && Math.abs(fe) > win / spec.counts_per_mm);
      e.state.closest(".machine-axis").classList.toggle("fault", fault);
    }
    for (const x of this.ioEls) {
      const on = !s.offline && x.b.value(s);
      x.dot.className = "dot" + (on ? " on" : "");
      x.val.textContent = on ? "on" : "off";
      x.li.dataset.on = on ? "1" : "0";
    }
    const c = s.counters || {};
    for (const [k] of COUNTERS) this.counterEls[k].textContent = String(isNum(c[k]) ? c[k] : 0);
    const active = (s.faults || []).map((f) => {
      const k = Object.keys(f.fault || {})[0];
      return el("li", { class: "bad" }, `Active: ${f.machine} ${k}${f.fault[k] === true ? "" : " " + f.fault[k]}`);
    });
    this.activeFaults.replaceChildren(...active);
    this.eventsEl.replaceChildren(...(this.events.length ? this.events.map((e) => el("li", { class: e.on ? "bad" : "" }, `${e.t} ${e.text}`))
      : [el("li", { class: "muted" }, "None.")]));
    this.updateLabels(s);
  }

  // ---- 3D ----
  initGL() {
    const ms = buildMachine(this.file);
    this.ms = ms;
    const canvas = el("canvas", { "aria-label": "3D view of the machine; drag to orbit, right-drag or two fingers to pan, scroll or pinch to zoom", role: "img" });
    this.stage.prepend(canvas);
    const renderer = new THREE.WebGLRenderer({ canvas, antialias: false, powerPreference: "high-performance" });
    renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
    renderer.shadowMap.enabled = true;
    renderer.toneMapping = THREE.AgXToneMapping;
    renderer.toneMappingExposure = 1.18;
    const scene = ms.scene;
    const pmrem = new THREE.PMREMGenerator(renderer);
    const env = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
    pmrem.dispose();
    scene.environment = env;
    scene.environmentIntensity = 0.7;
    const dome = new THREE.Mesh(new THREE.SphereGeometry(18, 32, 16), new THREE.ShaderMaterial({
      side: THREE.BackSide, depthWrite: false, fog: false,
      uniforms: { top: { value: new THREE.Color() }, mid: { value: new THREE.Color() }, bottom: { value: new THREE.Color() } },
      vertexShader: "varying vec3 vP; void main(){ vP = normalize(position); gl_Position = projectionMatrix * modelViewMatrix * vec4(position,1.0); }",
      fragmentShader: "uniform vec3 top; uniform vec3 mid; uniform vec3 bottom; varying vec3 vP; void main(){ float h = vP.y; vec3 c = h > 0.0 ? mix(mid, top, pow(h, 0.55)) : mix(mid, bottom, pow(-h, 0.4)); gl_FragColor = vec4(c, 1.0); }",
    }));
    scene.add(dome);
    scene.fog = new THREE.Fog(0x141a1f, 5, 13);
    const camera = new THREE.PerspectiveCamera(36, 16 / 10, 0.05, 40);
    camera.position.copy(ms.views.overview);
    const controls = new OrbitControls(camera, canvas);
    controls.target.copy(ms.views.target);
    controls.enableDamping = true;
    controls.dampingFactor = 0.08;
    controls.minDistance = 0.4;
    controls.maxDistance = 9;
    controls.maxPolarAngle = Math.PI * 0.495;
    const labels = new CSS2DRenderer();
    labels.domElement.className = "machine-labels";
    this.stage.append(labels.domElement);
    this.gl = { renderer, scene, camera, controls, labels, dome, env, canvas, composer: null, anim: null, trail: this.makeTrail(scene) };
    this.makeLabels();
    this.theme();
    this.themeObserver = new MutationObserver(() => this.theme());
    this.themeObserver.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    this.buildComposer();
    this.resize();
    this.resizeObserver = new ResizeObserver(() => this.resize());
    this.resizeObserver.observe(this.stage);
    this.pointer(canvas);
    this.applyShow();
    if (prefs.camera !== "overview") this.camera(prefs.camera, true);
    this.last = performance.now();
    const frame = (now) => {
      if (this.stopped) return;
      this.raf = requestAnimationFrame(frame);
      if (document.hidden) { this.last = now; return; }
      this.frame(now);
    };
    this.raf = requestAnimationFrame(frame);
  }

  disposeGL() {
    const g = this.gl;
    cancelAnimationFrame(this.raf);
    if (this.resizeObserver) this.resizeObserver.disconnect();
    if (this.themeObserver) this.themeObserver.disconnect();
    g.controls.dispose();
    if (g.composer) g.composer.dispose();
    g.env.dispose();
    this.ms.dispose();
    g.renderer.dispose();
    g.renderer.forceContextLoss();
    this.gl = null;
  }

  theme() {
    const g = this.gl;
    const t = document.documentElement.dataset.theme;
    const dark = t === "dark" || (t !== "light" && matchMedia("(prefers-color-scheme: dark)").matches);
    const c = dark ? [0x07090b, 0x1a2026, 0x0b0e11, 0x141a1f] : [0x9aa3ab, 0xe4e7ea, 0x8f969c, 0xc9ced3];
    g.dome.material.uniforms.top.value.setHex(c[0]);
    g.dome.material.uniforms.mid.value.setHex(c[1]);
    g.dome.material.uniforms.bottom.value.setHex(c[2]);
    g.scene.fog.color.setHex(c[3]);
    g.scene.background = new THREE.Color(c[2]);
  }

  buildComposer() {
    const g = this.gl;
    if (g.composer) g.composer.dispose();
    const w = Math.max(1, this.stage.clientWidth), h = Math.max(1, this.stage.clientHeight);
    const pr = g.renderer.getPixelRatio();
    const composer = new EffectComposer(g.renderer);
    composer.addPass(new RenderPass(g.scene, g.camera));
    const high = this.quality === "high";
    if (high) {
      const gtao = new GTAOPass(g.scene, g.camera, w, h);
      gtao.output = GTAOPass.OUTPUT.Default;
      gtao.blendIntensity = 0.9;
      gtao.updateGtaoMaterial({ radius: 0.18, distanceExponent: 1.6, thickness: 1.2, scale: 1.0, samples: 16 });
      gtao.updatePdMaterial({ lumaPhi: 10, depthPhi: 2, normalPhi: 3, radius: 4, rings: 2, samples: 16 });
      composer.addPass(gtao);
      composer.addPass(new UnrealBloomPass(new THREE.Vector2(w, h), 0.35, 0.5, 0.92));  // only lamps pass the threshold
    }
    composer.addPass(new SMAAPass(w * pr, h * pr));
    composer.addPass(new OutputPass());
    g.composer = composer;
    g.renderer.shadowMap.type = high ? THREE.PCFSoftShadowMap : THREE.PCFShadowMap;
    const key = this.ms.keyLight;
    key.shadow.mapSize.set(high ? 2048 : 1024, high ? 2048 : 1024);
    if (key.shadow.map) { key.shadow.map.dispose(); key.shadow.map = null; }
    g.scene.traverse((o) => { if (o.material) for (const m of [].concat(o.material)) m.needsUpdate = true; });
  }

  setQuality(q, auto) {
    this.quality = q;
    storeQuality(q);
    for (const b of this.qualityBar.querySelectorAll("button")) b.setAttribute("aria-pressed", String(b.dataset.machineQuality === q));
    this.noticeEl.hidden = !auto;
    this.noticeEl.textContent = auto ? "Switched to Low: the view ran under 28 frames per second for 3 s on High. Pick High to try again." : "";
    this.watch.reset();
    if (this.gl) { this.buildComposer(); this.resize(); }
  }

  resize() {
    const g = this.gl;
    if (!g) return;
    const w = Math.max(1, this.stage.clientWidth), h = Math.max(1, this.stage.clientHeight);
    g.renderer.setSize(w, h, false);
    g.camera.aspect = w / h;
    g.camera.updateProjectionMatrix();
    g.composer.setSize(w, h);
    g.labels.setSize(w, h);
  }

  camera(mode, instant) {
    prefs.camera = mode;
    for (const b of this.camBar.querySelectorAll("button")) b.setAttribute("aria-pressed", String(b.dataset.machineCam === mode));
    const g = this.gl;
    if (!g || mode === "tool") return;
    const v = this.ms.views;
    const to = mode === "top" ? { p: v.top, t: v.topTarget } : { p: v.overview, t: v.target };
    if (instant || reduceMotion()) { g.camera.position.copy(to.p); g.controls.target.copy(to.t); g.anim = null; return; }
    g.anim = { k: 0, fromP: g.camera.position.clone(), fromT: g.controls.target.clone(), toP: to.p, toT: to.t };
  }

  applyShow() {
    if (!this.gl) return;
    this.gl.labels.domElement.hidden = !prefs.labels;
    this.gl.trail.line.visible = prefs.path;
  }

  // Click a drive (motor, carriage) to open its node; the pointer shows what can be clicked.
  pointer(canvas) {
    const ray = new THREE.Raycaster();
    const v = new THREE.Vector2();
    const hit = (ev) => {
      const r = canvas.getBoundingClientRect();
      v.set(((ev.clientX - r.left) / r.width) * 2 - 1, -((ev.clientY - r.top) / r.height) * 2 + 1);
      ray.setFromCamera(v, this.gl.camera);
      const h = ray.intersectObjects(this.ms.pickables, false)[0];
      let o = h ? h.object : null;
      while (o && !(o.userData && o.userData.node)) o = o.parent;
      return o ? o.userData : null;
    };
    let down = null;
    canvas.addEventListener("pointerdown", (ev) => { down = { x: ev.clientX, y: ev.clientY, t: performance.now() }; });
    canvas.addEventListener("pointerup", (ev) => {
      if (!down || Math.hypot(ev.clientX - down.x, ev.clientY - down.y) > 5 || performance.now() - down.t > 600) { down = null; return; }
      down = null;
      const d = hit(ev);
      if (d) this.ctx.openNode(d.node);
    });
    let pending = false;
    canvas.addEventListener("pointermove", (ev) => {
      if (pending || ev.buttons) return;
      pending = true;
      requestAnimationFrame(() => {
        pending = false;
        if (!this.gl) return;
        const d = hit(ev);
        canvas.style.cursor = d ? "pointer" : "";
        canvas.title = d ? `Node ${d.node} (${d.joint.toUpperCase()} axis): click to open in the Online view` : "";
      });
    });
  }

  makeLabels() {
    this.labelEls = {};
    for (const a of this.ms.anchors) {
      const d = el("div", { class: "machine-tag", dataset: { machineTag: a.key } });
      if (a.kind === "joint") {
        const node = this.spec.joints[a.name].node;
        d.classList.add("clickable");
        d.addEventListener("click", () => { if (node) this.ctx.openNode(node); });
      }
      a.object.add(new CSS2DObject(d));
      this.labelEls[a.key] = d;
    }
  }

  updateLabels(s) {
    if (!this.labelEls || !prefs.labels) return;
    const set = (key, bad, name, rest) => {
      const d = this.labelEls[key];
      if (!d) return;
      const text = `${name} ${rest}`;
      if (d.dataset.text === text) return;
      d.dataset.text = text;
      d.classList.toggle("bad", bad);
      d.replaceChildren(el("b", null, name), " " + rest);
    };
    for (const n of JOINTS) {
      const j = (s.joints || {})[n] || {};
      const f = jointFault(j);
      const code = emcyOf(j);
      const what = f ? (code !== null ? `EMCY ${hex(code, 4)}` : "FAULT") : j.state === "operation_enabled" ? MODES[j.mode] || stateText(j.state) : stateText(j.state);
      set("joint:" + n, f, n.toUpperCase(), `node ${this.spec.joints[n].node} · ${fmt(j.position, 1)} mm · ${what}`);
    }
    for (const x of this.spec.sensors) {
      const st = (s.faults || []).find((f) => f.machine === x.name && f.fault && f.fault.stuck);
      set("sensor:" + x.name, !!st, x.name, `${(s.sensors || {})[x.name] ? "on" : "off"}${st ? ` · stuck ${st.fault.stuck}` : ""}`);
    }
    for (const f of this.spec.fixtures) {
      const st = (s.fixtures || {})[f.name] || {};
      set("fixture:" + f.name, false, f.name, `${st.filled || 0}/${f.count[0] * f.count[1]}${st.changing ? " · changing" : st.ready === false && !s.offline ? " · not ready" : ""}`);
    }
  }

  makeTrail(scene) {
    const ring = new Float32Array(TRAIL_N * 3), pos = new Float32Array(TRAIL_N * 3), col = new Float32Array(TRAIL_N * 4);
    const geo = new THREE.BufferGeometry();
    geo.setAttribute("position", new THREE.BufferAttribute(pos, 3));
    geo.setAttribute("color", new THREE.BufferAttribute(col, 4));
    const line = new THREE.Line(geo, new THREE.LineBasicMaterial({ vertexColors: true, transparent: true, opacity: 0.95, depthWrite: false, toneMapped: false }));
    line.frustumCulled = false;
    scene.add(line);
    const color = new THREE.Color(0xf2a93b);
    const ringMesh = new THREE.Mesh(new THREE.RingGeometry(0.018, 0.024, 40), new THREE.MeshBasicMaterial({ color: 0xf2a93b, transparent: true, opacity: 0.9, depthWrite: false, toneMapped: false, side: THREE.DoubleSide }));
    ringMesh.rotation.x = -Math.PI / 2;
    scene.add(ringMesh);
    const cross = new THREE.LineSegments(new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(-0.03, 0, 0), new THREE.Vector3(0.03, 0, 0),
      new THREE.Vector3(0, 0, -0.03), new THREE.Vector3(0, 0, 0.03), new THREE.Vector3(0, -0.03, 0), new THREE.Vector3(0, 0.03, 0)]),
    new THREE.LineBasicMaterial({ color: 0xf2a93b, transparent: true, opacity: 0.8, toneMapped: false }));
    scene.add(cross);
    const planned = new THREE.Line(new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(), new THREE.Vector3()]),
      new THREE.LineDashedMaterial({ color: 0xf2a93b, dashSize: 0.012, gapSize: 0.01, transparent: true, opacity: 0.75, toneMapped: false }));
    planned.frustumCulled = false;
    scene.add(planned);
    return { ring, pos, col, geo, line, color, head: 0, fill: 0, t: 0, ringMesh, cross, planned };
  }

  updateTrail(dt, s) {
    const tr = this.gl.trail;
    const tool = this.ms.toolWorld();
    tr.t += dt;
    if (tr.t > 1 / 90 && this.live) {
      tr.t = 0;
      tr.head = (tr.head + 1) % TRAIL_N;
      tr.fill = Math.min(TRAIL_N, tr.fill + 1);
      tr.ring.set([tool.x, tool.y, tool.z], tr.head * 3);
      for (let i = 0; i < tr.fill; i++) {
        const src = ((tr.head - tr.fill + 1 + i) % TRAIL_N + TRAIL_N) % TRAIL_N;
        tr.pos.set(tr.ring.subarray(src * 3, src * 3 + 3), i * 3);
        tr.col.set([tr.color.r, tr.color.g, tr.color.b, Math.pow(i / tr.fill, 1.6)], i * 4);
      }
      tr.geo.setDrawRange(0, tr.fill);
      tr.geo.attributes.position.needsUpdate = true;
      tr.geo.attributes.color.needsUpdate = true;
    }
    // The current move's target: where the drives are told to be.
    const J = s.joints || {};
    const dem = {};
    let off = 0;
    for (const n of JOINTS) {
      const j = J[n] || {};
      dem[n] = isNum(j.demand) ? j.demand : isNum(j.position) ? j.position : 0;
      off = Math.max(off, Math.abs(dem[n] - (isNum(j.position) ? j.position : dem[n])), Math.abs(j.velocity || 0) > 2 ? 1 : 0);
    }
    const show = prefs.path && this.live && off > 0.3;
    tr.ringMesh.visible = tr.cross.visible = tr.planned.visible = show;
    if (show) {
      const d = toolPoint(this.spec, dem);
      const p = this.ms.fromMachine(d[0], d[1], d[2]);
      const floor = this.ms.fromMachine(d[0], d[1], 0);
      tr.cross.position.copy(p);
      tr.ringMesh.position.set(floor.x, floor.y + 0.0015, floor.z);
      const pts = tr.planned.geometry.attributes.position;
      pts.setXYZ(0, tool.x, tool.y, tool.z);
      pts.setXYZ(1, p.x, p.y, p.z);
      pts.needsUpdate = true;
      tr.planned.computeLineDistances();
    }
  }

  frame(now) {
    const g = this.gl;
    const dt = Math.min(0.05, (now - this.last) / 1000);
    this.last = now;
    const s = this.current(now);
    this.shown = s;
    this.ms.pose(s, { blink: (now / 400) % 1 < 0.5 });
    this.updateTrail(dt, s);
    if (prefs.camera === "tool") {
      const tool = this.ms.toolWorld();
      const k = 1 - Math.exp(-dt * 4);
      g.controls.target.lerp(tool, k);
      g.camera.position.lerp(tool.clone().add(new THREE.Vector3(0.55, 0.28, 0.75)), k * 0.6);
    } else if (g.anim) {
      const a = g.anim;
      a.k = Math.min(1, a.k + dt / 1.1);
      const e = a.k < 0.5 ? 4 * a.k ** 3 : 1 - (-2 * a.k + 2) ** 3 / 2;
      g.camera.position.lerpVectors(a.fromP, a.toP, e);
      g.controls.target.lerpVectors(a.fromT, a.toT, e);
      if (a.k >= 1) g.anim = null;
    }
    g.controls.update();
    g.composer.render(dt);
    if (prefs.labels) g.labels.render(g.scene, g.camera);
    if (this.quality === "high" && this.watch.frame(dt) === "low") this.setQuality("low", true);
    else if (this.quality === "low") this.watch.frame(dt);
    if (this.watch.fps !== null) this.fpsEl.textContent = `${this.watch.fps.toFixed(0)} fps · ${this.quality === "high" ? "High" : "Low"}`;
  }
}

const problemText = (p) => (typeof p === "string" ? p : p && p.message ? (p.path ? `${p.path}: ${p.message}` : p.message) : JSON.stringify(p));

function errorText(e) {
  const msg = e.message || "";
  if (/no machine/.test(msg)) return `The runtime runs no machine on this network (${msg}).`;
  const kind = e.body && e.body.kind;
  const why = { closed: "port closed", unreachable: "host unreachable", token: "wrong token", timeout: "no answer",
    protocol: "not a CANopen diagnostics port", refused: "refused" }[kind];
  return `Not connected${why ? ` (${why})` : ""}: ${msg}. Retrying…`;
}
