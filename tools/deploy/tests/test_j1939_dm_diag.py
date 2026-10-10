"""J1939 trouble codes in the PC tools (add-j1939-diagnostics, tasks 5.1, 5.2
and 5.5): `canworks-diag dm list | read | clear` against a fake plugin and,
on python-can's virtual bus, straight through an adapter against the
simulator; the "dm" part of `canworks-diag status`; the DBC import with DM
PGNs and SPN attributes; the located variable declarations of the
diagnostics locations."""

import copy
import json
import os
import shutil
import tempfile
import time
import unittest

import can

from canworks import editorproject
from canworks.configurator import declare
from canworks.j1939 import dbc, dm, dmtool, sim

from .fake_diag import J1939_NETWORK, FakePlugin
from .helpers import REPO
from .test_diag import run
from .test_j1939_sim import channel

MACHINE_CONFIG = os.path.join(REPO, "examples", "j1939", "canworks.json")

DM_STATUS = {
    "sources": [{"address": 0, "lamps": 4, "flash": 255, "count": 1, "truncated": 0,
                 "dtcs": [{"spn": 520192, "fmi": 3, "oc": 2, "cm": False}], "age_ms": 120, "dm1_count": 17,
                 "old_spn_format": False},
                {"address": 3, "lamps": 0, "flash": 255, "count": 70, "truncated": 6,
                 "dtcs": [{"spn": 520300, "fmi": 31, "oc": 1, "cm": True}], "age_ms": 900, "dm1_count": 2,
                 "old_spn_format": True}],
    "watched": [{"index": 0, "source": 0, "source_name": None, "timed_out": False, "timeouts": 0}],
    "own": {"active": [{"spn": 520192, "fmi": 3, "oc": 1, "lamps": ["amber"], "flash": None}],
            "previous": [], "lamps": 4, "flash": 255, "clears": 1, "suspended": True, "dm1_sent": 12},
}

# A DBC with DM1 (PGN 65226) and PGN 65280, whose signal carries SPN 520192.
DM_DBC = """VERSION ""
NS_ :
BS_:
BU_: Engine PLC
BO_ %d DM1: 8 Engine
 SG_ Lamps : 0|8@1+ (1,0) [0|255] "" PLC
 SG_ FirstSpn : 16|16@1+ (1,0) [0|65535] "" PLC
BO_ %d Coolant: 8 Engine
 SG_ CoolantLevel : 0|8@1+ (1,0) [0|100] "%%" PLC
 SG_ CoolantTemp : 8|8@1+ (1,-40) [-40|210] "degC" PLC
BA_DEF_ SG_ "SPN" INT 0 524287;
BA_DEF_DEF_ "SPN" 0;
BA_ "SPN" SG_ %d CoolantLevel 520192;
BA_ "SPN" SG_ %d FirstSpn 1234;
""" % (0x98FECA00, 0x98FF0000, 0x98FF0000, 0x98FECA00)


def plugin():
    fp = FakePlugin(networks=[J1939_NETWORK])
    fp.status["j1939"]["dm"] = copy.deepcopy(DM_STATUS)
    return fp


class TempDir(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir)

    def dbc_file(self):
        path = os.path.join(self.dir, "dm.dbc")
        with open(path, "w") as f:
            f.write(DM_DBC)
        return path


