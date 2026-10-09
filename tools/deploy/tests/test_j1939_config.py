"""J1939 networks in the PC tools beyond the shared fixtures
(test_contract.SharedFixtures.test_cases_j1939): the network list, the
gateway's words, located variable declarations, the location clash checks,
free locations and the version writers pick."""

import copy
import json
import os
import re
import shutil
import tempfile
import unittest

from canworks import clash, contract
from canworks.configurator import declare, layout, server

from .test_contract import FIXTURES, load_cases, patched

EDS_CONFIG = os.path.join(FIXTURES, "eds", "canworks.json")


def base():
    """CANopen network io (node 2, TPDO 0x4001 on %ID100) and J1939 network machine."""
    return copy.deepcopy(load_cases("cases-j1939.json")["base"])


def check(cfg):
    return contract.check_config(cfg, EDS_CONFIG)


class Networks(unittest.TestCase):
    def test_a_j1939_network_is_no_canopen_network(self):
        cfg = base()
        io, machine = contract.networks(cfg)
        self.assertEqual((io["role"], io["protocol"]), ("master", "canopen"))
        self.assertEqual((machine["role"], machine["protocol"]), ("j1939", "j1939"))
        self.assertEqual((machine["master"], machine["nodes"], machine["slave"]), ({}, [], {}))
        self.assertEqual(machine["j1939"]["ecu"]["address"], 128)
        self.assertEqual(len(contract.all_nodes(cfg)), 1)
        self.assertEqual(contract.eds_users(cfg), [cfg["networks"][0]["nodes"][0]])

    def test_parse_fills_in_defaults(self):
        j = contract.parse_j1939(base()["networks"][1])
        tx = j["tx"][0]
        self.assertEqual((tx["length"], tx["priority"], tx["destination"], tx["min_gap_ms"]), (8, 6, 255, 0))
        self.assertEqual(str(j["rx"][0]["signals"][0]["location"]), "%IW210")
        self.assertEqual(j["ecu"]["name"]["ecu_instance"], 0)
        self.assertEqual(contract.j1939_name_value(base()["networks"][1]["j1939"]["ecu"]["name"]),
                         0x80008200000004D2)  # as the plugin's J1939Name::value()

    def test_big_endian_bits(self):
        # Start bit 7, 16 bits: bytes 0 and 1, most significant byte first.
        self.assertEqual(sorted(contract.j1939_signal_bits(7, 16, True)), list(range(16)))
        self.assertEqual(contract.j1939_signal_bits(7, 16, True)[0], 8)

    def test_messages_have_paths(self):
        r = check(patched(base(), [["set", "networks/1/j1939/rx/0/signals/0/iec_location", "%IB10"]]))
        item = next(i for i in r.items if "does not fit location" in i["message"])
        self.assertEqual(item["paths"], ["networks[1].j1939.rx[0].signals[0].iec_location"])
        r = check(patched(base(), [["set", "networks/1/nodes", []]]))
        self.assertIn("networks[1].nodes", r.items[0]["paths"])

    def test_misplaced_keys_give_only_the_plugin_message(self):
        r = check(patched(base(), [["set", "networks/1/master", {"node_id": 1}]]))
        self.assertEqual(len(r.errors), 1, r.errors)

    def test_type_errors_in_the_plugin_words(self):
        r = check(patched(base(), [["set", "networks/1/j1939/rx/0/timeout_ms", "300"],
                                   ["set", "networks/1/j1939/tx/0/signals/0/byte_order", "middle"],
                                   ["set", "networks/1/j1939/tx/0/signals/1/valid_location", "%IX9.0"]]))
        text = "\n".join(r.errors)
        self.assertIn("networks[1]: j1939: rx[0]: field 'timeout_ms' must be a non-negative integer", text)
        self.assertIn("networks[1]: j1939: tx[0]: signal Setpoint: field 'byte_order' must be \"little\" or "
                      "\"big\", not \"middle\"", text)
        self.assertIn("networks[1]: j1939: tx[0]: signal Run: field 'valid_location' is only for received signals "
                      "(rx)", text)

    def test_default_tx_length_from_the_signals(self):
        # No length: 8 bytes, or as many as the signals need.
        r = check(patched(base(), [["set", "networks/1/j1939/tx/0/signals/1/start_bit", 100],
                                   ["set", "networks/1/j1939/tx/0/signals/1/length", 2],
                                   ["set", "networks/1/j1939/tx/0/signals/1/iec_location", "%QB222"]]))
        self.assertEqual(r.errors, [])
        self.assertEqual(contract.parse_j1939(patched(base(), [
            ["set", "networks/1/j1939/tx/0/signals/1/start_bit", 100]])["networks"][1])["tx"][0]["length"], 13)

    def test_j1939_object_in_a_version_1_file(self):
        cfg = load_cases()["base"]
        cfg = dict(cfg, j1939={"ecu": {"name": {}, "address": 1}})
        r = contract.check_config(cfg, EDS_CONFIG)
        self.assertIn("field 'j1939' needs schema_version 2", "\n".join(r.errors))
        self.assertFalse(any("unknown field 'j1939'" in w for w in r.warnings))


