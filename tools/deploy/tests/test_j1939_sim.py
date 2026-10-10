"""canworks-j1939-sim (add-j1939-ecu, task 5.3) on python-can's virtual bus:
address claim and contention, periodic messages with ramp values, request
answers and NACK, received messages decoded and logged, the transport
protocol (BAM and RTS/CTS) and the scenario file checks. The vcan run with
two simulators is test/j1939/sim_vcan.sh."""

import contextlib
import io
import itertools
import json
import os
import shutil
import statistics
import tempfile
import threading
import time
import unittest

import can
import cantools

from canworks.j1939 import sim

from .helpers import REPO

DBC = os.path.join(REPO, "examples", "j1939", "machine.dbc")
PLC_NAME = (1 << 63) | (130 << 40) | 1234  # the example config's PLC: arbitrary address capable, function 130

# A PDU1 message over 8 bytes from Engine (0) to the PLC (128): RTS/CTS.
DBC_PDU1 = """VERSION ""
NS_ :
BS_:
BU_: PLC Engine
BO_ 2565832704 Block: 16 Engine
 SG_ A : 0|32@1+ (1,0) [0|1000] "" PLC
 SG_ B : 96|32@1+ (1,0) [0|1000] "" PLC
BA_DEF_ BO_ "GenMsgCycleTime" INT 0 65535;
BA_DEF_DEF_ "GenMsgCycleTime" 0;
BA_ "GenMsgCycleTime" BO_ 2565832704 200;
"""

_n = itertools.count()


def channel():
    return "j1939-sim-test-%d" % next(_n)


