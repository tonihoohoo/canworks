"""Import from CODESYS (codesys-import spec): the PLCopenXML reader and the
converter, on exports CODESYS V3.5 SP22 made of the virtual-plant example
(tests/data/codesys-import: the three CANbus objects exported together, and
the io network after setting fixed I/O addresses and SDO flags in CODESYS)."""

import copy
import gzip
import json
import os
import re
import shutil
import unittest

from canworks import contract
from canworks.codesys import xmlimport as x

from .helpers import tmpdir
from .test_contract import REPO

DATA = os.path.join(os.path.dirname(__file__), "data", "codesys-import")
PLANT_XML = os.path.join(DATA, "virtual-plant.xml.gz")
EDITED_XML = os.path.join(DATA, "virtual-plant-io-edited.xml.gz")
PLANT_DIR = os.path.join(REPO, "examples", "virtual-plant", "canworks")


def xml_text(path):
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return f.read()


def library():
    return x.library_finder(x.folder_matcher([("library", PLANT_DIR)]))


def run(source, find=None, choice=0):
    tops = x.read(source.encode("utf-8") if source.lstrip().startswith("<") else source)
    return x.convert(x.choices(tops)[choice], find or library())


def node(cfg, name):
    return next(n for net in cfg["networks"] for n in net["nodes"] if n["name"] == name)


def pdo(n, key, number):
    return next((p for p in n.get(key, []) if p["number"] == number), None)


def in_device(text, device="PLC"):
    """The export as if the CANbus objects were exported with their PLC:
    one PLC configuration holding them."""
    start = text.index("<configurations>") + len("<configurations>")
    end = text.rindex("</configurations>")
    inner = text[start:end]
    plc = ('<configuration name="%s"><addData><data name="Device" handleUnknown="discard"><Device xmlns="">'
           '<DeviceType><DeviceIdentification><Type>4096</Type><Id>0000 0001</Id><Version>3.5.22.40</Version>'
           '</DeviceIdentification></DeviceType></Device></data>'
           '<data name="http://www.3s-software.com/plcopenxml/configurations" handleUnknown="implementation">'
           '<configurations>%s</configurations></data></addData></configuration>' % (device, inner))
    return text[:start] + plc + text[end:]


# What a canworks config says that the CODESYS project of the virtual-plant
# example cannot give back, and why (the export was made before
# fix-codesys-export-names and with CODESYS's own defaults).
def expected_from_example():
    with open(os.path.join(PLANT_DIR, "canworks.json"), encoding="utf-8") as f:
        cfg = json.load(f)
    nets = [n for n in cfg["networks"] if n.get("role") != "slave"]
    for net in nets:
        net["master"].pop("time_period_ms", None)  # the script cannot switch TIME producing on
        for n in net["nodes"]:
            if n["name"] in ("conveyor", "cell"):
                n["heartbeat_ms"] = 0  # the export predates "heartbeat producer always set"
            if n["name"] == "rtd":
                n.pop("sdo")  # both rows equal the EDS default, CODESYS drops them
    cell = next(n for n in nets[-1]["nodes"] if n["name"] == "cell")
    # The EDS maps two objects in TPDO3 and TPDO5 and CODESYS kept both.
    pdo(cell, "tx_pdos", 3)["entries"].append({"index": "0x5E10", "subindex": 2, "type": "UNSIGNED32"})
    pdo(cell, "tx_pdos", 5)["entries"].append({"index": "0x5E11", "subindex": 2, "type": "UNSIGNED32"})
    pdo(cell, "tx_pdos", 5)["cob_id"] = 0x57F  # "auto" as canworks resolved it
    return nets


CARRIED_NODE = ("node_id", "name", "eds", "mandatory", "boot", "heartbeat_ms", "heartbeat_consumer", "time_cob_id",
                "guard_time_ms", "restore_configuration")