class ThroughThePlugin(TempDir):
    def test_list(self):
        """List faults through the PLC."""
        with plugin() as fp:
            code, out, err = run("--runtime", fp.runtime, "dm", "list", "--network", "machine")
        self.assertEqual((code, err), (0, ""))
        self.assertIn("diagnostic messages of network machine:\n", out)
        self.assertIn("  ECU 0: amber warning on; 1 active code, last DM1 120 ms ago\n"
                      "    SPN 520192 FMI 3 (voltage above normal or shorted high) OC 2\n", out)
        self.assertIn("  ECU 3: lamps off; 70 active codes, last DM1 900 ms ago, older SPN format\n", out)
        self.assertIn("    SPN 520300 FMI 31 (condition exists) OC 1 [older SPN format]\n    ... 6 more codes not "
                      "stored\n", out)
        self.assertIn("  watched rx[0] (ECU 0): ok, 0 timeouts\n", out)
        self.assertIn("  own DM1: amber warning on; 12 sent, 1 clear accepted, SUSPENDED by DM13\n", out)
        self.assertIn("  own active codes: \n    SPN 520192 FMI 3 (voltage above normal or shorted high) OC 1\n", out)
        self.assertIn("  own previously active codes: none\n", out)

    def test_list_names_spns_from_the_dbc(self):
        with plugin() as fp:
            code, out, err = run("--runtime", fp.runtime, "dm", "list", "--dbc", self.dbc_file())
        self.assertEqual(code, 0, err)
        self.assertIn("SPN 520192 CoolantLevel FMI 3 (voltage above normal or shorted high) OC 2", out)

    def test_status_shows_the_dm_part(self):
        with plugin() as fp:
            code, out, err = run("--runtime", fp.runtime, "status", "--network", "machine")
        self.assertEqual(code, 0, err)
        self.assertIn("diagnostic messages:\n  ECU 0: amber warning on; 1 active code", out)

    def test_status_without_dm(self):
        with FakePlugin(networks=[J1939_NETWORK]) as fp:
            code, out, err = run("--runtime", fp.runtime, "status")
        self.assertEqual(code, 0, err)
        self.assertNotIn("diagnostic messages", out)

    def test_json(self):
        with plugin() as fp:
            code, out, _ = run("--runtime", fp.runtime, "--json", "dm", "list")
        self.assertEqual(json.loads(out), DM_STATUS)

    def test_read(self):
        with plugin() as fp:
            fp.extra_ops["j1939_dm_read"] = lambda req: {
                "address": req["address"], "lamps": 0, "flash": 255, "count": 1,
                "dtcs": [{"spn": 520193, "fmi": 1, "oc": 4, "cm": False}]}
            code, out, err = run("--runtime", fp.runtime, "dm", "read", "--address", "0", "--dm-timeout", "500")
            req = fp.requests[-1]
        self.assertEqual(code, 0, err)
        self.assertEqual((req["op"], req["address"], req["timeout_ms"]), ("j1939_dm_read", 0, 500))
        self.assertEqual(out, "DM2 from 0: lamps off; 1 previously active code\n"
                              "  SPN 520193 FMI 1 (below normal, most severe) OC 4\n")

    def test_read_errors(self):
        for why in ("no answer from 0 within 1000 ms", "busy: a DM2 read or clear for address 0 is pending",
                    "network has no address (state: claiming)"):
            with self.subTest(why), plugin() as fp:
                def refuse(req, why=why):
                    raise ValueError(why)
                fp.extra_ops["j1939_dm_read"] = refuse
                code, out, err = run("--runtime", fp.runtime, "dm", "read", "--address", "0")
                self.assertEqual((code, out), (1, ""))
                self.assertIn(why, err)

    def test_clear_without_force(self):
        """Clear without force: nothing is sent, the tool says --force."""
        with plugin() as fp:
            code, out, err = run("--runtime", fp.runtime, "dm", "clear", "--address", "0")
            self.assertEqual(fp.requests, [])
        self.assertEqual((code, out), (1, ""))
        self.assertIn("clearing trouble codes acts on another ECU: repeat with --force; nothing sent", err)

    def test_clear(self):
        with plugin() as fp:
            fp.extra_ops["j1939_dm_clear"] = lambda req: {"address": req["address"], "result": "ack"} \
                if req["address"] != 255 else {"address": 255, "result": "sent"}
            code, out, err = run("--runtime", fp.runtime, "dm", "clear", "--address", "0", "--force")
            self.assertEqual(code, 0, err)
            self.assertEqual(out, "DM11 (clear active DTCs) to 0: ACK\n")
            req = fp.requests[-1]
            self.assertEqual((req["op"], req["address"], req["previous"], req["force"]),
                             ("j1939_dm_clear", 0, False, True))
            code, out, err = run("--runtime", fp.runtime, "--force", "dm", "clear", "--address", "global",
                                 "--previous")
            self.assertEqual(code, 0, err)
            self.assertEqual(out, "DM3 (clear previously active DTCs) sent to every ECU (global: no "
                                  "acknowledgement)\n")
            self.assertEqual((fp.requests[-1]["address"], fp.requests[-1]["previous"]), (255, True))

    def test_nack(self):
        with plugin() as fp:
            def nack(req):
                raise ValueError("NACK from 0")
            fp.extra_ops["j1939_dm_clear"] = nack
            code, out, err = run("--runtime", fp.runtime, "dm", "clear", "--address", "0", "--force")
        self.assertEqual(code, 1)
        self.assertIn("NACK from 0", err)

    def test_not_a_j1939_network(self):
        with FakePlugin() as fp:
            code, out, err = run("--runtime", fp.runtime, "dm", "list")
        self.assertEqual(code, 1)
        self.assertIn("is not a J1939 network", err)

    def test_addresses(self):
        for argv in (["read", "--address", "254"], ["read", "--address", "global"], ["clear", "--address", "254"]):
            with self.subTest(argv), self.assertRaises(SystemExit):
                run("--runtime", "localhost", "dm", *argv)


