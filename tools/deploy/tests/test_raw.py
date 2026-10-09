"""Raw CAN messages in the PC tools (spec can-raw-messages): the shared
config fixtures, signal packing against the shared vectors, declarations,
DBC export/import and trace decoding."""

import json
import os
import unittest

from canworks import contract as _contract  # noqa: F401 - import order of the package
from canworks.configurator.declare import identifier
from canworks.raw import assist, contract, declare, replay, signals
from canworks.raw.decode import RawDecoder

try:
    import cantools  # noqa: F401
    from canworks.raw import dbc
except ImportError:
    dbc = None

FIXTURES = os.path.join(os.path.dirname(__file__), "..", "..", "..", "test", "fixtures")


def load(name):
    with open(os.path.join(FIXTURES, name)) as f:
        return json.load(f)


class SharedCases(unittest.TestCase):
    def test_cases(self):
        cases = load(os.path.join("config", "cases-raw.json"))["cases"]
        self.assertGreaterEqual(len(cases), 20)
        for case in cases:
            with self.subTest(case["name"]):
                ids = case.get("protocol_ids") or {}

                def use(ident, ext, ids=ids):
                    return "" if ext else ids.get("0x%X" % ident, "")

                errors, warnings, _ = contract.check_raw(case["raw"], "networks[0].raw", case.get("listen_only", False),
                                                         use if ids else None)
                for key, got in (("errors", errors), ("warnings", warnings)):
                    if key not in case:
                        continue
                    want = case[key]
                    self.assertEqual(len(got), len(want), "%s: %r" % (key, got))
                    for w, g in zip(want, got):
                        self.assertIn(w, g)


class Signals(unittest.TestCase):
    def test_vectors(self):
        for c in load("can_signals.json")["cases"]:
            data = bytes.fromhex(c["data"])
            self.assertEqual(signals.unpack(data, c["start_bit"], c["length"], c["big_endian"], c["signed"]), c["value"])
            packed = signals.pack(bytearray(8), c["start_bit"], c["length"], c["value"], c["big_endian"])
            self.assertEqual(bytes(packed).hex(), c["packed"])

    def test_tx_dlc(self):
        self.assertEqual(contract.tx_dlc({"signals": [{"start_bit": 7, "length": 16, "byte_order": "big"}]}), 2)
        self.assertEqual(contract.tx_dlc({"rtr": True}), 0)
        self.assertEqual(contract.tx_dlc({"data_location": "%QL1"}), 8)


CAB = {
    "rx": [{"name": "Joystick", "id": 291, "dlc": 8, "timeout_ms": 300, "status_location": "%IX300.0",
            "signals": [{"name": "X", "start_bit": 0, "length": 12, "signed": True, "scale": 0.1, "unit": "%",
                         "iec_location": "%IW304"}]}],
    "tx": [{"name": "Lamps", "id": 1281, "period_ms": 100,
            "signals": [{"name": "Red", "start_bit": 0, "length": 1, "iec_location": "%QX300.1"},
                        {"name": "Level", "start_bit": 15, "length": 16, "byte_order": "big",
                         "iec_location": "%QW300"}]},
           {"name": "Wake", "id": 0x18FF0080, "extended": True, "on_change": True,
            "signals": [{"name": "V", "start_bit": 0, "length": 8, "iec_location": "%QB1"}]}],
}


class Declarations(unittest.TestCase):
    def test_names_types_comments(self):
        names = set()

        def unique(n):
            names.add(n.lower())
            return n

        decls = declare.declarations(CAB, "", "", "", unique, identifier, {})
        by_name = {d["name"]: d for d in decls}
        self.assertEqual(by_name["Joystick_X"]["type"], "INT")
        self.assertEqual(by_name["Joystick_X"]["location"], "%IW304")
        self.assertIn("scale 0.1, offset 0, unit %", by_name["Joystick_X"]["description"])
        self.assertEqual(by_name["Joystick_status"]["type"], "BOOL")
        self.assertEqual(by_name["Lamps_Level"]["type"], "UINT")
        self.assertEqual(by_name["Wake_V"]["type"], "USINT")


