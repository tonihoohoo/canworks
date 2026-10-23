"""The configurator's Modbus bridge requests, over HTTP (spec
canopen-configurator, "Modbus bridge target", "Bridge settings panel",
"Register map preview and export"; modbus-connections): the register map,
Pack for Modbus, Suggest for the bridge blocks, the connections' Add and
Download against canworks-deploy's exports, the OpenPLC connection, the
per-type repack and the checks of a bridge config."""

import base64
import contextlib
import copy
import io
import json
import os
import re
import shutil
import tempfile
import threading
import unittest
import zipfile

from canworks import cli, connections, editorproject, mainmove, modbusmap, nodered, openplcmodbus, plclibrary, plcopen_targets
from canworks.configurator import server as srv

from .helpers import REPO, tmpdir
from .test_configurator_server import FIXTURE

EXAMPLE = os.path.join(REPO, "examples", "modbus-bridge")


def load(path=os.path.join(EXAMPLE, "canworks.json")):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def plugin_config():
    """The example as a config of the removed OpenPLC plugin: no bridge object."""
    cfg = load()
    del cfg["bridge"]
    return cfg


class Base(unittest.TestCase):
    """A server on a free port with the example open as a standalone folder."""

    def setUp(self):
        self.dir = tmpdir(self)
        os.environ["CANWORKS_CONFIG_DIR"] = os.path.join(self.dir, "cfg")
        self.addCleanup(os.environ.pop, "CANWORKS_CONFIG_DIR", None)
        self.server = srv.Server()
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.folder = os.path.join(self.dir, "pump-station")
        shutil.copytree(EXAMPLE, self.folder)
        self.cfg = load()

    def request(self, path, body, method="POST"):
        import http.client
        c = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=10)
        c.request(method, path, None if body is None else json.dumps(body), {"Host": "127.0.0.1:%d" % self.server.server_port,
                                                   srv.TOKEN_HEADER: self.server.token,
                                                   "Content-Type": "application/json"})
        r = c.getresponse()
        data = json.loads(r.read().decode() or "{}")
        c.close()
        return r.status, data

    def ok(self, path, body, method="POST"):
        status, data = self.request(path, body, method)
        self.assertEqual(status, 200, data)
        return data

    def open(self, path=None, mode="standalone"):
        return self.ok("/api/open", {"path": path or self.folder, "mode": mode})

    def project(self):
        """A copy of the editor fixture project with the example's EDS files."""
        project = os.path.join(self.dir, "rtd-monitor")
        shutil.copytree(FIXTURE, project)
        os.makedirs(os.path.join(project, "canworks"), exist_ok=True)
        for name in ("rtd8.eds", "dio16.eds"):
            shutil.copy(os.path.join(EXAMPLE, name), os.path.join(project, "canworks"))
        return project

    def errors(self, cfg):
        r = self.ok("/api/check", {"config": cfg})
        return [i["message"] for i in r["items"] if i["level"] == "error"]


class RegisterMap(Base):
    def test_map(self):
        self.open()
        r = self.ok("/api/bridge/map", {"config": self.cfg})
        rows = modbusmap.register_map(self.cfg)
        self.assertEqual(r["rows"], rows)
        self.assertEqual((r["input_bytes"], r["output_bytes"]), modbusmap.image_sizes(rows))
        self.assertEqual([(c["function"], c["start"], c["count"], c["direction"]) for c in r["channels"]],
                         modbusmap.suggest_channels(rows))
        self.assertNotIn("problem", r)
        live = [row for row in r["rows"] if row["name"] == "bridge.live_list.field"]
        self.assertEqual([(x["table"], x["address"], x["count"]) for x in live], [("input register", 16, 8)])

    def test_overlap_is_a_problem_not_an_error(self):
        self.open()
        self.cfg["bridge"]["status_location"] = "%IB4"
        r = self.ok("/api/bridge/map", {"config": self.cfg})
        self.assertEqual(r["rows"], [])
        self.assertIn("overlap in input bytes", r["problem"])

    def test_needs_a_bridge_config(self):
        self.open()
        del self.cfg["bridge"]
        for path in ("/api/bridge/map", "/api/bridge/pack", "/api/bridge/suggest", "/api/connections/add",
                     "/api/connections/download"):
            status, data = self.request(path, {"config": self.cfg, "block": "status_location", "index": 0,
                                               "connection": {"kind": "hmi"}})
            self.assertEqual(status, 400, path)
            self.assertIn("not a bridge config", data["error"])

    def test_needs_an_open_folder(self):
        status, _ = self.request("/api/bridge/map", {"config": self.cfg})
        self.assertEqual(status, 409)


