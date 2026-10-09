// Machine tab scene (canopen-machine-view "Built-in gantry drawing" and
// "Smooth motion from snapshots"; docs/simulator.md): the 3D model of a
// machine file built from its kind and dimensions, posed from sim_machine
// snapshots, and the snapshot interpolator. No renderer here, so the page
// tests build and pose it without WebGL; machine_view.js draws it.
//
// Units: the scene is in metres with y up. Machine x is scene x, machine y
// is scene z, and a height above the table top is scene y above the table.
import * as THREE from "./three/build/three.module.min.js";
import { RoundedBoxGeometry } from "./three/addons/geometries/RoundedBoxGeometry.js";

export { THREE };

// The view draws this far behind the newest snapshot (microseconds).
export const DELAY_US = 100000;
export const JOINTS = ["x", "y", "z"];

const mm = (v) => v / 1000;
const isNum = (v) => typeof v === "number" && Number.isFinite(v);
const nums = (v, n, dflt) => (Array.isArray(v) && v.length === n && v.every(isNum) ? v.slice() : dflt.slice());
const obj = (v) => (v && typeof v === "object" && !Array.isArray(v) ? v : {});

// ---------------------------------------------------------------------------
// The machine file with the simulator's defaults (plugin/src/canopen/sim/sim_machine.h)
// and a drawing size for every part the file leaves out.

export function machineSpec(file) {
  const m = obj(file);
  const spec = { name: typeof m.name === "string" ? m.name : "", kind: m.kind || "gantry_xyz", joints: {} };
  for (const n of JOINTS) {
    const j = obj(obj(m.joints)[n]);
    spec.joints[n] = {
      name: n, node: Number.isInteger(j.node) ? j.node : null,
      travel: nums(j.travel, 2, [0, n === "z" ? 300 : 500]),
      counts_per_mm: isNum(j.counts_per_mm) && j.counts_per_mm > 0 ? j.counts_per_mm : 1000,
      offset_mm: isNum(j.offset_mm) ? j.offset_mm : 0,
      direction: j.direction === -1 ? -1 : 1,
      down: j.down === true,
      home_flag: isNum(j.home_flag) ? j.home_flag : null,
      limits: nums(j.limits, 2, []), hard_stops: nums(j.hard_stops, 2, []),
    };
  }
  const t = obj(m.tool);
  spec.tool = {
    present: m.tool !== undefined, close: t.close || null, gripped: t.gripped || null,
    stroke_ms: isNum(t.stroke_ms) ? t.stroke_ms : 120,
    open_mm: isNum(t.open_mm) ? t.open_mm : 96, closed_mm: isNum(t.closed_mm) ? t.closed_mm : 0,
    axis: t.axis === "y" ? "y" : "x", offset: nums(t.offset, 3, [0, 0, 300]), finger: nums(t.finger, 3, [12, 30, 60]),
  };
  spec.parts = {};
  for (const [k, p] of Object.entries(obj(m.parts))) spec.parts[k] = { size: nums(obj(p).size, 3, [80, 60, 50]) };
  if (!Object.keys(spec.parts).length) spec.parts.part = { size: [80, 60, 50] };
  const list = (v) => (Array.isArray(v) ? v.filter((x) => x && typeof x === "object") : []);
  spec.conveyors = list(m.conveyors).map((c, i) => ({
    name: typeof c.name === "string" ? c.name : `conveyor${i + 1}`,
    from: nums(c.from, 2, [0, 0]), to: nums(c.to, 2, [500, 0]),
    width: isNum(c.width) ? c.width : 120, height: isNum(c.height) ? c.height : 60,
    run: c.run || null, feed: c.feed && typeof c.feed === "object" ? c.feed : null,
  }));
  spec.sensors = list(m.sensors).map((s, i) => ({
    name: typeof s.name === "string" ? s.name : `sensor${i + 1}`,
    at: nums(s.at, 3, [0, 0, 0]), size: nums(s.size, 3, [10, 10, 10]),
    detects: s.detects === "tool" ? "tool" : "part", output: s.output || null,
  }));
  spec.fixtures = list(m.fixtures).map((f, i) => {
    const s = obj(f.slots);
    const ch = f.change && typeof f.change === "object" ? f.change : null;
    return {
      name: typeof f.name === "string" ? f.name : `fixture${i + 1}`,
      origin: nums(s.origin, 2, [0, 0]), pitch: nums(s.pitch, 2, [100, 100]),
      count: nums(s.count, 2, [1, 1]).map((v) => Math.max(1, Math.round(v))),
      height: isNum(f.height) ? f.height : 40, margin: isNum(f.margin) ? f.margin : 30,
      change: ch ? { request: ch.request || null, ready: ch.ready || null, move: nums(ch.move, 2, [0, 400]) } : null,
    };
  });
  spec.visual = visualSpec(spec, obj(m.visual));
  return spec;
}

// The size of the parts a fixture's slots take: the fed part, else the first kind.
export function slotPart(spec) {
  const fed = spec.conveyors.map((c) => c.feed && c.feed.part).find((k) => k && spec.parts[k]);
  return spec.parts[fed || Object.keys(spec.parts)[0]].size;
}

function visualSpec(spec, v) {
  const J = spec.joints, T = spec.tool;
  const x0 = J.x.travel[0] + T.offset[0], x1 = J.x.travel[1] + T.offset[0];
  const y0 = J.y.travel[0] + T.offset[1], y1 = J.y.travel[1] + T.offset[1];
  const f = obj(v.frame);
  const frame = {
    origin: nums(f.origin, 2, [x0 - 60, y0 - 60]), size: nums(f.size, 2, [x1 - x0 + 120, y1 - y0 + 120]),
    height: isNum(f.height) ? f.height : Math.max(500, T.offset[2] + 370), profile_mm: isNum(f.profile_mm) ? f.profile_mm : 40,
  };
  // Everything on the table, for the defaults of the table, fence and floor.
  const box = [frame.origin[0], frame.origin[1], frame.origin[0] + frame.size[0], frame.origin[1] + frame.size[1]];
  const grow = (x, y) => { box[0] = Math.min(box[0], x); box[1] = Math.min(box[1], y); box[2] = Math.max(box[2], x); box[3] = Math.max(box[3], y); };
  for (const c of spec.conveyors) { grow(c.from[0], c.from[1]); grow(c.to[0], c.to[1]); }
  const t = obj(v.table);
  const table = {
    origin: nums(t.origin, 2, [box[0] - 100, box[1] - 100]), size: nums(t.size, 2, [box[2] - box[0] + 200, box[3] - box[1] + 200]),
    height: isNum(t.height) ? t.height : 760,
  };
  const fe = obj(v.fence);
  const fence = {
    origin: nums(fe.origin, 2, [table.origin[0] - 250, table.origin[1] - 250]),
    size: nums(fe.size, 2, [table.size[0] + 500, table.size[1] + 500]), height: isNum(fe.height) ? fe.height : 1900,
  };
  const fl = obj(v.floor);
  const colors = Object.assign({ carriage: "#d9951f", frame: "#c9ced3", part: "#b98a55", pallet: "#3a6e5a", belt: "#1d2023" }, obj(v.colors));
  return {
    frame, table, fence, colors,
    floor: { size: nums(fl.size, 2, [fence.size[0] + 1500, fence.size[1] + 1500]) },
    stack_light: nums(v.stack_light, 2, [frame.origin[0] + frame.size[0] + 40, frame.origin[1] + frame.size[1] - 20]),
  };
}

// Joint positions at home: the home flag inside the travel, else the
// travel's low end.
export function homePositions(spec) {
  const out = {};
  for (const n of JOINTS) {
    const j = spec.joints[n];
    const h = j.home_flag === null ? j.travel[0] : j.home_flag;
    out[n] = Math.min(j.travel[1], Math.max(j.travel[0], h));
  }
  return out;
}

// The tool point (x, y, height above the table top) of joint positions in mm.
export function toolPoint(spec, pos) {
  const o = spec.tool.offset;
  return [o[0] + pos.x, o[1] + pos.y, o[2] + (spec.joints.z.down ? -pos.z : pos.z)];
}