class Base(unittest.TestCase):
    db = None

    @classmethod
    def setUpClass(cls):
        cls.db = cantools.database.load_file(DBC)

    def setUp(self):
        self.ch = channel()
        self.peer = can.Bus(interface="virtual", channel=self.ch)
        self.sims = []
        self.buses = [self.peer]

    def tearDown(self):
        for s in self.sims:
            s.stop()
        for b in self.buses:
            b.shutdown()

    def sim(self, node="Engine", address=0, name=None, keep=False, scenario=None, db=None, ramp=2.0, start=True):
        db = db or self.db
        bus = can.Bus(interface="virtual", channel=self.ch)
        self.buses.append(bus)
        events = []
        s = sim.Simulator(bus, address, sim.make_name(name, address=address), db,
                          sim.plans(db, node, scenario, ramp) if node else (), keep_address=keep,
                          report=lambda event, text, **f: events.append((event, text, f)))
        s.events = events
        self.sims.append(s)
        if start:
            s.start()
        return s

    def frames(self, count=1, match=lambda m: True, timeout=1.0):
        """The next `count` frames on the bus that `match`, with their arrival times
        (frame.timestamp is the send time)."""
        out = []
        deadline = time.monotonic() + timeout
        while len(out) < count and time.monotonic() < deadline:
            m = self.peer.recv(max(0.0, deadline - time.monotonic()))
            if m is not None and match(m):
                out.append((time.monotonic(), m))
        return out

    def send(self, can_id, data):
        self.peer.send(can.Message(arbitration_id=can_id, data=bytes(data)))

    def wait_event(self, s, event, contains="", timeout=1.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            for e in list(s.events):
                if e[0] == event and contains in e[1]:
                    return e
            time.sleep(0.01)
        self.fail("no %s event with %r in %r" % (event, contains, [e[1] for e in s.events]))


def tick_overshoot():
    """How much longer than sim.TICK_S a timed wait takes here (the most of 5)."""
    ev, late = threading.Event(), []
    for _ in range(5):
        t = time.monotonic()
        ev.wait(sim.TICK_S)
        late.append(time.monotonic() - t - sim.TICK_S)
    return max(0.0, *late)


def pf_is(pf, sa=None):
    return lambda m: (m.arbitration_id >> 16) & 0xFF == pf and (sa is None or m.arbitration_id & 0xFF == sa)


def request(pgn):
    return [pgn & 0xFF, (pgn >> 8) & 0xFF, (pgn >> 16) & 0xFF]


# ---------------------------------------------------------------------------


class Values(unittest.TestCase):
    def setUp(self):
        self.db = cantools.database.load_file(DBC)

    def sig(self, message, name):
        return self.db.get_message_by_name(message).get_signal_by_name(name)

    def test_pgn(self):
        self.assertEqual(sim.pgn_of(0x18FF0180), 65281)
        self.assertEqual(sim.pgn_of(0x18EF0080), 61184)  # PDU1: the destination is not part of the PGN

    def test_ramp_limits(self):
        self.assertEqual(sim.ramp_limits(self.sig("Pressures", "Pressure")), (0, 0xFAFF))
        self.assertEqual(sim.ramp_limits(self.sig("Pressures", "Temp")), (-125, 125))
        self.assertEqual(sim.ramp_limits(self.sig("Pressures", "PumpOn")), (0, 1))
        self.assertEqual(sim.ramp_limits(self.sig("ComponentInfo", "Serial")), (0, 0xFAFFFFFF))  # below "not available"

    def test_sources(self):
        r = sim.Ramp(0, 100, 1.0)
        self.assertEqual([r.raw(t) for t in (0, 0.25, 0.5, 0.999, 1.0)], [0, 25, 50, 100, 0])
        s = sim.Steps([1, 2, 3], 0.5)
        self.assertEqual([s.raw(t) for t in (0, 0.5, 1.0, 1.5)], [1, 2, 3, 1])
        self.assertEqual(sim.Steps([1, 2], 0.5, repeat=False).raw(5), 2)

    def test_default_address(self):
        self.assertEqual(sim.default_address(self.db, "Engine"), 0)
        self.assertEqual(sim.default_address(self.db, "PLC"), 128)
        with self.assertRaisesRegex(sim.SimError, r"node Pump is not in the DBC \(its nodes: PLC, Engine\)"):
            sim.node_messages(self.db, "Pump")

    def test_default_name(self):
        self.assertEqual(sim.make_name(address=5).value, 0x10005)
        self.assertEqual(sim.make_name(0x1234).value, 0x1234)

    def test_format(self):
        self.assertEqual([sim.fmt_value(v) for v in (500, 50.0, 0.30000000000000004, -3, 210554060.75)],
                         ["500", "50", "0.3", "-3", "210554060.75"])


class Scenario(unittest.TestCase):
    def setUp(self):
        self.db = cantools.database.load_file(DBC)

    def load(self, obj):
        return sim.plans(self.db, "Engine", sim.load_scenario(obj, self.db, "Engine"))

    def test_rejected(self):
        p = {"messages": {"Pressures": {"signals": {}}}}
        cases = [
            ({"speed": 1}, "scenario: unknown key 'speed' (allowed: ramp_period_s, messages, dtcs)"),
            ({"ramp_period_s": 0}, "scenario: ramp_period_s: give a number of seconds above 0"),
            ({"messages": {"Nope": {}}}, "scenario: messages: no message 'Nope' in the DBC (allowed: Pressures, "
                                         "ComponentInfo)"),
            ({"messages": {"Setpoints": {}}}, "scenario: messages.Setpoints: sent by PLC in the DBC, not by Engine"),
            ({"messages": {"Pressures": {"period_ms": -1}}}, "messages.Pressures.period_ms: give milliseconds, 0 or "
                                                            "more (0: only on request)"),
            ({"messages": {"Pressures": {"signals": {"Rpm": 1}}}}, "messages.Pressures.signals: no signal 'Rpm' in "
                                                                   "Pressures"),
            ({"messages": {"Pressures": {"signals": {"Temp": 200}}}}, "messages.Pressures.signals.Temp: 200 is above "
                                                                      "Temp's maximum 125"),
            ({"messages": {"Pressures": {"signals": {"Temp": "hot"}}}}, "signals.Temp: give a number, or an object"),
            ({"messages": {"Pressures": {"signals": {"Pressure": {"raw": 70000}}}}},
             "signals.Pressure.raw: raw value 70000 does not fit Pressure's 16 bits (0..65535)"),
            ({"messages": {"Pressures": {"signals": {"Pressure": {"raw": 1, "ramp": [0, 1]}}}}},
             "signals.Pressure: give exactly one of ramp, values or raw"),
            ({"messages": {"Pressures": {"signals": {"Level": {"ramp": [0]}}}}}, "signals.Level.ramp: give [from, to]"),
            ({"messages": {"Pressures": {"signals": {"Level": {"ramp": [0, 100], "period": 1}}}}},
             "signals.Level: unknown key 'period' (allowed: ramp, period_s)"),
            ({"messages": {"Pressures": {"signals": {"Level": {"values": []}}}}},
             "signals.Level.values: give a list of at least one value"),
            ({"messages": {"Pressures": {"signals": {"Level": {"values": [1], "repeat": "yes"}}}}},
             "signals.Level.repeat: give true or false"),
        ]
        self.assertTrue(self.load(p))
        for obj, message in cases:
            with self.subTest(message=message):
                with self.assertRaises(sim.SimError) as ctx:
                    self.load(obj)
                self.assertIn(message, str(ctx.exception))

    def test_file_errors(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d)
        path = os.path.join(d, "bad.json")
        with open(path, "w") as f:
            f.write("{")
        with self.assertRaisesRegex(sim.SimError, "bad.json: not valid JSON"):
            sim.load_scenario(path, self.db, "Engine")
        with self.assertRaisesRegex(sim.SimError, "cannot read scenario"):
            sim.load_scenario(os.path.join(d, "missing.json"), self.db, "Engine")

    def test_values(self):
        plans = self.load({"ramp_period_s": 4, "messages": {
            "Pressures": {"period_ms": 50, "signals": {
                "Pressure": 12.5, "PumpOn": {"raw": 3}, "Level": {"values": [10, 50], "step_s": 1},
                "Temp": {"ramp": [-20, 80], "period_s": 2}}},
            "ComponentInfo": {"period_ms": 0}}})
        p = {x.message.name: x for x in plans}
        self.assertEqual(p["Pressures"].period_s, 0.05)
        self.assertIsNone(p["ComponentInfo"].period_s)
        decode = p["Pressures"].message.decode
        self.assertEqual(decode(p["Pressures"].payload(0), decode_choices=False),
                         {"Pressure": 12.5, "Temp": -20, "Level": 10, "PumpOn": 3})
        self.assertEqual(decode(p["Pressures"].payload(1.0), decode_choices=False),
                         {"Pressure": 12.5, "Temp": 30, "Level": 50, "PumpOn": 3})
        self.assertEqual(p["ComponentInfo"].sources["Hours"].period, 4)  # the scenario's ramp period


class Claim(Base):
    def test_claim_then_messages(self):
        self.sim(ramp=2.0)
        (_, claim), = self.frames()
        self.assertEqual(claim.arbitration_id, 0x18EEFF00)
        self.assertEqual(bytes(claim.data), (0x10000).to_bytes(8, "little"))
        got = self.frames(5, pf_is(0xFF), timeout=1.5)
        self.assertEqual(len(got), 5)
        msg = self.db.get_message_by_name("Pressures")
        values = [msg.decode(bytes(m.data), decode_choices=False) for _, m in got]
        for _, m in got:
            self.assertEqual(m.arbitration_id, 0x18FF0000)
            self.assertEqual(bytes(m.data[5:]), b"\xff\xff\xff")  # unused bits are 1
        pressures = [v["Pressure"] for v in values]
        self.assertEqual(pressures, sorted(pressures))  # ramping up (period 2 s)
        self.assertLess(pressures[0], pressures[-1])
        for v in values:
            self.assertTrue(0 <= v["Pressure"] <= 6425.5 and -125 <= v["Temp"] <= 125 and v["PumpOn"] in (0, 1), v)
        gaps = [b[1].timestamp - a[1].timestamp for a, b in zip(got, got[1:])]
        # GenMsgCycleTime 100 ms. The median: a runner that stalls the sender
        # once makes one long gap (the scheduler does not burst to catch up).
        # Never faster than the cycle time; slower by at most what this
        # machine's timer adds to a scheduler tick (the macOS CI runners
        # wake a 20 ms wait after 60-170 ms; elsewhere it is ~0).
        median = statistics.median(gaps)
        self.assertGreaterEqual(median, 0.1 - 0.03)
        self.assertLessEqual(median, 0.1 + 0.03 + tick_overshoot(), gaps)

    def test_veto_wait(self):
        s = self.sim("PLC", 128)
        (_, claim), = self.frames()
        self.assertEqual(claim.arbitration_id, 0x18EEFF80)
        (_, first), = self.frames(1, pf_is(0xFF))
        self.assertGreaterEqual(first.timestamp - claim.timestamp, 0.24)  # 250 ms before sending from 128..247
        self.assertTrue(s.claimed)
        self.assertEqual(s.events[0][:2], ("claimed", "Claimed address 128 with NAME 0x0000000000010080"))

    def test_answers_request_for_claim(self):
        s = self.sim()
        self.assertTrue(s.wait_claimed(1))
        self.frames()
        self.send(0x18EAFFFE, request(60928))
        (_, m), = self.frames(1, pf_is(0xEE))
        self.assertEqual(m.arbitration_id, 0x18EEFF00)

    def test_contender_takes_address(self):
        plc = self.sim(None, 128, name=PLC_NAME)
        self.assertTrue(plc.wait_claimed(1))
        contender = self.sim(None, 128, name=0x100, keep=True)
        self.wait_event(plc, "lost", "Lost address 128 to NAME 0x0000000000000100; claiming 129")
        self.assertTrue(contender.wait_claimed(1))
        self.wait_event(plc, "claimed", "Claimed address 129")
        self.assertEqual((contender.address, plc.address), (128, 129))
        self.wait_event(contender, "claim_seen", "Address claim from 129: NAME 0x8000820000000" + "4D2")

    def test_contender_loses(self):
        defender = self.sim(None, 128, name=0x100)
        self.assertTrue(defender.wait_claimed(1))
        contender = self.sim(None, 128, name=PLC_NAME, keep=True)  # arbitrary address capable, but keeps
        self.wait_event(contender, "cannot_claim", "Cannot claim: lost address 128 to NAME 0x0000000000000100")
        self.wait_event(defender, "defended", "Defended address 128 against NAME 0x80008200000004D2")
        got = self.frames(1, lambda m: m.arbitration_id == 0x18EEFFFE)
        self.assertEqual(int.from_bytes(bytes(got[0][1].data), "little"), PLC_NAME)
        self.assertFalse(contender.claimed)
        self.assertEqual(defender.address, 128)


class Requests(Base):
    def setUp(self):
        super().setUp()
        self.engine = self.sim()
        self.assertTrue(self.engine.wait_claimed(1))

    def bam(self, timeout=1.0):
        """The next BAM transfer on the bus: (PGN, data)."""
        (_, cm), = self.frames(1, lambda m: m.arbitration_id == 0x18ECFF00, timeout)
        self.assertEqual(cm.data[0], 32)
        size, packets = cm.data[1] | cm.data[2] << 8, cm.data[3]
        dts = self.frames(packets, lambda m: m.arbitration_id == 0x1CEBFF00, timeout)
        self.assertEqual([m.data[0] for _, m in dts], list(range(1, packets + 1)))
        data = b"".join(bytes(m.data[1:]) for _, m in dts)[:size]
        return cm.data[5] | cm.data[6] << 8 | cm.data[7] << 16, data

    def test_request_answered_with_bam(self):
        self.send(0x18EA0080, request(65282))  # to the engine
        pgn, data = self.bam()
        self.assertEqual((pgn, len(data)), (65282, 40))
        values = self.db.get_message_by_name("ComponentInfo").decode(data, decode_choices=False)
        self.assertTrue(0 <= values["Hours"] <= 210554060.75, values)
        self.wait_event(self.engine, "request", "Request for PGN 65282 from 128: sent ComponentInfo")
        self.send(0x18EAFF80, request(65282))  # global
        self.assertEqual(self.bam()[0], 65282)

    def test_request_for_cyclic_message(self):
        self.send(0x18EA0080, request(65280))
        self.wait_event(self.engine, "request", "sent Pressures")

    def test_nack(self):
        self.send(0x18EAFF80, request(65290))  # global: no answer
        self.send(0x18EA0080, request(65291))  # to the engine: NACK
        (_, m), = self.frames(1, pf_is(0xE8))
        self.assertEqual(m.arbitration_id, 0x18E8FF00)
        self.assertEqual(bytes(m.data), bytes([1, 0xFF, 0xFF, 0xFF, 0x80, 0x0B, 0xFF, 0x00]))
        self.wait_event(self.engine, "request", "Request for PGN 65291 from 128: not sent here, NACK")
        self.assertEqual([e for e in self.engine.events if "65290" in e[1]], [])

    def test_request_to_other_address_ignored(self):
        self.send(0x18EA0580, request(65291))
        self.assertEqual(self.frames(1, pf_is(0xE8), timeout=0.2), [])


class Receive(Base):
    def test_decoded(self):
        engine = self.sim()
        self.assertTrue(engine.wait_claimed(1))
        self.send(0x18FF0180, [0xF4, 0x01, 0xFD, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF])
        self.send(0x18FF0580, [0] * 8)  # not in the DBC
        self.send(0x18EF0080, [3, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF])  # PDU1 to the engine
        event, text, fields = self.wait_event(engine, "rx", "65281")
        self.assertEqual(text, "PGN 65281 from 128: Setpoint=500 Run=1")
        self.assertEqual((fields["message"], fields["signals"]), ("Setpoints", {"Setpoint": 500, "Run": 1}))
        self.assertEqual(self.wait_event(engine, "rx", "61184")[1], "PGN 61184 from 128: Mode=3")
        self.assertEqual(engine.received, 2)

    def test_rts_cts_between_simulators(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d)
        path = os.path.join(d, "block.dbc")
        with open(path, "w") as f:
            f.write(DBC_PDU1)
        db = cantools.database.load_file(path)
        plc = self.sim("PLC", 128, db=db)
        self.assertTrue(plc.wait_claimed(1))
        self.sim("Engine", 0, db=db)
        (_, rts), = self.frames(1, lambda m: m.arbitration_id == 0x18EC8000)
        self.assertEqual(list(rts.data[:4]), [16, 16, 0, 3])  # RTS, 16 bytes, 3 packets
        event, text, fields = self.wait_event(plc, "rx", "PGN 61184 from 0: A=")
        self.assertTrue(0 <= fields["signals"]["A"] <= 1000 and 0 <= fields["signals"]["B"] <= 1000, fields)


class Command(Base):
    def run_main(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = sim.main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_log(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d)
        log = os.path.join(d, "sim.jsonl")
        result = {}
        t = threading.Thread(target=lambda: result.update(r=self.run_main(
            ["--dbc", DBC, "--node", "Engine", "--adapter", "virtual:" + self.ch, "--log", log, "--duration", "0.6"])))
        t.start()
        self.assertTrue(self.frames(1, pf_is(0xEE)))
        self.send(0x18FF0180, [0xF4, 0x01, 0xFD, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF])
        t.join(5)
        code, out, err = result["r"]
        self.assertEqual((code, err), (0, ""))
        self.assertIn("Engine on virtual:%s: address 0, NAME 0x0000000000010000" % self.ch, out)
        self.assertIn("  sends Pressures (PGN 65280, 100 ms)\n  sends ComponentInfo (PGN 65282, on request)", out)
        self.assertIn("PGN 65281 from 128: Setpoint=500 Run=1\n", out)
        self.assertIn("Stopped: sent ", out)
        with open(log) as f:
            records = [json.loads(line) for line in f]
        rx = [r for r in records if r["event"] == "rx"]
        self.assertEqual(len(rx), 1)
        self.assertEqual({k: rx[0][k] for k in ("pgn", "source", "message", "signals")},
                         {"pgn": 65281, "source": 128, "message": "Setpoints", "signals": {"Setpoint": 500, "Run": 1}})
        self.assertIn("claimed", [r["event"] for r in records])

    def test_usage_errors(self):
        a = ["--adapter", "virtual:" + self.ch]
        cases = [
            (["--dbc", DBC] + a, "give --node: the DBC node to simulate"),
            (["--contend", "128"] + a, "--contend needs --name-value"),
            (["--contend", "128", "--name-value", "5", "--address", "3"] + a, "give --contend ADDRESS or --address"),
            (["--dbc", DBC, "--node", "Pump"] + a, "node Pump is not in the DBC"),
            (["--dbc", DBC, "--node", "Engine", "--name-value", "5", "--function", "3"] + a,
             "give --name-value or the NAME field options, not both"),
            (["--dbc", os.path.join(REPO, "missing.dbc"), "--node", "Engine"] + a, "cannot read DBC"),
            (["--dbc", DBC, "--node", "Engine", "--adapter", "nope"], "write the adapter as TYPE:CHANNEL"),
        ]
        for argv, message in cases:
            with self.subTest(message=message):
                code, out, err = self.run_main(argv)
                self.assertEqual(code, 2)
                self.assertIn(message, err)

    def test_name_fields(self):
        args = sim.parser().parse_args(["--interface", "vcan0", "--dbc", DBC, "--node", "Engine",
                                        "--identity-number", "7", "--function", "130",
                                        "--arbitrary-address-capable"])
        _db, _plans, address, name, _dtcs = sim.setup(args)
        self.assertEqual((address, name.value), (0, (1 << 63) | (130 << 40) | 7))


if __name__ == "__main__":
    unittest.main()
