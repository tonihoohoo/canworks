// bridge.js - one connection to canworks-bridge for every canworks node
// (nodered-blocks): the poll cycle, the values in and out, and the bridge's
// control block, SDO registers, request mailboxes, receive mailbox, network
// info and cyclic jobs, shared by queueing instead of the PLC blocks'
// tickets. No Node-RED here, so the tests run it alone.
"use strict";

const { EventEmitter } = require("events");
const { ModbusClient } = require("./modbus");
const codec = require("./codec");
const L = require("./layout");
const T = require("./texts");

const RECONNECT_MIN_MS = 500;
const RECONNECT_MAX_MS = 5000;
const QUEUE_LIMIT = 64;
const NMT_COMMANDS = { run: 1, idle: 2, start: 3, stop: 4, preop: 5, reset: 6, reset_comm: 7 };

// A job's end with an ERROR_ID (the block family's numbers).
class CwError extends Error {
  constructor(errorId, text, extra) {
    super(text || T.errorText((extra && extra.family) || "", errorId));
    this.errorId = errorId;
    this.explicit = !!text;
    Object.assign(this, extra || {});
  }
}

function be16(img, i) {
  return (img[i] << 8) | img[i + 1];
}
function put16(img, i, v) {
  img[i] = (v >> 8) & 255;
  img[i + 1] = v & 255;
}
function be32(img, i) {
  return img[i] * 0x1000000 + ((img[i + 1] << 16) | (img[i + 2] << 8) | img[i + 3]);
}
function put32(img, i, v) {
  put16(img, i, Math.floor(v / 65536) & 65535);
  put16(img, i + 2, v & 65535);
}
// A counter the bridge has not seen: not the last one, not the echo, not 0.
function nextCounter(last, echo) {
  let c = (last + 1) & 0xffff;
  if (c === 0) c = 1;
  if (c === echo) c = (c + 1) & 0xffff || 1;
  return c;
}
// Ticks are milliseconds that wrap at 16 bits: a is at or after b.
function notBefore(a, b) {
  return ((a - b) & 0x8000) === 0;
}

class Bridge extends EventEmitter {
  // options: host, port, unit, pollMs, layout (from the flow export),
  // readOnly; clientFactory for tests.
  constructor(options) {
    super();
    this.setMaxListeners(0);
    const lay = options.layout;
    if (!lay || !Array.isArray(lay.inputs)) throw new Error("export the flow from canworks: the bridge node has no layout");
    this.lay = lay;
    this.host = options.host;
    this.port = options.port;
    this.unit = options.unit === undefined ? lay.unit : options.unit;
    const wd = lay.watchdogMs || 0;
    const top = wd ? Math.floor(wd / 3) : Infinity;
    this.pollMs = Math.max(10, Math.min(options.pollMs || 10, top));
    this.rewriteMs = wd ? Math.max(10, Math.floor(wd / 3)) : 0;
    this.readOnly = !!(options.readOnly || lay.readOnly);
    this.clientFactory = options.clientFactory || Bridge.clientFactory || ((o) => new ModbusClient(o));
    this.inImg = Buffer.alloc(lay.inBytes);
    this.outImg = Buffer.alloc(lay.outBytes);
    this.written = null; // what the bridge holds of outImg
    this.lastWrite = 0;
    this.outputs = new Map(lay.outputs.map((r) => [r.n, r]));
    this.inputNames = new Set(lay.inputs.map((r) => r.n)); // a map row wins over a network info topic
    this.last = new Map(); // topic -> value key, for "only changes"
    this.values = new Map(); // topic -> message
    this.pendingOut = new Map();
    this.state = "stopped";
    this.client = null;
    this.running = false;
    this.connected = false;
    this.seeded = false;
    this.haveInput = false;
    this.writesRefused = false;
    this.delay = RECONNECT_MIN_MS;
    this.timer = null;
    // Jobs and resources.
    this.mb = (lay.mailboxes && lay.mailboxes.requests) || [];
    this.mbBusy = this.mb.map(() => null); // the lease using it
    this.mbWait = [];
    this.mbCounter = this.mb.map(() => 0);
    this.sdoQueue = [];
    this.sdoBusy = null;
    this.sdoCounter = 0;
    this.nmtQueue = [];
    this.nmtBusy = null;
    this.ctlCounter = 0;
    this.receivers = new Set();
    this.rxBySlot = new Map();
    this.rxSeq = null;
    this.rxBusy = false;
    this.rxOrphans = new Set();
    this.ack = null; // {seq} to write
    this.cyclics = new Set();
    this.jobBySlot = new Map();
  }

  // ---- connection ----

  start() {
    if (this.running) return;
    this.running = true;
    this._connect();
  }

  stop() {
    this.running = false;
    clearTimeout(this.timer);
    if (this.client) this.client.close();
    this._down(new CwError(20, "the bridge node was stopped"));
    this._state("stopped", { fill: "grey", shape: "ring", text: "stopped" });
  }

