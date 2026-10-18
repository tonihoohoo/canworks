"""Node-RED flow of a bridge config (modbus-bridge-map "Node-RED flow").

The flow is a client of canworks-bridge through the node-red-contrib-modbus
palette: one input register read node per suggested read channel, a decode
function that turns registers into one message per changed value on the link
out "canworks in" (topic = the register map row's name), and an encode
function behind the link in "canworks out" that sets a named output value and
writes the changed write channels. Outputs are read back from the bridge once
before the first write, a tick keeps the bridge's watchdog fed, and the
bridge's control and SDO blocks get "canworks nmt" and "canworks sdo" links.

The function bodies are generated JavaScript: a shared library (LIB) plus a
handler per node, with the map rows the node needs as a JSON constant. Tests
run them under `node` with a stub Node-RED context.
"""

import hashlib
import json
import os

from . import contract, modbusmap

DEFAULT_POLL_MS = 100
MIN_POLL_MS = 10
# How often the outputs are read until they are seeded from the bridge.
SEED_POLL_MS = 1000
DEFAULT_SDO_TIMEOUT_MS = 1000

REAL_TYPES = ("REAL32", "REAL64", "REAL", "LREAL")
SIGNED_PREFIXES = ("INTEGER", "SINT", "INT", "DINT", "LINT")
NMT_COMMANDS = {"run": 1, "idle": 2, "start": 3, "stop": 4, "preop": 5, "reset": 6, "reset_comm": 7}


class FlowError(ValueError):
    """The config is not a bridge config, or the options are out of range."""


def _kind(t):
    if t in REAL_TYPES:
        return "real"
    if t.startswith(SIGNED_PREFIXES):
        return "signed"
    return "unsigned"


