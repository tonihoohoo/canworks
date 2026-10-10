"""PDO links in the deploy tool's exports and checks (canopen-pdo-links,
canopen-dbc-export "Linked PDOs in the DBC", canopen-network-docs "PDO links
in the document", canopen-device-simulator "Linked PDOs between simulated
devices", canopen-deploy "Link checks before upload"), on the shared link
fixture (test/fixtures/config/cases-links.json)."""

import os
import unittest

from canworks import contract, dbcexport, docexport, docwriter, simfile

from .test_contract import FIXTURES, load_cases, patched

EDS_DIR = os.path.join(FIXTURES, "eds")
PATH = os.path.join(EDS_DIR, "canworks.json")


def base():
    return load_cases("cases-links.json")["base"]


def two_consumers():
    # Node 21 as a second consumer, with the same module as node 20.
    return patched(base(), [["set", "nodes/2/eds", "link-io.eds"],
                            ["set", "links/0/to/1", {"node": 21, "rpdo": 1, "mapping": "device"}]])


class Checks(unittest.TestCase):
    def test_base_and_two_consumers_accepted(self):
        for cfg in (base(), two_consumers()):
            r = contract.check_config(cfg, PATH)
            self.assertEqual(r.errors, [])

    def test_v2_network_links(self):
        cfg = {"schema_version": 2, "networks": [dict(name="io", **{k: v for k, v in base().items()
                                                                    if k != "schema_version"})]}
        self.assertEqual(contract.check_config(cfg, PATH).errors, [])
        cfg["networks"][0]["links"][0]["to"][0]["entries"].pop()
        errors = "\n".join(contract.check_config(cfg, PATH).errors)
        self.assertIn("networks[0]: link stick_to_valves: node 20 (valves) RPDO 2 maps 16 bits", errors)

    def test_links_on_a_plain_network(self):
        cfg = {"schema_version": 2, "networks": [
            {"name": "plain", "protocol": "none", "adapter": {"type": "socketcan", "interface": "vcan0",
                                                              "bitrate": 125000}, "links": []}]}
        errors = "\n".join(contract.check_config(cfg, PATH).errors)
        self.assertIn("networks[0]: field 'links' needs a CANopen master network; this is a plain CAN network", errors)


class Dbc(unittest.TestCase):
    def test_consumers_are_receivers(self):
        m = dbcexport.build(two_consumers(), PATH)
        msg = next(x for x in m.messages if x.name == "stick_TPDO1")
        self.assertEqual(msg.cob_id, 0x18A)
        first, second = msg.signals
        self.assertEqual(first.receivers, ["Master", "valves", "fixed"])
        # Node 20 skips the second position with a dummy entry.
        self.assertEqual(second.receivers, ["Master", "fixed"])
        self.assertIn("link stick_to_valves", msg.comment)
        self.assertIn("node 20 RPDO 2 writes 0x6411:1, dummy", msg.comment)
        self.assertIn("node 21 RPDO 1 writes 0x6411:1, 0x6411:2", msg.comment)
        self.assertIn("not used by the PLC", second.comment)
        self.assertEqual(len([x for x in m.messages if x.cob_id == 0x18A]), 1)


class Docs(unittest.TestCase):
    def test_links_table_and_consumer_sheet(self):
        model = docexport.build(base(), PATH)
        net = model["networks"][0]
        (link,) = net["links"]
        self.assertEqual((link["cob_id"], link["producer"], link["tpdo"], link["on_plc_stop"]), (0x18A, 10, 1, "keep"))
        self.assertEqual(link["plc_reads"], ["%IW100 (0x6401:1)"])
        self.assertTrue(link["consumers"][0]["watches_producer"])
        f = next(x for x in net["frames"] if x["cob_id"] == 0x18A)
        self.assertIn("valves", f["consumers"])
        valves = next(n for n in net["nodes"] if n["node_id"] == 20)
        rpdo = next(p for p in valves["pdos"] if p["kind"] == "RPDO" and p["number"] == 2)
        self.assertEqual([(e["index"], e["bit"], e["length"], e["dummy"]) for e in rpdo["entries"]],
                         [(0x6411, 0, 16, False), (0x0003, 16, 16, True)])
        self.assertIn("node 10 TPDO 1", rpdo["entries"][0]["link_from"])
        html = docwriter.write(model)
        self.assertIn("PDO links", html)

    def test_bus_load_unchanged(self):
        without = patched(base(), [["delete", "links"], ["delete", "nodes/1/heartbeat_watch"],
                                   ["set", "nodes/0/tx_pdos/0/entries/1/iec_location", "%IW101"]])
        a = docexport.build(base(), PATH)["networks"][0]["bus_load"]
        b = docexport.build(without, PATH)["networks"][0]["bus_load"]
        self.assertEqual((a["cyclic"], a["worst"]), (b["cyclic"], b["worst"]))

    def test_plc_does_not_read(self):
        cfg = patched(base(), [["delete", "nodes/0/tx_pdos/0/entries/0/iec_location"]])
        model = docexport.build(cfg, PATH)
        self.assertEqual(model["networks"][0]["links"][0]["plc_reads"], [])
        self.assertFalse([x for x in model["io"] if "%IW100" in x["location"]])


class Simulation(unittest.TestCase):
    def test_source_on_a_linked_object(self):
        cfg = base()
        sim = {"schema_version": 1, "nodes": {"20": {"sources": {"0x6411:1": {"constant": 1}}}}}
        r = simfile.check(sim, os.path.join(EDS_DIR, "simulation.json"), cfg, PATH)
        self.assertIn("0x6411:1 is written by link stick_to_valves (RPDO 2, from node 10 TPDO 1)", "\n".join(r.errors))
        sim = {"schema_version": 1, "nodes": {"20": {"sources": {"0x6401:1": {"expr": "[0x6411:1]"}}}}}
        self.assertEqual(simfile.check(sim, os.path.join(EDS_DIR, "simulation.json"), cfg, PATH).errors, [])


if __name__ == "__main__":
    unittest.main()
