"""Node-RED flow of bridge configs (canworks.nodered, modbus-bridge-map
"Node-RED flow"): the flow's nodes, host and poll options, the command-line
export, and the generated function code run under node (tests/data/nodered/
harness.js) against register images packed independently here."""

import contextlib
import copy
import io
import json
import os
import shutil
import struct
import subprocess
import tempfile
import unittest

from canworks import cli, nodered

from .test_contract import REPO

DATA = os.path.join(os.path.dirname(__file__), "data")
BRIDGE = os.path.join(DATA, "modbus", "bridge.json")
EXAMPLE = os.path.join(REPO, "examples", "modbus-bridge", "canworks.json")
GOLDEN = os.path.join(DATA, "nodered", "modbus-bridge-example.json")
HARNESS = os.path.join(DATA, "nodered", "harness.js")
NODE = shutil.which("node")


def load(path=BRIDGE):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def by_type(nodes, typ):
    return [n for n in nodes if n["type"] == typ]


def named(nodes, name):
    return next(n for n in nodes if n.get("name") == name)


def run_js(nodes, steps):
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
        json.dump(nodes, f)
        path = f.name
    try:
        proc = subprocess.run([NODE, HARNESS, path], input=json.dumps(steps), capture_output=True, text=True,
                              check=False)
    finally:
        os.unlink(path)
    if proc.returncode:
        raise AssertionError("node failed: %s" % proc.stderr)
    return json.loads(proc.stdout)


class Image:
    """A byte image packed with struct, independent of the generated code."""

    def __init__(self, nbytes):
        self.b = bytearray(nbytes)

    def put(self, row, fmt, value, low_first=False):
        raw = struct.pack(">" + fmt, value)
        if low_first:
            words = [raw[i:i + 2] for i in range(0, len(raw), 2)]
            raw = b"".join(reversed(words))
        self.b[row["byte"]:row["byte"] + len(raw)] = raw

    def bit(self, row, value):
        bit = row["address"] - row["byte"] * 8
        if value:
            self.b[row["byte"]] |= 1 << bit
        else:
            self.b[row["byte"]] &= ~(1 << bit) & 255

    def regs(self, start, count):
        return [struct.unpack(">H", bytes(self.b[2 * i:2 * i + 2]))[0] for i in range(start, start + count)]


def rows_by_name(cfg):
    from canworks import modbusmap
    return {r["name"]: r for r in modbusmap.register_map(cfg)}


