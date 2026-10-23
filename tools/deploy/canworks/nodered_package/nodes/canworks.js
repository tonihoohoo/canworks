// canworks.js - the Node-RED nodes of node-red-canworks (nodered-blocks):
// the "canworks bridge" config node with its one Modbus TCP connection, the
// value nodes canworks in and out, and one node per block family.
"use strict";

const { Bridge, CwError } = require("../lib/bridge");
const jobs = require("../lib/jobs");
const T = require("../lib/texts");
const L = require("../lib/layout");

// The ERROR_IDs after which a receiver opens again (the ST blocks' RETRY).
const RETRY = { can: [1, 8, 20], j1939: [1, 8, 9, 20], emcy: [4, 8, 20] };

function plainObject(v) {
  return typeof v === "object" && v !== null && !Array.isArray(v) && !Buffer.isBuffer(v);
}

function truthy(v) {
  return v === true || v === "true" || v === 1 || v === "1";
}

module.exports = function (RED) {
  // ---- the config node ----

  function BridgeNode(config) {
    RED.nodes.createNode(this, config);
    const node = this;
    node.users = new Set();
    node.problem = null;
    node.bridge = null;
    let layout = null;
    try {
      layout = config.layout ? JSON.parse(config.layout) : null;
    } catch (e) {
      layout = null;
    }
    try {
      node.bridge = new Bridge({
        host: config.host || "127.0.0.1",
        port: Number(config.port) || 502,
        unit: config.unit === undefined || config.unit === "" ? undefined : Number(config.unit),
        pollMs: Number(config.period) || 10,
        readOnly: truthy(config.readOnly),
        layout,
      });
    } catch (e) {
      node.problem = e.message;
      node.error(e.message);
    }
    if (node.bridge) {
      node.bridge.on("state", (s) => {
        for (const u of node.users) u.cwBridgeState(s);
      });
      node.bridge.on("error", () => {});
    }

    node.use = function (user) {
      node.users.add(user);
      if (node.bridge) {
        user.cwBridgeState(node.bridge.status || { fill: "yellow", shape: "ring", text: "connecting" });
        node.bridge.start();
      }
    };
    node.release = function (user) {
      node.users.delete(user);
    };
    node.on("close", (done) => {
      if (node.bridge) node.bridge.stop();
      done();
    });
  }
  RED.nodes.registerType("canworks-bridge", BridgeNode);

  // Joins `node` to its config node; returns the Bridge or null (status says why).
  function attach(node, config) {
    const cfg = RED.nodes.getNode(config.bridge);
    node.cwOwn = null; // the node's own status (a job's end), shown while the bridge runs
    node.cwBridge = null;
    node.cwBridgeState = (s) => {
      node.cwBridge = s;
      if (s && s.fill === "green" && node.cwOwn) node.status(node.cwOwn);
      else node.status(s || {});
    };
    node.cwShow = (s) => {
      node.cwOwn = s;
      if (!node.cwBridge || node.cwBridge.fill === "green") node.status(s);
    };
    if (!cfg) {
      node.status({ fill: "red", shape: "ring", text: "choose a canworks bridge" });
      return null;
    }
    if (!cfg.bridge) {
      node.status({ fill: "red", shape: "ring", text: cfg.problem || "the canworks bridge did not start" });
      node.cwProblem = cfg.problem;
      return null;
    }
    cfg.use(node);
    node.on("close", () => cfg.release(node));
    return cfg.bridge;
  }

  // ---- values ----

  function matcher(filter) {
    const parts = String(filter || "").split(/[\s,]+/).filter(Boolean);
    if (!parts.length) return () => true;
    return (topic) => parts.some((p) => (p.endsWith("*") ? topic.startsWith(p.slice(0, -1)) : topic === p));
  }

  function InNode(config) {
    RED.nodes.createNode(this, config);
    const node = this;
    const b = attach(node, config);
    if (!b) return;
    const want = matcher(config.filter);
    const onValue = (msg) => {
      if (want(msg.topic)) node.send(Object.assign({}, msg));
    };
    // Every value once: what the bridge already read, then the changes.
    for (const msg of b.values.values()) onValue(msg);
    b.on("value", onValue);
    node.on("close", () => b.removeListener("value", onValue));
  }
  RED.nodes.registerType("canworks-in", InNode);

  function OutNode(config) {
    RED.nodes.createNode(this, config);
    const node = this;
    const b = attach(node, config);
    let warnedReadOnly = false;
    node.on("input", (msg, send, done) => {
      if (!b) {
        done();
        return;
      }
      const topic = config.topic || msg.topic;
      const err = b.set(topic, msg.payload);
      if (err && b.readOnly) {
        if (!warnedReadOnly) node.warn(err);
        warnedReadOnly = true;
        node.cwShow({ fill: "grey", shape: "ring", text: "read-only" });
      } else if (err) {
        node.warn(err);
        node.cwShow({ fill: "red", shape: "dot", text: err });
      } else node.cwShow({ fill: "green", shape: "dot", text: topic + " = " + String(msg.payload) });
      done();
    });
  }
  RED.nodes.registerType("canworks-out", OutNode);

  // ---- jobs ----

  // Form fields whose names Node-RED keeps for itself (a node's id, type
  // and name) are can_id, datatype and ecu_name; msg.payload may use either.
  const RENAMED = { can_id: "id", datatype: "type", ecu_name: "name" };

  // The node's settings: form fields, then msg.payload's fields of the same
  // name; a payload that is not an object sets the node's `primary` field.
  function settings(config, fields, primary, msg) {
    const p = {};
    for (const f of fields) if (config[f] !== undefined && config[f] !== "") p[RENAMED[f] || f] = config[f];
    const pl = msg.payload;
    if (plainObject(pl)) {
      for (const f of fields) {
        const key = RENAMED[f] || f;
        if (pl[f] !== undefined) p[key] = pl[f];
        else if (key !== f && pl[key] !== undefined) p[key] = pl[key];
      }
    } else if (primary && primary.accepts(pl, p)) p[primary.field] = pl;
    return p;
  }

  function outcome(msg, family, p, res, err) {
    if (err) {
      const e = jobs.inFamily(family, err);
      msg.payload = null;
      msg.canworks = {
        status: "error", errorId: e.errorId, abortCode: e.abortCode || 0,
        abortText: e.abortCode ? T.abortText(e.abortCode) : "", text: e.message, request: p,
      };
      return e;
    }
    msg.payload = res.payload;
    msg.canworks = Object.assign({ status: "done", errorId: 0, abortCode: 0, abortText: "", request: p }, res.extra || {});
    return null;
  }

  function errorStatus(e) {
    return { fill: "red", shape: "dot", text: "ERROR_ID " + e.errorId + ": " + e.message };
  }

  // A node that runs one job per message: `run(bridge, settings, node)`
  // resolves {payload, extra}.
  function jobNode(type, family, fields, primary, run) {
    function JobNode(config) {
      RED.nodes.createNode(this, config);
      const node = this;
      const b = attach(node, config);
      let busy = 0;
      node.on("input", (msg, send, done) => {
        let p = {};
        busy++;
        node.cwShow({ fill: "blue", shape: "dot", text: busy > 1 ? "busy (" + busy + ")" : "busy" });
        Promise.resolve()
          .then(() => {
            p = settings(config, fields, primary, msg);
            if (!b) throw new CwError(22, node.cwProblem || "choose a canworks bridge");
            return run(b, p, node);
          })
          .then(
            (res) => {
              outcome(msg, family, p, res, null);
              busy--;
              node.cwShow({ fill: "green", shape: "dot", text: "done" });
            },
            (err) => {
              const e = outcome(msg, family, p, null, err);
              busy--;
              node.cwShow(errorStatus(e));
            },
          )
          .then(() => {
            send(msg);
            done();
          });
      });
    }
    RED.nodes.registerType(type, JobNode);
  }

  const isData = { accepts: (v) => typeof v === "string" || Array.isArray(v) || Buffer.isBuffer(v) };
  // A bare payload is the value of a write only: an inject's timestamp must not become one.
  const isValue = { accepts: (v, p) => p.action === "write" && v !== undefined && v !== null && !plainObject(v) };

  jobNode("canworks-nmt", "sdo", ["network", "node", "command", "timeout"],
    { field: "command", accepts: (v) => typeof v === "string" }, (b, p) => jobs.nmt(b, p));
  jobNode("canworks-sdo", "sdo", ["network", "node", "index", "subindex", "action", "datatype", "size", "value", "timeout"],
    Object.assign({ field: "value" }, isValue), (b, p) => jobs.sdo(b, p));
  jobNode("canworks-can-send", "can", ["network", "can_id", "extended", "rtr", "dlc", "data", "timeout"],
    Object.assign({ field: "data" }, isData), (b, p) => jobs.canSend(b, p));
  jobNode("canworks-j1939-send", "j1939", ["network", "pgn", "destination", "priority", "data", "timeout"],
    Object.assign({ field: "data" }, isData), (b, p) => jobs.j1939Send(b, p));
  jobNode("canworks-j1939-request", "j1939", ["network", "pgn", "destination", "timeout"], null,
    (b, p) => jobs.j1939Request(b, p));
  jobNode("canworks-j1939-dm", "j1939", ["network", "action", "address", "previous", "timeout"], null,
    (b, p) => jobs.dm(b, p));
  jobNode("canworks-find-ecu", "j1939", ["network", "ecu_name", "mask"], null, (b, p) => jobs.findEcu(b, p));

  // ---- cyclic frames ----

  function CyclicNode(config) {
    RED.nodes.createNode(this, config);
    const node = this;
    const b = attach(node, config);
    const fields = ["network", "can_id", "extended", "dlc", "data", "period", "action"];
    let job = null;
    let want = null; // the frame that should run
    let retry = null;

    const report = (msg, p, res, err) => {
      const e = outcome(msg, "can", p, res, err);
      node.cwShow(e ? errorStatus(e) : want ? { fill: "green", shape: "dot", text: "sending every " + want.period + " ms" }
        : { fill: "grey", shape: "ring", text: "stopped" });
      return msg;
    };
    const setUp = () => {
      const f = want;
      if (!f || !b || !b.connected) return;
      job.set(f).then(
        () => node.cwShow({ fill: "green", shape: "dot", text: "sending every " + f.period + " ms" }),
        (e) => node.send(report({ topic: config.name || "can cyclic" }, f, null, e)),
      );
    };
    if (b) {
      job = b.cyclic({
        ended: (id) => {
          // The bridge stopped the job: say so once, then set it up again.
          if (!want) return;
          node.send(report({ topic: config.name || "can cyclic" }, want, null, new CwError(id)));
          if (id === 8) {
            clearTimeout(retry);
            retry = setTimeout(setUp, 1000);
          }
        },
      });
      b.on("up", setUp);
      node.on("close", () => {
        clearTimeout(retry);
        b.removeListener("up", setUp);
        want = null;
        job.close();
      });
    }
    node.on("input", (msg, send, done) => {
      let p = {};
      Promise.resolve()
        .then(() => {
          p = settings(config, fields, Object.assign({ field: "data" }, isData), msg);
          if (!b) throw new CwError(22, node.cwProblem || "choose a canworks bridge");
          if (p.action === "stop") {
            want = null;
            return job.stop().then(() => ({ payload: true }));
          }
          b._guard("mailbox");
          const f = jobs.cyclicFrame(b, p);
          return job.set(f).then(() => {
            want = f;
            return { payload: true };
          });
        })
        .then((res) => report(msg, p, res, null), (err) => report(msg, p, null, err))
        .then((m) => {
          send(m);
          done();
        });
    });
  }
  RED.nodes.registerType("canworks-can-cyclic", CyclicNode);

  // ---- receivers ----

  // A node that holds one receiver while it is deployed; `spec(b, config)`
  // gives the receiver's filter, `body(rec)` a record's payload.
  function receiverNode(type, family, kind, spec, body) {
    function RxNode(config) {
      RED.nodes.createNode(this, config);
      const node = this;
      const b = attach(node, config);
      const topic = config.name || type.replace("canworks-", "");
      const say = (payload, canworks) => node.send({ topic, payload, canworks });
      if (!b) return;
      let s;
      try {
        s = Object.assign(spec(b, config), { kind, retry: RETRY[kind] });
      } catch (e) {
        const x = jobs.inFamily(family, e);
        node.cwShow(errorStatus(x));
        return;
      }
      let count = 0;
      const rx = b.receiver(s, {
        active: (on) => node.cwShow(on ? { fill: "green", shape: "dot", text: "receiving" + (count ? " (" + count + ")" : "") }
          : { fill: "yellow", shape: "ring", text: "opening" }),
        record: (rec) => {
          count++;
          say(body(rec), { status: "done", errorId: 0, queued: rec.queued, dropped: rec.dropped, overflow: rec.overflow });
          node.cwShow({ fill: "green", shape: "dot", text: "receiving (" + count + ")" });
        },
        error: (id, e) => {
          const x = jobs.inFamily(family, e instanceof CwError ? e : new CwError(id));
          say(null, { status: "error", errorId: x.errorId, abortCode: 0, abortText: "", text: x.message });
          node.cwShow(errorStatus(x));
        },
      });
      node.on("close", () => rx.close());
    }
    RED.nodes.registerType(type, RxNode);
  }

  const time = (rec) => rec.time;

  receiverNode("canworks-can-receive", "can", "can", (b, c) => {
    const extended = truthy(c.extended);
    const id = jobs.int(c.can_id, "can_id", 0, extended ? 0x1fffffff : 0x7ff, "can", 0);
    let mask = jobs.int(c.mask, "mask", 0, 0x1fffffff, "can", 0);
    if (truthy(c.all_ids)) mask = 0;
    else if (!mask) mask = extended ? 0x1fffffff : 0x7ff;
    return {
      net: jobs.inFamilyNet(b, c.network, "can", "can"), flags: extended ? L.rxOpenFlags.can_extended : 0,
      depth: jobs.int(c.depth, "depth", 0, 255, "can", 0), id, mask,
    };
  }, (rec) => ({ id: rec.id, extended: rec.extended, rtr: rec.rtr, dlc: rec.dlc, data: rec.data, time: time(rec) }));

  receiverNode("canworks-j1939-receive", "j1939", "j1939", (b, c) => {
    const filter = c.source !== undefined && c.source !== "" && c.source !== null;
    return {
      net: jobs.inFamilyNet(b, c.network, "j1939", "j1939"),
      flags: (truthy(c.all_pgns) ? L.rxOpenFlags.j1939_all_pgns : 0) | (truthy(c.all_destinations) ? L.rxOpenFlags.j1939_all_destinations : 0),
      depth: jobs.int(c.depth, "depth", 0, 255, "j1939", 0),
      id: truthy(c.all_pgns) ? 0 : jobs.int(c.pgn, "pgn", 0, 0x3ffff, "j1939"),
      mask: filter ? jobs.int(c.source, "source", 0, 254, "j1939") : 255,
    };
  }, (rec) => ({ pgn: rec.pgn, source: rec.source, destination: rec.destination, priority: rec.priority, data: rec.data, time: time(rec) }));

  receiverNode("canworks-emcy", "sdo", "emcy", (b, c) => ({
    net: jobs.inFamilyNet(b, c.network, "canopen", "sdo"), flags: truthy(c.skip_old) ? L.rxOpenFlags.emcy_skip_old : 0,
    depth: 0, id: 0, mask: jobs.int(c.node, "node", 0, 127, "sdo", 0),
  }), (rec) => ({ node: rec.node, code: rec.code, register: rec.register, data: rec.data, time: time(rec) }));
};