class Pack(Base):
    def test_pack_for_modbus(self):
        self.open()
        cfg = copy.deepcopy(self.cfg)
        cfg["bridge"]["status_location"] = "%IB500"
        r = self.ok("/api/bridge/pack", {"config": cfg})
        self.assertEqual(r["config"], modbusmap.pack(cfg))
        self.assertNotEqual(r["config"]["bridge"]["status_location"], "%IB500")
        self.assertEqual(self.errors(r["config"]), [])

    def test_pack_refuses_a_bad_block(self):
        self.open()
        self.cfg["bridge"]["control_location"] = "%QW6"
        status, data = self.request("/api/bridge/pack", {"config": self.cfg})
        self.assertEqual(status, 400)
        self.assertIn("bridge.control: '%QW6' must be a byte location", data["error"])

class Suggest(Base):
    def test_live_list_after_the_data(self):
        self.open()
        self.cfg["bridge"]["live_lists"] = [{"network": "field"}]
        r = self.ok("/api/bridge/suggest", {"config": self.cfg, "block": "live_list", "index": 0})
        # Data and status end at input byte 24; the status block takes 24-31.
        self.assertEqual(r["location"], "%IB32")
        self.cfg["bridge"]["live_lists"][0]["location"] = r["location"]
        rows = self.ok("/api/bridge/map", {"config": self.cfg})["rows"]
        self.assertIn(("bridge.live_list.field", "input register", 16, 8),
                      [(x["name"], x["table"], x["address"], x["count"]) for x in rows])
        self.assertEqual(self.errors(self.cfg), [])

    def test_a_block_moves_out_of_the_way(self):
        self.open()
        # The response block sits right after the data and a live list just after it:
        # the status block goes after both, past the gap that is too small.
        del self.cfg["bridge"]["status_location"]
        self.cfg["bridge"]["sdo_bridge_location"]["response"] = "%IB24"
        self.cfg["bridge"]["live_lists"][0]["location"] = "%IB40"
        r = self.ok("/api/bridge/suggest", {"config": self.cfg, "block": "status_location"})
        self.assertEqual(r["location"], "%IB56")
        r = self.ok("/api/bridge/suggest", {"config": self.cfg, "block": "control_location"})
        self.assertEqual(r["location"], "%QB6")
        r = self.ok("/api/bridge/suggest", {"config": self.cfg, "block": "sdo_request"})
        self.assertEqual(r["location"], "%QB12")
        # A block's own location does not count: Suggest may move it.
        r = self.ok("/api/bridge/suggest", {"config": self.cfg, "block": "sdo_response"})
        self.assertEqual(r["location"], "%IB24")

    def test_bad_requests(self):
        self.open()
        for body in ({"block": "nope"}, {"block": "live_list", "index": 5}, {"block": "live_list"}):
            status, _ = self.request("/api/bridge/suggest", dict(body, config=self.cfg))
            self.assertEqual(status, 400, body)


