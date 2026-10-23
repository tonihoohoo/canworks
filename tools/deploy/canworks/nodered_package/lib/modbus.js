// modbus.js - a small Modbus TCP client: read holding registers (3), read
// input registers (4) and write multiple registers (16), one transaction at
// a time (the bridge answers in order). No dependencies, like the bridge's
// own server.
"use strict";

const net = require("net");
const { EventEmitter } = require("events");

class ModbusError extends Error {
  constructor(message, code) {
    super(message);
    this.code = code;
  }
}

class ModbusClient extends EventEmitter {
  // options: host, port, unit (default 1), timeoutMs (default 1000)
  constructor(options) {
    super();
    this.host = options.host;
    this.port = options.port || 502;
    this.unit = options.unit === undefined ? 1 : options.unit;
    this.timeoutMs = options.timeoutMs || 1000;
    this.socket = null;
    this.connected = false;
    this.tid = 0;
    this.pending = null; // {tid, fc, resolve, reject, timer}
    this.queue = [];
    this.buf = Buffer.alloc(0);
  }

  connect() {
    return new Promise((resolve, reject) => {
      const s = net.createConnection({ host: this.host, port: this.port });
      let settled = false;
      s.setNoDelay(true);
      s.once("connect", () => {
        settled = true;
        this.socket = s;
        this.connected = true;
        resolve();
      });
      s.on("data", (d) => this._data(d));
      s.on("error", (e) => {
        if (!settled) {
          settled = true;
          reject(e);
        }
        this._lost(e);
      });
      s.on("close", () => this._lost(new ModbusError("connection closed", "closed")));
    });
  }

  close() {
    if (this.socket) this.socket.destroy();
    this._lost(new ModbusError("connection closed", "closed"));
  }

  _lost(err) {
    const was = this.connected;
    this.connected = false;
    this.socket = null;
    this.buf = Buffer.alloc(0);
    const all = (this.pending ? [this.pending] : []).concat(this.queue);
    this.pending = null;
    this.queue = [];
    for (const t of all) {
      if (t.timer) clearTimeout(t.timer);
      t.reject(err);
    }
    if (was) this.emit("close", err);
  }

  readHolding(start, count) {
    return this._request(3, Buffer.from([start >> 8, start & 255, count >> 8, count & 255]));
  }

  readInput(start, count) {
    return this._request(4, Buffer.from([start >> 8, start & 255, count >> 8, count & 255]));
  }

  // words: an array of 16-bit values
  writeMultiple(start, words) {
    const pdu = Buffer.alloc(5 + words.length * 2);
    pdu.writeUInt16BE(start, 0);
    pdu.writeUInt16BE(words.length, 2);
    pdu[4] = words.length * 2;
    words.forEach((w, i) => pdu.writeUInt16BE(w & 0xffff, 5 + i * 2));
    return this._request(16, pdu);
  }

  _request(fc, body) {
    return new Promise((resolve, reject) => {
      if (!this.connected) {
        reject(new ModbusError("not connected", "closed"));
        return;
      }
      this.queue.push({ fc, body, resolve, reject });
      this._next();
    });
  }

  _next() {
    if (this.pending || !this.queue.length || !this.connected) return;
    const t = this.queue.shift();
    this.tid = (this.tid + 1) & 0xffff;
    t.tid = this.tid;
    const frame = Buffer.alloc(8 + t.body.length);
    frame.writeUInt16BE(t.tid, 0);
    frame.writeUInt16BE(0, 2);
    frame.writeUInt16BE(2 + t.body.length, 4);
    frame[6] = this.unit;
    frame[7] = t.fc;
    t.body.copy(frame, 8);
    t.timer = setTimeout(() => {
      // A lost answer leaves the stream out of step: start again.
      this.pending = null;
      t.reject(new ModbusError("no answer within " + this.timeoutMs + " ms", "timeout"));
      if (this.socket) this.socket.destroy();
    }, this.timeoutMs);
    this.pending = t;
    this.socket.write(frame);
  }

  _data(d) {
    this.buf = Buffer.concat([this.buf, d]);
    while (this.buf.length >= 7) {
      const len = this.buf.readUInt16BE(4);
      if (this.buf.length < 6 + len) return;
      const frame = this.buf.subarray(0, 6 + len);
      this.buf = this.buf.subarray(6 + len);
      const t = this.pending;
      if (!t || frame.readUInt16BE(0) !== t.tid) continue;
      clearTimeout(t.timer);
      this.pending = null;
      const fc = frame[7];
      if (fc === (t.fc | 0x80)) {
        t.reject(new ModbusError("exception " + frame[8], "exception" + frame[8]));
      } else if (t.fc === 3 || t.fc === 4) {
        const n = frame[8] / 2;
        const words = new Array(n);
        for (let i = 0; i < n; i++) words[i] = frame.readUInt16BE(9 + i * 2);
        t.resolve(words);
      } else {
        t.resolve(true);
      }
      this._next();
    }
  }
}

module.exports = { ModbusClient, ModbusError };
