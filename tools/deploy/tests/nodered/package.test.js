// package.test.js - node-red-canworks against a scripted model of the
// bridge (fake_bridge.js), on the flow of the example config with mailboxes
// (tests/data/nodered/modbus-bridge-mailboxes.json, kept fresh by
// test_nodered.py). Run: node --test tools/deploy/tests/nodered/
"use strict";

const test = require("node:test");
const assert = require("node:assert");
const path = require("path");

const { makeRuntime, PACKAGE } = require("./harness");
const { FakeBridge, L } = require("./fake_bridge");
const { Bridge } = require(path.join(PACKAGE, "lib", "bridge"));

const FLOW = require(path.join(__dirname, "..", "data", "nodered", "modbus-bridge-mailboxes.json"));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// The runtime of the running test, closed after it however it ended.
let current = null;
test.afterEach(async () => {
  if (current) await finish(current);
});

// The flow with its layout changed by `patch(layout)`; a J1939 network "truck" next to "field".
function setup(patch, options) {
  const flow = JSON.parse(JSON.stringify(FLOW));
  const cfg = flow.find((n) => n.type === "canworks-bridge");
  const lay = JSON.parse(cfg.layout);
  lay.networks.push({ index: 1, name: "truck", kinds: ["can", "j1939"] });
  if (patch) patch(lay, cfg);
  cfg.layout = JSON.stringify(lay);
  const model = new FakeBridge(lay);
  if (options && options.before) options.before(model);
  Bridge.clientFactory = model.factory();
  const rt = makeRuntime();
  const made = rt.load(flow);
  const B = cfg.id;
  let n = 0;
  const add = (type, fields) => rt.add(Object.assign({ id: "n" + ++n, type, z: "t", bridge: B }, fields));
  current = {
    rt, model, lay, B, add,
    inNode: made.find((x) => x.type === "canworks-in"),
    outNode: made.find((x) => x.type === "canworks-out"),
    bridge: rt.nodes.get(B).bridge,
  };
  return current;
}

async function finish(t) {
  if (current === t) current = null;
  await t.rt.close();
  Bridge.clientFactory = null;
}

function word(model, byte) {
  return model.hold[byte / 2];
}

function last(node) {
  return node.statuses[node.statuses.length - 1] || {};
}

async function run(t, node, msg) {
  const from = node.sent.length;
  await t.rt.input(node, msg || {});
  return node.sent[from];
}

const ready = (t) => t.rt.until(() => t.bridge.seeded && t.bridge.haveInput, 3000, "bridge up");

// ---- connection and values ----

test("one connection for every node; values once, then changes; topic filter", async () => {
  const t = setup(null, {
    before: (m) => {
      m.inp[5] = 0xfb2e; // dio.0x6401:1 at byte 10: -1234
    },
  });
  const filtered = t.add("canworks-in", { filter: "dio.0x64*, bridge.state" });
  t.add("canworks-sdo", { node: "5", index: "0x1000" });
  t.add("canworks-sdo", { node: "6", index: "0x1000" });
  t.add("canworks-can-receive", { network: "field", can_id: "0x181" });
  await ready(t);
  await t.rt.until(() => t.inNode.sent.some((m) => m.topic === "dio.0x6401:1"), 2000);
  assert.strictEqual(t.model.connects, 1);
  const v = t.inNode.sent.find((m) => m.topic === "dio.0x6401:1");
  assert.strictEqual(v.payload, -1234);
  assert.deepStrictEqual(filtered.sent.map((m) => m.topic).sort(), ["bridge.state", "dio.0x6401:1", "dio.0x6401:2"]);
  const before = t.inNode.sent.length;
  t.model.inp[5] = 5;
  await t.rt.until(() => t.inNode.sent.length > before, 1000);
  await sleep(50);
  assert.deepStrictEqual(t.inNode.sent.slice(before).map((m) => [m.topic, m.payload]), [["dio.0x6401:1", 5]]);
  await finish(t);
});

