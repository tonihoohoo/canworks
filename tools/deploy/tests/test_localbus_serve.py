"""The adapter server (canopen-remote-adapter, canworks-diag adapter-serve) on
python-can's virtual bus, against fake devices, and the PC side
(--adapter remote:HOST, localbus/remote.py): the SCRAM login bound to the
certificate, the operations of a local adapter, --allow-changes, the
limits, the token, the systemd service files and discovery. No CAN
hardware; the server runs in this process on 127.0.0.1."""

import io
import itertools
import os
import shutil
import signal
import socket
import ssl
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

import can

from canworks import diag
from canworks.link import discovery
from canworks.localbus import LocalBus, parse
from canworks.localbus import adapter as adapter_mod
from canworks.localbus import core as core_mod
from canworks.localbus import remote, serve

from . import fake_tls
from .fake_canopen import FakeDevice
from .fake_diag import FakePlugin
from .test_configurator_server import DEPLOY
from .test_localbus import cli

TOKEN = "adapter-test-token"
_n = itertools.count(1)


def closed(s):
    """What the server sent before closing: b"" (a reset counts as closed)."""
    try:
        return s.recv(100)
    except ConnectionResetError:
        return b""


class ServerBase(unittest.TestCase):
    """A server on a fresh virtual channel; `self.log` holds its log lines."""

    allow_changes = True

    def setUp(self):
        self.ch = "serve-test-%d-%d" % (os.getpid(), next(_n))
        self.devices, self.clients, self.log = [], [], []
        self.srv = self.server()

    def server(self, verifier=None, **kw):
        kw.setdefault("allow_changes", self.allow_changes)
        kw.setdefault("cert_hash", fake_tls.CERT_HASH)
        kw.setdefault("context", fake_tls.server_context())
        srv = serve.AdapterServer(parse("virtual:" + self.ch), 250000, verifier or diag.token_verifier(TOKEN),
                                  bind="127.0.0.1", port=0, listen_s=0.05, name="benchbox",
                                  log=self.log.append, **kw)
        threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        return srv

    def tearDown(self):
        for c in self.clients:
            c.close()
        for d in self.devices:
            d.close()

    def device(self, node, **kw):
        d = FakeDevice(self.ch, node, **kw)
        self.devices.append(d)
        return d

    def client(self, token=TOKEN, srv=None, connect=True, **kw):
        c = remote.RemoteBus("127.0.0.1", (srv or self.srv).port, token, timeout=3.0, **kw)
        self.clients.append(c)
        if connect:
            c.connect()
        return c

    def watch(self):
        bus = can.Bus(interface="virtual", channel=self.ch, receive_own_messages=False)
        self.addCleanup(bus.shutdown)
        return bus

    def wait(self, cond, timeout=3.0):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if cond():
                return True
            time.sleep(0.02)
        return False


