"""openplc-canopen-diag and the diag client against a fake plugin."""

import io
import json
import os
import shlex
import unittest
from contextlib import redirect_stderr
from unittest import mock

from openplc_canopen_deploy import diag

from .fake_diag import TOKEN, TWO_NETWORKS, FakePlugin, closed_port
from .helpers import REPO


def run(*argv, env_token=TOKEN):
    out, err = io.StringIO(), io.StringIO()
    env = {diag.TOKEN_ENV: env_token} if env_token else {}
    with mock.patch.dict(os.environ, env, clear=False), redirect_stderr(err):
        if not env_token:
            os.environ.pop(diag.TOKEN_ENV, None)
        args = diag.parser().parse_args(list(argv))
        try:
            code = diag.run(args, out)
        except diag.DiagError as e:
            err.write("openplc-canopen-diag: %s\n" % e)
            code = 2 if e.kind == "usage" else 1
    return code, out.getvalue(), err.getvalue()


class Values(unittest.TestCase):
    def test_hash_token(self):
        self.assertEqual(diag.hash_token("test"),
                         "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08")
        self.assertGreaterEqual(len(diag.new_token()), 32)
        self.assertNotEqual(diag.new_token(), diag.new_token())

    def test_parse_runtime(self):
        self.assertEqual(diag.parse_runtime("plc.local"), ("plc.local", 7531))
        self.assertEqual(diag.parse_runtime("10.0.0.2:8000"), ("10.0.0.2", 8000))
        self.assertEqual(diag.parse_runtime("[fe80::1]:9000"), ("fe80::1", 9000))
        for bad in ("", "host:x", "host:0", ":80"):
            with self.assertRaises(ValueError):
                diag.parse_runtime(bad)

    def test_decode(self):
        self.assertEqual(diag.decode("VISIBLE_STRING", b"VALVE\0\0")["text"], "VALVE")
        self.assertEqual(diag.decode("UNSIGNED32", (305419896).to_bytes(4, "little"))["text"],
                         "305419896 (0x12345678)")
        self.assertEqual(diag.decode(0x0003, b"\xff\xff")["value"], -1)
        self.assertEqual(diag.decode("0x0008", b"\x00\x00\x80\x3f")["value"], 1.0)
        self.assertEqual(diag.decode("BOOLEAN", b"\x01")["text"], "TRUE")
        self.assertEqual(diag.decode(None, b"\x1e\x00")["text"], "1E 00")
        self.assertEqual(diag.decode("UNSIGNED16", b"\x01")["text"], "01")  # wrong size: bytes as they came

    def test_encode(self):
        self.assertEqual(diag.encode("UNSIGNED16", "0x1E"), b"\x1e\x00")
        self.assertEqual(diag.encode("INTEGER8", "-128"), b"\x80")
        self.assertEqual(diag.encode("VISIBLE_STRING", "abc"), b"abc")
        self.assertEqual(diag.encode("OCTET_STRING", "01 02"), b"\x01\x02")
        self.assertEqual(diag.encode("BOOLEAN", "true"), b"\x01")
        self.assertEqual(diag.encode("UNSIGNED24", "65536"), b"\x00\x00\x01")
        for t, v in (("UNSIGNED8", "256"), ("INTEGER16", "32768"), ("UNSIGNED32", "-1"), ("UNSIGNED8", "x"),
                     ("BOOLEAN", "2"), ("REAL32", "1e40")):
            with self.assertRaises(ValueError, msg=(t, v)):
                diag.encode(t, v)

    def test_texts(self):
        self.assertEqual(diag.abort_text(0x06020000), "object does not exist in the object dictionary")
        self.assertEqual(diag.abort_text(0x12345678), "abort code 0x12345678")
        self.assertEqual(diag.emcy_class(0x4210), "temperature")
        self.assertEqual(diag.emcy_class(0x8130), "communication")
        self.assertEqual(diag.emcy_class(0x8F00), "monitoring")
        self.assertEqual(diag.emcy_class(0x0000), "error reset or no error")
        self.assertEqual(diag.emcy_class(0xFF01), "device specific")