  _state(name, status) {
    this.state = name;
    this.status = status;
    this.emit("state", status);
  }

  async _connect() {
    if (!this.running) return;
    this._state("connecting", { fill: "yellow", shape: "ring", text: "connecting to " + this.host + ":" + this.port });
    const c = this.clientFactory({ host: this.host, port: this.port, unit: this.unit, timeoutMs: 1000 });
    this.client = c;
    try {
      await c.connect();
    } catch (e) {
      this._retry(e);
      return;
    }
    c.on("close", (e) => {
      if (this.client === c) this._retry(e);
    });
    try {
      await this._seed();
    } catch (e) {
      c.close();
      return;
    }
    this.connected = true;
    this.delay = RECONNECT_MIN_MS;
    if (this.writesRefused) this._refused();
    else this._state("running", { fill: "green", shape: "dot", text: "connected" });
    this.emit("up");
    for (const rx of this.receivers) rx._open();
    this._loop();
  }

  _retry(err) {
    const was = this.connected;
    this.connected = false;
    this.seeded = false;
    this.haveInput = false;
    this.client = null;
    clearTimeout(this.timer);
    this._down(new CwError(20));
    if (!this.running) return;
    if (was) {
      this._zeroOnLoss();
      this.emit("down");
    }
    this._state("reconnecting", {
      fill: "red", shape: "ring",
      text: "reconnecting" + (err && err.message ? " (" + err.message + ")" : ""),
    });
    this.timer = setTimeout(() => this._connect(), this.delay);
    this.delay = Math.min(RECONNECT_MAX_MS, this.delay * 2);
  }

  // Every job and call running or waiting ends with `err`.
  _down(err) {
    for (const w of this.mbWait.splice(0)) w.reject(err);
    for (let m = 0; m < this.mb.length; m++) {
      const lease = this.mbBusy[m];
      if (lease && lease.expect) {
        const x = lease.expect;
        lease.expect = null;
        x.reject(err);
      }
    }
    for (const q of [this.sdoQueue, this.nmtQueue]) for (const j of q.splice(0)) j.reject(err);
    for (const j of [this.sdoBusy, this.nmtBusy]) if (j) j.reject(err);
    this.sdoBusy = this.nmtBusy = null;
    this.rxBySlot.clear();
    this.rxSeq = null;
    this.rxBusy = false;
    this.rxOrphans.clear();
    this.ack = null;
    this.jobBySlot.clear();
    for (const rx of this.receivers) rx._lost();
    for (const j of this.cyclics) j._lost();
  }

  // After a connect: read the outputs and requests back and write them
  // again unchanged. That write is the mailboxes' baseline after a bridge
  // restart, and leaves every counter as the bridge has it, so nothing old
  // runs again.
  async _seed() {
    const c = this.client;
    if (this.readOnly) {
      this.seeded = false;
      return;
    }
    for (const [s, n] of this.lay.write) {
      const words = await c.readHolding(s, n);
      for (let i = 0; i < n; i++) put16(this.outImg, (s + i) * 2, words[i]);
    }
    this.written = Buffer.from(this.outImg);
    try {
      for (const [s, n] of this.lay.write) await c.writeMultiple(s, this._words(s, n));
      this.writesRefused = false;
    } catch (e) {
      if (!/^exception/.test(e.code || "")) throw e;
      this.writesRefused = true;
    }
    this.lastWrite = Date.now();
    this.mbCounter = this.mb.map((m) => be16(this.outImg, m.req));
    if (this.lay.sdoReq !== null && this.lay.sdoReq !== undefined) this.sdoCounter = be16(this.outImg, this.lay.sdoReq);
    if (this.lay.control !== null && this.lay.control !== undefined) this.ctlCounter = be16(this.outImg, this.lay.control);
    for (const [name, value] of this.pendingOut) codec.encode(this.outImg, this.outputs.get(name), value);
    this.pendingOut.clear();
    this.seeded = true;
  }

  _words(start, n) {
    const out = new Array(n);
    for (let i = 0; i < n; i++) out[i] = be16(this.outImg, (start + i) * 2);
    return out;
  }

  async _loop() {
    const c = this.client;
    while (this.running && this.client === c && c.connected) {
      const t0 = Date.now();
      try {
        await this._cycle(c);
      } catch (e) {
        if (this.client === c) c.close();
        return;
      }
      const wait = Math.max(0, this.pollMs - (Date.now() - t0));
      await new Promise((r) => {
        this.timer = setTimeout(r, wait);
      });
    }
  }