class Login(ServerBase):
    def test_right_token(self):
        self.device(5, heartbeat_s=0.05)
        c = self.client()
        self.assertTrue(c.info["local"])
        self.assertEqual(c.info["adapter"], "virtual:" + self.ch)
        self.assertEqual(c.info["remote"], "benchbox")
        self.assertEqual(c.info["bitrate"], 250000)
        self.assertFalse(c.info["allow_changes"])  # the PC's switch is off
        st = c.status()
        self.assertTrue(st["local"])
        self.assertEqual(st["remote"], "benchbox")
        self.assertEqual(self.srv.status()["pcs"][0]["address"], "127.0.0.1")
        self.assertIn("127.0.0.1 connected", self.log)

    def test_wrong_token_delayed_and_logged(self):
        with mock.patch.object(serve, "LOGIN_BACKOFF_S", 0.4):
            c = self.client(token="wrong", connect=False)
            with self.assertRaises(diag.DiagError) as e:
                c.connect()
            self.assertEqual(e.exception.kind, "token")
            self.assertIn("wrong token", str(e.exception))
            self.assertIn("login from 127.0.0.1 refused: wrong token", self.log)
            t0 = time.monotonic()
            self.client()  # the right token right after: waits out the delay
            self.assertGreaterEqual(time.monotonic() - t0, 0.3)

    def test_wrong_channel_binding(self):
        # A server whose login is bound to another certificate (a machine in
        # the middle re-encrypting): the proof does not match, nothing opens.
        srv = self.server(cert_hash=b"\x01" * 32)
        c = self.client(srv=srv, connect=False)
        with self.assertRaises(diag.DiagError) as e:
            c.connect()
        self.assertEqual(e.exception.kind, "token")
        self.assertNotIn("virtual:" + self.ch, core_mod._cores)

    def test_plain_connection_closed(self):
        s = socket.create_connection(("127.0.0.1", self.srv.port), timeout=3)
        s.sendall(b'{"op": "hello", "id": 1}\n')
        self.assertEqual(closed(s), b"")
        s.close()
        self.assertNotIn("virtual:" + self.ch, core_mod._cores)

    def test_too_many_failures_refuse_logins(self):
        with mock.patch.object(serve, "LOGIN_BACKOFF_S", 0.0), mock.patch.object(serve, "FAILED_PER_MINUTE", 2):
            for _ in range(2):
                with self.assertRaises(diag.DiagError):
                    self.client(token="wrong")
            with self.assertRaises(diag.DiagError):
                self.client()  # the right token, but logins wait
        self.assertTrue(any("failed logins in the last minute" in line for line in self.log))

    def test_bitrate_refused_is_the_login_error(self):
        def refuse(core, check_node=None):
            raise core_mod.BitrateRefused("the bus does not run at 250 kbit/s (5 error frames and 0 valid frames)")
        with mock.patch.object(core_mod, "check_bitrate", refuse):
            with self.assertRaises(diag.DiagError) as e:
                self.client()
        self.assertEqual(e.exception.kind, "bitrate")
        self.assertIn("does not run at 250 kbit/s", str(e.exception))

    def test_runtime_is_not_an_adapter_server(self):
        with FakePlugin(token=TOKEN) as fp:
            c = remote.RemoteBus("127.0.0.1", fp.port, TOKEN, timeout=3.0)
            with self.assertRaises(diag.DiagError) as e:
                c.connect()
        self.assertIn("is a runtime, not an adapter server: connect without remote:", str(e.exception))

    @unittest.skipUnless(shutil.which("openssl"), "no openssl command")
    def test_certificate_made_at_start(self):
        ctx, digest = serve.make_context()
        self.assertEqual(len(digest), 32)
        self.assertIsInstance(ctx, ssl.SSLContext)
        srv = self.server(context=ctx, cert_hash=digest)
        self.device(5, heartbeat_s=0.05)
        self.assertTrue(self.client(srv=srv).info["local"])

    def test_openssl_missing(self):
        with self.assertRaises(serve.ServeError) as e:
            serve.make_context(openssl="canworks-no-such-openssl")
        self.assertIn("install the openssl package", str(e.exception))


class AdapterMachine(ServerBase):
    """Errors about the server's own adapter name its machine on the PC
    (configurator-survive-sleep)."""

    def setUp(self):
        self.devices, self.clients, self.log = [], [], []

    @unittest.skipUnless(sys.platform.startswith("linux"), "socketcan on Linux")
    def test_interface_missing_on_the_server(self):
        real = subprocess.run

        def no_interface(cmd, *a, **kw):
            if cmd[:1] == ["ip"]:
                return subprocess.CompletedProcess(cmd, 1, "", 'Device "slcan0" does not exist.')
            return real(cmd, *a, **kw)

        kw = dict(cert_hash=fake_tls.CERT_HASH, context=fake_tls.server_context())
        srv = serve.AdapterServer(parse("socketcan:slcan0"), 250000, diag.token_verifier(TOKEN), bind="127.0.0.1",
                                  port=0, listen_s=0.05, name="adapterbox", log=self.log.append, **kw)
        threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        with mock.patch.object(adapter_mod.subprocess, "run", no_interface):
            with self.assertRaises(diag.DiagError) as e:
                self.client(srv=srv)
        text = str(e.exception)
        self.assertIn("no CAN interface slcan0 on the adapter machine 127.0.0.1", text)
        self.assertNotIn("this PC", text)
        self.assertNotIn("this machine", text)
        # The server's own log says it for its machine.
        self.assertTrue(any("no CAN interface slcan0 on this machine" in line for line in self.log), self.log)

    def test_local_adapter_words(self):
        e = diag.DiagError("unreachable", "no gs_usb adapter 1 on this machine (1 found)")
        c = remote.RemoteBus("linuxbox", 7536, TOKEN)
        self.assertEqual(str(c._named(e)), "no gs_usb adapter 1 on the adapter machine linuxbox (1 found)")
        self.assertEqual(c._named(e).kind, "unreachable")
        other = diag.DiagError("refused", "node 5 does not answer")
        self.assertIs(c._named(other), other)