// A sim_machine answer for the machine standing at home, nothing powered:
// the offline preview.
export function homeSnapshot(spec) {
  const pos = homePositions(spec);
  const joints = {};
  for (const n of JOINTS) {
    const j = spec.joints[n];
    joints[n] = { node: j.node, position: pos[n], velocity: 0, demand: pos[n],
      actual_counts: Math.round(j.direction * (pos[n] - j.offset_mm) * j.counts_per_mm),
      state: "off", mode: 0, statusword: 0, fault: false };
  }
  const sensors = {}, conveyors = {}, fixtures = {};
  for (const s of spec.sensors) sensors[s.name] = false;
  for (const c of spec.conveyors) conveyors[c.name] = { running: false, travel: 0 };
  for (const f of spec.fixtures) fixtures[f.name] = { offset: [0, 0], ready: false, changing: false, filled: 0 };
  return { name: spec.name, kind: spec.kind, t_us: 0, seq: 0, joints,
    tool: { position: toolPoint(spec, pos), opening: spec.tool.open_mm, closed: false, holding: null },
    parts: [], sensors, conveyors, fixtures,
    counters: { fed: 0, picked: 0, placed: 0, misplaced: 0, dropped: 0, pallets: 0 }, faults: [], offline: true };
}

// ---------------------------------------------------------------------------
// Snapshot interpolation

const lerp = (a, b, k) => a + (b - a) * k;
const BELT_WRAP = 100000;  // conveyors' travel wraps here (sim_machine.cpp)

// The machine between snapshots a and b (k in 0..1): positions linear, parts
// matched by id, everything else (states, bits, counters) as a has it until
// b is reached.
export function interpolate(a, b, k) {
  if (!b || k <= 0) return a;
  if (k >= 1) return b;
  const out = Object.assign({}, a);
  out.t_us = lerp(a.t_us, b.t_us, k);
  out.joints = {};
  for (const [n, ja] of Object.entries(a.joints || {})) {
    const jb = (b.joints || {})[n];
    const j = Object.assign({}, ja);
    if (jb) for (const f of ["position", "velocity", "demand"]) if (isNum(ja[f]) && isNum(jb[f])) j[f] = lerp(ja[f], jb[f], k);
    if (jb && isNum(ja.actual_counts) && isNum(jb.actual_counts)) j.actual_counts = Math.round(lerp(ja.actual_counts, jb.actual_counts, k));
    out.joints[n] = j;
  }
  if (a.tool && b.tool) {
    out.tool = Object.assign({}, a.tool);
    if (Array.isArray(a.tool.position) && Array.isArray(b.tool.position)) out.tool.position = a.tool.position.map((v, i) => lerp(v, b.tool.position[i], k));
    if (isNum(a.tool.opening) && isNum(b.tool.opening)) out.tool.opening = lerp(a.tool.opening, b.tool.opening, k);
  }
  const later = new Map((b.parts || []).map((p) => [p.id, p]));
  out.parts = (a.parts || []).map((p) => {
    const q = later.get(p.id);
    if (!q || !Array.isArray(p.position) || !Array.isArray(q.position)) return p;
    return Object.assign({}, p, { position: p.position.map((v, i) => lerp(v, q.position[i], k)), yaw: lerp(p.yaw || 0, q.yaw || 0, k) });
  });
  out.conveyors = {};
  for (const [n, ca] of Object.entries(a.conveyors || {})) {
    const cb = (b.conveyors || {})[n];
    if (!cb || !isNum(ca.travel) || !isNum(cb.travel)) { out.conveyors[n] = ca; continue; }
    let d = cb.travel - ca.travel;
    if (d < -BELT_WRAP / 2) d += BELT_WRAP;
    out.conveyors[n] = Object.assign({}, ca, { travel: ca.travel + d * k });
  }
  out.fixtures = {};
  for (const [n, fa] of Object.entries(a.fixtures || {})) {
    const fb = (b.fixtures || {})[n];
    out.fixtures[n] = fb && Array.isArray(fa.offset) && Array.isArray(fb.offset)
      ? Object.assign({}, fa, { offset: fa.offset.map((v, i) => lerp(v, fb.offset[i], k)) }) : fa;
  }
  return out;
}

// The received snapshots, drawn a fixed delay behind the newest by their
// simulator time. The simulator's time now is taken as the newest
// snapshot's plus the wall time since it came; the drawing clock runs with
// the wall clock and is steered gently towards that time less the delay,
// so answers that come late or unevenly never show as a jump. It never goes
// back, and it stops at the newest snapshot, so the last pose holds when
// answers stop.
export class SnapshotBuffer {
  constructor(delayUs) {
    this.delay = delayUs === undefined ? DELAY_US : delayUs;
    this.reset();
  }

  reset() {
    this.list = [];
    this.play = null;     // the drawn simulator time (µs)
    this.wall = null;     // the wall time (ms) of the last sample
    this.arrived = null;  // the wall time (ms) the newest snapshot came
  }

  get newest() { return this.list.length ? this.list[this.list.length - 1] : null; }

  // Adds an answer that came at wall time nowMs; false for one that is not
  // newer than the newest. A time far behind the newest is a restarted
  // simulator: start again.
  push(s, nowMs) {
    if (!s || !isNum(s.t_us)) return false;
    const last = this.newest;
    if (last) {
      if (s.t_us + 1e6 < last.t_us) this.reset();
      else if (s.t_us <= last.t_us) return false;
    }
    this.list.push(s);
    this.arrived = isNum(nowMs) ? nowMs : null;
    if (this.list.length > 200) this.list.splice(0, this.list.length - 200);
    return true;
  }

  // The machine to draw at wall time nowMs (performance.now()).
  sample(nowMs) {
    const n = this.list.length;
    if (!n) return null;
    const newest = this.list[n - 1].t_us;
    if (this.arrived === null) this.arrived = nowMs;
    const since = Math.max(0, nowMs - this.arrived) * 1000;
    const target = Math.min(newest, newest + since - this.delay);
    if (this.play === null) {
      this.play = Math.max(target, this.list[0].t_us);
    } else {
      const dt = Math.max(0, Math.min(1000, nowMs - this.wall)) * 1000;
      let next = this.play + dt;
      const err = target - next;
      if (err > 1e6) next = target;  // far behind (the tab slept): catch up at once
      else next += err * Math.min(1, dt / 4e5);
      this.play = Math.max(this.play, Math.min(next, newest));
      if (target >= newest && newest - this.play < 2000) this.play = newest;
    }
    this.wall = nowMs;
    while (this.list.length > 2 && this.list[1].t_us <= this.play) this.list.shift();
    const a = this.list[0], b = this.list[1];
    if (!b || this.play <= a.t_us) return a;
    return interpolate(a, b, (this.play - a.t_us) / (b.t_us - a.t_us));
  }
}

// ---------------------------------------------------------------------------
// Textures and materials

// A small fixed random sequence, so the textures look the same every time.
function rng(seed) {
  let s = seed >>> 0;
  return () => { s = (s * 1664525 + 1013904223) >>> 0; return s / 4294967296; };
}

function canvasTex(w, h, draw, repeat) {
  const c = document.createElement("canvas");
  c.width = w;
  c.height = h;
  draw(c.getContext("2d", { willReadFrequently: true }), w, h);
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  t.anisotropy = 8;
  if (repeat) { t.wrapS = t.wrapT = THREE.RepeatWrapping; t.repeat.set(repeat[0], repeat[1]); }
  return t;
}

// Specks of n random pixels (or 2 x 2 blocks), darker or lighter by up to a.
function noise(g, w, h, n, a, light, rand) {
  const img = g.getImageData(0, 0, w, h), d = img.data;
  for (let i = 0; i < n; i++) {
    const x = (rand() * w) | 0, y = (rand() * h) | 0, s = rand() < 0.5 ? 1 : 2, k = rand() * a;
    for (let dy = 0; dy < s; dy++) {
      for (let dx = 0; dx < s; dx++) {
        const p = (((y + dy) % h) * w + ((x + dx) % w)) * 4;
        for (let c = p; c < p + 3; c++) d[c] = light ? d[c] + (255 - d[c]) * k : d[c] * (1 - k);
      }
    }
  }
  g.putImageData(img, 0, 0);
}