def comparable(nets):
    out = {}
    for net in nets:
        nodes = {}
        for n in net["nodes"]:
            c = {k: n[k] for k in CARRIED_NODE if k in n}
            if isinstance(c.get("time_cob_id"), str):
                c["time_cob_id"] = int(c["time_cob_id"], 0)
            for key in ("tx_pdos", "rx_pdos"):
                c[key] = {p.get("number"): {"transmission": p.get("transmission"),
                                            "cob_id": p.get("cob_id") if p.get("cob_id") != "auto" else None,
                                            "entries": [(int(str(e["index"]), 0), e.get("subindex", 0), e["type"])
                                                        for e in p["entries"]]}
                          for p in n.get(key, [])}
            c["sdo"] = [(int(str(s["index"]), 0), s.get("subindex", 0), s["type"], s["value"]) for s in n.get("sdo", [])]
            nodes[n["node_id"]] = c
        m = net["master"]
        out[net["name"]] = {"master": {k: m.get(k) for k in ("node_id", "heartbeat_ms", "sync_period_us",
                                                              "time_period_ms")},
                            "bitrate": net["adapter"]["bitrate"], "nodes": nodes}
    return out


class Reader(unittest.TestCase):
    def test_choices(self):
        tops = x.read(PLANT_XML)
        found = x.choices(tops)
        self.assertEqual([(c["name"], [b.name for b in c["buses"]], c["nodes"]) for c in found],
                         [(None, ["CANbus", "CANbus_2", "CANbus_3"], 5)])

    def test_device_export(self):
        tops = x.read(in_device(xml_text(PLANT_XML)).encode("utf-8"))
        found = x.choices(tops)
        self.assertEqual([(c["name"], len(c["buses"])) for c in found], [("PLC", 3)])
        res = x.convert(found[0], library())
        self.assertEqual(res.cfg["codesys"], {"device": "PLC"})

    def test_not_plcopen(self):
        with self.assertRaises(x.ImportError_):
            x.read(b"<x/>")
        with self.assertRaises(x.ImportError_):
            x.read(b"not xml")

    def test_numbers(self):
        self.assertEqual([x.number(v) for v in ("16#7B", "123", "TRUE", "FALSE", "'16#185'", "2#101", "")],
                         [123, 123, 1, 0, 0x185, 5, None])
        self.assertEqual(x.generic_cob_id("'$NODEID+16#180'"), ("node", 0x180))
        self.assertEqual(x.generic_cob_id("'16#80000285'"), ("literal", 0x80000285))


