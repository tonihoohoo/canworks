"""Node-RED flow and package of bridge configs (canworks.nodered;
modbus-bridge-map "Node-RED flow", nodered-blocks): the flow's nodes and the
layout its bridge node carries, host and poll options, the command-line
exports, the package .tgz and its generated layout, the package's value
codec under node against images packed here with struct, and the package's
own node --test suite (tests/nodered/)."""

import contextlib
import copy
import gzip
import io
import json
import os
import re
import shutil
import struct
import subprocess
import tarfile
import tempfile
import unittest

from canworks import __version__, cli, mailboxlayout, modbusmap, nodered

from .test_contract import REPO

DATA = os.path.join(os.path.dirname(__file__), "data")
JS = os.path.join(os.path.dirname(__file__), "nodered")
BRIDGE = os.path.join(DATA, "modbus", "bridge.json")
EXAMPLE = os.path.join(REPO, "examples", "modbus-bridge", "canworks.json")
GOLDEN = os.path.join(DATA, "nodered", "modbus-bridge-example.json")
GOLDEN_MAILBOXES = os.path.join(DATA, "nodered", "modbus-bridge-mailboxes.json")
MAILBOXES_H = os.path.join(REPO, "plugin", "src", "bridge", "mailboxes.h")
MAILBOXES_CPP = os.path.join(REPO, "plugin", "src", "bridge", "mailboxes.cpp")
NODE = shutil.which("node")


def load(path=BRIDGE):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def with_mailboxes(cfg=None):
    """The example with Node-RED as a writer, SDO writes and the mailboxes:
    the config of the package's node tests (tests/nodered/)."""
    cfg = cfg or load(EXAMPLE)
    cfg["bridge"].update({"listen": "127.0.0.1:1502", "writers": ["127.0.0.1"], "sdo_bridge_write": True,
                          "mailboxes": {"requests": 2, "cyclic_jobs": 2, "input_location": "%IB64",
                                        "output_location": "%QB64"}})
    return cfg


def by_type(nodes, typ):
    return [n for n in nodes if n["type"] == typ]


def bridge_layout(nodes):
    return json.loads(by_type(nodes, "canworks-bridge")[0]["layout"])


def check_golden(test, path, text):
    if os.environ.get("CANWORKS_UPDATE_GOLDEN"):
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
    with open(path, encoding="utf-8") as f:
        test.assertEqual(text, f.read(), "regenerate with CANWORKS_UPDATE_GOLDEN=1 when the change is meant")