@unittest.skipUnless(os.name == "posix" and shutil.which("openssl"), "signals on POSIX; the certificate needs openssl")
class StopLine(unittest.TestCase):
    """adapter-serve logs how it stopped, as a service's journal shows it."""

    def run_server(self, sig):
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        env = dict(os.environ, PYTHONPATH=DEPLOY, CANWORKS_CONFIG_DIR=folder)
        proc = subprocess.Popen([sys.executable, "-m", "canworks.diag", "adapter-serve", "--adapter",
                                 "virtual:stop-line-%d" % os.getpid(), "--bitrate", "250", "--port", str(port),
                                 "--bind", "127.0.0.1"],
                                env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
        self.addCleanup(lambda: proc.poll() is None and proc.kill())
        first = proc.stderr.readline()
        self.assertIn("serving adapter", first)
        proc.send_signal(sig)
        self.assertEqual(proc.wait(10), 0)
        with proc.stderr:
            return [line for line in proc.stderr.read().splitlines() if line.strip()]

    def test_sigterm(self):
        lines = self.run_server(signal.SIGTERM)
        self.assertTrue(lines[-1].endswith("adapter-serve: stopped (SIGTERM), 0 PCs were connected"), lines)

    def test_ctrl_c(self):
        lines = self.run_server(signal.SIGINT)
        self.assertTrue(lines[-1].endswith("adapter-serve: stopped (Ctrl-C), 0 PCs were connected"), lines)

    def test_words(self):
        self.assertEqual(serve.stop_line("SIGTERM", 1), "stopped (SIGTERM), 1 PC was connected")
        self.assertEqual(serve.stop_line("Ctrl-C", 3), "stopped (Ctrl-C), 3 PCs were connected")


class Operations(ServerBase):
    def test_sdo(self):
        self.device(5, heartbeat_s=0.05)
        c = self.client()
        res = c.sdo_read(5, 0x1018, 1)
        self.assertTrue(res["success"])
        self.assertEqual(diag.parse_hex(res["data"]), (0x360).to_bytes(4, "little"))
        self.assertIsNotNone(c.rtt_ms)  # the scan is in test_cli_scan

    def test_changes_need_both_switches(self):
        d = self.device(5, od={(0x2000, 0): b"\0\0"})
        c = self.client()
        with self.assertRaises(diag.DiagError) as e:
            c.sdo_write(5, 0x2000, 0, b"\x01\x00")
        self.assertIn("changes not allowed", str(e.exception))
        c.allow_changes = True  # the PC's switch, on the open connection
        self.assertTrue(c.info["allow_changes"])
        self.assertTrue(c.sdo_write(5, 0x2000, 0, b"\x01\x00")["success"])
        self.assertEqual(d.od[(0x2000, 0)], b"\x01\x00")

    def test_session_names_configured_nodes(self):
        self.device(5, heartbeat_s=0.05)
        c = self.client(config={5: {"name": "valve", "expect": {}}})
        self.assertTrue(self.wait(lambda: any(n.get("name") == "valve" for n in c.status()["nodes"])))

    def test_lss_and_pdo_test_methods(self):
        self.device(None)
        c = self.client(allow_changes=True)
        res = c.lss_find(True)
        while res.get("running"):
            time.sleep(0.05)
            res = c.lss_find(False)
        self.assertTrue(res.get("found"), res)
        self.assertIn("stopped", c.pdo_test_stop())

    def test_cyclic_job_stops_when_the_connection_ends(self):
        self.device(5, heartbeat_s=0.05)
        c = self.client(allow_changes=True)
        watch = self.watch()
        res = c.send_frame(0x321, b"\x01", period_ms=10)
        self.assertIsNotNone(res.get("job"))
        self.assertIsNotNone(watch.recv(1.0))
        c.sock.shutdown(socket.SHUT_RDWR)  # the connection is lost, as if the network went away
        c.close()

        def silent():
            while watch.recv(0) is not None:
                pass
            time.sleep(0.1)
            got = watch.recv(0)
            while got is not None and got.arbitration_id != 0x321:
                got = watch.recv(0)
            return got is None
        self.assertTrue(self.wait(silent))

    def test_adapter_closed_after_the_last_connection(self):
        self.device(5, heartbeat_s=0.05)
        a, b = self.client(), self.client()
        self.assertIn("virtual:" + self.ch, core_mod._cores)
        a.close()
        self.assertTrue(b.status()["local"])
        b.close()
        self.assertTrue(self.wait(lambda: "virtual:" + self.ch not in core_mod._cores))
        self.assertTrue(self.wait(lambda: not self.srv.status()["pcs"]))
        # The machine itself can open the adapter again.
        local = LocalBus(parse("virtual:" + self.ch), 250000, listen_s=0.05)
        local.connect()
        local.close()

    def test_cli_scan(self):
        self.device(5, heartbeat_s=0.05)
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "t")
            with open(path, "w") as f:
                f.write(TOKEN + "\n")
            code, out, err = cli("--adapter", "remote:127.0.0.1:%d" % self.srv.port, "--token-file", path, "scan")
        self.assertEqual(code, 0, err)
        self.assertIn("node   5", out)
        code, out, err = cli("--adapter", "remote:127.0.0.1:%d" % self.srv.port, "--token", TOKEN, "status")
        self.assertEqual(code, 0, err)
        self.assertIn("adapter virtual:%s, 250 kbit/s, read-only" % self.ch, out)


    def test_cli_trace_drops_are_the_adapter_machines(self):
        self.device(5, heartbeat_s=0.05)
        path = os.path.join(tempfile.mkdtemp(), "run.trc")
        self.addCleanup(shutil.rmtree, os.path.dirname(path), True)
        code, out, err = cli("--adapter", "remote:127.0.0.1:%d" % self.srv.port, "--token", TOKEN, "trace", "-o", path,
                             "--duration", "0.4")
        self.assertEqual(code, 0, err)
        self.assertIn("0 dropped by the adapter machine's kernel (127.0.0.1)", out)
        self.assertNotIn("PLC", out)

    def test_drops_words(self):
        self.assertEqual(diag.drops_by("remote:linuxbox"), "the adapter machine's kernel (linuxbox)")
        self.assertEqual(diag.drops_by("remote:[fd00::1]:7600"), "the adapter machine's kernel (fd00::1)")
        self.assertEqual(diag.drops_by("slcan:COM5"), "this PC's kernel")
        self.assertEqual(diag.drops_by(None), "the PLC's kernel")


