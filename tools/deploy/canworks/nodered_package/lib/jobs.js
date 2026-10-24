// jobs.js - the blocks as jobs on the bridge (nodered-blocks "Block
// nodes"): each takes the node's settings merged with msg.payload and ends
// with a result or a CwError carrying the block family's ERROR_ID.
"use strict";

const L = require("./layout");
const T = require("./texts");
const codec = require("./codec");
const { CwError, fetchAll, stage } = require("./bridge");

const DEFAULT_TIMEOUT_MS = 5000;
const SDO_MAX = 1024; // the bridge's CANopen side (CANOPEN_PLC_MAX_DATA)

function fail(family, id, text, extra) {
  return new CwError(id, text, Object.assign({ family }, extra || {}));
}

// Adds the family to an error a lower layer threw.
function inFamily(family, e) {
  if (e instanceof CwError) {
    e.family = e.family || family;
    // A full queue is the family's "no free slot".
    if (e.queueFull && e.family === "j1939") e.errorId = 9;
    if (!e.explicit) e.message = T.errorText(e.family, e.errorId);
    return e;
  }
  return fail(family, 20, e && e.message);
}

function int(v, name, lo, hi, family, dflt) {
  if ((v === undefined || v === null || v === "") && dflt !== undefined) return dflt;
  const n = typeof v === "string" && /^\s*(0x[0-9a-f]+|\d+)\s*$/i.test(v) ? Number(v.trim()) : v;
  if (!Number.isInteger(n) || n < lo || n > hi)
    throw fail(family, family === "sdo" ? 6 : 3, name + " must be " + lo + "-" + hi + ", not " + JSON.stringify(v));
  return n;
}

// `dflt`: an SDO job's is the network's SDO timeout from the layout.
function timeoutOf(p, family, dflt) {
  return int(p.timeout, "timeout", 0, 60000, family, 0) || dflt || DEFAULT_TIMEOUT_MS;
}

function net(b, p, kind, family) {
  try {
    return b.network(p.network, kind);
  } catch (e) {
    throw inFamily(family, e);
  }
}

// ---- SDO ----

const TYPES = ["unsigned", "signed", "real", "bytes", "string"];

function numberToLe(v, type, size, family) {
  const buf = Buffer.alloc(size);
  if (type === "real") {
    const x = Number(v);
    if (!isFinite(x)) throw fail(family, 6, "value must be a number");
    if (size === 4) buf.writeFloatLE(x);
    else buf.writeDoubleLE(x);
    return buf;
  }
  let big;
  try {
    big = BigInt(typeof v === "string" ? v.trim() : v);
  } catch (e) {
    throw fail(family, 6, "value must be an integer, not " + JSON.stringify(v));
  }
  const bits = BigInt(size * 8);
  const lo = type === "signed" ? -(1n << (bits - 1n)) : 0n;
  const hi = type === "signed" ? (1n << (bits - 1n)) - 1n : (1n << bits) - 1n;
  if (big < lo || big > hi) throw fail(family, 6, "value is out of range " + lo + ".." + hi);
  big = BigInt.asUintN(Number(bits), big);
  for (let i = 0; i < size; i++) {
    buf[i] = Number(big & 255n);
    big >>= 8n;
  }
  return buf;
}

function leToNumber(buf, type) {
  if (type === "real") {
    if (buf.length === 4) return buf.readFloatLE(0);
    if (buf.length === 8) return buf.readDoubleLE(0);
    throw fail("sdo", 7, "a REAL reply must be 4 or 8 bytes, not " + buf.length);
  }
  if (buf.length > 8) throw fail("sdo", 7, "the reply is " + buf.length + " bytes, more than a number holds");
  let big = 0n;
  for (let i = buf.length - 1; i >= 0; i--) big = (big << 8n) | BigInt(buf[i]);
  if (type === "signed" && buf.length) big = BigInt.asIntN(buf.length * 8, big);
  return big <= BigInt(Number.MAX_SAFE_INTEGER) && big >= BigInt(Number.MIN_SAFE_INTEGER) ? Number(big) : big.toString();
}