function textures() {
  const r = rng(7);
  const floor = canvasTex(1024, 1024, (g, w, h) => {
    g.fillStyle = "#3a3f44"; g.fillRect(0, 0, w, h);
    for (let i = 0; i < 40; i++) {  // trowel marks
      const x = r() * w, y = r() * h, rad = 80 + r() * 220;
      const gr = g.createRadialGradient(x, y, 0, x, y, rad);
      const l = r() < 0.5;
      gr.addColorStop(0, l ? "rgba(255,255,255,.035)" : "rgba(0,0,0,.05)"); gr.addColorStop(1, "rgba(0,0,0,0)");
      g.fillStyle = gr; g.fillRect(0, 0, w, h);
    }
    noise(g, w, h, 26000, 0.12, false, r); noise(g, w, h, 9000, 0.06, true, r);
    g.strokeStyle = "rgba(0,0,0,.35)"; g.lineWidth = 2; g.strokeRect(1, 1, w - 2, h - 2);  // saw-cut joints
  }, [3, 3]);
  const floorRough = canvasTex(512, 512, (g, w, h) => {
    g.fillStyle = "#9a9a9a"; g.fillRect(0, 0, w, h); noise(g, w, h, 12000, 0.25, true, r); noise(g, w, h, 12000, 0.25, false, r);
  }, [6, 6]);
  floorRough.colorSpace = THREE.NoColorSpace;
  const hazard = canvasTex(256, 32, (g, w, h) => {
    g.fillStyle = "#e3b324"; g.fillRect(0, 0, w, h); g.fillStyle = "#16181a";
    for (let x = -h; x < w + h; x += 32) { g.beginPath(); g.moveTo(x, h); g.lineTo(x + 16, h); g.lineTo(x + 16 + h, 0); g.lineTo(x + h, 0); g.fill(); }
    noise(g, w, h, 900, 0.25, false, r);
  }, [1, 1]);
  const belt = canvasTex(512, 64, (g, w, h) => {
    g.fillStyle = "#1d2023"; g.fillRect(0, 0, w, h);
    g.strokeStyle = "#2b2f33"; g.lineWidth = 3;
    for (let x = 0; x < w; x += 16) { g.beginPath(); g.moveTo(x, 0); g.lineTo(x + 8, h); g.stroke(); }
    noise(g, w, h, 2500, 0.3, false, r);
  }, [12, 1]);
  const kraft = canvasTex(512, 512, (g, w, h) => {
    g.fillStyle = "#b98a55"; g.fillRect(0, 0, w, h);
    for (let y = 0; y < h; y += 3) { g.fillStyle = `rgba(90,55,20,${r() * 0.08})`; g.fillRect(0, y, w, 2); }
    noise(g, w, h, 6000, 0.12, false, r);
    g.fillStyle = "rgba(225,205,165,.55)"; g.fillRect(w * 0.42, 0, w * 0.16, h);  // packing tape
    g.fillStyle = "#f2efe6"; g.fillRect(w * 0.1, h * 0.62, w * 0.26, h * 0.22);  // label
    g.fillStyle = "#222"; for (let i = 0; i < 14; i++) g.fillRect(w * 0.12 + i * 7, h * 0.66, i % 3 ? 3 : 5, h * 0.1);
  }, null);
  const mesh = canvasTex(256, 256, (g, w, h) => {
    g.clearRect(0, 0, w, h); g.strokeStyle = "#e8e8e8"; g.lineWidth = 3;
    for (let i = 0; i <= w; i += 32) { g.beginPath(); g.moveTo(i, 0); g.lineTo(i, h); g.stroke(); g.beginPath(); g.moveTo(0, i); g.lineTo(w, i); g.stroke(); }
  }, [6, 4]);
  return { floor, floorRough, hazard, belt, kraft, mesh };
}

// Every clear coat has some roughness: a mirror-sharp coat's highlight
// overflows the half-float render target, and bloom spreads that to black.
function materials(tex, colors) {
  const color = (c, d) => { try { return new THREE.Color(c); } catch (e) { return new THREE.Color(d); } };
  return {
    alu: new THREE.MeshPhysicalMaterial({ color: color(colors.frame, 0xc9ced3), metalness: 0.9, roughness: 0.34, clearcoatRoughness: 0.15, clearcoat: 0.15 }),
    aluDark: new THREE.MeshStandardMaterial({ color: 0x8c949b, metalness: 0.85, roughness: 0.42 }),
    steel: new THREE.MeshStandardMaterial({ color: 0xdfe3e6, metalness: 1.0, roughness: 0.16 }),
    black: new THREE.MeshPhysicalMaterial({ color: 0x15171a, metalness: 0.25, roughness: 0.42, clearcoat: 0.6, clearcoatRoughness: 0.3 }),
    blackMatte: new THREE.MeshStandardMaterial({ color: 0x1b1e21, metalness: 0.1, roughness: 0.8 }),
    plate: new THREE.MeshStandardMaterial({ color: 0x2b3237, metalness: 0.55, roughness: 0.5 }),
    carriage: new THREE.MeshPhysicalMaterial({ color: color(colors.carriage, 0xd9951f), metalness: 0.15, roughness: 0.38, clearcoatRoughness: 0.15, clearcoat: 0.5 }),
    bluePaint: new THREE.MeshPhysicalMaterial({ color: 0x2d5f8f, metalness: 0.35, roughness: 0.4, clearcoatRoughness: 0.15, clearcoat: 0.4 }),
    pallet: new THREE.MeshPhysicalMaterial({ color: color(colors.pallet, 0x3a6e5a), metalness: 0.0, roughness: 0.55, clearcoatRoughness: 0.15, clearcoat: 0.25 }),
    chain: new THREE.MeshStandardMaterial({ color: 0x1a1c1f, metalness: 0.05, roughness: 0.6 }),
    belt: new THREE.MeshStandardMaterial({ map: tex.belt, color: color(colors.belt, 0x1d2023).lerp(new THREE.Color(0xffffff), 0.85), roughness: 0.85, metalness: 0 }),
    part: new THREE.MeshStandardMaterial({ map: tex.kraft, color: color(colors.part, 0xb98a55).lerp(new THREE.Color(0xffffff), 0.6), roughness: 0.9, metalness: 0 }),
    fencePost: new THREE.MeshPhysicalMaterial({ color: 0xe0b42a, metalness: 0.1, roughness: 0.45, clearcoatRoughness: 0.15, clearcoat: 0.4 }),
    rubber: new THREE.MeshStandardMaterial({ color: 0x0f1012, roughness: 0.95 }),
    floor: new THREE.MeshStandardMaterial({ map: tex.floor, roughnessMap: tex.floorRough, roughness: 0.75, metalness: 0.0, color: 0xbfc4c9 }),
    fault: new THREE.MeshBasicMaterial({ color: 0xff3b30, transparent: true, opacity: 0.55, depthWrite: false, toneMapped: false }),
  };
}

const ledMat = (c) => new THREE.MeshStandardMaterial({ color: 0x111111, emissive: c, emissiveIntensity: 0, roughness: 0.3 });

// ---------------------------------------------------------------------------
// Geometry helpers

function shadowed(m) { m.castShadow = true; m.receiveShadow = true; return m; }
function add(parent, geo, mat, x = 0, y = 0, z = 0, name) {
  const m = shadowed(new THREE.Mesh(geo, mat));
  m.position.set(x, y, z);
  if (name) m.name = name;
  parent.add(m);
  return m;
}
function group(parent, name, x = 0, y = 0, z = 0) {
  const g = new THREE.Group();
  g.name = name || "";
  g.position.set(x, y, z);
  parent.add(g);
  return g;
}

// A T-slot extrusion outline (40 x 40 with 8 mm slots and a core bore,
// scaled to the size s in metres).
function tslotShape(s) {
  const k = s / 0.04;
  const h = s / 2, slot = 0.004 * k, lip = 0.0045 * k, inner = 0.006 * k, depth = 0.011 * k;
  const pts = [];
  const side = (rot) => {
    const local = [[-h, -h], [-slot, -h], [-slot, -h + lip], [-inner, -h + lip], [-inner, -h + depth], [inner, -h + depth], [inner, -h + lip], [slot, -h + lip], [slot, -h]];
    const c = Math.cos(rot), sn = Math.sin(rot);
    for (const [x, y] of local) pts.push([x * c - y * sn, x * sn + y * c]);
  };
  side(0); side(Math.PI / 2); side(Math.PI); side(-Math.PI / 2);
  const sh = new THREE.Shape();
  sh.moveTo(pts[0][0], pts[0][1]);
  for (let i = 1; i < pts.length; i++) sh.lineTo(pts[i][0], pts[i][1]);
  sh.closePath();
  const bore = new THREE.Path();
  bore.absarc(0, 0, 0.0034 * k, 0, Math.PI * 2, true);
  sh.holes.push(bore);
  return sh;
}

