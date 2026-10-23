"""The CiA 309-3 client (canworks.cia309) and canworks-diag gateway against
the fake plugin (canopen-cia309-gateway "Gateway client in the command-line
tools"); the plugin itself is tested in test/cia309/run.sh."""

import io
import json
import os
import socket
import threading
import time
import unittest
from contextlib import redirect_stderr
from unittest import mock

from canworks import cia309, contract, diag

from .fake_diag import TOKEN, TWO_NETWORKS, FakePlugin

INFO = {"protocol": "CiA 309-3", "version": "2.1", "allow_changes": False, "allow_force": False, "default_net": None,
        "nets": [{"number": 1, "name": "io", "protocol": "canopen", "role": "master", "served": True},
                 {"number": 2, "name": "drives", "protocol": "canopen", "role": "master", "served": True}]}


def run(*argv):
    out, err = io.StringIO(), io.StringIO()
    with mock.patch.dict(os.environ, {diag.TOKEN_ENV: TOKEN}, clear=False), redirect_stderr(err):
        args = diag.parser().parse_args(list(argv))
        try:
            code = diag.run(args, out)
        except diag.DiagError as e:
            err.write("canworks-diag: %s\n" % e)
            code = 2 if e.kind == "usage" else 1
    return code, out.getvalue(), err.getvalue()


class LineServer:
    """A plain TCP server that answers CiA 309-3 lines from a table."""

    def __init__(self, answers, notes=()):
        self.answers = answers
        self.notes = list(notes)
        self.srv = socket.socket()
        self.srv.bind(("127.0.0.1", 0))
        self.srv.listen(1)
        self.port = self.srv.getsockname()[1]
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self):
        conn, _ = self.srv.accept()
        buf = b""
        while True:
            data = conn.recv(4096)
            if not data:
                return
            buf += data
            while b"\n" in buf:
                line, _, buf = buf.partition(b"\n")
                text = line.decode().strip()
                seq, _, rest = text.partition("] ")
                for n in self.notes:
                    conn.sendall(n.encode() + b"\r\n")
                self.notes = []
                conn.sendall(("%s] %s\r\n" % (seq, self.answers.get(rest, "OK"))).encode())


class ClientTests(unittest.TestCase):
    def test_answers_errors_and_notifications(self):
        s = LineServer({"1 2 r 0x1018 1 u32": "0x000001A2", "1 2 r 0x2100 0 u8": "ERROR: 06020000 (Object does "
                                                                                    "not exist)",
                        "1 2 w 0x2000 1 u8 3": "ERROR: 102 (Request not processed due to internal state)"},
                       notes=["1 3 EMCY 5030 01 0 0 0 0 0", "# 2 notifications lost (the client did not read them)"])
        c = cia309.Client.plain("127.0.0.1", s.port, timeout=3)
        try:
            self.assertEqual(c.command("1 2 r 0x1018 1 u32"), "0x000001A2")
            self.assertEqual(c.notifications, ["1 3 EMCY 5030 01 0 0 0 0 0"])
            self.assertEqual(len(c.comments), 1)
            with self.assertRaises(cia309.GatewayError) as e:
                c.command("1 2 r 0x2100 0 u8")
            self.assertEqual(e.exception.code, 0x06020000)
            self.assertEqual(cia309.error_code(c.request("1 2 w 0x2000 1 u8 3")), 102)
            self.assertEqual(c.request("1 2 start"), "OK")
        finally:
            c.close()

    def test_pipelined_answers_matched_by_sequence(self):
        s = LineServer({"a": "1", "b": "2"})
        c = cia309.Client.plain("127.0.0.1", s.port, timeout=3)
        try:
            first, second = c.send("a"), c.send("b")
            self.assertEqual(c.answer(second), "2")
            self.assertEqual(c.answer(first), "1")
        finally:
            c.close()


