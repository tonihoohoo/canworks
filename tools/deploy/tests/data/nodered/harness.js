// Runs the function nodes of a generated Node-RED flow outside Node-RED
// (tests/test_nodered.py). argv[2]: the flow JSON. stdin: JSON list of steps
// {node: <function node name>, msg: {...}, now?: ms}. Prints one JSON line:
// the outputs of each step (per output, the list of messages), the
// warnings and the last status per node, and the flow context.
"use strict";
const fs = require("fs");
const nodes = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const steps = JSON.parse(fs.readFileSync(0, "utf8"));
const store = {};
const flow = {
  get: (k) => (store[k] === undefined ? undefined : JSON.parse(JSON.stringify(store[k]))),
  set: (k, v) => { store[k] = v === undefined ? undefined : JSON.parse(JSON.stringify(v)); },
};
const warnings = [], status = {};
let clock = 1000000;
const realNow = Date.now;
Date.now = () => clock;
function stub(name) {
  return { warn: (t) => warnings.push(name + ": " + t), status: (s) => { status[name] = s; }, error: (t) => warnings.push(name + ": " + t) };
}
const funcs = {};
for (const n of nodes) {
  if (n.type !== "function") continue;
  funcs[n.name] = { run: new Function("msg", "node", "flow", n.func), init: n.initialize, outputs: n.outputs };
  if (n.initialize) new Function("node", "flow", n.initialize)(stub(n.name), flow);
}
function norm(ret, outputs) {
  if (ret === null || ret === undefined) return Array.from({ length: outputs }, () => []);
  if (!Array.isArray(ret)) ret = [ret];
  const out = [];
  for (let i = 0; i < outputs; i++) {
    const r = ret[i];
    out.push(r === null || r === undefined ? [] : Array.isArray(r) ? r : [r]);
  }
  return out;
}
const results = [];
for (const s of steps) {
  if (s.now !== undefined) clock = s.now;
  const f = funcs[s.node];
  if (!f) throw new Error("no function node " + s.node);
  results.push(norm(f.run(JSON.parse(JSON.stringify(s.msg)), stub(s.node), flow), f.outputs));
}
Date.now = realNow;
process.stdout.write(JSON.stringify({ results, warnings, status, flow: store }, (k, v) => (typeof v === "bigint" ? v.toString() + "n" : v)) + "\n");