// The bevel leaves a few zero-area triangles with zero normals; a zero
// normal shades as NaN, and bloom spreads one such pixel over the frame.
// They take a normal of their triangle's other corners.
function fixNormals(g) {
  const n = g.attributes.normal;
  const len = (i) => Math.hypot(n.getX(i), n.getY(i), n.getZ(i));
  for (let i = 0; i < n.count; i++) {
    if (len(i) > 1e-6) continue;
    const t = i - (i % 3);
    const k = [t, t + 1, t + 2].find((j) => j < n.count && len(j) > 1e-6);
    if (k === undefined) n.setXYZ(i, 0, 0, 1);
    else n.setXYZ(i, n.getX(k) / len(k), n.getY(k) / len(k), n.getZ(k) / len(k));
  }
  n.needsUpdate = true;
}

class Profiles {
  constructor() { this.shapes = new Map(); this.geos = new Map(); }
  geo(len, size) {
    const key = `${size.toFixed(4)}:${len.toFixed(4)}`;
    if (this.geos.has(key)) return this.geos.get(key);
    if (!this.shapes.has(size)) this.shapes.set(size, tslotShape(size));
    const bevel = 0.02 * size;
    const g = new THREE.ExtrudeGeometry(this.shapes.get(size), { depth: len, bevelEnabled: true, bevelThickness: bevel, bevelSize: bevel, bevelSegments: 1, curveSegments: 10 });
    g.translate(0, 0, -len / 2);
    fixNormals(g);
    this.geos.set(key, g);
    return g;
  }
}

// ---------------------------------------------------------------------------
// The scene