class Connections(Base):
    """Add connection and each connection's Download (modbus-connections)."""

    def add(self, cfg, **conn):
        return self.ok("/api/connections/add", {"config": cfg, "connection": conn})["config"]

    def download(self, cfg, index):
        return self.ok("/api/connections/download", {"config": cfg, "index": index})

    def cli_file(self, cfg, *argv):
        """What canworks-deploy writes for cfg with argv (OUT stands for the file)."""
        tmp = tempfile.mkdtemp(dir=self.dir)
        for name in os.listdir(self.folder):
            if name.endswith(".eds"):
                shutil.copy(os.path.join(self.folder, name), tmp)
        src = os.path.join(tmp, "canworks.json")
        with open(src, "w", encoding="utf-8") as f:
            json.dump(cfg, f)
        out = os.path.join(tmp, "out")
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            argv = [out + a[3:] if a.startswith("OUT") else a for a in argv]
            self.assertEqual(cli.main(["--config", src] + argv), 0)
            out = next(a for a in argv if a.startswith(out))
        with open(out, "rb") as f:
            return f.read()

    def test_add_an_hmi(self):
        self.open()
        cfg = self.add(self.cfg, kind="hmi", name="Line HMI", address="192.168.10.20")
        [c] = cfg["bridge"]["connections"]
        self.assertEqual(c, {"kind": "hmi", "name": "Line HMI", "address": "192.168.10.20", "writes": False,
                             "format": "csv"})
        # Writers follow the connections: none of them writes.
        self.assertEqual(cfg["bridge"]["writers"], [])
        self.assertEqual(self.errors(cfg), [])
        # Names stay unique.
        again = self.add(cfg, kind="hmi", name="Line HMI", address="192.168.10.21")
        self.assertEqual(again["bridge"]["connections"][1]["name"], "Line HMI 2")

    def test_writers_follow_the_connections(self):
        self.open()
        cfg = self.add(self.cfg, kind="hmi", name="Panel", address="192.168.10.20", writes=True)
        cfg = self.add(cfg, kind="nodered", name="Flows", address="192.168.10.30", writes=True)
        self.assertEqual(cfg["bridge"]["writers"], ["192.168.10.20", "192.168.10.30"])
        cfg["bridge"]["writers"] = ["10.0.0.1"]
        items = self.ok("/api/check", {"config": cfg})["items"]
        self.assertIn(["bridge.writers"], [i["paths"] for i in items if "use the connections' addresses" in i["message"]])

    def test_same_files_as_the_deploy_tool(self):
        self.open()
        # An unsaved change goes into the download.
        self.cfg["bridge"]["word_order"] = "low_first"
        cfg = self.cfg
        for fmt, ctype in (("csv", "text/csv"), ("json", "application/json"), ("st", "text/plain")):
            cfg = self.add(cfg, kind="hmi", name="hmi " + fmt, address="192.168.10.20", format=fmt)
            r = self.download(cfg, len(cfg["bridge"]["connections"]) - 1)
            self.assertEqual((r["errors"], r["name"], r["content_type"]), (0, "pump-station-hmi-%s.%s" % (fmt, fmt), ctype))
            self.assertEqual(base64.b64decode(r["data"]), self.cli_file(cfg, "--export-modbus-map", "OUT." + fmt), fmt)
            self.assertEqual(r["map_hash"], "0x%08x" % modbusmap.map_hash(cfg))
        self.assertIn("word order low_first", base64.b64decode(r["data"]).decode())
        cfg = self.add(cfg, kind="nodered", name="Flows", address="192.168.10.30", bridge_host="192.168.10.5",
                       period_ms=200)
        r = self.download(cfg, len(cfg["bridge"]["connections"]) - 1)
        self.assertEqual(r["name"], "pump-station-Flows.json")
        # Without Writes the flow only reads.
        nodes, _, _ = nodered.flow(cfg, "pump-station-Flows", host="192.168.10.5", poll_ms=200, readonly=True)
        self.assertEqual(base64.b64decode(r["data"]).decode(), nodered.to_json(nodes))
        self.assertEqual(r["package"], nodered.package_name())

    def test_nodered_package(self):
        # Package on a Node-RED row: the .tgz canworks-deploy --export-nodered-package writes.
        self.open()
        r = self.ok("/api/nodered_package", {})
        self.assertEqual((r["name"], r["content_type"]), (nodered.package_name(), "application/gzip"))
        self.assertEqual(base64.b64decode(r["data"]), nodered.package_tgz())

    def test_plcopen_download(self):
        self.open()
        cfg = copy.deepcopy(self.cfg)
        cfg["bridge"]["plc_link"] = True
        cfg = self.ok("/api/bridge/pack", {"config": cfg})["config"]
        cfg = self.add(cfg, kind="plc", name="Line PLC", address="192.168.10.40", bridge_host="192.168.10.5")
        r = self.download(cfg, 0)
        self.assertEqual((r["errors"], r["name"], r["content_type"]), (0, "pump-station-Line-PLC.zip", "application/zip"))
        with zipfile.ZipFile(io.BytesIO(base64.b64decode(r["data"]))) as z:
            got = {n: z.read(n).decode() for n in z.namelist()}
        path = os.path.join(self.folder, "canworks.json")
        want = plcopen_targets.files(cfg, editorproject.declarations(cfg, path), "generic", host="192.168.10.5")
        # The XML's creation time differs between the two runs.
        strip = lambda s: re.sub(r'creationDateTime="[^"]*"', "", s)
        self.assertEqual({n: strip(v) for n, v in got.items()}, {n: strip(v) for n, v in want.items()})

    def test_problem_downloads_nothing(self):
        self.open()
        cfg = self.add(self.cfg, kind="hmi", name="Panel", address="192.168.10.20", format="st")
        cfg["networks"][0]["nodes"][0]["tx_pdos"][0]["entries"][0]["iec_location"] = "%IW1"
        r = self.download(cfg, 0)
        # The odd start, and the overlap with the next entry it causes.
        self.assertEqual(r["errors"], 2)
        self.assertNotIn("data", r)
        self.assertIn("must start at an even byte", r["items"][0]["message"])
        # The config check's item, so the Problems row opens the field.
        self.assertEqual(r["items"][0]["paths"], ["networks[0].nodes[0].tx_pdos[0].entries[0].iec_location"])
        # A PLCopen download without the PLC link says how to turn it on.
        cfg = self.add(self.cfg, kind="trust", name="truST", address="127.0.0.1")
        r = self.download(cfg, 0)
        self.assertIn("turn it on", r["items"][0]["message"])
        # truST refuses a watchdog under 500 ms, and the item opens the field.
        linked = copy.deepcopy(cfg)
        linked["bridge"].update(plc_link=True, listen="127.0.0.1:502", watchdog_ms=100)
        linked = self.ok("/api/bridge/pack", {"config": linked})["config"]
        r = self.download(linked, 0)
        self.assertIn((["bridge.watchdog_ms"], True),
                      [(i["paths"], '"watchdog_ms": 500 or more' in i["message"]) for i in r["items"]])
        self.assertNotIn("data", r)
        status, _ = self.request("/api/connections/download", {"config": cfg, "index": 5})
        self.assertEqual(status, 400)

    def test_out_of_date(self):
        self.open()
        cfg = self.add(self.cfg, kind="hmi", name="Panel", address="192.168.10.20")
        warn = lambda c: [i for i in self.ok("/api/check", {"config": c})["items"] if "Download again" in i["message"]]
        self.assertEqual(warn(cfg), [])  # not downloaded yet
        cfg["bridge"]["connections"][0]["map_hash"] = self.download(cfg, 0)["map_hash"]
        self.assertEqual(warn(cfg), [])
        cfg["networks"][0]["nodes"][0]["tx_pdos"][0]["entries"][0]["iec_location"] = "%IW100"
        [item] = warn(cfg)
        self.assertEqual(item["paths"], ["bridge.connections[0]"])
        self.assertIn("Panel", item["message"])

    def test_connections_reach_the_bridge(self):
        self.open()
        self.cfg["bridge"]["listen"] = "127.0.0.1:1502"
        cfg = self.add(self.cfg, kind="hmi", name="Panel", address="192.168.10.20")
        items = self.ok("/api/check", {"config": cfg})["items"]
        [err] = [i for i in items if "listen on all addresses" in i["message"]]
        self.assertEqual((err["level"], err["paths"]), ("error", ["bridge.listen", "bridge.connections[0].address"]))
        # A truST connection without the bridge's address
        cfg = self.add(self.cfg, kind="trust", name="truST", address="192.168.10.7")
        cfg["bridge"]["listen"] = "0.0.0.0:502"
        items = self.ok("/api/check", {"config": cfg})["items"]
        self.assertIn(["bridge.connections[0].bridge_host"],
                      [i["paths"] for i in items if "needs the bridge's address" in i["message"]])

    def test_only_the_plc_writes_with_a_plc_link(self):
        self.open()
        cfg = copy.deepcopy(self.cfg)
        cfg["bridge"]["plc_link"] = True
        cfg = self.ok("/api/bridge/pack", {"config": cfg})["config"]
        cfg = self.add(cfg, kind="nodered", name="Flows", address="192.168.10.30", writes=True)
        items = self.ok("/api/check", {"config": cfg})["items"]
        self.assertTrue(any("only the PLC writes outputs and mailboxes" in i["message"] for i in items), items)