async function sdo(b, p) {
  const F = "sdo";
  const write = p.action === "write" || (p.action !== "read" && p.value !== undefined);
  const network = net(b, p, "canopen", F);
  const node = int(p.node, "node", 1, 127, F);
  const index = int(p.index, "index", 0, 0xffff, F);
  const subindex = int(p.subindex, "subindex", 0, 255, F, 0);
  const type = p.type || "unsigned";
  if (!TYPES.includes(type)) throw fail(F, 6, "type must be one of " + TYPES.join(", "));
  const numeric = type === "unsigned" || type === "signed" || type === "real";
  const size = numeric ? int(p.size, "size", 1, 8, F, 4) : 0;
  if (type === "real" && size !== 4 && size !== 8) throw fail(F, 6, "a real is 4 or 8 bytes");
  if (numeric && ![1, 2, 4, 8].includes(size)) throw fail(F, 6, "size must be 1, 2, 4 or 8");
  const timeout = timeoutOf(p, F, b.lay.sdoTimeoutMs);
  let data = null;
  if (write) {
    if (p.value === undefined) throw fail(F, 6, "a write needs a value");
    if (numeric) data = numberToLe(p.value, type, size, F);
    else if (type === "string") data = Buffer.from(String(p.value), "utf8");
    else {
      try {
        data = codec.toBytes(p.value);
      } catch (e) {
        throw fail(F, 6, e.message);
      }
    }
    if (data.length > SDO_MAX) throw fail(F, 7, "at most " + SDO_MAX + " bytes");
  }
  // Numbers up to 4 bytes go through the SDO registers when the config has them.
  if (numeric && size <= 4 && (b.hasSdoRegisters() || !b.mb.length)) {
    let raw = 0;
    if (write) for (let i = size - 1; i >= 0; i--) raw = raw * 256 + data[i];
    let got;
    try {
      got = await b.sdoShort({ write, net: network, node, index, subindex, length: size, value: raw, timeoutMs: timeout });
    } catch (e) {
      throw inFamily(F, e);
    }
    if (write) return { payload: true };
    const le = Buffer.alloc(4);
    le.writeUInt32LE(got >>> 0);
    return { payload: leToNumber(le.subarray(0, size), type) };
  }
  const kind = type === "string" ? 2 : 3;
  const args = [(node << 8) | subindex, index, (kind << 8) | (numeric ? size : 0), timeout, write ? data.length : 0, 0];
  try {
    if (write) {
      const a = await b.withMailbox(async (lease) => {
        await stage(lease, data);
        return lease.call(L.ops.sdo_write, network, args, data.length <= L.chunk ? data : null, timeout + 5000);
      });
      if (a.error) throw fail(F, a.error, a.error === 1 ? "the node aborted: " + T.abortText(a.r[2] * 65536 + a.r[3]) : undefined,
        { abortCode: a.r[2] * 65536 + a.r[3] });
      return { payload: true };
    }
    const buf = await b.withMailbox((lease) => fetchAll(lease, L.ops.sdo_read, network, args, SDO_MAX, "sdo", null, timeout + 5000));
    if (buf.total > SDO_MAX) throw fail(F, 7, "the object is " + buf.total + " bytes, more than " + SDO_MAX, { size: buf.total });
    if (type === "bytes") return { payload: Buffer.from(buf) };
    if (type === "string") {
      const end = buf.indexOf(0);
      return { payload: buf.subarray(0, end < 0 ? buf.length : end).toString("utf8") };
    }
    return { payload: leToNumber(buf, type) };
  } catch (e) {
    if (e.answer && e.answer.error) {
      const abort = e.answer.r[2] * 65536 + e.answer.r[3];
      throw fail(F, e.answer.error, e.answer.error === 1 ? "the node aborted: " + T.abortText(abort) : undefined, { abortCode: abort });
    }
    throw inFamily(F, e);
  }
}

// ---- NMT ----

async function nmt(b, p) {
  try {
    await b.nmt(p.command, p.network, p.node, timeoutOf(p, "sdo"));
    return { payload: true };
  } catch (e) {
    throw inFamily("sdo", e);
  }
}

// ---- CAN frames ----

function frameOf(p, family) {
  const extended = p.extended === true || p.extended === "true";
  const id = int(p.id, "id", 0, extended ? 0x1fffffff : 0x7ff, family);
  let data;
  try {
    data = codec.toBytes(p.data);
  } catch (e) {
    throw fail(family, 3, e.message);
  }
  const dlc = int(p.dlc, "dlc", 0, 8, family, Math.min(8, data.length));
  if (data.length > 8) throw fail(family, 3, "a CAN frame carries at most 8 bytes");
  const full = Buffer.alloc(8);
  data.copy(full);
  return { id, extended, rtr: p.rtr === true || p.rtr === "true", dlc, data: full };
}

async function canSend(b, p) {
  const F = "can";
  const network = net(b, p, "can", F);
  const f = frameOf(p, F);
  const flags = (f.extended ? L.canFlags.extended : 0) | (f.rtr ? L.canFlags.rtr : 0);
  const ms = int(p.timeout, "timeout", 0, 60000, F, 0) || 1000;
  try {
    const a = await b.withMailbox((lease) => lease.call(L.ops.can_send, network, [Math.floor(f.id / 65536), f.id & 0xffff, (flags << 8) | f.dlc, ms, 0, 0], f.data, ms + 5000));
    if (a.error) throw fail(F, a.error);
    return { payload: true };
  } catch (e) {
    throw inFamily(F, e);
  }
}

function cyclicFrame(b, p) {
  const F = "can";
  const f = frameOf(p, F);
  f.net = net(b, p, "can", F);
  f.period = int(p.period, "period", 1, 60000, F);
  return f;
}

// ---- J1939 ----

function pgnOf(p, family) {
  return int(p.pgn, "pgn", 0, 0x3ffff, family);
}