class ReadOnlyServer(ServerBase):
    allow_changes = False

    def test_changes_refused_naming_the_option(self):
        d = self.device(5, od={(0x2000, 0): b"\0\0"})
        c = self.client(allow_changes=True)
        watch = self.watch()  # after the bit rate check's probe
        self.assertFalse(c.info["allow_changes"])
        for call in (lambda: c.sdo_write(5, 0x2000, 0, b"\x01\x00"), lambda: c.nmt(5, "stop"),
                     lambda: c.send_frame(0x321, b"\x01"), lambda: c.sync_start(100)):
            with self.assertRaises(diag.DiagError) as e:
                call()
            self.assertEqual(str(e.exception), "the adapter server on benchbox was started without --allow-changes")
        self.assertEqual(d.od[(0x2000, 0)], b"\0\0")
        self.assertIsNone(watch.recv(0.1))
        self.assertTrue(c.sdo_read(5, 0x1018, 1)["success"])  # reads still work


class Limits(ServerBase):
    def raw(self):
        return socket.create_connection(("127.0.0.1", self.srv.port), timeout=3)

    def test_pending_connections_per_address(self):
        a, b = self.raw(), self.raw()
        self.assertTrue(self.wait(lambda: self.srv.pending.get("127.0.0.1") == 2))
        c = self.raw()
        self.assertEqual(closed(c), b"")  # the third one waiting to log in is closed
        for s in (a, b, c):
            s.close()

    def test_login_time(self):
        with mock.patch.object(serve, "LOGIN_S", 0.3):
            s = self.raw()
            t0 = time.monotonic()
            self.assertEqual(closed(s), b"")
            self.assertLess(time.monotonic() - t0, 2.5)
            s.close()

    def test_idle_connection_closed(self):
        self.device(5, heartbeat_s=0.05)
        with mock.patch.object(serve, "IDLE_S", 0.3):
            c = self.client()
            time.sleep(0.6)
            with self.assertRaises(diag.DiagError) as e:
                c.status()
            self.assertEqual(e.exception.kind, "eof")

    def test_pcs_limit(self):
        self.device(5, heartbeat_s=0.05)
        with mock.patch.object(serve, "MAX_PER_PC", 1):
            self.client()
            with self.assertRaises(diag.DiagError) as e:
                self.client()
            self.assertIn("connections to the adapter server on benchbox already", str(e.exception))
        # A PC that is connected already is served; a new one is not when MAX_PCS are.
        for c in self.clients:
            c.close()
        self.assertTrue(self.wait(lambda: not self.srv.status()["pcs"]))
        with mock.patch.object(serve, "MAX_PCS", 0):
            with self.assertRaises(diag.DiagError) as e:
                self.client()
            self.assertIn("serves 0 PCs already", str(e.exception))