class Cli(unittest.TestCase):
    def test_status(self):
        with FakePlugin() as fp:
            code, out, err = run("--runtime", fp.runtime, "status")
        self.assertEqual(code, 0, err)
        self.assertIn("bus vcan0: error active", out)
        self.assertIn("master node 1: OPERATIONAL", out)
        self.assertIn("SYNC: PLC cycle, every 2 cycles, 500 sent, interval 10012 us (min 9870, max 10240), "
                      "skipped 0, late PDOs 3", out)
        self.assertRegex(out, r"2\s+pingpong\s+OPERATIONAL\s+yes\s+booted\s+none\s+0x4210 temperature")
        self.assertIn("error J: the configuration download failed", out)
        self.assertIn("(retrying)", out)
        self.assertIn("node 2 SDO variable 0x2001:0 (uptime), UNSIGNED32 read: raw 42", out)

    def test_format_sync(self):
        from openplc_canopen_deploy.diag import format_sync
        self.assertIsNone(format_sync(None))
        self.assertEqual(format_sync({"source": "none", "count": 0}), "SYNC: off")
        self.assertEqual(format_sync({"source": "timer", "period_us": 20000, "count": 1, "skipped": 0,
                                      "late_pdos": 0}), "SYNC: timer 20000 us, 1 sent, skipped 0, late PDOs 0")

    def test_status_json(self):
        with FakePlugin() as fp:
            code, out, _ = run("--runtime", fp.runtime, "--json", "status")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["nodes"][1]["boot_error"], "J")

    def test_wrong_token(self):
        with FakePlugin() as fp:
            code, _, err = run("--runtime", fp.runtime, "--token", "nope", "status")
        self.assertEqual(code, 1)
        self.assertIn("refused the token", err)

    def test_closed_port(self):
        code, _, err = run("--runtime", "127.0.0.1:%d" % closed_port(), "status")
        self.assertEqual(code, 1)
        self.assertIn("is closed", err)

    def test_no_token_without_terminal(self):
        with mock.patch("sys.stdin", io.StringIO()):
            code, _, err = run("--runtime", "127.0.0.1:1", "status", env_token=None)
        self.assertEqual(code, 1)
        self.assertIn("--token", err)

    def test_emcy(self):
        with FakePlugin() as fp:
            code, out, _ = run("--runtime", fp.runtime, "emcy", "2")
        self.assertEqual(code, 0)
        lines = out.splitlines()
        self.assertIn("2026-10-03T12:00:01.250Z  0x4210  temperature", lines[0])
        self.assertIn("error reset or no error", lines[1])

    def test_sdo_read(self):
        with FakePlugin() as fp:
            self.assertEqual(run("--runtime", fp.runtime, "sdo-read", "2", "0x1008", "0", "--type",
                                 "VISIBLE_STRING")[1], "pingpong\n")
            with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                run("--runtime", fp.runtime, "sdo-read", "2", "0x1018", "4", "--type", "u32")
            self.assertEqual(run("--runtime", fp.runtime, "sdo-read", "2", "0x1018", "4", "--type", "unsigned32")[1],
                             "305419896 (0x12345678)\n")
            code, _, err = run("--runtime", fp.runtime, "sdo-read", "2", "0x6000", "1")
            self.assertEqual(code, 1)
            self.assertIn("abort 0x06020000: object does not exist in the object dictionary", err)
            code, _, err = run("--runtime", fp.runtime, "sdo-read", "9", "0x1000", "0")
            self.assertEqual(code, 1)
            self.assertIn("node 9 0x1000:0: timeout", err)
            self.assertEqual(fp.requests[0]["timeout_ms"], 1000)

    def test_write_without_permission(self):
        with FakePlugin(allow_changes=False) as fp:
            code, _, err = run("--runtime", fp.runtime, "nmt", "5", "stop")
            self.assertEqual(code, 1)
            self.assertIn("changes not allowed", err)
            code, _, err = run("--runtime", fp.runtime, "sdo-write", "2", "0x2000", "0", "5", "--type",
                               "UNSIGNED32")
            self.assertEqual(code, 1)
            self.assertIn("changes not allowed", err)

    def test_write_and_nmt(self):
        with FakePlugin(allow_changes=True) as fp:
            code, out, err = run("--runtime", fp.runtime, "sdo-write", "2", "0x2000", "0", "0x1E", "--type",
                                 "UNSIGNED32")
            self.assertEqual((code, out), (0, "written\n"), err)
            self.assertEqual(fp.requests[-1]["data"], "1E 00 00 00")
            self.assertEqual(run("--runtime", fp.runtime, "sdo-write", "2", "0x2000", "0", "-1", "--type",
                                 "UNSIGNED32")[0], 2)
            self.assertEqual(run("--runtime", fp.runtime, "nmt", "2", "stop")[0], 0)
            self.assertEqual(fp.requests[-1], {"op": "nmt", "node": 2, "command": "stop", "id": 2})
            code, _, err = run("--runtime", fp.runtime, "nmt", "40", "stop")
            self.assertEqual(code, 1)
            self.assertIn("node 40 is not in the configuration", err)

    def test_scan(self):
        with FakePlugin() as fp:
            code, out, _ = run("--runtime", fp.runtime, "scan")
        self.assertEqual(code, 0)
        self.assertIn("scanned in 1.8 s", out)
        self.assertIn("node  40  vendor 0x000000AB  product 0x00001234  revision 0x00010002  serial 0x00000063  "
                      "'RTD sensor'  not configured", out)
        self.assertIn("as pingpong", out)
        self.assertIn("note: devices in STOPPED", out)

    def test_lss_read_only(self):
        with FakePlugin() as fp:
            for argv in (["lss-find"], ["lss-inquire", "0x360", "0", "0", "0x42"],
                         ["lss-set-id", "0x360", "0", "0", "0x42", "40"],
                         ["lss-set-bitrate", "0x360", "0", "0", "0x42", "250"]):
                code, _, err = run("--runtime", fp.runtime, *argv)
                self.assertEqual(code, 1, argv)
                self.assertIn("changes not allowed", err)

    def test_lss_find(self):
        with FakePlugin(allow_changes=True) as fp:
            code, out, _ = run("--runtime", fp.runtime, "lss-find")
            self.assertEqual(code, 0)
            self.assertIn("found vendor 0x00000360, product 0x00000000, revision 0x00000000, serial 0x00000042, "
                          "no node ID", out)
            self.assertNotIn("vendor_id", fp.requests[0])
            code, out, _ = run("--runtime", fp.runtime, "lss-find", "--vendor", "0xAB", "--product", "1")
            self.assertEqual(code, 0)
            self.assertIn("no device without a node ID answered", out)
            self.assertEqual(fp.requests[-1]["op"], "lss_find_status")
            self.assertTrue(any(r.get("vendor_id") == 0xAB and r.get("product_code") == 1 for r in fp.requests))
            self.assertEqual(run("--runtime", fp.runtime, "lss-find", "--vendor", "1")[0], 2)

    def test_lss_set_id_and_bitrate(self):
        with FakePlugin(allow_changes=True) as fp:
            code, out, _ = run("--runtime", fp.runtime, "lss-set-id", "0x360", "0", "0", "0x42", "40")
            self.assertEqual(code, 0)
            self.assertIn("node ID 40 set; the device had no node ID", out)
            self.assertIs(fp.requests[-1]["store"], False)
            code, out, _ = run("--runtime", fp.runtime, "lss-set-id", "0x360", "0", "0", "0x42", "41", "--store")
            self.assertEqual(code, 0)
            self.assertIn("node ID 41 set, stored", out)
            self.assertIs(fp.requests[-1]["store"], True)
            code, out, _ = run("--runtime", fp.runtime, "lss-inquire", "0x360", "0", "0", "0x42")
            self.assertIn("node ID 41", out)
            code, out, _ = run("--runtime", fp.runtime, "lss-set-bitrate", "0x360", "0", "0", "0x42", "250")
            self.assertEqual(code, 0)
            self.assertIn("next power cycle", out)
            self.assertEqual(fp.requests[-1]["bitrate_kbit"], 250)
            self.assertIs(fp.requests[-1]["store"], False)
            # Refusals exit non-zero with the reason.
            code, _, err = run("--runtime", fp.runtime, "lss-set-id", "0x360", "0", "0", "0x42", "2")
            self.assertEqual(code, 1)
            self.assertIn("node ID 2 is in use by node 2 (pingpong)", err)
            code, _, err = run("--runtime", fp.runtime, "lss-inquire", "0x360", "0", "0", "0x9999")
            self.assertEqual(code, 1)
            self.assertIn("not found", err)
        with redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                diag.parser().parse_args(["lss-set-bitrate", "1", "2", "3", "4", "100"])

    def test_hash_token_command(self):
        code, out, _ = run("hash-token", "test", env_token=None)
        self.assertEqual(out.strip(), "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08")

    def test_bad_arguments(self):
        with redirect_stderr(io.StringIO()):
            for argv in (["nmt", "2", "halt"], ["sdo-read", "128", "0x1000", "0"], ["sdo-write", "2", "1", "0", "1"],
                         ["sdo-read", "2", "0x10000", "0"]):
                with self.assertRaises(SystemExit, msg=argv):
                    diag.parser().parse_args(argv)
        self.assertEqual(run("status")[0], 2)