async function j1939Send(b, p) {
  const F = "j1939";
  const network = net(b, p, "j1939", F);
  const pgn = pgnOf(p, F);
  const destination = int(p.destination, "destination", 0, 255, F, 255);
  const priority = int(p.priority, "priority", 0, 7, F, 6);
  let data;
  try {
    data = codec.toBytes(p.data);
  } catch (e) {
    throw fail(F, 3, e.message);
  }
  if (data.length > L.buffer) throw fail(F, 3, "at most " + L.buffer + " bytes");
  const ms = timeoutOf(p, F);
  try {
    const a = await b.withMailbox(async (lease) => {
      await stage(lease, data);
      return lease.call(L.ops.j1939_send, network, [Math.floor(pgn / 65536), pgn & 0xffff, (destination << 8) | priority, data.length, ms, 0],
        data.length <= L.chunk ? data : null, ms + 5000);
    });
    if (a.error) throw fail(F, a.error);
    return { payload: true };
  } catch (e) {
    throw inFamily(F, e);
  }
}

async function j1939Request(b, p) {
  const F = "j1939";
  const network = net(b, p, "j1939", F);
  const pgn = pgnOf(p, F);
  const destination = int(p.destination, "destination", 0, 255, F, 255);
  const ms = timeoutOf(p, F);
  try {
    const buf = await b.withMailbox((lease) => fetchAll(lease, L.ops.j1939_request, network, [Math.floor(pgn / 65536), pgn & 0xffff, destination, ms, 0, 0], L.buffer, 1, null, ms + 5000));
    return { payload: Buffer.from(buf), extra: { pgn, source: buf.answer.r[0], length: buf.total } };
  } catch (e) {
    if (e.answer && e.answer.error) throw fail(F, e.answer.error, undefined, { ackCode: e.answer.r[2] });
    throw inFamily(F, e);
  }
}

function splitDtc(d) {
  return { spn: d & 0x7ffff, fmi: (d >>> 19) & 0x1f, oc: (d >>> 24) & 0x7f, cm: (d >>> 31) === 1, dtc: d >>> 0 };
}

async function dm(b, p) {
  const F = "j1939";
  const network = net(b, p, "j1939", F);
  const ms = timeoutOf(p, F);
  const previous = p.previous === true || p.previous === "true";
  try {
    if (p.action === "clear") {
      const destination = int(p.address, "address", 0, 255, F);
      const a = await b.withMailbox((lease) => lease.call(L.ops.dm_clear, network, [destination, previous ? 1 : 0, ms, 0, 0, 0], null, ms + 5000));
      if (a.error) throw fail(F, a.error);
      return { payload: true };
    }
    const source = int(p.address, "address", 0, 253, F);
    const a = await b.withMailbox((lease) => lease.call(L.ops.dm_read, network, [source, previous ? 1 : 0, ms, 0, 0, 0], null, ms + 5000));
    if (a.error) throw fail(F, a.error);
    const count = Math.min(a.r[1], 32);
    const codes = [];
    for (let i = 0; i < count; i++) codes.push(splitDtc(a.data.readUInt32BE(4 * i)));
    return {
      payload: codes,
      extra: { lamps: a.r[0] >> 8, flash: a.r[0] & 255, count: a.r[1], ageMs: a.r[2] * 65536 + a.r[3], previous },
    };
  } catch (e) {
    throw inFamily(F, e);
  }
}

function nameToBig(v, what, family) {
  if (v === undefined || v === null || v === "") return 0n;
  try {
    return BigInt.asUintN(64, BigInt(typeof v === "string" ? v.trim() : v));
  } catch (e) {
    throw fail(family, 3, what + " must be a 64-bit number or a decimal or 0x string");
  }
}

function splitName(n) {
  const f = (s, m) => Number((n >> BigInt(s)) & BigInt(m));
  return {
    name: n.toString(), identity: f(0, 0x1fffff), manufacturer: f(21, 0x7ff), ecuInstance: f(32, 7),
    functionInstance: f(35, 0x1f), function: f(40, 0xff), vehicleSystem: f(49, 0x7f),
    vehicleSystemInstance: f(56, 0xf), industryGroup: f(60, 7), arbitraryAddressCapable: f(63, 1) === 1,
  };
}

async function findEcu(b, p) {
  const F = "j1939";
  const network = net(b, p, "j1939", F);
  const name = nameToBig(p.name, "name", F);
  const mask = p.mask === undefined || p.mask === "" ? (1n << 64n) - 1n : nameToBig(p.mask, "mask", F);
  const data = Buffer.alloc(16);
  data.writeBigUInt64BE(name, 0);
  data.writeBigUInt64BE(mask, 8);
  try {
    const a = await b.withMailbox((lease) => lease.call(L.ops.find_ecu, network, [0, 0, 0, 0, 0, 0], data));
    if (a.error) throw fail(F, a.error);
    const found = a.r[0] !== 0;
    return {
      payload: found ? a.r[1] : null,
      extra: { found, address: a.r[1], count: a.r[2], ecu: found ? splitName(a.data.readBigUInt64BE(0)) : null },
    };
  } catch (e) {
    throw inFamily(F, e);
  }
}

function inFamilyNet(b, network, kind, family) {
  return net(b, { network }, kind, family);
}

module.exports = { inFamilyNet, sdo, nmt, canSend, cyclicFrame, j1939Send, j1939Request, dm, findEcu, splitName, splitDtc, inFamily, fail, int };
