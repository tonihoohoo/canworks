"""Writing a configuration to a device, restore defaults and verify
(canopen-device-commissioning), on python-can's virtual bus against a fake
device built from the RTD module's EDS. No CAN hardware."""

import json
import os
import shutil
import struct
import tempfile
import time
import unittest

from openplc_canopen_deploy import commissioning as C
from openplc_canopen_deploy import dcfexport
from openplc_canopen_deploy import parameters as P

from .fake_canopen import FakeDevice
from .helpers import REPO
from .test_localbus import Base, cli

RTD = os.path.join(REPO, "config", "rtd-sensor")
IDENTITY = (0x00F0F0F0, 0x404, 0x00010003, 0x77)


def rtd_od(node=5):
    """(od, read-only keys) of the RTD module with its EDS defaults."""
    eds, _ = P.read_eds(os.path.join(RTD, "rtd8.eds"))
    od = P.reference_from_eds(eds, node)
    ro = {e.key for e in P.entries(eds) if e.access in ("ro", "const")}
    for e in P.entries(eds):
        if e.key not in od and e.data_type != P.DOMAIN:
            od[e.key] = bytes(max(1, (P._int_type(e.data_type) or (1, False))[0]))
    for sub in range(1, 5):
        od.pop((0x1018, sub), None)  # FakeDevice's identity
    return od, ro


class Rtd(Base):
    """A configured RTD module (node 5) and its config in a temp folder."""

    def setUp(self):
        super().setUp()
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir)
        for name in ("rtd8.eds",):
            shutil.copy(os.path.join(RTD, name), self.dir)
        with open(os.path.join(RTD, "canopen_config.json")) as f:
            self.cfg = json.load(f)
        self.config = os.path.join(self.dir, "canopen.json")
        self.save()

    def save(self):
        with open(self.config, "w") as f:
            json.dump(self.cfg, f)

    def fake(self, node=5, identity=IDENTITY, **kw):
        od, ro = rtd_od(node)
        od.update(kw.pop("od", {}))
        return self.device(node, od=od, ro=ro | set(kw.pop("ro", ())), identity=identity, nvm=True, **kw)

    def source(self, node=5):
        ctx = P.node_context(node, self.config)
        return C.config_source(ctx, node)

    def plan(self, client, src, node=5, **kw):
        live = P.read_entries(client, node, C.plan_keys(src))
        return C.build_plan(src, node, live, **kw)


class ConfigSource(Rtd):
    def test_writes_of_the_config(self):
        src = self.source()
        self.assertEqual(src.kind, "config")
        self.assertEqual(src.node_id, 5)
        self.assertEqual(src.identity, {"vendor_id": 0x00F0F0F0, "product_code": 0x404, "revision_number": 0x00010003})
        self.assertEqual(src.values[(0x1A00, 1)], struct.pack("<I", 0x71300110))
        self.assertEqual(src.values[(0x6110, 1)], struct.pack("<H", 30))
        self.assertEqual(src.values[(0x1800, 1)], struct.pack("<I", 0x185))  # the final value, switched on

    def test_store_and_restore_steps_are_left_out(self):
        node = self.cfg["nodes"][0]
        node.update(config_check=True, store_configuration=1, restore_configuration=1)
        self.save()
        src = self.source()
        self.assertNotIn((0x1010, 1), src.values)
        self.assertIn((0x1020, 1), src.values)  # the configuration stamp is kept
        reasons = {(s["index"], s["subindex"]): s["reason"] for s in src.skipped}
        self.assertIn("store_configuration", reasons[(0x1010, 1)])
        self.assertIn("restore_configuration", reasons[(0x1011, 1)])

    def test_consumer_heartbeat_warns(self):
        self.cfg["nodes"][0]["heartbeat_consumer"] = True
        self.save()
        src = self.source()
        if any(k[0] == 0x1016 for k in src.values):
            self.assertTrue(any("heartbeat" in w for w in src.warnings))