class FlowShape(unittest.TestCase):
    def test_example_matches_golden(self):
        nodes, notes, _ = nodered.flow(load(EXAMPLE), "modbus-bridge-example")
        text = nodered.to_json(nodes)
        if os.environ.get("CANWORKS_UPDATE_GOLDEN"):
            with open(GOLDEN, "w", encoding="utf-8", newline="\n") as f:
                f.write(text)
        with open(GOLDEN, encoding="utf-8") as f:
            self.assertEqual(text, f.read(), "regenerate with CANWORKS_UPDATE_GOLDEN=1 when the change is meant")

    def test_nodes(self):
        nodes, notes, sp = nodered.flow(load(EXAMPLE), "line1")
        tab = by_type(nodes, "tab")[0]
        self.assertEqual(tab["label"], "canworks line1")
        client = by_type(nodes, "modbus-client")[0]
        self.assertEqual((client["tcpHost"], client["tcpPort"], client["unit_id"]), ("127.0.0.1", "1502", "1"))
        self.assertNotIn("z", client)
        reads = [n for n in by_type(nodes, "modbus-read") if n["dataType"] == "InputRegister"]
        self.assertEqual([(n["adr"], n["quantity"], n["rate"]) for n in reads], [("0", "31", "100")])
        backs = [n for n in by_type(nodes, "modbus-read") if n["dataType"] == "HoldingRegister"]
        self.assertEqual([(n["adr"], n["quantity"]) for n in backs], [("0", "13")])
        self.assertEqual(sorted(n["name"] for n in by_type(nodes, "link out")), ["canworks in", "canworks sdo result"])
        self.assertEqual(sorted(n["name"] for n in by_type(nodes, "link in")),
                         ["canworks nmt", "canworks out", "canworks sdo"])
        self.assertEqual(named(nodes, "tick")["repeat"], "0.1")
        self.assertTrue(all(n["z"] == tab["id"] for n in nodes if n["type"] not in ("tab", "modbus-client")))
        ids = [n["id"] for n in nodes]
        self.assertEqual(len(ids), len(set(ids)))
        # Every wire points at a node of the flow.
        for n in nodes:
            for out in n.get("wires", []):
                for target in out:
                    self.assertIn(target, ids, n["name"])
        self.assertEqual(len(sp["inputs"]), 17)
        self.assertEqual(len(sp["outputs"]), 4)

    def test_bit_channels_by_name(self):
        cfg = load(EXAMPLE)
        dio = [n for n in cfg["networks"][0]["nodes"] if n["name"] == "dio"][0]
        dio["tx_pdos"][0]["entries"][0]["bits"] = [{"bit": 3, "name": "jog_x_plus"}]  # 0x6000:1 at %IB8
        _, _, sp = nodered.flow(cfg, "line1")
        row = [r for r in sp["inputs"] if r["n"] == "dio.jog_x_plus"][0]
        self.assertEqual((row["k"], row["b"], row["bit"]), ("bit", 8, 3))

    def test_ids_are_stable_per_name(self):
        a, _, _ = nodered.flow(load(EXAMPLE), "line1")
        b, _, _ = nodered.flow(load(EXAMPLE), "line1")
        c, _, _ = nodered.flow(load(EXAMPLE), "line2")
        self.assertEqual([n["id"] for n in a], [n["id"] for n in b])
        self.assertFalse(set(n["id"] for n in a) & set(n["id"] for n in c))

    def test_without_blocks(self):
        cfg = load(EXAMPLE)
        for key in ("status_location", "control_location", "live_lists", "sdo_bridge_location"):
            cfg["bridge"].pop(key)
        nodes, _, _ = nodered.flow(cfg)
        self.assertEqual([n["name"] for n in by_type(nodes, "link in")], ["canworks out"])
        self.assertEqual([n["name"] for n in by_type(nodes, "link out")], ["canworks in"])

    def test_not_a_bridge_config(self):
        cfg = load(EXAMPLE)
        del cfg["bridge"]
        with self.assertRaisesRegex(nodered.FlowError, "not a bridge config"):
            nodered.flow(cfg)


class Options(unittest.TestCase):
    def test_defaults_and_overrides(self):
        cfg = load(EXAMPLE)
        h, port, poll, notes = nodered.options(cfg)
        self.assertEqual((h, port, poll), ("127.0.0.1", 1502, 100))
        self.assertIn("no loopback address", notes[0])
        self.assertEqual(nodered.options(cfg, "192.168.1.5")[:3], ("192.168.1.5", 1502, 100))
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

    def test_poll_clamped(self):
        cfg = load(EXAMPLE)
        self.assertEqual(nodered.options(cfg, poll_ms=5)[2], 10)
        h, port, poll, notes = nodered.options(cfg, poll_ms=500)
        self.assertEqual(poll, 333)
        self.assertTrue(any("333 ms instead of 500 ms" in n for n in notes))
        cfg["bridge"]["watchdog_ms"] = 0
        self.assertEqual(nodered.options(cfg, poll_ms=5000)[2], 5000)
        _, _, sp = nodered.flow(cfg, poll_ms=5000)
        self.assertEqual((sp["keepalive"], sp["tickMs"]), (False, 5000))

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
            with open(path, encoding="utf-8") as f:
                nodes = json.load(f)
            self.assertEqual(by_type(nodes, "tab")[0]["label"], "canworks line1")
            self.assertEqual(by_type(nodes, "modbus-read")[0]["rate"], "50")

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
                cli.run(cli.parser().parse_args(["--config", EXAMPLE, "--export-modbus-map", os.path.join(tmp, "m.csv"),
                                        "--nodered-host", "x"]))