class Decode(unittest.TestCase):
    def test_joystick_row(self):
        d = RawDecoder(CAB)
        self.assertEqual(d.text(0x123, False, bytes([0xFF, 0x0F, 0, 0, 0, 0, 0, 0])), "Joystick X=-1 (-0.1 %)")
        self.assertEqual(d.text(0x124, False, bytes(8)), "")
        self.assertEqual(d.text(0x18FF0080, True, bytes([7])), "Wake V=7")
        self.assertEqual(d.text(0x18FF0080, False, bytes([7])), "")


@unittest.skipIf(dbc is None, "cantools not installed")
class Dbc(unittest.TestCase):
    def test_round_trip(self):
        text = dbc.export_dbc(CAB, "cab")
        messages = {m["name"]: m for m in dbc.read_dbc(text)}
        self.assertEqual(set(messages), {"Joystick", "Lamps", "Wake"})
        self.assertEqual(messages["Lamps"]["senders"], ["PLC"])
        self.assertEqual(messages["Joystick"]["senders"], [])
        joy = dbc.to_entry(messages["Joystick"], "receive")
        self.assertEqual(joy["timeout_ms"], 300)
        self.assertEqual(joy["signals"], [{"name": "X", "start_bit": 0, "length": 12, "byte_order": "little",
                                           "signed": True, "scale": 0.1, "unit": "%"}])
        lamps = dbc.to_entry(messages["Lamps"], "send")
        self.assertEqual(lamps["period_ms"], 100)
        self.assertEqual(lamps["dlc"], 3)
        got = sorted((s["name"], s["start_bit"], s["length"], s["byte_order"]) for s in lamps["signals"])
        self.assertEqual(got, [("Level", 15, 16, "big"), ("Red", 0, 1, "little")])
        wake = dbc.to_entry(messages["Wake"], "send")
        self.assertTrue(wake["extended"])
        self.assertEqual(wake["id"], 0x18FF0080)
        self.assertTrue(wake["on_change"])

    def test_multiplexed_listed(self):
        text = (
            'VERSION ""\nBU_: A\nBO_ 100 M: 8 A\n SG_ Mux M : 0|8@1+ (1,0) [0|0] "" Vector__XXX\n'
            ' SG_ Val m1 : 8|8@1+ (1,0) [0|0] "" Vector__XXX\n SG_ Plain : 16|8@1+ (1,0) [0|0] "" Vector__XXX\n')
        (m,) = dbc.read_dbc(text)
        self.assertTrue(m["multiplexed"])
        self.assertEqual([s["name"] for s in m["signals"]], ["Plain"])



@unittest.skipIf(dbc is None, "cantools not installed")
class AssistTests(unittest.TestCase):
    def test_suggest_import_and_st_call(self):
        text = dbc.export_dbc(CAB, "cab")
        raw, notes = assist.import_messages(dbc.read_dbc(text), {"Joystick": "receive", "Lamps": "send"})
        self.assertEqual(notes, [])
        self.assertEqual([m["name"] for m in raw["rx"]], ["Joystick"])
        self.assertEqual([m["name"] for m in raw["tx"]], ["Lamps"])
        used = {("I", "X", 300 * 8)}
        filled = assist.suggest_locations(raw["rx"][0], "rx", used)
        self.assertEqual(filled, ["status_location", "signals[0].iec_location"])
        self.assertEqual(raw["rx"][0]["status_location"], "%IX300.1")
        self.assertEqual(raw["rx"][0]["signals"][0]["iec_location"], "%IW300")
        assist.suggest_locations(raw["tx"][0], "tx", used)
        self.assertEqual(sorted(s["iec_location"] for s in raw["tx"][0]["signals"]), ["%QW300", "%QX300.0"])
        self.assertEqual(contract.check_raw(raw, "networks[0].raw")[0], [])
        st = assist.st_call(raw["rx"][0], "rx", 1)
        self.assertIn("rx_Joystick(ENABLE := TRUE, NETWORK := 1, ID := 16#123, RX_DATA := Joystick_data);", st)
        self.assertIn("Joystick_X := CAN_GET_BITS(DATA := Joystick_data, START_BIT := 0, BIT_LENGTH := 12, "
                      "MOTOROLA := FALSE, SIGNED := TRUE);", st)
        st = assist.st_call(raw["tx"][0], "tx")
        self.assertIn("tx_Lamps(EXECUTE := Lamps_go, ID := 16#501, DLC := 3, DATA := Lamps_data);", st)