class FlowShape(unittest.TestCase):
    def test_example_matches_golden(self):
        nodes, _, _ = nodered.flow(load(EXAMPLE), "modbus-bridge-example")
        check_golden(self, GOLDEN, nodered.to_json(nodes))

    def test_mailboxes_match_golden(self):
        nodes, _, _ = nodered.flow(with_mailboxes(), "modbus-bridge-mailboxes")
        check_golden(self, GOLDEN_MAILBOXES, nodered.to_json(nodes))

    def test_nodes(self):
        nodes, notes, lay = nodered.flow(load(EXAMPLE), "line1")
        tab = by_type(nodes, "tab")[0]
        self.assertEqual(tab["label"], "canworks line1")
        self.assertIn(nodered.package_name().replace(".tgz", ""), tab["info"])
        cfg_node = by_type(nodes, "canworks-bridge")[0]
        self.assertEqual((cfg_node["host"], cfg_node["port"], cfg_node["unit"], cfg_node["period"], cfg_node["readOnly"]),
                         ("127.0.0.1", 1502, 1, 10, False))
        self.assertNotIn("z", cfg_node)
        self.assertEqual(json.loads(cfg_node["layout"]), lay)
        self.assertEqual(by_type(nodes, "canworks-in")[0]["bridge"], cfg_node["id"])
        self.assertEqual(by_type(nodes, "canworks-out")[0]["bridge"], cfg_node["id"])
        self.assertTrue(all(n["z"] == tab["id"] for n in nodes if n["type"] not in ("tab", "canworks-bridge")))
        ids = [n["id"] for n in nodes]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertFalse([n for n in nodes if n["type"].startswith("modbus") or n["type"] == "function"],
                         "no node-red-contrib-modbus nodes or generated code")

    def test_layout(self):
        lay = nodered.flow(load(EXAMPLE), "line1")[2]
        self.assertEqual((len(lay["inputs"]), len(lay["outputs"])), (17, 4))
        self.assertEqual((lay["version"], lay["unit"], lay["readOnly"], lay["watchdogMs"]), (__version__, 1, False, 1000))
        self.assertEqual(lay["read"], [[0, 31]])
        self.assertEqual(lay["write"], [[0, 13]])
        self.assertEqual((lay["status"], lay["control"], lay["sdoReq"], lay["sdoResp"]), (24, 6, 12, 48))
        self.assertEqual(lay["live"], [{"net": "field", "b": 32, "nodes": [5, 6]}])
        self.assertEqual(lay["networks"], [{"index": 0, "name": "field", "kinds": ["can", "canopen"]}])
        self.assertIsNone(lay["mailboxes"])
        row = next(r for r in lay["inputs"] if r["n"] == "dio.0x6401:1")
        self.assertEqual(row, {"n": "dio.0x6401:1", "b": 10, "k": "signed", "size": 2, "regs": [5, 5]})

    def test_mailbox_layout(self):
        lay = nodered.flow(with_mailboxes(), "t")[2]
        mb = lay["mailboxes"]
        self.assertEqual(mb["requests"], [{"req": 64, "resp": 64}, {"req": 208, "resp": 208}])
        self.assertEqual(mb["receive"], {"block": 352, "blocks": 1, "ack": 352})
        self.assertEqual(mb["info"], [{"net": 0, "name": "field", "j1939": False, "b": 592}])
        self.assertEqual(mb["cyclic"], {"table": 628, "keepalive": 358, "jobs": 2})
        # Every block is inside a read or write channel.
        def covered(byte, n, channels):
            return any(s * 2 <= byte and byte + n <= (s + c) * 2 for s, c in channels)
        for m in mb["requests"]:
            self.assertTrue(covered(m["resp"], 144, lay["read"]))
            self.assertTrue(covered(m["req"], 144, lay["write"]))
        self.assertTrue(covered(mb["receive"]["block"], 240, lay["read"]))
        self.assertTrue(covered(mb["cyclic"]["keepalive"], 4, lay["write"]))

    def test_read_only(self):
        cfg = load(EXAMPLE)
        cfg["bridge"]["plc_link"] = True
        for cfg in (modbusmap.pack(cfg),):
            nodes, notes, lay = nodered.flow(cfg, "line1")
            self.assertEqual(by_type(nodes, "canworks-out"), [])
            self.assertTrue(by_type(nodes, "canworks-bridge")[0]["readOnly"])
            self.assertEqual((lay["readOnly"], lay["outputs"], lay["write"]), (True, [], []))
            self.assertIn("It only reads: the bridge's writes belong to the PLC program.", by_type(nodes, "tab")[0]["info"])
            self.assertFalse([n for n in notes if "writers" in n], "no writers note for a flow that does not write")
        nodes, _, lay = nodered.flow(load(EXAMPLE), "line1", readonly=True)
        self.assertEqual(by_type(nodes, "canworks-out"), [])

    def test_bit_channels_by_name(self):
        cfg = load(EXAMPLE)
        dio = [n for n in cfg["networks"][0]["nodes"] if n["name"] == "dio"][0]
        dio["tx_pdos"][0]["entries"][0]["bits"] = [{"bit": 3, "name": "jog_x_plus"}]  # 0x6000:1 at %IB8
        lay = nodered.flow(cfg, "line1")[2]
        row = [r for r in lay["inputs"] if r["n"] == "dio.jog_x_plus"][0]
        self.assertEqual((row["k"], row["b"], row["bit"]), ("bit", 8, 3))

    def test_ids_are_stable_per_name(self):
        a = nodered.flow(load(EXAMPLE), "line1")[0]
        b = nodered.flow(load(EXAMPLE), "line1")[0]
        c = nodered.flow(load(EXAMPLE), "line2")[0]
        self.assertEqual([n["id"] for n in a], [n["id"] for n in b])
        self.assertFalse(set(n["id"] for n in a) & set(n["id"] for n in c))

    def test_without_blocks(self):
        cfg = load(EXAMPLE)
        for key in ("status_location", "control_location", "live_lists", "sdo_bridge_location"):
            cfg["bridge"].pop(key)
        lay = nodered.flow(cfg)[2]
        self.assertEqual((lay["status"], lay["control"], lay["sdoReq"], lay["live"]), (None, None, None, []))

    def test_not_a_bridge_config(self):
        cfg = load(EXAMPLE)
        del cfg["bridge"]
        with self.assertRaisesRegex(nodered.FlowError, "not a bridge config"):
            nodered.flow(cfg)


