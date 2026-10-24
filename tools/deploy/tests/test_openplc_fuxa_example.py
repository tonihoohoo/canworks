"""The OpenPLC + FUXA example (examples/openplc-fuxa; openplc-fuxa-example,
canopen-ci "OpenPLC FUXA example ... check"): an OpenPLC Editor project on the
shared plant whose canworks-owned files are what Save writes, an OPC UA server
entry that publishes main's HMI variables, a FUXA project that reads and writes
only what that entry publishes and allows, and a compose file with the local
runtime's pinned runtime. No editor, runtime, FUXA, node or Docker."""

import contextlib
import io
import json
import os
import re
import unittest

from canworks import cli, editorproject, localruntime, openplcmodbus
from canworks.configurator import scan

from .test_contract import REPO

EXAMPLE = os.path.join(REPO, "examples", "openplc-fuxa")
PLANT = os.path.join(REPO, "examples", "modbus-bridge")
NAMED = os.path.join(REPO, "examples", "node-red-dashboard")
CONFIG = os.path.join(EXAMPLE, "canworks", "canworks.json")
# Tags a FUXA view writes: buttons, inputs and switches.
WRITERS = ("svg-ext-html_button", "svg-ext-html_input", "svg-ext-html_switch", "svg-ext-html_select",
           "svg-ext-html_slider")


def load(*parts):
    with open(os.path.join(EXAMPLE, *parts), encoding="utf-8") as f:
        return json.load(f) if parts[-1].endswith(".json") else f.read()


def located_free(cfg):
    """The networks without the locations, which packing for the PLC link moves."""
    nets = json.loads(json.dumps(cfg["networks"]))

    def strip(obj):
        if isinstance(obj, dict):
            return {k: strip(v) for k, v in obj.items() if not k.endswith("location")}
        if isinstance(obj, list):
            return [strip(v) for v in obj]
        return obj
    return strip(nets)


def main_variables():
    """{name: type} of main's VAR block."""
    text = load("pous", "programs", "main.st")
    block = re.search(r"\bVAR\b(.*?)\bEND_VAR\b", text, re.S).group(1)
    out = {}
    for m in re.finditer(r"^\s*(\w+)\s*:\s*(\w+)", block, re.M):
        out[m.group(1)] = m.group(2)
    return out