class ReplayTests(unittest.TestCase):
    def test_trc_plan_batches_and_adapter(self):
        import io
        from canworks.bustrace import formats
        from canworks.bustrace.model import Frame, Trace
        t = Trace()
        t.extend([Frame(1000000, 0x123, b"\x01\x02"), Frame(1010000, 0x18FF0080, bytes(8), ext=True),
                  Frame(1015000, 0x7E0, b"", rtr=True, dlc=2), Frame(1020000, 0, b"\x00" * 8, err=True)])
        out = io.StringIO()
        formats.write_trc(t, out)
        frames = replay.read_trc(out.getvalue())
        self.assertEqual([(f.time_us, f.can_id, f.ext, f.rtr, f.dlc) for f in frames],
                         [(0, 0x123, False, False, 2), (10000, 0x18FF0080, True, False, 8), (15000, 0x7E0, False, True, 2)])
        p = replay.plan(frames)
        self.assertEqual([off for off, _ in p], [0, 10000, 15000])
        self.assertEqual([off for off, _ in replay.plan(frames, rate=100)], [0, 10000, 20000])
        b = replay.batches(p, size=2)
        self.assertEqual(len(b), 2)
        self.assertEqual(b[0]["frames"][0], {"id": 0x123, "dlc": 2, "data": "0102", "t_us": 0})
        self.assertEqual(b[1]["frames"][0], {"id": 0x7E0, "dlc": 2, "rtr": True, "t_us": 15000})
        with self.assertRaises(replay.ReplayError):
            replay.plan([Frame(i * 100, 1, b"") for i in range(1001)])
        with self.assertRaises(replay.ReplayError):
            replay.plan(frames, rate=5000)
        try:
            import can
        except ImportError:
            return
        tx = can.Bus(interface="virtual", channel="replay-test")
        rx = can.Bus(interface="virtual", channel="replay-test")
        try:
            self.assertEqual(replay.play_on_bus(tx, p, sleep=lambda s: None), 3)
            got = [rx.recv(1) for _ in range(3)]
            self.assertEqual([(m.arbitration_id, m.is_extended_id, m.is_remote_frame) for m in got],
                             [(0x123, False, False), (0x18FF0080, True, False), (0x7E0, False, True)])
        finally:
            tx.shutdown()
            rx.shutdown()


if __name__ == "__main__":
    unittest.main()


class ReplayCli(unittest.TestCase):
    """canworks-diag replay --adapter on a python-can virtual bus."""

    def test_adapter_replay(self):
        try:
            import can
        except ImportError:
            self.skipTest("python-can not installed")
        import os
        from canworks.bustrace import formats
        from canworks.bustrace.model import Frame, Trace
        from .helpers import tmpdir
        from .test_localbus import channel, cli
        d = tmpdir(self)
        t = Trace()
        t.extend([Frame(0, 0x321, b"\x11"), Frame(5000, 0x322, b""), Frame(10000, 0x205, b"\x01")])
        path = os.path.join(d, "bus.asc")
        with open(path, "w") as f:
            formats.write_asc(t, f)
        ch = channel()
        rx = can.Bus(interface="virtual", channel=ch)
        self.addCleanup(rx.shutdown)
        base = ("--adapter", "virtual:" + ch, "--bitrate", "250")
        code, _, err = cli(*base, "replay", path)
        self.assertEqual(code, 1)
        self.assertIn("changes not allowed", err)
        code, out, err = cli(*base, "--allow-changes", "replay", path)
        self.assertEqual(code, 0, err)
        self.assertIn("replaying 3 frames", out)
        self.assertIn("replay ended: done, 3 frames sent", out)
        got = [rx.recv(1) for _ in range(3)]
        self.assertEqual([(m.arbitration_id, bytes(m.data)) for m in got],
                         [(0x321, b"\x11"), (0x322, b""), (0x205, b"\x01")])
        code, _, err = cli(*base, "--allow-changes", "replay", path, "--rate", "5000")
        self.assertEqual(code, 2)
        self.assertIn("at most 1000", err)


