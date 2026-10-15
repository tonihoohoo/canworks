"""canworks-diag send and send-stop against a fake
plugin (add-raw-frames-bitrate-detect task 3.1)."""

import io
import json
import unittest
from contextlib import redirect_stderr
from unittest import mock

from canworks import diag

from .fake_diag import TWO_NETWORKS, FakePlugin
from .test_diag import run


class Values(unittest.TestCase):
    def test_frame_id_and_data(self):
        self.assertEqual(diag.parse_frame_id("0x60A"), 0x60A)
        self.assertEqual(diag.parse_frame_id(1546), 0x60A)
        self.assertEqual(diag.parse_frame_id("0x1ABCDEF", ext=True), 0x1ABCDEF)
        for bad, ext in (("0x800", False), ("0x20000000", True), ("60G", False), (True, False), (-1, False)):
            with self.assertRaises(ValueError, msg=bad):
                diag.parse_frame_id(bad, ext)
        for parts in (["40 18 10 01"], ["40181001"], ["40", "18", "10", "01"], "40 1810 01"):
            self.assertEqual(diag.parse_frame_data(parts), b"\x40\x18\x10\x01", parts)
        self.assertEqual(diag.parse_frame_data([]), b"")
        for bad in (["4"], ["00 11 22 33 44 55 66 77 88"], ["zz"]):
            with self.assertRaises(ValueError, msg=bad):
                diag.parse_frame_data(bad)
        self.assertEqual(diag.frame_text(0x60A, data=b"\x40\x18"), "0x60A [2] 40 18")
        self.assertEqual(diag.frame_text(0x123, ext=True, rtr=True, dlc=4), "0x00000123 remote [4]")

    def test_refusal_kinds(self):
        self.assertTrue(diag.needs_force(diag.DiagError("refused", "0x205 is RPDO1 of node 5; force needed")))
        self.assertFalse(diag.needs_force(diag.DiagError("refused", "changes not allowed")))
        self.assertTrue(diag.too_old(diag.DiagError("refused", "unknown op 'send_frame'")))
        self.assertFalse(diag.too_old(diag.DiagError("eof", "unknown op")))