// Builds the machine. Returns the scene parts and pose(); see the end.
export function buildMachine(file, options) {
  const opts = options || {};
  const spec = machineSpec(file);
  const V = spec.visual;
  const tex = textures();
  const M = materials(tex, V.colors);
  const prof = new Profiles();
  const TOP = mm(V.table.height);
  const P = mm(V.frame.profile_mm);
  const pickables = [];
  const anchors = [];      // label anchors: { key, kind, name, object }
  const lamps = { stack: {}, drives: {}, sensors: {} };
  const named = {};
  const reg = (o, name) => { o.name = name; named[name] = o; return o; };

  const scene = new THREE.Scene();
  const cell = reg(new THREE.Group(), "cell");
  // The middle of the frame is the scene's origin.
  const cx = mm(V.frame.origin[0] + V.frame.size[0] / 2), cz = mm(V.frame.origin[1] + V.frame.size[1] / 2);
  cell.position.set(-cx, 0, -cz);
  scene.add(cell);

  const profile = (parent, len, axis, x, y, z, mat, size) => {
    const m = add(parent, prof.geo(len, size || P), mat || M.alu, x, y, z);
    if (axis === "x") m.rotation.y = Math.PI / 2;
    else if (axis === "y") m.rotation.x = Math.PI / 2;
    return m;
  };
  const pickable = (g, data) => {
    g.userData = Object.assign(g.userData || {}, data);
    g.traverse((o) => { if (o.isMesh) pickables.push(o); });
    return g;
  };

  // ---- Floor, safety marking, fence ----
  {
    const fs = V.floor.size;
    const tcx = mm(V.table.origin[0] + V.table.size[0] / 2), tcz = mm(V.table.origin[1] + V.table.size[1] / 2);
    tex.floor.repeat.set(mm(fs[0]) / 1.3, mm(fs[1]) / 1.3);
    tex.floorRough.repeat.set(mm(fs[0]) / 0.7, mm(fs[1]) / 0.7);
    const floor = reg(new THREE.Mesh(new THREE.PlaneGeometry(mm(fs[0]), mm(fs[1])), M.floor), "floor");
    floor.rotation.x = -Math.PI / 2;
    floor.position.set(tcx, 0, tcz);
    floor.receiveShadow = true;
    cell.add(floor);
    // Hazard tape around the table.
    const tx0 = mm(V.table.origin[0]) - 0.3, tx1 = mm(V.table.origin[0] + V.table.size[0]) + 0.3;
    const tz0 = mm(V.table.origin[1]) - 0.3, tz1 = mm(V.table.origin[1] + V.table.size[1]) + 0.3;
    const tape = (x, z, len, alongZ) => {
      const t = tex.hazard.clone();
      t.wrapS = THREE.RepeatWrapping; t.repeat.set(len / 0.5, 1); t.needsUpdate = true;
      const m = new THREE.Mesh(new THREE.PlaneGeometry(len, 0.06), new THREE.MeshStandardMaterial({ map: t, roughness: 0.7 }));
      m.rotation.x = -Math.PI / 2;
      if (alongZ) m.rotation.z = Math.PI / 2;
      m.position.set(x, 0.0015, z);
      m.receiveShadow = true;
      cell.add(m);
    };
    tape((tx0 + tx1) / 2, tz0, tx1 - tx0, false); tape((tx0 + tx1) / 2, tz1, tx1 - tx0, false);
    tape(tx0, (tz0 + tz1) / 2, tz1 - tz0, true); tape(tx1, (tz0 + tz1) / 2, tz1 - tz0, true);

    // Guard fence: mesh panels on the back and the left side; the front and
    // the right, where the camera looks in from, stay open.
    const fence = group(cell, "fence");
    named.fence = fence;
    const H = mm(V.fence.height);
    const fx0 = mm(V.fence.origin[0]), fz0 = mm(V.fence.origin[1]);
    const fx1 = fx0 + mm(V.fence.size[0]), fz1 = fz0 + mm(V.fence.size[1]);
    const panel = (x, z, w, rotY) => {
      const g = group(fence, "fence-panel", x, 0, z);
      g.rotation.y = rotY;
      const t = tex.mesh.clone();
      t.wrapS = t.wrapT = THREE.RepeatWrapping; t.repeat.set(w / 0.4, (H - 0.2) / 0.4); t.needsUpdate = true;
      const pm = new THREE.Mesh(new THREE.PlaneGeometry(w - 0.06, H - 0.2),
        new THREE.MeshStandardMaterial({ map: t, alphaMap: t, transparent: true, depthWrite: false, color: 0x9aa3aa, metalness: 0.8, roughness: 0.4, side: THREE.DoubleSide }));
      pm.position.y = H / 2 + 0.05;
      g.add(pm);
      for (const sx of [-w / 2, w / 2]) {
        add(g, new THREE.BoxGeometry(0.04, H, 0.04), M.fencePost, sx, H / 2, 0);
        add(g, new THREE.BoxGeometry(0.12, 0.01, 0.12), M.fencePost, sx, 0.005, 0);
      }
      add(g, new THREE.BoxGeometry(w, 0.025, 0.025), M.fencePost, 0, H - 0.04, 0);
      add(g, new THREE.BoxGeometry(w, 0.025, 0.025), M.fencePost, 0, 0.15, 0);
    };
    const run = (a0, a1, at, alongZ) => {
      const n = Math.max(1, Math.ceil((a1 - a0) / 1.4));
      const w = (a1 - a0) / n;
      for (let i = 0; i < n; i++) {
        const c = a0 + w * (i + 0.5);
        if (alongZ) panel(at, c, w, Math.PI / 2); else panel(c, at, w, 0);
      }
    };
    run(fx0, fx1, fz0, false);
    run(fz0, fz1, fx0, true);

    // Ceiling light strips (they glow in the bloom).
    for (const dx of [-0.9, 0.9]) {
      const strip = new THREE.Mesh(new THREE.BoxGeometry(0.12, 0.03, 2.4), new THREE.MeshStandardMaterial({ color: 0x111111, emissive: 0xfff4e6, emissiveIntensity: 3.2 }));
      strip.position.set(cx + dx, 3.3, cz - 0.1);
      cell.add(strip);
    }
  }

  // ---- Table ----
  {
    const table = group(cell, "table");
    named.table = table;
    const x0 = mm(V.table.origin[0]), z0 = mm(V.table.origin[1]);
    const w = mm(V.table.size[0]), d = mm(V.table.size[1]);
    const lx = [x0 + P / 2 + 0.02, x0 + w - P / 2 - 0.02], lz = [z0 + P / 2 + 0.02, z0 + d - P / 2 - 0.02];
    for (const sx of lx) for (const sz of lz) {
      profile(table, TOP - 0.05, "y", sx, (TOP - 0.05) / 2 + 0.03, sz);
      add(table, new THREE.CylinderGeometry(0.03, 0.036, 0.03, 24), M.blackMatte, sx, 0.015, sz);  // levelling feet
    }
    for (const y of [0.18, TOP - 0.02 - P / 2]) {
      for (const sz of lz) profile(table, lx[1] - lx[0] - P, "x", (lx[0] + lx[1]) / 2, y, sz);
      for (const sx of lx) profile(table, lz[1] - lz[0] - P, "z", sx, y, (lz[0] + lz[1]) / 2);
    }
    add(table, new RoundedBoxGeometry(w, 0.02, d, 2, 0.004), M.plate, x0 + w / 2, TOP - 0.01, z0 + d / 2, "table-top");
    // Electrical cabinet under the table.
    add(table, new RoundedBoxGeometry(Math.min(0.6, w * 0.4), 0.42, Math.min(0.32, d * 0.4), 3, 0.01), M.bluePaint,
      x0 + w * 0.62, 0.43, z0 + d * 0.3, "cabinet");
  }

  // ---- Gantry ----
  const F = V.frame;
  const fx0 = mm(F.origin[0]), fx1 = mm(F.origin[0] + F.size[0]);
  const fz0 = mm(F.origin[1]), fz1 = mm(F.origin[1] + F.size[1]);
  const FH = TOP + mm(F.height);           // top of the Y beams
  const railTop = FH + 0.012;
  const carTop = railTop + 0.024;          // top of the Y carriages
  const bridgeLo = carTop + P / 2, bridgeHi = carTop + P * 1.5, bridgeTop = carTop + 2 * P;
  const bridgeZ = -(P / 2 + 0.0225);       // the bridge's centre behind the tool point
  const servo = (parent, x, y, z, joint) => {
    const g = group(parent, "motor:" + joint, x, y, z);
    add(g, new RoundedBoxGeometry(0.062, 0.062, 0.11, 3, 0.006), M.black, 0, 0, -0.055);
    add(g, new THREE.BoxGeometry(0.07, 0.07, 0.012), M.alu, 0, 0, 0.006);
    add(g, new THREE.CylinderGeometry(0.012, 0.012, 0.02, 20), M.steel, 0, 0, 0.022).rotation.x = Math.PI / 2;
    add(g, new THREE.BoxGeometry(0.03, 0.022, 0.03), M.blackMatte, 0, 0.042, -0.08);  // connector
    for (let i = 0; i < 4; i++) add(g, new THREE.BoxGeometry(0.064, 0.064, 0.003), M.blackMatte, 0, 0, -0.112 + i * 0.006);  // ribbed cap
    const led = add(g, new THREE.SphereGeometry(0.0045, 12, 8), ledMat(0x46d07f), 0.022, 0.033, -0.01, "lamp:" + joint);
    lamps.drives[joint] = led;
    named["motor:" + joint] = g;
    pickable(g, { joint, node: spec.joints[joint].node });
    return g;
  };
  const faultBar = (parent, name, geo, x, y, z) => {
    const m = new THREE.Mesh(geo, M.fault);
    m.position.set(x, y, z);
    m.visible = false;
    m.renderOrder = 2;
    parent.add(reg(m, "fault:" + name));
    return m;
  };

  const frame = group(cell, "frame");
  named.frame = frame;
  for (const sx of [fx0, fx1]) {
    for (const sz of [fz0, fz1]) {
      profile(frame, FH - P - TOP, "y", sx, (TOP + FH - P) / 2, sz);
      add(frame, new THREE.BoxGeometry(P * 2, 0.008, P * 2), M.aluDark, sx, TOP + 0.004, sz);
    }
    profile(frame, fz1 - fz0 + P, "z", sx, FH - P / 2, (fz0 + fz1) / 2);       // Y beam
    add(frame, new THREE.BoxGeometry(0.015, 0.012, fz1 - fz0), M.steel, sx, FH + 0.006, (fz0 + fz1) / 2, "rail:y");
    for (const sz of [fz0 - P / 2 - 0.002, fz1 + P / 2 + 0.002]) add(frame, new THREE.BoxGeometry(P + 0.002, P + 0.002, 0.004), M.blackMatte, sx, FH - P / 2, sz);
  }
  for (const sz of [fz0, fz1]) profile(frame, fx1 - fx0 - P, "x", (fx0 + fx1) / 2, FH - P / 2, sz);  // cross beams
  faultBar(frame, "y", new THREE.BoxGeometry(0.03, 0.02, fz1 - fz0), fx0, FH + 0.008, (fz0 + fz1) / 2);
  const yServo = servo(frame, fx1, FH - P / 2, fz0 - P / 2 - 0.006, "y");

  // Y energy chain on a tray outside the right beam; its moving end rides with the bridge.
  const yTrayX = fx1 + P / 2 + 0.04;
  add(frame, new THREE.BoxGeometry(0.05, 0.004, fz1 - fz0 + 0.06), M.aluDark, yTrayX, FH - 0.002, (fz0 + fz1) / 2);
  add(frame, new THREE.BoxGeometry(0.03, 0.004, 0.06), M.aluDark, (fx1 + yTrayX) / 2, FH - 0.002, fz0 + 0.03);

  // Bridge (moves with the tool's y).
  const bridge = group(cell, "carriage:y");
  named["carriage:y"] = bridge;
  const bLen = fx1 - fx0 + P + 0.04;
  const bMid = (fx0 + fx1) / 2;
  profile(bridge, bLen, "x", bMid, bridgeLo, bridgeZ);
  profile(bridge, bLen, "x", bMid, bridgeHi, bridgeZ);
  for (const sx of [fx0, fx1]) {
    add(bridge, new RoundedBoxGeometry(0.075, 0.03, 0.09, 2, 0.004), M.carriage, sx, railTop + 0.009, bridgeZ);
    add(bridge, new THREE.BoxGeometry(0.045, 0.018, 0.07), M.steel, sx, railTop + 0.002, bridgeZ);
  }
  const front = bridgeZ + P / 2;
  for (const y of [bridgeLo, bridgeHi]) add(bridge, new THREE.BoxGeometry(bLen - 0.08, 0.012, 0.004), M.steel, bMid, y, front + 0.002, "rail:x");
  faultBar(bridge, "x", new THREE.BoxGeometry(bLen - 0.06, 0.03, 0.01), bMid, (bridgeLo + bridgeHi) / 2, front + 0.004);
  const xServo = servo(bridge, fx0 - P / 2 - 0.02, (bridgeLo + bridgeHi) / 2, bridgeZ, "x");
  xServo.rotation.y = Math.PI / 2;
  add(bridge, new THREE.BoxGeometry(bLen - 0.04, 0.004, 0.05), M.aluDark, bMid, bridgeTop + 0.002, bridgeZ, "tray:x");

  // X carriage on the bridge's front.
  const xcar = group(bridge, "carriage:x");
  named["carriage:x"] = xcar;
  const plateZ = front + 0.004 + 0.0055;
  const plateH = bridgeTop - carTop + 0.03;
  add(xcar, new RoundedBoxGeometry(0.15, plateH, 0.011, 2, 0.003), M.carriage, 0, (carTop + bridgeTop) / 2, plateZ, "plate:x");
  for (const y of [bridgeLo, bridgeHi]) add(xcar, new THREE.BoxGeometry(0.05, 0.03, 0.008), M.steel, 0, y, plateZ + 0.0095);
  const chainR = 0.04;
  add(xcar, new RoundedBoxGeometry(0.05, 2 * chainR + 0.02, 0.012, 2, 0.003), M.carriage, -0.04, bridgeTop + chainR, bridgeZ + 0.03);
  pickable(xcar, { joint: "x", node: spec.joints.x.node });

  // Z column (moves with the tool's height).
  const zmax = spec.tool.offset[2] - (spec.joints.z.down ? spec.joints.z.travel[1] : -spec.joints.z.travel[0]);
  const fingerH = mm(spec.tool.finger[2]);
  const colBottom = fingerH + 0.06;
  const colLen = Math.max(0.3, bridgeTop + 0.08 - (TOP + mm(Math.min(zmax, spec.tool.offset[2])) + colBottom));
  const zcol = group(xcar, "carriage:z");
  named["carriage:z"] = zcol;
  profile(zcol, colLen, "y", 0, colBottom + colLen / 2, 0);
  add(zcol, new THREE.BoxGeometry(0.012, colLen, 0.008), M.steel, 0, colBottom + colLen / 2, -P / 2 - 0.004, "rail:z");
  add(zcol, new THREE.BoxGeometry(0.06, 0.012, 0.06), M.blackMatte, 0, colBottom + colLen + 0.006, 0);
  faultBar(zcol, "z", new THREE.BoxGeometry(P + 0.01, colLen, P + 0.01), 0, colBottom + colLen / 2, 0);
  const zServo = servo(zcol, 0, colBottom + colLen + 0.012, 0, "z");
  zServo.rotation.x = Math.PI / 2;
  pickable(zcol, { joint: "z", node: spec.joints.z.node });
  const toolObj = reg(new THREE.Object3D(), "tool_point");
  zcol.add(toolObj);

  // Gripper body and fingers (the fingers close along the tool's axis).
  const gripper = group(zcol, "gripper");
  named.gripper = gripper;
  const T = spec.tool;
  const fT = mm(T.finger[0]), fW = mm(T.finger[1]);
  const bodyW = mm(T.open_mm) + 2 * fT + 0.03, bodyD = fW + 0.03;
  const along = T.axis === "x" ? "x" : "z";
  const bodyGeo = along === "x" ? new RoundedBoxGeometry(bodyW, 0.045, bodyD, 3, 0.006) : new RoundedBoxGeometry(bodyD, 0.045, bodyW, 3, 0.006);
  add(gripper, bodyGeo, M.bluePaint, 0, fingerH + 0.0275, 0);
  add(gripper, new THREE.CylinderGeometry(0.03, 0.03, 0.01, 32), M.aluDark, 0, fingerH + 0.055, 0);
  const fingers = [];
  for (const s of [-1, 1]) {
    const f = group(gripper, s < 0 ? "finger:left" : "finger:right");
    named[f.name] = f;
    const g = (a, b, c) => (along === "x" ? [a, b, c] : [c, b, a]);
    add(f, new RoundedBoxGeometry(...g(fT, fingerH, fW), 2, 0.002), M.alu, ...g(s * fT / 2, fingerH / 2, 0));
    add(f, new THREE.BoxGeometry(...g(0.002, fingerH * 0.5, fW * 0.8)), M.rubber, ...g(-s * 0.001, fingerH * 0.3, 0));
    add(f, new THREE.BoxGeometry(...g(fT + 0.01, 0.012, 0.012)), M.aluDark, ...g(s * fT / 2, fingerH + 0.006, 0));
    fingers.push({ group: f, side: s });
  }

  // X energy chain on top of the bridge.
  const xr = spec.joints.x.travel;
  const xs0 = mm(T.offset[0] + (xr[0] + xr[1]) / 2), xtp = mm(xr[1] - xr[0]) / 2 + 0.05;
  const xChain = energyChain(bridge, M.chain, new THREE.Vector3(0, bridgeTop + 0.004 + 0.007, bridgeZ), new THREE.Vector3(1, 0, 0),
    new THREE.Vector3(0, 1, 0), xs0 - 0.04, chainR, xtp, 0.035, "chain:x");
  const yr = spec.joints.y.travel;
  const ys0 = mm(T.offset[1] + (yr[0] + yr[1]) / 2) + bridgeZ, ytp = mm(yr[1] - yr[0]) / 2 + 0.05;
  const yChainR = Math.max(0.03, (bridgeLo - FH) / 2);
  const yChain = energyChain(frame, M.chain, new THREE.Vector3(yTrayX, FH + 0.007, 0), new THREE.Vector3(0, 0, 1),
    new THREE.Vector3(0, 1, 0), ys0, yChainR, ytp, 0.04, "chain:y");
  // The Y chain's moving end bracket on the bridge.
  add(bridge, new THREE.BoxGeometry(yTrayX - fx1 + 0.03, 0.01, 0.05), M.aluDark, (fx1 + yTrayX) / 2, FH + 0.007 + 2 * yChainR + 0.012, bridgeZ);

  for (const [k, g, at] of [["x", xServo, [0, 0.06, -0.06]], ["y", yServo, [0, 0.06, -0.06]], ["z", gripper, [bodyW / 2 + 0.03, fingerH + 0.03, 0]]]) {
    const a = group(g, "label:" + k, ...at);
    anchors.push({ key: "joint:" + k, kind: "joint", name: k, object: a });
  }

  // ---- Conveyors ----
  const conveyors = spec.conveyors.map((c) => {
    const dx = c.to[0] - c.from[0], dy = c.to[1] - c.from[1];
    const len = mm(Math.hypot(dx, dy));
    const g = group(cell, "conveyor:" + c.name, mm(c.from[0]), TOP, mm(c.from[1]));
    named[g.name] = g;
    g.rotation.y = -Math.atan2(dy, dx);  // local +x runs from "from" to "to"
    const H = mm(c.height), W = mm(c.width);
    const t = tex.belt.clone();
    t.wrapS = t.wrapT = THREE.RepeatWrapping;
    t.repeat.set((len + 0.04) / 0.08, 1);
    t.needsUpdate = true;
    const beltMat = M.belt.clone();
    beltMat.map = t;
    const belt = add(g, new THREE.BoxGeometry(len + 0.04, 0.012, W), [M.blackMatte, M.blackMatte, beltMat, M.blackMatte, M.blackMatte, M.blackMatte],
      len / 2, H - 0.006, 0, "belt:" + c.name);
    named[belt.name] = belt;
    const sp = 0.03;  // side profile size
    for (const s of [-1, 1]) {
      profile(g, len + 0.04, "x", len / 2, Math.max(sp / 2, H - 0.012 - sp / 2), s * (W / 2 + sp / 2), M.alu, sp);
      add(g, new THREE.BoxGeometry(len + 0.04, 0.03, 0.003), M.steel, len / 2, H + 0.018, s * (W / 2 - 0.004));  // side guides
      add(g, new THREE.CylinderGeometry(0.008, 0.008, W, 16), M.steel, s < 0 ? -0.02 : len + 0.02, H - 0.008, 0).rotation.x = Math.PI / 2;
      if (H - 0.012 - sp > 0.01) {
        for (const x of [0.02, len - 0.02]) profile(g, H - 0.012 - sp, "y", x, (H - 0.012 - sp) / 2, s * (W / 2 + sp / 2), M.alu, sp);
      }
    }
    add(g, new THREE.BoxGeometry(0.01, 0.035, W + 0.01), M.carriage, len + 0.005, H + 0.0175, 0, "stop:" + c.name);  // end stop
    add(g, new THREE.CylinderGeometry(0.03, 0.03, 0.07, 24), M.black, 0.04, Math.max(0.03, H - 0.04), W / 2 + sp + 0.035).rotation.x = Math.PI / 2;  // gear motor
    return { spec: c, group: g, texture: t, length: len };
  });

  // ---- Sensors ----
  const beamMats = {};
  for (const s of spec.sensors) {
    const g = group(cell, "sensor:" + s.name, mm(s.at[0]), TOP, mm(s.at[1]));
    named[g.name] = g;
    const acrossX = s.size[0] > s.size[1];  // the beam runs along the box's long side
    const L = mm(Math.max(s.size[0], s.size[1]));
    const h = mm(s.at[2]);
    const at = (u, y) => (acrossX ? [u, y, 0] : [0, y, u]);
    add(g, new RoundedBoxGeometry(0.02, 0.03, 0.02, 2, 0.003), M.black, ...at(-L / 2 - 0.012, h), "eye:" + s.name);
    add(g, new THREE.BoxGeometry(0.004, 0.024, 0.016), M.steel, ...at(L / 2 + 0.006, h));  // reflector
    for (const u of [-L / 2 - 0.012, L / 2 + 0.006]) add(g, new THREE.BoxGeometry(0.006, h - 0.015, 0.006), M.aluDark, ...at(u, (h - 0.015) / 2));
    const led = add(g, new THREE.SphereGeometry(0.004, 10, 8), ledMat(0xffb347), ...at(-L / 2 - 0.012, h + 0.017), "lamp:" + s.name);
    lamps.sensors[s.name] = led;
    const mat = new THREE.MeshBasicMaterial({ color: 0xff3b2f, transparent: true, opacity: 0.18, depthWrite: false, toneMapped: false });
    beamMats[s.name] = mat;
    const beam = new THREE.Mesh(new THREE.CylinderGeometry(0.0012, 0.0012, L, 6), mat);
    if (acrossX) beam.rotation.z = Math.PI / 2; else beam.rotation.x = Math.PI / 2;
    beam.position.set(0, h, 0);
    g.add(reg(beam, "beam:" + s.name));
    const a = group(g, "label:" + s.name, ...at(-L / 2 - 0.012, h + 0.05));
    anchors.push({ key: "sensor:" + s.name, kind: "sensor", name: s.name, object: a });
  }

  // ---- Fixtures (pallets with slots) ----
  const psize = slotPart(spec);
  const tableRect = [mm(V.table.origin[0]), mm(V.table.origin[1]), mm(V.table.origin[0] + V.table.size[0]), mm(V.table.origin[1] + V.table.size[1])];
  const fixtures = spec.fixtures.map((f) => {
    const g = group(cell, "fixture:" + f.name);
    named[g.name] = g;
    const x0 = mm(f.origin[0] - psize[0] / 2 - f.margin), x1 = mm(f.origin[0] + (f.count[0] - 1) * f.pitch[0] + psize[0] / 2 + f.margin);
    const z0 = mm(f.origin[1] - psize[1] / 2 - f.margin), z1 = mm(f.origin[1] + (f.count[1] - 1) * f.pitch[1] + psize[1] / 2 + f.margin);
    const H = mm(f.height);
    add(g, new RoundedBoxGeometry(x1 - x0, H, z1 - z0, 3, Math.min(0.006, H / 3)), M.pallet, (x0 + x1) / 2, TOP + H / 2, (z0 + z1) / 2, "pallet:" + f.name);
    for (let j = 0; j < f.count[1]; j++) {
      for (let i = 0; i < f.count[0]; i++) {
        const k = i + j * f.count[0];
        const sx = mm(f.origin[0] + i * f.pitch[0]), sz = mm(f.origin[1] + j * f.pitch[1]);
        const slot = add(g, new THREE.BoxGeometry(mm(psize[0]) + 0.012, 0.002, mm(psize[1]) + 0.012), M.blackMatte, sx, TOP + H + 0.0005, sz, `slot:${f.name}:${k}`);
        named[slot.name] = slot;
        for (const [ox, oz] of [[-1, -1], [1, 1]]) {
          add(g, new THREE.CylinderGeometry(0.004, 0.004, 0.012, 12), M.steel, sx + ox * (mm(psize[0]) / 2 + 0.01), TOP + H + 0.006, sz + oz * (mm(psize[1]) / 2 + 0.01));
        }
      }
    }
    const a = group(g, "label:" + f.name, x1, TOP + H + 0.06, z1);
    anchors.push({ key: "fixture:" + f.name, kind: "fixture", name: f.name, object: a });
    // A roller bed off the table where the pallet goes during a change.
    if (f.change) {
      const mx = mm(f.change.move[0]), mz = mm(f.change.move[1]);
      const r = [Math.min(x0, x0 + mx), Math.min(z0, z0 + mz), Math.max(x1, x1 + mx), Math.max(z1, z1 + mz)];
      const bed = [r[0], r[1], r[2], r[3]];
      if (Math.abs(mz) >= Math.abs(mx)) {
        if (mz < 0) bed[3] = Math.min(r[3], tableRect[1]); else bed[1] = Math.max(r[1], tableRect[3]);
      } else if (mx < 0) bed[2] = Math.min(r[2], tableRect[0]); else bed[0] = Math.max(r[0], tableRect[2]);
      if (bed[2] - bed[0] > 0.05 && bed[3] - bed[1] > 0.05) {
        const rb = group(cell, "rollers:" + f.name);
        const alongZ = Math.abs(mz) >= Math.abs(mx);
        const L = alongZ ? bed[3] - bed[1] : bed[2] - bed[0];
        const W = alongZ ? bed[2] - bed[0] : bed[3] - bed[1];
        const mid = [(bed[0] + bed[2]) / 2, (bed[1] + bed[3]) / 2];
        for (const s of [-1, 1]) {
          const side = alongZ ? [mid[0] + s * W / 2, mid[1]] : [mid[0], mid[1] + s * W / 2];
          profile(rb, L, alongZ ? "z" : "x", side[0], TOP - 0.035, side[1]);
          for (const e of [-1, 1]) {
            const leg = alongZ ? [side[0], mid[1] + e * (L / 2 - P / 2)] : [mid[0] + e * (L / 2 - P / 2), side[1]];
            profile(rb, TOP - 0.055 - 0.03, "y", leg[0], (TOP - 0.055) / 2 + 0.015, leg[1]);
            add(rb, new THREE.CylinderGeometry(0.03, 0.036, 0.03, 24), M.blackMatte, leg[0], 0.015, leg[1]);
          }
        }
        for (let u = 0.03; u < L - 0.01; u += 0.058) {
          const c = add(rb, new THREE.CylinderGeometry(0.012, 0.012, W, 16), M.steel,
            alongZ ? mid[0] : bed[0] + u, TOP - 0.012, alongZ ? bed[1] + u : mid[1]);
          if (alongZ) c.rotation.z = Math.PI / 2; else c.rotation.x = Math.PI / 2;
        }
      }
    }
    return { spec: f, group: g };
  });

  // ---- Stack light ----
  {
    const [sx, sz] = V.stack_light;
    const g = group(cell, "stack_light", mm(sx), TOP, mm(sz));
    named.stack_light = g;
    add(g, new THREE.CylinderGeometry(0.04, 0.045, 0.012, 32), M.blackMatte, 0, 0.006, 0);
    add(g, new THREE.CylinderGeometry(0.012, 0.012, 0.28, 16), M.aluDark, 0, 0.152, 0);
    add(g, new THREE.CylinderGeometry(0.022, 0.022, 0.03, 24), M.blackMatte, 0, 0.305, 0);
    [["green", 0x46d07f], ["amber", 0xf2a93b], ["red", 0xec4a40]].forEach(([n, c], i) => {
      const m = new THREE.MeshPhysicalMaterial({ color: c, emissive: c, emissiveIntensity: 0, transparent: true, opacity: 0.9, roughness: 0.2 });
      lamps.stack[n] = add(g, new THREE.CylinderGeometry(0.024, 0.024, 0.042, 24), m, 0, 0.342 + i * 0.044, 0, "lamp:" + n);
    });
    add(g, new THREE.CylinderGeometry(0.024, 0.024, 0.008, 24), M.blackMatte, 0, 0.342 + 3 * 0.044 - 0.018, 0);
  }

  // ---- Lights ----
  const lights = group(scene, "lights");
  const key = new THREE.DirectionalLight(0xffeedd, 3.1);
  const span = Math.max(mm(V.table.size[0]), mm(V.table.size[1])) * 0.75 + 0.4;
  key.position.set(2.2, 4.2, 1.6);
  key.castShadow = true;
  key.shadow.mapSize.set(2048, 2048);
  Object.assign(key.shadow.camera, { left: -span, right: span, top: span, bottom: -span, near: 1, far: 9 });
  key.shadow.bias = -0.0004;
  key.shadow.normalBias = 0.02;
  key.shadow.radius = 4;
  lights.add(key);
  const rim = new THREE.DirectionalLight(0x9cc4ff, 0.9);
  rim.position.set(-3, 2.5, -2.5);
  lights.add(rim);
  lights.add(new THREE.HemisphereLight(0xcfd8e3, 0x2a2219, 0.35));
  const fill = new THREE.PointLight(0xffe2c4, 0.9, 6, 2);
  fill.position.set(-1.2, 2.6, 1.4);
  lights.add(fill);

  // ---- Parts ----
  const partGeos = new Map();
  const partMeshes = new Map();
  const partsGroup = group(cell, "parts");
  const partGeo = (kind) => {
    if (!partGeos.has(kind)) {
      const s = (spec.parts[kind] || { size: psize }).size;
      const g = new RoundedBoxGeometry(mm(s[0]), mm(s[2]), mm(s[1]), 2, 0.003);
      g.translate(0, mm(s[2]) / 2, 0);  // the part's position is its bottom
      partGeos.set(kind, g);
    }
    return partGeos.get(kind);
  };
  const syncParts = (parts) => {
    const live = new Set();
    for (const p of parts || []) {
      if (!p || !Array.isArray(p.position)) continue;
      live.add(p.id);
      let m = partMeshes.get(p.id);
      if (!m) {
        m = shadowed(new THREE.Mesh(partGeo(p.kind), M.part));
        m.name = "part:" + p.id;
        partsGroup.add(m);
        partMeshes.set(p.id, m);
      }
      m.position.set(mm(p.position[0]), TOP + mm(p.position[2]), mm(p.position[1]));
      m.rotation.y = -(p.yaw || 0) * Math.PI / 180;
      m.userData.state = p.state;
    }
    for (const [id, m] of partMeshes) if (!live.has(id)) { partsGroup.remove(m); partMeshes.delete(id); }
  };

  // ---- Pose ----
  const home = homePositions(spec);
  const driveColor = (j) => {
    if (!j || j.state === "off" || j.state === undefined) return null;
    if (j.fault || j.state === "fault" || j.state === "fault_reaction_active") return 0xff3b30;
    if (j.state === "operation_enabled") return 0x46d07f;
    return 0xf2a93b;
  };
  let lastTool = toolPoint(spec, home);

  // Places everything from a snapshot (a sim_machine answer, maybe
  // interpolated). opts.blink: the blink phase (true on) for fault lamps.
  function pose(snap, poseOpts) {
    const po = poseOpts || {};
    const s = snap || {};
    const J = s.joints || {};
    const pos = {};
    for (const n of JOINTS) pos[n] = J[n] && isNum(J[n].position) ? J[n].position : home[n];
    const tp = toolPoint(spec, pos);
    lastTool = tp;
    bridge.position.z = mm(tp[1]);
    xcar.position.x = mm(tp[0]);
    zcol.position.y = TOP + mm(tp[2]);
    const opening = s.tool && isNum(s.tool.opening) ? s.tool.opening : T.open_mm;
    for (const f of fingers) {
      const v = f.side * mm(opening / 2);
      if (along === "x") f.group.position.x = v; else f.group.position.z = v;
    }
    xChain(mm(tp[0]) - 0.04);
    yChain(mm(tp[1]) + bridgeZ);
    for (const c of conveyors) {
      const st = (s.conveyors || {})[c.spec.name] || {};
      const travel = isNum(st.travel) ? mm(st.travel) : 0;
      c.texture.offset.x = -((travel / 0.08) % 1);
    }
    for (const sn of spec.sensors) {
      const on = !!(s.sensors || {})[sn.name];
      beamMats[sn.name].opacity = on ? 0.85 : 0.18;
      lamps.sensors[sn.name].material.emissiveIntensity = on ? 3.2 : 0.3;
      named["beam:" + sn.name].userData.on = on;
    }
    for (const f of fixtures) {
      const st = (s.fixtures || {})[f.spec.name] || {};
      const off = Array.isArray(st.offset) ? st.offset : [0, 0];
      f.group.position.set(mm(off[0] || 0), 0, mm(off[1] || 0));
    }
    syncParts(s.parts);
    // Drive lamps, fault marking, stack light.
    const blink = po.blink !== false;
    let anyFault = false, allOn = true, anyOn = false;
    for (const n of JOINTS) {
      const j = J[n];
      const c = driveColor(j);
      const led = lamps.drives[n];
      const faulted = c === 0xff3b30;
      anyFault = anyFault || faulted;
      anyOn = anyOn || c !== null;
      allOn = allOn && c === 0x46d07f;
      if (c === null) led.material.emissiveIntensity = 0;
      else { led.material.emissive.setHex(c); led.material.emissiveIntensity = faulted && !blink ? 0.3 : 2.4; }
      named["fault:" + n].visible = faulted;
    }
    const st = lamps.stack;
    st.green.material.emissiveIntensity = anyOn && allOn ? 2.2 : 0;
    st.amber.material.emissiveIntensity = anyOn && !allOn && !anyFault ? 2.2 : 0;
    st.red.material.emissiveIntensity = anyFault && blink ? 3.0 : 0;
    st.green.userData.on = st.green.material.emissiveIntensity > 0;
    st.amber.userData.on = st.amber.material.emissiveIntensity > 0;
    st.red.userData.on = anyFault;
    return tp;
  }

  // The tool point in scene (world) coordinates.
  function toolWorld(target) {
    toolObj.updateWorldMatrix(true, false);
    return (target || new THREE.Vector3()).setFromMatrixPosition(toolObj.matrixWorld);
  }
  // A scene point back in machine mm: [x, y, height above the table].
  function toMachine(v) {
    cell.updateWorldMatrix(true, false);
    const l = cell.worldToLocal(v.clone());
    return [l.x * 1000, l.z * 1000, (l.y - TOP) * 1000];
  }
  // A machine point (mm) in scene coordinates.
  function fromMachine(x, y, h) {
    cell.updateWorldMatrix(true, false);
    return cell.localToWorld(new THREE.Vector3(mm(x), TOP + mm(h), mm(y)));
  }

  pose(homeSnapshot(spec));
  if (opts.update !== false) scene.updateMatrixWorld(true);

  const size = Math.max(mm(V.table.size[0]), mm(V.table.size[1]));
  const fsize = Math.max(mm(F.size[0]), mm(F.size[1]));
  return {
    spec, scene, cell, named, pickables, anchors, lamps, keyLight: key,
    tableTop: TOP, pose, toolWorld, toMachine, fromMachine, get tool() { return lastTool; },
    // Camera presets around the frame's middle.
    views: {
      target: new THREE.Vector3(0, TOP + mm(F.height) * 0.45, 0),
      overview: new THREE.Vector3(fsize * 1.35, TOP + fsize * 1.15, fsize * 1.75),
      top: new THREE.Vector3(0.001, TOP + size * 2.2, 0.25),
      topTarget: new THREE.Vector3(0, TOP, 0.02),
    },
    dispose() {
      scene.traverse((o) => {
        if (o.geometry) o.geometry.dispose();
        for (const m of [].concat(o.material || [])) { if (m.map) m.map.dispose(); m.dispose(); }
      });
      for (const t of Object.values(tex)) t.dispose();
    },
  };
}