class Convert(unittest.TestCase):
    def test_virtual_plant(self):
        res = run(PLANT_XML)
        self.assertEqual(comparable(res.cfg["networks"]), comparable(expected_from_example()))
        self.assertEqual([n["codesys"] for n in res.cfg["networks"]],
                         [{"net_id": 0, "managed": [5, 6, 7]}, {"net_id": 1, "managed": [4]},
                          {"net_id": 2, "managed": [20]}])
        self.assertEqual([n["adapter"] for n in res.cfg["networks"]],
                         [{"interface": "can0", "bitrate": 250000}, {"interface": "can1", "bitrate": 500000},
                          {"interface": "can2", "bitrate": 250000}])
        self.assertEqual(sorted(res.eds_files), ["cell.eds", "conveyor.eds", "dio16.eds", "rtd8.eds"])
        self.assertEqual(res.missing, [])

    def test_imported_config_checks(self):
        res = run(EDITED_XML)
        folder = tmpdir(self)
        for name, path in res.eds_files.items():
            shutil.copy(path, os.path.join(folder, name))
        path = os.path.join(folder, "canworks.json")
        result = contract.check_config(res.cfg, path)
        self.assertEqual((result.errors, result.warnings), ([], []))

    def test_fixed_address_must_fit_the_channel(self):
        # CODESYS refuses an address of another size or direction: the check says so first.
        res = run(EDITED_XML)
        folder = tmpdir(self)
        for name, path in res.eds_files.items():
            shutil.copy(path, os.path.join(folder, name))
        path = os.path.join(folder, "canworks.json")
        entry = pdo(node(res.cfg, "dio"), "rx_pdos", 1)["entries"][2]
        for address, ok in (("%QW20", True), ("%QB20", False), ("%IW20", False)):
            entry["codesys"]["address"] = address
            errors = [e for e in contract.check_config(res.cfg, path).errors if "CODESYS address" in e]
            self.assertEqual(errors == [], ok, (address, errors))

    def test_variable_names_become_entry_names(self):
        res = run(PLANT_XML)
        # Every channel has the name canworks would give it: no name needed.
        self.assertNotIn("name", pdo(node(res.cfg, "rtd"), "tx_pdos", 1)["entries"][0])
        text = xml_text(PLANT_XML).replace("<Mapping>io_rtd_AI0_Input_PV<", "<Mapping>io_rtd_oven<") \
            .replace("<Mapping>io_rtd_AI1_Input_PV<", "<Mapping>oven_2<")
        entries = pdo(node(run(text).cfg, "rtd"), "tx_pdos", 1)["entries"]
        self.assertEqual(entries[0].get("name"), "oven")
        self.assertEqual(entries[1].get("codesys"), {"variable": "oven_2"})

    def test_one_network_keeps_its_variables(self):
        # Alone in the config the io network's channels would be rtd_..., so
        # the io_... names CODESYS has are kept as they are.
        res = run(EDITED_XML)
        entry = pdo(node(res.cfg, "dio"), "tx_pdos", 1)["entries"][1]
        self.assertEqual(entry["codesys"], {"variable": "io_dio_Read_input_8_bit_2"})
        self.assertEqual(res.cfg["networks"][0]["name"], "io")

    def test_generated_sdo_rows_skipped(self):
        res = run(PLANT_XML)
        self.assertEqual(node(res.cfg, "dio")["sdo"],
                         [{"index": "0x2000", "subindex": 0, "type": "UNSIGNED16", "value": 10}])
        self.assertNotIn("sdo", node(res.cfg, "new_io"))

    def test_disabled_pdo_left_out(self):
        res = run(PLANT_XML)
        self.assertEqual([p["number"] for p in node(res.cfg, "rtd")["tx_pdos"]], [1])
        self.assertEqual([p["number"] for p in node(res.cfg, "cell")["tx_pdos"]], [1, 2, 3, 5])

    def test_fixed_address_and_sdo_flags(self):
        res = run(EDITED_XML)
        dio = node(res.cfg, "dio")
        self.assertEqual(pdo(dio, "tx_pdos", 1)["entries"][0]["codesys"]["address"], "%IB40")
        self.assertEqual(pdo(dio, "rx_pdos", 1)["entries"][2]["codesys"]["address"], "%QW20")
        self.assertEqual(dio["sdo"][0]["codesys"], {"abort_on_error": True, "jump_to_line": 3})
        self.assertIn({"where": "io/dio", "setting": "SDO 0x1014:0",
                       "note": "abort-on-error / jump-to-line on a row CODESYS generates; set it again in CODESYS "
                               "after a build"}, res.report)

    def test_identity_checks(self):
        text = xml_text(PLANT_XML)
        # Tick the product code of every node, untick the vendor ID of rtd.
        text = re.sub(r'(<Parameter ParameterId="285311008"[^>]*>\s*<Attributes) download="false"', r"\1", text)
        rtd = text.index('<configuration name="rtd">')
        vendor = text.index('ParameterId="285310992"', rtd)
        attrs = text.index("<Attributes", vendor)
        text = text[:attrs] + '<Attributes download="false"' + text[attrs + len("<Attributes"):]
        res = run(text)
        self.assertEqual(node(res.cfg, "rtd")["codesys"]["checks"], ["product"])
        self.assertEqual(node(res.cfg, "dio")["codesys"]["checks"], ["vendor", "product"])
        res = run(PLANT_XML)
        self.assertNotIn("codesys", node(res.cfg, "dio"))  # CODESYS's default: vendor only

    def test_missing_eds(self):
        res = run(PLANT_XML, find=lambda ident: None)
        self.assertEqual([(m["name"], m["eds_state"]) for m in res.missing],
                         [("rtd", "missing"), ("dio", "missing"), ("new_io", "missing"), ("conveyor", "missing"),
                          ("cell", "missing")])
        self.assertEqual(node(res.cfg, "rtd")["eds"], "")

    def test_nearest_revision(self):
        def find(ident):
            return {"path": os.path.join(PLANT_DIR, "dio16.eds"), "state": "library",
                    "note": "no EDS with revision 0x10001; took dio16.eds (revision 0x10000)"} \
                if ident["product_code"] == 1025 else library()(ident)
        res = run(PLANT_XML, find=find)
        self.assertIn({"where": "io/dio", "setting": "EDS",
                       "note": "no EDS with revision 0x10001; took dio16.eds (revision 0x10000)"}, res.report)

    def test_slave_on_a_canbus_is_reported(self):
        text = in_device(xml_text(PLANT_XML))
        # Turn the third CANbus's manager into a CANopen device (CODESYS as slave).
        third = text.index('<configuration name="CANbus_3">')
        mgr = text.index("<Type>16</Type>", third)
        text = text[:mgr] + "<Type>17</Type>" + text[mgr + len("<Type>16</Type>"):]
        res = run(text)
        self.assertEqual([n["name"] for n in res.cfg["networks"]], ["io", "motion"])
        self.assertTrue(any(r["where"] == "PLC/CANbus_3" and r["setting"] == "CANbus" for r in res.report),
                        res.report)

    def test_report_text(self):
        res = run(PLANT_XML)
        lines = x.text(res).splitlines()
        self.assertIn("node     io/rtd (node 5): EDS from the library, rtd8.eds", lines)