class OpenplcFuxaExampleConfigTest(unittest.TestCase):
    def test_plant_files_are_the_modbus_bridge_examples(self):
        for name in ("rtd8.eds", "dio16.eds", "simulation.json"):
            with open(os.path.join(PLANT, name), "rb") as a, open(os.path.join(EXAMPLE, "canworks", name), "rb") as b:
                self.assertEqual(a.read(), b.read(), "examples/openplc-fuxa/canworks/%s differs from "
                                 "examples/modbus-bridge/%s; the examples share one plant" % (name, name))

    def test_same_networks_and_names_as_the_dashboard_example(self):
        with open(os.path.join(NAMED, "canworks.json"), encoding="utf-8") as f:
            named = json.load(f)
        self.assertEqual(located_free(load("canworks", "canworks.json")), located_free(named))

    def test_config_passes_the_check(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            rc = cli.main(["--config", CONFIG, "--check"])
        self.assertEqual(rc, 0, out.getvalue())
        self.assertNotIn("warning: bridge", out.getvalue())

    def test_openplc_connection_with_the_plc_link(self):
        bridge = load("canworks", "canworks.json")["bridge"]
        self.assertEqual([c["kind"] for c in bridge["connections"]], ["openplc"])
        self.assertTrue(bridge["plc_link"])
        self.assertEqual(bridge["listen"], "127.0.0.1:1502")
        self.assertEqual(bridge["word_order"], "low_first")
        self.assertNotIn("mailboxes", bridge)

    def test_generated_editor_files_are_what_save_writes(self):
        cfg = load("canworks", "canworks.json")
        uses, _ = scan.scan(EXAMPLE)
        decls = editorproject.declarations(cfg, CONFIG)
        self.assertEqual(openplcmodbus.outdated_files(EXAMPLE, cfg, decls, uses), [],
                         "regenerate them: canworks-deploy --config examples/openplc-fuxa/canworks/canworks.json "
                         "--into-project examples/openplc-fuxa --force")
        self.assertEqual(openplcmodbus.changed_files(EXAMPLE, cfg, openplcmodbus.own_texts(cfg, decls, uses)[1]), [])


class OpenplcFuxaExampleHmiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        server = load("devices", "servers", "opcua.json")
        cls.opcua = server["opcuaServerConfig"]
        cls.nodes = {n["nodeId"]: n for n in cls.opcua["addressSpace"]["nodes"]}
        cls.fuxa = load("fuxa", "project.json")
        cls.device = [d for d in cls.fuxa["devices"].values() if d["type"] == "OPCUA"][0]

    def test_server_is_on_with_anonymous_operator_only(self):
        s = self.opcua["server"]
        self.assertTrue(s["enabled"])
        self.assertEqual((s["port"], s["endpointPath"]), (4840, "/openplc/opcua"))
        self.assertEqual([(p["securityPolicy"], p["authMethods"], p.get("anonymousRole")) for p in
                          self.opcua["securityProfiles"] if p["enabled"]], [("None", ["Anonymous"], "operator")])
        self.assertEqual(self.opcua["users"], [])

    def test_main_nodes_name_main_variables(self):
        variables = main_variables()
        for n in self.nodes.values():
            if n["pouName"] == "main":
                self.assertIn(n["variablePath"], variables, n["nodeId"])
                self.assertEqual(n["variableType"], variables[n["variablePath"]], n["nodeId"])

    def test_canworks_nodes_name_list_members(self):
        cfg = load("canworks", "canworks.json")
        members = {v["name"]: v["type"]["value"] for v in
                   openplcmodbus.global_list(editorproject.declarations(cfg, CONFIG))["variables"]}
        for n in self.nodes.values():
            if n["pouName"] == "GVL":
                list_name, _, member = n["variablePath"].partition(".")
                self.assertEqual(list_name, "canworks", n["nodeId"])
                self.assertEqual(members.get(member), n["variableType"], n["nodeId"])

    def test_only_commands_are_writable(self):
        writable = {n["variablePath"] for n in self.nodes.values() if "w" in n["permissions"]["operator"]}
        self.assertEqual(writable, {"limit", "ack", "run", "manual_out0", "manual_out1"})
        for n in self.nodes.values():
            self.assertEqual(n["permissions"]["viewer"], "r", n["nodeId"])

    def test_fuxa_device_is_the_plc_endpoint(self):
        self.assertEqual(self.device["property"]["address"], "opc.tcp://bridge:4840/openplc/opcua")

    def test_fuxa_tags_are_published_nodes(self):
        for tag_id, tag in self.device["tags"].items():
            self.assertEqual(tag_id, tag["name"], "tag ids are their names (shared views)")
            m = re.fullmatch(r"ns=2;s=(.+)", tag["address"])
            self.assertTrue(m, tag["address"])
            self.assertIn(m.group(1), self.nodes, "FUXA tag %s reads %s, which the OPC UA server entry does not "
                          "publish" % (tag_id, m.group(1)))

    def test_fuxa_views_write_only_writable_nodes(self):
        tags = self.device["tags"]
        used = set()
        for view in self.fuxa["hmi"]["views"]:
            for item in view["items"].values():
                prop = item.get("property") or {}
                tag = prop.get("variableId")
                if not tag:
                    continue
                self.assertIn(tag, tags, "view %s item %s" % (view["name"], item["name"]))
                used.add(tag)
                if item["type"] in WRITERS:
                    node = self.nodes[tags[tag]["address"].split(";s=", 1)[1]]
                    self.assertIn("w", node["permissions"]["operator"], "view %s writes %s, which is read-only "
                                  "on the OPC UA server" % (view["name"], tag))
        for chart in self.fuxa.get("charts", []):
            for line in chart["lines"]:
                self.assertIn(line["id"], tags, chart["name"])
        self.assertEqual(sorted(set(tags) - used), [], "tags no view uses")


class OpenplcFuxaExampleComposeTest(unittest.TestCase):
    def test_runtime_is_the_local_runtimes_pin(self):
        images = re.findall(r"image:\s*(\S+)", load("docker-compose.yml"))
        runtime = [i for i in images if i.startswith(localruntime.RUNTIME_IMAGE_REPO + ":")]
        self.assertEqual(runtime, [localruntime.runtime_image()],
                         "the example's runtime image differs from canworks-local-runtime's pinned %s"
                         % localruntime.TESTED_RUNTIME)

    def test_ports_only_on_loopback(self):
        ports = re.findall(r'-\s*"([^"]+:\d+)"', load("docker-compose.yml"))
        self.assertEqual(sorted(ports), sorted("127.0.0.1:%d:%d" % (p, p) for p in (8443, 1881, 4840)))

    def test_compose_and_start_script_name_existing_files(self):
        compose = load("docker-compose.yml")
        for path in re.findall(r"/example/([\w./*-]+)", compose + load("fuxa", "start.sh")):
            if "*" in path:
                folder, pattern = os.path.split(path)
                regex = re.compile(pattern.replace(".", r"\.").replace("*", ".*") + "$")
                self.assertTrue([f for f in os.listdir(os.path.join(EXAMPLE, folder)) if regex.match(f)], path)
            else:
                self.assertTrue(os.path.exists(os.path.join(EXAMPLE, path)), path)


if __name__ == "__main__":
    unittest.main()
