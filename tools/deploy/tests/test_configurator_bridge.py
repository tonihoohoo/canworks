"""The configurator's Modbus bridge requests, over HTTP (spec
canopen-configurator, "Modbus bridge target", "Bridge settings panel",
"Register map preview and export"): the register map, Pack for Modbus,
Suggest for the bridge blocks, the map exports against canworks-deploy's,
the per-type repack and the checks of a bridge config."""

import base64
import contextlib
import copy
import io
import json
import os
import shutil
import tempfile
import threading
import unittest

from canworks import cli, modbusmap
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

    def request(self, path, body):
        import http.client
        c = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=10)
        c.request("POST", path, json.dumps(body), {"Host": "127.0.0.1:%d" % self.server.server_port,
                                                   srv.TOKEN_HEADER: self.server.token,
                                                   "Content-Type": "application/json"})
        r = c.getresponse()
        data = json.loads(r.read().decode() or "{}")
        c.close()
        return r.status, data

    def ok(self, path, body):
        status, data = self.request(path, body)
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
        for path in ("/api/bridge/map", "/api/bridge/pack", "/api/bridge/suggest", "/api/bridge/export"):
            status, data = self.request(path, {"config": self.cfg, "block": "status_location", "format": "csv"})
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


class Export(Base):
    def cli_file(self, ext):
        """What canworks-deploy --export-modbus-map writes for self.cfg."""
        tmp = tempfile.mkdtemp(dir=self.dir)
        src = os.path.join(tmp, "canworks.json")
        with open(src, "w", encoding="utf-8") as f:
            json.dump(self.cfg, f)
        path = os.path.join(tmp, "map." + ext)
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(cli.main(["--config", src, "--export-modbus-map", path]), 0)
        with open(path, "rb") as f:
            return f.read()

    def test_same_files_as_the_deploy_tool(self):
        self.open()
        # An unsaved change goes into the export.
        self.cfg["bridge"]["word_order"] = "low_first"
        for ext, ctype in (("csv", "text/csv"), ("json", "application/json"), ("st", "text/plain")):
            r = self.ok("/api/bridge/export", {"config": self.cfg, "format": ext})
            self.assertEqual((r["errors"], r["name"], r["content_type"]), (0, "pump-station_modbus." + ext, ctype))
            self.assertEqual(base64.b64decode(r["data"]), self.cli_file(ext), ext)
            self.assertEqual(r["rows"], len(modbusmap.register_map(self.cfg)))
        st = base64.b64decode(r["data"]).decode()
        self.assertIn("word order low_first", st)

    def test_problem_downloads_nothing(self):
        self.open()
        self.cfg["networks"][0]["nodes"][0]["tx_pdos"][0]["entries"][0]["iec_location"] = "%IW1"
        r = self.ok("/api/bridge/export", {"config": self.cfg, "format": "st"})
        # The odd start, and the overlap with the next entry it causes.
        self.assertEqual(r["errors"], 2)
        self.assertNotIn("data", r)
        self.assertIn("must start at an even byte", r["items"][0]["message"])
        # The config check's item, so the Problems row opens the field.
        self.assertEqual(r["items"][0]["paths"], ["networks[0].nodes[0].tx_pdos[0].entries[0].iec_location"])

    def test_problems_one_item_each(self):
        self.open()
        entries = self.cfg["networks"][0]["nodes"][0]["tx_pdos"][0]["entries"]
        entries[0]["iec_location"] = "%IW1"
        r = self.ok("/api/bridge/export", {"config": self.cfg, "format": "nodered"})
        self.assertGreaterEqual(r["errors"], 1)
        self.assertEqual(r["errors"], len(r["items"]))
        self.assertTrue(all("; " not in it["message"] for it in r["items"]), r["items"])

    def test_unknown_format(self):
        self.open()
        status, data = self.request("/api/bridge/export", {"config": self.cfg, "format": "xlsx"})
        self.assertEqual(status, 400)
        self.assertIn("csv, json, st or nodered", data["error"])


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


if __name__ == "__main__":
    unittest.main()


class OpenplcModbus(Base):
    """OpenPLC through Modbus (canopen-configurator "OpenPLC remote device on
    save", "Project target"): the switch, Save writing the editor's files,
    the changed-file confirm and the Project page's facts."""

    def switched(self):
        return self.ok("/api/switch_target", {"config": plugin_config(), "target": "openplc_modbus"})["config"]

    def test_switch_from_the_plugin(self):
        self.open()
        cfg = self.switched()
        b = cfg["bridge"]
        self.assertEqual(b["openplc"], {})
        self.assertTrue(b["sdo_bridge_write"])
        self.assertEqual([l["network"] for l in b["live_lists"]], ["field"])
        self.assertNotIn("listen", b)
        self.assertEqual(self.errors(cfg), [])
        # packed after the PLC link header and the status block
        text = modbusmap.map_hash_text(cfg).splitlines()
        self.assertEqual(text[:3], ["I 0 4 -", "I 4 8 -", "I 12 2 -"])
        self.assertIn("Q 6 1 -", text)

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
        cfg["bridge"]["openplc"]["poll_ms"] = 20
        status, data = self.request("/api/save", {"config": cfg})
        self.assertEqual(status, 409)
        self.assertEqual(data["editor_changed"], ["pous/programs/canworks_in.st"])
        # nothing was written
        self.assertEqual(load(os.path.join(project, "canworks", "canworks.json"))["bridge"]["openplc"], {})
        self.ok("/api/save", {"config": cfg, "editor_overwrite": True})
        with open(remote, encoding="utf-8") as f:
            self.assertEqual({g["cycleTime"] for g in json.load(f)["modbusTcpConfig"]["ioGroups"]}, {20})

    def test_standalone_writes_no_editor_files(self):
        self.open()
        r = self.ok("/api/save", {"config": self.switched()})
        self.assertNotIn("editor", r)
        self.assertEqual(r["state"]["openplc"]["requests"], 7)
