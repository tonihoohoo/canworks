"""The remote link (canworks.link): pairing with the diagnostics token, the
device's forwarding targets, revoking, the automatic path choice and the
canworks-diag link commands. Everything runs offline on 127.0.0.1 with relays
off; skipped where the iroh package is missing."""

import asyncio
import io
import json
import os
import shutil
import socket
import tempfile
import threading
import time
import unittest
from contextlib import redirect_stderr
from unittest import mock

from canworks import diag, runtime
from canworks.link import available, device, discovery, protocol

from .fake_diag import TOKEN, FakePlugin

HAVE_IROH = available()


class Protocol(unittest.TestCase):
    def test_lan_addresses(self):
        for a in ("192.168.1.20:7533", "10.1.2.3", "172.20.0.5:1", "169.254.10.2:7533", "[fe80::1%eth0]:7533",
                  "fd00::5", "127.0.0.1:4000", "[::ffff:192.168.0.2]:7533"):
            self.assertTrue(protocol.is_lan_address(a), a)
        for a in ("8.8.8.8:7533", "100.64.1.2", "[2001:db8::1]:7533", "relay.example.com:443", ""):
            self.assertFalse(protocol.is_lan_address(a), a)

    def test_server_check_matches_the_client(self):
        verifier = diag.token_verifier("secret")
        it, salt, _, _ = diag.parse_verifier(verifier)
        cbind = protocol.channel_binding(b"\x01" * 32, b"\x02" * 32)
        auth = protocol.auth_message("c", "cs", diag._b64(salt), it, cbind)
        proof, want = diag.scram_client("secret", salt, it, auth)
        self.assertEqual(protocol.server_check(verifier, auth, diag._b64(proof)), diag._b64(want))
        bad, _ = diag.scram_client("guess", salt, it, auth)
        self.assertIsNone(protocol.server_check(verifier, auth, diag._b64(bad)))
        self.assertIsNone(protocol.server_check(verifier, auth, "not base64!"))
        # Bound to both keys: another pair of keys gives another login.
        other = protocol.auth_message("c", "cs", diag._b64(salt), it, protocol.channel_binding(b"\x01" * 32,
                                                                                              b"\x03" * 32))
        self.assertIsNone(protocol.server_check(verifier, other, diag._b64(proof)))

    def test_deployed_settings(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        p = os.path.join(tmp, "canworks.json")
        with open(p, "w") as f:
            json.dump({"schema_version": 2, "diagnostics": {"token_verifier": "V", "port": 7600,
                                                            "remote_link": {"internet": True, "pairing": "off",
                                                                            "relays": ["https://r.example.com"]}},
                       "networks": []}, f)
        v, port, rl = device.deployed_settings(p)
        self.assertEqual((v, port), ("V", 7600))
        self.assertEqual(device.remote_settings(rl), (True, ["https://r.example.com"], "off"))
        with open(p, "w") as f:
            json.dump({"master": {"diagnostics": {"token_verifier": "W"}}, "nodes": []}, f)
        v, port, rl = device.deployed_settings(p)
        self.assertEqual((v, port, device.remote_settings(rl)), ("W", 7531, (False, [], "lan")))
        self.assertEqual(device.deployed_settings(os.path.join(tmp, "missing.json"))[0], None)

    def test_avahi_service(self):
        text = discovery.avahi_service(link_id="abc", name="line<3>")
        self.assertIn("<type>_canworks._tcp</type>", text)
        self.assertIn("<port>7531</port>", text)
        for t in ("v=1", "diag=7531", "runtime=8443", "id=abc", "link=7533"):
            self.assertIn("<txt-record>%s</txt-record>" % t, text)
        self.assertIn("line&lt;3&gt;", text)
        bridge = discovery.avahi_service(runtime_port=None)
        self.assertNotIn("runtime=", bridge)
        self.assertNotIn("id=", bridge)
        self.assertIn("%h", bridge)


def _cli(*argv):
    out, err = io.StringIO(), io.StringIO()
    with mock.patch.dict(os.environ, {diag.TOKEN_ENV: TOKEN}), redirect_stderr(err):
        try:
            code = diag.run(diag.parser().parse_args(list(argv)), out)
        except diag.DiagError as e:
            err.write("canworks-diag: %s\n" % e)
            code = 2 if e.kind == "usage" else 1
    return code, out.getvalue(), err.getvalue()


@unittest.skipUnless(HAVE_IROH, "the iroh package is not installed")
class Link(unittest.TestCase):
    """One device service per test, its config pointing at a fake plugin."""

    def setUp(self):
        from canworks.link import pc
        self.pc = pc
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        env = mock.patch.dict(os.environ, {"CANWORKS_CONFIG_DIR": os.path.join(self.tmp, "pc"),
                                           "CANWORKS_LINK": "off"})
        env.start()
        self.addCleanup(env.stop)
        pc._conns.clear()
        self.fp = FakePlugin()
        self.fp.__enter__()
        self.addCleanup(self.fp.__exit__, None, None, None)
        self.devdir = os.path.join(self.tmp, "dev")
        os.makedirs(self.devdir)
        self.cfg = os.path.join(self.tmp, "canworks.json")
        self.write_config({})
        with open(os.path.join(self.devdir, "link.json"), "w") as f:
            json.dump({"config": self.cfg, "port": 0, "runtime_port": self.https_port()}, f)
        self.svc = device.Service(self.devdir, bind="127.0.0.1:0", name="testdev")
        self.loop = asyncio.new_event_loop()
        threading.Thread(target=self.loop.run_forever, daemon=True).start()
        self.running = running = asyncio.run_coroutine_threadsafe(self.svc.run(), self.loop)
        deadline = time.monotonic() + 10
        while self.svc.endpoint is None and time.monotonic() < deadline and not running.done():
            time.sleep(0.02)
        if running.done():
            running.result()  # the service failed to start: show why
        self.assertIsNotNone(self.svc.endpoint, "the link service did not start")
        self.addCleanup(self._stop)
        self.entry = pc.remember("testdev", hosts=["192.0.2.1"], id=self.svc.id,
                                 link_addrs=self.svc.endpoint.addr().direct_addresses())

    def _stop(self):
        try:
            asyncio.run_coroutine_threadsafe(self.svc.stop(), self.loop).result(5)
        except Exception:
            pass  # already stopped
        self.loop.call_soon_threadsafe(self.loop.stop)

    def https_port(self):
        """A plain TCP echo server standing in for the runtime's HTTPS port."""
        srv = socket.socket()
        srv.bind(("127.0.0.1", 0))
        srv.listen()
        self.addCleanup(srv.close)

        def serve():
            while True:
                try:
                    c, _ = srv.accept()
                except OSError:
                    return

                def echo(c=c):
                    with c:
                        while True:
                            d = c.recv(65536)
                            if not d:
                                return
                            c.sendall(d)
                threading.Thread(target=echo, daemon=True).start()
        threading.Thread(target=serve, daemon=True).start()
        return srv.getsockname()[1]

    def write_config(self, remote_link):
        with open(self.cfg, "w") as f:
            json.dump({"schema_version": 2, "networks": [],
                       "diagnostics": {"token_verifier": diag.token_verifier(TOKEN), "port": self.fp.port,
                                       "remote_link": remote_link}}, f)

    def pair(self):
        self.entry = self.pc.pair(self.entry, TOKEN)
        return self.entry

    def test_unpaired_pc_only_pairs(self):
        with self.assertRaises(protocol.LinkError) as cm:
            self.pc.link_socket(self.entry, "diag", 10)
        self.assertEqual(cm.exception.kind, "unpaired")
        self.assertFalse(os.path.exists(os.path.join(self.devdir, "paired.json")))

    def test_wrong_token_then_right_token(self):
        with self.assertRaises(protocol.LinkError) as cm:
            self.pc.pair(self.entry, "guess")
        self.assertEqual(cm.exception.kind, "token")
        with self.assertRaises(protocol.LinkError) as cm:   # at once again: slowed down
            self.pc.pair(self.entry, TOKEN)
        self.assertIn("wait a second", str(cm.exception))
        time.sleep(device.PAIR_DELAY_S + 0.1)
        entry = self.pair()
        self.assertTrue(entry["paired"])
        with open(os.path.join(self.devdir, "paired.json")) as f:
            pcs = json.load(f)["pcs"]
        self.assertEqual([p["id"] for p in pcs], [self.pc.my_id()])

    def test_diagnostics_over_the_link(self):
        self.pair()
        c = diag.Client("link:testdev", token=TOKEN)
        c.connect()
        try:
            self.assertEqual(c.path, "LAN")    # a direct path to 127.0.0.1
            self.assertIn("nodes", c.status())
            self.assertIsNotNone(c.rtt_ms)
        finally:
            c.close()

    def test_runtime_target_and_unknown_target(self):
        self.pair()
        sock, _, _ = self.pc.link_socket(self.entry, "runtime", 10)
        with sock:
            sock.sendall(b"GET / HTTP/1.0\r\n\r\n")
            self.assertEqual(sock.recv(64), b"GET / HTTP/1.0\r\n\r\n")
        with self.assertRaises(protocol.LinkError) as cm:
            self.pc.link_socket(self.entry, "ssh", 10)
        self.assertIn("unknown target", str(cm.exception))

    def test_diagnostics_not_listening(self):
        self.pair()
        self.fp.__exit__(None, None, None)
        with self.assertRaises(protocol.LinkError) as cm:
            self.pc.link_socket(self.entry, "diag", 10)
        self.assertIn("diagnostics not listening", str(cm.exception))

    def test_automatic_path_choice(self):
        self.pair()
        # The remembered direct address does not answer: the link carries it.
        sock, path, _ = self.pc.open_socket("testdev", 7531, 1.0)
        sock.close()
        self.assertEqual(path, "LAN")
        # A reachable direct address wins without the link.
        self.pc.remember("testdev", hosts=["127.0.0.1"])
        sock, path, rtt = self.pc.open_socket("testdev", self.fp.port, 2.0)
        sock.close()
        self.assertEqual((path, rtt), ("LAN", None))

    def test_revoke_closes_sessions(self):
        self.pair()
        c = diag.Client("link:testdev", token=TOKEN)
        c.connect()
        self.addCleanup(c.close)
        self.assertEqual(device.main(["--dir", self.devdir, "revoke", "testdev" if False else self.pc.my_id()]), 0)
        deadline = time.monotonic() + device.WATCH_S + 3
        gone = False
        while time.monotonic() < deadline and not gone:
            try:
                c.status()
                time.sleep(0.2)
            except diag.DiagError:
                gone = True
        self.assertTrue(gone, "the session survived the revoke")
        with self.assertRaises(protocol.LinkError) as cm:
            self.pc.link_socket(self.entry, "diag", 10)
        self.assertEqual(cm.exception.kind, "unpaired")

    def test_manage_and_unpair(self):
        self.pair()
        pcs, me = self.pc.paired_pcs(self.entry, TOKEN)
        self.assertEqual([p["id"] for p in pcs], [me])
        with self.assertRaises(protocol.LinkError):
            self.pc.paired_pcs(self.entry, "guess")
        self.assertTrue(self.pc.unpair(self.entry))
        self.assertEqual(device.Paired(os.path.join(self.devdir, "paired.json")).pcs, [])

    def test_pairing_scope_from_config(self):
        self.write_config({"pairing": "off"})
        time.sleep(device.WATCH_S + 1)
        with self.assertRaises(protocol.LinkError) as cm:
            self.pair()
        self.assertIn("pairing is off", str(cm.exception))
        self.write_config({"pairing": "lan"})
        time.sleep(device.WATCH_S + 1)
        self.assertTrue(self.pair()["paired"])
        self.assertFalse(self.entry["internet"])

    def test_internet_change_restarts_the_service(self):
        # iroh keeps the UDP port until the endpoint is gone: the service stops
        # and systemd (Restart=always) starts it with the new settings.
        self.write_config({"internet": True})
        self.running.result(device.WATCH_S + 10)
        self.assertTrue(self.svc.restart)

    def test_no_token_configured(self):
        with open(self.cfg, "w") as f:
            json.dump({"schema_version": 2, "networks": []}, f)
        time.sleep(device.WATCH_S + 1)
        with self.assertRaises(protocol.LinkError) as cm:
            self.pair()
        self.assertIn("no token configured", str(cm.exception))

    def test_device_cli(self):
        out = io.StringIO()
        with mock.patch("sys.stdout", out):
            self.assertEqual(device.main(["--dir", self.devdir, "id"]), 0)
            self.assertEqual(device.main(["--dir", self.devdir, "allow", self.pc.my_id(), "--name", "bench pc"]), 0)
            self.assertEqual(device.main(["--dir", self.devdir, "list"]), 0)
        self.assertIn(self.svc.id, out.getvalue())
        self.assertIn("bench pc", out.getvalue())
        with redirect_stderr(io.StringIO()):
            self.assertEqual(device.main(["--dir", self.devdir, "allow", "not-an-id"]), 2)
            self.assertEqual(device.main(["--dir", self.devdir, "revoke", "nobody"]), 1)
        time.sleep(device.WATCH_S + 1)   # the service reloads paired.json
        sock, _, _ = self.pc.link_socket(self.entry, "diag", 10)
        sock.close()

    def test_diag_link_commands(self):
        code, out, err = _cli("link", "id")
        self.assertEqual((code, out.strip()), (0, self.pc.my_id()), err)
        code, out, _ = _cli("link", "list")
        self.assertIn("testdev", out)
        self.assertIn("link ID known", out)
        self.pair()
        code, out, _ = _cli("link", "list")
        self.assertIn("paired", out)
        code, out, err = _cli("--runtime", "link:testdev", "status")
        self.assertEqual(code, 0, err)
        code, _, err = _cli("--runtime", "link:nobody", "status")
        self.assertEqual(code, 1)
        self.assertIn("no remembered runtime", err)
        code, out, _ = _cli("link", "forget", "testdev")
        self.assertEqual(code, 0)
        self.assertEqual(self.pc.runtimes(), [])

    def test_https_client_over_the_link(self):
        self.pair()
        conn = runtime._Connection("link:testdev", 8443, context=None, timeout=5)
        # The echo server is not TLS: the handshake fails, after the link connected.
        import ssl
        conn.ctx = ssl._create_unverified_context()
        with self.assertRaises((ssl.SSLError, OSError)):
            conn.connect()


class Unavailable(unittest.TestCase):
    def test_commands_say_so(self):
        with mock.patch("canworks.link.available", return_value=False), \
                mock.patch("canworks.link.pc.available", return_value=False):
            code, _, err = _cli("link", "id")
        self.assertEqual(code, 2)
        self.assertIn("not available on this platform", err)

    def test_direct_connection_without_iroh(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        with mock.patch.dict(os.environ, {"CANWORKS_CONFIG_DIR": tmp}), \
                mock.patch("canworks.link.pc.available", return_value=False), FakePlugin() as fp:
            code, out, err = _cli("--runtime", fp.runtime, "status")
        self.assertEqual(code, 0, err)
        self.assertNotIn("path:", out)


if __name__ == "__main__":
    unittest.main()