class GatewayCommand(unittest.TestCase):
    def fake(self, **kw):
        f = FakePlugin(networks=TWO_NETWORKS, **kw)
        f.cia309 = json.loads(json.dumps(INFO))
        f.cia309_answers = {"1 2 r 0x1018 1 u32": "0x000001A2", "2 2 r 0x1008 0 vs": "\"drive\""}
        return f

    def test_list(self):
        with self.fake() as f:
            code, out, err = run("--runtime", "127.0.0.1:%d" % f.port, "gateway", "--list")
        self.assertEqual(code, 0, err)
        self.assertIn("networks 1 = io, 2 = drives", out)
        self.assertIn("read-only", out)

    def test_exec_lines(self):
        with self.fake() as f:
            code, out, err = run("--runtime", "127.0.0.1:%d" % f.port, "gateway", "--exec", "1 2 r 0x1018 1 u32",
                                 "--exec", "[9] 2 2 r 0x1008 0 vs")
            lines = list(f.cia309_lines)
        self.assertEqual(code, 0, err)
        self.assertEqual(out.splitlines(), ["0x000001A2", "\"drive\""])
        self.assertEqual(lines, ["[1] 1 2 r 0x1018 1 u32", "[9] 2 2 r 0x1008 0 vs"])

    def test_network_sets_the_default(self):
        with self.fake() as f:
            code, out, err = run("--runtime", "127.0.0.1:%d" % f.port, "gateway", "--network", "drives",
                                 "--exec", "2 r 0x1008 0 vs")
            lines = list(f.cia309_lines)
        self.assertEqual(code, 0, err)
        self.assertEqual(lines[0], "[1] set network 2")
        with self.fake() as f:
            code, _, err = run("--runtime", "127.0.0.1:%d" % f.port, "gateway", "--network", "motion", "--list")
        self.assertEqual(code, 1)
        self.assertIn("no network 'motion'", err)

    def test_error_answer_exits_1(self):
        with self.fake() as f:
            f.cia309_answers["1 2 stop"] = "ERROR: 102 (Request not processed due to internal state)"
            code, out, _ = run("--runtime", "127.0.0.1:%d" % f.port, "gateway", "--exec", "1 2 stop")
        self.assertEqual(code, 1)
        self.assertIn("ERROR: 102", out)

    def test_older_plugin_and_not_configured(self):
        with self.fake() as f:
            f.cia309 = None  # the fake answers "unknown op"
            code, _, err = run("--runtime", "127.0.0.1:%d" % f.port, "gateway", "--list")
        self.assertEqual(code, 1)
        self.assertIn(diag.GATEWAY_TOO_OLD, err)
        with self.fake() as f:
            f.cia309 = "off"
            code, _, err = run("--runtime", "127.0.0.1:%d" % f.port, "gateway", "--list")
        self.assertEqual(code, 1)
        self.assertIn("cia309 gateway not configured", err)
        with self.fake() as f:
            f.cia309_max = 0
            code, _, err = run("--runtime", "127.0.0.1:%d" % f.port, "gateway", "--list")
        self.assertIn("too many gateway clients", err)

    def test_listen_refuses_a_network_address(self):
        code, _, err = run("--runtime", "127.0.0.1:1", "gateway", "--listen", "0.0.0.0:7533")
        self.assertEqual(code, 2)
        self.assertIn("not a loopback address", err)
        self.assertEqual(diag.parse_listen("127.0.0.1:7600"), ("127.0.0.1", 7600))
        self.assertEqual(diag.parse_listen("[::1]:7600"), ("::1", 7600))
        with self.assertRaises(diag.DiagError):
            diag.parse_listen("127.0.0.1:x")

    def test_listen_tunnels_a_local_tool(self):
        """A CiA 309-3 tool on the PC connects to the local port and needs no
        token: its lines reach the runtime's gateway."""
        with self.fake() as f:
            probe = socket.socket()
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
            probe.close()
            out = io.StringIO()
            args = diag.parser().parse_args(["--runtime", "127.0.0.1:%d" % f.port, "--token", TOKEN, "gateway",
                                             "--listen", "127.0.0.1:%d" % port])
            threading.Thread(target=lambda: diag.run(args, out), daemon=True).start()
            for _ in range(100):
                if "until Ctrl-C" in out.getvalue():
                    break
                time.sleep(0.05)
            tool = cia309.Client.plain("127.0.0.1", port, timeout=5)
            try:
                self.assertEqual(tool.command("1 2 r 0x1018 1 u32"), "0x000001A2")
            finally:
                tool.close()
            self.assertIn("[1] 1 2 r 0x1018 1 u32", f.cia309_lines)

    def _listen(self, f):
        """canworks-diag gateway --listen on a free local port: the port."""
        probe = socket.socket()
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
        probe.close()
        out = io.StringIO()
        args = diag.parser().parse_args(["--runtime", "127.0.0.1:%d" % f.port, "--token", TOKEN, "gateway",
                                         "--listen", "127.0.0.1:%d" % port])
        threading.Thread(target=lambda: diag.run(args, out), daemon=True).start()
        for _ in range(100):
            if "until Ctrl-C" in out.getvalue():
                break
            time.sleep(0.05)
        return port

    @staticmethod
    def _read_all(sock):
        sock.settimeout(5)
        data = b""
        while True:
            got = sock.recv(4096)
            if not got:
                return data.decode()
            data += got

    def test_listen_closes_a_web_request(self):
        """A web page posting to the local port: its first line is not CiA
        309-3, so it gets one ERROR: 101 and is closed, and nothing reaches
        the runtime (no gateway session is even opened)."""
        with self.fake() as f, redirect_stderr(io.StringIO()):
            port = self._listen(f)
            opened = len([r for r in f.requests if r.get("op") == "cia309"])
            web = socket.create_connection(("127.0.0.1", port), timeout=5)
            try:
                web.sendall(b"POST / HTTP/1.1\r\nHost: 127.0.0.1:%d\r\nContent-Type: text/plain\r\n\r\n"
                            b"[1] 1 5 w 0x2000 0 u8 1\r\n" % port)
                got = self._read_all(web)
            finally:
                web.close()
            self.assertEqual(got.count("ERROR: 101"), 1, got)
            self.assertEqual(len(got.splitlines()), 1, got)
            self.assertEqual(f.cia309_lines, [])
            self.assertEqual(len([r for r in f.requests if r.get("op") == "cia309"]), opened)

    def test_listen_keeps_a_session_after_a_later_typo(self):
        with self.fake() as f:
            port = self._listen(f)
            tool = socket.create_connection(("127.0.0.1", port), timeout=5)
            try:
                tool.sendall(b"\r\n# a comment\r\n[1] 1 2 r 0x1018 1 u32\r\n")
                rfile = tool.makefile("rb")
                self.assertEqual(rfile.readline().strip(), b"[1] 0x000001A2")
                tool.sendall(b"[2] 1 2 r 0x1018\r\n[3] 1 2 r 0x1018 1 u32\r\n")
                self.assertEqual(rfile.readline().strip(), b"[2] OK")  # the fake does not parse
                self.assertEqual(rfile.readline().strip(), b"[3] 0x000001A2")
            finally:
                tool.close()
            self.assertIn("[2] 1 2 r 0x1018", f.cia309_lines)

    def test_listen_takes_four_local_connections(self):
        """Four local clients may be connected; a fifth gets one ERROR: 102
        and is closed, and a slot that frees takes a new client."""
        with self.fake() as f, redirect_stderr(io.StringIO()) as err:
            port = self._listen(f)
            held = [socket.create_connection(("127.0.0.1", port), timeout=5) for _ in range(diag.FORWARD_MAX)]
            try:
                fifth = socket.create_connection(("127.0.0.1", port), timeout=5)
                got = self._read_all(fifth)
                fifth.close()
                self.assertEqual(got, "ERROR: 102 (too many local connections, at most 4)\r\n")
                held.pop().close()
                time.sleep(0.2)
                tool = socket.create_connection(("127.0.0.1", port), timeout=5)
                held.append(tool)
                tool.sendall(b"[1] 1 2 r 0x1018 1 u32\r\n")
                self.assertEqual(tool.makefile("rb").readline().strip(), b"[1] 0x000001A2")
            finally:
                for s in held:
                    s.close()
            self.assertIn("refused a local connection", err.getvalue())

    def test_link_forwarder_holds_a_fifth_connection(self):
        """canworks-diag link open: past four local connections the next one
        waits (unaccepted) until one ends."""
        srv = socket.socket()
        srv.bind(("127.0.0.1", 0))
        srv.listen(8)
        release, started = threading.Event(), []

        def handle(local):
            started.append(local)
            release.wait(5)
            local.close()
        threading.Thread(target=diag._serve_local, args=(srv, handle, None), daemon=True).start()
        clients = [socket.create_connection(srv.getsockname(), timeout=5) for _ in range(diag.FORWARD_MAX + 1)]
        try:
            time.sleep(0.2)
            self.assertEqual(len(started), diag.FORWARD_MAX)
            release.set()
            for _ in range(50):
                if len(started) == diag.FORWARD_MAX + 1:
                    break
                time.sleep(0.02)
            self.assertEqual(len(started), diag.FORWARD_MAX + 1)
        finally:
            for c in clients:
                c.close()
            srv.close()

    def test_first_line_check(self):
        for line in ("[1] 1 2 r 0x1018 1 u32", "1 2 r 0x1018 1 u32", "[7] info version", "[2] 1 lss_switch_sel 1 2 3 4",
                     "[3] set network 2", "[4]2 start", "[5] 1 2 W 0x2000 0 u8 1", "[0x10] 1 _lss_fastscan"):
            self.assertTrue(cia309.looks_like_command(line), line)
        for line in ("POST / HTTP/1.1", "GET /index.html HTTP/1.1", "Host: 127.0.0.1:7533", "OPTIONS * HTTP/1.1",
                     "[1] 1 2 frobnicate", "{\"op\":\"status\"}", "[1]"):
            self.assertFalse(cia309.looks_like_command(line), line)

    def test_status_line(self):
        line = diag.gateway_status_line({"listen": "127.0.0.1:7533", "listening": True, "allow_changes": False,
                                         "sessions": [{"address": "10.0.0.5", "kind": "tunnelled", "commands": 3}]})
        self.assertEqual(line, "CiA 309-3 gateway on 127.0.0.1:7533 (read-only): 1 session: 10.0.0.5 tunnelled "
                               "3 commands")
        self.assertIn("without a plain port", diag.gateway_status_line({"listen": None, "sessions": []}))