  async _cycle(c) {
    for (const [s, n] of this.lay.read) {
      const words = await c.readInput(s, n);
      for (let i = 0; i < n; i++) put16(this.inImg, (s + i) * 2, words[i]);
    }
    this.haveInput = true;
    this._afterRead();
    if (this.readOnly || !this.seeded) return;
    if (this.writesRefused && Date.now() - this.lastWrite < 5000) return;
    const now = Date.now();
    const all = this.rewriteMs && now - this.lastWrite >= this.rewriteMs;
    for (const j of this.cyclics) j._keepalive();
    if (this.ack) {
      const a = this.lay.mailboxes.receive.ack;
      put16(this.outImg, a, this.ack.seq);
      put16(this.outImg, a + 2, 0);
      put16(this.outImg, a + 4, 0);
      this.ack = null;
    }
    let wrote = false;
    try {
      for (const [s, n] of this.lay.write) {
        const from = s * 2, to = (s + n) * 2;
        if (!all && this.written.compare(this.outImg, from, to, from, to) === 0) continue;
        await c.writeMultiple(s, this._words(s, n));
        this.outImg.copy(this.written, from, from, to);
        wrote = true;
      }
      if (this.writesRefused) {
        this.writesRefused = false;
        this._state("running", { fill: "green", shape: "dot", text: "connected" });
      }
    } catch (e) {
      if (!/^exception/.test(e.code || "")) throw e;
      this.writesRefused = true;
      this.lastWrite = now;
      this._refused();
      return;
    }
    if (wrote || all) this.lastWrite = now;
  }

  _refused() {
    this._state("refused", { fill: "red", shape: "dot", text: "writes refused: add Node-RED's address to the bridge's writers" });
  }

  // ---- inputs ----

  _emit(topic, value, unit) {
    const key = typeof value === "object" && value !== null ? JSON.stringify(value) : value;
    if (this.last.has(topic) && Object.is(this.last.get(topic), key)) return;
    this.last.set(topic, key);
    const msg = { topic, payload: value };
    if (unit) msg.unit = unit;
    this.values.set(topic, msg);
    this.emit("value", msg);
  }

  // The bridge is lost: status, state and timeout values, the live lists
  // and bridge.bus_ok read 0 or false; the other values keep their last.
  _zeroOnLoss() {
    const lay = this.lay;
    if (!lay) return;
    for (const r of lay.inputs) if (r.z) this._emit(r.n, r.k === "bit" ? false : 0, r.u);
    for (const l of lay.live || []) for (const id of l.nodes) this._emit(l.net + ".node" + id + ".operational", false);
    if (lay.status !== null && lay.status !== undefined) this._emit("bridge.bus_ok", false);
  }

  _afterRead() {
    const img = this.inImg, lay = this.lay;
    for (const r of lay.inputs) this._emit(r.n, codec.decode(img, r), r.u);
    if (lay.status !== null && lay.status !== undefined) {
      const s = lay.status;
      const state = { 1: "running", 2: "watchdog", 3: "idle", 4: "map mismatch", 5: "plc stopped" }[img[s]] || "state " + img[s];
      this._emit("bridge.state", state);
      this._emit("bridge.clients", img[s + 1]);
      // Byte 7 bit 1: a network's bus is down, missing or bus-off.
      this._emit("bridge.bus_ok", (img[s + 7] & 2) === 0);
      this._emit("bridge.command", { counter: be16(img, s + 4), result: img[s + 6], text: T.controlResult(img[s + 6]) });
      this._nmtAnswer(be16(img, s + 4), img[s + 6]);
    }
    for (const l of lay.live || [])
      for (const id of l.nodes) this._emit(l.net + ".node" + id + ".operational", ((img[l.b + (id >> 3)] >> (id & 7)) & 1) === 1);
    if (lay.sdoResp !== null && lay.sdoResp !== undefined) this._sdoAnswer();
    const mbl = lay.mailboxes;
    if (!mbl) return;
    for (let m = 0; m < this.mb.length; m++) this._mbAnswer(m);
    for (const info of mbl.info || []) this._info(info);
    if (mbl.cyclic) this._cyclicTable();
    if (mbl.receive) this._receive();
  }

  _info(info) {
    const w = (k) => be16(this.inImg, info.b + 2 * k);
    const p = info.name + ".";
    const emit = (topic, value) => {
      if (!this.inputNames.has(topic)) this._emit(topic, value);
    };
    const hi = (k) => w(k) >> 8, lo = (k) => w(k) & 255;
    emit(p + "bus_state", ["error active", "warning", "error passive", "bus off", "unknown"][hi(0)] || "unknown");
    emit(p + "bus_load", lo(0));
    emit(p + "tx_errors", w(1));
    emit(p + "rx_errors", w(2));
    emit(p + "bus_offs", w(3) * 65536 + w(4));
    if (info.j1939 && hi(11) !== 0xff) {
      emit(p + "claim", ["claiming", "claimed", "cannot claim", "off"][hi(11)] || "state " + hi(11));
      emit(p + "address", lo(11));
      let name = 0n;
      for (let k = 12; k < 16; k++) name = (name << 16n) | BigInt(w(k));
      emit(p + "name", name.toString());
      emit(p + "ecus", w(16));
    }
  }

