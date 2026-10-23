"""J1939 networks in the PC tools beyond the shared fixtures
(test_contract.SharedFixtures.test_cases_j1939): the network list, the
gateway's words, located variable declarations, the location clash checks,
and free locations."""

import copy
import json
import os
import re
import unittest

from canworks import contract
from canworks.configurator import declare, layout, server

from .helpers import REPO
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
        item = next(i for i in r.items if "overlap in input bytes 100" in i["message"])
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

    def test_free_locations_skip_j1939(self):
        used = layout.taken(base(), [])
        for key in (("I", "B", 200), ("I", "B", 201), ("I", "X", 202 * 8), ("I", "b", 202), ("I", "B", 210),
                    ("I", "B", 211), ("Q", "X", 202 * 8)):
            self.assertIn(key, used)
        self.assertEqual(layout.suggest("I", "B", used, 200), "%IB203")


if __name__ == "__main__":
    unittest.main()


class CopyAsStCall(unittest.TestCase):
    """Copy as ST call on a J1939 rx or tx entry (j1939-pc-tools)."""

    def setUp(self):
        with open(os.path.join(REPO, "examples", "j1939", "canworks.json")) as f:
            self.cfg = json.load(f)

    def text(self, kind, index, network=0):
        return server.Session.j1939_st(None, self.cfg, network, kind, index)["text"]

    def test_received_pgn(self):
        st = self.text("rx", 0)
        self.assertIn("  rx_machine_Pressures : J1939_RECEIVE;\n", st)
        self.assertIn("  machine_Pressures_data : ARRAY[0..1784] OF BYTE;\n", st)
        call = ("rx_machine_Pressures(ENABLE := TRUE, NETWORK := 0 (* machine *), PGN := 65280, SOURCE := 0, "
                "FILTER_SOURCE := TRUE, RX_DATA := machine_Pressures_data);")
        self.assertEqual(st.count(call), 2)
        self.assertIn("WHILE rx_machine_Pressures.NEW DO\n", st)
        self.assertIn("  machine_Pressures_Pressure := J1939_GET_BITS(DATA := machine_Pressures_data, START_BIT := 0, "
                      "BIT_LENGTH := 16, SIGNED := FALSE); (* raw x 0.1 bar *)\n", st)
        self.assertIn("  machine_Pressures_Temp := J1939_GET_BITS(DATA := machine_Pressures_data, START_BIT := 16, "
                      "BIT_LENGTH := 8, SIGNED := TRUE); (* raw degC *)\n", st)
        self.assertIn("rq_machine_Pressures(EXECUTE := machine_Pressures_ask, NETWORK := 0 (* machine *), PGN := 65280, "
                      "DESTINATION := 0, DATA := machine_Pressures_answer);", st)

    def test_any_source_requests_globally(self):
        del self.cfg["networks"][0]["j1939"]["rx"][0]["source"]
        st = self.text("rx", 0)
        self.assertNotIn("FILTER_SOURCE", st)
        self.assertIn("DESTINATION := 255", st)

    def test_sent_pgn(self):
        st = self.text("tx", 1)
        self.assertIn("  tx_machine_Command : J1939_SEND;\n", st)
        self.assertIn("remove this tx entry, or set raw.program_override_protocol", st)
        self.assertIn("machine_Command_packed := J1939_SET_BITS(DATA := machine_Command_data, START_BIT := 0, "
                      "BIT_LENGTH := 8, VALUE := machine_Command_Mode);", st)
        self.assertIn("tx_machine_Command(EXECUTE := machine_Command_go, NETWORK := 0 (* machine *), PGN := 61184, "
                      "DESTINATION := 0, PRIORITY := 6, LENGTH := 8, DATA := machine_Command_data);", st)
        # A PDU2 PGN goes to every ECU; the length holds every signal, at least 8.
        sig = {"name": "Far", "start_bit": 100, "length": 16}
        self.cfg["networks"][0]["j1939"]["tx"][0]["signals"].append(sig)
        self.assertIn("PGN := 65281, DESTINATION := 255, PRIORITY := 6, LENGTH := 15,", self.text("tx", 0))

    def test_big_endian_signals_refused(self):
        # J1939_GET_BITS and J1939_SET_BITS are little-endian: no call for a
        # big-endian signal, a message naming it instead.
        for kind, index in (("rx", 0), ("tx", 1)):
            entry = self.cfg["networks"][0]["j1939"][kind][index]
            entry["signals"].append({"name": "Motorola", "start_bit": 39, "length": 16, "byte_order": "big"})
            st = self.text(kind, index)
            self.assertNotIn("_Motorola", st)
            self.assertIn("(* Motorola is big-endian; J1939_%s_BITS is little-endian only, so this call leaves it out. *)"
                          % ("GET" if kind == "rx" else "SET"), st)

    def test_no_entry(self):
        with self.assertRaises(server.ApiError):
            self.text("rx", 9)
        with self.assertRaises(server.ApiError):
            self.text("requests", 0)