class Configurator(unittest.TestCase):
    def test_saved_key_order(self):
        from canworks.configurator import server
        cfg = server.canonical({"cia309": {"allow_force": False, "port": 7533}, "networks": [], "schema_version": 2})
        self.assertEqual(list(cfg), ["schema_version", "networks", "cia309"])
        self.assertEqual(list(cfg["cia309"]), ["port", "allow_force"])
        v1 = server.canonical({"master": {"cia309": {"max_clients": 2, "port": 0}, "node_id": 1}})
        self.assertEqual(list(v1["master"]), ["node_id", "cia309"])
        self.assertEqual(list(v1["master"]["cia309"]), ["port", "max_clients"])

    def test_check_names_the_bind_field(self):
        r = contract.check_config({"schema_version": 2, "networks": [], "cia309": {"bind": "0.0.0.0"}}, "canworks.json")
        msgs = [m for m in r.errors if "cia309.bind" in m.message] if hasattr(r.errors[0], "message") else \
            [m for m in r.errors if "cia309.bind" in str(m)]
        self.assertTrue(msgs, r.errors)


class NetworkDocs(unittest.TestCase):
    def test_numbers_and_gateway_rpdos(self):
        from canworks import docexport, docwriter
        from .helpers import REPO
        path = os.path.join(REPO, "config", "pingpong", "canopen_config.json")
        with open(path) as f:
            cfg = json.load(f)
        plain = docexport.build(cfg, path)
        self.assertNotIn("cia309", plain)
        cfg["cia309"] = {"allow_changes": True}
        model = docexport.build(cfg, path)
        self.assertEqual(model["cia309"]["nets"], [{"number": 1, "name": "vcan0"}])
        self.assertEqual(model["networks"][0]["cia309_number"], 1)
        tpdo = [p for p in model["networks"][0]["nodes"][0]["pdos"] if p["kind"] == "TPDO"][0]
        self.assertEqual(tpdo["gateway_rpdo"], 5)  # node 2's TPDO 1
        html = docwriter.write(model)
        self.assertIn("CiA 309-3: r p 5", html)
        self.assertIn('id="cia309"', html)


class Contract(unittest.TestCase):
    def test_numbering(self):
        two = {"schema_version": 2, "networks": [{"name": "io"}, {"name": "drives"}], "cia309": {}}
        self.assertEqual(contract.cia309_numbering(two), [(1, "io", 0), (2, "drives", 1)])
        two["cia309"] = {"nets": {"10": "drives"}}
        self.assertEqual(contract.cia309_numbering(two), [(10, "drives", 1)])
        self.assertEqual(contract.cia309_numbering({"schema_version": 2, "networks": []}), [])
        v1 = {"master": {"node_id": 1, "cia309": {}}}
        self.assertEqual(contract.cia309_numbering(v1), [(1, "", 0)])


if __name__ == "__main__":
    unittest.main()