class Gateway(unittest.TestCase):
    def config(self):
        cfg = base()
        cfg["networks"].append({"name": "upper", "role": "slave",
                                "adapter": {"type": "socketcan", "interface": "vcan2", "bitrate": 250000},
                                "slave": {"node_id": 20, "eds": "openplc-gateway.eds"}})
        cfg["gateway"] = {"upper": "upper", "routes": [
            {"slave": {"index": "0x2101", "subindex": 1},
             "field": {"network": "machine", "node": 2, "index": "0x4001", "subindex": 0}}]}
        return cfg

    def test_j1939_network_as_a_field_end(self):
        r = check(self.config())
        self.assertIn('gateway: routes[0]: field: network "machine" is a J1939 network; a route\'s field end is on a '
                      'CANopen master network', "\n".join(r.errors))

    def test_j1939_network_as_the_upper_network(self):
        cfg = self.config()
        cfg["gateway"]["upper"] = "machine"
        r = check(cfg)
        self.assertIn('gateway: upper network "machine" must be a slave network ("role": "slave"); it is a J1939 '
                      'network', "\n".join(r.errors))

    def test_j1939_network_is_no_field_network(self):
        cfg = self.config()
        del cfg["networks"][0]
        self.assertEqual([n["name"] for n in contract.field_networks(cfg)], [])


class Declarations(unittest.TestCase):
    def test_spec_example(self):
        # Spec scenario "Declaration with scaling".
        cfg = patched(base(), [["set", "networks/1/j1939/rx/0/signals/0/iec_location", "%IW200"]])
        decls = declare.declarations(cfg, lambda *a: None, {})
        block = re.sub(r" +", " ", declare.st_block(decls))  # names are padded to one width
        self.assertIn(" machine_Pressure AT %IW200 : UINT; (* x 0.1 + 0 bar *)\n", block)

    def test_names_types_and_comments(self):
        decls = {d["name"]: d for d in declare.declarations(base(), lambda *a: None, {})}
        self.assertEqual(decls["machine_Temp"]["type"], "SINT")
        self.assertEqual(decls["machine_Temp"]["comment"], "x 1 + 0")
        self.assertEqual(decls["machine_Setpoint"]["type"], "UINT")
        self.assertEqual(decls["machine_Run"]["type"], "BOOL")
        self.assertEqual(decls["machine_ecu_state"]["location"], "%IB200")
        self.assertEqual(decls["machine_ecu_address"]["type"], "USINT")
        self.assertEqual(decls["machine_Pressures_ok"]["location"], "%IX202.0")
        self.assertEqual(decls["machine_Pressure_valid"]["path"],
                         "networks[1].j1939.rx[0].signals[0].valid_location")
        self.assertEqual(decls["machine_Pressure"]["kind"], "j1939")
        self.assertIn("PGN 65280 (Pressures) Pressure", decls["machine_Pressure"]["description"])

    def test_sizes_and_sign(self):
        cfg = base()
        sigs = cfg["networks"][1]["j1939"]["rx"][0]["signals"]
        sigs[:] = [{"name": "a b", "start_bit": 0, "length": 32, "signed": True, "iec_location": "%ID220"},
                   {"name": "c", "start_bit": 32, "length": 20, "iec_location": "%ID221"},
                   {"name": "d", "start_bit": 64, "length": 64, "signed": True, "offset": -40.5, "scale": 2,
                    "iec_location": "%IL220"}]
        decls = {d["name"]: d for d in declare.declarations(cfg, lambda *a: None, {})}
        self.assertEqual(decls["machine_a_b"]["type"], "DINT")
        self.assertEqual(decls["machine_c"]["type"], "UDINT")
        self.assertEqual(decls["machine_d"]["type"], "LINT")
        self.assertEqual(decls["machine_d"]["comment"], "x 2 + -40.5")

    def test_after_canopen_in_a_program(self):
        decls = declare.program_order(declare.declarations(base(), lambda *a: None, {}))
        kinds = [d["kind"] for d in decls]
        self.assertEqual(kinds[-1], "j1939")
        self.assertLess(max(i for i, k in enumerate(kinds) if k != "j1939"), kinds.index("j1939"))


