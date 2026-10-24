"""The FUXA example (examples/fuxa-node-red; fuxa-nodered-example, canopen-ci
"FUXA Node-RED example check" and "FUXA tag ids checked"): the plant files
and the plant logic are the Node-RED dashboard example's, plant.json fits
the flow exported from the config under the name "plant", and every FUXA
tag the flow or the views use is a tag of the project's FUXA Server device.
Also the compose file and the start script name files that are there. No
FUXA, Node-RED, node or Docker."""

import json
import os
import re
import unittest

from canworks import nodered

from .test_contract import REPO
from .test_nodered_example import STATUS_TOPICS

EXAMPLE = os.path.join(REPO, "examples", "fuxa-node-red")
DASHBOARD = os.path.join(REPO, "examples", "node-red-dashboard")
FUXA_TAG_NODES = ("get-tag", "get-tag-change", "set-tag")


def load(name, folder=EXAMPLE):
    with open(os.path.join(folder, name), encoding="utf-8") as f:
        return json.load(f) if name.endswith(".json") else f.read()


def view_tag_ids(view):
    """(item name, tag id) of every tag a view's items show or write."""
    for item in view["items"].values():
        prop = item.get("property") or {}
        if prop.get("variableId"):
            yield item["name"], prop["variableId"]
        for ev in prop.get("events") or []:
            var = (ev.get("actoptions") or {}).get("variable") or {}
            if var.get("variableId"):
                yield item["name"], var["variableId"]


class FuxaNodeRedExampleTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg = load("canworks.json")
        cls.flow_tab = load("plant.json")
        cls.project = load("fuxa/project.json")
        cls.export, _, cls.layout = nodered.flow(cls.cfg, "plant")
        cls.inputs = {r["n"] for r in cls.layout["inputs"]}
        cls.outputs = {r["n"] for r in cls.layout["outputs"]}
        cls.tags = cls.project["devices"]["0"]["tags"]

    def test_plant_files_are_the_dashboard_examples(self):
        for name in ("canworks.json", "rtd8.eds", "dio16.eds", "simulation.json"):
            with open(os.path.join(DASHBOARD, name), "rb") as a, open(os.path.join(EXAMPLE, name), "rb") as b:
                self.assertEqual(a.read(), b.read(), "examples/fuxa-node-red/%s differs from "
                                 "examples/node-red-dashboard/%s; the examples share one plant" % (name, name))

    def test_plant_logic_is_the_dashboard_examples(self):
        mine = [n for n in self.flow_tab if n["type"] == "function" and n.get("name") == "plant logic"]
        theirs = [n for n in load("dashboard.json", DASHBOARD) if n["type"] == "function" and n.get("name") == "plant logic"]
        self.assertEqual(len(mine), 1)
        self.assertEqual(mine[0]["func"], theirs[0]["func"], "the plant logic in examples/fuxa-node-red/plant.json "
                         "differs from examples/node-red-dashboard/dashboard.json; change both")
        self.assertEqual(mine[0]["outputs"], theirs[0]["outputs"])

    def test_uses_the_exported_bridge_node(self):
        bridge = [n for n in self.export if n["type"] == "canworks-bridge"][0]
        users = [n for n in self.flow_tab if n["type"].startswith("canworks-")]
        self.assertTrue(users)
        for n in users:
            self.assertEqual(n.get("bridge"), bridge["id"], "%s (%s) does not use the bridge node \"%s\" of the "
                             "export named plant" % (n["id"], n["type"], bridge["name"]))
        self.assertFalse({n["id"] for n in self.export} & {n["id"] for n in self.flow_tab},
                         "plant.json reuses ids of the export")

    def test_topics_exist(self):
        known = self.inputs | STATUS_TOPICS
        for n in self.flow_tab:
            if n["type"] == "canworks-in":
                for t in n["filter"].split(","):
                    self.assertIn(t.strip(), known, "%s filters on %r, which the export does not have" % (n["id"], t))
            if n["type"] == "canworks-out" and n.get("topic"):
                self.assertIn(n["topic"], self.outputs)

    def test_wires_point_at_nodes(self):
        ids = {n["id"] for n in self.flow_tab}
        for n in self.flow_tab:
            for port in n.get("wires", []):
                for target in port:
                    self.assertIn(target, ids, "%s is wired to a missing node %s" % (n["id"], target))

    def test_server_tags(self):
        server = self.project["devices"]["0"]
        self.assertEqual(server["type"], "FuxaServer")
        self.assertEqual(self.project["server"], server)
        self.assertEqual([k for k, v in self.project["devices"].items() if v["type"] != "FuxaServer"], [],
                         "the FUXA project has a device of its own; Node-RED is the bridge's only client")
        for tid, tag in self.tags.items():
            self.assertEqual(tid, tag["id"])
            self.assertEqual(tag["id"], tag["name"], "FUXA tag ids equal their names")
        self.assertLessEqual(server["polling"], 200)

    def test_flow_tags_exist(self):
        used = []
        for n in self.flow_tab:
            if n["type"] in FUXA_TAG_NODES:
                self.assertEqual(n["tag"], n["tagId"], n["id"])
                used.append((n["id"], n["tagId"]))
        to_fuxa = [n for n in self.flow_tab if n.get("name") == "to FUXA tags"][0]
        block = re.search(r"const values = \{(.*?)\};", to_fuxa["func"], re.S).group(1)
        used += [(to_fuxa["id"], t) for t in re.findall(r"(\w+):", block)]
        self.assertGreater(len(used), 15)
        for node, tid in used:
            self.assertIn(tid, self.tags, "%s uses the FUXA tag %r, which the project does not have" % (node, tid))

    def test_view_tags_exist(self):
        views = self.project["hmi"]["views"]
        self.assertEqual(sorted(v["name"] for v in views), ["I/O", "Plant"])
        view_ids = {v["id"] for v in views}
        for v in views:
            for item, tid in view_tag_ids(v):
                self.assertIn(tid, self.tags, "view %s: %s uses the tag %r, which the project does not have"
                              % (v["name"], item, tid))
            for item in v["items"].values():
                for ev in (item.get("property") or {}).get("events") or []:
                    if ev["action"] == "onpage":
                        self.assertIn(ev["actparam"], view_ids)
                self.assertIn('id="%s"' % item["id"], v["svgcontent"], "view %s: item %s is not drawn" % (v["name"], item["id"]))
        for chart in self.project["charts"]:
            for line in chart["lines"]:
                self.assertIn(line["id"], self.tags, "chart %s: line %r" % (chart["name"], line["id"]))
        self.assertIn(self.project["hmi"]["layout"]["start"], view_ids)

    def test_compose_and_start_script(self):
        compose = load("docker-compose.yml")
        start = load("start.sh")
        for name in ("canworks.json", "simulation.json", "start.sh", "plant_node-red.json", "plant.json", "fuxa/project.json"):
            self.assertIn(name, compose + start)
        self.assertIn("network_mode: service:bridge", compose)
        self.assertIn("frangoteam/fuxa:1.3.5", compose)
        self.assertIn('"127.0.0.1:1881:1881"', compose)
        self.assertIn("ghcr.io/tonihoohoo/canworks-bridge:${CANWORKS_VERSION:-latest}", compose)
        self.assertIn("npm install --offline", start)
        for name in re.findall(r"/example/([\w./*-]+)", compose + start):
            if "*" not in name:
                self.assertTrue(os.path.exists(os.path.join(EXAMPLE, name)), name)
        for name in re.findall(r'\$EXAMPLE/([\w./-]+)', start):
            self.assertTrue(os.path.exists(os.path.join(EXAMPLE, name)), name)


if __name__ == "__main__":
    unittest.main()