// An energy chain: instanced links laid on the bend curve between a fixed
// end at fixedS and a moving end, along u with the bend towards n. Returns
// update(movingS) that lays the links.
function energyChain(parent, mat, origin, u, n, fixedS, radius, travelPart, width, name) {
  const pitch = 0.016;
  const length = travelPart + Math.PI * radius;
  const count = Math.floor(length / pitch);
  const geo = new RoundedBoxGeometry(pitch * 0.92, 0.014, width, 1, 0.002);
  const im = new THREE.InstancedMesh(geo, mat, count);
  im.name = name;
  im.castShadow = true;
  im.receiveShadow = true;
  im.frustumCulled = false;
  parent.add(im);
  const w = new THREE.Vector3().crossVectors(u, n).normalize();
  const m4 = new THREE.Matrix4(), pos = new THREE.Vector3(), t = new THREE.Vector3(), y = new THREE.Vector3();
  const update = (movingS) => {
    const a = Math.max(0, Math.min(travelPart, (movingS - fixedS + travelPart) / 2));
    for (let i = 0; i < count; i++) {
      const s = (i + 0.5) * pitch;
      let x, h, tx, th;
      if (s < a) { x = fixedS + s; h = 0; tx = 1; th = 0; }
      else if (s < a + Math.PI * radius) { const q = (s - a) / radius; x = fixedS + a + radius * Math.sin(q); h = radius - radius * Math.cos(q); tx = Math.cos(q); th = Math.sin(q); }
      else { x = fixedS + a - (s - a - Math.PI * radius); h = 2 * radius; tx = -1; th = 0; }
      pos.copy(origin).addScaledVector(u, x).addScaledVector(n, h);
      t.copy(u).multiplyScalar(tx).addScaledVector(n, th).normalize();
      y.crossVectors(w, t).normalize();
      m4.makeBasis(t, y, w).setPosition(pos);
      im.setMatrixAt(i, m4);
    }
    im.instanceMatrix.needsUpdate = true;
    im.userData.bend = fixedS + a;  // where the bend is, for the tests
  };
  return update;
}
