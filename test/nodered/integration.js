// integration.js - the package's nodes on the real bridge (run.py writes
// the config and flow): node integration.js BRIDGE CONFIG FLOW LONG_TEXT
"use strict";

const { spawn } = require("child_process");
const fs = require("fs");
const path = require("path");

const ROOT = path.join(__dirname, "..", "..");
const { makeRuntime } = require(path.join(ROOT, "tools", "deploy", "tests", "nodered", "harness.js"));

const [bridgeBin, cfgPath, flowPath, longText] = process.argv.slice(2);
const flow = JSON.parse(fs.readFileSync(flowPath, "utf8"));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const fails = [];

function check(ok, text) {
  console.log("    " + (ok ? "ok  " : "FAIL") + " " + text);
  if (!ok) fails.push(text);
}

let bridge = null;
const log = fs.openSync(path.join(path.dirname(cfgPath), "bridge.log"), "a");

function startBridge() {
  bridge = spawn(bridgeBin, ["--config", cfgPath], { stdio: ["ignore", log, log] });
}

function stopBridge() {
  return new Promise((resolve) => {
    if (!bridge || bridge.exitCode !== null) return resolve();
    bridge.once("exit", resolve);
    bridge.kill("SIGTERM");
  });
}

async function main() {
  startBridge();
  const rt = makeRuntime();
  const made = rt.load(flow);
  const B = flow.find((n) => n.type === "canworks-bridge").id;
  const b = rt.nodes.get(B).bridge;
  const inNode = made.find((n) => n.type === "canworks-in");
  const outNode = made.find((n) => n.type === "canworks-out");
  let n = 0;
  const add = (type, fields) => rt.add(Object.assign({ id: "i" + ++n, type, z: "t", bridge: B }, fields));
  const value = (topic) => {
    const m = b.values.get(topic);
    return m ? m.payload : undefined;
  };
  const job = async (node, msg) => {
    const from = node.sent.length;
    await rt.input(node, msg || {});
    return node.sent[from];
  };
  const until = (cond, ms) => rt.until(cond, ms || 10000).then(() => true, () => false);

  const sdo = add("canworks-sdo", { node: "5", index: "0x1018", subindex: "1" });
  const sdoText = add("canworks-sdo", { node: "6", index: "0x2100", datatype: "string" });
  const nmt = add("canworks-nmt", {});
  const rx = add("canworks-can-receive", { can_id: "0x706" });
  const send = add("canworks-can-send", { can_id: "0x123", data: "01 02" });
  const cyc = add("canworks-can-cyclic", { can_id: "0x321", data: "aa", period: "100" });

  console.log("1. values in and out");
  check(await until(() => value("bridge.state") === "running" && value("dio.state") === 5), "the bridge runs and the nodes are operational");
  check(await until(() => value("bridge.clients") === 1), "one connection for every node (" + value("bridge.clients") + " clients)");
  const rtd = value("rtd.0x7130:1");
  check(typeof rtd === "number" && rtd >= 200 && rtd <= 260, "a simulated value by name (rtd.0x7130:1 = " + rtd + ")");
  await rt.input(outNode, { topic: "dio.0x6200:1", payload: 0x5a });
  check(await until(() => value("dio.0x6000:1") === 0x5a), "canworks out reaches the node and comes back to canworks in");
  check(inNode.sent.filter((m) => m.topic === "dio.0x6000:1").length >= 2, "canworks in sends each change");

  console.log("2. SDO and NMT");
  let m = await job(sdo);
  check(m.canworks.status === "done" && typeof m.payload === "number", "0x1018:1 through the SDO registers (" + m.payload + ")");
  const t0 = Date.now();
  m = await job(sdoText);
  check(m.canworks.status === "done" && m.payload === longText, "a 1024-byte string through a request mailbox with FETCH (" + (Date.now() - t0) + " ms)");
  const names = await Promise.all([5, 6, 5].map((node) => job(add("canworks-sdo", { node: String(node), index: "0x1008", datatype: "string" }))));
  check(names.every((x) => x.canworks.status === "done" && x.payload.length > 0), "three device names at once share the mailbox (" + names.map((x) => x.payload).join(", ") + ")");
  m = await job(nmt, { payload: { command: "stop", node: 6 } });
  check(m.canworks.status === "done", "NMT stop of node 6 ends done");
  check(await until(() => value("field.node6.operational") === false), "node 6 leaves operational");
  await job(nmt, { payload: { command: "start", node: 6 } });
  check(await until(() => value("field.node6.operational") === true), "and comes back after NMT start");

  console.log("3. receive and cyclic");
  check(await until(() => rx.sent.length >= 5, 5000), "canworks can receive gets node 6's heartbeats (" + rx.sent.length + ")");
  const hb = rx.sent[rx.sent.length - 1];
  check(hb.payload && hb.payload.id === 0x706 && hb.payload.data.length === 1, "as {id, data} records");
  m = await job(send);
  check(m.canworks.status === "done", "canworks can send ends done");
  m = await job(cyc);
  check(m.canworks.status === "done", "canworks can cyclic starts");
  const ka = b.lay.mailboxes.cyclic.keepalive;
  const k0 = b.outImg.readUInt16BE(ka);
  await sleep(200);
  check(b.outImg.readUInt16BE(ka) !== k0, "its keepalive moves every poll");
  m = await job(cyc, { payload: { action: "stop" } });
  check(m.canworks.status === "done", "and stops");

  console.log("4. bridge restart");
  const rxErrors = () => rx.sent.filter((x) => x.canworks.status === "error").length;
  await stopBridge();
  check(await until(() => b.state === "reconnecting", 5000), "the nodes show reconnecting");
  startBridge();
  check(await until(() => b.connected && b.seeded && value("dio.state") === 5, 20000), "connected again without a redeploy");
  const before = rx.sent.length;
  check(await until(() => rx.sent.length > before + 3, 5000), "the receiver is open again and heartbeats come in");
  const errs = rxErrors();
  m = await job(send);
  check(m.canworks.status === "done", "the next can send after the restart runs (" + m.canworks.status + " " + m.canworks.errorId + ")");
  m = await job(sdoText);
  check(m.canworks.status === "done" && m.payload === longText, "and so does a long SDO read");
  await sleep(300);
  check(rxErrors() === errs, "no ERROR_ID 8 after the restart's first jobs");

  await rt.close();
  await stopBridge();
  console.log(fails.length ? fails.length + " FAILED" : "all passed");
  process.exit(fails.length ? 1 : 0);
}

main().catch(async (e) => {
  console.log("FAIL " + (e.stack || e));
  await stopBridge();
  process.exit(1);
});
