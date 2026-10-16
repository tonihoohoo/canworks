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


def _answer(instance, link_id):
    """A direct mDNS answer of the runtime `instance` with link ID `link_id`."""
    import struct

    def name(text, ptr=None):
        out = b"".join(bytes([len(p)]) + p.encode() for p in text.split(".") if p)
        return out + (struct.pack(">H", 0xC000 | ptr) if ptr is not None else b"\0")

    def rr(owner, rtype, rdata):
        return owner + struct.pack(">HHIH", rtype, 0x8001, 120, len(rdata)) + rdata

    q = name("_canworks._tcp.local")                      # at offset 12
    txt = b"".join(bytes([len(t)]) + t for t in (b"v=1", b"diag=7531", b"runtime=8443", b"id=" + link_id.encode(),
                                                 b"link=7533"))
    answers = [rr(b"\xc0\x0c", 12, name(instance, 12)),       # PTR -> <instance>._canworks._tcp.local
               rr(name(instance, 12), 33, struct.pack(">HHH", 0, 0, 7531) + name(instance + ".local")),
               rr(name(instance, 12), 16, txt)]
    return struct.pack(">HHHHHH", 0x6377, 0x8400, 1, 0, 0, 3) + q + struct.pack(">HH", 12, 1) + b"".join(answers)


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

    def test_parse_a_direct_answer(self):
        import struct
        r = discovery.parse_answer(_answer("line3", "abc"))
        self.assertEqual(r["name"], "line3")
        self.assertEqual(r["port"], 7531)
        self.assertEqual(r["txt"], {"v": "1", "diag": "7531", "runtime": "8443", "id": "abc", "link": "7533"})
        self.assertIsNone(discovery.parse_answer(struct.pack(">HHHHHH", 1, 0x8400, 0, 0, 0, 0)))

    def test_direct_query_takes_the_answer_of_the_asked_host_only(self):
        host = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        host.bind(("127.0.0.1", 0))
        # The other host: macOS has no 127.0.0.2, so it sends from 127.0.0.1
        # too and query_host's socket sees its datagrams as from 127.0.0.2.
        other = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        other.bind(("127.0.0.1", 0))
        for sock in (host, other):
            self.addCleanup(sock.close)
        other_port = other.getsockname()[1]

        class Socket(socket.socket):
            def recvfrom(self, *args):
                data, src = super().recvfrom(*args)
                return data, ("127.0.0.2", src[1]) if src[1] == other_port else src
        patch = mock.patch.object(discovery.socket, "socket", Socket)
        patch.start()
        self.addCleanup(patch.stop)

        def answer():
            _, asker = host.recvfrom(9000)
            other.sendto(_answer("line3", "forged"), asker)   # another host, first
            time.sleep(0.05)
            host.sendto(_answer("line3", "real"), asker)
        threading.Thread(target=answer, daemon=True).start()
        r = discovery.query_host("127.0.0.1", timeout=2, port=host.getsockname()[1])
        self.assertEqual((r["name"], r["id"]), ("line3", "real"))

        def forged_only():
            _, asker = host.recvfrom(9000)
            other.sendto(_answer("line3", "forged"), asker)
        threading.Thread(target=forged_only, daemon=True).start()
        self.assertIsNone(discovery.query_host("127.0.0.1", timeout=0.3, port=host.getsockname()[1]))

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


class ChangedIdentity(unittest.TestCase):
    """A paired runtime that answers discovery with another link ID."""

    def setUp(self):
        from canworks.link import pc
        self.pc = pc
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        for p in (mock.patch.dict(os.environ, {"CANWORKS_CONFIG_DIR": self.tmp, "CANWORKS_LINK": "on"}),
                  mock.patch.object(pc, "available", return_value=True),
                  mock.patch.dict(pc._after, clear=True)):
            p.start()
            self.addCleanup(p.stop)
        pc.remember("line3", hosts=["192.0.2.7"], id="old" * 10, link_addrs=["192.0.2.7:7533"], paired=True)
        self.answer = {"name": "line3", "addresses": ["192.0.2.7"], "diag": 7531, "runtime": 8443,
                       "id": "new" * 10, "link": 7533}

    def login(self, repair=False):
        def pair(entry, token):
            self.paired_with = dict(entry)
            return self.pc.remember(entry["name"], paired=True)
        self.paired_with = None
        with mock.patch.object(discovery, "find_address", return_value=self.answer), \
                mock.patch.object(self.pc, "pair", side_effect=pair), \
                mock.patch.object(self.pc, "refresh") as refresh:
            job = self.pc.after_login("192.0.2.7", 7531, TOKEN, wait=5, repair=repair)
        self.refreshed = refresh.called
        return job

    def test_not_stored_and_reported(self):
        job = self.login()
        entry = self.pc.find("line3")
        self.assertEqual(entry["id"], "old" * 10)
        self.assertTrue(entry["paired"])
        self.assertIsNone(self.paired_with)
        self.assertTrue(job.get("changed"))
        self.assertIn("identity changed", job["note"])
        self.assertIn("--repair", job["note"])

    def test_repair_takes_the_new_id_and_pairs(self):
        self.login(repair=True)
        self.assertEqual(self.paired_with["id"], "new" * 10)
        self.assertFalse(self.paired_with["paired"])
        entry = self.pc.find("line3")
        self.assertEqual((entry["id"], entry["paired"]), ("new" * 10, True))

    def test_same_id_refreshes(self):
        self.answer["id"] = "old" * 10
        job = self.login()
        self.assertTrue(self.refreshed)
        self.assertIsNone(job["note"])

    def test_repair_option(self):
        self.assertTrue(diag.parser().parse_args(["--runtime", "line3", "--repair", "status"]).repair)


