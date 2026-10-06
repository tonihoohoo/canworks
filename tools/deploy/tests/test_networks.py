"""Several networks (schema_version 2) in the deploy tool: the exports, the
editor declarations, the bundle and the clash check
(openspec change add-several-can-networks)."""

import copy
import json
import os
import shutil
import tempfile
import unittest

from openplc_canopen_deploy import bundle, clash, contract, dbcexport, dcfexport, editorproject
from openplc_canopen_deploy.configurator import declare

from .test_contract import FIXTURES, REPO, load_cases
from .test_dcfexport import NOW, section
from .test_deploy import deploy

FIXTURE_CONFIG = os.path.join(FIXTURES, "eds", "canopen.json")
TWO_NETWORKS = os.path.join(REPO, "config", "two-networks", "canopen_config.json")


def two():
    """Node 2 (pingpong) on io at 125 kbit/s and on drives at 500 kbit/s."""
    return copy.deepcopy(load_cases("cases-v2.json")["base"])


class Contract(unittest.TestCase):
    def test_networks_and_network_config(self):
        cfg = two()
        cfg["diagnostics"] = {"port": 7531}
        self.assertEqual([(n["name"], n["path"]) for n in contract.networks(cfg)],
                         [("io", "networks[0]"), ("drives", "networks[1]")])
        one = contract.network_config(cfg, "drives")
        self.assertEqual(one["adapter"]["bitrate"], 500000)
        self.assertEqual(one["master"]["diagnostics"], {"port": 7531})
        self.assertNotIn("diagnostics", cfg["networks"][1]["master"])
        with self.assertRaisesRegex(ValueError, r"2 networks \(io, drives\)"):
            contract.network_config(cfg)
        with self.assertRaisesRegex(ValueError, "no network 'x'"):
            contract.network_config(cfg, "x")
        self.assertEqual(len(contract.all_nodes(cfg)), 2)

    def test_unnamed_network_takes_its_interface(self):
        cfg = two()
        del cfg["networks"][1]["name"]
        self.assertEqual(contract.networks(cfg)[1]["name"], "vcan1")
        self.assertTrue(contract.check_config(cfg, FIXTURE_CONFIG).ok)

    def test_version_1_is_one_unnamed_network(self):
        cfg = load_cases()["base"]
        nets = contract.networks(cfg)
        self.assertEqual([(n["name"], n["path"]) for n in nets], [("", "")])
        self.assertIs(contract.network_config(cfg), cfg)


class DcfExport(unittest.TestCase):
    def test_two_networks(self):
        files, _ = dcfexport.export(two(), FIXTURE_CONFIG, now=NOW)
        self.assertEqual(sorted(files), ["drives/node_2.dcf", "io/node_2.dcf"])
        self.assertEqual(section(files["io/node_2.dcf"], "DeviceComissioning")["Baudrate"], "125")
        self.assertEqual(section(files["drives/node_2.dcf"], "DeviceComissioning")["Baudrate"], "500")

    def test_one_network_of_two(self):
        files, _ = dcfexport.export(two(), FIXTURE_CONFIG, now=NOW, network="drives")
        self.assertEqual(list(files), ["node_2.dcf"])
        self.assertEqual(section(files["node_2.dcf"], "DeviceComissioning")["Baudrate"], "500")

    def test_unknown_network(self):
        with self.assertRaises(dcfexport.ExportFailed) as e:
            dcfexport.export(two(), FIXTURE_CONFIG, now=NOW, network="x")
        self.assertIn("no network 'x' in the config (io, drives)", e.exception.problems[0][0])

    def test_write_files_makes_network_folders(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp)
        written = dcfexport.write_files({"io/node_2.dcf": "a", "drives/node_2.dcf": "b"}, tmp)
        self.assertEqual(sorted(os.path.relpath(p, tmp) for p in written),
                         [os.path.join("drives", "node_2.dcf"), os.path.join("io", "node_2.dcf")])

    def test_cli(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp)
        code, out, err = deploy("--config", TWO_NETWORKS, "--export-dcf", tmp)
        self.assertEqual(code, 0, err)
        self.assertTrue(os.path.isfile(os.path.join(tmp, "io", "node_2.dcf")))
        self.assertTrue(os.path.isfile(os.path.join(tmp, "drives", "node_2.dcf")))
        one = os.path.join(tmp, "one")
        code, out, err = deploy("--config", TWO_NETWORKS, "--export-dcf", one, "--network", "drives")
        self.assertEqual(code, 0, err)
        self.assertEqual(os.listdir(one), ["node_2.dcf"])