class Plan(Rtd):
    def test_pdo_order_and_only_differences(self):
        self.fake()
        c = self.client(allow_changes=True)
        plan = self.plan(c, self.source())
        self.assertIsNone(plan.refused)
        tpdo1 = [(s["index"], s["subindex"], s["role"]) for s in plan.steps if s["group"] == "TPDO1"]
        self.assertEqual(tpdo1, [(0x1800, 1, "off"), (0x1A00, 0, "clear"), (0x1A00, 1, "set"), (0x1A00, 2, "set"),
                                 (0x1A00, 3, "set"), (0x1A00, 4, "set"), (0x1A00, 0, "set"), (0x1800, 2, "set"),
                                 (0x1800, 1, "set")])
        # The startup SDOs come after the PDOs, the heartbeat before.
        order = [s["index"] for s in plan.steps]
        self.assertLess(order.index(0x1017), order.index(0x1800))
        self.assertGreater(order.index(0x6110), order.index(0x1A01))

    def test_configure_then_nothing_to_do(self):
        dev = self.fake(heartbeat_s=0.05, nmt_state=5)
        time.sleep(0.2)
        c = self.client(allow_changes=True)
        src = self.source()
        plan = self.plan(c, src)
        was = C.check_target(c, 5)
        self.assertTrue(was)
        res = C.configure(c, 5, plan, hold=True, was_operational=was)
        self.assertEqual(res["failed"], [])
        self.assertTrue(res["verified"], res["readback"])
        self.assertTrue(res["held"] and res["started"])
        self.assertEqual(dev.nmt_log[:1], [0x80])
        self.assertEqual(dev.nmt_log[-1], 0x01)
        self.assertEqual(dev.od[(0x1A00, 1)], struct.pack("<I", 0x71300110))
        self.assertEqual(dev.od[(0x6110, 1)], struct.pack("<H", 30))
        self.assertNotIn(1, dev.stored)
        again = self.plan(c, src)
        self.assertEqual(again.writes, [])

    def test_identity_and_node_id(self):
        self.fake(identity=(0x00F0F0F0, 0x999, 1, 1))
        c = self.client(allow_changes=True)
        plan = self.plan(c, self.source())
        self.assertIn("product code differs", plan.refused)
        with self.assertRaises(C.CommissioningError):
            C.configure(c, 5, plan)
        plan = self.plan(c, self.source(), ignore_identity=True)
        self.assertIsNone(plan.refused)
        self.fake(node=7)
        src = self.source()
        plan = self.plan(c, src, node=7)
        self.assertIn("the source is for node 5 and the device is node 7", plan.refused)

    def test_failed_write_leaves_the_pdo_off(self):
        dev = self.fake(ro={(0x1A00, 2)})
        c = self.client(allow_changes=True)
        plan = self.plan(c, self.source())
        res = C.configure(c, 5, plan, hold=False)
        self.assertEqual([(f["index"], f["subindex"]) for f in res["failed"]], [(0x1A00, 2)])
        skipped = [(s["index"], s["subindex"]) for s in res["skipped"] if "stays switched off" in s["reason"]]
        self.assertIn((0x1800, 1), skipped)
        self.assertEqual(struct.unpack("<I", dev.od[(0x1800, 1)])[0] & C.INVALID, C.INVALID)
        self.assertEqual(dev.od[(0x1A01, 1)], struct.pack("<I", 0x61500108))  # the next PDO is written
        self.assertFalse(res["verified"])

    def test_verify_after_power_cycle(self):
        dev = self.fake()
        c = self.client(allow_changes=True)
        plan = self.plan(c, self.source())
        C.configure(c, 5, plan, hold=False)
        self.assertEqual(C.verify(c, 5, plan)["differences"], [])
        dev.power_cycle()
        diffs = C.verify(c, 5, plan)["differences"]
        self.assertIn((0x1800, 2), [(d["index"], d["subindex"]) for d in diffs])
        # Stored, it survives.
        C.configure(c, 5, self.plan(c, self.source()), hold=False)
        P.store(c, 5, plan.source.eds)
        dev.power_cycle()
        self.assertEqual(C.verify(c, 5, plan)["differences"], [])

    def test_restore_defaults(self):
        dev = self.fake()
        c = self.client(allow_changes=True)
        C.configure(c, 5, self.plan(c, self.source()), hold=False)
        P.store(c, 5, self.source().eds)
        res = C.restore_defaults(c, 5, self.source().eds, reset=True)
        self.assertTrue(res["restored"] and res["reset"])
        self.assertEqual(dev.od[(0x1011, 1)], C.LOAD) if (0x1011, 1) in dev.od else None
        self.assertTrue(C.wait_ready(c, 5))
        self.assertEqual(dev.od[(0x1800, 2)], rtd_od()[0][(0x1800, 2)])

    def test_runtime_refuses_a_node_it_configures(self):
        class Runtime:
            info = {"local": False}

            def status(self):
                return {"nodes": [{"node_id": 5, "state": 5}]}

        with self.assertRaises(C.CommissioningError) as e:
            C.check_target(Runtime(), 5)
        self.assertIn("the master writes node 5's configuration at every boot", str(e.exception))


