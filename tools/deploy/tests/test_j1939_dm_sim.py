"""canworks-j1939-sim as a faulty ECU (add-j1939-diagnostics, task 6.2) on
python-can's virtual bus with a test clock: the scenario's "dtcs" with
from_s/to_s, DM1 every second and on change, DM2 answers, DM3/DM11 with ACK,
--refuse-clear with NACK, received DMs printed and logged. The vcan run is
in test/j1939/sim_vcan.sh."""

import contextlib
import io
import json
import os
import shutil
import tempfile
import threading
import time
import unittest

import can
import cantools

from canworks.j1939 import dm, sim

from .helpers import REPO
from .test_j1939_sim import DBC, channel, request

FAULTS = os.path.join(REPO, "examples", "j1939", "engine-faults.json")
FIXTURES = os.path.join(REPO, "test", "fixtures", "j1939-dm", "cases.json")
DM1_ID, DM2_ID, ACK_ID = 0x18FECA00, 0x18FECB00, 0x18E8FF00
REQ_TO_0 = 0x18EA0080  # a Request from 128 to 0
REQ_GLOBAL = 0x18EAFF80


class Clock:
    """A clock the test moves on."""

    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def code(spn, fmi, lamps=(), flash=None, from_s=0.0, to_s=None):
    return sim.DtcPlan(spn, fmi, lamps, flash, from_s, to_s)


class State(unittest.TestCase):
    def test_counts_and_previous(self):
        s = sim.DmState([code(520192, 3, ["amber"], None, 5, 20), code(520193, 1, ["red"], "fast", 10)])
        self.assertFalse(s.update(0))
        self.assertEqual(s.dm1(), bytes.fromhex("00FF00000000FFFF"))
        self.assertTrue(s.update(5))
        self.assertEqual(s.dm1(), bytes.fromhex("04FF00F0E301FFFF"))
        self.assertTrue(s.update(10))
        self.assertEqual(dm.parse_dm(s.dm1()).dtcs, [dm.Dtc(520192, 3, 1), dm.Dtc(520193, 1, 1)])
        self.assertTrue(s.update(20))
        self.assertEqual(s.previous, {(520192, 3): 1})
        self.assertEqual(dm.parse_dm(s.dm2()).dtcs, [dm.Dtc(520192, 3, 1)])
        s.clear(previous_only=True)  # DM3
        self.assertEqual(dm.parse_dm(s.dm2()).dtcs, [])
        self.assertEqual(s.oc[(520193, 1)], 1)

    def test_occurrences_and_dm11(self):
        s = sim.DmState([code(520192, 3)])
        s.update(0)
        s.plans[0].to_s = 1
        s.update(1)
        s.plans[0].from_s, s.plans[0].to_s = 2, None
        s.update(2)
        self.assertEqual(dm.parse_dm(s.dm1()).dtcs, [dm.Dtc(520192, 3, 2)])
        self.assertEqual(s.previous, {})  # active again: not previously active any more
        s.clear(previous_only=False)  # DM11: counts start again, active codes at 1
        self.assertEqual(s.oc, {(520192, 3): 1})

    def test_own_fixtures(self):
        """The plugin's own-DM1 byte fixtures, built by the simulator's rules."""
        with open(FIXTURES, encoding="utf-8") as f:
            cases = [c for c in json.load(f)["cases"] if c["kind"] == "own" and not c.get("lamps_output")]
        self.assertTrue(cases)
        for c in cases:
            with self.subTest(c["name"]):
                s = sim.DmState([code(a["spn"], a["fmi"], a["lamps"], a["flash"]) for a in c["active"]])
                s.update(0)
                s.oc = {(a["spn"], a["fmi"]): a["oc"] for a in c["active"]}
                self.assertEqual(s.dm1(), bytes.fromhex(c["data"].replace(" ", "")))