test("outputs: read back before the first write, held values, range refusal", async () => {
  const t = setup(null, {
    before: (m) => {
      m.hold[1] = 0x1234; // dio.0x6411:1 at %QW2 (holding register 1)
    },
  });
  // Set before the connection: held until the read-back.
  await t.rt.input(t.outNode, { topic: "dio.0x6200:1", payload: 9 });
  await ready(t);
  await t.rt.until(() => t.model.hold[0] >> 8 === 9, 1000, "held value written");
  assert.strictEqual(t.model.hold[1], 0x1234, "the read-back value kept, not zero");
  const first = t.model.writes[0];
  assert.strictEqual(first[1][1], 0x1234, "the first write carries what the bridge had");
  await t.rt.input(t.outNode, { topic: "dio.0x6411:1", payload: 5 });
  await t.rt.until(() => t.model.hold[1] === 5, 1000);
  await t.rt.input(t.outNode, { topic: "dio.0x6411:1", payload: 40000 });
  await sleep(50);
  assert.strictEqual(t.model.hold[1], 5);
  assert.match(t.outNode.warnings[0], /out of range/);
  await t.rt.input(t.outNode, { topic: "nope", payload: 1 });
  assert.match(t.outNode.warnings[1], /no output named "nope"/);
  await finish(t);
});

test("watchdog: outputs rewritten at least every third of watchdog_ms", async () => {
  const t = setup();
  await ready(t);
  const n0 = t.model.writes.length;
  await sleep(1100);
  const outs = t.model.writes.slice(n0).filter((w) => w[0] === 0);
  assert.ok(outs.length >= 3, "rewrites in 1 s: " + outs.length);
  await finish(t);
});

test("writes refused: status says so", async () => {
  const t = setup(null, { before: (m) => (m.refuseWrites = true) });
  const sdo = t.add("canworks-sdo", { node: "5", index: "0x1000" });
  await t.rt.until(() => /writes refused/.test(last(sdo).text || ""), 2000, "refused status");
  await finish(t);
});

// ---- NMT and SDO registers ----

test("nmt: control block, result 6 is ERROR_ID 8, bad command", async () => {
  const t = setup();
  const nmt = t.add("canworks-nmt", { node: "6" });
  await ready(t);
  let m = await run(t, nmt, { payload: "stop" });
  assert.strictEqual(m.canworks.status, "done");
  assert.deepStrictEqual(t.model.controls[0], { cmd: 4, net: 0, node: 6 });
  t.model.controlResult = () => 6;
  m = await run(t, nmt, { payload: "start" });
  assert.strictEqual(m.canworks.errorId, 8);
  m = await run(t, nmt, { payload: "jump" });
  assert.strictEqual(m.canworks.errorId, 6);
  assert.match(last(nmt).text, /ERROR_ID 6/);
  await finish(t);
});

test("sdo up to 4 bytes through the SDO registers; aborts", async () => {
  const t = setup();
  t.model.od.set("5:4120:1", 0x12345678);
  t.model.od.set("5:4096:0", { abort: 0x08000021 });
  t.model.od.set("6:25088:1", 0);
  const sdo = t.add("canworks-sdo", { node: "5", index: "0x1018", subindex: "1" });
  await ready(t);
  let m = await run(t, sdo, { topic: "serial" });
  assert.strictEqual(m.payload, 0x12345678);
  assert.strictEqual(m.topic, "serial");
  assert.strictEqual(m.canworks.status, "done");
  assert.strictEqual(t.model.calls.length, 0, "no mailbox used");
  m = await run(t, sdo, { payload: { index: 0x1000, subindex: 0 } });
  assert.strictEqual(m.canworks.errorId, 8);
  m = await run(t, sdo, { payload: { node: 5, index: 0x2000 } });
  assert.strictEqual(m.canworks.errorId, 1);
  assert.strictEqual(m.canworks.abortCode, 0x06020000);
  assert.match(m.canworks.abortText, /object does not exist/);
  const w = t.add("canworks-sdo", { node: "6", index: "0x6200", subindex: "1", action: "write", size: "1" });
  m = await run(t, w, { payload: 7 });
  assert.strictEqual(m.canworks.status, "done");
  assert.deepStrictEqual(t.model.sdos[t.model.sdos.length - 1], { write: true, net: 0, node: 6, index: 0x6200, sub: 1, len: 1, value: 7 });
  m = await run(t, w, { payload: 300 });
  assert.strictEqual(m.canworks.errorId, 6);
  await finish(t);
});

// ---- request mailboxes ----

function sdoReadOp(objects) {
  return (req) => {
    const node = req.args[0] >> 8, sub = req.args[0] & 255, index = req.args[1];
    const data = objects[node + ":" + index + ":" + sub];
    if (!data) return { error: 1, r: [0, 0, 0x0602, 0] };
    return { r: [Math.floor(data.length / 65536), data.length & 0xffff], data: data.subarray(0, L.chunk), full: data };
  };
}