class DcfSource(Rtd):
    def export(self):
        files, _ = dcfexport.export(self.cfg, self.config)
        path = os.path.join(self.dir, "node5.dcf")
        with open(path, "w") as f:
            f.write(next(iter(files.values())))
        return path

    def test_exported_dcf_gives_the_same_device(self):
        path = self.export()
        with open(path, "rb") as f:
            src = C.dcf_source(f.read(), path, 5)
        self.assertEqual(src.node_id, 5)
        self.assertNotIn((0x1010, 1), src.values)
        dev = self.fake()
        c = self.client(allow_changes=True)
        plan = self.plan(c, src)
        self.assertIsNone(plan.refused)
        res = C.configure(c, 5, plan, hold=False)
        self.assertEqual(res["failed"], [])
        self.assertTrue(res["verified"], res["readback"])
        self.assertEqual(dev.od[(0x1A01, 2)], struct.pack("<I", 0x61500208))
        # The config node now finds the device as it wants it.
        self.assertEqual(self.plan(c, self.source()).writes, [])

    def test_backup_as_source(self):
        self.fake(od={(0x6110, 2): struct.pack("<H", 99)})
        c = self.client(allow_changes=True)
        ctx = P.node_context(5, self.config)
        reading = P.read_all(c, 5, ctx.eds)
        text, _ = P.build_backup(ctx.eds_text, ctx.eds, ctx.eds_name, reading, 125)
        src = C.dcf_source(text, "backup.dcf", 5)
        self.assertEqual(src.values[(0x6110, 2)], struct.pack("<H", 99))
        self.assertEqual(src.identity["serial_number"] if "serial_number" in src.identity else None, None)
        dev2 = self.fake(node=6)
        plan = self.plan(c, src, node=6)
        self.assertIn("the source is for node 5", plan.refused)
        del dev2


class Cli(Rtd):
    def test_configure_dry_run_then_write_and_store(self):
        dev = self.fake()
        base = ("--adapter", "virtual:" + self.ch, "--bitrate", "125")
        code, out, err = cli(*base, "configure", "5", "--config", self.config, "--from-node", "5", "--dry-run")
        self.assertEqual(code, 0, err)
        self.assertIn("off   0x1800 sub 1", out)
        self.assertIn("to write", out)
        self.assertEqual(dev.od[(0x1800, 2)], rtd_od()[0][(0x1800, 2)])
        code, out, err = cli(*base, "configure", "5", "--config", self.config, "--from-node", "5", "--yes")
        self.assertEqual(code, 1)
        self.assertIn("changes not allowed", err)
        code, out, err = cli(*base, "--allow-changes", "configure", "5", "--config", self.config, "--from-node",
                             "5", "--yes", "--store")
        self.assertEqual(code, 0, err)
        self.assertIn("verified", out)
        self.assertIn(1, dev.stored)
        code, out, err = cli(*base, "configure", "5", "--config", self.config, "--from-node", "5", "--verify-only")
        self.assertEqual(code, 0, err)
        self.assertIn("no difference", out)

    def test_store_skipped_after_a_failure(self):
        dev = self.fake(ro={(0x1A00, 2)})
        code, out, err = cli("--adapter", "virtual:" + self.ch, "--bitrate", "125", "--allow-changes", "configure",
                             "5", "--config", self.config, "--from-node", "5", "--yes", "--store", "--no-hold")
        self.assertEqual(code, 1)
        self.assertIn("store skipped", out)
        self.assertEqual(dev.stored, [])

    def test_verify_only_lists_differences(self):
        self.fake()
        code, out, err = cli("--adapter", "virtual:" + self.ch, "--bitrate", "125", "configure", "5", "--config",
                             self.config, "--from-node", "5", "--verify-only")
        self.assertEqual(code, 1)
        self.assertIn("0x1800 sub 2", out)

    def test_restore_defaults(self):
        dev = self.fake()
        code, out, err = cli("--adapter", "virtual:" + self.ch, "--bitrate", "125", "--allow-changes",
                             "restore-defaults", "5", "--config", self.config, "--reset", "--yes")
        self.assertEqual(code, 0, err)
        self.assertIn("reset", out)
        self.assertEqual(dev.nmt_log[-1], 0x81)