class Options(unittest.TestCase):
    def test_defaults_and_overrides(self):
        cfg = load(EXAMPLE)
        h, port, poll, notes = nodered.options(cfg)
        self.assertEqual((h, port, poll), ("127.0.0.1", 1502, 10))
        self.assertIn("no loopback address", notes[0])
        self.assertEqual(nodered.options(cfg, "192.168.1.5")[:3], ("192.168.1.5", 1502, 10))
        self.assertEqual(nodered.options(cfg, "pi.local:502")[:2], ("pi.local", 502))
        self.assertEqual(nodered.options(cfg, "[fd00::5]:1503")[:2], ("fd00::5", 1503))
        cfg["bridge"]["listen"] = "192.168.1.9:502"
        self.assertEqual(nodered.options(cfg)[:2], ("192.168.1.9", 502))

    def test_writers_notes(self):
        cfg = load(EXAMPLE)
        cfg["bridge"]["writers"] = ["127.0.0.1"]
        self.assertEqual(nodered.options(cfg)[3], [])
        cfg["bridge"]["writers"] = []
        self.assertIn("'writers' is empty", nodered.options(cfg)[3][0])
        self.assertEqual(nodered.options(cfg, readonly=True)[3], [])

    def test_poll_clamped(self):
        cfg = load(EXAMPLE)
        self.assertEqual(nodered.options(cfg, poll_ms=5)[2], 10)
        h, port, poll, notes = nodered.options(cfg, poll_ms=500)
        self.assertEqual(poll, 333)
        self.assertTrue(any("333 ms instead of 500 ms" in n for n in notes))
        cfg["bridge"]["watchdog_ms"] = 0
        self.assertEqual(nodered.options(cfg, poll_ms=5000)[2], 5000)

    def test_bad_port(self):
        with self.assertRaises(nodered.FlowError):
            nodered.options(load(EXAMPLE), "host:99999")


