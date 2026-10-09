"""J1939 traces (j1939-trace spec): decoding a recorded trace of the example
machine network (claims, PGN 65280 from 0, a request and its RTS/CTS answer,
a NACK, a BAM of PGN 65283, a PGN nothing names, Cannot Claim), the frame
explanation with the identifier split, `canworks-diag explain`, `trace`
and `convert` on a J1939 network, and the J1939 lines of `canworks-diag
status` against a recorded status answer."""

import json
import os
import shutil
import tempfile
import threading
import time
import unittest

from canworks import diag
from canworks.bustrace import formats
from canworks.bustrace.decode import Decoder, decode_all
from canworks.bustrace.explain import context_for, explain, format_text, parse_frame
from canworks.bustrace.j1939 import J1939Decoder, name_fields, split_id
from canworks.bustrace.model import Frame
from canworks.bustrace.stats import Analysis

from .fake_diag import J1939_NETWORK, FakePlugin
from .helpers import PINGPONG, REPO
from .test_diag import run

EXAMPLE = os.path.join(REPO, "examples", "j1939", "canworks.json")
TRACE = os.path.join(os.path.dirname(__file__), "data", "trace", "j1939.log")


def example_config():
    with open(EXAMPLE, encoding="utf-8") as f:
        return json.load(f)


def machine_decoder():
    return Decoder.from_config(example_config(), EXAMPLE, network="machine")


def decoded_trace(dec=None):
    trace = formats.read_file(TRACE)
    return trace, decode_all(dec or machine_decoder(), trace)


def rows_of(trace, decoded, can_id):
    return [d for f, d in zip(trace, decoded) if f.can_id == can_id]


class Identifier(unittest.TestCase):
    def test_pdu1_split(self):
        s = split_id(0x18EF0380)
        self.assertEqual((s["priority"], s["reserved"], s["dp"], s["pf"], s["ps"], s["source"]),
                         (6, 0, 0, 0xEF, 3, 0x80))
        self.assertEqual((s["pgn"], s["destination"], s["group_extension"]), (0xEF00, 3, None))

    def test_pdu2_and_data_page(self):
        s = split_id(0x0DFF1005)
        self.assertEqual((s["priority"], s["dp"], s["pgn"], s["destination"], s["group_extension"], s["source"]),
                         (3, 1, 0x1FF10, None, 0x10, 5))

    def test_name_fields(self):
        f = {k: v for k, _label, v in name_fields(0x80008200000004D2)}
        self.assertEqual((f["identity_number"], f["manufacturer_code"], f["function"], f["industry_group"],
                          f["arbitrary_address_capable"]), (1234, 0, 130, 0, 1))