if __name__ == "__main__":
    unittest.main()


FIXED_IO = os.path.join(REPO, "test", "fixtures", "eds", "fixed-io.eds")


def fixed_io_od(node=5):
    eds, _ = P.read_eds(FIXED_IO)
    od = P.reference_from_eds(eds, node)
    od.update({(0x6000, 1): b"\x11", (0x6000, 2): b"\x22", (0x6200, 1): b"\x00", (0x6200, 2): b"\x00"})
    for sub in range(1, 5):
        od.pop((0x1018, sub), None)
    return od


class PdoTest(Base):
    def test_cli_sync_set_and_watch(self):
        dev = self.device(5, od=fixed_io_od(), pdo=True, nmt_state=127)
        code, out, err = cli("--adapter", "virtual:" + self.ch, "--bitrate", "250", "--allow-changes", "pdo-test",
                             "5", "--eds", FIXED_IO, "--start", "--sync", "50", "--set", "0x6200:1=0x0F",
                             "--duration", "1")
        self.assertEqual(code, 0, err)
        self.assertEqual(dev.od[(0x6200, 1)], b"\x0f")
        self.assertGreater(dev.syncs, 5)
        self.assertIn("TPDO1 0x185:", out)
        self.assertIn("17 (0x11)", out)
        self.assertIn("RPDO1 0x205:", out)
        self.assertIn("SYNC every 50 ms", out)

    def test_needs_allow_changes_and_an_adapter(self):
        self.device(5, od=fixed_io_od(), pdo=True)
        code, out, err = cli("--adapter", "virtual:" + self.ch, "--bitrate", "250", "pdo-test", "5", "--eds",
                             FIXED_IO, "--duration", "0.2")
        self.assertEqual(code, 1)
        self.assertIn("changes not allowed", err)

    def test_event_rpdo_ops_and_another_master(self):
        from openplc_canopen_deploy import pdotest
        from .fake_canopen import Peer
        od = fixed_io_od()
        od[(0x1400, 2)] = b"\xff"  # event-driven
        dev = self.device(5, od=od, pdo=True, nmt_state=5)
        c = self.client(allow_changes=True)
        eds, _ = P.read_eds(FIXED_IO)
        lay = pdotest.from_device(c, 5, eds)
        self.assertEqual([p["name"] for p in lay["rpdos"]], ["RPDO1"])
        self.assertEqual(lay["rpdos"][0]["transmission"], 255)
        c.pdo_test_start(5, lay)
        r = c.pdo_test_set(5, 1, {"0x6200:2": "200"})
        self.assertTrue(r["event"])
        time.sleep(0.2)
        self.assertEqual(dev.od[(0x6200, 2)], bytes([200]))
        with self.assertRaises(Exception) as e:
            c.pdo_test_set(5, 1, {"0x6200:2": "300"})
        self.assertIn("out of range", str(e.exception))
        # Another master: the test ends.
        peer = Peer(self.ch)
        self.addCleanup(peer.close)
        peer.send(0x000, b"\x01\x00")
        time.sleep(0.3)
        st = c.pdo_test_status(5)
        self.assertFalse(st["running"])
        self.assertIn("another master", st["ended"])
        with self.assertRaises(Exception) as e:
            c.pdo_test_start(5, lay)
        self.assertIn("force needed", str(e.exception))
        c.pdo_test_start(5, lay, force=True)
        self.assertTrue(c.pdo_test_status(5)["running"])

    def test_close_ends_sync(self):
        dev = self.device(5, od=fixed_io_od(), pdo=True, nmt_state=5)
        c = self.client(allow_changes=True)
        c.sync_start(20)
        time.sleep(0.2)
        c.close()
        n = dev.syncs
        self.assertGreater(n, 3)
        time.sleep(0.2)
        self.assertEqual(dev.syncs, n)