function withFetch(model, objects) {
  let last = null;
  const read = sdoReadOp(objects);
  model.ops[L.ops.sdo_read] = (req) => {
    const a = read(req);
    last = a.full;
    return a;
  };
  model.ops[L.ops.fetch] = (req) => ({ r: [last.length], data: last.subarray(req.args[0], req.args[0] + L.chunk) });
}

test("long SDO reads: string and bytes over a mailbox with FETCH", async () => {
  const t = setup();
  const name = Buffer.from("A device name forty characters long......");
  const long = Buffer.alloc(300, 0).map((_, i) => i & 255);
  withFetch(t.model, { "6:4104:0": name, "6:8448:0": long });
  const sdo = t.add("canworks-sdo", { node: "6", index: "0x1008", datatype: "string" });
  await ready(t);
  let m = await run(t, sdo);
  assert.strictEqual(m.payload, name.toString());
  assert.strictEqual(t.model.calls[0].args[2] >> 8, 2, "kind STRING");
  m = await run(t, sdo, { payload: { index: 0x2100, type: "bytes" } });
  assert.ok(Buffer.isBuffer(m.payload));
  assert.deepStrictEqual(m.payload, long);
  assert.deepStrictEqual(t.model.calls.slice(-2).map((c) => [c.op, c.args[0]]), [[L.ops.fetch, 128], [L.ops.fetch, 256]]);
  await finish(t);
});

test("three reads, one mailbox: in order, each its own result", async () => {
  const t = setup((lay) => (lay.mailboxes.requests = lay.mailboxes.requests.slice(0, 1)));
  const objs = { "6:8192:1": Buffer.from("one"), "6:8192:2": Buffer.from("two"), "6:8192:3": Buffer.from("three") };
  const read = sdoReadOp(objs);
  t.model.ops[L.ops.sdo_read] = (req) => sleep(20).then(() => read(req));
  const sdo = t.add("canworks-sdo", { node: "6", index: "0x2000", datatype: "string" });
  await ready(t);
  await Promise.all([1, 2, 3].map((s) => t.rt.input(sdo, { topic: "sub" + s, payload: { subindex: s } })));
  assert.deepStrictEqual(sdo.sent.map((m) => [m.topic, m.payload]), [["sub1", "one"], ["sub2", "two"], ["sub3", "three"]]);
  assert.deepStrictEqual(t.model.calls.map((c) => c.args[0] & 255), [1, 2, 3]);
  await finish(t);
});

test("long SDO write is STAGEd; the counter is new each time", async () => {
  const t = setup();
  const staged = [];
  t.model.ops[L.ops.stage] = (req) => {
    staged.push([req.args[0], req.args[1]]);
    return {};
  };
  const sdo = t.add("canworks-sdo", { node: "6", index: "0x2100", action: "write", datatype: "bytes" });
  await ready(t);
  const m = await run(t, sdo, { payload: Buffer.alloc(200, 1) });
  assert.strictEqual(m.canworks.status, "done");
  assert.deepStrictEqual(staged, [[0, 128], [128, 72]]);
  const counters = t.model.calls.map((c) => c.counter);
  assert.strictEqual(new Set(counters).size, counters.length);
  await finish(t);
});

test("queue limit: jobs beyond 64 waiting end with 5 (CAN) and 9 (J1939)", async () => {
  const t = setup();
  t.model.ops[L.ops.can_send] = () => new Promise(() => {}); // never answers
  t.model.ops[L.ops.j1939_send] = () => new Promise(() => {});
  const send = t.add("canworks-can-send", { network: "field", can_id: "0x123", data: "01", timeout: "60000" });
  const j = t.add("canworks-j1939-send", { network: "truck", pgn: "0xfeca", data: "01" });
  await ready(t);
  for (let i = 0; i < 2 + 64; i++) t.rt.input(send, {});
  await sleep(30);
  const m = await run(t, send);
  assert.strictEqual(m.canworks.errorId, 5);
  const k = await run(t, j);
  assert.strictEqual(k.canworks.errorId, 9);
  await finish(t);
});