class Values(unittest.TestCase):
    def test_signed_sdo_value(self):
        self.assertEqual(x._sdo_value("16#FFFF", "INTEGER16"), -1)
        self.assertEqual(x._sdo_value("16#a", "UNSIGNED16"), 10)
        self.assertIs(x._sdo_value("1", "BOOLEAN"), True)


if __name__ == "__main__":
    unittest.main()


class RoundTrip(unittest.TestCase):
    """canworks -> CODESYS -> canworks -> CODESYS on the stand-in: the
    import gives the config back, and building it again changes nothing."""

    def build(self, w, proj, cfg, path):
        from canworks.codesys import plan as cplan, run as crun
        folder = os.path.join(tmpdir(self), "codesys")
        files, _ = cplan.export_files(cfg, path)
        crun.write_folder(files, folder)
        return w.run(folder, primary=proj)

    def export(self, w, proj, device=None):
        from canworks.codesys import run as crun
        folder = tmpdir(self)

        def runner(line):
            w.run(folder, script="export_canworks_xml.py", report="export_report.txt")
        return crun.export_project(proj.path, device=device, exe="CODESYS.exe", profile="p", folder=folder,
                                   runner=runner)

    def test_virtual_plant(self):
        from . import fake_codesys
        w = fake_codesys.World()
        path = os.path.join(tmpdir(self), "vp.project")
        proj = w.project_with_plc(path)
        plant = os.path.join(PLANT_DIR, "canworks.json")
        with open(plant, encoding="utf-8") as f:
            original = json.load(f)
        report = self.build(w, proj, original, plant)
        self.assertTrue(report.startswith("result: ok"), report)
        devices, xml = self.export(w, proj)
        self.assertEqual(devices, [{"name": "PLC", "buses": ["CANbus", "CANbus_2", "CANbus_3"], "nodes": 5,
                                    "active": False}])
        res = run(xml)
        expected = expected_from_example()
        for net in expected:
            for n in net["nodes"]:
                if n["name"] in ("conveyor", "cell"):
                    n["heartbeat_ms"] = {"conveyor": 50, "cell": 200}[n["name"]]  # set since the fix
        cell = node({"networks": expected}, "cell")
        # The stand-in maps what the DCF configures (CODESYS also kept the EDS's second entries).
        pdo(cell, "tx_pdos", 3)["entries"].pop()
        pdo(cell, "tx_pdos", 5)["entries"].pop()
        self.assertEqual(comparable(res.cfg["networks"]), comparable(expected))
        self.assertEqual(res.cfg["codesys"], {"device": "PLC"})
        # Back into the project: every device is up to date.
        folder = tmpdir(self)
        for name, src in res.eds_files.items():
            shutil.copy(src, os.path.join(folder, name))
        cfg_path = os.path.join(folder, "canworks.json")
        with open(cfg_path, "w", encoding="utf-8") as f:
            json.dump(res.cfg, f)
        start = len(w.log)
        report = self.build(w, proj, res.cfg, cfg_path)
        self.assertTrue(report.startswith("result: ok"), report)
        self.assertEqual([e for e in w.log[start:] if e[0] in ("set", "add", "remove", "import")], [])
        for name in ("rtd", "dio", "new_io", "conveyor", "cell"):
            self.assertRegex(report, r"current  network \w+ node \d+ \(%s\): up to date" % name)

    def test_several_devices_listed(self):
        from . import fake_codesys
        w = fake_codesys.World()
        proj = w.project_with_plc(os.path.join(tmpdir(self), "two.project"))
        bridge = os.path.join(REPO, "examples", "modbus-bridge", "canworks.json")
        with open(bridge, encoding="utf-8") as f:
            cfg = json.load(f)
        self.build(w, proj, cfg, bridge)
        proj.add("HMI", 4096, "0000 0004", "3.5.22.40")
        hmi = proj.find("HMI")[0]
        del cfg["bridge"]
        cfg["codesys"] = {"device": "HMI"}
        self.build(w, proj, cfg, bridge)
        devices, xml = self.export(w, proj)
        self.assertEqual([d["name"] for d in devices], ["PLC", "HMI"])
        self.assertIsNone(xml)
        devices, xml = self.export(w, proj, device="HMI")
        self.assertEqual(x.choices(x.read(xml))[0]["name"], "HMI")
        self.assertTrue(hmi.find("CANbus"))


