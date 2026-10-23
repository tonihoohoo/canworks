// fake_bridge.js - a scripted model of canworks-bridge's registers for the
// package tests: the client side of lib/modbus.js on two word tables, and
// the bridge side of the control block, SDO registers, request mailboxes,
// receive mailbox and cyclic jobs as the bridge answers them
// (plugin/src/bridge/mailboxes.h). Tests script the answers per operation.
"use strict";

const { EventEmitter } = require("events");
const path = require("path");

const L = require(path.join(__dirname, "..", "..", "canworks", "nodered_package", "lib", "layout"));

class FakeBridge {
  constructor(layout) {
    this.lay = layout;
    this.hold = new Uint16Array(65536);
    this.inp = new Uint16Array(65536);
    this.clients = [];
    this.connects = 0;
    this.refuseWrites = false;
    this.down = false;
    this.writes = []; // [start, words] of every write
    this.reads = 0;
    this.t0 = Date.now();
    this.ops = {}; // op -> (req) => {error, r, data} | Promise of it
    this.calls = []; // every mailbox request the model ran: {op, net, args, data}
    this.controls = [];
    this.sdos = [];
    this.od = new Map(); // "node:index:sub" -> value (SDO registers)
    this.controlResult = () => 0;
    this.rxSlots = new Map(); // slot -> {gen, kind, args}
    this.rxGen = new Uint8Array(L.maxReceivers);
    this.rxSeq = 0;
    this.rxPending = []; // records not yet in the block
    this.acked = 0;
    this.jobs = new Map(); // slot -> {gen, count, state}
    this.jobGen = 0;
    this.restart();
  }

  // ---- the bridge side ----

  // A bridge start: the next write of every request block is its baseline.
  restart() {
    this.baseline = true;
    this.rxSlots.clear();
    this.jobs.clear();
    for (let s = 0; s < this.rxGen.length; s++) this.rxGen[s] = 0;
    this.seen = { control: null, sdo: null, mb: this.mbBlocks().map(() => null) };
  }

  tick() {
    return (Date.now() - this.t0) & 0xffff;
  }

  mbBlocks() {
    return (this.lay.mailboxes && this.lay.mailboxes.requests) || [];
  }

  w(byte) {
    return byte / 2;
  }

  _process() {
    const lay = this.lay;
    const base = this.baseline;
    this.baseline = false;
    if (lay.control !== null && lay.control !== undefined) {
      const at = this.w(lay.control);
      const c = this.hold[at];
      if (c !== this.seen.control) {
        this.seen.control = c;
        if (!base && c !== 0) {
          const cmd = this.hold[at + 1] >> 8, net = this.hold[at + 1] & 255, node = this.hold[at + 2] >> 8;
          this.controls.push({ cmd, net, node });
          const s = this.w(lay.status);
          this.inp[s + 2] = c;
          this.inp[s + 3] = (this.controlResult(cmd, net, node) & 255) << 8;
        }
      }
    }
    if (lay.sdoReq !== null && lay.sdoReq !== undefined) {
      const at = this.w(lay.sdoReq);
      const c = this.hold[at];
      if (c !== this.seen.sdo) {
        this.seen.sdo = c;
        if (!base && c !== 0) this._sdo(at, c);
      }
    }
    this.mbBlocks().forEach((m, k) => {
      const at = this.w(m.req);
      const c = this.hold[at];
      if (c === this.seen.mb[k]) return;
      this.seen.mb[k] = c;
      if (base || c === 0) return;
      const op = this.hold[at + 1] >> 8, net = this.hold[at + 1] & 255;
      const args = Array.from(this.hold.subarray(at + 2, at + 8));
      const data = Buffer.alloc(L.chunk);
      for (let i = 0; i < 64; i++) data.writeUInt16BE(this.hold[at + 8 + i], 2 * i);
      const req = { op, net, args, data, counter: c, mailbox: k };
      this.calls.push(req);
      const resp = this.w(m.resp);
      this.inp[resp] = c;
      this.inp[resp + 1] = L.states.busy << 8;
      Promise.resolve(this._op(req)).then((a) => {
        if (this.inp[resp] !== c || this.seen.mb[k] !== c) return;
        a = a || {};
        this.inp[resp + 1] = ((a.error ? L.states.error : L.states.done) << 8) | (a.error || 0);
        for (let i = 0; i < 6; i++) this.inp[resp + 2 + i] = (a.r && a.r[i]) || 0;
        const out = Buffer.alloc(L.chunk);
        if (a.data) Buffer.from(a.data).copy(out, 0, 0, L.chunk);
        for (let i = 0; i < 64; i++) this.inp[resp + 8 + i] = out.readUInt16BE(2 * i);
      });
    });
    const rcv = this.lay.mailboxes && this.lay.mailboxes.receive;
    if (rcv) {
      const seen = this.hold[this.w(rcv.ack)];
      if (seen === this.rxSeq && seen !== this.acked) {
        this.acked = seen;
        this._fillReceive();
      }
    }
    this._cyclicTable();
  }

