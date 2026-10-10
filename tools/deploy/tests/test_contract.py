"""The shared config fixtures (test/fixtures/config/cases.json): the deploy
tool must reach the plugin's verdict, with the same messages, and the JSON
Schema must give the stated verdict."""

import copy
import filecmp
import json
import os
import unittest

import jsonschema

from canworks import contract

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
FIXTURES = os.path.join(REPO, "test", "fixtures")


def patched(base, patch):
    cfg = copy.deepcopy(base)
    for op in patch:
        kind, path = op[0], op[1].split("/")
        parent = cfg
        for part in path[:-1]:
            parent = parent[int(part)] if isinstance(parent, list) else parent[part]
        last = path[-1]
        if isinstance(parent, list):
            last = int(last)
        if kind == "delete":
            del parent[last]
        elif isinstance(parent, list) and last == len(parent):
            parent.append(op[2])
        else:
            parent[last] = op[2]
    return cfg


def load_cases(name="cases.json"):
    with open(os.path.join(FIXTURES, "config", name), encoding="utf-8") as f:
        return json.load(f)


class SharedFixtures(unittest.TestCase):
    def test_cases(self):
        self.run_cases(load_cases(), contract.schema(), 20)

    def test_cases_v2(self):
        # Several networks (test/fixtures/config/cases-v2.json).
        self.run_cases(load_cases("cases-v2.json"), contract.schema(2), 15)

    def test_cases_links(self):
        # PDO links and heartbeat watch (test/fixtures/config/cases-links.json).
        self.run_cases(load_cases("cases-links.json"), contract.schema(), 30)

    def test_cases_j1939(self):
        # J1939 networks (test/fixtures/config/cases-j1939.json).
        self.run_cases(load_cases("cases-j1939.json"), contract.schema(2), 30)

    def test_cases_bridge(self):
        # Modbus bridge configs (test/fixtures/config/cases-bridge.json).
        self.run_cases(load_cases("cases-bridge.json"), contract.schema(2), 30)

    def run_cases(self, doc, schema, at_least):
        validator = jsonschema.Draft202012Validator(schema)
        self.assertGreater(len(doc["cases"]), at_least)
        for case in doc["cases"]:
            with self.subTest(case["name"]):
                cfg = patched(doc["base"], case["patch"])
                schema_valid = validator.is_valid(cfg)
                self.assertEqual(schema_valid, case["schema"] == "valid", "schema verdict")
                r = contract.check_config(cfg, os.path.join(FIXTURES, "eds", "canworks.json"))
                text = "\n".join(r.errors)
                self.assertEqual(r.ok, case["verdict"] == "accept", text)
                for m in case.get("messages", []) + case.get("tool_messages", []):
                    self.assertIn(m, text)
                for m in case.get("warnings", []):
                    self.assertIn(m, "\n".join(r.warnings))
                if case["verdict"] == "accept":
                    self.assertTrue(schema_valid, "the plugin accepts it, so the schema must too")


class Examples(unittest.TestCase):
    def test_schema_copy_matches(self):
        # The package ships a copy of schema/; it must not drift.
        for name in ("canworks.v1.schema.json", "canworks.v2.schema.json"):
            self.assertTrue(filecmp.cmp(os.path.join(REPO, "schema", name),
                                        os.path.join(REPO, "tools", "deploy", "canworks", "schema",
                                                     name), shallow=False), name)

    def test_example_configs_validate(self):
        found = 0
        paths = []
        for d in sorted(os.listdir(os.path.join(REPO, "examples"))):
            # An editor project keeps it in canworks/; examples/j1939 is the config alone.
            inside = os.path.join(REPO, "examples", d, "canworks", "canworks.json")
            paths.append(inside if os.path.isfile(inside) else os.path.join(REPO, "examples", d, "canworks.json"))
        for root, _, files in os.walk(os.path.join(REPO, "config")):
            for name in files:
                # Other JSON files there are not configs: simulation.json follows
                # canworks-sim.v1 (test_simfile), *_eds.json are slave EDS descriptions.
                if name.endswith(".json") and name != "simulation.json" and not name.endswith("_eds.json"):
                    paths.append(os.path.join(root, name))
        for path in paths:
            with self.subTest(path):
                with open(path, encoding="utf-8") as f:
                    cfg = json.load(f)
                validator = jsonschema.Draft202012Validator(contract.schema(contract.version_of(cfg)))
                self.assertEqual(list(validator.iter_errors(cfg)), [], path)
                r = contract.check_config(cfg, path)
                self.assertTrue(r.ok, r.errors)
                self.assertEqual(r.warnings, [])
                found += 1
        self.assertGreater(found, 0)

    def test_node_id_out_of_range_names_path_and_range(self):
        cfg = patched(load_cases()["base"], [["set", "nodes/0/node_id", 200]])
        r = contract.check_config(cfg, "canworks.json", eds_dir=os.path.join(FIXTURES, "eds"))
        self.assertIn("canworks.json: nodes[0].node_id: node ID must be 1 to 127", "\n".join(r.errors))