class _FakeConn:
    """An accepted link connection from `pc` at `addr`, without iroh: its
    streams are put on `streams` (None ends the connection)."""

    def __init__(self, pc, addr):
        self.pc, self.addr, self.closed = pc, addr, None
        self.streams = asyncio.Queue()

    def remote_id(self):
        return self.pc

    def paths(self):
        from types import SimpleNamespace
        return [SimpleNamespace(is_selected=True, is_relay=False, remote_addr=self.addr)]

    async def accept_bi(self):
        bi = await self.streams.get()
        if bi is None:
            raise ConnectionError("closed")
        return bi

    def close(self, code, reason):
        self.closed = reason
        self.streams.put_nowait(None)


class _FakeIncoming:
    def __init__(self, conn):
        self.conn = conn

    async def accept(self):
        return self

    async def connect(self):
        return self.conn


@unittest.skipUnless(HAVE_IROH, "the iroh package is not installed")
class Limits(unittest.TestCase):
    """The service's limits on PCs that are not paired, on fake connections."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.svc = device.Service(self.tmp, name="testdev")
        self.svc.verifier = diag.token_verifier(TOKEN)
        self.svc.pairing = "lan"
        self.out = io.StringIO()
        p = mock.patch("sys.stdout", self.out)
        p.start()
        self.addCleanup(p.stop)

    def run_async(self, coro):
        return asyncio.new_event_loop().run_until_complete(coro)

    def test_unpaired_connections_are_capped(self):
        async def go():
            n = iter(range(1000))

            def connect(addr, pc=None):
                conn = _FakeConn(pc or "pc%d" % next(n), addr)
                return conn, asyncio.ensure_future(self.svc._accept(_FakeIncoming(conn)))
            one = [connect("192.168.1.5:%d" % (4000 + i)) for i in range(20)]
            await asyncio.sleep(0.05)
            kept = [c for c, _ in one if c.closed is None]
            self.assertEqual(len(kept), 2)
            self.assertTrue(all(c.closed == b"too many unpaired from this address" for c, _ in one
                                if c.closed is not None))
            many = [connect("192.168.1.%d:4000" % (10 + i)) for i in range(10)]
            await asyncio.sleep(0.05)
            self.assertEqual(len([c for c, _ in many if c.closed is None]), 6)  # 8 unpaired in all
            self.assertEqual(len(self.svc.unpaired), 8)
            self.svc.paired.add("known", "office", "lan")
            paired, _ = connect("192.168.1.5:5000", pc="known")
            await asyncio.sleep(0.05)
            self.assertIsNone(paired.closed)
            for c, _ in one + many + [(paired, None)]:
                if c.closed is None:
                    c.close(0, b"bye")
            await asyncio.gather(*[t for _, t in one + many if t])
            self.assertEqual(self.svc.unpaired, {})
        self.run_async(go())

    def test_streams_of_an_unpaired_connection_are_capped(self):
        running, finished = [], []

        async def stream(conn, pc, bi):
            running.append(bi)
            await asyncio.sleep(1)

        class Bi:
            def send(self):
                return self

            async def finish(self):
                finished.append(self)

        async def go():
            conn = _FakeConn("pc1", "192.168.1.5:4000")
            task = asyncio.ensure_future(self.svc._accept(_FakeIncoming(conn)))
            for _ in range(5):
                conn.streams.put_nowait(Bi())
            await asyncio.sleep(0.05)
            conn.close(0, b"bye")
            await task
        with mock.patch.object(self.svc, "_stream", stream):
            self.run_async(go())
        self.assertEqual((len(running), len(finished)), (device.UNPAIRED_STREAMS, 5 - device.UNPAIRED_STREAMS))

    def test_concurrent_pairing_attempts_are_counted_before_the_login(self):
        started = []

        async def login(conn, pc, head, reader, send, **kw):
            started.append(pc)
            await asyncio.sleep(0.05)
            return False  # a wrong token

        class Send:
            def __init__(self):
                self.lines = []

            async def write_all(self, b):
                self.lines.append(json.loads(b))

        async def go():
            sends = [Send() for _ in range(15)]
            await asyncio.gather(*[self.svc._pair(_FakeConn("pc%d" % i, "192.168.1.%d:4000" % (10 + i)), "pc%d" % i,
                                                  {"t": "pair"}, None, sends[i]) for i in range(15)])
            return sends
        with mock.patch.object(self.svc, "_login", login):
            sends = self.run_async(go())
        self.assertEqual(len(started), device.PAIR_FAILS_PER_MIN)
        refused = [s.lines[0]["error"] for s in sends if s.lines]
        self.assertEqual(len(refused), 15 - device.PAIR_FAILS_PER_MIN)
        self.assertTrue(all("try again in a minute" in e for e in refused), refused)


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
        self.loop_thread = threading.Thread(target=self.loop.run_forever, daemon=True)
        self.loop_thread.start()
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
        # Stop the service, then end every task still on its loop (streams,
        # pumps) and close the loop. A loop left running tasks and closed
        # later by the garbage collector makes iroh's callbacks fail ("Event
        # loop is closed"), and on a runner with few cores the endpoints of
        # the next tests then never bind.
        async def shutdown():
            await self.svc.stop()
            tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        try:
            asyncio.run_coroutine_threadsafe(shutdown(), self.loop).result(10)
        except Exception:
            pass  # already stopped
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.loop_thread.join(5)
        if not self.loop.is_running():
            self.loop.close()
        # This test's PC side: its connections and endpoint (a new key per
        # test, so the endpoint is not reused).
        try:
            self.pc.LOOP.run(self.pc._close_all(), 5)
        except Exception:
            pass
        self.pc._conns.clear()
        self.pc._endpoints.clear()

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
