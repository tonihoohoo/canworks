"""The standard object dictionary of a node without an EDS and the identity
read of a heard node (name-nodes-and-standard-dictionary), with a fake client."""

import unittest

from canworks import identity, notes, parameters as P, standardod
from canworks.configurator import params

from .test_errorfield import FakeClient, u32


def device(node, extra=None):
    objs = {(node, 0x1018, 0): b"\x04", (node, 0x1018, 1): u32(0x360), (node, 0x1018, 2): u32(7),
            (node, 0x1018, 3): u32(0x10002), (node, 0x1018, 4): u32(0x1234), (node, 0x1000, 0): u32(0x20192),
            (node, 0x1008, 0): b"pump\0\0", (node, 0x1001, 0): b"\0", (node, 0x1017, 0): b"\x64\x00",
            (node, 0x1003, 0): b"\x01", (node, 0x1003, 1): u32(0x8130)}
    for n in range(2):  # TPDO 1 and 2
        objs.update({(node, 0x1800 + n, 0): b"\x02", (node, 0x1800 + n, 1): u32(0x180 + n * 0x100 + node),
                     (node, 0x1800 + n, 2): b"\xfe", (node, 0x1A00 + n, 0): b"\x01", (node, 0x1A00 + n, 1): u32(0x60410010)})
    for n in range(6):  # RPDO 1-6
        objs.update({(node, 0x1400 + n, 0): b"\x02", (node, 0x1400 + n, 1): u32(0x80000000),
                     (node, 0x1400 + n, 2): b"\xfe", (node, 0x1600 + n, 0): b"\x00"})
    objs.update(extra or {})
    return objs


class Dictionary(unittest.TestCase):
    def test_profiles(self):
        plain, _ = standardod.read(None)
        self.assertIsNotNone(plain.find(0x1017, 0))
        self.assertIsNone(plain.find(0x6040, 0))
        self.assertIsNone(notes.profile(plain))
        drive, _ = standardod.read(0x00020192)
        self.assertIsNotNone(drive.find(0x6040, 0))
        self.assertEqual(notes.profile(drive), 402)
        io, _ = standardod.read(0x191)
        self.assertIsNotNone(io.find(0x6000, 1))
        # Another profile: CiA 301 only.
        other, _ = standardod.read(0x196)
        self.assertIsNone(other.find(0x6000, 0))
        self.assertIsNone(other.find(0x6040, 0))

    def test_pdos_and_arrays(self):
        eds, _ = standardod.read(None)
        self.assertTrue(eds.has(0x1403) and not eds.has(0x1404))
        self.assertTrue(eds.has(0x1A03) and not eds.has(0x1A04))
        self.assertEqual(eds.object_types[0x1003], standardod.ARRAY)
        self.assertIsNotNone(eds.find(0x1003, 254))
        self.assertIsNotNone(eds.find(0x1600, 64))
        more, _ = standardod.read(None, rpdos=8)
        self.assertTrue(more.has(0x1407) and not more.has(0x1408))
        self.assertEqual(more.names[0x1407], "RPDO 8 communication parameter")

    def test_no_defaults_in_the_view(self):
        ctx = params.standard_context({"device_type": 0x20192}, 5)
        out = params.entries_json(ctx)
        self.assertTrue(out["standard"])
        self.assertEqual(out["profile"], 402)
        self.assertTrue(all(e["default_data"] is None and not e["default"] for e in out["entries"]))
        names = {(e["index"], e["subindex"]): e["name"] for e in out["entries"]}
        self.assertEqual(names[(0x1017, 0)], "Producer heartbeat time")
        with self.assertRaises(params.Refused):
            params.standard_context({"rpdos": 2}, 5)
        with self.assertRaises(params.Refused):
            params.standard_context({"device_type": "x"}, 5)

    def test_read_all(self):
        client = FakeClient(device(5))
        eds, _ = standardod.read(0x20192)
        reading, rpdos, tpdos = standardod.read_all(client, 5, eds)
        self.assertEqual((rpdos, tpdos), (6, 4))
        self.assertEqual(reading.values[(0x1017, 0)], b"\x64\x00")
        self.assertEqual(reading.values[(0x1003, 1)], u32(0x8130))
        # 0x1003 counts 1: sub-index 2 is not read; 0x1013 is lacking and read once.
        self.assertNotIn((5, 0x1003, 2), client.reads)
        self.assertEqual(reading.failed[(0x1013, 0)][0], standardod.NO_OBJECT)
        # TPDO 3 does not exist: its sub-indices past 0 are not read.
        self.assertIn((5, 0x1802, 0), client.reads)
        self.assertNotIn((5, 0x1802, 1), client.reads)
        # RPDO 5 and 6 found past the listed four, RPDO 7 not.
        self.assertIn((0x1405, 1), reading.values)
        self.assertIn((5, 0x1406, 0), client.reads)
        self.assertNotIn((5, 0x1407, 0), client.reads)

    def test_read_all_stops_on_silence(self):
        class Silent(FakeClient):
            def sdo_read(self, node, index, subindex, timeout_ms=1000):
                self.reads.append((node, index, subindex))
                return {"success": False, "abort_code": None, "error": "timeout"}
        client = Silent()
        reading, _, _ = standardod.read_all(client, 5, standardod.read(None)[0])
        self.assertIn("does not answer", reading.stopped)
        self.assertEqual(len(client.reads), P.SILENT_LIMIT)


class Identity(unittest.TestCase):
    def test_read(self):
        r = identity.read(FakeClient(device(5, {(5, 0x100A, 0): b"v1.2\x01"})), 5)
        self.assertEqual(r, {"node_id": 5, "answered": True, "vendor_id": 0x360, "product_code": 7,
                             "revision_number": 0x10002, "serial_number": 0x1234, "device_type": 0x20192,
                             "device_name": "pump", "software_version": "v1.2"})

    def test_no_answer(self):
        class Silent(FakeClient):
            def sdo_read(self, node, index, subindex, timeout_ms=1000):
                self.reads.append((node, index, subindex))
                return {"success": False, "error": "timeout"}
        client = Silent()
        self.assertEqual(identity.read(client, 5), {"node_id": 5, "answered": False})
        self.assertEqual(len(client.reads), 1)

    def test_text(self):
        self.assertEqual(identity.text(b" a\tb \0junk"), "a b")
        self.assertEqual(len(identity.text(b"x" * 300)), identity.MAX_TEXT)


if __name__ == "__main__":
    unittest.main()