  // ---- outputs ----

  // Sets output `name`; returns an error text or null.
  set(name, value) {
    if (this.readOnly) return "read-only: this flow does not write to the bridge";
    const r = this.outputs.get(name);
    if (!r) return "no output named " + JSON.stringify(name);
    const probe = Buffer.alloc(this.lay.outBytes);
    const err = codec.encode(probe, r, value);
    if (err) return name + " " + err;
    if (!this.seeded) this.pendingOut.set(name, value);
    else codec.encode(this.outImg, r, value);
    return null;
  }

  // ---- network names ----

  network(n, kind) {
    const nets = this.lay.networks || [];
    if (n === undefined || n === null || n === "") {
      const of = nets.filter((x) => !kind || x.kinds.includes(kind));
      if (of.length === 1) return of[0].index;
      throw new CwError(kind === "j1939" ? 2 : kind === "canopen" ? 6 : 2, "name the network: the config has " + of.length + " " + (kind || "") + " networks");
    }
    const index = typeof n === "number" ? n : typeof n === "string" && /^\d+$/.test(n) ? Number(n) : null;
    const hit = nets.find((x) => x.index === index) || nets.find((x) => x.name === n);
    if (!hit) throw new CwError(kind === "canopen" ? 6 : 2, "no network " + JSON.stringify(n));
    if (kind && !hit.kinds.includes(kind))
      throw new CwError(kind === "j1939" ? 10 : 4, hit.name + " is not a " + (kind === "j1939" ? "J1939" : "CANopen master") + " network");
    return hit.index;
  }

  _guard(what) {
    if (this.readOnly) throw new CwError(22, "read-only: the bridge's writes belong to another program");
    if (!this.connected || !this.seeded) throw new CwError(20);
    if (what === "mailbox" && !this.mb.length) throw new CwError(22, "the config has no request mailbox");
  }

  // ---- NMT through the control block ----

  nmt(command, network, node, timeoutMs) {
    return new Promise((resolve, reject) => {
      try {
        if (this.lay.control === null || this.lay.control === undefined) throw new CwError(22, "the config has no control block");
        // The answer (the last command counter handled) is in the status block.
        if (this.lay.status === null || this.lay.status === undefined)
          throw new CwError(22, "the config has no status block (status_location), which carries the NMT answer");
        this._guard();
        const cmd = NMT_COMMANDS[command];
        if (!cmd) throw new CwError(6, "command must be one of " + Object.keys(NMT_COMMANDS).join(", "));
        const net = cmd <= 2 ? 0 : this.network(network, "canopen");
        const id = cmd <= 2 ? 0 : node === undefined || node === null ? 0 : Number(node);
        if (!Number.isInteger(id) || id < 0 || id > 127) throw new CwError(6, "node must be 0-127 (0: every node)");
        if (this.nmtQueue.length >= QUEUE_LIMIT) throw new CwError(5, undefined, { queueFull: true });
        this.nmtQueue.push({ cmd, net, id, timeoutMs: timeoutMs || 5000, resolve, reject });
        this._nmtNext();
      } catch (e) {
        reject(e);
      }
    });
  }

  _nmtNext() {
    if (this.nmtBusy || !this.nmtQueue.length || !this.seeded) return;
    const j = this.nmtQueue.shift();
    const at = this.lay.control;
    const echo = this.haveInput && this.lay.status !== null ? be16(this.inImg, this.lay.status + 4) : -1;
    this.ctlCounter = nextCounter(this.ctlCounter, echo);
    j.counter = this.ctlCounter;
    put16(this.outImg, at, j.counter);
    this.outImg[at + 2] = j.cmd;
    this.outImg[at + 3] = j.net;
    this.outImg[at + 4] = j.id;
    this.outImg[at + 5] = 0;
    j.timer = setTimeout(() => this._nmtEnd(new CwError(2)), j.timeoutMs);
    this.nmtBusy = j;
  }

  _nmtAnswer(counter, result) {
    const j = this.nmtBusy;
    if (!j || counter !== j.counter) return;
    if (result === 0) this._nmtEnd(null);
    else this._nmtEnd(new CwError(result === 6 ? 8 : result === 5 ? 5 : 6, "the bridge answered " + T.controlResult(result)));
  }

  _nmtEnd(err) {
    const j = this.nmtBusy;
    if (!j) return;
    clearTimeout(j.timer);
    this.nmtBusy = null;
    if (err) j.reject(err);
    else j.resolve(true);
    this._nmtNext();
  }

  // ---- SDO up to 4 bytes through the SDO registers ----

  hasSdoRegisters() {
    return this.lay.sdoReq !== null && this.lay.sdoReq !== undefined && this.lay.sdoResp !== null && this.lay.sdoResp !== undefined;
  }