class Token(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir)

    def test_first_start_prints_once(self):
        out = io.StringIO()
        v = serve.prepare_token(7536, folder=self.dir, out=out)
        token = out.getvalue().split("token: ", 1)[1].split(" ", 1)[0]
        self.assertIn("shown once", out.getvalue())
        self.assertTrue(diag.token_matches(token, v))
        path = serve.settings_path(self.dir)
        with open(path) as f:
            text = f.read()
        self.assertNotIn(token, text)
        if os.name == "posix":
            self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)
        again = io.StringIO()
        self.assertEqual(serve.prepare_token(7536, folder=self.dir, out=again), v)
        self.assertEqual(again.getvalue(), "")
        # Another port has a token of its own; --new-token replaces this one.
        new = io.StringIO()
        self.assertNotEqual(serve.prepare_token(7536, new=True, folder=self.dir, out=new), v)
        self.assertIn("token: ", new.getvalue())

    def test_token_file(self):
        path = os.path.join(self.dir, "t")
        with open(path, "w") as f:
            f.write("given-token\n")
        out = io.StringIO()
        v = serve.prepare_token(7540, token_file=path, folder=self.dir, out=out)
        self.assertEqual(out.getvalue(), "")
        self.assertTrue(diag.token_matches("given-token", v))
        self.assertEqual(serve.load_verifier(7540, self.dir), v)


