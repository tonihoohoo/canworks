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
const STOP_WAIT_MS = 500; // how long stop() waits for the closes the nodes queued
const REFUSED = "writes refused: add Node-RED's address to the bridge's writers";
const MISMATCH = "map mismatch: export the flow again";
// Read Device Identification (function 43, MEI type 14): one object, the bridge's map hash.
const ID_INDIVIDUAL = 4;
const ID_MAP_HASH = 0x80;

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
    this.rxClosing = new Map(); // slot -> the generation an rx_close went out for
    this.sweepWaiters = [];
    this.closing = new Set(); // rx_close and cyclic_stop on their way
    this.readWaiters = [];
    // The mailbox parts read in the last poll, and whether the receivers
    // of an earlier connection were swept (nodered-blocks "Mailbox reads
    // only while in use").
    this.partRead = {};
    this.requestGrace = 0;
    this.rxSwept = false;
    this.ack = null; // {seq} to write
    this.cyclics = new Set();
    this.jobBySlot = new Map();
    this.mapMismatch = false;
    this.identity = null; // the bridge's map hash text, when it answers device identification
    this.warnedIdentity = false;
    this.stopping = null;
  }

  // ---- connection ----

  start() {
    if (this.running) return;
    this.running = true;
    this._connect();
  }

  // Resolves once stopped. A Deploy closes the receiver and cyclic nodes
  // next to this one: their rx_close and cyclic_stop go out first, for up to
  // STOP_WAIT_MS, so the bridge does not keep them.
  stop() {
    if (this.stopping) return this.stopping;
    this.stopping = new Promise((r) => setImmediate(r))
      .then(() => {
        if (!this.closing.size || !this.connected) return null;
        let timer;
        return Promise.race([Promise.allSettled([...this.closing]), new Promise((r) => (timer = setTimeout(r, STOP_WAIT_MS)))])
          .then(() => clearTimeout(timer));
      })
      .then(() => {
        this.stopping = null;
        this.running = false;
        clearTimeout(this.timer);
        if (this.client) this.client.close();
        this._down(new CwError(20, "the bridge node was stopped"));
        this._state("stopped", { fill: "grey", shape: "ring", text: "stopped" });
      });
    return this.stopping;
  }

  _state(name, status) {
    this.state = name;
    this.status = status;
    this.emit("state", status);
  }

  async _connect() {
    if (!this.running) return;
    if (!this.mapMismatch) this._state("connecting", { fill: "yellow", shape: "ring", text: "connecting to " + this.host + ":" + this.port });
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
      await this._identify(c);
      await this._seed();
    } catch (e) {
      c.close();
      return;
    }
    this.connected = true;
    this.delay = RECONNECT_MIN_MS;
    if (this.mapMismatch) this._state("mismatch", { fill: "red", shape: "dot", text: MISMATCH });
    else if (this.writesRefused) this._refused();
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
    this._endJobs(err);
    this.rxBySlot.clear();
    this.rxSeq = null;
    this.rxBusy = false;
    this.rxClosing.clear();
    this.sweepWaiters = [];
    this.rxSwept = false;
    this.partRead = {};
    for (const w of this.readWaiters.splice(0)) w.reject(err);
    this.ack = null;
    this.jobBySlot.clear();
    for (const rx of this.receivers) rx._lost();
    for (const j of this.cyclics) j._lost();
  }

  _endJobs(err) {
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
  }

  // At connect: the bridge's map hash by device identification. A hash
  // other than the flow's refuses every write and job; a bridge that does
  // not answer it (older) gives a warning only.
  async _identify(c) {
    this.mapMismatch = false;
    if (typeof this.lay.mapHash !== "number" || !c.readDeviceId) return;
    let text = "";
    try {
      const id = await c.readDeviceId(ID_INDIVIDUAL, ID_MAP_HASH);
      const v = id.objects[ID_MAP_HASH];
      text = v ? Buffer.from(v).toString("latin1").trim() : "";
    } catch (e) {
      if (!/^exception/.test(e.code || "")) throw e;
    }
    if (!/^[0-9A-Fa-f]{8}$/.test(text)) {
      this.identity = null;
      if (!this.warnedIdentity) this.emit("warning", "the bridge does not give its map hash by device identification (an older canworks-bridge): the flow's map is not checked");
      this.warnedIdentity = true;
      return;
    }
    this.identity = { mapHash: text.toUpperCase() };
    this.mapMismatch = parseInt(text, 16) !== this.lay.mapHash >>> 0;
  }

  // After a connect: read the outputs and requests back and write them
  // again unchanged. That write is the mailboxes' baseline after a bridge
  // restart, and leaves every counter as the bridge has it, so nothing old
  // runs again.
  async _seed() {
    const c = this.client;
    if (this.readOnly || this.mapMismatch) {
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
    this._baseline();
    this.seeded = true;
  }

  // The counters as the bridge holds them, and the outputs set since the
  // last confirmed write on top (they stay pending until written).
  _baseline() {
    this.mbCounter = this.mb.map((m) => be16(this.outImg, m.req));
    if (this.lay.sdoReq !== null && this.lay.sdoReq !== undefined) this.sdoCounter = be16(this.outImg, this.lay.sdoReq);
    if (this.lay.control !== null && this.lay.control !== undefined) this.ctlCounter = be16(this.outImg, this.lay.control);
    for (const [name, value] of this.pendingOut) codec.encode(this.outImg, this.outputs.get(name), value);
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

  // The mailbox parts in use, which this poll reads: a request mailbox
  // while a job holds or waits for one and for one poll after, the receive
  // mailbox while a receiver is open or closing or an earlier connection's
  // are not swept yet, the cyclic table while a job runs or is taken over.
  _partsInUse() {
    if (this.mbBusy.some((l) => l) || this.mbWait.length) this.requestGrace = 2;
    else if (this.requestGrace) this.requestGrace--;
    return {
      requests: this.requestGrace > 0,
      receive: this.receivers.size > 0 || this.rxClosing.size > 0 || this.sweepWaiters.length > 0 || (!this.rxSwept && !this.readOnly),
      cyclic: [...this.cyclics].some((j) => j.slot !== null || j.old),
    };
  }

  async _cycle(c) {
    const use = this._partsInUse();
    const read = {};
    for (const [s, n, part] of this.lay.read) {
      if (part && !use[part]) continue;
      const words = await c.readInput(s, n);
      for (let i = 0; i < n; i++) put16(this.inImg, (s + i) * 2, words[i]);
      if (part) read[part] = true;
    }
    this.partRead = read;
    this.haveInput = true;
    for (const w of this.readWaiters.splice(0)) w.resolve();
    this._afterRead();
    if (this.readOnly || !this.seeded) return;
    if (this.writesRefused && Date.now() - this.lastWrite < 5000) return;
    const now = Date.now();
    // While refused, every write is a try: an unchanged image must not pass for accepted.
    const all = this.writesRefused || (this.rewriteMs && now - this.lastWrite >= this.rewriteMs);
    for (const j of this.cyclics) j._keepalive();
    if (this.ack) {
      const a = this.lay.mailboxes.receive.ack;
      put16(this.outImg, a, this.ack.seq);
      put16(this.outImg, a + 2, 0);
      put16(this.outImg, a + 4, 0);
      this.ack = null;
    }
    let wrote = false;
    const sent = new Map(this.pendingOut);
    try {
      for (const [s, n] of this.lay.write) {
        const from = s * 2, to = (s + n) * 2;
        if (!all && this.written.compare(this.outImg, from, to, from, to) === 0) continue;
        await c.writeMultiple(s, this._words(s, n));
        this.outImg.copy(this.written, from, from, to);
        wrote = true;
      }
      for (const [name, value] of sent) if (Object.is(this.pendingOut.get(name), value)) this.pendingOut.delete(name);
      if (this.writesRefused) {
        this.writesRefused = false;
        this._state("running", { fill: "green", shape: "dot", text: "connected" });
        for (const rx of this.receivers) rx._open();
      }
    } catch (e) {
      if (!/^exception/.test(e.code || "")) throw e;
      const was = this.writesRefused;
      this.writesRefused = true;
      this.lastWrite = now;
      this._refused();
      if (!was) {
        // The jobs' requests never reach the bridge: end them now, and take
        // back what they put in the image so nothing old runs later.
        this._endJobs(new CwError(21, REFUSED));
        this.written.copy(this.outImg);
        this._baseline();
      }
      return;
    }
    if (wrote || all) this.lastWrite = now;
  }

  _refused() {
    this._state("refused", { fill: "red", shape: "dot", text: REFUSED });
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
    // A part not read this poll holds an old image: nothing to look at.
    if (this.partRead.requests) for (let m = 0; m < this.mb.length; m++) this._mbAnswer(m);
    for (const info of mbl.info || []) this._info(info);
    if (mbl.cyclic && this.partRead.cyclic) this._cyclicTable();
    if (mbl.receive && this.partRead.receive) this._receive();
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
    if (this.mapMismatch) return MISMATCH;
    const r = this.outputs.get(name);
    if (!r) return "no output named " + JSON.stringify(name);
    const probe = Buffer.alloc(this.lay.outBytes);
    const err = codec.encode(probe, r, value);
    if (err) return name + " " + err;
    // Pending until a write of it is confirmed: a reconnect's read-back does not lose it.
    this.pendingOut.set(name, value);
    if (this.seeded) codec.encode(this.outImg, r, value);
    return null;
  }

  // ---- network names ----

  network(n, kind) {
    const nets = this.lay.networks || [];
    if (n === undefined || n === null || n === "") {
      const of = nets.filter((x) => !kind || x.kinds.includes(kind));
      if (of.length === 1) return of[0].index;
      if (!of.length && kind === "j1939") throw new CwError(10, "the config has no J1939 network");
      if (!of.length && kind === "canopen") throw new CwError(4, "the config has no CANopen master network");
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
    if (this.mapMismatch) throw new CwError(22, MISMATCH);
    if (!this.connected || !this.seeded) throw new CwError(20);
    if (this.writesRefused) throw new CwError(21, REFUSED);
    if (what === "mailbox" && !this.mb.length) throw new CwError(22, "the config has no request mailbox");
  }

  // Resolves once the last poll has read `part`.
  _partFresh(part) {
    if (this.partRead[part]) return Promise.resolve();
    // A job that came in after this poll chose its parts waits one more.
    return new Promise((resolve, reject) => this.readWaiters.push({ resolve, reject })).then(() => this._partFresh(part));
  }

  // Resolves after the first read of this connection.
  _firstRead() {
    if (this.haveInput) return Promise.resolve();
    return new Promise((resolve, reject) => this.readWaiters.push({ resolve, reject }));
  }

  // An rx_close or cyclic_stop for a slot no node owns any more; stop() waits for it.
  _closeSlot(op, slot) {
    const p = this.withMailbox((lease) => lease.call(op, 0, [slot])).catch(() => {});
    this.closing.add(p);
    p.then(() => this.closing.delete(p));
    return p;
  }

  _closeReceiver(slot, gen) {
    this.rxClosing.set(slot, gen);
    return this._closeSlot(L.ops.rx_close, slot);
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
  // jobs asked (`first`: ahead of them); the job keeps the mailbox until fn ends.
  withMailbox(fn, first) {
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
      if (first) this.mbWait.unshift({ fn, resolve, reject });
      else this.mbWait.push({ fn, resolve, reject });
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
      // A mailbox not read last poll is read once before the job writes,
      // so its counter follows what the bridge holds.
      Promise.resolve()
        .then(() => this._partFresh("requests"))
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
    const opening = [...this.receivers].some((rx) => rx.opening);
    if (!opening) this._sweep(gen);
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
    // Records of a receiver whose open answer came in this same read: take
    // the batch next poll, once the receiver knows its slot.
    if (opening && records.some((r) => !this.rxBySlot.has(r.slot))) return;
    this.rxBusy = true;
    this._deliver(seq, records, tick).finally(() => {
      this.rxBusy = false;
    });
  }

  // Closes every open receiver no node owns: one of an earlier connection
  // or Deploy of this flow, also when it gets no records. Once no receiver
  // waits for its open answer, so each open slot has its owner.
  _sweep(gen) {
    if (!this.seeded || this.writesRefused) return;
    for (let slot = 0; slot < L.maxReceivers; slot++) {
      const g = gen(slot);
      if (g && !this.rxBySlot.has(slot) && this.rxClosing.get(slot) !== g) this._closeReceiver(slot, g);
    }
    this.rxSwept = true;
    if (!this.sweepWaiters.length) return;
    const waiting = this.sweepWaiters.splice(0);
    Promise.allSettled([...this.closing]).then(() => waiting.forEach((f) => f()));
  }

  // Resolves after the next sweep's closes.
  _afterSweep() {
    return new Promise((resolve) => this.sweepWaiters.push(resolve));
  }

  async _deliver(seq, records, tick) {
    for (const rec of records) {
      const rx = this.rxBySlot.get(rec.slot);
      if (!rx || !rx.fresh(tick)) continue;
      if (rec.long) {
        try {
          // Ahead of waiting jobs: the bridge closes the batch's receivers when its fetch stalls.
          rec.data = await this.withMailbox((lease) => fetchAll(lease, L.ops.rx_fetch, rx.net, [rec.slot, 0], 1785, 0), true);
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
  }

  // ---- cyclic jobs ----

  cyclic(handlers) {
    const j = new Cyclic(this, handlers);
    this.cyclics.add(j);
    return j;
  }

  // The generation of the cyclic job running in `slot`, 0 when none runs.
  _jobGen(slot) {
    const c = this.lay.mailboxes && this.lay.mailboxes.cyclic;
    if (!c || slot >= c.jobs) return 0;
    const at = c.table + 2 + slot * 2 * L.jobWords;
    return this.inImg[at] ? be16(this.inImg, at + 2) : 0;
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
    this.retriedFull = false;
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
        this.b._closeReceiver(a.r[0], a.r[1]);
        return;
      }
      this.retriedFull = false;
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
    if (id === this.spec.full && !this.retriedFull) {
      // The bridge's receivers are all open: once more, after the bridge node closed the ones no node owns.
      this.retriedFull = true;
      this.b._afterSweep().then(() => {
        if (this.b.connected) this._open();
      });
    } else if ((this.spec.retry || []).includes(id)) {
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
    if (slot !== null && this.b.connected) this.b._closeReceiver(slot, this.gen);
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
    this.old = null; // {slot, gen} of the job before a reconnect, which may still run
    this.closed = false;
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
    let slot = this.slot;
    if (slot === null && this.old) {
      // After a reconnect the old job may still run: take it over instead of starting a second one.
      const old = this.old;
      this.old = null;
      await this.b._firstRead();
      if (this.b._jobGen(old.slot) === old.gen) slot = old.slot;
    }
    const send = (at) => {
      const args = [at === null ? 0xffff : at, Math.floor(frame.id / 65536) & 0xffff, frame.id & 0xffff,
        ((frame.extended ? 1 : 0) << 8) | frame.dlc, frame.period, 0];
      return this.b.withMailbox((lease) => lease.call(L.ops.cyclic_set, frame.net, args, frame.data));
    };
    let a = await send(slot);
    if (a.error === 8 && slot !== null && this.slot === null) {
      slot = null; // the old job ended meanwhile
      a = await send(null);
    }
    if (a.error === 5 && slot === null) {
      // No free job: once more after the stops on their way, or after the
      // bridge's keepalive timeout ended a job of an earlier Deploy.
      if (this.b.closing.size) await Promise.allSettled([...this.b.closing]);
      else await new Promise((r) => setTimeout(r, 1100));
      a = await send(null);
    }
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
    if (this.closed) this._end();
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
    this.old = { slot: this.slot, gen: this.gen };
    this._forget();
    this.h.ended(20);
  }

  // Stops the job on the bridge now, for the slot it has at this moment.
  _end() {
    const slot = this.slot;
    this.frame = null;
    this._forget();
    if (slot !== null && this.b.connected) this.b._closeSlot(L.ops.cyclic_stop, slot);
  }

  close() {
    this.closed = true;
    this.old = null;
    this.b.cyclics.delete(this);
    this._end();
  }
}

module.exports = { Bridge, CwError, fetchAll, stage, parseRecords, nextCounter, NMT_COMMANDS };
