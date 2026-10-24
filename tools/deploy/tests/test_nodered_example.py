"""The Node-RED dashboard example (examples/node-red-dashboard;
nodered-dashboard-example, canopen-ci "Node-RED dashboard example check"):
the plant files are the Modbus bridge example's, the config passes the
check, and dashboard.json fits the flow exported from the config under the
name "plant": its canworks nodes use that flow's bridge node, it reads only
names the flow has and writes only outputs. Also the compose file and the
start script name files that are there. No Node-RED, node or Docker."""

import contextlib
import io
import json
import os
import re
import unittest

from canworks import cli, nodered

from .test_contract import REPO

EXAMPLE = os.path.join(REPO, "examples", "node-red-dashboard")
PLANT = os.path.join(REPO, "examples", "modbus-bridge")
STATUS_TOPICS = {"bridge.state", "bridge.clients", "bridge.command", "bridge.bus_ok"}


def load(name):
    with open(os.path.join(EXAMPLE, name), encoding="utf-8") as f:
        return json.load(f) if name.endswith(".json") else f.read()


def topics_in(text):
    """The topics a function node's code reads (t === "x") and writes ({ topic: "x")."""
    reads = set(re.findall(r'\bt === "([^"]+)"', text))
    writes = set(re.findall(r'\{ topic: "([^"]+)"', text))
    return reads, writes


class DashboardExampleTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg = load("canworks.json")
        cls.dashboard = load("dashboard.json")
        cls.flow, _, cls.layout = nodered.flow(cls.cfg, "plant")
        cls.inputs = {r["n"] for r in cls.layout["inputs"]}
        cls.outputs = {r["n"] for r in cls.layout["outputs"]}

    def test_plant_files_are_the_modbus_bridge_examples(self):
        for name in ("rtd8.eds", "dio16.eds", "simulation.json"):
            with open(os.path.join(PLANT, name), "rb") as a, open(os.path.join(EXAMPLE, name), "rb") as b:
                self.assertEqual(a.read(), b.read(), "examples/node-red-dashboard/%s differs from "
                                 "examples/modbus-bridge/%s; the examples share one plant" % (name, name))

    def test_same_networks_as_the_plant(self):
        with open(os.path.join(PLANT, "canworks.json"), encoding="utf-8") as f:
            plant = json.load(f)

        def unnamed(cfg):
            nets = json.loads(json.dumps(cfg["networks"]))
            for net in nets:
                for node in net["nodes"]:
                    for pdo in node.get("tx_pdos", []) + node.get("rx_pdos", []):
                        for e in pdo["entries"]:
                            e.pop("name", None)
            return nets
        self.assertEqual(unnamed(self.cfg), unnamed(plant))

    def test_config_passes_the_check(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            rc = cli.main(["--config", os.path.join(EXAMPLE, "canworks.json"), "--check"])
        self.assertEqual(rc, 0, out.getvalue())
        self.assertNotIn("warning: bridge", out.getvalue())

    def test_writers_and_listen_stay_local(self):
        self.assertEqual(self.cfg["bridge"]["listen"], "127.0.0.1:1502")
        self.assertEqual(self.cfg["bridge"]["writers"], ["127.0.0.1"])
        self.assertFalse(self.layout["readOnly"])

    def test_dashboard_uses_the_exported_bridge_node(self):
        bridge = [n for n in self.flow if n["type"] == "canworks-bridge"][0]
        users = [n for n in self.dashboard if n["type"].startswith("canworks-")]
        self.assertTrue(users)
        for n in users:
            self.assertEqual(n.get("bridge"), bridge["id"], "%s (%s) does not use the bridge node \"%s\" of the "
                             "export named plant" % (n["id"], n["type"], bridge["name"]))
        ids = {n["id"] for n in self.flow}
        self.assertFalse(ids & {n["id"] for n in self.dashboard}, "dashboard.json reuses ids of the export")

    def test_topics_exist(self):
        known = self.inputs | STATUS_TOPICS
        for n in self.dashboard:
            if n["type"] == "canworks-in":
                for t in n["filter"].split(","):
                    self.assertIn(t.strip(), known, "%s filters on %r, which the export does not have" % (n["id"], t))
            if n["type"] == "canworks-out" and n.get("topic"):
                self.assertIn(n["topic"], self.outputs)
        logic = [n for n in self.dashboard if n["type"] == "function" and n["name"] == "plant logic"][0]
        reads, writes = topics_in(logic["func"])
        canworks_reads = {t for t in reads if "." in t}
        self.assertEqual(canworks_reads - known, set(), "the plant logic reads names the export does not have")
        self.assertEqual({t for t in writes if "." in t} - self.outputs, set(),
                         "the plant logic writes names that are not outputs")
        self.assertTrue({"rtd.temp1", "dio.in1"} <= canworks_reads)
        self.assertEqual({t for t in writes if "." in t}, {"dio.out0", "dio.out1"})

    def test_wires_point_at_nodes(self):
        ids = {n["id"] for n in self.dashboard}
        for n in self.dashboard:
            for port in n.get("wires", []):
                for target in port:
                    self.assertIn(target, ids, "%s is wired to a missing node %s" % (n["id"], target))
            for key in ("group", "page", "ui", "theme"):
                if n.get(key) and n["type"].startswith("ui-"):
                    self.assertIn(n[key], ids, "%s names a missing %s %s" % (n["id"], key, n[key]))

    def test_compose_and_start_script(self):
        compose = load("docker-compose.yml")
        start = load("start.sh")
        for name in ("canworks.json", "simulation.json", "start.sh", "plant_node-red.json"):
            self.assertIn(name, compose + start)
        self.assertIn("network_mode: service:bridge", compose)
        self.assertIn("nodered/node-red:4.1", compose)
        self.assertIn("ghcr.io/tonihoohoo/canworks-bridge:${CANWORKS_VERSION:-latest}", compose)
        self.assertIn("dashboard.json", start)
        self.assertRegex(start, r"DASHBOARD_VERSION=\d+\.\d+\.\d+\n")
        for name in re.findall(r"/example/([\w.*-]+)", compose + start):
            if "*" not in name:
                self.assertTrue(os.path.exists(os.path.join(EXAMPLE, name)), name)


if __name__ == "__main__":
    unittest.main()