class CommandLine(unittest.TestCase):
    def test_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "line1.json")
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                rc = cli.main(["--config", EXAMPLE, "--export-nodered", path, "--nodered-poll-ms", "50"])
            self.assertEqual(rc, 0)
            text = out.getvalue()
            self.assertIn("17 values in, 4 out", text)
            self.assertIn("no loopback address", text)
            self.assertIn(nodered.package_name(), text)
            self.assertIn("block nodes: NMT (control block), short SDO (SDO registers)\n", text)
            with open(path, encoding="utf-8") as f:
                nodes = json.load(f)
            self.assertEqual(by_type(nodes, "tab")[0]["label"], "canworks line1")
            self.assertEqual(by_type(nodes, "canworks-bridge")[0]["period"], 50)

    def test_package(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(cli.main(["--export-nodered-package", tmp]), 0)
                self.assertEqual(cli.main(["--export-nodered-package", os.path.join(tmp, "x.tgz")]), 0)
            with open(os.path.join(tmp, nodered.package_name()), "rb") as f:
                a = f.read()
            with open(os.path.join(tmp, "x.tgz"), "rb") as f:
                self.assertEqual(f.read(), a)
            self.assertEqual(a, nodered.package_tgz())
            self.assertIn("Manage palette > Install > upload", out.getvalue())

    def test_refusals(self):
        cfg = load(EXAMPLE)
        del cfg["bridge"]
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "c.json")
            with open(src, "w", encoding="utf-8") as f:
                json.dump(cfg, f)
            with self.assertRaisesRegex(cli.Failure, "not a bridge config"):
                cli.run(cli.parser().parse_args(["--config", src, "--export-nodered", os.path.join(tmp, "f.json")]))
            with self.assertRaisesRegex(cli.Failure, "only writes the Node-RED flow"):
                cli.run(cli.parser().parse_args(["--config", EXAMPLE, "--export-nodered", os.path.join(tmp, "f.json"),
                                                 "--check-only"]))
            with self.assertRaisesRegex(cli.Failure, "--nodered-host"):
                cli.run(cli.parser().parse_args(["--config", EXAMPLE, "--export-modbus-map",
                                                 os.path.join(tmp, "m.csv"), "--nodered-host", "x"]))
            with self.assertRaisesRegex(cli.Failure, "give the config"):
                cli.run(cli.parser().parse_args(["--export-nodered", os.path.join(tmp, "f.json")]))


class Package(unittest.TestCase):
    def test_files(self):
        files = dict(nodered.package_files())
        self.assertEqual(sorted(files), ["LICENSE", "README.md", "lib/bridge.js", "lib/codec.js", "lib/jobs.js",
                                         "lib/layout.js", "lib/modbus.js", "lib/texts.js", "nodes/canworks.html",
                                         "nodes/canworks.js", "package.json"])
        pkg = json.loads(files["package.json"])
        self.assertEqual((pkg["name"], pkg["version"]), (nodered.PACKAGE, __version__))
        self.assertNotIn("dependencies", pkg)
        self.assertEqual(pkg["node-red"]["nodes"], {"canworks": "nodes/canworks.js"})
        for f in pkg["files"]:
            self.assertTrue(any(p == f or p.startswith(f + "/") for p in files), f)

    def test_tgz(self):
        a, b = nodered.package_tgz(), nodered.package_tgz()
        self.assertEqual(a, b, "the same bytes for the same version")
        self.assertEqual(gzip.decompress(a)[:8], b"package/")
        with tarfile.open(fileobj=io.BytesIO(a)) as tar:
            members = tar.getmembers()
            self.assertEqual([m.name for m in members], ["package/" + p for p, _ in nodered.package_files()])
            self.assertTrue(all(m.isfile() and m.mode == 0o644 for m in members))
            pkg = json.loads(tar.extractfile("package/package.json").read())
        self.assertEqual(pkg["version"], __version__)

    def test_layout_is_fresh(self):
        with open(os.path.join(nodered.PACKAGE_DIR, "lib", "layout.js"), encoding="utf-8") as f:
            self.assertEqual(f.read(), nodered.layout_js(),
                             "lib/layout.js is stale: run python -m canworks.nodered layout in tools/deploy")

    def test_layout_follows_the_bridge(self):
        with open(MAILBOXES_H, encoding="utf-8") as f:
            h = f.read()
        with open(MAILBOXES_CPP, encoding="utf-8") as f:
            cpp = f.read()

        def const(name):
            return int(re.search(r"\b%s\s*=\s*(0x[0-9a-fA-F]+|\d+)" % name, h).group(1), 0)

        lay = mailboxlayout.client_layout()
        self.assertEqual((lay["mailboxWords"], lay["chunk"], lay["buffer"], lay["receiveWords"], lay["rxHeaderWords"],
                          lay["infoWords"], lay["jobWords"], lay["maxReceivers"]),
                         tuple(const(n) for n in ("kMbWords", "kMbChunk", "kMbBuffer", "kRxWords", "kRxHeaderWords",
                                                   "kInfoWords", "kJobWords", "kMaxReceivers")))
        ops = {re.sub(r"(?<!^)([A-Z])", r"_\1", m.group(1)).lower(): int(m.group(2))
               for m in re.finditer(r"kOp(\w+) = (\d+)", h) if m.group(1) != "None"}
        self.assertEqual(lay["ops"], ops)
        self.assertEqual(lay["states"], {"idle": const("kMbIdle"), "busy": const("kMbBusy"), "done": const("kMbDone"),
                                         "error": const("kMbError")})
        self.assertEqual(lay["rxKinds"], {"can": const("kRxCan"), "j1939": const("kRxJ1939"), "emcy": const("kRxEmcy")})
        self.assertEqual(lay["recordFlags"], {"long": const("kRecLong"), "restart": const("kRecRestart"),
                                              "overflow": const("kRecOverflow")})
        self.assertEqual(lay["rxOpenFlags"], {"can_extended": const("kRxCanExtended"), "j1939_all_pgns": const("kRxJ1939Any"),
                                              "j1939_all_destinations": const("kRxJ1939AllDestinations"),
                                              "j1939_filter_source": const("kRxJ1939FilterSource"),
                                              "emcy_skip_old": const("kRxEmcySkipOld")})
        words = dict(re.findall(r"case kRx(\w+): return (\d+);", cpp))
        self.assertEqual(lay["recordWords"], {"can": int(words["Can"]), "j1939": int(words["J1939"]),
                                              "emcy": int(words["Emcy"])})
        # The batch time's words, the EMCY time's and where each record's body starts (the header's comment).
        self.assertIn("//   %d-%d batch time" % (lay["batchTimeWord"], lay["batchTimeWord"] + 3), h)
        self.assertIn("EMCY (12 words): receive time in UTC microseconds (4)", h)
        self.assertEqual((lay["recordBodyWord"], lay["emcyTimeWord"]), ({"can": 3, "j1939": 3, "emcy": 7}, 3))