  // Returns the value read (an unsigned 32-bit number) or true for a write.
  sdoShort(req) {
    return new Promise((resolve, reject) => {
      try {
        if (!this.hasSdoRegisters()) throw new CwError(22, "the config has no SDO registers");
        this._guard();
        if (this.sdoQueue.length >= QUEUE_LIMIT) throw new CwError(5, undefined, { queueFull: true });
        this.sdoQueue.push(Object.assign({ resolve, reject }, req));
        this._sdoNext();
      } catch (e) {
        reject(e);
      }
    });
  }

  _sdoNext() {
    if (this.sdoBusy || !this.sdoQueue.length || !this.seeded) return;
    const j = this.sdoQueue.shift();
    const at = this.lay.sdoReq, img = this.outImg;
    const echo = this.haveInput ? be16(this.inImg, this.lay.sdoResp) : -1;
    this.sdoCounter = nextCounter(this.sdoCounter, echo);
    j.counter = this.sdoCounter;
    put16(img, at, j.counter);
    img[at + 2] = j.write ? 2 : 1;
    img[at + 3] = j.net;
    img[at + 4] = j.node;
    img[at + 5] = j.subindex;
    put16(img, at + 6, j.index);
    img[at + 8] = j.write ? j.length : 0;
    img[at + 9] = 0;
    put32(img, at + 10, j.write ? j.value >>> 0 : 0);
    j.timer = setTimeout(() => this._sdoEnd(new CwError(2)), j.timeoutMs + 2000);
    this.sdoBusy = j;
  }

  _sdoAnswer() {
    const j = this.sdoBusy, r = this.lay.sdoResp, img = this.inImg;
    if (!j || be16(img, r) !== j.counter) return;
    const st = img[r + 2];
    if (st === 2) this._sdoEnd(null, j.write ? true : be32(img, r + 8));
    else if (st === 3) {
      const abort = be32(img, r + 4);
      const id = abort === 0x08000021 ? 8 : abort === 0x08000020 ? 21 : abort === 0x05040000 ? 2 : 1;
      this._sdoEnd(new CwError(id, id === 1 ? "the node aborted: " + T.abortText(abort) : undefined, { abortCode: abort }));
    }
  }

  _sdoEnd(err, value) {
    const j = this.sdoBusy;
    if (!j) return;
    clearTimeout(j.timer);
    this.sdoBusy = null;
    if (err) j.reject(err);
    else j.resolve(value);
    this._sdoNext();
  }

  // ---- request mailboxes ----

  // Runs fn(lease) on the first free request mailbox, in the order the
  // jobs asked; the job keeps the mailbox until fn ends.
  withMailbox(fn) {
    return new Promise((resolve, reject) => {
      try {
        this._guard("mailbox");
      } catch (e) {
        reject(e);
        return;
      }
      if (this.mbWait.length >= QUEUE_LIMIT) {
        reject(new CwError(5, undefined, { queueFull: true }));
        return;
      }
      this.mbWait.push({ fn, resolve, reject });
      this._mbNext();
    });
  }

  _mbNext() {
    while (this.mbWait.length && this.seeded) {
      const m = this.mbBusy.indexOf(null);
      if (m < 0) return;
      const w = this.mbWait.shift();
      const lease = { m, expect: null, call: (op, net, args, data, guardMs) => this._call(lease, op, net, args, data, guardMs) };
      this.mbBusy[m] = lease;
      Promise.resolve()
        .then(() => w.fn(lease))
        .then(w.resolve, w.reject)
        .finally(() => {
          if (this.mbBusy[m] === lease) this.mbBusy[m] = null;
          this._mbNext();
        });
    }
  }

  // One request on the lease's mailbox: resolves {error, r, data} once the
  // bridge answers it.
  _call(lease, op, net, args, data, guardMs) {
    return new Promise((resolve, reject) => {
      if (this.mbBusy[lease.m] !== lease || !this.seeded) {
        reject(new CwError(20));
        return;
      }
      const box = this.mb[lease.m], img = this.outImg;
      const echo = this.haveInput ? be16(this.inImg, box.resp) : -1;
      const counter = nextCounter(this.mbCounter[lease.m], echo);
      this.mbCounter[lease.m] = counter;
      put16(img, box.req, counter);
      put16(img, box.req + 2, ((op & 255) << 8) | (net & 255));
      for (let i = 0; i < 6; i++) put16(img, box.req + 4 + 2 * i, (args && args[i]) || 0);
      const words = codec.bytesToWords(data || [], 64);
      for (let i = 0; i < 64; i++) put16(img, box.req + 16 + 2 * i, words[i]);
      const timer = setTimeout(() => {
        if (lease.expect && lease.expect.counter === counter) {
          lease.expect = null;
          reject(new CwError(20, "the bridge did not answer the request"));
        }
      }, guardMs || 30000);
      lease.expect = {
        counter,
        resolve: (v) => { clearTimeout(timer); resolve(v); },
        reject: (e) => { clearTimeout(timer); reject(e); },
      };
    });
  }