class OnAnAdapter(unittest.TestCase):
    """--adapter: listen for DM1, claim 249 to read and clear, against the
    simulator as a faulty ECU at address 0."""

    def setUp(self):
        self.ch = channel()
        self.peer = can.Bus(interface="virtual", channel=self.ch, receive_own_messages=False)
        self.buses, self.sims = [self.peer], []

    def tearDown(self):
        for s in self.sims:
            s.stop()
        for b in self.buses:
            b.shutdown()

    def ecu(self, refuse=False, dtcs=None, address=0, name=None, keep=False):
        bus = can.Bus(interface="virtual", channel=self.ch)
        self.buses.append(bus)
        events = []
        s = sim.Simulator(bus, address, sim.make_name(name, address=address), keep_address=keep,
                          dtcs=dtcs if dtcs is not None else [sim.DtcPlan(520192, 3, ["amber"])],
                          refuse_clear=refuse, report=lambda event, text, **f: events.append((event, text, f)))
        s.events = events
        self.sims.append(s)
        s.start()
        self.assertTrue(s.wait_claimed(1))
        return s

    def diag(self, *argv):
        return run("--adapter", "virtual:" + self.ch, "--bitrate", "250", "dm", *argv)

    def test_list_sends_nothing(self):
        self.ecu()
        code, out, err = self.diag("list", "--listen", "1.2")
        self.assertEqual(code, 0, err)
        self.assertIn("DM1 heard on virtual:%s in 1.2 s:\n  ECU 0: amber warning on; 1 active code" % self.ch, out)
        self.assertIn("    SPN 520192 FMI 3 (voltage above normal or shorted high) OC 1\n", out)
        sent = []
        while True:
            m = self.peer.recv(0.05)
            if m is None:
                break
            if m.arbitration_id & 0xFF == dm.SERVICE_TOOL_ADDRESS:
                sent.append(m)
        self.assertEqual(sent, [])

    def test_read_and_clear(self):
        ecu = self.ecu(dtcs=[sim.DtcPlan(520192, 3, ["amber"], None, 0, 0.3)])
        time.sleep(0.4)  # the code goes inactive: previously active
        code, out, err = self.diag("read", "--address", "0")
        self.assertEqual(code, 0, err)
        self.assertIn("claimed address 249 (NAME 0x%016X)\n" % dmtool.default_name().value, out)
        self.assertIn("DM2 from 0: lamps off; 1 previously active code\n  SPN 520192 FMI 3 (voltage above normal "
                      "or shorted high) OC 1\n", out)
        code, out, err = self.diag("clear", "--address", "0", "--previous", "--force")
        self.assertEqual(code, 0, err)
        self.assertIn("DM3 (clear previously active DTCs) to 0: ACK\n", out)
        self.assertEqual(ecu.dm.previous, {})
        e = [x for x in ecu.events if x[0] == "dm_clear"]
        self.assertEqual(e[-1][2]["from"], 249)
        # The tool gave its address back: a Cannot Claim with its NAME.
        claims = []
        while True:
            m = self.peer.recv(0.05)
            if m is None:
                break
            if m.arbitration_id == 0x18EEFFFE:
                claims.append(int.from_bytes(bytes(m.data), "little"))
        self.assertIn(dmtool.default_name().value, claims)

    def test_nack_and_no_answer(self):
        self.ecu(refuse=True)
        code, out, err = self.diag("clear", "--address", "0", "--force")
        self.assertEqual(code, 1)
        self.assertIn("NACK from 0", err)
        code, out, err = self.diag("read", "--address", "7", "--dm-timeout", "200")
        self.assertEqual(code, 1)
        self.assertIn("no answer from 7 within 200 ms", err)

    def test_cannot_claim(self):
        # Another ECU keeps 249 with a lower NAME: the tool sends nothing.
        self.ecu(dtcs=[], address=249, name=1, keep=True)
        code, out, err = self.diag("read", "--address", "0", "--source-address", "249")
        self.assertEqual(code, 1)
        self.assertIn("cannot claim address 249", err)
        code, out, err = self.diag("read", "--address", "249", "--source-address", "250", "--dm-timeout", "300")
        self.assertEqual(code, 0, err)
        self.assertIn("claimed address 250", out)

    def test_needs_bitrate(self):
        code, out, err = run("--adapter", "virtual:" + self.ch, "dm", "list")
        self.assertEqual(code, 2)
        self.assertIn("--bitrate", err)