class Target(Base):
    def test_one_unnamed_network_stays_version_2(self):
        self.open()
        cfg = self.cfg
        # Without a name of its own the network is named after its interface.
        del cfg["networks"][0]["name"]
        cfg["bridge"] = {"listen": "0.0.0.0:502", "writers": ["10.0.0.20"], "live_lists": [{"network": "sim0", "location": "%IB32"}]}
        r = self.ok("/api/save", {"config": cfg})
        self.assertEqual(r["check"]["errors"], 0, r["check"]["items"])
        saved = load(os.path.join(self.folder, "canworks.json"))
        self.assertEqual(saved["schema_version"], 2)
        self.assertEqual(list(saved), ["$schema", "schema_version", "networks", "bridge"])
        self.assertEqual(list(saved["bridge"]), ["listen", "writers", "live_lists"])

    def test_plc_cycle_is_a_problem(self):
        self.open()
        self.cfg["networks"][0]["master"]["sync_source"] = "plc_cycle"
        del self.cfg["networks"][0]["master"]["sync_period_us"]
        r = self.ok("/api/check", {"config": self.cfg})
        [item] = [i for i in r["items"] if "plc_cycle" in i["message"]]
        self.assertEqual((item["level"], item["paths"]), ("error", ["networks[0].master.sync_source"]))

    def test_project_addresses_do_not_apply(self):
        self.open(self.project(), "project")
        # The fixture project's devices use %IW200: nothing to the bridge.
        self.cfg["networks"][0]["nodes"][1]["emcy_code_location"] = "%IW200"
        self.assertEqual(self.errors(self.cfg), [])
        plain = copy.deepcopy(self.cfg)
        del plain["bridge"]
        self.assertTrue(any("removed OpenPLC plugin" in m for m in self.errors(plain)))