class Networks(unittest.TestCase):
    """A plugin that runs two networks (io, drives), one that lists one, and
    an older one that lists none (the default fake)."""

    def test_hello_lists_the_networks(self):
        with FakePlugin(networks=TWO_NETWORKS) as fp:
            c = diag.Client("127.0.0.1", fp.port, TOKEN)
            c.connect()
            try:
                self.assertEqual([n["name"] for n in c.networks], ["io", "drives"])
                self.assertTrue(c.several())
                with self.assertRaises(diag.DiagError) as cm:
                    c.status()
                self.assertEqual(str(cm.exception), "network required (io, drives)")
                with self.assertRaises(diag.DiagError) as cm:
                    c.request("status", network="x")
                self.assertEqual(str(cm.exception), "unknown network 'x' (io, drives)")
                c.network = "drives"
                self.assertEqual(c.status()["network"], "drives")
                self.assertEqual(fp.requests[-1], {"op": "status", "id": 4, "network": "drives"})
            finally:
                c.close()

    def test_status_of_every_network(self):
        with FakePlugin(networks=TWO_NETWORKS) as fp:
            code, out, err = run("--runtime", fp.runtime, "status")
            self.assertEqual(code, 0, err)
            self.assertEqual([r.get("network") for r in fp.requests], ["io", "drives"])
        self.assertTrue(out.startswith("network io (vcan0)\nplugin v-test"), out)
        io_part, drives_part = out.split("\nnetwork drives (vcan1)\n")
        self.assertRegex(io_part, r"2\s+pingpong\s+OPERATIONAL")
        self.assertIn("bus vcan1: error active", drives_part)
        self.assertRegex(drives_part, r"2\s+drive\s+PRE-OPERATIONAL")
        self.assertNotIn("pingpong", drives_part)

    def test_status_json_of_every_network(self):
        with FakePlugin(networks=TWO_NETWORKS) as fp:
            code, out, _ = run("--runtime", fp.runtime, "--json", "status")
        self.assertEqual(code, 0)
        self.assertEqual([st["network"] for st in json.loads(out)["networks"]], ["io", "drives"])

    def test_status_of_one_network(self):
        with FakePlugin(networks=TWO_NETWORKS) as fp:
            code, out, err = run("--runtime", fp.runtime, "status", "--network", "drives")
            self.assertEqual(code, 0, err)
            self.assertEqual([r.get("network") for r in fp.requests], ["drives"])
        self.assertTrue(out.startswith("plugin v-test"))
        self.assertIn("bus vcan1", out)

    def test_commands_need_a_network(self):
        with FakePlugin(networks=TWO_NETWORKS, allow_changes=True) as fp:
            for argv in (["sdo-read", "2", "0x1018", "1"], ["emcy", "2"], ["nmt", "2", "stop"], ["scan"],
                         ["lss-find"], ["sdo-write", "2", "0x2000", "0", "1", "--type", "UNSIGNED32"]):
                code, _, err = run("--runtime", fp.runtime, *argv)
                self.assertEqual(code, 1, argv)
                self.assertIn("runs 2 networks (io, drives); give --network NAME", err)
            self.assertEqual(fp.requests, [])
            code, _, err = run("--runtime", fp.runtime, "sdo-read", "2", "0x1008", "0", "--network", "motion")
            self.assertEqual(code, 1)
            self.assertIn("runs no network 'motion' (io, drives)", err)

    def test_sdo_read_on_the_second_network(self):
        with FakePlugin(networks=TWO_NETWORKS) as fp:
            code, out, err = run("--runtime", fp.runtime, "sdo-read", "2", "0x1008", "0", "--type",
                                 "VISIBLE_STRING", "--network", "drives")
            self.assertEqual((code, out), (0, "drive\n"), err)
            self.assertEqual(fp.requests[-1]["network"], "drives")
            code, out, err = run("--runtime", fp.runtime, "sdo-read", "2", "0x1008", "0", "--type",
                                 "VISIBLE_STRING", "--network", "io")
            self.assertEqual((code, out), (0, "pingpong\n"), err)

    def test_one_listed_network(self):
        # A plugin with one network: --network may be left out and is never sent.
        with FakePlugin(networks=TWO_NETWORKS[:1]) as fp:
            code, out, err = run("--runtime", fp.runtime, "status")
            self.assertEqual(code, 0, err)
            self.assertTrue(out.startswith("plugin v-test"))
            code, out, _ = run("--runtime", fp.runtime, "sdo-read", "2", "0x1008", "0", "--network", "io")
            self.assertEqual(code, 0)
            self.assertFalse([r for r in fp.requests if "network" in r])
            code, _, err = run("--runtime", fp.runtime, "status", "--network", "drives")
            self.assertEqual(code, 1)
            self.assertIn("runs no network 'drives' (io)", err)

    def test_older_plugin(self):
        # No networks in the hello: the output is as before, and `network` is
        # never sent, whatever --network says.
        with FakePlugin() as fp:
            code, out, err = run("--runtime", fp.runtime, "status")
            self.assertEqual(code, 0, err)
            self.assertTrue(out.startswith("plugin v-test, up 12 s"))
            self.assertNotIn("network", out)
            code, out, _ = run("--runtime", fp.runtime, "sdo-read", "2", "0x1008", "0", "--network", "io")
            self.assertEqual(code, 0)
            self.assertFalse([r for r in fp.requests if "network" in r])


def documented_commands():
    """Every openplc-canopen-diag command line in the docs' code blocks, as
    argument lists ([optional] parts included)."""
    out = []
    for name in ("diagnostics.md", "trace.md"):
        with open(os.path.join(REPO, "docs", name), encoding="utf-8") as f:
            text = f.read()
        for block in text.split("```")[1::2]:
            for line in block.splitlines():
                line = line.strip()
                if line.startswith("openplc-canopen-diag "):
                    argv = shlex.split(line.replace("[", "").replace("]", ""), comments=True)
                    out.append((name, argv[1:]))
    return out


class Docs(unittest.TestCase):
    def test_documented_commands_parse(self):
        commands = documented_commands()
        self.assertGreater(len(commands), 20)
        self.assertTrue(any("--network" in argv for _, argv in commands))
        for name, argv in commands:
            with redirect_stderr(io.StringIO()):
                try:
                    diag.parser().parse_args(argv)
                except SystemExit:
                    self.fail("%s: %s does not parse" % (name, " ".join(argv)))


if __name__ == "__main__":
    unittest.main()