  _sdo(at, c) {
    const kind = this.hold[at + 1] & 255; // low byte of word 1: request byte 2 is high
    const write = (this.hold[at + 1] >> 8) === 2;
    const net = this.hold[at + 1] & 255;
    const node = this.hold[at + 2] >> 8, sub = this.hold[at + 2] & 255;
    const index = this.hold[at + 3];
    const len = this.hold[at + 4] >> 8;
    const value = this.hold[at + 5] * 65536 + this.hold[at + 6];
    void kind;
    const req = { write, net, node, index, sub, len, value };
    this.sdos.push(req);
    const r = this.w(this.lay.sdoResp);
    const key = node + ":" + index + ":" + sub;
    const answer = () => {
      this.inp[r] = c;
      const got = this.od.get(key);
      if (got === undefined) {
        this.inp[r + 1] = 3 << 8;
        this.inp[r + 2] = 0x0602;
        this.inp[r + 3] = 0x0000;
      } else if (typeof got === "object") {
        this.inp[r + 1] = 3 << 8;
        this.inp[r + 2] = Math.floor(got.abort / 65536);
        this.inp[r + 3] = got.abort & 0xffff;
      } else {
        if (write) this.od.set(key, value);
        this.inp[r + 1] = 2 << 8;
        const v = write ? 0 : got >>> 0;
        this.inp[r + 4] = Math.floor(v / 65536);
        this.inp[r + 5] = v & 0xffff;
      }
    };
    if (this.sdoDelayMs) setTimeout(answer, this.sdoDelayMs);
    else answer();
  }

  _op(req) {
    const fn = this.ops[req.op];
    if (fn) return fn(req);
    if (req.op === L.ops.rx_open) {
      let slot = 0;
      while (this.rxSlots.has(slot)) slot++;
      if (slot >= L.maxReceivers) return { error: 5 };
      this.rxNext = this.rxNext || new Uint8Array(L.maxReceivers);
      const gen = (this.rxNext[slot] % 255) + 1;
      this.rxNext[slot] = gen;
      this.rxGen[slot] = gen;
      this.rxSlots.set(slot, { gen, kind: req.args[0] >> 8, args: req.args, net: req.net });
      this._writeGens();
      return { r: [slot, gen, this.tick()] };
    }
    if (req.op === L.ops.rx_close) {
      this.rxSlots.delete(req.args[0]);
      this.rxGen[req.args[0]] = 0;
      this._writeGens();
      return {};
    }
    if (req.op === L.ops.cyclic_set) {
      let slot = req.args[0];
      if (slot === 0xffff) {
        slot = 0;
        while (this.jobs.has(slot)) slot++;
        if (slot >= this.lay.mailboxes.cyclic.jobs) return { error: 5 };
        this.jobGen = (this.jobGen % 0xffff) + 1;
        this.jobs.set(slot, { gen: this.jobGen, count: 0, state: 1, frame: req });
      } else if (!this.jobs.has(slot)) return { error: 8 };
      else this.jobs.get(slot).frame = req;
      return { r: [slot, this.jobs.get(slot).gen, this.tick()] };
    }
    if (req.op === L.ops.cyclic_stop) {
      this.jobs.delete(req.args[0]);
      return {};
    }
    return {};
  }

  _writeGens() {
    const b = this.w(this.lay.mailboxes.receive.block);
    for (let s = 0; s < L.maxReceivers; s += 2) this.inp[b + 5 + s / 2] = (this.rxGen[s] << 8) | this.rxGen[s + 1];
  }

  // Closes receiver `slot` as the bridge does at a link stop (its generation shows 0).
  closeReceiver(slot) {
    this.rxSlots.delete(slot);
    this.rxGen[slot] = 0;
    this._writeGens();
  }