class CommandLine(unittest.TestCase):
    def deploy(self, *argv):
        import contextlib
        import io
        from canworks import cli
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_xml_file(self):
        folder = os.path.join(tmpdir(self), "line2")
        xml = os.path.join(tmpdir(self), "line2.xml")
        with open(xml, "w", encoding="utf-8") as f:
            f.write(xml_text(PLANT_XML))
        code, out, err = self.deploy("--from-codesys", xml, "--out", folder, "--eds-dir", PLANT_DIR)
        self.assertEqual(code, 0, err)
        self.assertIn("node     io/rtd (node 5): EDS from the library, rtd8.eds", out)
        self.assertEqual(sorted(os.listdir(folder)), ["canworks.json", "cell.eds", "conveyor.eds", "dio16.eds",
                                                     "rtd8.eds"])
        code, _, err = self.deploy("--from-codesys", xml, "--out", folder, "--eds-dir", PLANT_DIR)
        self.assertEqual(code, 1)
        self.assertIn("exists already; give --force", err)
        code, _, err = self.deploy("--config", os.path.join(folder, "canworks.json"), "--check")
        self.assertEqual(code, 0, err)

    def test_missing_eds_writes_nothing(self):
        folder = os.path.join(tmpdir(self), "line2")
        xml = os.path.join(tmpdir(self), "line2.xml")
        with open(xml, "w", encoding="utf-8") as f:
            f.write(xml_text(PLANT_XML))
        code, out, err = self.deploy("--from-codesys", xml, "--out", folder, "--eds-dir", tmpdir(self))
        self.assertEqual(code, 1)
        self.assertIn("no EDS for io/rtd (node 5)", err)
        self.assertFalse(os.path.exists(os.path.join(folder, "canworks.json")))

    def test_several_devices_need_a_choice(self):
        text = xml_text(PLANT_XML)
        two = in_device(text, "PLC")
        start = two.index("<configurations>") + len("<configurations>")
        end = two.rindex("</configurations>")
        two = two[:end] + in_device(text, "HMI")[start:in_device(text, "HMI").rindex("</configurations>")] + two[end:]
        xml = os.path.join(tmpdir(self), "two.xml")
        with open(xml, "w", encoding="utf-8") as f:
            f.write(two)
        folder = os.path.join(tmpdir(self), "out")
        code, _, err = self.deploy("--from-codesys", xml, "--out", folder, "--eds-dir", PLANT_DIR)
        self.assertEqual(code, 1)
        self.assertIn("has 2 devices with a CANopen Manager; name one with --codesys-plc NAME", err)
        self.assertIn("  HMI: CANbus, CANbus_2, CANbus_3, 5 nodes", err)
        code, _, err = self.deploy("--from-codesys", xml, "--out", folder, "--eds-dir", PLANT_DIR,
                                   "--codesys-plc", "HMI")
        self.assertEqual(code, 0, err)

    def test_project_without_codesys(self):
        from unittest import mock
        from canworks.codesys import run as crun
        with mock.patch.object(crun, "find_codesys", return_value=None):
            code, _, err = self.deploy("--from-codesys", "line2.project", "--out", tmpdir(self))
        self.assertEqual(code, 1)
        self.assertIn("CODESYS is not installed on this PC: export the project in CODESYS", err)