test("a missing bridge part: ERROR_ID 22 with the reason", async () => {
  const t = setup((lay) => (lay.mailboxes = null));
  const send = t.add("canworks-can-send", { network: "field", can_id: "0x123", data: "01" });
  await ready(t);
  const m = await run(t, send);
  assert.strictEqual(m.canworks.errorId, 22);
  assert.match(m.canworks.text, /no request mailbox/);
  assert.match(last(send).text, /ERROR_ID 22/);
  await finish(t);
});

test("can send, j1939 send/request/dm/find ecu: arguments and results", async () => {
  const t = setup();
  const m = t.model;
  m.ops[L.ops.j1939_request] = () => ({ r: [0x21, 3, 0], data: Buffer.from([1, 2, 3]) });
  const dtc = (spn, fmi, oc) => ((oc & 0x7f) << 24) | ((fmi & 0x1f) << 19) | (spn & 0x7ffff);
  m.ops[L.ops.dm_read] = () => {
    const d = Buffer.alloc(8);
    d.writeUInt32BE(dtc(100, 3, 2) >>> 0, 0);
    d.writeUInt32BE(dtc(520000, 31, 127) >>> 0, 4);
    return { r: [(0x14 << 8) | 0, 2, 0, 1500], data: d };
  };
  m.ops[L.ops.find_ecu] = () => {
    const d = Buffer.alloc(8);
    d.writeBigUInt64BE(0x8000000000a00105n);
    return { r: [1, 0x30, 2], data: d };
  };
  const send = t.add("canworks-can-send", { network: "field", can_id: "0x18ff0001", extended: true, data: "01 02 03" });
  const req = t.add("canworks-j1939-request", { network: "truck", pgn: "65260", destination: "0x21" });
  const dm = t.add("canworks-j1939-dm", { network: "truck", address: "0x21" });
  const find = t.add("canworks-find-ecu", { network: "truck", ecu_name: "0x00000000000001", mask: "0xff" });
  await ready(t);
  let x = await run(t, send);
  assert.strictEqual(x.canworks.status, "done");
  let c = m.calls[m.calls.length - 1];
  assert.deepStrictEqual([c.op, c.args[0], c.args[1], c.args[2]], [L.ops.can_send, 0x18ff, 0x0001, (1 << 8) | 3]);
  assert.deepStrictEqual([...c.data.subarray(0, 3)], [1, 2, 3]);
  x = await run(t, req);
  assert.deepStrictEqual([...x.payload], [1, 2, 3]);
  assert.strictEqual(x.canworks.source, 0x21);
  c = m.calls[m.calls.length - 1];
  assert.deepStrictEqual([c.net, c.args[0], c.args[1], c.args[2]], [1, 0, 65260, 0x21]);
  x = await run(t, dm);
  assert.deepStrictEqual(x.payload.map((d) => [d.spn, d.fmi, d.oc]), [[100, 3, 2], [520000, 31, 127]]);
  assert.strictEqual(x.canworks.lamps, 0x14);
  assert.strictEqual(x.canworks.ageMs, 1500);
  x = await run(t, find);
  assert.strictEqual(x.payload, 0x30);
  assert.strictEqual(x.canworks.ecu.arbitraryAddressCapable, true);
  c = m.calls[m.calls.length - 1];
  assert.strictEqual(c.data.readBigUInt64BE(0), 1n);
  assert.strictEqual(c.data.readBigUInt64BE(8), 0xffn);
  x = await run(t, dm, { payload: { network: "field" } });
  assert.strictEqual(x.canworks.errorId, 10, "field is not a J1939 network");
  await finish(t);
});

// ---- receivers ----

function canRecord(slot, id, data, i) {
  const words = [Math.floor(id / 65536), id & 0xffff, data.length, 0, 0, 0, 0];
  for (let k = 0; k < data.length; k++) words[3 + (k >> 1)] |= k & 1 ? data[k] : data[k] << 8;
  return { slot, kind: "can", timeUs: 1700000000000000 + i * 250, body: words };
}

