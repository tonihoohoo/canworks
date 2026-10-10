"""The device error history (0x1003): the shared helper with a fake client,
canworks-diag errors against the fake plugin and on a local adapter, and the
EMCY COB-ID line of canworks-diag status (add-emcy-history)."""

import io
import json
import os
import time
import unittest
from contextlib import redirect_stderr
from unittest import mock

from canworks import diag, errorfield

from .fake_diag import TOKEN, FakePlugin

try:
    import can  # noqa: F401
except ImportError:  # the local bus tests need python-can
    can = None


def u32(v):
    return v.to_bytes(4, "little")


class FakeClient:
    """sdo_read / sdo_write over a dict {(node, index, sub): bytes}, with
    aborts by key, as diag.Client and localbus.LocalBus answer them."""

    def __init__(self, objects=None, aborts=None, refuse=None):
        self.objects = dict(objects or {})
        self.aborts = dict(aborts or {})
        self.refuse = refuse
        self.reads, self.writes = [], []

    def sdo_read(self, node, index, subindex, timeout_ms=1000):
        self.reads.append((node, index, subindex))
        base = {"node": node, "index": index, "subindex": subindex}
        key = (node, index, subindex)
        if key in self.aborts:
            return dict(base, success=False, abort_code=self.aborts[key], error=diag.abort_text(self.aborts[key]))
        if key not in self.objects:
            return dict(base, success=False, abort_code=0x06020000, error="object does not exist")
        return dict(base, success=True, data=diag.hex_bytes(self.objects[key]))

    def sdo_write(self, node, index, subindex, data, timeout_ms=1000, force=None):
        if self.refuse:
            raise diag.DiagError("refused", self.refuse)
        self.writes.append((node, index, subindex, bytes(data), force))
        self.objects[(node, index, subindex)] = bytes(data)
        return {"node": node, "index": index, "subindex": subindex, "success": True}


def history(node, *values):
    objs = {(node, 0x1003, 0): bytes([len(values)])}
    for i, v in enumerate(values):
        objs[(node, 0x1003, i + 1)] = u32(v)
    return objs


class Helper(unittest.TestCase):
    def test_two_entries(self):
        c = FakeClient(history(5, 0x00004210, 0x00125000))
        res = errorfield.read(c, 5)
        self.assertEqual(res["count"], 2)
        self.assertTrue(res["history"])
        self.assertIsNone(res["failed"])
        self.assertEqual(res["entries"], [
            {"subindex": 1, "value": 0x4210, "code": 0x4210, "class": "temperature", "info": 0},
            {"subindex": 2, "value": 0x125000, "code": 0x5000, "class": "device hardware", "info": 0x12}])
        text = errorfield.lines(res)
        self.assertEqual(text[0], "node 5 error history (0x1003): count 2, newest first")
        self.assertIn("0x4210  temperature", text[1])
        self.assertIn("information 0x0000", text[1])
        self.assertIn("0x5000  device hardware", text[2])
        self.assertIn("information 0x0012", text[2])

    def test_count_zero(self):
        c = FakeClient(history(5))
        res = errorfield.read(c, 5)
        self.assertEqual((res["count"], res["entries"], res["failed"]), (0, [], None))
        self.assertEqual(c.reads, [(5, 0x1003, 0)])
        self.assertEqual(errorfield.lines(res), ["node 5 error history (0x1003): count 0"])

    def test_abort_on_sub_0(self):
        res = errorfield.read(FakeClient(), 5)
        self.assertFalse(res["history"])
        self.assertIsNone(res["failed"])
        self.assertEqual(errorfield.lines(res), ["node 5 has no error history (0x1003)"])

    def test_other_failure_on_sub_0(self):
        c = FakeClient(aborts={(5, 0x1003, 0): 0x08000000})
        res = errorfield.read(c, 5)
        self.assertTrue(res["history"])
        self.assertIsNone(res["count"])
        self.assertEqual(res["failed"]["abort_code"], 0x08000000)
        self.assertEqual(res["failed"]["reason"], "abort 0x08000000: general error")

    def test_abort_on_entry_3(self):
        objs = history(5, 0x1000, 0x2310, 0x3210, 0x4210)
        c = FakeClient(objs, aborts={(5, 0x1003, 3): 0x06090011})
        res = errorfield.read(c, 5)
        self.assertEqual(res["count"], 4)
        self.assertEqual([e["subindex"] for e in res["entries"]], [1, 2])
        self.assertEqual(res["failed"], {"subindex": 3, "reason": "abort 0x06090011: sub-index does not exist",
                                         "abort_code": 0x06090011, "abort_text": "sub-index does not exist"})
        self.assertNotIn((5, 0x1003, 4), c.reads)
        self.assertEqual(errorfield.lines(res)[-1],
                         "  sub 3: abort 0x06090011: sub-index does not exist; the list ends here")

    def test_at_most_254(self):
        objs = {(5, 0x1003, 0): b"\xff"}
        objs.update({(5, 0x1003, s): u32(0x1000) for s in range(1, 256)})
        c = FakeClient(objs)
        res = errorfield.read(c, 5)
        self.assertEqual(len(res["entries"]), 254)
        self.assertNotIn((5, 0x1003, 255), c.reads)
        self.assertIn("only sub-indices 1-254", errorfield.lines(res)[-1])

    def test_clear(self):
        c = FakeClient(history(5, 0x4210))
        errorfield.clear(c, 5, force=True)
        self.assertEqual(c.writes, [(5, 0x1003, 0, b"\x00", True)])
        self.assertEqual(errorfield.read(c, 5)["count"], 0)

    def test_clear_refused(self):
        c = FakeClient(history(5, 0x4210), refuse="changes not allowed")
        with self.assertRaises(diag.DiagError) as e:
            errorfield.clear(c, 5)
        self.assertEqual(str(e.exception), "changes not allowed")

    def test_clear_aborted(self):
        c = FakeClient(history(5, 0x4210))
        c.sdo_write = lambda *a, **k: {"success": False, "abort_code": 0x06090030}
        with self.assertRaises(diag.DiagError) as e:
            errorfield.clear(c, 5)
        self.assertIn("node 5 0x1003:0: abort 0x06090030", str(e.exception))

    def test_emcy_class_still_in_diag(self):
        self.assertIs(errorfield.emcy_class, diag.emcy_class)