class InterfaceNames(unittest.TestCase):
    def test_old_style_interface_checked(self):
        # The pre-contract top-level interface goes through the same check.
        cfg = patched(load_cases()["base"], [["delete", "adapter"], ["set", "interface", "vcan0 --up"],
                                             ["set", "bitrate", 125000]])
        r = contract.check_config(cfg, os.path.join(FIXTURES, "eds", "canworks.json"))
        self.assertIn('interface "vcan0 --up" must be 1-15 characters', "\n".join(r.errors))


class AutoCobIds(unittest.TestCase):
    def test_defaults_then_free_from_the_top(self):
        nodes = [{"node_id": 2, "tx_pdos": [{"number": 1, "cob_id": "auto"}],
                  "rx_pdos": [{"number": 5, "cob_id": "auto"}, {"number": 6, "cob_id": "auto"}]},
                 {"node_id": 3, "tx_pdos": [{"number": 5, "cob_id": 0x57D}], "rx_pdos": []}]
        cobs = contract.auto_cob_ids(nodes)
        self.assertEqual(cobs[(0, "tx_pdos", 0)], 0x182)
        self.assertEqual(cobs[(0, "rx_pdos", 0)], 0x57F)
        self.assertEqual(cobs[(0, "rx_pdos", 1)], 0x57E)

    def test_skips_predefined_sets(self):
        nodes = [{"node_id": 0x7F, "tx_pdos": [], "rx_pdos": [{"number": 5, "cob_id": "auto"}]}]
        # 0x57F is node 127's RPDO 4 (0x500 + 0x7F).
        self.assertEqual(contract.auto_cob_ids(nodes)[(0, "rx_pdos", 0)], 0x57E)


class SdoValues(unittest.TestCase):
    def test_encodings(self):
        self.assertEqual(contract.sdo_value(100, "UNSIGNED16"), (b"\x64\x00", None))
        self.assertEqual(contract.sdo_value(-2, "INTEGER8"), (b"\xfe", None))
        self.assertEqual(contract.sdo_value(1.5, "REAL32"), (b"\x00\x00\xc0\x3f", None))
        self.assertEqual(contract.sdo_value("0xDEADBEEF", "UNSIGNED32"), (b"\xef\xbe\xad\xde", None))
        self.assertEqual(contract.sdo_value(True, "BOOLEAN"), (b"\x01", None))
        self.assertEqual(contract.sdo_value("-0x8000000000000000", "INTEGER64")[1], None)

    def test_out_of_range(self):
        for value, type_name, problem in [(300, "UNSIGNED8", "does not fit UNSIGNED8"),
                                          ("-1", "UNSIGNED16", "does not fit UNSIGNED16"),
                                          (128, "INTEGER8", "does not fit INTEGER8"),
                                          (-129, "INTEGER8", "does not fit INTEGER8"),
                                          (2, "BOOLEAN", "does not fit BOOLEAN"),
                                          ("0x100000000", "UNSIGNED32", "does not fit UNSIGNED32"),
                                          (1.5, "UNSIGNED16", "is not an integer"),
                                          ("1", "REAL32", "must be a number")]:
            self.assertEqual(contract.sdo_value(value, type_name), (None, problem), (value, type_name))



class SdoOverrides(unittest.TestCase):
    """The startup SDO overlap warning covers the objects the dcfgen node
    options write, only when the node sets them."""

    def over(self, node, index, sub, value, nbytes=4):
        return contract.sdo_override(node, {"index": index, "subindex": sub}, value.to_bytes(nbytes, "little"))

    def test_dcfgen_node_options(self):
        node = {"time_cob_id": "0x100", "heartbeat_consumer": True, "restore_configuration": 1,
                "error_behavior": {"1": 2}}
        self.assertEqual(self.over(node, 0x1012, 0, 0x80000100), "time_cob_id")
        self.assertIsNone(self.over(node, 0x1012, 0, 0x100))
        self.assertEqual(self.over(node, 0x1016, 1, 0x000101F4), "heartbeat_consumer")
        self.assertEqual(self.over(node, 0x1011, 1, 0x64616F6C), "restore_configuration")
        self.assertEqual(self.over(node, 0x1029, 1, 0, 1), "error_behavior")
        self.assertIsNone(self.over(node, 0x1029, 1, 2, 1))

    def test_left_out_options_are_not_overridden(self):
        for index, sub in ((0x1011, 1), (0x1012, 0), (0x1016, 1), (0x1029, 1)):
            self.assertIsNone(self.over({}, index, sub, 1), hex(index))


