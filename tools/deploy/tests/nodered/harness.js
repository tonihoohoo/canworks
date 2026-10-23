// harness.js - a stand-in for Node-RED's runtime for the package tests: it
// loads nodes/canworks.js, makes nodes from a flow's objects as Node-RED
// does (new constructor(config)), feeds them messages and closes them.
"use strict";

const path = require("path");

const PACKAGE = path.join(__dirname, "..", "..", "canworks", "nodered_package");

function makeRuntime() {
  const types = {};
  const nodes = new Map();
  const RED = {
    nodes: {
      createNode(node, config) {
        const handlers = {};
        node.id = config.id;
        node.type = config.type;
        node.name = config.name;
        node.sent = [];
        node.statuses = [];
        node.warnings = [];
        node.errors = [];
        node.waiters = [];
        node.on = (ev, fn) => {
          (handlers[ev] = handlers[ev] || []).push(fn);
          return node;
        };
        node.handlers = handlers;
        node.status = (s) => node.statuses.push(s);
        node.warn = (t) => node.warnings.push(String(t));
        node.error = (t) => node.errors.push(String(t));
        node.log = () => {};
        node.send = (msg) => {
          if (msg === null || msg === undefined) return;
          node.sent.push(msg);
          for (const w of node.waiters.splice(0)) w();
        };
      },
      registerType(type, ctor) {
        types[type] = ctor;
      },
      getNode(id) {
        return nodes.get(id) || null;
      },
    },
  };
  require(path.join(PACKAGE, "nodes", "canworks.js"))(RED);

  const rt = {
    types,
    nodes,
    // Makes the nodes of `flow` (config nodes first, as Node-RED starts them).
    load(flow) {
      const made = [];
      const order = flow.filter((n) => types[n.type] && !n.z).concat(flow.filter((n) => types[n.type] && n.z));
      for (const config of order) {
        const n = new types[config.type](config);
        nodes.set(config.id, n);
        made.push(n);
      }
      return made;
    },
    add(config) {
      const n = new types[config.type](config);
      nodes.set(config.id, n);
      return n;
    },
    // Sends msg to node; resolves when the node called done().
    input(node, msg) {
      return new Promise((resolve) => {
        for (const fn of node.handlers.input || []) fn(msg, (m) => node.send(m), () => resolve());
      });
    },
    // Resolves the node's next message (or the first not yet taken after `from`).
    next(node, timeoutMs, from) {
      const want = from === undefined ? node.sent.length : from;
      return rt.until(() => node.sent.length > want, timeoutMs || 5000, node.type + " sent nothing").then(() => node.sent[want]);
    },
    // Resolves once cond() holds (checked every 5 ms).
    until(cond, timeoutMs, what) {
      return new Promise((resolve, reject) => {
        const end = Date.now() + (timeoutMs || 5000);
        const tick = () => {
          let ok = false;
          try {
            ok = cond();
          } catch (e) {
            ok = false;
          }
          if (ok) resolve(true);
          else if (Date.now() > end) reject(new Error("timed out: " + (what || "condition")));
          else setTimeout(tick, 5);
        };
        tick();
      });
    },
    async close() {
      const all = [...nodes.values()].reverse();
      for (const n of all)
        for (const fn of n.handlers.close || [])
          await new Promise((resolve) => {
            if (fn.length >= 2) fn(false, resolve);
            else if (fn.length === 1) fn(resolve);
            else {
              fn();
              resolve();
            }
          });
      nodes.clear();
    },
  };
  return rt;
}

module.exports = { makeRuntime, PACKAGE };