  slotOf(kind) {
    for (const [slot, rx] of this.rxSlots) if (rx.kind === L.rxKinds[kind]) return slot;
    return -1;
  }

  // Queues records {slot, kind, flags, queued, dropped, timeUs, body: [words]}.
  push(records) {
    this.rxPending.push(...records);
    if (this.acked === this.rxSeq) this._fillReceive();
  }

  _fillReceive() {
    if (!this.rxPending.length) return;
    const b = this.w(this.lay.mailboxes.receive.block);
    const room = L.receiveWords - L.rxHeaderWords;
    const words = [];
    let present = 0;
    while (this.rxPending.length) {
      const rec = this.rxPending[0];
      const n = L.recordWords[rec.kind];
      if (words.length + n > room) break;
      this.rxPending.shift();
      const w = new Array(n).fill(0);
      w[0] = (rec.slot << 8) | (L.rxKinds[rec.kind] << 4) | (rec.flags || 0);
      w[1] = rec.queued || 0;
      w[2] = rec.dropped || 0;
      let t = BigInt(rec.timeUs || 0);
      for (let k = 3; k >= 0; k--) {
        w[L.recordTimeWord + k] = Number(t & 0xffffn);
        t >>= 16n;
      }
      (rec.body || []).forEach((v, i) => (w[L.recordBodyWord + i] = v));
      words.push(...w);
      present |= 1 << rec.slot;
    }
    for (let i = 0; i < room; i++) this.inp[b + L.rxHeaderWords + i] = words[i] || 0;
    this.rxSeq = (this.rxSeq + 1) & 0xffff || 1;
    this.inp[b] = this.rxSeq;
    this.inp[b + 1] = (present >>> 16) & 0xffff;
    this.inp[b + 2] = present & 0xffff;
    this.inp[b + 3] = words.length;
    this.inp[b + 4] = this.tick();
  }

  _cyclicTable() {
    const c = this.lay.mailboxes && this.lay.mailboxes.cyclic;
    if (!c) return;
    const t = this.w(c.table);
    this.inp[t] = this.tick();
    for (let s = 0; s < c.jobs; s++) {
      const j = this.jobs.get(s);
      const at = t + 1 + s * L.jobWords;
      this.inp[at] = j ? j.state << 8 : 0;
      this.inp[at + 1] = j ? j.gen : 0;
      this.inp[at + 2] = j ? Math.floor(j.count / 65536) : 0;
      this.inp[at + 3] = j ? j.count & 0xffff : 0;
    }
  }

  // ---- the client side (what lib/modbus.js offers) ----

  factory() {
    return (o) => {
      const model = this;
      const c = new EventEmitter();
      c.connected = false;
      c.connect = async () => {
        if (model.down) throw Object.assign(new Error("connect ECONNREFUSED"), { code: "ECONNREFUSED" });
        model.connects++;
        c.connected = true;
        model.clients.push(c);
      };
      c.close = () => {
        if (!c.connected) return;
        c.connected = false;
        model.clients = model.clients.filter((x) => x !== c);
        setImmediate(() => c.emit("close", new Error("closed")));
      };
      const live = () => {
        if (!c.connected || model.down) throw Object.assign(new Error("not connected"), { code: "ECONNRESET" });
      };
      c.readHolding = async (s, n) => {
        live();
        return Array.from(model.hold.subarray(s, s + n));
      };
      c.readInput = async (s, n) => {
        live();
        model.reads++;
        model._cyclicTable();
        // The receive block's tick is the bridge's time now, every cycle.
        const rcv = model.lay.mailboxes && model.lay.mailboxes.receive;
        if (rcv) model.inp[model.w(rcv.block) + 4] = model.tick();
        return Array.from(model.inp.subarray(s, s + n));
      };
      c.writeMultiple = async (s, words) => {
        live();
        if (model.refuseWrites) throw Object.assign(new Error("exception 1"), { code: "exception1" });
        model.writes.push([s, words.slice()]);
        for (let i = 0; i < words.length; i++) model.hold[s + i] = words[i];
        model._process();
      };
      c.options = o;
      return c;
    };
  }

  // The connection drops (the bridge goes away until up()).
  drop() {
    this.down = true;
    for (const c of this.clients.slice()) c.close();
  }

  up() {
    this.down = false;
  }
}

module.exports = { FakeBridge, L };