class LoneSweep(Base):
    def setUp(self):
        super().setUp()
        from openplc_canopen_deploy.localbus import adapter as adapter_mod
        from openplc_canopen_deploy.localbus import parse
        from unittest import mock
        self.opened = []
        real = adapter_mod.open

        def opener(spec, bitrate, listen_only=False, options=None, **kw):
            self.opened.append((bitrate, listen_only))
            if bitrate != 250000:
                spec = parse("virtual:lone-elsewhere-%d" % len(self.opened))  # a wrong rate: nothing gets through
            return real(spec, bitrate, listen_only, options)

        p = mock.patch.object(adapter_mod, "open", opener)
        p.start()
        self.addCleanup(p.stop)

    def wait(self, c):
        res = c.detect_bitrate_status()
        end = time.monotonic() + 10
        while res["running"] and time.monotonic() < end:
            time.sleep(0.05)
            res = c.detect_bitrate_status()
        return res

    def test_lss_probe_finds_a_quiet_device(self):
        dev = self.device(None)
        c = self.client(allow_changes=True)
        c.detect_bitrate(per_rate_ms=200, lone_device=True, probe="lss")
        res = self.wait(c)
        self.assertEqual((res["verdict"], res["bitrate_kbit"]), ("detected", 250), res)
        self.assertTrue(res["lone_device"])
        # Normal mode at every rate tried, stopped at the device's.
        tried = [b for b, lo in self.opened[1:-1]]
        self.assertTrue(all(not lo for _, lo in self.opened[1:-1]))
        self.assertEqual(tried[-1], 250000)
        self.assertEqual(dev._lss_state, "waiting")

    def test_guards(self):
        c = self.client()
        with self.assertRaises(Exception) as e:
            c.detect_bitrate(lone_device=True)
        self.assertIn("changes not allowed", str(e.exception))
        self.device(5, heartbeat_s=0.05)
        self.device(7, heartbeat_s=0.05)
        c = self.client(allow_changes=True)
        time.sleep(0.3)
        with self.assertRaises(Exception) as e:
            c.detect_bitrate(lone_device=True)
        self.assertIn("more than one node", str(e.exception))
        with self.assertRaises(Exception) as e:
            c.request("detect_bitrate", probe="lss")
        self.assertIn("needs 'lone_device'", str(e.exception))

    def test_silent_hint_and_runtime_refusal(self):
        from openplc_canopen_deploy import diag
        c = self.client()
        c.detect_bitrate(rates=[500], per_rate_ms=100)
        res = self.wait(c)
        self.assertEqual(res["verdict"], "silent")
        self.assertIn("lone-device", res["hint"])
        with self.assertRaises(diag.DiagError) as e:
            diag.Client("x").detect_bitrate(lone_device=True)
        self.assertIn("only on a USB adapter", str(e.exception))

    def test_cli(self):
        self.device(5, heartbeat_s=0.05)
        code, out, err = cli("--adapter", "virtual:" + self.ch, "--bitrate", "500", "--allow-changes",
                             "detect-bitrate", "--lone-device", "--per-rate-ms", "200")
        self.assertEqual(code, 0, err)
        self.assertIn("250 kbit/s detected", out)