class Send(unittest.TestCase):
    def test_single_frame(self):
        with FakePlugin(allow_changes=True) as fp:
            code, out, err = run("--runtime", fp.runtime, "send", "0x60A", "40 18 10 01 00 00 00 00")
            self.assertEqual(code, 0, err)
            self.assertEqual(out, "sent 0x60A [8] 40 18 10 01 00 00 00 00\n")
            self.assertEqual(fp.sent[0]["data"], "40 18 10 01 00 00 00 00")
            self.assertEqual(fp.requests[-1]["can_id"], 0x60A)
            self.assertNotIn("period_ms", fp.requests[-1])
            self.assertEqual(run("--runtime", fp.runtime, "send", "0x60A", "40181001")[0], 0)
            self.assertEqual(run("--runtime", fp.runtime, "send", "0x60A", "40", "18", "10", "01")[0], 0)
            self.assertEqual([f["data"] for f in fp.sent[1:]], ["40 18 10 01"] * 2)
            code, out, _ = run("--runtime", fp.runtime, "send", "0x7F0")  # no data
            self.assertEqual((code, out), (0, "sent 0x7F0 [0]\n"))
            self.assertNotIn("data", fp.requests[-1])

    def test_remote_and_extended(self):
        with FakePlugin(allow_changes=True) as fp:
            code, out, err = run("--runtime", fp.runtime, "send", "0x1234567", "--ext", "--rtr", "--dlc", "4")
            self.assertEqual(code, 0, err)
            self.assertEqual(out, "sent 0x01234567 remote [4]\n")
            req = fp.requests[-1]
            self.assertEqual((req["can_id"], req["ext"], req["rtr"], req["dlc"]), (0x1234567, True, True, 4))
            self.assertNotIn("data", req)
            for argv, why in ((["0x60A", "01", "--rtr"], "carries no data"), (["0x60A", "--dlc", "2"], "--rtr"),
                              (["0x800"], "out of range"), (["0x60A", "00 11 22 33 44 55 66 77 88"], "at most 8"),
                              (["0x60A", "--count", "3"], "--period-ms")):
                code, _, err = run("--runtime", fp.runtime, "send", *argv)
                self.assertEqual(code, 2, argv)
                self.assertIn(why, err)
            with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                diag.parser().parse_args(["send", "0x60A", "--period-ms", "2"])

    def test_refusals_and_force(self):
        with FakePlugin(allow_changes=False) as fp:
            code, _, err = run("--runtime", fp.runtime, "send", "0x60A", "01")
            self.assertEqual(code, 1)
            self.assertIn("changes not allowed", err)
        with FakePlugin(allow_changes=True) as fp:
            code, _, err = run("--runtime", fp.runtime, "send", "0x205", "01 02")
            self.assertEqual(code, 1)
            self.assertIn("0x205 is RPDO1 of node 5; force needed; add --force to send it anyway", err)
            self.assertEqual(fp.sent, [])
            code, out, _ = run("--runtime", fp.runtime, "send", "0x205", "01 02", "--force")
            self.assertEqual((code, out), (0, "sent 0x205 [2] 01 02 (forced)\n"))
            self.assertTrue(fp.sent[0]["forced"])
            fp.operational = 5
            code, _, err = run("--runtime", fp.runtime, "send", "0x60A")
            self.assertEqual(code, 1)
            self.assertIn("node 5 is OPERATIONAL; force needed; add --force", err)

    def test_older_plugin(self):
        with FakePlugin(allow_changes=True) as fp:
            fp.send_supported = False
            for argv in (["send", "0x60A"], ["send-stop"]):
                code, _, err = run("--runtime", fp.runtime, *argv)
                self.assertEqual(code, 1)
                self.assertIn("plugin is too old for this command", err)

    def test_cyclic_with_count(self):
        with FakePlugin(allow_changes=True) as fp:
            code, out, err = run("--runtime", fp.runtime, "send", "0x60A", "01", "--period-ms", "10", "--count", "5")
            self.assertEqual(code, 0, err)
            self.assertIn("job 1: sending 0x60A [1] 01 every 10 ms, 5 frames", out)
            self.assertIn("job 1: 5 frames sent, count reached", out)
            start = [r for r in fp.requests if r["op"] == "send_frame"][0]
            self.assertEqual((start["period_ms"], start["count"]), (10, 5))
            self.assertEqual(fp.requests[-1], dict(fp.requests[-1], op="send_frame_stop", job=1))

    def test_cyclic_with_duration_and_ctrl_c(self):
        with FakePlugin(allow_changes=True) as fp:
            code, out, err = run("--runtime", fp.runtime, "send", "0x60A", "--period-ms", "100", "--duration", "0.6")
            self.assertEqual(code, 0, err)
            self.assertRegex(out, r"job 1: \d+ frames sent, stopped")
            self.assertTrue(fp.jobs[1]["reason"], "stopped")
            # Ctrl-C stops the job too.
            with mock.patch.object(diag.time, "sleep", side_effect=KeyboardInterrupt):
                code, out, err = run("--runtime", fp.runtime, "send", "0x60A", "--period-ms", "1000")
            self.assertEqual(code, 0, err)
            self.assertIn("job 2: 1 frame sent, stopped", out)
            self.assertEqual(fp.requests[-1]["op"], "send_frame_stop")

    def test_cyclic_ended_by_the_plugin(self):
        with FakePlugin(allow_changes=True) as fp:
            fp.job_failure = "transmit queue full"
            code, out, err = run("--runtime", fp.runtime, "send", "0x60A", "--period-ms", "10")
        self.assertEqual(code, 1)
        self.assertIn("transmit queue full", out)
        self.assertIn("job 1 ended early: transmit queue full", err)

    def test_cyclic_json(self):
        with FakePlugin(allow_changes=True) as fp:
            code, out, err = run("--runtime", fp.runtime, "--json", "send", "0x60A", "--period-ms", "10",
                                 "--count", "3")
        self.assertEqual(code, 0, err)
        res = json.loads(out)
        self.assertEqual((res["job"], res["stopped"][0]["sent"], res["stopped"][0]["reason"]), (1, 3, "count reached"))

    def test_send_stop_and_status(self):
        with FakePlugin(allow_changes=True) as fp:
            code, out, _ = run("--runtime", fp.runtime, "send-stop")
            self.assertEqual((code, out), (0, "no job of this connection was running\n"))
            code, out, _ = run("--runtime", fp.runtime, "--json", "send-stop", "7")
            self.assertEqual(json.loads(out), {"stopped": []})
            self.assertEqual(fp.requests[-1]["job"], 7)
            # status lists a job another client runs.
            c = diag.Client("127.0.0.1", fp.port, "test-token")
            c.connect()
            c.send_frame(0x60A, b"\x01", period_ms=100)
            code, out, _ = run("--runtime", fp.runtime, "status")
            c.close()
            self.assertIn("send job 1: 0x60A every 100 ms", out)

    def test_network(self):
        with FakePlugin(allow_changes=True, networks=TWO_NETWORKS) as fp:
            code, _, err = run("--runtime", fp.runtime, "send", "0x60A")
            self.assertEqual(code, 1)
            self.assertIn("give --network NAME", err)
            self.assertEqual(run("--runtime", fp.runtime, "send", "0x60A", "--network", "drives")[0], 0)
            self.assertEqual(fp.sent[0]["network"], "drives")


if __name__ == "__main__":
    unittest.main()