class OpenplcModbus(Base):
    """The OpenPLC connection (modbus-connections; canopen-configurator
    "OpenPLC remote device on save"): Use with canworks-bridge in an editor
    project, Add connection, Save writing the editor's files, the
    changed-file confirm and the facts."""

    def switched(self):
        """The plugin example as Use with canworks-bridge leaves it in an
        editor project, or with Add connection → OpenPLC standalone."""
        cfg = self.ok("/api/switch_target", {"config": plugin_config(), "target": "bridge"})["config"]
        if not cfg["bridge"].get("connections"):
            cfg = self.ok("/api/connections/add", {"config": cfg, "connection": {"kind": "openplc"}})["config"]
        return cfg

    def test_switch_from_the_plugin(self):
        self.open(self.project(), "project")
        cfg = self.switched()
        b = cfg["bridge"]
        self.assertEqual(b["connections"], [{"kind": "openplc", "name": "OpenPLC", "address": "127.0.0.1",
                                             "writes": True}])
        self.assertEqual((b["plc_link"], b["word_order"], b["listen"], b["writers"], b["watchdog_ms"]),
                         (True, "low_first", "127.0.0.1:1502", ["127.0.0.1"], 50))
        self.assertTrue(b["sdo_bridge_write"])
        self.assertEqual([l["network"] for l in b["live_lists"]], ["field"])
        self.assertEqual(self.errors(cfg), [])
        # packed after the PLC link header and the status block
        text = modbusmap.map_hash_text(cfg).splitlines()
        self.assertEqual(text[:3], ["I 0 4 -", "I 4 8 -", "I 12 2 -"])
        self.assertIn("Q 6 1 -", text)
        # Standalone, Use with canworks-bridge adds no connection.
        self.open()
        out = self.ok("/api/switch_target", {"config": plugin_config(), "target": "bridge"})["config"]
        self.assertNotIn("connections", out["bridge"])

    def test_add_to_a_new_bridge_config(self):
        self.open()
        new = self.ok("/api/switch_target", {"config": srv.empty_config(), "target": "bridge"})["config"]
        out = self.ok("/api/connections/add", {"config": new, "connection": {"kind": "openplc"}})["config"]
        b = out["bridge"]
        self.assertEqual((b["plc_link"], b["listen"], b["writers"], b["watchdog_ms"]),
                         (True, "127.0.0.1:1502", ["127.0.0.1"], 50))
        self.assertIn("mailboxes", b)
        status, data = self.request("/api/connections/add", {"config": out, "connection": {"kind": "openplc"}})
        self.assertEqual(status, 400)
        self.assertIn("already has an OpenPLC connection", data["error"])
        # High word first is refused with the connection.
        b["word_order"] = "high_first"
        self.assertTrue(any("lowest word first" in m for m in self.errors(out)))

    def test_place_skips_the_bridge_blocks(self):
        # The mailbox areas reach past byte 100: a new entry lands after them.
        self.open()
        cfg = self.switched()
        ends = {}
        for it in modbusmap.collect(cfg):
            if it.kind == "bridge":
                ends[it.loc.area] = max(ends.get(it.loc.area, 0), it.loc.index + it.nbytes)
        self.assertGreater(ends["I"], 100)
        for direction, area in (("input", "I"), ("output", "Q")):
            loc = self.ok("/api/place", {"config": cfg, "node": 0, "direction": direction,
                                         "type": "UNSIGNED16"})["location"]
            self.assertGreaterEqual(int(loc[3:]), max(100, ends[area]), loc)

    def test_save_writes_the_editor_files(self):
        project = self.project()
        self.open(project, "project")
        cfg = self.switched()
        r = self.ok("/api/save", {"config": cfg})
        self.assertEqual(r["errors"], 0, r["check"]["items"])
        self.assertEqual(r["editor"]["requests"], 7)  # 5 data groups + the mailboxes' input and output
        remote = os.path.join(project, "devices", "remote", "canworks.json")
        self.assertIn(remote, r["written"])
        with open(remote, encoding="utf-8") as f:
            dev = json.load(f)
        self.assertEqual(dev["modbusTcpConfig"]["port"], 1502)
        self.assertTrue(os.path.isfile(os.path.join(project, "pous", "programs", "canworks_out.st")))
        info = r["state"]["openplc"]
        self.assertEqual((info["remote_device"], info["poll_ms"], info["requests"]), ("canworks", 10, 7))
        self.assertEqual(info["map_hash"], "0x%08x" % modbusmap.map_hash(load(os.path.join(project, "canworks",
                                                                                            "canworks.json"))))
        # someone edits canworks_in.st: the next save asks first
        with open(os.path.join(project, "pous", "programs", "canworks_in.st"), "a", encoding="utf-8") as f:
            f.write("(* mine *)\n")
        cfg["bridge"]["connections"][0]["poll_ms"] = 20
        status, data = self.request("/api/save", {"config": cfg})
        self.assertEqual(status, 409)
        self.assertEqual(data["editor_changed"], ["pous/programs/canworks_in.st"])
        # nothing was written
        self.assertEqual(load(os.path.join(project, "canworks", "canworks.json"))["bridge"]["connections"][0].get("poll_ms"), None)
        self.ok("/api/save", {"config": cfg, "editor_overwrite": True})
        with open(remote, encoding="utf-8") as f:
            self.assertEqual({g["cycleTime"] for g in json.load(f)["modbusTcpConfig"]["ioGroups"]}, {20})

    def test_save_enables_the_library(self):
        project = self.project()
        self.open(project, "project")
        r = self.ok("/api/save", {"config": self.switched()})
        self.assertTrue(r["editor"]["library_ok"], r["editor"]["library"])
        with open(os.path.join(project, "project.json"), encoding="utf-8") as f:
            libs = json.load(f)["data"]["libraries"]
        self.assertEqual([l["name"] for l in libs].count("canworks"), 1)
        self.assertEqual(plclibrary.installed_version(), plclibrary.__version__)

    def test_unnamed_network_gets_a_live_list(self):
        self.open()
        cfg = self.ok("/api/switch_target", {"config": plugin_config(), "target": "bridge"})["config"]
        del cfg["networks"][0]["name"]
        cfg["networks"][0]["adapter"]["interface"] = "can1"
        cfg["bridge"].pop("live_lists", None)
        out = self.ok("/api/connections/add", {"config": cfg, "connection": {"kind": "openplc"}})["config"]
        self.assertEqual([l["network"] for l in out["bridge"]["live_lists"]], ["can1"])
        self.assertNotIn("name", out["networks"][0])
        self.assertEqual(self.errors(out), [])

    def test_main_with_plugin_locations(self):
        project = self.project()
        self.open(project, "project")
        cfg = self.switched()
        members = [d["name"] for d, _ in openplcmodbus._typed(
            editorproject.declarations(cfg, os.path.join(project, "canworks", "canworks.json")))]
        name = members[0]
        main = os.path.join(project, mainmove.MAIN)
        with open(main, "w", encoding="utf-8") as f:
            f.write("PROGRAM main\n  VAR\n    %s : INT AT %%IW100;\n    start_button : BOOL AT %%IX0.0;\n  END_VAR\n\n"
                    "(* %s from the plugin *)\nIF start_button THEN x := %s; END_IF;\n\nEND_PROGRAM\n" % (name, name, name))
        # The switch's answer, Problems and the Project page say so.
        self.assertEqual(self.ok("/api/switch_target", {"config": plugin_config(), "target": "bridge"})["old_main"], 1)
        plain = copy.deepcopy(cfg)
        del plain["bridge"]["connections"]
        self.assertEqual(self.ok("/api/connections/add", {"config": plain, "connection": {"kind": "openplc"}})["old_main"], 1)
        r = self.ok("/api/check", {"config": cfg})
        self.assertTrue(any("main declares 1 canworks value at the removed plugin's locations (%IW100)" in i["message"]
                            for i in r["items"]), r["items"])
        state = self.ok("/api/save", {"config": cfg})["state"]
        self.assertEqual(state["openplc"]["old_main"], {"count": 1, "locations": ["%IW100"], "clashes": []})
        r = self.ok("/api/openplc/move_main", {"config": cfg})
        self.assertEqual((r["moved"], r["uses"], r["clashes"]), ([name], 1, []))
        with open(main, encoding="utf-8") as f:
            text = f.read()
        self.assertNotIn("%IW100", text)
        self.assertIn("start_button : BOOL AT %IX0.0;", text)
        self.assertIn("x := canworks.%s;" % name, text)
        self.assertIn("(* %s from the plugin *)" % name, text)
        self.assertTrue(os.path.isfile(os.path.join(project, mainmove.BACKUP)))
        self.assertIsNone(self.ok("/api/check", {"config": cfg}).get("state", {}).get("old_main"))
        status, data = self.request("/api/openplc/move_main", {"config": cfg})
        self.assertEqual(status, 422)

    def test_outdated_editor_files(self):
        # Spec canopen-configurator "Out-of-date OpenPLC editor files".
        project = self.project()
        self.open(project, "project")
        state = self.ok("/api/save", {"config": self.switched()})["state"]
        self.assertEqual(state["openplc"]["outdated"], [])
        saved = state["config"]
        # canworks_in as an older canworks wrote it
        path = os.path.join(project, "pous", "programs", "canworks_in.st")
        with open(path, "w", encoding="utf-8") as f:
            f.write("PROGRAM canworks_in\nEND_PROGRAM\n")
        stamp = os.path.join(project, openplcmodbus.STAMP)
        with open(stamp, encoding="utf-8") as f:
            stamps = json.load(f)
        stamps["pous/programs/canworks_in.st"] = openplcmodbus._sha(path)
        with open(stamp, "w", encoding="utf-8") as f:
            json.dump(stamps, f)
        state = self.ok("/api/state", None, method="GET")
        self.assertEqual(state["openplc"]["outdated"], ["pous/programs/canworks_in.st"])
        warn = lambda cfg: [i for i in self.ok("/api/check", {"config": cfg})["items"] if "older canworks" in i["message"]]
        self.assertEqual([i["paths"] for i in warn(saved)], [["project"]])
        edited = copy.deepcopy(saved)
        edited["bridge"]["connections"][0]["poll_ms"] = 20
        self.assertEqual(warn(edited), [])  # a changed draft is saved anyway
        # Save without a change writes it again; canworks.json stays as it is
        config = os.path.join(project, "canworks", "canworks.json")
        before = load(config)
        r = self.ok("/api/save", {"config": saved})
        self.assertEqual(r["state"]["openplc"]["outdated"], [])
        self.assertEqual(load(config), before)
        with open(path, encoding="utf-8") as f:
            self.assertIn("canworks.ok :=", f.read())

    def test_standalone_writes_no_editor_files(self):
        self.open()
        r = self.ok("/api/save", {"config": self.switched()})
        self.assertNotIn("editor", r)
        self.assertEqual(r["state"]["openplc"]["requests"], 7)


if __name__ == "__main__":
    unittest.main()