@unittest.skipUnless(NODE, "node is not installed: the Node-RED function code is not run")
class FunctionCode(unittest.TestCase):
    """The generated function bodies under node, on the test bridge config."""

    def setUp(self):
        self.cfg = load()
        self.cfg["bridge"]["writers"] = ["127.0.0.1"]
        self.rows = rows_by_name(self.cfg)

    def flow(self, cfg=None):
        nodes, _, sp = nodered.flow(cfg or self.cfg, "t")
        return nodes, sp

    def inputs(self, low_first=False):
        r = self.rows
        img = Image(80)
        img.put(r["sensor.0x6000:1"], "I", 0x12345678, low_first)
        img.put(r["sensor.0x6000:2"], "h", -1234)
        img.put(r["sensor.0x6000:3"], "B", 200)
        img.put(r["field.state"], "B", 5)
        img.put(r["sensor.state"], "B", 127)
        img.bit(r["sensor.0x6000:4"], True)
        img.bit(r["sensor.status"], False)
        img.bit(r["sensor.TPDO1.timeout"], True)
        st = r["bridge.status"]["byte"]
        img.b[st:st + 8] = bytes([1, 2, 0, 9, 0, 3, 0, 0])
        live = r["bridge.live_list.field"]["byte"]
        img.b[live + 0] = 1 << 5      # node 5 operational
        return img

    def test_decode_every_type_and_only_changes(self):
        nodes, sp = self.flow()
        img = self.inputs()
        regs = img.regs(2, 34)
        out = run_js(nodes, [{"node": "decode 2-35", "msg": {"payload": regs}},
                             {"node": "decode 2-35", "msg": {"payload": regs}}])
        first = {m["topic"]: m["payload"] for m in out["results"][0][0]}
        self.assertEqual(first["sensor.0x6000:1"], 0x12345678)
        self.assertEqual(first["sensor.0x6000:2"], -1234)
        self.assertEqual(first["sensor.0x6000:3"], 200)
        self.assertEqual(first["field.state"], 5)
        self.assertEqual(first["sensor.state"], 127)
        self.assertIs(first["sensor.0x6000:4"], True)
        self.assertIs(first["sensor.status"], False)
        self.assertIs(first["sensor.TPDO1.timeout"], True)
        self.assertEqual(first["bridge.state"], "running")
        self.assertEqual(first["bridge.clients"], 2)
        self.assertEqual(first["bridge.command"], {"counter": 3, "result": "ok"})
        self.assertIs(first["field.node5.operational"], True)
        self.assertEqual(out["results"][1], [[], []])
        self.assertEqual(out["status"]["decode 2-35"]["text"], "running, 2 clients")

    def test_low_first(self):
        cfg = copy.deepcopy(self.cfg)
        cfg["bridge"]["word_order"] = "low_first"
        nodes, sp = self.flow(cfg)
        out = run_js(nodes, [{"node": "decode 2-35", "msg": {"payload": self.inputs(True).regs(2, 34)}}])
        first = {m["topic"]: m["payload"] for m in out["results"][0][0]}
        self.assertEqual(first["sensor.0x6000:1"], 0x12345678)

    def test_change_emits_one_message(self):
        nodes, sp = self.flow()
        img = self.inputs()
        a = img.regs(2, 34)
        img.put(self.rows["sensor.0x6000:2"], "h", 77)
        b = img.regs(2, 34)
        out = run_js(nodes, [{"node": "decode 2-35", "msg": {"payload": a}},
                             {"node": "decode 2-35", "msg": {"payload": b}}])
        self.assertEqual(out["results"][1][0], [{"topic": "sensor.0x6000:2", "payload": 77}])

    def seed(self, img=None):
        regs = (img or Image(102)).regs(0, 51)
        return {"node": "seed 0-50", "msg": {"payload": regs}}

    def written(self, msgs):
        """The output image after the write messages."""
        img = Image(102)
        for m in msgs:
            p = m["payload"]
            self.assertEqual((p["fc"], p["unitid"]), (16, 1))
            for i, v in enumerate(p["value"]):
                img.b[(p["address"] + i) * 2:(p["address"] + i) * 2 + 2] = struct.pack(">H", v)
        return img

    def test_writes_wait_for_read_back(self):
        nodes, sp = self.flow()
        held = Image(102)
        held.put(self.rows["sensor.0x6200:1"], "H", 4321)
        out = run_js(nodes, [
            {"node": "encode", "msg": {"topic": "sensor.0x6200:3", "payload": 1.5}},
            {"node": "encode", "msg": {"topic": "canworks_tick"}},
            self.seed(held),
        ])
        self.assertEqual(out["results"][0], [[]])
        self.assertEqual(out["results"][1], [[]])
        self.assertEqual(out["status"]["encode"]["text"], "waiting for the bridge")
        seeded = out["results"][2][0]
        self.assertEqual(seeded, [{"topic": "canworks_seeded"}])
        out = run_js(nodes, [{"node": "encode", "msg": {"topic": "sensor.0x6200:3", "payload": 1.5}},
                             self.seed(held), {"node": "encode", "msg": seeded[0]}])
        img = self.written(out["results"][2][0])
        self.assertEqual(struct.unpack(">f", bytes(img.b[4:8]))[0], 1.5)
        self.assertEqual(struct.unpack(">H", bytes(img.b[0:2]))[0], 4321, "read-back value kept")

    def test_encode_values_and_errors(self):
        nodes, sp = self.flow()
        out = run_js(nodes, [
            self.seed(), {"node": "encode", "msg": {"topic": "canworks_seeded"}},
            {"node": "encode", "msg": {"topic": "sensor.0x6200:1", "payload": 65535}},
            {"node": "encode", "msg": {"topic": "sensor.0x6200:2", "payload": True}},
            {"node": "encode", "msg": {"topic": "sensor.0x6200:1", "payload": 65536}},
            {"node": "encode", "msg": {"topic": "nope", "payload": 1}},
            {"node": "encode", "msg": {"topic": "canworks_tick"}},
        ])
        img = self.written(out["results"][2][0])
        self.assertEqual(struct.unpack(">H", bytes(img.b[0:2]))[0], 65535)
        img = self.written(out["results"][3][0])
        self.assertEqual(img.b[100] & 2, 2)      # %QX100.1
        self.assertEqual(out["results"][4], [[]])
        self.assertEqual(out["results"][5], [[]])
        self.assertTrue(any("out of range" in w for w in out["warnings"]))
        self.assertTrue(any("no output named \"nope\"" in w for w in out["warnings"]))
        keep = self.written(out["results"][6][0])
        self.assertEqual(struct.unpack(">H", bytes(keep.b[0:2]))[0], 65535)
        self.assertEqual(keep.b[100] & 2, 2)

    def test_no_keepalive_without_watchdog(self):
        cfg = copy.deepcopy(self.cfg)
        cfg["bridge"]["watchdog_ms"] = 0
        nodes, sp = self.flow(cfg)
        out = run_js(nodes, [self.seed(), {"node": "encode", "msg": {"topic": "canworks_tick"}}])
        self.assertEqual(out["results"][1], [[]])

    def test_nmt(self):
        nodes, sp = self.flow()
        held = Image(102)
        ctl = self.rows["bridge.control"]["byte"]
        held.b[ctl:ctl + 2] = struct.pack(">H", 41)
        out = run_js(nodes, [
            {"node": "nmt", "msg": {"payload": {"network": "field", "node": 4, "command": "stop"}}},
            self.seed(held),
            {"node": "nmt", "msg": {"payload": {"network": "field", "node": 4, "command": "stop"}}},
            {"node": "nmt", "msg": {"payload": {"command": "idle"}}},
            {"node": "nmt", "msg": {"payload": {"network": "nope", "node": 4, "command": "start"}}},
            {"node": "nmt", "msg": {"payload": {"network": "field", "node": 4, "command": "jump"}}},
        ])
        self.assertEqual(out["results"][0], [[]])
        img = self.written(out["results"][2][0])
        self.assertEqual(bytes(img.b[ctl:ctl + 6]), bytes([0, 42, 4, 0, 4, 0]))
        img = self.written(out["results"][3][0])
        self.assertEqual(bytes(img.b[ctl:ctl + 6]), bytes([0, 43, 2, 0, 0, 0]))
        self.assertEqual(len(out["warnings"]), 3)

    def test_sdo_read_write_and_timeout(self):
        cfg = copy.deepcopy(self.cfg)
        cfg["bridge"]["sdo_bridge_location"] = {"request": "%QB20", "response": "%IB72"}
        self.rows = rows_by_name(cfg)
        nodes, sp = self.flow(cfg)
        req = self.rows["bridge.sdo_bridge.request"]["byte"]
        resp = self.rows["bridge.sdo_bridge.response"]["byte"]
        name = "decode %d-%d" % (sp["read"][0][0], sp["read"][0][0] + sp["read"][0][1] - 1)
        start, count = sp["read"][0]

        def answer(counter, status, abort=0, value=0):
            img = self.inputs()
            img.b.extend(bytes(200))
            img.b[resp:resp + 14] = struct.pack(">HBBIIH", counter, status, 0, abort, value, 0)
            return {"node": name, "msg": {"payload": img.regs(start, count)}}

        seed = {"node": "seed 0-50", "msg": {"payload": Image(102).regs(0, 51)}}
        out = run_js(nodes, [
            seed,
            {"node": "sdo", "msg": {"topic": "serial", "payload": {"network": "field", "node": 4, "index": 0x1018,
                                                                  "subindex": 4}}},
            {"node": "sdo", "msg": {"payload": {"network": "field", "node": 4, "index": 0x6200, "subindex": 1,
                                                "value": 7, "length": 1}}},
            answer(1, 1),
            answer(1, 2, 0, 123456),
            {"node": "sdo", "msg": {"topic": "canworks_tick"}},
            answer(2, 3, 0x06020000),
            {"node": "sdo", "msg": {"payload": {"network": "field", "node": 4, "index": 0x1000}}, "now": 1000000},
            {"node": "sdo", "msg": {"topic": "canworks_tick"}, "now": 1000000 + sp["sdoTimeoutMs"] + 1},
            {"node": "sdo", "msg": {"payload": {"network": "field", "node": 200, "index": 1}}},
        ])
        first = self.written(out["results"][1][0])
        self.assertEqual(bytes(first.b[req:req + 14]),
                         bytes([0, 1, 1, 0, 4, 4, 0x10, 0x18, 0, 0, 0, 0, 0, 0]))
        self.assertEqual(out["results"][2], [[], []], "second request waits for the first")
        self.assertEqual(out["results"][3][1], [], "busy: no result yet")
        self.assertEqual(out["results"][4][1], [{"topic": "serial", "payload": 123456, "sdo": {
            "status": "done", "abort": 0, "abortText": "",
            "request": {"network": "field", "node": 4, "index": 0x1018, "subindex": 4}}}])
        second = self.written(out["results"][5][0])
        self.assertEqual(bytes(second.b[req:req + 14]),
                         bytes([0, 2, 2, 0, 4, 1, 0x62, 0x00, 1, 0, 0, 0, 0, 7]))
        aborted = out["results"][6][1][0]
        self.assertEqual((aborted["payload"], aborted["sdo"]["status"], aborted["sdo"]["abortText"]),
                         (None, "aborted", "0x06020000"))
        self.assertEqual(out["results"][8][1][0]["sdo"]["status"], "timeout")
        self.assertTrue(any("node must be 1-127" in w for w in out["warnings"]))


