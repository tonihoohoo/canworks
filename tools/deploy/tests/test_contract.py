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


if __name__ == "__main__":
    unittest.main()