class EmcyCobIds(unittest.TestCase):
    """emcy_cob_id and a startup SDO to 0x1014 (add-emcy-history): the
    plugin's checks and messages, the first failing one per node."""

    def config(self, emcy=None, sdo=None, second_emcy=None):
        cfg = load_cases()["base"]
        second = copy.deepcopy(cfg["nodes"][0])
        second.update(node_id=3, name="second", status_location="%IX10.1")
        second["tx_pdos"][0]["entries"][0]["iec_location"] = "%ID104"
        second["rx_pdos"][0]["entries"][0]["iec_location"] = "%QD104"
        cfg["nodes"].append(second)
        if emcy is not None:
            cfg["nodes"][0]["emcy_cob_id"] = emcy
        if second_emcy is not None:
            second["emcy_cob_id"] = second_emcy
        if sdo is not None:
            cfg["nodes"][0]["sdo"].append({"index": "0x1014", "subindex": 0, "type": "UNSIGNED32", "value": sdo})
        return cfg

    def check(self, cfg):
        return contract.check_config(cfg, "canworks.json", eds_dir=os.path.join(FIXTURES, "eds"))

    def emcy_errors(self, cfg):
        # The fixture EDS has no 0x1014, so a startup SDO to it fails the EDS check.
        return [e for e in self.check(cfg).errors if "index 0x1014, subindex 0: object is not defined" not in e]

    def error(self, cfg):
        r = self.check(cfg)
        self.assertEqual(len(r.errors), 1, r.errors)
        return r.errors[0], [i["paths"] for i in r.items if i["level"] == "error"][0]

    def test_accepted(self):
        validator = jsonschema.Draft202012Validator(contract.schema())
        for v in (None, "device", "eds", 197, "0xC5", "197", 0x6DF):
            cfg = self.config(v)
            with self.subTest(v):
                r = self.check(cfg)
                self.assertEqual(r.errors, [])
                self.assertEqual(r.warnings, [])
                self.assertTrue(validator.is_valid(cfg))

    def test_wrong_type(self):
        for v in ("dev", True, -5, [1], "0xZZ"):
            with self.subTest(v):
                msg, paths = self.error(self.config(v))
                self.assertEqual(msg, "canworks.json: nodes[0]: node 2 (pingpong): field 'emcy_cob_id' must be "
                                      "\"device\", \"eds\" or a COB-ID")
                self.assertEqual(paths, ["nodes[0].emcy_cob_id"])

    def test_bit_31(self):
        msg, _ = self.error(self.config(0x80000085))
        self.assertEqual(msg, "canworks.json: nodes[0]: node 2 (pingpong): emcy_cob_id 0x80000085 has bit 31 set "
                              "(EMCY not valid); give the COB-ID the device sends on")

    def test_not_11_bit(self):
        msg, _ = self.error(self.config("0x20000085"))
        self.assertTrue(msg.endswith("node 2 (pingpong): emcy_cob_id 0x20000085 is not an 11-bit CAN-ID (29-bit "
                                     "EMCY COB-IDs are not supported)"), msg)
        msg, _ = self.error(self.config(0x800))
        self.assertIn("emcy_cob_id 0x800 is not an 11-bit CAN-ID", msg)

    def test_restricted(self):
        msg, paths = self.error(self.config(1537))
        self.assertEqual(msg, "canworks.json: nodes[0]: node 2 (pingpong): emcy_cob_id 0x601 is a restricted "
                              "CAN-ID (CiA 301)")
        self.assertEqual(paths, ["nodes[0].emcy_cob_id"])
        for v in (0, 0x7F, 0x101, 0x180, 0x581, 0x5FF, 0x67F, 0x6E0, 0x6FF, 0x701):
            with self.subTest(hex(v)):
                self.assertIn("is a restricted CAN-ID", self.error(self.config(v))[0])
        for v in (0x181, 0x580, 0x680, 0x6DF):
            with self.subTest(hex(v)):
                self.assertNotIn("restricted", "\n".join(self.check(self.config(v)).errors))

    def test_clashes(self):
        for v, who in ((0x80, "SYNC"), (0x100, "TIME"), (0x81, "the master's EMCY"),
                       (0x83, "the EMCY of node 3 (second)"), ("0x183", "node 3 (second) TPDO 1"),
                       (0x182, "node 2 (pingpong) TPDO 1"), (0x203, "node 3 (second) RPDO 1")):
            with self.subTest(v):
                msg, _ = self.error(self.config(v))
                cob = contract._uint(v)
                self.assertTrue(msg.endswith("node 2 (pingpong): emcy_cob_id 0x%03X clashes with %s" % (cob, who)),
                                msg)

    def test_clash_with_the_masters_time_cob_id(self):
        cfg = self.config(0x190)
        cfg["master"]["time_cob_id"] = "0x40000190"
        self.assertIn("emcy_cob_id 0x190 clashes with TIME", self.error(cfg)[0])

    def test_clash_with_a_moved_emcy(self):
        cfg = self.config(0xC5, second_emcy=0xC5)
        r = self.check(cfg)
        self.assertEqual(r.errors, [
            "canworks.json: nodes[0]: node 2 (pingpong): emcy_cob_id 0x0C5 clashes with the EMCY of node 3 (second)",
            "canworks.json: nodes[1]: node 3 (second): emcy_cob_id 0x0C5 clashes with the EMCY of node 2 (pingpong)"])

    def test_auto_cob_id(self):
        cfg = self.config(0x57F)
        cfg["nodes"][1]["tx_pdos"][0].update(number=5, cob_id="auto")
        self.assertIn("emcy_cob_id 0x57F clashes with node 3 (second) TPDO 5", self.error(cfg)[0])

    def test_startup_sdo(self):
        msg, paths = self.error(self.config(sdo="0x183"))
        self.assertEqual(msg, "canworks.json: nodes[0]: node 2 (pingpong): EMCY COB-ID 0x183 from the startup SDO "
                              "to 0x1014 clashes with node 3 (second) TPDO 1")
        self.assertEqual(paths, ["nodes[0].sdo[1]"])
        self.assertIn("EMCY COB-ID 0x20000085 from the startup SDO to 0x1014 is not an 11-bit CAN-ID",
                      self.error(self.config(sdo=0x20000085))[0])
        # Bit 31: ignored, no COB-ID taken.
        self.assertEqual(self.emcy_errors(self.config(sdo=0x80000183)), [])
        self.assertEqual(self.emcy_errors(self.config(sdo=0xC5)), [])
        # A number in emcy_cob_id wins; "eds" and "device" do not.
        self.assertEqual(self.emcy_errors(self.config(0xC5, sdo="0x183")), [])
        self.assertIn("from the startup SDO", self.error(self.config("eds", sdo="0x183"))[0])

    def test_last_startup_sdo_counts(self):
        cfg = self.config(sdo="0x183")
        cfg["nodes"][0]["sdo"].append({"index": "0x1014", "subindex": 0, "type": "UNSIGNED32", "value": 0xC5})
        self.assertEqual(self.emcy_errors(cfg), [])
        cfg["nodes"][0]["sdo"][-1]["value"] = 0x800000C5  # bit 31: no COB-ID taken at all
        self.assertEqual(self.emcy_errors(cfg), [])

    def test_configured_value(self):
        self.assertEqual(contract.configured_emcy_cob_id({"emcy_cob_id": "0xC5"}), (0xC5, "emcy_cob_id", None))
        self.assertIsNone(contract.configured_emcy_cob_id({"emcy_cob_id": "device"}))
        sdo = [{"index": "0x1014", "subindex": 0, "type": "UNSIGNED32", "value": 0xC5}]
        self.assertEqual(contract.configured_emcy_cob_id({"emcy_cob_id": "eds", "sdo": sdo}),
                         (0xC5, "startup SDO", 0))

    def test_version_2(self):
        doc = load_cases("cases-v2.json")
        cfg = copy.deepcopy(doc["base"])
        node = cfg["networks"][0]["nodes"][0]
        node["emcy_cob_id"] = 1537
        r = contract.check_config(cfg, "canworks.json", eds_dir=os.path.join(FIXTURES, "eds"))
        self.assertIn("networks[0]: nodes[0]: node %d" % contract._uint(node["node_id"]), "\n".join(r.errors))
        self.assertIn("emcy_cob_id 0x601 is a restricted CAN-ID (CiA 301)", "\n".join(r.errors))
        node["emcy_cob_id"] = "eds"
        self.assertTrue(jsonschema.Draft202012Validator(contract.schema(2)).is_valid(cfg))


if __name__ == "__main__":
    unittest.main()