class Scenario(unittest.TestCase):
    def setUp(self):
        self.db = cantools.database.load_file(DBC)

    def test_example_scenario(self):
        sc = sim.load_scenario(FAULTS, self.db, "Engine")
        self.assertEqual([(c.spn, c.fmi, c.lamps, c.flash, c.from_s, c.to_s) for c in sc["dtcs"]],
                         [(520200, 0, ["amber"], None, 5.0, 20.0), (520201, 5, ["red"], "slow", 10.0, None)])
        self.assertIn("Pressures", sc["messages"])
        self.assertTrue(sim.plans(self.db, "Engine", sc))

    def test_without_dbc(self):
        sc = sim.load_scenario({"dtcs": []}, None, None)
        self.assertEqual(sc["dtcs"], [])
        self.assertIsNone(sim.load_scenario({}, self.db, "Engine")["dtcs"])
        with self.assertRaisesRegex(sim.SimError, "messages need --dbc and --node"):
            sim.load_scenario({"messages": {"Pressures": {}}, "dtcs": []}, None, None)

    def test_rejected(self):
        cases = [
            ({"dtcs": {}}, "scenario: dtcs: give a list of trouble codes"),
            ({"dtcs": [{"spn": 524288, "fmi": 3}]}, "dtcs[0].spn: give 0..524287"),
            ({"dtcs": [{"spn": 1, "fmi": 32}]}, "dtcs[0].fmi: give 0..31"),
            ({"dtcs": [{"spn": 1}]}, "dtcs[0].fmi: give 0..31"),
            ({"dtcs": [{"spn": 1, "fmi": 1}, {"spn": 1, "fmi": 1}]}, "dtcs[1]: SPN 1 FMI 1 is already in the list"),
            ({"dtcs": [{"spn": 1, "fmi": 1, "lamps": ["blue"]}]}, 'dtcs[0].lamps: give a list out of "mil"'),
            ({"dtcs": [{"spn": 1, "fmi": 1, "flash": "on"}]}, 'dtcs[0].flash: give "slow" or "fast"'),
            ({"dtcs": [{"spn": 1, "fmi": 1, "from_s": -1}]}, "dtcs[0].from_s: give seconds, 0 or more"),
            ({"dtcs": [{"spn": 1, "fmi": 1, "from_s": 5, "to_s": 5}]}, "dtcs[0].to_s: give seconds after from_s"),
            ({"dtcs": [{"spn": 1, "fmi": 1, "oc": 3}]}, "dtcs[0]: unknown key 'oc'"),
        ]
        for obj, message in cases:
            with self.subTest(message=message):
                with self.assertRaises(sim.SimError) as ctx:
                    sim.load_scenario(obj, self.db, "Engine")
                self.assertIn(message, str(ctx.exception))