class DbcExport(unittest.TestCase):
    def test_two_networks(self):
        files, _ = dbcexport.export_networks(two(), FIXTURE_CONFIG)
        self.assertEqual([name for name, _ in files], ["io", "drives"])
        for name, text in files:
            self.assertIn("CANopen network %s of canopen.json" % name, text)
            self.assertIn("BO_ 0 NMT", text)
            self.assertEqual(text.count("pingpong_Heartbeat"), 1)

    def test_one_network_of_two(self):
        files, _ = dbcexport.export_networks(two(), FIXTURE_CONFIG, network="drives")
        self.assertEqual([name for name, _ in files], ["drives"])

    def test_version_1_unchanged(self):
        cfg = load_cases()["base"]
        text, _ = dbcexport.export(cfg, FIXTURE_CONFIG)
        files, _ = dbcexport.export_networks(cfg, FIXTURE_CONFIG)
        self.assertEqual(files, [("", text)])

    def test_network_file(self):
        self.assertEqual(dbcexport.network_file(os.path.join("out", "plant.dbc"), "io"),
                         os.path.join("out", "plant_io.dbc"))

    def test_cli(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp)
        code, _, err = deploy("--config", TWO_NETWORKS, "--export-dbc", os.path.join(tmp, "plant.dbc"))
        self.assertEqual(code, 0, err)
        self.assertEqual(sorted(os.listdir(tmp)), ["plant_drives.dbc", "plant_io.dbc"])
        code, _, err = deploy("--config", TWO_NETWORKS, "--export-dbc", os.path.join(tmp, "drives.dbc"),
                              "--network", "drives")
        self.assertEqual(code, 0, err)
        self.assertIn("drives.dbc", os.listdir(tmp))

    def test_network_needs_an_export(self):
        code, _, err = deploy("--config", TWO_NETWORKS, "--into-project", "unused", "--network", "io")
        self.assertEqual(code, 1)
        self.assertIn("--network needs --export-dcf or --export-dbc", err)


class Declarations(unittest.TestCase):
    def test_same_node_name_on_two_networks(self):
        cfg = two()
        for net in cfg["networks"]:
            net["nodes"][0]["name"] = "door"
        decls = declare.declarations(cfg, lambda i, index, sub: None, {})
        names = [d["name"] for d in decls]
        self.assertIn("io_door_ok", names)
        self.assertIn("drives_door_ok", names)
        ok = next(d for d in decls if d["name"] == "drives_door_ok")
        self.assertEqual(ok["path"], "networks[1].nodes[0].status_location")
        self.assertEqual(ok["node"], 1)
        self.assertTrue(ok["description"].startswith("network drives: node door (2)"))

    def test_editor_project_names_eds_objects_per_network(self):
        with open(TWO_NETWORKS, encoding="utf-8") as f:
            cfg = json.load(f)
        decls = editorproject.declarations(cfg, TWO_NETWORKS)
        names = [d["name"] for d in decls]
        self.assertEqual(names[:3], ["io_pingpong_ok", "io_pingpong_UNSIGNED32_sent_from_slave",
                                      "io_pingpong_UNSIGNED32_received_by_slave"])
        self.assertEqual(names[3:], ["drives_pingpong_ok", "drives_pingpong_UNSIGNED32_sent_from_slave",
                                      "drives_pingpong_UNSIGNED32_received_by_slave"])

    def test_one_network_unchanged(self):
        cfg = load_cases()["base"]
        decls = declare.declarations(cfg, lambda i, index, sub: None, {})
        self.assertTrue(all(d["path"].startswith(("nodes[", "master.")) for d in decls))
        self.assertFalse(any(d["description"].startswith("network ") for d in decls))


class Bundle(unittest.TestCase):
    def test_rewrite_every_network(self):
        out, by_name = bundle.rewrite(two(), FIXTURE_CONFIG)
        self.assertEqual(sorted(by_name), ["cpp-slave.eds"])
        self.assertEqual([n["eds"] for n in contract.all_nodes(out)], ["canopen/eds/cpp-slave.eds"] * 2)

    def test_clash_inside_canopen_json(self):
        cfg = two()
        cfg["networks"][1]["nodes"][0]["tx_pdos"][0]["entries"][0]["iec_location"] = "%ID100"
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp)
        os.makedirs(os.path.join(tmp, "conf"))
        with open(os.path.join(tmp, "conf", "canopen.json"), "w", encoding="utf-8") as f:
            json.dump(cfg, f)
        uses, problems = clash.bundle_uses(tmp)
        errors, _ = clash.check(uses)
        self.assertEqual(problems, [])
        self.assertEqual(errors, ["conf/canopen.json: networks[0].nodes[0].tx_pdos[0].entries[0].iec_location and "
                                  "networks[1].nodes[0].tx_pdos[0].entries[0].iec_location both map %ID100"])


if __name__ == "__main__":
    unittest.main()