test("can receive: 20 frames between polls arrive in order and are acknowledged", async () => {
  const t = setup();
  const rx = t.add("canworks-can-receive", { network: "field", can_id: "0x181", depth: "32" });
  await ready(t);
  await t.rt.until(() => t.model.slotOf("can") >= 0, 2000, "receiver open");
  const open = t.model.calls.find((c) => c.op === L.ops.rx_open);
  assert.deepStrictEqual(open.args, [(1 << 8) | 0, 32, 0, 0x181, 0, 0x7ff]);
  const slot = t.model.slotOf("can");
  t.model.push(Array.from({ length: 20 }, (_, i) => canRecord(slot, 0x181, [i, 0xaa], i)));
  await t.rt.until(() => rx.sent.length >= 20, 3000, "20 records");
  assert.deepStrictEqual(rx.sent.map((m) => m.payload.data[0]), Array.from({ length: 20 }, (_, i) => i));
  assert.strictEqual(rx.sent[3].payload.id, 0x181);
  assert.strictEqual(rx.sent[0].payload.time.getTime(), 1700000000000);
  await t.rt.until(() => t.model.acked === t.model.rxSeq && !t.model.rxPending.length, 1000, "all acknowledged");
  await finish(t);
});

test("receiver closed by the bridge: one ERROR_ID 8 message, then it opens again", async () => {
  const t = setup();
  const rx = t.add("canworks-can-receive", { network: "field", can_id: "0x181" });
  await ready(t);
  await t.rt.until(() => t.model.slotOf("can") >= 0, 2000);
  t.model.closeReceiver(t.model.slotOf("can"));
  await t.rt.until(() => rx.sent.length === 1, 1000, "the error message");
  assert.strictEqual(rx.sent[0].canworks.errorId, 8);
  await t.rt.until(() => t.model.calls.filter((c) => c.op === L.ops.rx_open).length === 2, 3000, "opened again");
  await finish(t);
});

test("j1939 receive: filter and a long message fetched with RX_FETCH", async () => {
  const t = setup();
  const long = Buffer.alloc(200).map((_, i) => i & 255);
  t.model.ops[L.ops.rx_fetch] = (req) => ({ r: [long.length], data: long.subarray(0, L.chunk) });
  t.model.ops[L.ops.fetch] = (req) => ({ r: [long.length], data: long.subarray(req.args[0], req.args[0] + L.chunk) });
  const rx = t.add("canworks-j1939-receive", { network: "truck", pgn: "0xfeca", source: "0x21", all_destinations: true });
  await ready(t);
  await t.rt.until(() => t.model.slotOf("j1939") >= 0, 2000);
  const open = t.model.calls.find((c) => c.op === L.ops.rx_open);
  assert.deepStrictEqual([open.net, open.args[0], open.args[3], open.args[5]], [1, (2 << 8) | 2, 0xfeca, 0x21]);
  const slot = t.model.slotOf("j1939");
  t.model.push([{ slot, kind: "j1939", flags: L.recordFlags.long, body: [0, 0xfeca, (0x21 << 8) | 0xff, 6, 200] }]);
  await t.rt.until(() => rx.sent.length === 1, 2000);
  const p = rx.sent[0].payload;
  assert.deepStrictEqual([p.pgn, p.source, p.destination, p.priority], [0xfeca, 0x21, 0xff, 6]);
  assert.deepStrictEqual(p.data, long);
  await finish(t);
});

test("emcy: node filter and record fields", async () => {
  const t = setup();
  const rx = t.add("canworks-emcy", { network: "field", node: "6", skip_old: true });
  await ready(t);
  await t.rt.until(() => t.model.slotOf("emcy") >= 0, 2000);
  const open = t.model.calls.find((c) => c.op === L.ops.rx_open);
  assert.deepStrictEqual([open.args[0], open.args[5]], [(3 << 8) | 1, 6]);
  t.model.push([{ slot: t.model.slotOf("emcy"), kind: "emcy", body: [(6 << 8) | 0x81, 0x8130, 0x0102, 0x0304, 0x0500] }]);
  await t.rt.until(() => rx.sent.length === 1, 2000);
  const p = rx.sent[0].payload;
  assert.deepStrictEqual([p.node, p.register, p.code, [...p.data]], [6, 0x81, 0x8130, [1, 2, 3, 4, 5]]);
  await finish(t);
});

// ---- cyclic jobs ----