@unittest.skipUnless(NODE, "node is not installed: the Node-RED function code is not run")
class Conversions(unittest.TestCase):
    """decodeRow/encodeRow on rows the test configs do not have: 64-bit,
    REAL64, scale and offset, signed bytes."""

    def run_lib(self, rows, values, nbytes=16):
        sp = {"unit": 1, "inBytes": nbytes, "outBytes": nbytes, "inputs": rows, "outputs": rows,
              "read": [[0, nbytes // 2]], "write": [[0, nbytes // 2]], "status": None, "control": None,
              "sdoReq": None, "sdoResp": None, "live": [], "networks": {}, "masters": [], "sdoTimeoutMs": 2000,
              "keepalive": True, "tickMs": 100}
        nodes = [
            {"type": "function", "name": "seed", "outputs": 1, "initialize": nodered.START_CODE,
             "func": nodered.function_body(sp, nodered.SEED, 0)},
            {"type": "function", "name": "encode", "outputs": 1, "func": nodered.function_body(sp, nodered.ENCODE)},
            {"type": "function", "name": "decode", "outputs": 2, "func": nodered.function_body(sp, nodered.DECODE, 0)},
        ]
        steps = [{"node": "seed", "msg": {"payload": [0] * (nbytes // 2)}},
                 {"node": "encode", "msg": {"topic": "canworks_seeded"}}]
        steps += [{"node": "encode", "msg": {"topic": n, "payload": v}} for n, v in values]
        out = run_js(nodes, steps)
        regs = [0] * (nbytes // 2)
        for res in out["results"][2:]:
            for m in res[0]:
                p = m["payload"]
                regs[p["address"]:p["address"] + p["quantity"]] = p["value"]
        back = run_js(nodes, [{"node": "decode", "msg": {"payload": regs}}])
        return bytes(b for r in regs for b in struct.pack(">H", r)), \
            {m["topic"]: m["payload"] for m in back["results"][0][0]}, out["warnings"]

    def test_64_bit_and_scale(self):
        rows = [
            {"n": "i64", "b": 0, "k": "signed", "size": 8, "regs": [0, 3], "lo": False},
            {"n": "u64", "b": 8, "k": "unsigned", "size": 8, "regs": [4, 7], "lo": True},
            {"n": "r64", "b": 16, "k": "real", "size": 8, "regs": [8, 11], "lo": False},
            {"n": "scaled", "b": 24, "k": "unsigned", "size": 2, "regs": [12, 12], "s": 0.1, "o": -40},
            {"n": "s8", "b": 26, "k": "signed", "size": 1, "regs": [13, 13]},
        ]
        raw, back, warnings = self.run_lib(rows, [("i64", -2), ("u64", "18446744073709551615"),
                                                  ("r64", 3.25), ("scaled", 21.5), ("s8", -3)], 28)
        self.assertEqual(warnings, [])
        self.assertEqual(raw[0:8], struct.pack(">q", -2))
        self.assertEqual(raw[8:16], b"\xff" * 8)
        self.assertEqual(raw[16:24], struct.pack(">d", 3.25))
        self.assertEqual(raw[24:26], struct.pack(">H", 615))
        self.assertEqual(raw[26], 0xfd)
        self.assertEqual(back["i64"], -2)
        self.assertEqual(back["u64"], "18446744073709551615")
        self.assertEqual(back["r64"], 3.25)
        self.assertAlmostEqual(back["scaled"], 21.5)
        self.assertEqual(back["s8"], -3)

    def test_low_first_32(self):
        rows = [{"n": "v", "b": 0, "k": "unsigned", "size": 4, "regs": [0, 1], "lo": True}]
        raw, back, _ = self.run_lib(rows, [("v", 0x12345678)], 4)
        self.assertEqual(raw, bytes([0x56, 0x78, 0x12, 0x34]))
        self.assertEqual(back["v"], 0x12345678)


if __name__ == "__main__":
    unittest.main()