def run(*argv):
    """diag.main as the command runs it: (exit code, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    with mock.patch.dict(os.environ, {diag.TOKEN_ENV: TOKEN}), mock.patch("sys.stdout", out), redirect_stderr(err):
        code = diag.main(list(argv))
    return code, out.getvalue(), err.getvalue()


def plugin(allow_changes=False):
    fp = FakePlugin(allow_changes=allow_changes)
    for (_, index, sub), v in history(2, 0x00004210, 0x00125000).items():
        fp.objects[(2, index, sub)] = v
    return fp


class Cli(unittest.TestCase):
    def test_read(self):
        with plugin() as fp:
            code, out, err = run("--runtime", fp.runtime, "errors", "2")
        self.assertEqual(code, 0, err)
        lines = out.splitlines()
        self.assertEqual(lines[0], "node 2 error history (0x1003): count 2, newest first")
        self.assertRegex(lines[1], r"sub 1 +0x4210  temperature +information 0x0000")
        self.assertRegex(lines[2], r"sub 2 +0x5000  device hardware +information 0x0012")

    def test_json(self):
        with plugin() as fp:
            code, out, err = run("--runtime", fp.runtime, "errors", "2", "--json")
        self.assertEqual(code, 0, err)
        res = json.loads(out)
        self.assertEqual(res["count"], 2)
        self.assertEqual(res["entries"][1]["info"], 0x12)

    def test_no_history(self):
        with FakePlugin() as fp:
            code, out, err = run("--runtime", fp.runtime, "errors", "2")
        self.assertEqual(code, 0, err)
        self.assertEqual(out, "node 2 has no error history (0x1003)\n")

    def test_no_answer(self):
        with FakePlugin() as fp:
            code, out, err = run("--runtime", fp.runtime, "errors", "5")
        self.assertEqual(code, 1)
        self.assertIn("node 5 0x1003:0: timeout", err)

    def test_clear_read_only(self):
        with plugin() as fp:
            code, out, err = run("--runtime", fp.runtime, "errors", "2", "--clear")
            self.assertEqual(code, 1)
            self.assertIn("changes not allowed", err)
            self.assertEqual(fp.objects[(2, 0x1003, 0)], b"\x02")

    def test_clear_operational(self):
        with plugin(allow_changes=True) as fp:
            fp.force_running = True  # node 2 is OPERATIONAL in the fake status
            code, out, err = run("--runtime", fp.runtime, "errors", "2", "--clear")
            self.assertEqual(code, 1)
            self.assertIn("node 2 is OPERATIONAL", err)
            self.assertIn("force needed; add --force to go ahead", err)
            self.assertEqual(fp.objects[(2, 0x1003, 0)], b"\x02")
            code, out, err = run("--runtime", fp.runtime, "errors", "2", "--clear", "--force")
            self.assertEqual(code, 0, err)
            self.assertEqual(out.splitlines(), ["node 2: error history (0x1003) cleared",
                                                "node 2 error history (0x1003): count 0"])
            writes = [r for r in fp.requests if r["op"] == "sdo_write"]
            self.assertEqual(writes[-1]["data"], "00")
            self.assertIs(writes[-1]["force"], True)
            self.assertEqual((writes[-1]["index"], writes[-1]["subindex"]), (0x1003, 0))
            self.assertIn(("sdo_write", 2), fp.forced)

    def test_global_force(self):
        with plugin(allow_changes=True) as fp:
            fp.force_running = True
            code, out, err = run("--runtime", fp.runtime, "--force", "errors", "2", "--clear")
            self.assertEqual(code, 0, err)


class StatusLine(unittest.TestCase):
    def node(self, **kw):
        return dict({"node_id": 5}, **kw)

    def test_text(self):
        t = diag.emcy_cob_id_text
        self.assertEqual(t(self.node()), "")  # an older plugin
        self.assertEqual(t(self.node(emcy_cob_id={"value": 0x85, "source": "default", "valid": True})), "")
        self.assertEqual(t(self.node(emcy_cob_id={"value": 0xC5, "source": "device", "valid": True})),
                         "EMCY COB-ID 0xC5 (device)")
        self.assertEqual(t(self.node(emcy_cob_id={"value": 0x85, "source": "default", "valid": False})),
                         "EMCY COB-ID 0x85 (default, off on the device)")

    def test_status(self):
        with FakePlugin() as fp:
            fp.status["nodes"][0]["emcy_cob_id"] = {"value": 0xC5, "source": "device", "valid": True}
            fp.status["nodes"][1]["emcy_cob_id"] = {"value": 0x97, "source": "default", "valid": True}
            code, out, err = run("--runtime", fp.runtime, "status")
        self.assertEqual(code, 0, err)
        self.assertIn("node 2: EMCY COB-ID 0xC5 (device)\n", out)
        self.assertNotIn("node 23: EMCY", out)


@unittest.skipIf(can is None, "needs python-can")
class LocalAdapter(unittest.TestCase):
    def setUp(self):
        from .fake_canopen import FakeDevice
        from .test_localbus import channel
        self.ch = channel()
        self.dev = FakeDevice(self.ch, 5, od={(i, s): v for (_, i, s), v in history(5, 0x4210, 0x125000).items()},
                              heartbeat_s=0.05)

    def tearDown(self):
        self.dev.close()

    def cli(self, *argv):
        return run("--adapter", "virtual:" + self.ch, "--bitrate", "250", *argv)

    def test_read_and_clear(self):
        code, out, err = self.cli("errors", "5")
        self.assertEqual(code, 0, err)
        self.assertIn("count 2, newest first", out)
        self.assertRegex(out, r"sub 2 +0x5000  device hardware +information 0x0012")
        code, out, err = self.cli("errors", "5", "--clear")
        self.assertEqual(code, 1)
        self.assertIn("changes not allowed", err)
        self.dev.state = 5
        time.sleep(0.1)
        code, out, err = self.cli("--allow-changes", "errors", "5", "--clear")
        self.assertEqual(code, 1)
        self.assertIn("node 5 is OPERATIONAL", err)
        self.assertEqual(self.dev.od[(0x1003, 0)], b"\x02")
        code, out, err = self.cli("--allow-changes", "errors", "5", "--clear", "--force")
        self.assertEqual(code, 0, err)
        self.assertIn("count 0", out)
        self.assertEqual(self.dev.od[(0x1003, 0)], b"\x00")


if __name__ == "__main__":
    unittest.main()