class DbcImport(TempDir):
    def test_dm_pgns_are_problems(self):
        """Vendor DBC with DM1: PGN 65280 offered, 65226 a problem."""
        imported = dbc.load(text=DM_DBC)
        self.assertEqual([m["pgn"] for m in imported.messages], [65280])
        self.assertIn("message DM1 (ID 0x18FECA00) is PGN 65226, diagnostic message DM1 (active DTCs): use "
                      "diagnostics, not rx/tx", imported.problems)
        self.assertFalse([p for p in imported.problems if "attribute SPN" in p])
        self.assertEqual(imported.spns, {520192: "CoolantLevel", 1234: "FirstSpn"})
        sig = imported.messages[0]["signals"]
        self.assertEqual([s.get("spn") for s in sig], [520192, None])

    def test_spn_names(self):
        self.assertEqual(dbc.spn_names(self.dbc_file()), {520192: "CoolantLevel", 1234: "FirstSpn"})
        with self.assertRaises(dbc.ImportFailed):
            dbc.spn_names(os.path.join(self.dir, "missing.dbc"))

    def test_every_dm_pgn(self):
        for pgn in sorted(dm.DM_PGNS):
            with self.subTest(pgn=pgn):
                fid = 0x80000000 | dbc.join_id(6, pgn, 0)
                text = 'VERSION ""\nNS_ :\nBS_:\nBU_: E\nBO_ %d M: 8 E\n SG_ S : 0|8@1+ (1,0) [0|255] "" E\n' % fid
                imported = dbc.load(text=text)
                self.assertEqual(imported.messages, [])
                self.assertTrue(any("diagnostic message %s" % dm.DM_PGNS[pgn] in p for p in imported.problems))


class Declarations(unittest.TestCase):
    def config(self):
        with open(MACHINE_CONFIG, encoding="utf-8") as f:
            return json.load(f)

    def test_watched_engine(self):
        """Network machine watches source 0 with count_location %IB222."""
        cfg = self.config()
        diag = cfg["networks"][0]["j1939"]["diagnostics"]
        self.assertEqual((diag["rx"][0]["source"], diag["rx"][0]["count_location"]), (0, "%IB222"))
        block = declare.st_block(editorproject.declarations(cfg, MACHINE_CONFIG))
        self.assertRegex(block, r"\n  machine_dm0_count +AT %IB222 : USINT;\n")

    def test_every_location(self):
        cfg = self.config()
        j = cfg["networks"][0]["j1939"]
        j["diagnostics"] = {
            "rx": [{"source": 0, "status_location": "%IX230.0", "lamps_location": "%IB231",
                    "flash_location": "%IB232", "count_location": "%IB233", "dtcs_location": "%ID240", "dtcs": 3},
                   {"source_name": 5, "status_location": "%IX230.1"}],
            "dtcs": [{"spn": 520192, "fmi": 3, "active_location": "%QX230.0", "lamps": ["amber"]}],
            "lamps_location": "%QB231", "clear_location": "%IB234"}
        decls = {d["name"]: d for d in declare.declarations(cfg, lambda *a: None, {})}
        want = {"machine_dm0_status": ("%IX230.0", "BOOL"), "machine_dm0_lamps": ("%IB231", "BYTE"),
                "machine_dm0_flash": ("%IB232", "BYTE"), "machine_dm0_count": ("%IB233", "USINT"),
                "machine_dm0_dtc0": ("%ID240", "UDINT"), "machine_dm0_dtc1": ("%ID241", "UDINT"),
                "machine_dm0_dtc2": ("%ID242", "UDINT"), "machine_dm_rx1_status": ("%IX230.1", "BOOL"),
                "machine_dtc_520192_3": ("%QX230.0", "BOOL"), "machine_dm_lamps": ("%QB231", "BYTE"),
                "machine_dm_clears": ("%IB234", "USINT")}
        self.assertEqual({k: (decls[k]["location"], decls[k]["type"]) for k in want}, want)
        self.assertEqual(decls["machine_dm0_dtc0"]["path"], "networks[0].j1939.diagnostics.rx[0].dtcs_location")
        self.assertEqual({d["kind"] for k, d in decls.items() if k in want}, {"j1939"})
        self.assertNotIn("machine_dm0_dtc3", decls)


if __name__ == "__main__":
    unittest.main()