class Decoding(unittest.TestCase):
    def test_decoder_for_a_j1939_network(self):
        dec = machine_decoder()
        self.assertIsInstance(dec, J1939Decoder)
        self.assertEqual(dec.warnings, [])
        self.assertEqual(dec.pdos, {})
        keys = [k for k, _label, _node in dec.signal_keys()]
        self.assertIn("Pressures.Pressure", keys)
        self.assertIn("ComponentInfo.Serial", keys)

    def test_signal_decoded(self):
        trace, decoded = decoded_trace()
        d = rows_of(trace, decoded, 0x18FF0000)[0]
        self.assertEqual((d.kind, d.node, d.name), ("pgn", 0, "Pressures"))
        self.assertEqual(d.text, "priority 6, PGN 65280 from 0 (Engine): Pressure=123.4 bar, Temp=-10 degC, "
                                 "Level=40 %, PumpOn=1")
        self.assertEqual(dict(d.signals)["Pressures.Pressure"], 123.4)
        sent = rows_of(trace, decoded, 0x18FF0180)[0]
        self.assertEqual(sent.text, "priority 6, PGN 65281 from 128 (PLC): Setpoint=1000 rpm, Run=1")

    def test_address_claim_and_cannot_claim(self):
        trace, decoded = decoded_trace()
        d = rows_of(trace, decoded, 0x18EEFF80)[0]
        self.assertEqual((d.kind, d.node, d.name), ("claim", 128, "Address Claimed"))
        for text in ("address 128 (PLC) claimed", "NAME 0x80008200000004D2", "identity number 1234",
                     "manufacturer code 0", "ECU instance 0", "function instance 0", "function 130",
                     "vehicle system 0", "vehicle system instance 0", "industry group 0",
                     "arbitrary address capable yes"):
            self.assertIn(text, d.text)
        d = rows_of(trace, decoded, 0x18EEFFFE)[0]
        self.assertEqual((d.kind, d.name), ("claim", "Cannot Claim"))
        self.assertIn("no address for NAME 0x0000000000000003 (identity number 3", d.text)

    def test_request_and_nack(self):
        trace, decoded = decoded_trace()
        req = rows_of(trace, decoded, 0x18EA0080)
        self.assertEqual(req[0].text, "for PGN 65282 (ComponentInfo) from 128 (PLC) to 0 (Engine)")
        self.assertEqual(req[1].text, "for PGN 65284 (0xFF04) from 128 (PLC) to 0 (Engine)")
        nack = rows_of(trace, decoded, 0x18E8FF00)[0]
        self.assertEqual((nack.kind, nack.name), ("ack", "NACK"))
        self.assertEqual(nack.text, "NACK for PGN 65284 (0xFF04), to 128 (PLC), from 0 (Engine)")

    def test_rts_cts_session(self):
        trace, decoded = decoded_trace()
        cm = [d.text for d in rows_of(trace, decoded, 0x1CEC8000) + rows_of(trace, decoded, 0x1CEC0080)]
        self.assertEqual(cm, [
            "RTS for PGN 65282 (ComponentInfo): 40 bytes in 6 packets, from 0 (Engine) to 128 (PLC), "
            "no limit per CTS",
            "CTS for PGN 65282 (ComponentInfo): send 6 packets from packet 1, from 128 (PLC) to 0 (Engine)",
            "PGN 65282 (ComponentInfo) received: 40 bytes in 6 packets, from 128 (PLC) to 0 (Engine)"])
        dt = rows_of(trace, decoded, 0x1CEB8000)
        self.assertEqual(len(dt), 6)
        self.assertEqual(dt[0].text, "packet 1/6 of PGN 65282 (ComponentInfo) (RTS/CTS), from 0 (Engine) to 128 (PLC)")
        whole = dt[-1]
        self.assertEqual((whole.kind, whole.name), ("pgn", "ComponentInfo"))
        self.assertIn("PGN 65282 from 0 (Engine) to 128 (PLC) (40 bytes by RTS/CTS in 6 packets", whole.text)
        self.assertIn("Hours=1000 h, Starts=42, Serial=305419896", whole.text)
        self.assertEqual(dict(whole.signals)["ComponentInfo.Hours"], 1000)

    def test_bam_session(self):
        trace, decoded = decoded_trace()
        parts = rows_of(trace, decoded, 0x1CECFF00) + rows_of(trace, decoded, 0x1CEBFF00)
        self.assertEqual(len(parts), 7)  # the seven frames stay rows
        self.assertEqual(parts[0].text, "BAM for PGN 65283 (0xFF03): 40 bytes in 6 packets, from 0 (Engine) to "
                                        "global (255)")
        self.assertTrue(all("packet %d/6 of PGN 65283" % (k + 1) in p.text for k, p in enumerate(parts[1:6])))
        whole = parts[-1]
        self.assertEqual((whole.kind, whole.name), ("pgn", "PGN 65283"))
        self.assertIn("PGN 65283 from 0 (Engine) (40 bytes by BAM in 6 packets", whole.text)
        self.assertTrue(whole.text.endswith(": " + " ".join("%02X" % b for b in range(1, 41))), whole.text)

    def test_unnamed_frame_shows_the_split(self):
        trace, decoded = decoded_trace()
        d = rows_of(trace, decoded, 0x18FF1005)[0]
        self.assertEqual((d.kind, d.node, d.name, d.text),
                         ("pgn", 5, "PGN 65296", "priority 6, PGN 65296 from 5: 01 02"))

    def test_session_needs_its_start(self):
        # Decoded from the middle of a BAM, a packet says it has no session.
        trace = formats.read_file(TRACE)
        dt = next(f for f in trace if f.can_id == 0x1CEBFF00)
        d = machine_decoder().decode(dt)
        self.assertEqual((d.kind, d.text), ("tp", "packet 1 without a session, from 0 (Engine) to global (255)"))

    def test_without_the_dbc_the_config_names_signals(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp)
        path = os.path.join(tmp, "canworks.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(example_config(), f)
        dec = Decoder.from_config(example_config(), path, network="machine")
        self.assertEqual(len(dec.warnings), 1)
        self.assertIn("decoding without the DBC machine.dbc", dec.warnings[0])
        trace, decoded = decoded_trace(dec)
        d = rows_of(trace, decoded, 0x18FF0000)[0]
        self.assertEqual(d.name, "Pressures")
        self.assertIn("Pressure=123.4 bar, Temp=-10 degC, Level=40 %, PumpOn=1", d.text)

    def test_series_and_kinds(self):
        trace = formats.read_file(TRACE)
        a = Analysis(machine_decoder())
        for f in trace:
            a.feed(f)
        self.assertEqual(len(a.series["Pressures.Pressure"].values), 2)
        self.assertEqual(list(a.series["ComponentInfo.Starts"].values), [42.0])
        # Transport identifiers are named after their message, not their last frame.
        names = {x["id_text"]: (x["name"], x["kind"]) for x in (st.as_dict() for st in a.ids.values())}
        self.assertEqual(names["1CEC0080"], ("TP.CM", "tp"))
        self.assertEqual(names["1CEB8000"], ("TP.DT of ComponentInfo", "tp"))
        self.assertEqual(names["1CEBFF00"], ("TP.DT of PGN 65283", "tp"))

    def test_canopen_frame_on_a_j1939_network(self):
        m = explain(parse_frame("185#01"), machine_decoder())
        self.assertEqual((m["kind"], m["title"], m["protocol"]), ("other", "11-bit frame", "j1939"))
        self.assertNotIn("TPDO", json.dumps(m))
        self.assertEqual({b["part"] for b in m["identifier"]["bits"]}, {"id"})

    def test_frame_lab_examples(self):
        from canworks.bustrace import framebuild
        from canworks.bustrace.explain import candump_text
        ex = {x["label"]: [candump_text(f["frame"]) for f in x["frames"]] for x in framebuild.examples(machine_decoder())}
        self.assertEqual(ex["Request for Address Claimed"], ["18EAFF80#00EE00"])
        self.assertEqual(ex["Pressures"], ["18FF0000#0000000000000000"])
        self.assertNotIn("NMT start all nodes", ex)

    def test_canopen_networks_keep_their_decoding(self):
        with open(os.path.join(PINGPONG, "canopen_config.json"), encoding="utf-8") as f:
            cfg = json.load(f)
        dec = Decoder.from_config(cfg, os.path.join(PINGPONG, "canopen_config.json"))
        self.assertEqual(dec.protocol, "canopen")
        self.assertEqual(dec.decode(Frame(0, 0x18FF0000, bytes(8), ext=True)).kind, "other")
        m = explain(parse_frame("18EF0380#01"), dec)
        self.assertEqual(m["kind"], "ext")
        self.assertNotIn("j1939", m["identifier"])


class Explanation(unittest.TestCase):
    def test_pdu1_identifier(self):
        m = explain(parse_frame("18EF0380#01"), machine_decoder())
        j = m["identifier"]["j1939"]
        self.assertEqual((j["priority"], j["pf"], j["destination"], j["source"], j["pgn"]), (6, 0xEF, 3, 0x80, 0xEF00))
        self.assertEqual([b["part"] for b in m["identifier"]["bits"][:6]],
                         ["priority"] * 3 + ["reserved", "dp", "pf"])
        self.assertEqual(m["title"], "Command from 128 (PLC)")
        self.assertEqual(m["fields"][0]["name"], "Mode")
        text = format_text(m)
        self.assertIn("priority 110 = 6   reserved 0   data page 0", text)
        self.assertIn("PDU format 11101111 = 0xEF   PDU specific 00000011 = 0x03 (destination 3)   "
                      "source 10000000 = 128 (0x80)", text)
        self.assertIn("PGN 0xEF00 = 61184", text)

    def test_claim_fields(self):
        m = explain(parse_frame("18EEFF80#D204000000820000"), machine_decoder())
        self.assertEqual(m["kind"], "claim")
        fields = {f["name"]: f["value"] for f in m["fields"]}
        self.assertEqual((fields["Identity number"], fields["Function"], fields["Arbitrary address capable"]),
                         ("1234", "130", "no"))
        self.assertEqual(sum(f["length"] for f in m["fields"]), 64)

    def test_tp_packet_with_its_session(self):
        trace = formats.read_file(TRACE)
        dec = machine_decoder()
        i = next(k for k, f in enumerate(trace) if f.can_id == 0x1CEBFF00) + 1  # packet 2 of the BAM
        m = explain(trace.frame(i), dec, None, context_for(trace, i, dec))
        self.assertEqual(m["meaning"], "Packet 2 of 6 of PGN 65283 (0xFF03) from 0 (Engine) (BAM).")
        self.assertIn("Bytes 7-13 of PGN 65283", next(f for f in m["fields"] if f["name"] == "Data")["text"])


class Cli(unittest.TestCase):
    def project(self):
        """A folder with canworks/canworks.json and its DBC, as the current folder."""
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp)
        shutil.copytree(os.path.dirname(EXAMPLE), os.path.join(tmp, "canworks"))
        cwd = os.getcwd()
        os.chdir(tmp)
        self.addCleanup(os.chdir, cwd)
        return tmp

    def test_explain_a_claim(self):
        self.project()
        code, out, err = run("explain", "18EEFF80#D204000000820000", "--network", "machine")
        self.assertEqual(code, 0, err)
        self.assertIn("Address Claimed from 128\n", out)
        for name in ("Identity number (bits 0-20): 1234", "Manufacturer code (bits 21-31): 0",
                     "ECU instance (bits 32-34): 0", "Function instance (bits 35-39): 0", "Function (bits 40-47): 130",
                     "Vehicle system (bits 49-55): 0", "Vehicle system instance (bits 56-59): 0",
                     "Industry group (bits 60-62): 0", "Arbitrary address capable (bit 63): no"):
            self.assertIn(name, out)
        self.assertIn("On the wire at 250 kbit/s\n", out)  # the network's bit rate

    def test_explain_without_cantools(self):
        self.project()
        import sys
        saved = sys.modules.get("cantools")
        sys.modules["cantools"] = None  # import fails as when it is not installed
        self.addCleanup(lambda: sys.modules.pop("cantools") if saved is None else sys.modules.__setitem__("cantools", saved))
        code, out, err = run("explain", "18FF0000#0102", "--network", "machine")
        self.assertEqual(code, 0, err)
        self.assertIn("decoding without the DBC machine.dbc: cantools is not installed", err)
        self.assertIn("Pressures (PGN 65280) from 0", out)

    def test_explain_a_trace_frame(self):
        self.project()
        code, out, err = run("explain", "--trace", TRACE, "--index", "13", "--network", "machine", "--format", "json")
        self.assertEqual(code, 0, err)
        m = json.loads(out)
        self.assertEqual(m["title"], "TP.DT from 0 (Engine)")
        self.assertEqual(m["kind"], "tp")
        self.assertIn("Packet 6 of 6 of PGN 65282 (ComponentInfo)", m["meaning"])

    def test_convert_names_signals(self):
        tmp = self.project()
        csv = os.path.join(tmp, "out.csv")
        code, _, err = run("convert", TRACE, csv, "--network", "machine")
        self.assertEqual(code, 0, err)
        with open(csv, encoding="utf-8") as f:
            text = f.read()
        self.assertIn("Pressure=123.4 bar", text)
        self.assertIn("Address Claimed", text)

    def test_trace_records_and_decodes(self):
        tmp = self.project()
        trace = formats.read_file(TRACE)
        with FakePlugin(networks=[J1939_NETWORK]) as fake:
            stop = threading.Event()

            def feed():
                while not stop.is_set():
                    now = int(time.time() * 1e6)
                    fake.push([Frame(now + k, f.can_id, f.data, ext=True, tx=f.tx) for k, f in enumerate(trace)])
                    time.sleep(0.05)

            th = threading.Thread(target=feed, daemon=True)
            th.start()
            self.addCleanup(stop.set)
            path = os.path.join(tmp, "run.csv")
            code, out, err = run("--runtime", fake.runtime, "trace", "-o", path, "--duration", "0.4",
                                 "--network", "machine")
            stop.set()
        self.assertEqual(code, 0, err)
        with open(path, encoding="utf-8") as f:
            text = f.read()
        self.assertIn("Pressure=123.4 bar", text)
        self.assertIn("40 bytes by BAM", text)