  _mbAnswer(m) {
    const lease = this.mbBusy[m];
    if (!lease || !lease.expect) return;
    const at = this.mb[m].resp, img = this.inImg;
    if (be16(img, at) !== lease.expect.counter) return;
    const state = img[at + 2];
    if (state < L.states.done) return;
    const r = [];
    for (let i = 0; i < 6; i++) r.push(be16(img, at + 4 + 2 * i));
    const x = lease.expect;
    lease.expect = null;
    x.resolve({ error: state === L.states.error ? img[at + 3] : 0, r, data: Buffer.from(img.subarray(at + 16, at + 16 + L.chunk)) });
  }

  // ---- receive mailbox ----

  receiver(spec, handlers) {
    const rx = new Receiver(this, spec, handlers);
    this.receivers.add(rx);
    if (this.connected && this.seeded) rx._open();
    return rx;
  }

  _receive() {
    const { block: rb, blocks } = this.lay.mailboxes.receive, img = this.inImg;
    const w = (k) => be16(img, rb + 2 * k);
    const tick = w(4);
    const gen = (slot) => img[rb + 10 + slot];
    for (const rx of this.receivers) if (rx.slot !== null) rx._check(tick, gen(rx.slot));
    const seq = w(0);
    if (this.rxBusy || seq === this.rxSeq) return;
    const present = w(1) * 65536 + w(2);
    if (!present) {
      this.rxSeq = seq;
      return;
    }
    const used = w(3);
    const words = [];
    // A batch spans every receive block, one after the other.
    for (let k = 0; k < used && L.rxHeaderWords + k < L.receiveWords * (blocks || 1); k++) words.push(w(L.rxHeaderWords + k));
    let us = 0n;
    for (let k = 0; k < 4; k++) us = (us << 16n) | BigInt(w(L.batchTimeWord + k));
    const records = parseRecords(words, us);
    const opening = [...this.receivers].some((rx) => rx.opening);
    // Records of a receiver whose open answer came in this same read: take
    // the batch next poll, once the receiver knows its slot.
    if (opening && records.some((r) => !this.rxBySlot.has(r.slot))) return;
    for (let slot = 0; slot < L.maxReceivers; slot++)
      if (gen(slot) && !this.rxBySlot.has(slot) && !opening) this.rxOrphans.add(slot);
    this.rxBusy = true;
    this._deliver(seq, records, tick).finally(() => {
      this.rxBusy = false;
    });
  }

  async _deliver(seq, records, tick) {
    for (const rec of records) {
      const rx = this.rxBySlot.get(rec.slot);
      if (!rx || !rx.fresh(tick)) continue;
      if (rec.long) {
        try {
          rec.data = await this.withMailbox((lease) => fetchAll(lease, L.ops.rx_fetch, rx.net, [rec.slot, 0], 1785, 0));
        } catch (e) {
          rx._error(e.errorId || 8);
          continue;
        }
      }
      if (Buffer.isBuffer(rec.data)) rec.data = Buffer.from(rec.data);
      rx._record(rec);
    }
    if (!this.connected) return;
    this.rxSeq = seq;
    this.ack = { seq };
    for (const slot of this.rxOrphans) {
      this.rxOrphans.delete(slot);
      // A receiver of an earlier run of this flow: close it, so its records stop.
      this.withMailbox((lease) => lease.call(L.ops.rx_close, 0, [slot])).catch(() => {});
    }
  }

  // ---- cyclic jobs ----

  cyclic(handlers) {
    const j = new Cyclic(this, handlers);
    this.cyclics.add(j);
    return j;
  }

  _cyclicTable() {
    const c = this.lay.mailboxes.cyclic, img = this.inImg;
    const tick = be16(img, c.table);
    for (const j of this.cyclics) {
      if (j.slot === null) continue;
      const at = c.table + 2 + j.slot * 2 * L.jobWords;
      j._check(tick, be16(img, at + 2), img[at], img[at + 1], be16(img, at + 4) * 65536 + be16(img, at + 6));
    }
  }
}

// Tests put a model of the bridge here (tests/nodered/fake_bridge.js).
Bridge.clientFactory = null;