@unittest.skipUnless(os.name == "posix", "the service is for Linux")
class Service(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir)
        self.units, self.avahi, self.home = (os.path.join(self.dir, d) for d in ("units", "avahi", "home"))
        os.makedirs(self.units)
        self.bin = os.path.join(self.dir, "bin")
        os.makedirs(self.bin)
        self.calls = os.path.join(self.dir, "calls")
        fake = os.path.join(self.bin, "systemctl")
        with open(fake, "w") as f:
            f.write("#!/bin/sh\necho \"$@\" >> %s\n[ \"$1\" = is-active ] && echo active\nexit 0\n" % self.calls)
        os.chmod(fake, 0o755)
        self.user = "benchuser"
        for p in (mock.patch.dict(os.environ, {"PATH": self.bin + os.pathsep + os.environ.get("PATH", ""),
                                               "SUDO_USER": self.user}),
                  mock.patch.object(serve.os, "geteuid", lambda: 0),
                  mock.patch.object(serve, "_user_config_dir", lambda user: self.home),
                  mock.patch.object(serve, "_owner", lambda user: (os.getuid(), os.getgid()))):
            p.start()
            self.addCleanup(p.stop)

    def args(self, *argv):
        return diag.parser().parse_args(["adapter-serve"] + list(argv))

    def systemctl(self):
        with open(self.calls) as f:
            return f.read().splitlines()

    def test_install_and_remove(self):
        os.makedirs(self.avahi)
        out = io.StringIO()
        args = self.args("--adapter", "socketcan:can0", "--bitrate", "500", "--allow-changes", "--install-service")
        serve.install_service(args, out, self.units, self.avahi)
        self.assertIn("token: ", out.getvalue())
        self.assertIsNotNone(serve.load_verifier(7536, self.home))
        unit = os.path.join(self.units, "canworks-adapter-can0.service")
        with open(unit) as f:
            text = f.read()
        for line in ("User=%s" % self.user, "AmbientCapabilities=CAP_NET_ADMIN", "Restart=on-failure",
                     "WantedBy=multi-user.target"):
            self.assertIn(line, text)
        self.assertIn("adapter-serve --adapter socketcan:can0 --bitrate 500 --port 7536 --allow-changes", text)
        self.assertNotIn("token", text.lower())
        with open(os.path.join(self.avahi, "canworks-adapter-can0.service")) as f:
            adv = f.read()
        for t in ("kind=adapter", "adapter=socketcan:can0", "bitrate=500", "v=1"):
            self.assertIn("<txt-record>%s</txt-record>" % t, adv)
        self.assertEqual(self.systemctl(), ["daemon-reload", "enable canworks-adapter-can0.service",
                                            "restart canworks-adapter-can0.service"])
        # --status names the service.
        st = io.StringIO()
        serve.show_status(self.args("--status"), st, self.units)
        self.assertIn("service canworks-adapter-can0.service: active", st.getvalue())
        # Removing leaves nothing behind.
        serve.remove_service(self.args("--remove-service"), io.StringIO(), self.units, self.avahi)
        self.assertEqual(os.listdir(self.units), [])
        self.assertEqual(os.listdir(self.avahi), [])
        self.assertIn("disable --now canworks-adapter-can0.service", self.systemctl())

    def test_without_avahi_and_without_sudo(self):
        out = io.StringIO()
        serve.install_service(self.args("--adapter", "slcan:/dev/ttyACM0", "--bitrate", "250", "--install-service"),
                              out, self.units, self.avahi)
        self.assertIn("Avahi is not installed", out.getvalue())
        self.assertEqual(os.listdir(self.units), ["canworks-adapter-dev-ttyACM0.service"])
        with mock.patch.dict(os.environ, {"SUDO_USER": ""}):
            with self.assertRaises(serve.ServeError) as e:
                serve.install_service(self.args("--adapter", "socketcan:can0", "--bitrate", "250"), out,
                                      self.units, self.avahi)
        self.assertIn("with sudo", str(e.exception))

    def test_root_install_for_a_user_with_a_verifier(self):
        # The Devices job: root, no SUDO_USER, the verifier made on the PC.
        verifier = diag.token_verifier("pc-made-token")
        vfile = os.path.join(self.dir, "verifier")
        with open(vfile, "w") as f:
            f.write(verifier + "\n")
        out = io.StringIO()
        with mock.patch.dict(os.environ, {"SUDO_USER": ""}):
            serve.install_service(self.args("--adapter", "socketcan:can0", "--bitrate", "500", "--install-service",
                                            "--service-user", "devuser", "--token-verifier-file", vfile),
                                  out, self.units, self.avahi)
        self.assertNotIn("token: ", out.getvalue())
        self.assertEqual(serve.load_verifier(7536, self.home), verifier)
        with open(os.path.join(self.units, "canworks-adapter-can0.service")) as f:
            text = f.read()
        self.assertIn("User=devuser", text)
        self.assertNotIn("verifier", text)
        # A reinstall without a token option keeps the verifier.
        serve.install_service(self.args("--adapter", "socketcan:can0", "--bitrate", "250", "--install-service",
                                        "--service-user", "devuser"), io.StringIO(), self.units, self.avahi)
        self.assertEqual(serve.load_verifier(7536, self.home), verifier)

    def test_reinstall_without_discovery(self):
        os.makedirs(self.avahi)
        base = ("--adapter", "socketcan:can0", "--bitrate", "500", "--install-service")
        serve.install_service(self.args(*base, "--allow-changes"), io.StringIO(), self.units, self.avahi)
        verifier = serve.load_verifier(7536, self.home)
        self.assertEqual(os.listdir(self.avahi), ["canworks-adapter-can0.service"])
        out = io.StringIO()
        serve.install_service(self.args(*base, "--without-discovery"), out, self.units, self.avahi)
        self.assertEqual(os.listdir(self.avahi), [])
        self.assertIn("not advertised", out.getvalue())
        self.assertEqual(serve.load_verifier(7536, self.home), verifier)
        with open(os.path.join(self.units, "canworks-adapter-can0.service")) as f:
            self.assertNotIn("--allow-changes", f.read())
        self.assertEqual(self.systemctl()[-1], "restart canworks-adapter-can0.service")

    def test_root_service_user_refused(self):
        with self.assertRaises(serve.ServeError) as e:
            serve.install_service(self.args("--adapter", "socketcan:can0", "--bitrate", "500", "--install-service",
                                            "--service-user", "root"), io.StringIO(), self.units, self.avahi)
        self.assertIn("not root", str(e.exception))

    def test_bad_verifier_file(self):
        vfile = os.path.join(self.dir, "verifier")
        with open(vfile, "w") as f:
            f.write("plain-token\n")
        with self.assertRaises(serve.ServeError) as e:
            serve.install_service(self.args("--adapter", "socketcan:can0", "--bitrate", "500", "--install-service",
                                            "--token-verifier-file", vfile), io.StringIO(), self.units, self.avahi)
        self.assertIn("does not hold a token verifier", str(e.exception))
        self.assertEqual(os.listdir(self.units), [])