class Status(unittest.TestCase):
    def test_j1939_status(self):
        with FakePlugin(networks=[J1939_NETWORK]) as fp:
            code, out, err = run("--runtime", fp.runtime, "status", "--network", "machine")
        self.assertEqual(code, 0, err)
        self.assertIn("built-in protocols: canopen, j1939\n", out)
        self.assertIn("bus vcan0: error active, tx errors 0, rx errors 3, bus-off 0\n", out)
        self.assertIn("J1939 ECU: claimed, address 128\n", out)
        self.assertIn("own NAME 0x80008200000004D2 (identity number 1234, manufacturer code 0", out)
        self.assertIn("  0        12 ms ago     0x0000000000000001\n", out)
        self.assertRegex(out, r"\n  65280  any +0, 3 +1250 ms ago +TIMED OUT +2 +1234\n")
        self.assertRegex(out, r"\n  65282  0 +0 +never +ok +0 +0\n")
        self.assertIn("  65283  NAME 0x0000000000000001 mask 0x00000000001FFFFF", out)
        self.assertIn("PGN 65280: timed out, no message for 1250 ms (2 timeouts)\n", out)
        self.assertIn("PGN 65280 signals (raw): Pressure 1234, Temp -10, Level 255 (not valid)\n", out)
        self.assertIn("sent PGN 65281: 812 sent, 2 requests answered\n", out)
        self.assertIn("request for PGN 65282: 81 sent\n", out)
        self.assertNotIn("master node", out)
        self.assertNotIn("CANopen session", out)

    def test_j1939_without_a_bus(self):
        with FakePlugin(networks=[J1939_NETWORK]) as fp:
            j = fp.status["j1939"]
            j.update(state=3, state_name="no bus", address=254, ecus=[],
                     error="J1939 needs the can-j1939 kernel module (modprobe can-j1939)")
            fp.status["session"] = False
            code, out, err = run("--runtime", fp.runtime, "status")
        self.assertEqual(code, 0, err)
        self.assertIn("J1939 ECU: no bus, no address\n", out)
        self.assertIn("J1939 not running: J1939 needs the can-j1939 kernel module (modprobe can-j1939)\n", out)
        self.assertIn("ECUs seen: none\n", out)

    def test_json_passes_the_answer(self):
        with FakePlugin(networks=[J1939_NETWORK]) as fp:
            code, out, _ = run("--runtime", fp.runtime, "--json", "status")
        self.assertEqual(json.loads(out)["j1939"]["rx"][0]["sources"], [0, 3])


if __name__ == "__main__":
    unittest.main()
