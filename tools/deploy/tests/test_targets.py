"""Project targets (canopen-config-contract "Config target", "Settings the
target does not use", "Variable name of a PDO entry", "CODESYS configs are
for CODESYS"; codesys-export and canopen-deploy with a CODESYS config)."""

import copy
import json
import os
import shutil
import unittest
from unittest import mock

from canworks import cli, contract, targets
from canworks.codesys import plan as cplan
from canworks.codesys import run as crun
from canworks.configurator import declare

from .helpers import tmpdir
from .test_codesys import BRIDGE, deploy, load


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
        del cfg["bridge"]
        self.assertEqual(targets.target(cfg), "openplc")
        cfg["codesys"] = {}
        self.assertEqual(targets.target(cfg), "codesys")

    def test_both_markers_are_an_error(self):
        cfg = load(BRIDGE)
        cfg["codesys"] = {}
        self.assertIn(targets.BOTH_MESSAGE, "\n".join(check(cfg).errors))

    def test_codesys_needs_version_2(self):
        cfg = {"adapter": {"type": "socketcan", "interface": "can0", "bitrate": 250000}, "codesys": {},
               "nodes": [{"node_id": 5, "eds": "rtd8.eds"}]}
        self.assertIn("field 'codesys' needs schema_version 2", "\n".join(check(cfg).errors))

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
        self.assertEqual((item["unused"], item["removable"]), ("codesys", True))
        self.assertIn("'emcy_code_location' is not used by CODESYS: plugin status location", item["message"])

    def test_bridge_ignores_the_scan_watchdog(self):
        cfg = load(BRIDGE)
        cfg["networks"][0]["master"]["scan_watchdog_ms"] = 500
        r = check(cfg)
        self.assertIn("networks[0].master.scan_watchdog_ms: 'scan_watchdog_ms' is not used by the Modbus bridge: "
                      "the bridge has no PLC scan", "\n".join(r.warnings))

    def test_openplc_does_not_use_codesys_settings(self):
        cfg = load(BRIDGE)
        del cfg["bridge"]
        cfg["networks"][0]["codesys"] = {"net_id": 1}
        self.assertEqual(targets.unused(cfg), [("networks[0].codesys", "codesys",
                                                "CODESYS settings of the network")])

    def test_refused_values_are_not_warned(self):
        cfg = load(BRIDGE)
        cfg["networks"][0]["master"]["sync_source"] = "plc_cycle"
        self.assertEqual(targets.unused(cfg), [])

    def test_network_kinds_are_not_removable(self):
        cfg = {"schema_version": 2, "codesys": {}, "networks": [{"name": "eng", "protocol": "j1939"}]}
        (path, key, _), = targets.unused(cfg)
        self.assertEqual(path, "networks[0].protocol")
        self.assertFalse(targets.removable(key))

    def test_table_for_the_page(self):
        rows = {r["key"]: r for r in targets.table()}
        self.assertEqual(rows["ui:editor_project"]["targets"], ["openplc"])
        self.assertEqual(rows["master.sync_source=plc_cycle"]["refused"], ["bridge"])


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
    def test_runtime_refuses_a_codesys_config(self):
        path, _ = codesys_config(self)
        code, _, err = deploy("--config", path, "--runtime", "plc.local", "--bundle", "/nonexistent")
        self.assertEqual(code, 1)
        self.assertIn("is a CODESYS config (it has a 'codesys' object): CODESYS runs it", err)
        code, _, err = deploy("--config", path, "--bridge", "plc.local")
        self.assertIn("is a CODESYS config", err)

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


if __name__ == "__main__":
    unittest.main()