// The records of the receive mailbox's batch. `batchUs` is the batch time:
// the first record's receive time in UTC microseconds. CAN and J1939
// records carry no time of their own and get it; EMCY records have theirs.
function parseRecords(words, batchUs) {
  const out = [];
  const kinds = {};
  for (const k of Object.keys(L.rxKinds)) kinds[L.rxKinds[k]] = k;
  const stamp = (rec, us) => {
    rec.time = us ? new Date(Number(us / 1000n)) : null;
    rec.timeUs = us.toString();
  };
  let i = 0;
  while (i < words.length) {
    const w0 = words[i];
    const kind = kinds[(w0 >> 4) & 15];
    if (!kind) break;
    const n = L.recordWords[kind];
    const r = words.slice(i, i + n);
    i += n;
    const flags = w0 & 15;
    const rec = {
      slot: w0 >> 8, kind, queued: r[1], dropped: r[2],
      overflow: (flags & L.recordFlags.overflow) !== 0, restart: (flags & L.recordFlags.restart) !== 0,
      long: (flags & L.recordFlags.long) !== 0,
    };
    const b = L.recordBodyWord[kind];
    if (kind === "can") {
      stamp(rec, batchUs || 0n);
      rec.id = r[b] * 65536 + r[b + 1];
      rec.extended = (r[b + 2] & 0x0100) !== 0;
      rec.rtr = (r[b + 2] & 0x0200) !== 0;
      rec.dlc = r[b + 2] & 255;
      rec.data = codec.wordsToBytes(r.slice(b + 3, b + 7), Math.min(8, rec.dlc));
    } else if (kind === "j1939") {
      stamp(rec, batchUs || 0n);
      rec.pgn = r[b] * 65536 + r[b + 1];
      rec.source = r[b + 2] >> 8;
      rec.destination = r[b + 2] & 255;
      rec.priority = r[b + 3];
      rec.length = r[b + 4];
      rec.data = codec.wordsToBytes(r.slice(b + 5, b + 9), Math.min(8, rec.length));
    } else {
      let us = 0n;
      for (let k = 0; k < 4; k++) us = (us << 16n) | BigInt(r[L.emcyTimeWord + k]);
      stamp(rec, us);
      rec.node = r[b] >> 8;
      rec.register = r[b] & 255;
      rec.code = r[b + 1];
      rec.data = codec.wordsToBytes(r.slice(b + 2, b + 5), 5);
    }
    out.push(rec);
  }
  return out;
}

// Runs `op` and FETCHes the rest of its result: up to `max` bytes. `lenAt`
// is the result word that holds the whole length (0: words 0-1 as 32 bits
// for SDO, else the 16-bit word).
async function fetchAll(lease, op, net, args, max, lenAt, data, guardMs) {
  const a = await lease.call(op, net, args, data, guardMs);
  if (a.error) throw Object.assign(new CwError(a.error), { answer: a });
  const total = lenAt === "sdo" ? a.r[0] * 65536 + a.r[1] : a.r[lenAt];
  const want = Math.min(total, max);
  const parts = [a.data.subarray(0, Math.min(L.chunk, want))];
  let got = parts[0].length;
  while (got < want) {
    const f = await lease.call(L.ops.fetch, 0, [got]);
    if (f.error) throw new CwError(f.error);
    const n = Math.min(L.chunk, want - got);
    parts.push(f.data.subarray(0, n));
    got += n;
  }
  const out = Buffer.concat(parts);
  out.total = total;
  out.answer = a;
  return out;
}

// STAGEs `data` beyond what one request carries.
async function stage(lease, data) {
  if (data.length <= L.chunk) return;
  for (let off = 0; off < data.length; off += L.chunk) {
    const part = data.subarray(off, off + L.chunk);
    const a = await lease.call(L.ops.stage, 0, [off, part.length], part);
    if (a.error) throw new CwError(a.error);
  }
}

// One receiver of the bridge, kept open while the node runs.
class Receiver {
  constructor(bridge, spec, handlers) {
    this.b = bridge;
    this.spec = spec; // kind, net, flags, depth, id, mask, retry (ERROR_IDs that reopen)
    this.h = handlers; // record(rec), error(errorId, err), active(bool)
    this.slot = null;
    this.gen = 0;
    this.tick0 = 0;
    this.synced = false;
    this.opening = false;
    this.closed = false;
    this.retryTimer = null;
    this.net = spec.net;
  }

  _open() {
    if (this.closed || this.opening || this.slot !== null) return;
    if (!this.b.lay.mailboxes || !this.b.lay.mailboxes.receive || !this.b.mb.length) {
      this._fail(new CwError(22, "the config has no receive mailbox or request mailbox"));
      return;
    }
    this.opening = true;
    const s = this.spec;
    const args = [((L.rxKinds[s.kind] & 255) << 8) | (s.flags & 255), s.depth || 0, Math.floor(s.id / 65536) & 0xffff, s.id & 0xffff,
      Math.floor(s.mask / 65536) & 0xffff, s.mask & 0xffff];
    this.b.withMailbox((lease) => lease.call(L.ops.rx_open, s.net, args)).then((a) => {
      this.opening = false;
      if (a.error) throw new CwError(a.error);
      if (this.closed) {
        this.b.withMailbox((lease) => lease.call(L.ops.rx_close, 0, [a.r[0]])).catch(() => {});
        return;
      }
      this.slot = a.r[0];
      this.gen = a.r[1];
      this.tick0 = a.r[2];
      this.synced = false;
      this.b.rxBySlot.set(this.slot, this);
      if (this.h.active) this.h.active(true);
    }).catch((e) => {
      this.opening = false;
      this._fail(e);
    });
  }