def _number(v):
    if v in ("", None):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _spec_row(r):
    """The fields of a map row the JavaScript side needs."""
    out = {"n": r["name"], "b": r["byte"], "k": _kind(r["type"])}
    if r["table"] in ("discrete input", "coil"):
        out["bit"] = r["address"] - r["byte"] * 8
        out["k"] = "bit"
        out["size"] = 1
        out["regs"] = [r["byte"] // 2, r["byte"] // 2]
    else:
        size = 1 if r.get("byte_in_register") else r["count"] * 2
        out["size"] = size
        out["regs"] = [r["address"], r["address"] + r["count"] - 1]
        if size >= 4:
            out["lo"] = r["word_order"] == "low_first"
    scale, offset = _number(r["scale"]), _number(r["offset"])
    if scale is not None and scale != 1:
        out["s"] = scale
    if offset:
        out["o"] = offset
    if r["unit"]:
        out["u"] = r["unit"]
    return out


def _parse_host(text):
    """(host, port) of "host", "host:port" or "[v6]:port"; port None when
    not given."""
    text = text.strip()
    if text.startswith("["):
        host, _, rest = text[1:].partition("]")
        port = rest[1:] if rest.startswith(":") else ""
    elif text.count(":") == 1:
        host, port = text.split(":")
    else:
        host, port = text, ""
    if port:
        try:
            port = int(port)
        except ValueError:
            raise FlowError("bad port in %r" % text)
        if not 0 < port < 65536:
            raise FlowError("bad port in %r" % text)
    return host, port or None


def options(cfg, host=None, poll_ms=None):
    """(host, port, poll_ms, notes) for the flow: the bridge's listen address
    (127.0.0.1 for an all-addresses listen) unless `host` says otherwise, and
    the poll period kept between MIN_POLL_MS and a third of watchdog_ms."""
    b = cfg["bridge"]
    lhost, lport = _parse_host(b.get("listen", "0.0.0.0:502"))
    notes = []
    if lhost in ("0.0.0.0", "::", ""):
        lhost = "127.0.0.1"
    port = lport or 502
    if host:
        h, p = _parse_host(host)
        lhost, port = h or lhost, p or port
    watchdog = b.get("watchdog_ms", 1000)
    poll = DEFAULT_POLL_MS if poll_ms is None else poll_ms
    if not isinstance(poll, int) or isinstance(poll, bool):
        raise FlowError("the poll period must be a whole number of milliseconds")
    top = watchdog // 3 if watchdog else None
    want = poll
    if poll < MIN_POLL_MS:
        poll = MIN_POLL_MS
    if top is not None and poll > top:
        poll = max(MIN_POLL_MS, top)
    if poll != want:
        notes.append("poll period %d ms instead of %d ms (kept between %d ms and a third of the bridge's "
                      "watchdog_ms)" % (poll, want, MIN_POLL_MS))
    writers = b.get("writers", [])
    if not writers:
        notes.append("the bridge's 'writers' is empty, so it refuses the flow's writes; add Node-RED's address")
    elif lhost in ("127.0.0.1", "::1", "localhost") and not any(
            w.startswith("127.") or w in ("::1", "::1/128", "0.0.0.0/0", "::/0") for w in writers):
        notes.append("the flow connects over loopback but the bridge's 'writers' (%s) has no loopback address; "
                     "add \"127.0.0.1\" so its writes are accepted" % ", ".join(writers))
    return lhost, port, poll, notes


def spec(cfg, rows, poll_ms):
    """The constant every function node of the flow shares."""
    b = cfg["bridge"]
    nets = contract.networks(cfg)
    by_name = {r["name"]: r for r in rows}
    data = [r for r in rows if r["type"] != "BLOCK"]
    in_regs = out_regs = 0
    for r in rows:
        end = (r["byte"] // 2 + 1) if r["table"] in ("discrete input", "coil") else r["address"] + r["count"]
        if r["direction"] == "input":
            in_regs = max(in_regs, end)
        else:
            out_regs = max(out_regs, end)
    channels = modbusmap.suggest_channels(rows)

    def block(name):
        r = by_name.get(name)
        return r["byte"] if r else None

    live = []
    for r in rows:
        if r["name"].startswith("bridge.live_list."):
            net = next((n for n in nets if n["name"] == r["network"]), None)
            ids = sorted(n["node_id"] for n in (net["nodes"] if net else []) if isinstance(n, dict)
                         and isinstance(n.get("node_id"), int))
            live.append({"net": r["network"], "b": r["byte"], "nodes": ids})
    sdo_timeout = max([n["master"].get("sdo_timeout_ms", DEFAULT_SDO_TIMEOUT_MS)
                       for n in nets if n["role"] == "master"] or [DEFAULT_SDO_TIMEOUT_MS])
    watchdog = b.get("watchdog_ms", 1000)
    return {
        "unit": b.get("unit_id", 1),
        "inBytes": in_regs * 2,
        "outBytes": out_regs * 2,
        "inputs": [_spec_row(r) for r in data if r["direction"] == "input"],
        "outputs": [_spec_row(r) for r in data if r["direction"] == "output"],
        "read": [[s, c] for f, s, c, d in channels if d == "input"],
        "write": [[s, c] for f, s, c, d in channels if d == "output"],
        "status": block("bridge.status"),
        "control": block("bridge.control"),
        "sdoReq": block("bridge.sdo_bridge.request"),
        "sdoResp": block("bridge.sdo_bridge.response"),
        "live": live,
        "networks": {n["name"] or str(n["index"]): n["index"] for n in nets},
        "masters": [n["index"] for n in nets if n["role"] == "master"],
        "sdoTimeoutMs": sdo_timeout + 1000,
        "keepalive": bool(watchdog),
        "tickMs": min(poll_ms, watchdog // 3) if watchdog else poll_ms,
    }


# -- JavaScript ----------------------------------------------------------------

# Shared by every function node: the image helpers, value conversion and the
# write messages. `SPEC` is defined in front of it.
LIB = r"""
function be16(a, i) { return (a[i] << 8) | a[i + 1]; }
function put16(a, i, v) { a[i] = (v >> 8) & 255; a[i + 1] = v & 255; }
function be32(a, i) { return ((a[i] << 24) >>> 0) + ((a[i + 1] << 16) | (a[i + 2] << 8) | a[i + 3]); }
function put32(a, i, v) { put16(a, i, Math.floor(v / 65536) & 65535); put16(a, i + 2, v & 65535); }
function known(a, r) {
  for (let i = 0; i < r.size; i++) if (a[r.b + i] === null || a[r.b + i] === undefined) return false;
  return true;
}
// The value's bytes most significant first: the registers swapped back for low_first.
function valueBytes(a, r) {
  const out = a.slice(r.b, r.b + r.size);
  if (!r.lo) return out;
  const words = [];
  for (let i = 0; i < out.length; i += 2) words.push([out[i], out[i + 1]]);
  return [].concat.apply([], words.reverse());
}
function storeBytes(a, r, bytes) {
  let src = bytes;
  if (r.lo) {
    const words = [];
    for (let i = 0; i < bytes.length; i += 2) words.push([bytes[i], bytes[i + 1]]);
    src = [].concat.apply([], words.reverse());
  }
  for (let i = 0; i < src.length; i++) a[r.b + i] = src[i];
}
function decodeRow(a, r) {
  let v;
  if (r.k === "bit") return ((a[r.b] >> r.bit) & 1) === 1;
  const bytes = valueBytes(a, r);
  if (r.k === "real") {
    const dv = new DataView(new Uint8Array(bytes).buffer);
    v = r.size === 8 ? dv.getFloat64(0) : dv.getFloat32(0);
  } else if (r.size === 8) {
    let big = 0n;
    for (const x of bytes) big = (big << 8n) | BigInt(x);
    if (r.k === "signed") big = BigInt.asIntN(64, big);
    // Beyond 2^53 a decimal string: exact, and safe for the debug sidebar and context stores.
    v = (big <= BigInt(Number.MAX_SAFE_INTEGER) && big >= BigInt(Number.MIN_SAFE_INTEGER)) ? Number(big) : big.toString();
  } else {
    v = 0;
    for (const x of bytes) v = v * 256 + x;
    const bits = r.size * 8;
    if (r.k === "signed" && v >= Math.pow(2, bits - 1)) v -= Math.pow(2, bits);
  }
  if (r.s !== undefined || r.o !== undefined) {
    v = Number(v) * (r.s === undefined ? 1 : r.s) + (r.o || 0);
  }
  return v;
}
// Writes `value` into the image; returns an error text, or null.
function encodeRow(a, r, value) {
  if (r.k === "bit") {
    if (value !== true && value !== false && value !== 0 && value !== 1)
      return "needs true or false, not " + JSON.stringify(value);
    if (value === true || value === 1) a[r.b] |= (1 << r.bit); else a[r.b] &= ~(1 << r.bit) & 255;
    return null;
  }
  let v = value;
  if (typeof v === "string" && /^\s*-?\d+\s*$/.test(v) && r.k !== "real" && r.s === undefined && r.o === undefined)
    v = BigInt(v.trim());
  else if (typeof v === "string" && v.trim() !== "" && !isNaN(Number(v))) v = Number(v);
  if (typeof v !== "number" && typeof v !== "bigint") return "needs a number, not " + JSON.stringify(value);
  if (r.s !== undefined || r.o !== undefined) v = (Number(v) - (r.o || 0)) / (r.s === undefined ? 1 : r.s);
  const bytes = new Array(r.size).fill(0);
  if (r.k === "real") {
    if (typeof v === "bigint") v = Number(v);
    const dv = new DataView(new ArrayBuffer(r.size));
    if (r.size === 8) dv.setFloat64(0, v); else dv.setFloat32(0, v);
    for (let i = 0; i < r.size; i++) bytes[i] = dv.getUint8(i);
    storeBytes(a, r, bytes);
    return null;
  }
  if (typeof v === "number") {
    if (!isFinite(v)) return "needs a finite number";
    v = Math.round(v);
  }
  let big = BigInt(v);
  const bits = BigInt(r.size * 8);
  const lo = r.k === "signed" ? -(1n << (bits - 1n)) : 0n;
  const hi = r.k === "signed" ? (1n << (bits - 1n)) - 1n : (1n << bits) - 1n;
  if (big < lo || big > hi) return "is out of range " + lo + ".." + hi + ": " + value;
  big = BigInt.asUintN(Number(bits), big);
  for (let i = r.size - 1; i >= 0; i--) { bytes[i] = Number(big & 255n); big >>= 8n; }
  storeBytes(a, r, bytes);
  return null;
}
function writeMsgs(a, firstReg, lastReg) {
  const out = [];
  for (const ch of SPEC.write) {
    const s = ch[0], c = ch[1];
    if (lastReg < s || firstReg > s + c - 1) continue;
    const regs = [];
    for (let i = 0; i < c; i++) regs.push(be16(a, (s + i) * 2));
    out.push({ payload: { value: regs, fc: 16, unitid: SPEC.unit, address: s, quantity: c } });
  }
  return out;
}
function writeAll(a) { return writeMsgs(a, 0, 1 << 30); }
function outImage() { return flow.get("canworks_out") || null; }
function seeded() { return flow.get("canworks_seeded") === true; }
function netIndex(n) {
  if (typeof n === "number") return n;
  if (Object.prototype.hasOwnProperty.call(SPEC.networks, n)) return SPEC.networks[n];
  if (n === undefined && SPEC.masters.length === 1) return SPEC.masters[0];
  return null;
}
function nextCounter(a, at) { const c = (be16(a, at) + 1) & 65535; return c === 0 ? 1 : c; }
"""

DECODE = r"""
// Registers START.. of this read node into the input image, then one message
// per changed value on output 1 and SDO results on output 2.
let img = flow.get("canworks_in");
if (!img || img.length !== SPEC.inBytes) img = new Array(SPEC.inBytes).fill(null);
const regs = Array.isArray(msg.payload) ? msg.payload : [];
for (let i = 0; i < regs.length; i++) put16(img, (START + i) * 2, regs[i] & 65535);
flow.set("canworks_in", img);
const last = flow.get("canworks_last") || {};
const out = [], sdo = [];
function emit(topic, value, unit) {
  const key = (typeof value === "object" && value !== null) ? JSON.stringify(value) : value;
  if (Object.is(last[topic], key)) return;
  last[topic] = key;
  const m = { topic: topic, payload: value };
  if (unit) m.unit = unit;
  out.push(m);
}
let ready = 0;
for (const r of SPEC.inputs) {
  if (!known(img, r)) continue;
  ready++;
  emit(r.n, decodeRow(img, r), r.u);
}
let status = { fill: "green", shape: "dot", text: ready + " of " + SPEC.inputs.length + " values" };
if (SPEC.status !== null && known(img, { b: SPEC.status, size: 8 })) {
  const s = SPEC.status;
  const state = ({ 1: "running", 2: "watchdog", 3: "idle" })[img[s]] || ("state " + img[s]);
  emit("bridge.state", state);
  emit("bridge.clients", img[s + 1]);
  emit("bridge.command", { counter: be16(img, s + 4),
                           result: ["ok", "unknown command", "bad network", "bad node", "not a CANopen master network",
                                    "refused"][img[s + 6]] || ("result " + img[s + 6]) });
  status = state === "running"
    ? { fill: "green", shape: "dot", text: "running, " + img[s + 1] + " clients" }
    : { fill: "yellow", shape: "ring", text: "outputs off (" + state + ")" };
}
for (const l of SPEC.live) {
  if (!known(img, { b: l.b, size: 16 })) continue;
  for (const id of l.nodes) emit(l.net + ".node" + id + ".operational", ((img[l.b + (id >> 3)] >> (id & 7)) & 1) === 1);
}
const pending = flow.get("canworks_sdo_pending");
if (SPEC.sdoResp !== null && pending && known(img, { b: SPEC.sdoResp, size: 14 })) {
  const r = SPEC.sdoResp;
  if (be16(img, r) === pending.counter && (img[r + 2] === 2 || img[r + 2] === 3)) {
    flow.set("canworks_sdo_pending", null);
    const done = img[r + 2] === 2;
    const abort = be32(img, r + 4);
    sdo.push({ topic: pending.topic || "sdo", payload: done ? (pending.write ? true : be32(img, r + 8)) : null,
               sdo: { status: done ? "done" : "aborted", abort: done ? 0 : abort,
                      abortText: done ? "" : "0x" + abort.toString(16).padStart(8, "0"), request: pending.request } });
  }
}
flow.set("canworks_last", last);
node.status(status);
return [out, sdo];
"""

SEED = r"""
// Holding registers START.. read back once, so the first write after a
// restart carries what the bridge holds, not zeros.
const done = flow.get("canworks_seed") || {};
if (done[START]) return null;
let img = flow.get("canworks_out");
if (!img || img.length !== SPEC.outBytes) img = new Array(SPEC.outBytes).fill(0);
const regs = Array.isArray(msg.payload) ? msg.payload : [];
for (let i = 0; i < regs.length; i++) put16(img, (START + i) * 2, regs[i] & 65535);
done[START] = true;
flow.set("canworks_out", img);
flow.set("canworks_seed", done);
if (SPEC.write.every((ch) => done[ch[0]])) {
  flow.set("canworks_seeded", true);
  return { topic: "canworks_seeded" };
}
return null;
"""

ENCODE = r"""
// "canworks out": {topic: name, payload: value}. Also the tick (keepalive)
// and the "seeded" message from the read-back.
const rows = {};
for (const row of SPEC.outputs) rows[row.n] = row;
if (msg.topic === "canworks_tick") {
  if (!SPEC.keepalive || !seeded()) return null;
  return [writeAll(outImage())];
}
if (msg.topic === "canworks_seeded") {
  const img = outImage();
  const pend = flow.get("canworks_pending") || {};
  for (const name of Object.keys(pend)) encodeRow(img, rows[name], pend[name]);
  flow.set("canworks_pending", {});
  flow.set("canworks_out", img);
  node.status({ fill: "green", shape: "dot", text: "writing" });
  return [writeAll(img)];
}
const r = rows[msg.topic];
if (!r) {
  node.warn("canworks out: no output named " + JSON.stringify(msg.topic));
  return null;
}
if (!seeded()) {
  const probe = new Array(SPEC.outBytes).fill(0);
  const err = encodeRow(probe, r, msg.payload);
  if (err) { node.warn("canworks out: " + msg.topic + " " + err); return null; }
  const pend = flow.get("canworks_pending") || {};
  pend[msg.topic] = msg.payload;
  flow.set("canworks_pending", pend);
  node.status({ fill: "yellow", shape: "ring", text: "waiting for the bridge" });
  return null;
}
const img = outImage();
const err = encodeRow(img, r, msg.payload);
if (err) { node.warn("canworks out: " + msg.topic + " " + err); return null; }
flow.set("canworks_out", img);
return [writeMsgs(img, r.regs[0], r.regs[1])];
"""

NMT = r"""
// "canworks nmt": {payload: {network, node, command}}, command one of
// run, idle, start, stop, preop, reset, reset_comm. The bridge's answer
// comes back on "canworks in" as bridge.command.
const COMMANDS = %s;
const p = (msg.payload && typeof msg.payload === "object") ? msg.payload : {};
const cmd = COMMANDS[p.command];
if (cmd === undefined) { node.warn("canworks nmt: command must be one of " + Object.keys(COMMANDS).join(", ")); return null; }
const net = cmd <= 2 ? 0 : netIndex(p.network);
if (net === null) { node.warn("canworks nmt: unknown network " + JSON.stringify(p.network)); return null; }
const id = cmd <= 2 ? 0 : (p.node === undefined ? 0 : p.node);
if (!Number.isInteger(id) || id < 0 || id > 127) { node.warn("canworks nmt: node must be 0-127 (0: all)"); return null; }
if (!seeded()) { node.warn("canworks nmt: the bridge has not answered yet; nothing sent"); return null; }
const img = outImage();
const at = SPEC.control;
const counter = nextCounter(img, at);
put16(img, at, counter);
img[at + 2] = cmd; img[at + 3] = net; img[at + 4] = id; img[at + 5] = 0;
flow.set("canworks_out", img);
node.status({ fill: "blue", shape: "dot", text: p.command + " sent (" + counter + ")" });
return [writeMsgs(img, at >> 1, (at + 5) >> 1)];
"""

SDO = r"""
// "canworks sdo": {payload: {network, node, index, subindex, value?, length?}}.
// Without value a read, with it a write (length 1-4 bytes, default 4).
// One request at a time; results on output 2 ("canworks sdo result").
const queue = flow.get("canworks_sdo_queue") || [];
const now = Date.now();
const results = [];
if (msg.topic !== "canworks_tick") {
  const p = (msg.payload && typeof msg.payload === "object") ? msg.payload : {};
  const net = netIndex(p.network);
  const bad = net === null ? "unknown network " + JSON.stringify(p.network)
    : (!Number.isInteger(p.node) || p.node < 1 || p.node > 127) ? "node must be 1-127"
    : (!Number.isInteger(p.index) || p.index < 0 || p.index > 65535) ? "index must be 0-0xFFFF"
    : (!Number.isInteger(p.subindex || 0) || (p.subindex || 0) < 0 || (p.subindex || 0) > 255) ? "subindex must be 0-255"
    : (p.value !== undefined && (!Number.isInteger(p.length === undefined ? 4 : p.length) ||
       (p.length === undefined ? 4 : p.length) < 1 || (p.length === undefined ? 4 : p.length) > 4)) ? "length must be 1-4"
    : (p.value !== undefined && (!Number.isInteger(p.value) || p.value < -2147483648 || p.value > 4294967295))
      ? "value must be a 32-bit integer" : null;
  if (bad) { node.warn("canworks sdo: " + bad); return null; }
  queue.push({ topic: msg.topic, request: p, net: net });
}
let pending = flow.get("canworks_sdo_pending");
if (pending && now - pending.t > SPEC.sdoTimeoutMs) {
  results.push({ topic: pending.topic || "sdo", payload: null,
                 sdo: { status: "timeout", abort: 0, abortText: "", request: pending.request } });
  pending = null;
  flow.set("canworks_sdo_pending", null);
}
let writes = [];
if (!pending && queue.length && seeded()) {
  const q = queue.shift();
  const p = q.request;
  const img = outImage();
  const at = SPEC.sdoReq;
  const counter = nextCounter(img, at);
  const write = p.value !== undefined;
  const len = p.length === undefined ? 4 : p.length;
  put16(img, at, counter);
  img[at + 2] = write ? 2 : 1; img[at + 3] = q.net; img[at + 4] = p.node; img[at + 5] = p.subindex || 0;
  put16(img, at + 6, p.index); img[at + 8] = write ? len : 0; img[at + 9] = 0;
  put32(img, at + 10, write ? (p.value >>> 0) : 0);
  flow.set("canworks_out", img);
  flow.set("canworks_sdo_pending", { counter: counter, t: now, topic: q.topic, write: write, request: p });
  writes = writeMsgs(img, at >> 1, (at + 13) >> 1);
}
flow.set("canworks_sdo_queue", queue);
return [writes, results];
"""

START_CODE = r"""
flow.set("canworks_in", null);
flow.set("canworks_last", {});
flow.set("canworks_out", null);
flow.set("canworks_seed", {});
flow.set("canworks_seeded", false);
flow.set("canworks_pending", {});
flow.set("canworks_sdo_queue", []);
flow.set("canworks_sdo_pending", null);
node.status({ fill: "yellow", shape: "ring", text: "waiting for the bridge" });
"""


def function_body(spec_obj, handler, start=None):
    """The JavaScript of one function node: SPEC, START, the library and the handler."""
    head = "const SPEC = %s;\n" % json.dumps(spec_obj, sort_keys=True)
    if start is not None:
        head += "const START = %d;\n" % start
    return head + LIB + handler


# -- the flow ----------------------------------------------------------------

def flow(cfg, name="canworks", host=None, poll_ms=None):
    """(nodes, notes, spec): the Node-RED flow of a bridge config as a list of node
    objects (one tab plus a Modbus client config node), and notes for the user.
    Raises FlowError for a config that is not a bridge config or whose map
    breaks the byte rules."""
    if not modbusmap.is_bridge_config(cfg):
        raise FlowError("not a bridge config: a Node-RED flow needs a top-level \"bridge\" object "
                        "(docs/node-red.md)")
    try:
        rows = modbusmap.register_map(cfg)
    except modbusmap.MapError as e:
        raise FlowError(str(e))
    h, port, poll, notes = options(cfg, host, poll_ms)
    sp = spec(cfg, rows, poll)

    def nid(key):
        return hashlib.sha1(("canworks-node-red:%s:%s" % (name, key)).encode("utf-8")).hexdigest()[:16]

    tab = nid("tab")
    client = nid("client")
    decode_ids = [nid("decode:%d" % s) for s, c in sp["read"]]
    encode, nmt, sdo = nid("encode"), nid("nmt"), nid("sdo")
    write = nid("write")
    link_in, link_out = nid("link:in"), nid("link:out")
    sdo_result = nid("link:sdo-result")
    has_control = sp["control"] is not None
    has_sdo = sp["sdoReq"] is not None and sp["sdoResp"] is not None
    nodes = [{
        "id": tab, "type": "tab", "label": "canworks %s" % name, "disabled": False,
        "info": ("canworks Modbus bridge at %s:%d, generated by canworks-deploy --export-nodered.\n\n"
                 "Link to \"canworks in\" for values (msg.topic = name, msg.payload = value), send "
                 "{topic, payload} to \"canworks out\" to set an output. Needs node-red-contrib-modbus. "
                 "Export again after changing the config." % (h, port)),
    }, {
        "id": client, "type": "modbus-client", "name": "canworks bridge %s" % name, "clienttype": "tcp",
        "bufferCommands": True, "stateLogEnabled": False, "queueLogEnabled": False, "failureLogEnabled": True,
        "tcpHost": h, "tcpPort": str(port), "tcpType": "DEFAULT", "serialPort": "", "serialType": "RTU-BUFFERD",
        "serialBaudrate": "9600", "serialDatabits": "8", "serialStopbits": "1", "serialParity": "none",
        "serialConnectionDelay": "100", "serialAsciiResponseStartDelimiter": "0x3A",
        "unit_id": str(sp["unit"]), "commandDelay": "1", "clientTimeout": "1000",
        "reconnectOnTimeout": True, "reconnectTimeout": "2000", "parallelUnitIdsAllowed": True,
        "showErrors": False, "showWarnings": True, "showLogs": False,
    }]

    def common(node_id, typ, label, x, y, wires):
        return {"id": node_id, "type": typ, "z": tab, "name": label, "x": x, "y": y, "wires": wires}

    def func(node_id, label, body, outputs, x, y, wires, init=""):
        n = common(node_id, "function", label, x, y, wires)
        n.update({"func": body, "outputs": outputs, "timeout": 0, "noerr": 0, "initialize": init,
                  "finalize": "", "libs": []})
        return n

    def reader(node_id, label, data_type, start, count, rate, x, y, target):
        n = common(node_id, "modbus-read", label, x, y, [[target], []])
        n.update({"topic": label, "showStatusActivities": False, "logIOActivities": False, "showErrors": False,
                  "showWarnings": True, "unitid": "", "dataType": data_type, "adr": str(start),
                  "quantity": str(count), "rate": str(rate), "rateUnit": "ms", "delayOnStart": False,
                  "startDelayTime": "", "server": client, "useIOFile": False, "ioFile": "",
                  "useIOForPayload": False, "emptyMsgOnFail": False})
        return n

    y = 60
    for i, (start, count) in enumerate(sp["read"]):
        read_id = nid("read:%d" % start)
        nodes.append(reader(read_id, "inputs %d-%d" % (start, start + count - 1), "InputRegister", start, count,
                            poll, 170, y, decode_ids[i]))
        nodes.append(func(decode_ids[i], "decode %d-%d" % (start, start + count - 1),
                          function_body(sp, DECODE, start), 2, 420, y, [[link_out], [sdo_result] if has_sdo else []],
                          START_CODE if i == 0 else ""))
        y += 60
    out_link = common(link_out, "link out", "canworks in", 650, 60, [])
    out_link.update({"mode": "link", "links": []})
    nodes.append(out_link)
    if has_sdo:
        res = common(sdo_result, "link out", "canworks sdo result", 650, 120, [])
        res.update({"mode": "link", "links": []})
        nodes.append(res)

    if sp["write"]:
        y += 40
        writer = common(write, "modbus-flex-write", "write outputs", 690, y + 60, [[], []])
        writer.update({"showStatusActivities": False, "showErrors": False, "showWarnings": True, "server": client,
                       "emptyMsgOnFail": False, "keepMsgProperties": False, "delayOnStart": False,
                       "startDelayTime": ""})
        for start, count in sp["write"]:
            seed_id = nid("seed:%d" % start)
            nodes.append(reader(nid("readback:%d" % start), "read back outputs %d-%d" % (start, start + count - 1),
                                "HoldingRegister", start, count, SEED_POLL_MS, 170, y, seed_id))
            nodes.append(func(seed_id, "seed %d-%d" % (start, start + count - 1), function_body(sp, SEED, start),
                              1, 420, y, [[encode]], "" if sp["read"] else START_CODE))
            y += 60
        tick = nid("tick")
        tick_node = common(tick, "inject", "tick", 170, y, [[encode] + ([sdo] if has_sdo else [])])
        tick_node.update({"props": [{"p": "topic", "vt": "str"}], "repeat": "%g" % (sp["tickMs"] / 1000.0),
                          "crontab": "", "once": True, "onceDelay": "1", "topic": "canworks_tick"})
        nodes.append(tick_node)
        y += 60
        in_link = common(link_in, "link in", "canworks out", 170, y, [[encode]])
        in_link["links"] = []
        nodes.append(in_link)
        nodes.append(func(encode, "encode", function_body(sp, ENCODE), 1, 420, y, [[write]]))
        nodes.append(writer)
        y += 60
        if has_control:
            nmt_in = nid("link:nmt")
            n = common(nmt_in, "link in", "canworks nmt", 170, y, [[nmt]])
            n["links"] = []
            nodes.append(n)
            nodes.append(func(nmt, "nmt", function_body(sp, NMT % json.dumps(NMT_COMMANDS)), 1, 420, y, [[write]]))
            y += 60
        if has_sdo:
            sdo_in = nid("link:sdo")
            n = common(sdo_in, "link in", "canworks sdo", 170, y, [[sdo]])
            n["links"] = []
            nodes.append(n)
            nodes.append(func(sdo, "sdo", function_body(sp, SDO), 2, 420, y, [[write], [sdo_result]]))
    return nodes, notes, sp


def export(cfg, path, name=None, host=None, poll_ms=None):
    """Writes the flow to `path`; returns (number of inputs, number of outputs, notes)."""
    stem = os.path.splitext(os.path.basename(path))[0]
    for suffix in ("_node-red", "-node-red"):
        if stem.endswith(suffix) and len(stem) > len(suffix):
            stem = stem[:-len(suffix)]
    stem = name or stem or "canworks"
    nodes, notes, sp = flow(cfg, stem, host, poll_ms)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(to_json(nodes))
    return len(sp["inputs"]), len(sp["outputs"]), notes


def to_json(nodes):
    return json.dumps(nodes, indent=2) + "\n"