class Discovery(unittest.TestCase):
    def test_adapter_answer(self):
        r = discovery._entry("benchbox adapter socketcan:can0", ["192.0.2.7"], 7536,
                             {"v": "1", "kind": "adapter", "name": "benchbox", "adapter": "socketcan:can0",
                              "bitrate": "500"})
        self.assertEqual((r["kind"], r["machine"], r["adapter"], r["bitrate"], r["diag"]),
                         ("adapter", "benchbox", "socketcan:can0", 500, 7536))
        self.assertEqual(discovery._entry("plc", ["192.0.2.8"], 7531, {"diag": "7531"})["kind"], "runtime")

    def test_discover_lists_adapter_servers_apart(self):
        found = [discovery._entry("plc", ["192.0.2.8"], 7531, {"diag": "7531", "runtime": "8443"}),
                 discovery._entry("benchbox adapter socketcan:can0", ["192.0.2.7"], 7536,
                                  {"kind": "adapter", "name": "benchbox", "adapter": "socketcan:can0", "bitrate": "500"})]
        with mock.patch.object(discovery, "available", lambda: True), \
                mock.patch.object(discovery, "browse", lambda wait: found):
            code, out, err = cli("discover")
        self.assertEqual(code, 0, err)
        head, servers = out.split("adapter servers")
        self.assertIn("plc", head)
        self.assertNotIn("benchbox", head)
        self.assertIn("benchbox", servers)
        self.assertIn("socketcan:can0 at 500 kbit/s", servers)


class RemoteTarget(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(remote.parse("remote:benchbox"), ("benchbox", 7536))
        self.assertEqual(remote.parse("remote:benchbox:7600"), ("benchbox", 7600))
        self.assertEqual(remote.parse("[fe80::1]:7536"), ("fe80::1", 7536))
        self.assertEqual(remote.host_key("benchbox", 7536), "benchbox")
        self.assertEqual(remote.host_key("benchbox", 7600), "benchbox:7600")
        for bad in ("remote:", "remote:x:y"):
            with self.assertRaises(ValueError):
                remote.parse(bad)

    def test_cli_needs_no_bitrate(self):
        code, out, err = cli("--adapter", "remote:127.0.0.1:1", "--token", "x", "--bitrate", "250", "status")
        self.assertEqual(code, 2)
        self.assertIn("adapter server sets the bit rate", err)

    def test_dm_refused(self):
        code, out, err = cli("--adapter", "remote:127.0.0.1:1", "--token", "x", "dm", "list")
        self.assertEqual(code, 2)
        self.assertIn("not available through an adapter server", err)


if __name__ == "__main__":
    unittest.main()
