// codec.js - register map values to and from the byte image (the rules of
// modbus-bridge-map: high byte first in a register, word order per row,
// bits, REAL, scale and offset).
"use strict";

// A row from the layout: n name, b first byte, k kind (bit, signed,
// unsigned, real), size bytes, bit, lo (lowest word first), s scale, o
// offset, u unit, regs [first, last] register.

function valueBytes(img, r) {
  const out = Array.from(img.subarray(r.b, r.b + r.size));
  if (!r.lo) return out;
  const words = [];
  for (let i = 0; i < out.length; i += 2) words.push([out[i], out[i + 1]]);
  return [].concat(...words.reverse());
}

function storeBytes(img, r, bytes) {
  let src = bytes;
  if (r.lo) {
    const words = [];
    for (let i = 0; i < bytes.length; i += 2) words.push([bytes[i], bytes[i + 1]]);
    src = [].concat(...words.reverse());
  }
  for (let i = 0; i < src.length; i++) img[r.b + i] = src[i];
}

function decode(img, r) {
  if (r.k === "bit") return ((img[r.b] >> r.bit) & 1) === 1;
  const bytes = valueBytes(img, r);
  let v;
  if (r.k === "real") {
    const dv = new DataView(new Uint8Array(bytes).buffer);
    v = r.size === 8 ? dv.getFloat64(0) : dv.getFloat32(0);
  } else if (r.size === 8) {
    let big = 0n;
    for (const x of bytes) big = (big << 8n) | BigInt(x);
    if (r.k === "signed") big = BigInt.asIntN(64, big);
    // Beyond 2^53 a decimal string: exact, and safe for the debug sidebar and context stores.
    v = big <= BigInt(Number.MAX_SAFE_INTEGER) && big >= BigInt(Number.MIN_SAFE_INTEGER) ? Number(big) : big.toString();
  } else {
    v = 0;
    for (const x of bytes) v = v * 256 + x;
    const bits = r.size * 8;
    if (r.k === "signed" && v >= Math.pow(2, bits - 1)) v -= Math.pow(2, bits);
  }
  if (r.s !== undefined || r.o !== undefined) v = Number(v) * (r.s === undefined ? 1 : r.s) + (r.o || 0);
  return v;
}

// Writes `value` into the image; returns an error text, or null.
function encode(img, r, value) {
  if (r.k === "bit") {
    if (value !== true && value !== false && value !== 0 && value !== 1)
      return "needs true or false, not " + JSON.stringify(value);
    if (value === true || value === 1) img[r.b] |= 1 << r.bit;
    else img[r.b] &= ~(1 << r.bit) & 255;
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
    if (r.size === 8) dv.setFloat64(0, v);
    else dv.setFloat32(0, v);
    for (let i = 0; i < r.size; i++) bytes[i] = dv.getUint8(i);
    storeBytes(img, r, bytes);
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
  for (let i = r.size - 1; i >= 0; i--) {
    bytes[i] = Number(big & 255n);
    big >>= 8n;
  }
  storeBytes(img, r, bytes);
  return null;
}

// Data given as a Buffer, an array of byte values, or a hex string ("01 02",
// "0102", "0x0102").
function toBytes(data) {
  if (data === undefined || data === null) return Buffer.alloc(0);
  if (Buffer.isBuffer(data)) return data;
  if (data instanceof Uint8Array) return Buffer.from(data);
  if (Array.isArray(data)) {
    for (const x of data) if (!Number.isInteger(x) || x < 0 || x > 255) throw new Error("data bytes must be 0-255");
    return Buffer.from(data);
  }
  if (typeof data === "string") {
    const hex = data.replace(/^0x/i, "").replace(/[\s:,-]/g, "");
    if (!/^([0-9a-fA-F]{2})*$/.test(hex)) throw new Error("data must be bytes or a hex string");
    return Buffer.from(hex, "hex");
  }
  if (data && data.type === "Buffer" && Array.isArray(data.data)) return Buffer.from(data.data);
  throw new Error("data must be a Buffer, an array of bytes or a hex string");
}

// Bytes into request words (byte 2k in the high byte of word k) and back.
function bytesToWords(bytes, nwords) {
  const out = new Array(nwords).fill(0);
  for (let i = 0; i < bytes.length && i < nwords * 2; i++) out[i >> 1] |= i & 1 ? bytes[i] : bytes[i] << 8;
  return out;
}

function wordsToBytes(words, n) {
  const out = Buffer.alloc(n);
  for (let i = 0; i < n; i++) out[i] = i & 1 ? words[i >> 1] & 255 : words[i >> 1] >> 8;
  return out;
}

module.exports = { decode, encode, toBytes, bytesToWords, wordsToBytes };