class StatusText(unittest.TestCase):
    """canworks-diag status of a plain CAN network, from an answer shaped as
    the plugin's (DiagHub::offline_answer + RawRuntime::status)."""

    ANSWER = {
        "version": "0.45.0", "uptime_s": 12, "config_sha256": "ab" * 32, "network": "cab", "protocols": ["canopen", "j1939", "none"],
        "session": False, "protocol": "none", "simulated_network": True, "simulation_forced": False,
        "listen_only": False, "bus": {"interface": "simulated", "bitrate": 250000, "state": 1},
        "send_jobs": [], "bitrate_sweep": {"running": False},
        "raw": {"running": True, "listen_only": False, "confirm": "echo", "frames_sent": 40, "frames_received": 81,
                "bus_load": 3, "program": {"receivers": 1, "cyclic_jobs": 0, "frames_sent": 2, "dropped": 0},
                "rx": [{"message": "joystick (0x180)", "count": 80, "short_frames": 0, "seen": True,
                        "timed_out": False, "age_ms": 9, "last_id": 384, "last_dlc": 2, "last_data": "10 00"},
                       {"message": "lamp_ack (0x181)", "count": 0, "short_frames": 0, "seen": False,
                        "timed_out": True}],
                "tx": [{"message": "lamp (0x200)", "count": 40}],
                "simulated_devices": ["joystick"]}}

    def test_plain_status(self):
        import io
        from canworks import diag
        out = io.StringIO()
        diag._print_status(self.ANSWER, out)
        text = out.getvalue()
        self.assertIn("plain CAN network on simulated, 250 kbit/s (simulated", text)
        self.assertIn("raw CAN: running, 40 frames sent, 81 received, bus load 3 %, confirm: echo", text)
        self.assertIn("program blocks: 1 receiver, 0 cyclic jobs, 2 frames sent, 0 dropped", text)
        self.assertIn("simulated plain CAN devices: joystick", text)
        self.assertRegex(text, r"joystick \(0x180\)\s+80\s+9 ms ago\s+0x180 \[2\] 10 00")
        self.assertRegex(text, r"lamp_ack \(0x181\)\s+0\s+never received")
        self.assertRegex(text, r"lamp \(0x200\)\s+40\s+-")
        self.assertNotIn("master node", text)


class TraceDecoding(unittest.TestCase):
    """Raw messages in the bus trace and the frame inspector."""

    RAW = {"rx": [{"name": "joystick", "id": 0x180, "dlc": 2, "signals": [
        {"name": "x", "start_bit": 0, "length": 8, "signed": True, "scale": 0.5, "unit": "%", "location": "%IW70"},
        {"name": "y", "start_bit": 15, "length": 8, "byte_order": "big"}]}],
        "tx": [{"name": "lamp", "id": 0x18FF0010, "extended": True, "dlc": 1, "period_ms": 100}]}

    def plain(self):
        return {"schema_version": 2, "networks": [{"name": "cab", "protocol": "none",
                                                   "adapter": {"interface": "can0", "bitrate": 250000},
                                                   "raw": self.RAW}]}

    def test_plain_network(self):
        from canworks.bustrace import explain
        from canworks.bustrace.decode import Decoder
        from canworks.bustrace.model import Frame
        d = Decoder.from_config(self.plain(), "/x/canworks.json", network="cab")
        self.assertEqual(d.protocol, "none")
        r = d.decode(Frame(0, 0x180, b"\xfe\x10"))
        self.assertEqual((r.kind, r.name, r.text), ("raw", "joystick", "joystick x=-2 (-1 %) y=16"))
        self.assertEqual(r.signals, [("joystick.x", -1.0), ("joystick.y", 16)])
        self.assertEqual(d.decode(Frame(0, 0x18FF0010, b"\x01", ext=True)).name, "lamp")
        # A plain network knows no CANopen: 0x181 is just a frame.
        self.assertEqual(d.decode(Frame(0, 0x181, b"\x01")).kind, "other")
        self.assertIn(("joystick.x", "joystick x", None), d.signal_keys())
        e = explain.explain(Frame(0, 0x180, b"\xfe\x10"), d)
        self.assertEqual((e["kind"], e["title"]), ("raw", "joystick"))
        self.assertEqual([(f["name"], f["start"], f["length"], f["value"]) for f in e["fields"]],
                         [("x", 0, 8, "-2 (-1 %)"), ("y", 8, 8, "16")])
        self.assertIn("In the PLC program: %IW70.", e["fields"][0]["text"])
        e = explain.explain(Frame(0, 0x182, b"\xfe"), d)
        self.assertEqual(e["kind"], "other")
        self.assertIn("0x182 with 1 data byte; not configured", e["meaning"])

    def test_next_to_canopen(self):
        from canworks.bustrace.decode import Decoder
        from canworks.bustrace.model import Frame
        from .helpers import pingpong_config
        from .helpers import tmpdir
        path = pingpong_config(tmpdir(self))
        with open(path) as f:
            cfg = json.load(f)
        cfg["raw"] = {"rx": [{"name": "free", "id": 0x3F0, "dlc": 1}, {"name": "on_pdo", "id": 0x182, "dlc": 1}]}
        d = Decoder.from_config(cfg, path)
        self.assertEqual(d.decode(Frame(0, 0x3F0, b"\x01")).kind, "raw")
        # The protocol keeps the identifiers it uses.
        self.assertNotEqual(d.decode(Frame(0, 0x182, b"\x01")).kind, "raw")