test("can cyclic: start, keepalive every poll, change, stop; a job the bridge ended is set up again", async () => {
  const t = setup();
  const cyc = t.add("canworks-can-cyclic", { network: "field", can_id: "0x321", data: "aa bb", period: "100" });
  await ready(t);
  let m = await run(t, cyc);
  assert.strictEqual(m.canworks.status, "done");
  const set = t.model.calls.find((c) => c.op === L.ops.cyclic_set);
  assert.deepStrictEqual(set.args.slice(0, 5), [0xffff, 0, 0x321, 2, 100]);
  const ka = t.lay.mailboxes.cyclic.keepalive;
  const k0 = word(t.model, ka);
  await sleep(60);
  assert.notStrictEqual(word(t.model, ka), k0, "keepalive moves");
  m = await run(t, cyc, { payload: { period: 50 } });
  const change = t.model.calls.filter((c) => c.op === L.ops.cyclic_set)[1];
  assert.strictEqual(change.args[0], 0, "the same slot");
  // The bridge ends the job (link stop): one message, then set up again.
  t.model.jobs.delete(0);
  await t.rt.until(() => cyc.sent.length === 3, 1000, "ended message");
  assert.strictEqual(cyc.sent[2].canworks.errorId, 8);
  await t.rt.until(() => t.model.jobs.has(0), 3000, "set up again");
  m = await run(t, cyc, { payload: { action: "stop" } });
  assert.strictEqual(m.canworks.status, "done");
  assert.strictEqual(t.model.jobs.size, 0);
  await finish(t);
});

// ---- restart, loss, read-only ----

test("bridge restart while idle: the old request is a baseline, the next job runs", async () => {
  const t = setup(null, {
    before: (m) => {
      // The last CAN send's request still in mailbox 0's holding registers.
      const at = m.lay.mailboxes.requests[0].req / 2;
      m.hold[at] = 5;
      m.hold[at + 1] = L.ops.can_send << 8;
    },
  });
  const send = t.add("canworks-can-send", { network: "field", can_id: "0x123", data: "01" });
  await ready(t);
  await sleep(50);
  assert.strictEqual(t.model.calls.length, 0, "nothing ran again");
  const m = await run(t, send);
  assert.strictEqual(m.canworks.status, "done");
  assert.notStrictEqual(t.model.calls[0].counter, 5);
  await finish(t);
});

test("connection loss: running jobs end with 20, values flow again after the reconnect", async () => {
  const t = setup();
  t.model.ops[L.ops.can_send] = () => new Promise(() => {});
  const send = t.add("canworks-can-send", { network: "field", can_id: "0x123", data: "01" });
  await ready(t);
  const pending = run(t, send);
  await sleep(30);
  t.model.drop();
  const m = await pending;
  assert.strictEqual(m.canworks.errorId, 20);
  await t.rt.until(() => /reconnecting/.test(last(send).text || ""), 1000);
  t.model.up();
  t.model.restart();
  await t.rt.until(() => t.model.connects === 2 && t.bridge.seeded, 5000, "reconnected");
  const before = t.inNode.sent.length;
  t.model.inp[5] = 77;
  await t.rt.until(() => t.inNode.sent.length > before, 1000);
  await finish(t);
});

test("read-only: values come in, nothing is written, jobs end with 22", async () => {
  const t = setup((lay, cfg) => {
    lay.readOnly = true;
    lay.outputs = [];
    lay.write = [];
    cfg.readOnly = true;
  });
  const sdo = t.add("canworks-sdo", { node: "5", index: "0x1000" });
  const out = t.add("canworks-out", {});
  const rx = t.add("canworks-can-receive", { network: "field", can_id: "0x181" });
  await t.rt.until(() => t.inNode.sent.length > 5, 2000);
  const m = await run(t, sdo);
  assert.strictEqual(m.canworks.errorId, 22);
  assert.match(m.canworks.text, /read-only/);
  await t.rt.input(out, { topic: "dio.0x6200:1", payload: 1 });
  await t.rt.input(out, { topic: "dio.0x6200:1", payload: 2 });
  assert.strictEqual(out.warnings.length, 1);
  await t.rt.until(() => rx.sent.length === 1, 1000);
  assert.strictEqual(rx.sent[0].canworks.errorId, 22);
  assert.strictEqual(t.model.writes.length, 0);
  await finish(t);
});

test("a bridge node without a layout refuses to start", async () => {
  const rt = makeRuntime();
  const b = rt.add({ id: "b", type: "canworks-bridge", host: "127.0.0.1", port: 1502, layout: "" });
  const sdo = rt.add({ id: "s", type: "canworks-sdo", z: "t", bridge: "b", node: "5", index: "0x1000" });
  assert.match(b.errors[0], /export the flow from canworks/);
  const m = await new Promise((resolve) => {
    sdo.handlers.input[0]({}, resolve, () => {});
  });
  assert.strictEqual(m.canworks.errorId, 22);
  await rt.close();
});