def run_codec(rows, image, writes=()):
    proc = subprocess.run([NODE, os.path.join(JS, "codec_run.js")], capture_output=True, text=True, check=False,
                          input=json.dumps({"rows": rows, "image": bytes(image).hex(), "writes": list(writes)}))
    if proc.returncode:
        raise AssertionError("node failed: %s" % proc.stderr)
    out = json.loads(proc.stdout)
    return out["values"], bytes.fromhex(out["image"]), out["errors"]


@unittest.skipUnless(NODE, "node is not installed: the package is not run")
class Codec(unittest.TestCase):
    """lib/codec.js on images packed here with struct: every type of the
    test bridge config, word order, 64-bit, REAL64, scale and offset."""

    def rows(self, cfg):
        return nodered.flow(cfg, "t")[2]

    def test_decode_every_type(self):
        lay = self.rows(load())
        img = bytearray(lay["inBytes"])
        by = {r["n"]: r for r in lay["inputs"]}
        struct.pack_into(">I", img, by["sensor.0x6000:1"]["b"], 0x12345678)
        struct.pack_into(">h", img, by["sensor.0x6000:2"]["b"], -1234)
        img[by["sensor.0x6000:3"]["b"]] = 200
        img[by["sensor.0x6000:4"]["b"]] |= 1 << 3
        img[by["sensor.TPDO1.timeout"]["b"]] |= 1 << by["sensor.TPDO1.timeout"]["bit"]
        img[by["field.state"]["b"]] = 5
        values, _, _ = run_codec(lay["inputs"], img)
        self.assertEqual(values["sensor.0x6000:1"], 0x12345678)
        self.assertEqual(values["sensor.0x6000:2"], -1234)
        self.assertEqual(values["sensor.0x6000:3"], 200)
        self.assertIs(values["sensor.0x6000:4"], True)
        self.assertIs(values["sensor.status"], False)
        self.assertIs(values["sensor.TPDO1.timeout"], True)
        self.assertEqual(values["field.state"], 5)

    def test_low_first(self):
        cfg = load()
        cfg["bridge"]["word_order"] = "low_first"
        lay = self.rows(cfg)
        row = next(r for r in lay["inputs"] if r["n"] == "sensor.0x6000:1")
        img = bytearray(lay["inBytes"])
        img[row["b"]:row["b"] + 4] = bytes([0x56, 0x78, 0x12, 0x34])
        self.assertEqual(run_codec([row], img)[0]["sensor.0x6000:1"], 0x12345678)

    def test_encode_values_and_errors(self):
        lay = self.rows(load())
        rows = lay["outputs"]
        by = {r["n"]: r for r in rows}
        _, img, errors = run_codec(rows, bytes(lay["outBytes"]), [
            ["sensor.0x6200:1", 65535], ["sensor.0x6200:2", True], ["sensor.0x6200:3", 1.5],
            ["sensor.0x6200:1", 65536], ["sensor.0x6200:2", "yes"]])
        self.assertEqual(struct.unpack_from(">H", img, by["sensor.0x6200:1"]["b"])[0], 65535, "the refused value left it")
        self.assertEqual(img[100] & 2, 2)  # %QX100.1
        self.assertEqual(struct.unpack_from(">f", img, by["sensor.0x6200:3"]["b"])[0], 1.5)
        self.assertIn("out of range", errors["sensor.0x6200:1"])
        self.assertIn("true or false", errors["sensor.0x6200:2"])

    def test_64_bit_and_scale(self):
        rows = [
            {"n": "i64", "b": 0, "k": "signed", "size": 8, "regs": [0, 3], "lo": False},
            {"n": "u64", "b": 8, "k": "unsigned", "size": 8, "regs": [4, 7], "lo": True},
            {"n": "r64", "b": 16, "k": "real", "size": 8, "regs": [8, 11], "lo": False},
            {"n": "scaled", "b": 24, "k": "unsigned", "size": 2, "regs": [12, 12], "s": 0.1, "o": -40},
            {"n": "s8", "b": 26, "k": "signed", "size": 1, "regs": [13, 13]},
        ]
        _, raw, errors = run_codec(rows, bytes(28), [["i64", -2], ["u64", "18446744073709551615"], ["r64", 3.25],
                                                     ["scaled", 21.5], ["s8", -3]])
        self.assertEqual(errors, {})
        self.assertEqual(raw[0:8], struct.pack(">q", -2))
        self.assertEqual(raw[8:16], b"\xff" * 8)
        self.assertEqual(raw[16:24], struct.pack(">d", 3.25))
        self.assertEqual(raw[24:26], struct.pack(">H", 615))
        self.assertEqual(raw[26], 0xfd)
        back = run_codec(rows, raw)[0]
        self.assertEqual(back["i64"], -2)
        self.assertEqual(back["u64"], "18446744073709551615")
        self.assertEqual(back["r64"], 3.25)
        self.assertAlmostEqual(back["scaled"], 21.5)
        self.assertEqual(back["s8"], -3)


@unittest.skipUnless(NODE, "node is not installed: the package is not run")
class NodeSuite(unittest.TestCase):
    """The package's node --test suite (tests/nodered/*.test.js): every node
    against a scripted model of the bridge's registers."""

    def test_suite(self):
        tests = sorted(os.path.join(JS, f) for f in os.listdir(JS) if f.endswith(".test.js"))
        proc = subprocess.run([NODE, "--test", "--test-reporter=dot"] + tests, capture_output=True, text=True,
                              check=False, timeout=300)
        self.assertEqual(proc.returncode, 0, proc.stdout[-6000:] + proc.stderr[-3000:])


if __name__ == "__main__":
    unittest.main()