  fresh(tick) {
    if (!this.synced) this.synced = notBefore(tick, this.tick0);
    return this.synced;
  }

  _check(tick, gen) {
    if (this.fresh(tick) && gen !== this.gen) {
      // The bridge closed it: link stop, stall or network restart.
      this._drop();
      this._fail(new CwError(8));
    }
  }

  _record(rec) {
    if (rec.restart) {
      this.h.error(8, new CwError(8, "a new CANopen session"));
      return;
    }
    this.h.record(rec);
  }

  _error(id) {
    this.h.error(id, new CwError(id));
  }

  _drop() {
    if (this.slot !== null && this.b.rxBySlot.get(this.slot) === this) this.b.rxBySlot.delete(this.slot);
    this.slot = null;
    if (this.h.active) this.h.active(false);
  }

  _fail(e) {
    const id = e.errorId || 20;
    this.h.error(id, e);
    if (this.closed) return;
    if ((this.spec.retry || []).includes(id)) {
      clearTimeout(this.retryTimer);
      this.retryTimer = setTimeout(() => {
        if (this.b.connected) this._open();
      }, 1000);
    }
  }

  // The connection went away; it opens again when the bridge is back.
  _lost() {
    this.opening = false;
    if (this.slot !== null) {
      this._drop();
      this.h.error(20, new CwError(20));
    }
  }

  close() {
    this.closed = true;
    clearTimeout(this.retryTimer);
    this.b.receivers.delete(this);
    const slot = this.slot;
    this._drop();
    if (slot !== null && this.b.connected) this.b.withMailbox((lease) => lease.call(L.ops.rx_close, 0, [slot])).catch(() => {});
  }
}

// One cyclic job of the bridge.
class Cyclic {
  constructor(bridge, handlers) {
    this.b = bridge;
    this.h = handlers; // ended(errorId), count(n)
    this.slot = null;
    this.gen = 0;
    this.tick0 = 0;
    this.synced = false;
    this.frame = null;
    this.keep = 0;
    this.chain = Promise.resolve();
  }

  // One change at a time: a stop waits for a set still on its way.
  _queue(fn) {
    const p = this.chain.then(fn, fn);
    this.chain = p.catch(() => {});
    return p;
  }

  // frame: net, id, extended, dlc, data (Buffer), period
  set(frame) {
    return this._queue(() => this._set(frame));
  }

  stop() {
    return this._queue(() => this._stop());
  }

  async _set(frame) {
    const c = this.b.lay.mailboxes && this.b.lay.mailboxes.cyclic;
    if (!c) throw new CwError(22, "the config has no cyclic jobs");
    const args = [this.slot === null ? 0xffff : this.slot, Math.floor(frame.id / 65536) & 0xffff, frame.id & 0xffff,
      ((frame.extended ? 1 : 0) << 8) | frame.dlc, frame.period, 0];
    const a = await this.b.withMailbox((lease) => lease.call(L.ops.cyclic_set, frame.net, args, frame.data));
    if (a.error) {
      if (a.error === 8 && this.slot !== null) this._forget();
      throw new CwError(a.error);
    }
    this.frame = frame;
    if (this.slot === null) {
      this.slot = a.r[0];
      this.gen = a.r[1];
      this.tick0 = a.r[2];
      this.synced = false;
      this.b.jobBySlot.set(this.slot, this);
    }
    return true;
  }

  async _stop() {
    const slot = this.slot;
    this.frame = null;
    this._forget();
    if (slot === null || !this.b.connected) return true;
    await this.b.withMailbox((lease) => lease.call(L.ops.cyclic_stop, 0, [slot]));
    return true;
  }

  _forget() {
    if (this.slot !== null && this.b.jobBySlot.get(this.slot) === this) this.b.jobBySlot.delete(this.slot);
    this.slot = null;
  }

  _keepalive() {
    if (this.slot === null) return;
    const at = this.b.lay.mailboxes.cyclic.keepalive + 2 * this.slot;
    this.keep = (be16(this.b.outImg, at) + 1) & 0xffff;
    put16(this.b.outImg, at, this.keep);
  }

  _check(tick, gen, state, error, count) {
    if (!this.synced) this.synced = notBefore(tick, this.tick0);
    if (!this.synced) return;
    if (gen !== this.gen || state === 0) {
      this._forget();
      this.h.ended(8);
      return;
    }
    if (this.h.count) this.h.count(count, state === 2 ? error : 0);
  }

  _lost() {
    if (this.slot === null) return;
    this._forget();
    this.h.ended(20);
  }

  close() {
    this.b.cyclics.delete(this);
    if (this.slot !== null && this.b.connected) this.stop().catch(() => {});
    this._forget();
  }
}

module.exports = { Bridge, CwError, fetchAll, stage, parseRecords, nextCounter, NMT_COMMANDS };
