"""Project targets (canopen-config-contract "Config target", "Settings the
target does not use", "Variable name of a PDO entry", "CODESYS configs are
for CODESYS"; codesys-export and canopen-deploy with a CODESYS config)."""

import copy
import json
import os
import shutil
import unittest
import urllib.parse
from unittest import mock

from canworks import cli, contract, targets
from canworks.codesys import plan as cplan
from canworks.codesys import run as crun
from canworks.configurator import declare

from canworks.configurator import server as srv

from .helpers import tmpdir
from .test_codesys import BRIDGE, deploy, load
from .test_configurator_server import Running


def codesys_config(test, change=None, remove_unused=True):
    """The bridge example as a CODESYS config in a folder of its own: the
    path and the config."""
    cfg = load(BRIDGE)
    del cfg["bridge"]
    cfg["codesys"] = {}
    if remove_unused:
        targets.remove(cfg, [p for p, k, _ in targets.unused(cfg) if targets.removable(k)])
    if change:
        change(cfg)
    d = tmpdir(test)
    for name in ("rtd8.eds", "dio16.eds"):
        shutil.copy(os.path.join(os.path.dirname(BRIDGE), name), d)
    path = os.path.join(d, "canworks.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f)
    return path, cfg


def check(cfg, path=BRIDGE):
    return contract.check_config(cfg, path, eds_dir=os.path.dirname(BRIDGE))


class Target(unittest.TestCase):
    def test_target_from_the_markers(self):
        cfg = load(BRIDGE)
        self.assertEqual(targets.target(cfg), "bridge")
        cfg["bridge"]["openplc"] = {}
        self.assertEqual(targets.target(cfg), "openplc_modbus")
        del cfg["bridge"]
        self.assertEqual(targets.target(cfg), "plugin")  # the removed plugin's config
        cfg["codesys"] = {}
        self.assertEqual(targets.target(cfg), "codesys")

    def test_both_markers_are_an_error(self):
        cfg = load(BRIDGE)
        cfg["codesys"] = {}
        self.assertIn(targets.BOTH_MESSAGE, "\n".join(check(cfg).errors))

    def test_version_1_codesys_refused(self):
        cfg = {"adapter": {"type": "socketcan", "interface": "can0", "bitrate": 250000}, "codesys": {},
               "nodes": [{"node_id": 5, "eds": "rtd8.eds"}]}
        self.assertIn(contract.NOT_BRIDGE_MESSAGE, "\n".join(check(cfg).errors))

    def test_codesys_config_without_locations(self):
        _, cfg = codesys_config(self)
        for node in cfg["networks"][0]["nodes"]:
            for key in ("tx_pdos", "rx_pdos"):
                for p in node.get(key, []):
                    for e in p["entries"]:
                        self.assertNotIn("iec_location", e)
        self.assertEqual(cfg["networks"][0]["adapter"], {"interface": "sim0", "bitrate": 250000})
        r = check(cfg)
        self.assertEqual((r.errors, r.warnings), ([], []))

    def test_codesys_adapter_needs_the_bit_rate(self):
        _, cfg = codesys_config(self)
        del cfg["networks"][0]["adapter"]["bitrate"]
        self.assertIn("networks[0]: adapter: the bit rate is missing", "\n".join(check(cfg).errors))

    def test_codesys_settings_in_the_schema(self):
        _, cfg = codesys_config(self)
        cfg["codesys"] = {"project": "C:\\p.project", "device": "PLC", "create": "4096:0000 0004:3.5.22.40",
                          "variables": False}
        cfg["networks"][0]["codesys"] = {"net_id": 1, "interface": "CAN"}
        self.assertEqual(check(cfg).errors, [])
        cfg["networks"][0]["codesys"] = {"net_id": 300}
        self.assertTrue(check(cfg).errors)


class Unused(unittest.TestCase):
    def test_codesys_warns_with_the_path_and_reason(self):
        cfg = load(BRIDGE)
        del cfg["bridge"]
        cfg["codesys"] = {}
        r = check(cfg)
        self.assertEqual(r.errors, [])
        item = [i for i in r.items if i["paths"] == ["networks[0].nodes[0].emcy_code_location"]][0]
        self.assertEqual(item["level"], "warning")
        self.assertEqual((item["unused"], item["removable"], item["key"]), ("codesys", True, "nodes.emcy_code_location"))
        self.assertIn("'emcy_code_location' is not used by CODESYS: canworks status location", item["message"])

    def test_every_setting_has_a_page_label(self):
        # The page's list of settings the target does not use names each one.
        rows = {r["key"]: r for r in targets.table()}
        for key, _, _, _ in targets.ROWS:
            if not key.startswith("ui:"):
                self.assertTrue(rows[key]["label"], key)
        self.assertEqual(rows["nodes.tx_pdos.entries.iec_location"]["label"], "PLC location")

    def test_openplc_does_not_use_codesys_settings(self):
        cfg = load(BRIDGE)
        cfg["bridge"]["openplc"] = {}
        cfg["networks"][0]["codesys"] = {"net_id": 1}
        self.assertEqual(targets.unused(cfg), [("networks[0].codesys", "codesys",
                                                "CODESYS settings of the network")])
        del cfg["bridge"]
        self.assertEqual(targets.unused(cfg), [])  # a plugin config is only switched, not cleaned

    def test_refused_values_are_not_warned(self):
        cfg = load(BRIDGE)
        cfg["networks"][0]["nodes"][1]["tx_pdos"][0]["entries"][0]["bits"] = [{"bit": 0, "iec_location": "%IX110.0"}]
        self.assertEqual(targets.unused(cfg), [])
        self.assertTrue(check(cfg).errors)

    def test_network_kinds_are_not_removable(self):
        cfg = {"schema_version": 2, "codesys": {}, "networks": [{"name": "eng", "protocol": "j1939"}]}
        (path, key, _), = targets.unused(cfg)
        self.assertEqual(path, "networks[0].protocol")
        self.assertFalse(targets.removable(key))

    def test_table_for_the_page(self):
        rows = {r["key"]: r for r in targets.table()}
        self.assertEqual(rows["ui:editor_project"]["targets"], ["openplc_modbus"])
        self.assertEqual(rows["nodes.rx_pdos.entries.bits.iec_location"]["refused"], ["bridge", "openplc_modbus"])


class EntryName(unittest.TestCase):
    def test_name_replaces_the_eds_part(self):
        cfg = load(BRIDGE)
        cfg["networks"][0]["nodes"][1]["tx_pdos"][0]["entries"][0]["name"] = "door_open"
        names = [d["name"] for d in declare.declarations(cfg, lambda *a: "Read_input", {})]
        self.assertIn("dio_door_open", names)

    def test_unlocated_entries_only_when_asked(self):
        _, cfg = codesys_config(self)
        self.assertFalse([d for d in declare.declarations(cfg, lambda *a: None, {}) if d["kind"] == "pdo"])
        pdo = [d for d in declare.declarations(cfg, lambda *a: None, {}, unlocated=True) if d["kind"] == "pdo"]
        self.assertTrue(pdo)
        self.assertIsNone(pdo[0]["location"])
        self.assertEqual(pdo[0]["name"], "rtd_" + pdo[0]["entry_name"])

    def test_duplicate_names(self):
        cfg = load(BRIDGE)
        entries = cfg["networks"][0]["nodes"][1]["tx_pdos"][0]["entries"]
        entries[0]["name"] = entries[1]["name"] = "Door"
        self.assertIn('two PDO entries are named "Door"', "\n".join(check(cfg).errors))

    def test_duplicate_bit_names(self):
        cfg = load(BRIDGE)
        entries = cfg["networks"][0]["nodes"][1]["tx_pdos"][0]["entries"]
        entries[0]["name"] = "Door"
        entries[1]["bits"] = [{"bit": 0, "name": "lamp"}, {"bit": 1, "name": "door"}]
        errors = "\n".join(check(cfg).errors)
        self.assertIn('two PDO entries or bits are named "door"', errors)
        entries[1]["bits"][1]["name"] = "LAMP"
        self.assertIn('two PDO entries or bits are named "LAMP"', "\n".join(check(cfg).errors))

    def test_name_names_the_register_row(self):
        from canworks import modbusmap
        cfg = load(BRIDGE)
        cfg["networks"][0]["nodes"][1]["tx_pdos"][0]["entries"][0]["name"] = "door_open"
        names = [r["name"] for r in modbusmap.register_map(cfg)]
        self.assertIn("dio.door_open", names)

    def test_name_must_be_an_identifier(self):
        cfg = load(BRIDGE)
        cfg["networks"][0]["nodes"][1]["tx_pdos"][0]["entries"][0]["name"] = "door open"
        self.assertTrue(check(cfg).errors)


class Plan(unittest.TestCase):
    def test_channels_without_locations(self):
        path, cfg = codesys_config(self, lambda c: c["networks"][0]["nodes"][1]["tx_pdos"][0]["entries"][0]
                                   .__setitem__("name", "door_open"))
        plan, _ = cplan.build(cfg, path)
        dio = plan["networks"][0]["nodes"][1]
        self.assertEqual(dio["channels"][0]["variable"], "dio_door_open")
        self.assertEqual(len(plan["networks"][0]["nodes"][0]["channels"]), 4)

    def test_settings_from_the_config(self):
        def change(c):
            c["codesys"] = {"device": "HMI", "variables": False}
            c["networks"][0]["codesys"] = {"net_id": 2, "interface": "CAN2"}
        path, cfg = codesys_config(self, change)
        plan, _ = cplan.build(cfg, path)
        self.assertEqual((plan["plc"], plan["variables"]), ("HMI", False))
        self.assertEqual((plan["networks"][0]["net_id"], plan["networks"][0]["interface"]), (2, "CAN2"))
        plan, _ = cplan.build(cfg, path, overrides={"field": 0}, interfaces={"field": "CAN"}, plc="PLC",
                              variables=True)
        self.assertEqual((plan["plc"], plan["variables"]), ("PLC", True))
        self.assertEqual((plan["networks"][0]["net_id"], plan["networks"][0]["interface"]), (0, "CAN"))

    def test_notes_are_the_check_warnings(self):
        cfg = load(BRIDGE)
        del cfg["bridge"]
        cfg["codesys"] = {}
        plan, _ = cplan.build(cfg, BRIDGE)
        self.assertIn({"where": "field/rtd", "setting": "emcy_code_location",
                       "note": dict((p, w) for p, _, w in targets.unused(cfg))["networks[0].nodes[0].emcy_code_location"]},
                      plan["notes"])
        self.assertIn({"where": "field/rtd", "setting": "PDO entry locations",
                       "note": "CODESYS assigns the I/O addresses itself; the entry's name names the channel"},
                      plan["notes"])


class Deploy(unittest.TestCase):
    def test_bridge_refuses_a_codesys_config(self):
        path, _ = codesys_config(self)
        code, _, err = deploy("--config", path, "--bridge", "plc.local")
        self.assertEqual(code, 1)
        self.assertIn("is a CODESYS config (it has a 'codesys' object): CODESYS runs it", err)

    def test_import_without_a_project(self):
        path, _ = codesys_config(self)
        code, _, err = deploy("--config", path, "--codesys-import")
        self.assertEqual(code, 1)
        self.assertIn("--codesys-import needs a project", err)

    def test_import_takes_the_config_project(self):
        d = tmpdir(self)
        project = os.path.join(d, "cell.project")
        open(project, "w").close()
        path, cfg = codesys_config(self, lambda c: c["codesys"].update(project=project, device="PLC"))
        folder = os.path.join(d, "export")
        seen = []

        def runner(line):
            seen.append(load(os.path.join(folder, cplan.PLAN_NAME)))
            with open(os.path.join(folder, cplan.REPORT_NAME), "w", encoding="utf-8") as f:
                f.write("result: ok\n")
        exe = os.path.join(d, "CODESYS.exe")
        open(exe, "w").close()
        args = cli.parser().parse_args(["--config", path, "--codesys-import", "--codesys-dir", folder,
                                        "--codesys-exe", exe, "--codesys-profile", "P"])
        self.assertEqual(cli._codesys(args, cfg, None, lambda m: None, runner=runner), 0)
        self.assertEqual((seen[0]["project"], seen[0]["plc"]), (os.path.abspath(project), "PLC"))

    def test_import_creates_with_the_config_device(self):
        d = tmpdir(self)
        project = os.path.join(d, "new.project")
        path, cfg = codesys_config(self, lambda c: c["codesys"].update(project=project,
                                                                       create="4096:0000 0004:3.5.22.40"))
        folder = os.path.join(d, "export")
        seen = []

        def runner(line):
            seen.append(load(os.path.join(folder, cplan.PLAN_NAME)))
            with open(os.path.join(folder, cplan.REPORT_NAME), "w", encoding="utf-8") as f:
                f.write("result: ok\n")
        exe = os.path.join(d, "CODESYS.exe")
        open(exe, "w").close()
        args = cli.parser().parse_args(["--config", path, "--codesys-import", "--codesys-dir", folder,
                                        "--codesys-exe", exe, "--codesys-profile", "P"])
        with mock.patch.object(crun, "find_codesys", return_value=exe):
            self.assertEqual(cli._codesys(args, cfg, None, lambda m: None, runner=runner), 0)
        self.assertEqual(seen[0]["create"]["device"]["id"], "0000 0004")


def entries(cfg):
    return [e for n in cfg["networks"][0]["nodes"] for k in ("tx_pdos", "rx_pdos") for p in n.get(k, [])
            for e in p["entries"]]


class Server(Running):
    """/api/switch_target and /api/codesys/build (canopen-configurator
    "Switching the target", "CODESYS actions")."""

    def setUp(self):
        super().setUp()
        self.folder = os.path.join(self.dir, "cell")
        os.makedirs(self.folder)
        for name in ("rtd8.eds", "dio16.eds"):
            shutil.copy(os.path.join(os.path.dirname(BRIDGE), name), self.folder)
        self.cfg = load(BRIDGE)
        self.cfg["networks"][0]["nodes"][0]["emcy_code_location"] = "%IW90"
        with open(os.path.join(self.folder, "canworks.json"), "w", encoding="utf-8") as f:
            json.dump(self.cfg, f)
        self.ok("POST", "/api/open", {"path": self.folder, "mode": "standalone"})

    def switch(self, cfg, target, **kw):
        return self.ok("POST", "/api/switch_target", dict({"config": cfg, "target": target}, **kw))

    def test_state_has_the_table(self):
        state = self.ok("GET", "/api/state")
        self.assertIn("codesys_found", state)
        self.assertIn("ui:codesys", [r["key"] for r in state["targets"]])

    def test_bridge_to_codesys_and_back(self):
        # No question: what CODESYS does not use goes (target-cleans-up).
        r = self.switch(self.cfg, "codesys")
        cfg = r["config"]
        self.assertEqual((cfg["codesys"], targets.target(cfg)), ({}, "codesys"))
        self.assertNotIn("unused", r)
        self.assertGreaterEqual(r["removed"], 2)
        self.assertNotIn("emcy_code_location", cfg["networks"][0]["nodes"][0])
        self.assertTrue(all("name" in e and "iec_location" not in e for e in entries(cfg)))
        self.assertEqual(check(cfg).errors, [])
        self.assertEqual([w for w in check(cfg).items if w.get("unused")], [])
        # The names are the generated declaration names (EDS names).
        after = {d["name"] for d in declare.declarations(cfg, lambda *a: None, {}, unlocated=True) if d["kind"] == "pdo"}
        self.assertIn("dio_Read_input_8_bit_1", after)
        self.assertIn("rtd_AI0_Input_PV", after)
        # Back to the bridge: every entry is placed per type, the names stay.
        back = self.switch(cfg, "bridge")
        self.assertEqual(back["located"], len(entries(cfg)))
        out = back["config"]
        self.assertNotIn("codesys", out)
        self.assertTrue(all(e.get("iec_location") and e.get("name") for e in entries(out)))
        self.assertEqual(check(out).errors, [])

    def test_old_switch_options_are_ignored(self):
        cfg = self.switch(self.cfg, "codesys", keep=True, preview=True)["config"]
        self.assertNotIn("emcy_code_location", cfg["networks"][0]["nodes"][0])

    def test_codesys_to_bridge_packs(self):
        cfg = self.switch(self.cfg, "codesys")["config"]
        out = self.switch(cfg, "bridge")["config"]
        self.assertEqual(targets.target(out), "bridge")
        self.assertNotIn("codesys", out)
        self.assertTrue(all(e.get("iec_location") for e in entries(out)))
        self.assertEqual(check(out).errors, [])

    def test_bridge_and_openplc(self):
        out = self.switch(self.cfg, "openplc_modbus")["config"]
        self.assertEqual(targets.target(out), "openplc_modbus")
        self.assertEqual(check(out).errors, [])
        back = self.switch(out, "bridge")["config"]
        self.assertEqual(targets.target(back), "bridge")
        self.assertNotIn("openplc", back["bridge"])

    def test_plugin_config_switches_to_openplc(self):
        cfg = load(BRIDGE)
        del cfg["bridge"]
        status, data, _ = self.request("POST", "/api/save", {"config": cfg})
        self.assertEqual(status, 409, data)
        self.assertTrue(data["plugin"])
        out = self.switch(cfg, "openplc_modbus")["config"]
        self.assertEqual(targets.target(out), "openplc_modbus")
        self.assertEqual(check(out).errors, [])
        self.ok("POST", "/api/save", {"config": out})
        # The removed plugin is not a target to switch to.
        self.assertEqual(self.request("POST", "/api/switch_target", {"config": out, "target": "plugin"})[0], 400)

    def test_bit_channels_follow_the_target(self):
        dio = self.cfg["networks"][0]["nodes"][1]
        dio["rx_pdos"][0]["entries"][0]["bits"] = [{"bit": 0, "name": "lamp"}, {"bit": 1}]
        self.assertEqual(check(self.cfg).errors, [])
        # CODESYS: names only, every bit named.
        cs = self.switch(self.cfg, "codesys")["config"]
        bits = cs["networks"][0]["nodes"][1]["rx_pdos"][0]["entries"][0]["bits"]
        self.assertEqual([b.get("iec_location") for b in bits], [None, None])
        self.assertEqual(bits[0]["name"], "lamp")
        self.assertTrue(bits[1]["name"].endswith("_bit1"), bits[1])
        self.assertEqual(check(cs).errors, [])
        # Back to the bridge: the bits are served in the entry's own location, which it gets again.
        back = self.switch(cs, "bridge")["config"]
        rx = back["networks"][0]["nodes"][1]["rx_pdos"][0]["entries"][0]
        self.assertTrue(rx["iec_location"])
        self.assertEqual(rx["bits"][0], {"bit": 0, "name": "lamp"})
        self.assertEqual(check(back).errors, [])

    def test_bridge_to_codesys(self):
        cfg = self.switch(self.cfg, "bridge")["config"]
        out = self.switch(cfg, "codesys")["config"]
        self.assertNotIn("bridge", out)
        self.assertEqual(targets.target(out), "codesys")

    def test_bad_target(self):
        status, data, _ = self.request("POST", "/api/switch_target", {"config": self.cfg, "target": "s7"})
        self.assertEqual(status, 400, data)

    def test_save_leaves_out_what_the_target_does_not_use(self):
        """canopen-configurator "Settings the target does not use are left out on save"."""
        cfg = self.switch(self.cfg, "codesys")["config"]
        cfg["networks"][0]["nodes"][0]["emcy_code_location"] = "%IW90"
        r = self.ok("POST", "/api/save", {"config": cfg})
        self.assertEqual(r["left_out"], 1)
        with open(os.path.join(self.folder, "canworks.json"), encoding="utf-8") as f:
            saved = json.load(f)
        self.assertNotIn("emcy_code_location", saved["networks"][0]["nodes"][0])
        self.assertEqual(r["state"]["config"], saved)
        # Nothing left out: none counted.
        self.assertEqual(self.ok("POST", "/api/save", {"config": saved})["left_out"], 0)

    def test_build_needs_a_saved_config(self):
        cfg = self.switch(self.cfg, "codesys")["config"]
        self.ok("POST", "/api/save", {"config": cfg})
        self.server.session.pending["new.eds"] = b""
        status, data, _ = self.request("POST", "/api/codesys/build", {})
        self.assertEqual(status, 409, data)
        self.assertTrue(data.get("unsaved"))

    def test_build_reports_codesys_missing(self):
        cfg = self.switch(self.cfg, "codesys")["config"]
        cfg["codesys"] = {"project": os.path.join(self.dir, "missing.project")}
        self.ok("POST", "/api/save", {"config": cfg})
        r = self.ok("POST", "/api/codesys/build", {})
        self.assertFalse(r["ok"])
        self.assertIn("does not exist", r["output"])

    def test_build_runs_codesys(self):
        root = os.path.join(self.dir, "pf")
        common = os.path.join(root, "CODESYS 3.5.22.40", "CODESYS", "Common")
        profiles = os.path.join(root, "CODESYS 3.5.22.40", "CODESYS", "Profiles")
        os.makedirs(common)
        os.makedirs(profiles)
        open(os.path.join(common, "CODESYS.exe"), "w").close()
        open(os.path.join(profiles, "CODESYS V3.5 SP22.profile.xml"), "w").close()
        project = os.path.join(self.dir, "cell.project")
        open(project, "w").close()
        cfg = self.switch(self.cfg, "codesys")["config"]
        cfg["codesys"] = {"project": project}
        self.ok("POST", "/api/save", {"config": cfg})
        lines = []

        def runner(line, report="result: ok\nnodes: 2\n"):
            lines.append(line)
            folder = os.path.dirname(line.split('--runscript="')[1].rstrip('"'))
            with open(os.path.join(folder, cplan.REPORT_NAME), "w", encoding="utf-8") as f:
                f.write(report)
        self.server.codesys_runner = runner
        with mock.patch.dict(os.environ, {"PROGRAMFILES": root}):
            self.assertTrue(self.ok("GET", "/api/state")["codesys_found"])
            r = self.ok("POST", "/api/codesys/build", {})
        self.assertTrue(r["ok"], r)
        self.assertIn("result: ok", r["output"])
        self.assertIn("SP22", lines[0])

        def locked(line):
            runner(line, "result: error\nthe project is opened by another user (locked)\n")
        self.server.codesys_runner = locked
        with mock.patch.dict(os.environ, {"PROGRAMFILES": root}):
            r = self.ok("POST", "/api/codesys/build", {})
        self.assertFalse(r["ok"])
        self.assertIn("Close the project in CODESYS first", r["hint"])

        # A project that does not exist and no PLC device: the page's words, not the command line's.
        cfg["codesys"] = {"project": os.path.join(self.dir, "new")}
        self.ok("POST", "/api/save", {"config": cfg})
        with mock.patch.dict(os.environ, {"PROGRAMFILES": root}):
            r = self.ok("POST", "/api/codesys/build", {})
        self.assertFalse(r["ok"])
        self.assertIn("new.project does not exist. Pick a PLC device for a new project", r["output"])
        self.assertNotIn("--codesys-new", r["output"])

    def test_codesys_devices(self):
        from canworks.configurator import server as srv
        root = os.path.join(os.path.dirname(__file__), "data", "codesys-devices", "Devices")
        project = os.path.join(self.dir, "cell.project")
        open(project, "w").close()
        with mock.patch.object(srv, "_codesys_devices", None), \
                mock.patch("canworks.codesys.run.repository_roots", return_value=[root]):
            r = self.ok("GET", "/api/codesys/devices?project=" + urllib.parse.quote(os.path.join(self.dir, "cell")))
            self.assertTrue(r["exists"])
            self.assertEqual(len(r["devices"]), 3)
            r = self.ok("GET", "/api/codesys/devices?project=" + urllib.parse.quote(os.path.join(self.dir, "new.project")))
            self.assertFalse(r["exists"])
            self.assertIsNone(self.ok("GET", "/api/codesys/devices")["exists"])


if __name__ == "__main__":
    unittest.main()