class Bus(unittest.TestCase):
    def setUp(self):
        self.ch = channel()
        self.peer = can.Bus(interface="virtual", channel=self.ch)
        self.buses, self.sims = [self.peer], []
        self.clock = Clock()

    def tearDown(self):
        for s in self.sims:
            s.stop()
        for b in self.buses:
            b.shutdown()

    def sim(self, dtcs, refuse=False, address=0):
        bus = can.Bus(interface="virtual", channel=self.ch)
        self.buses.append(bus)
        events = []
        s = sim.Simulator(bus, address, sim.make_name(None, address=address), clock=self.clock, dtcs=dtcs,
                          refuse_clear=refuse, report=lambda event, text, **f: events.append((event, text, f)))
        s.events = events
        self.sims.append(s)
        s.start()
        self.assertTrue(s.wait_claimed(1))
        return s

    def frames(self, can_id, count=1, timeout=1.0):
        out, deadline = [], time.monotonic() + timeout
        while len(out) < count and time.monotonic() < deadline:
            m = self.peer.recv(max(0.0, deadline - time.monotonic()))
            if m is not None and m.arbitration_id == can_id:
                out.append(bytes(m.data))
        return out

    def drain(self):
        while self.peer.recv(0.05) is not None:
            pass

    def advance(self, to):
        self.clock.t = 1000.0 + to

    def send(self, can_id, data):
        self.peer.send(can.Message(arbitration_id=can_id, data=bytes(data)))

    def event(self, s, event, contains="", timeout=1.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            for e in list(s.events):
                if e[0] == event and contains in e[1]:
                    return e
            time.sleep(0.01)
        self.fail("no %s event with %r in %r" % (event, contains, [e[1] for e in s.events]))

    def test_codes_come_and_go(self):
        """Faulty ECU: no codes before 5 s, the code with amber from 5 s,
        none again from 20 s, every second."""
        self.sim([code(520192, 3, ["amber"], None, 5, 20)])
        self.assertEqual(self.frames(DM1_ID), [bytes.fromhex("00FF00000000FFFF")])
        self.assertEqual(self.frames(DM1_ID, timeout=0.2), [])  # the clock stands: no second DM1 yet
        self.advance(1.0)
        self.assertEqual(self.frames(DM1_ID), [bytes.fromhex("00FF00000000FFFF")])
        self.advance(5.0)  # the code goes active: sent at once
        self.assertEqual(self.frames(DM1_ID), [bytes.fromhex("04FF00F0E301FFFF")])
        self.advance(6.0)
        self.assertEqual(self.frames(DM1_ID), [bytes.fromhex("04FF00F0E301FFFF")])
        self.advance(20.0)
        self.assertEqual(self.frames(DM1_ID), [bytes.fromhex("00FF00000000FFFF")])

    def test_one_bam_at_a_time(self):
        """A DM1 of six codes and ComponentInfo (40 bytes) both go by BAM at
        the same tick: one transfer per address at a time, so ComponentInfo
        waits for the DM1's to end and is then sent, not dropped."""
        db = cantools.database.load_file(DBC)
        sc = sim.load_scenario({"messages": {"ComponentInfo": {"period_ms": 1000}}}, db, "Engine")
        bus = can.Bus(interface="virtual", channel=self.ch)
        self.buses.append(bus)
        s = sim.Simulator(bus, 0, sim.make_name(None, address=0), db, sim.plans(db, "Engine", sc),
                          clock=self.clock, dtcs=[code(520192 + i, 3) for i in range(6)])
        self.sims.append(s)
        s.start()
        self.assertTrue(s.wait_claimed(1))
        bams, deadline = [], time.monotonic() + 3.0
        while len(bams) < 2 and time.monotonic() < deadline:
            m = self.peer.recv(max(0.0, deadline - time.monotonic()))
            if m is not None and m.arbitration_id & 0xFFFFFF == 0xECFF00 and m.data[0] == 0x20:
                bams.append(int.from_bytes(m.data[5:8], "little"))
        self.assertEqual(sorted(bams), [dm.PGN_DM1, 65282])  # the clock stands: one each

    def test_requests_dm2_dm3_dm11(self):
        """PLC clears the simulator: ACK, and the next DM2 answer is empty."""
        s = self.sim([code(520192, 3, ["amber"], None, 0, 1), code(520193, 1, ["red"], "fast", 0)])
        self.advance(1.0)
        time.sleep(0.1)
        self.drain()
        self.send(REQ_TO_0, request(dm.PGN_DM2))
        self.assertEqual(self.frames(DM2_ID), [bytes.fromhex("10DF00F0E301FFFF")])  # red fast, 520192 previous
        self.send(REQ_TO_0, request(dm.PGN_DM3))
        self.assertEqual(self.frames(ACK_ID), [bytes([0, 0xFF, 0xFF, 0xFF, 0x80, 0xCC, 0xFE, 0x00])])
        e = self.event(s, "dm_clear", "DM3")
        self.assertEqual((e[2]["dm"], e[2]["from"], e[2]["result"]), ("DM3", 128, "ack"))
        self.send(REQ_TO_0, request(dm.PGN_DM2))
        self.assertEqual(self.frames(DM2_ID), [bytes.fromhex("10DF00000000FFFF")])
        self.send(REQ_TO_0, request(dm.PGN_DM11))
        self.assertEqual(self.frames(ACK_ID), [bytes([0, 0xFF, 0xFF, 0xFF, 0x80, 0xD3, 0xFE, 0x00])])
        self.send(REQ_GLOBAL, request(dm.PGN_DM1))
        self.assertEqual(dm.parse_dm(self.frames(DM1_ID)[0]).dtcs, [dm.Dtc(520193, 1, 1)])
        self.send(REQ_GLOBAL, request(dm.PGN_DM11))  # global: carried out, no ACK
        self.event(s, "dm_clear", "global, no ACK")
        self.assertEqual(self.frames(ACK_ID, timeout=0.2), [])

    def test_refuse_clear(self):
        s = self.sim([code(520192, 3)], refuse=True)
        self.send(REQ_TO_0, request(dm.PGN_DM11))
        self.assertEqual(self.frames(ACK_ID), [bytes([1, 0xFF, 0xFF, 0xFF, 0x80, 0xD3, 0xFE, 0x00])])
        e = self.event(s, "dm_clear", "refused")
        self.assertEqual(e[2]["result"], "nack")
        self.assertEqual(s.dm.oc, {(520192, 3): 1})

    def test_many_codes_by_bam(self):
        self.sim([code(520192 + k, 3) for k in range(5)])
        (cm,) = self.frames(0x18ECFF00)
        self.assertEqual((cm[0], cm[1] | cm[2] << 8, cm[5] | cm[6] << 8 | cm[7] << 16), (32, 22, dm.PGN_DM1))

    def test_received_dms_printed(self):
        s = self.sim(None)
        self.send(0x18FECA80, dm.build_dm(0x04, 0xFF, [dm.Dtc(520192, 3, 2)]))
        e = self.event(s, "dm", "DM1 from 128")
        self.assertEqual(e[1], "DM1 from 128: amber warning on; SPN 520192 FMI 3 (voltage above normal or shorted "
                               "high) OC 2")
        self.assertEqual(e[2], {"dm": "DM1", "source": 128, "lamps": 4, "flash": 255,
                                "dtcs": [{"spn": 520192, "fmi": 3, "oc": 2, "cm": False}]})
        self.send(0x18DFFF80, [0x3F, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF])
        self.assertIn("current data link stop", self.event(s, "dm", "DM13")[1])
        # Without dtcs the simulator does not answer DM requests: NACK as any other PGN.
        self.send(REQ_TO_0, request(dm.PGN_DM2))
        self.assertEqual(self.frames(ACK_ID)[0][0], 1)


class Command(unittest.TestCase):
    def setUp(self):
        self.ch = channel()
        self.peer = can.Bus(interface="virtual", channel=self.ch)
        self.dir = tempfile.mkdtemp()

    def tearDown(self):
        self.peer.shutdown()
        shutil.rmtree(self.dir)

    def run_main(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = sim.main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_dtcs_only_with_log(self):
        scenario = os.path.join(self.dir, "faults.json")
        with open(scenario, "w") as f:
            json.dump({"dtcs": [{"spn": 520192, "fmi": 3, "lamps": ["amber"]}]}, f)
        log = os.path.join(self.dir, "sim.jsonl")
        result = {}
        t = threading.Thread(target=lambda: result.update(r=self.run_main(
            ["--address", "0", "--scenario", scenario, "--adapter", "virtual:" + self.ch, "--log", log,
             "--duration", "0.8"])))
        t.start()
        dm1 = None
        deadline = time.monotonic() + 2
        while dm1 is None and time.monotonic() < deadline:
            m = self.peer.recv(0.5)
            if m is not None and m.arbitration_id == DM1_ID:
                dm1 = bytes(m.data)
        self.assertEqual(dm1, bytes.fromhex("04FF00F0E301FFFF"))
        self.peer.send(can.Message(arbitration_id=0x18FECA80, data=dm.build_dm(0, 0xFF, [])))
        self.peer.send(can.Message(arbitration_id=REQ_TO_0, data=request(dm.PGN_DM3)))
        t.join(5)
        code, out, err = result["r"]
        self.assertEqual((code, err), (0, ""))
        self.assertIn("ECU on virtual:%s: address 0" % self.ch, out)
        self.assertIn("  sends DM1 every second and on change, 1 trouble code in the scenario", out)
        self.assertIn("DM1 from 128: lamps off; no codes\n", out)
        self.assertIn("Stopped: sent 0 messages and ", out)
        with open(log) as f:
            records = [json.loads(line) for line in f]
        got = [r for r in records if r["event"] == "dm"]
        self.assertEqual([{k: r[k] for k in ("dm", "source", "lamps", "flash", "dtcs")} for r in got],
                         [{"dm": "DM1", "source": 128, "lamps": 0, "flash": 255, "dtcs": []}])
        self.assertIn("time", got[0])
        cleared = [r for r in records if r["event"] == "dm_clear"]
        self.assertEqual([{k: r[k] for k in ("dm", "from", "result")} for r in cleared],
                         [{"dm": "DM3", "from": 128, "result": "ack"}])

    def test_usage(self):
        a = ["--adapter", "virtual:" + self.ch]
        scenario = os.path.join(self.dir, "s.json")
        with open(scenario, "w") as f:
            json.dump({"dtcs": []}, f)
        for argv, message in [
            (["--scenario", scenario] + a, "give --node, or --address for a scenario with only trouble codes"),
            (["--dbc", DBC, "--node", "Engine", "--refuse-clear"] + a, "--refuse-clear needs a scenario with dtcs"),
        ]:
            with self.subTest(message=message):
                code, out, err = self.run_main(argv)
                self.assertEqual(code, 2)
                self.assertIn(message, err)


if __name__ == "__main__":
    unittest.main()