class Clash(unittest.TestCase):
    def test_signal_and_canopen_pdo_on_one_location(self):
        # Spec scenario "Clash with a CANopen PDO".
        cfg = patched(base(), [["set", "networks/1/j1939/rx/0/signals/0/iec_location", "%ID100"],
                               ["set", "networks/1/j1939/rx/0/signals/0/length", 32]])
        r = check(cfg)
        item = next(i for i in r.items if "both map to %ID100" in i["message"])
        self.assertEqual(item["paths"], ["networks[0].nodes[0].tx_pdos[0].entries[0].iec_location",
                                         "networks[1].j1939.rx[0].signals[0].iec_location"])

    def test_every_j1939_location_is_named(self):
        whos = [u[1] for u in contract.location_uses(contract.networks(base())[1])]
        self.assertEqual(whos, ["ECU state", "ECU address", "PGN 65280 status_location", "PGN 65280 signal Pressure",
                                "PGN 65280 signal Pressure valid_location", "PGN 65280 signal Temp",
                                "PGN 65281 signal Setpoint", "PGN 65281 signal Run"])

    def test_valid_and_status_locations(self):
        cfg = patched(base(), [["set", "networks/1/j1939/rx/0/signals/0/valid_location", "%IX202.0"]])
        self.assertIn("networks[1] (machine) PGN 65280 status_location and networks[1] (machine) PGN 65280 signal "
                      "Pressure valid_location both map to %IX202.0", "\n".join(check(cfg).errors))

    def test_other_plugin_writes_the_ecu_address(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp)
        os.mkdir(os.path.join(tmp, "conf"))
        with open(os.path.join(tmp, "conf", "canworks.json"), "w", encoding="utf-8") as f:
            json.dump(base(), f)
        with open(os.path.join(tmp, "conf", "modbus_master.json"), "w", encoding="utf-8") as f:
            json.dump({"devices": [{"iec_location": "%IB201", "len": 1},
                                   {"iec_location": "%IX202.1", "len": 1}]}, f)
        uses, problems = clash.bundle_uses(tmp)
        self.assertEqual(problems, [])
        errors, _ = clash.check(uses)
        text = "\n".join(errors)
        self.assertIn("networks[1].j1939.ecu.address_location", text)
        self.assertIn("networks[1].j1939.rx[0].signals[0].valid_location", text)

    def test_free_locations_skip_j1939(self):
        used = layout.taken(base(), [])
        for key in (("I", "B", 200), ("I", "B", 201), ("I", "X", 202 * 8), ("I", "W", 210), ("Q", "X", 202 * 8)):
            self.assertIn(key, used)
        self.assertEqual(layout.suggest("I", "B", used, 200), "%IB202")


class Writers(unittest.TestCase):
    def test_only_a_j1939_network_stays_version_2(self):
        # Spec scenario "Only a J1939 network".
        cfg = patched(base(), [["delete", "networks/0"]])
        cfg["networks"][0]["name"] = "vcan1"  # even named after its interface
        out = server.lowest_version(cfg)
        self.assertEqual(out["schema_version"], 2)
        self.assertEqual(out["networks"][0]["protocol"], "j1939")
        self.assertTrue(contract.has_j1939(out))
        self.assertFalse(contract.has_j1939(load_cases()["base"]))


if __name__ == "__main__":
    unittest.main()