class SimFile(unittest.TestCase):
    """raw_devices and device steps in the simulation file (simfile.py)."""

    CFG = {"schema_version": 2, "networks": [
        {"name": "cab", "protocol": "none", "adapter": {"type": "socketcan", "interface": "can1", "bitrate": 250000,
                                                         "simulate": True}}]}

    def check(self, data, cfg=None):
        from canworks import simfile
        d = tmpdir_(self)
        path = os.path.join(d, "simulation.json")
        return simfile.check(data, path, cfg or self.CFG, os.path.join(d, "canworks.json"))

    def joystick(self, **extra):
        dev = {"name": "joystick", "send": [{"id": 0x180, "dlc": 2, "period_ms": 100, "signals": [
            {"name": "x", "start_bit": 0, "length": 16, "signed": True,
             "source": {"sine": {"min": -1000, "max": 1000, "period_s": 4}}}]}],
            "replies": [{"on": {"id": 0x7E0, "data": [2, 1, 12]}, "send": {"id": 0x7E8, "data": [4, 65, 12]}}]}
        dev.update(extra)
        return dev

    def test_accepted(self):
        data = {"schema_version": 2, "raw_devices": [self.joystick()], "networks": {"cab": {"scenarios": {"stop": {
            "steps": [{"at_ms": 1000, "device": "joystick", "fault": {"stop": True}},
                      {"repeat": {"count": 2, "steps": [{"after_ms": 100, "device": "joystick",
                                                         "fault": {"wrong_dlc": 1}},
                                                        {"device": "joystick", "clear": "all"}]}}]}}}}}
        r = self.check(data)
        self.assertEqual(r.errors, [])

    def test_refusals(self):
        bad_signal = self.joystick()
        bad_signal["send"][0]["signals"][0]["start_bit"] = 8
        data = {"schema_version": 2, "raw_devices": [bad_signal, self.joystick(network="nope")],
                "networks": {"cab": {"scenarios": {"s": {"steps": [
                    {"device": "pedal", "fault": {"stop": True}},
                    {"node": 5, "fault": {"heartbeat": "stop"}}]}}}}}
        text = "\n".join(self.check(data).errors)
        self.assertIn("raw_devices[0].send[0].signals[0]: does not fit the frame's 2 bytes", text)
        self.assertIn("raw_devices[1].name: another plain CAN device is also called 'joystick'", text)
        self.assertIn("raw_devices[1].network: there is no network 'nope'", text)
        self.assertIn("steps[0].device: no plain CAN device 'pedal' on this network (raw_devices: joystick)", text)
        self.assertIn("steps[1]: on a plain CAN network a scenario step is a 'fault' or 'clear' on a 'device'", text)
        # The schema: a device fault is stop or wrong_dlc.
        data = {"schema_version": 2, "raw_devices": [self.joystick()], "networks": {"cab": {"scenarios": {"s": {
            "steps": [{"device": "joystick", "fault": {"wrong_dlc": 9}}]}}}}}
        self.assertTrue(self.check(data).errors)
        data = {"raw_devices": [{"name": "x"}]}
        self.assertTrue(self.check(data).errors)  # neither send nor replies


def tmpdir_(test):
    from .helpers import tmpdir
    return tmpdir(test)
