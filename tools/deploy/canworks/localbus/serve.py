"""canworks-diag adapter-serve: the CAN adapter of this machine served to PCs
on the network (canopen-remote-adapter).

  canworks-diag adapter-serve --adapter socketcan:can0 --bitrate 500 [--allow-changes]

The server speaks the bridge's diagnostics protocol: TLS with a certificate
made at start (by the openssl command) and the SCRAM-SHA-256 login bound to
it, then one JSON line per request. After the login every request goes to a
LocalBus handle of its own on the one open adapter (core.acquire shares it),
so the PC sees the operations, results and refusals of a local adapter.
The adapter opens, with the bit rate check, at the first login and closes
when the last connection ends; a connection's cyclic jobs, trace and PDO
test end with it (LocalBus.close).

Only the token's verifier is kept on this machine (adapter-serve.json in the
settings folder, mode 0600). Changes need --allow-changes here and the
PC's own allow-changes for its session (the "session" request).

--install-service writes a systemd unit (and an Avahi service file, TXT
kind=adapter) that runs the same command as the user who ran sudo.
"""

import base64
import glob
import hashlib
import hmac
import json
import os
import re
import secrets
import shlex
import shutil
import socket
import socketserver
import ssl
import subprocess
import sys
import tempfile
import threading
import time

from .. import diag
from ..diag import DiagError
from ..userdirs import config_dir, replace_file
from . import adapter as adapter_mod
from . import client as client_mod

DEFAULT_PORT = 7536  # 7531 is the runtime's diagnostics, 7532 the simulator's, 7533 the CiA 309-3 gateway's
SETTINGS = "adapter-serve.json"
MAX_PCS = 4  # addresses logged in at a time
MAX_PER_PC = 8  # connections of one logged-in address (the configurator opens a few: pages, Send panel, trace)
MAX_PENDING = 8  # connections not logged in yet
PENDING_PER_ADDRESS = 2
LOGIN_S = 30.0
IDLE_S = 600.0
LOGIN_BACKOFF_S = 1.0  # after a failed login, the next one from that address waits this long
FAILED_PER_MINUTE = 10  # failed logins in total; beyond it logins are refused until the minute is over
NO_CHANGES = "the adapter server on %s was started without --allow-changes"
UNIT_DIR = "/etc/systemd/system"
AVAHI_DIR = "/etc/avahi/services"
ANSWER_KINDS = ("bitrate", "busy", "eof")  # error kinds the PC gets as such (the rest are refusals)


class ServeError(Exception):
    pass


def _log(text):
    sys.stderr.write("%s adapter-serve: %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), text))
    sys.stderr.flush()


def _peer(address):
    host = address[0] if isinstance(address, tuple) else str(address)
    return host[7:] if host.startswith("::ffff:") else host


# ---------------------------------------------------------------------------
# The token: only its verifier is kept, per port


def settings_path(folder=None):
    return os.path.join(folder or config_dir(), SETTINGS)


def load_verifier(port, folder=None):
    try:
        with open(settings_path(folder), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    v = ((data.get("ports") or {}).get(str(port)) or {}).get("token_verifier") if isinstance(data, dict) else None
    return v if diag.parse_verifier(v) else None


def store_verifier(port, verifier, folder=None, owner=None):
    """Writes the verifier for `port`, readable by the user only; `owner`
    (uid, gid) gives the file (and a folder made for it) to that user, for
    --install-service run with sudo."""
    path = settings_path(folder)
    parent = os.path.dirname(path)
    if not os.path.isdir(parent):
        os.makedirs(parent, mode=0o700)
        if owner:
            os.chown(parent, *owner)
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        data = data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        data = {}
    data.setdefault("ports", {})[str(port)] = {"token_verifier": verifier}
    tmp = "%s.%d.tmp" % (path, os.getpid())
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    if owner:
        os.chown(tmp, *owner)
    replace_file(tmp, path)


def read_token_file(path):
    try:
        with open(path, encoding="utf-8") as f:
            token = f.read().strip()
    except OSError as e:
        raise ServeError("cannot read the token file %s: %s" % (path, e.strerror or e))
    if not token:
        raise ServeError("the token file %s is empty" % path)
    return token


def prepare_token(port, new=False, token_file=None, folder=None, owner=None, out=sys.stdout):
    """The verifier the server checks logins against: the stored one, or a
    new one from --token-file or a new token, printed once. The plain token
    is never written here."""
    if token_file:
        verifier = diag.token_verifier(read_token_file(token_file))
        store_verifier(port, verifier, folder, owner)
        return verifier
    verifier = None if new else load_verifier(port, folder)
    if verifier:
        return verifier
    token = diag.new_token()
    verifier = diag.token_verifier(token)
    store_verifier(port, verifier, folder, owner)
    out.write("token: %s (shown once; --new-token makes another)\n" % token)
    out.flush()
    return verifier


# ---------------------------------------------------------------------------
# TLS: a fresh self-signed P-256 certificate per start


def make_context(openssl="openssl"):
    """(server SSLContext, SHA-256 of the certificate) for a certificate made
    now. The key exists on disk only in a 0700 temporary folder, removed
    right after loading."""
    tmp = tempfile.mkdtemp(prefix="canworks-adapter-")
    try:
        key, cert = os.path.join(tmp, "key.pem"), os.path.join(tmp, "cert.pem")
        try:
            r = subprocess.run([openssl, "req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:prime256v1",
                                "-nodes", "-keyout", key, "-out", cert, "-days", "3650", "-subj",
                                "/CN=canworks adapter server"], capture_output=True, text=True, timeout=30)
        except FileNotFoundError:
            raise ServeError("the openssl command is missing: install the openssl package "
                             "(sudo apt install openssl, or your distribution's)")
        except (OSError, subprocess.SubprocessError) as e:
            raise ServeError("openssl could not make the certificate: %s" % e)
        if r.returncode != 0:
            raise ServeError("openssl could not make the certificate: %s" % (r.stderr.strip() or r.returncode))
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        ctx.load_cert_chain(cert, key)
        with open(cert, encoding="ascii") as f:
            cert_hash = hashlib.sha256(ssl.PEM_cert_to_DER_cert(f.read())).digest()
        return ctx, cert_hash
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# The server


class _Login:
    """The server's half of the SCRAM-SHA-256 login (diag.scram_client is the
    client's, plugin/src/can/secure_channel.h the bridge's)."""

    def __init__(self, verifier, cert_hash):
        self.iterations, self.salt, self.stored, self.server_key = diag.parse_verifier(verifier)
        self.cert_hash = cert_hash
        self.cnonce = self.snonce = None

    def hello(self, req):
        """The hello's answer, or None (close without one)."""
        if req.get("op") != "hello" or req.get("mech") != diag.SCRAM_MECH or not isinstance(req.get("nonce"), str) \
                or not 16 <= len(req["nonce"]) <= 256:
            return None
        self.cnonce, self.snonce = req["nonce"], diag._b64(secrets.token_bytes(18))
        return {"protocol": diag.PROTOCOL, "nonce": self.snonce, "salt": diag._b64(self.salt),
                "iterations": self.iterations}

    def check(self, req):
        """The server signature (base64) when the proof is right, else None."""
        if req.get("op") != "login" or self.snonce is None:
            return None
        try:
            proof = base64.b64decode(req.get("proof") or "", validate=True)
        except (ValueError, TypeError):
            return None
        auth = diag.scram_auth_message(self.cnonce, self.snonce, diag._b64(self.salt), self.iterations,
                                       self.cert_hash).encode("utf-8")
        sig = hmac.new(self.stored, auth, hashlib.sha256).digest()
        client_key = bytes(a ^ b for a, b in zip(proof, sig))
        if len(proof) != 32 or not hmac.compare_digest(hashlib.sha256(client_key).digest(), self.stored):
            return None
        return diag._b64(hmac.new(self.server_key, auth, hashlib.sha256).digest())


class AdapterServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    """Serves `spec` at `bitrate` (bit/s) to PCs that log in with the token
    of `verifier`. `context` and `cert_hash` default to a certificate made
    now (make_context). `listen_s` is the bit rate check's listening time
    (tests shorten it)."""

    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 16

    def __init__(self, spec, bitrate, verifier, bind="", port=DEFAULT_PORT, allow_changes=False, check_node=None,
                 listen_s=None, name=None, context=None, cert_hash=None, log=_log, status_path=None):
        if diag.parse_verifier(verifier) is None:
            raise ServeError("no valid token verifier")
        self.spec, self.bitrate, self.verifier = spec, bitrate, verifier
        self.allow_changes, self.check_node, self.listen_s = bool(allow_changes), check_node, listen_s
        self.name = name or socket.gethostname()
        self.log = log
        self.status_path = status_path
        if context is None:
            context, cert_hash = make_context()
        self.context, self.cert_hash = context, cert_hash
        self.lock = threading.Lock()
        self.pending = {}   # address -> connections not logged in
        self.pcs = {}       # address -> {"connections", "since"}
        self.failed_at = {}  # address -> time of its last failed login
        self.failures = []  # times of the failed logins of the last minute
        self.refused_logged = 0.0
        family = socket.AF_INET
        if not bind:
            if socket.has_dualstack_ipv6():
                family, bind = socket.AF_INET6, "::"
            else:
                bind = "0.0.0.0"
        elif ":" in bind:
            family = socket.AF_INET6
        self.address_family = family
        super().__init__((bind, port), _Handler, bind_and_activate=False)
        try:
            if family == socket.AF_INET6 and bind == "::":
                self.socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
            self.server_bind()
            self.server_activate()
        except OSError as e:
            self.server_close()
            raise ServeError("cannot listen on port %d%s: %s" % (port, " of %s" % bind if bind not in ("::", "0.0.0.0")
                                                                 else "", e.strerror or e))

    @property
    def port(self):
        return self.server_address[1]

    # -- admission ----------------------------------------------------------------
    def verify_request(self, request, client_address):
        peer = _peer(client_address)
        with self.lock:
            if sum(self.pending.values()) >= MAX_PENDING or self.pending.get(peer, 0) >= PENDING_PER_ADDRESS:
                return False
            self.pending[peer] = self.pending.get(peer, 0) + 1
        return True

    def done_pending(self, peer):
        with self.lock:
            n = self.pending.get(peer, 0) - 1
            if n > 0:
                self.pending[peer] = n
            else:
                self.pending.pop(peer, None)

    def wait_backoff(self, peer):
        """Waits out the delay after this address's last failed login. False
        when too many logins failed in the last minute (refused, not tried)."""
        with self.lock:
            left = self.failed_at.get(peer, 0) + LOGIN_BACKOFF_S - time.monotonic()
        if left > 0:
            time.sleep(left)
        now = time.monotonic()
        with self.lock:
            self.failures = [t for t in self.failures if now - t < 60]
            if len(self.failures) < FAILED_PER_MINUTE:
                return True
            if now - self.refused_logged >= 60:
                self.refused_logged = now
                self.log("%d failed logins in the last minute: logins refused for a while" % len(self.failures))
            return False

    def failed(self, peer):
        now = time.monotonic()
        with self.lock:
            self.failed_at[peer] = now
            self.failures.append(now)
            for p in [p for p, t in self.failed_at.items() if now - t > 60]:
                del self.failed_at[p]
        self.log("login from %s refused: wrong token" % peer)

    def logged_in(self, peer):
        """Counts a logged-in connection of `peer`; an error text when the
        server serves MAX_PCS other PCs already, or this one has too many."""
        with self.lock:
            pc = self.pcs.get(peer)
            if pc is None and len(self.pcs) >= MAX_PCS:
                return "the adapter server on %s serves %d PCs already" % (self.name, MAX_PCS)
            if pc is not None and pc["connections"] >= MAX_PER_PC:
                return "this PC has %d connections to the adapter server on %s already" % (MAX_PER_PC, self.name)
            if pc is None:
                pc = self.pcs[peer] = {"connections": 0, "since": time.time()}
                self.log("%s connected" % peer)
            pc["connections"] += 1
        self.write_status()
        return None

    def logged_out(self, peer):
        with self.lock:
            pc = self.pcs.get(peer)
            if pc is None:
                return
            pc["connections"] -= 1
            if pc["connections"] <= 0:
                del self.pcs[peer]
                self.log("%s disconnected" % peer)
        self.write_status()

    # -- what --status reads ------------------------------------------------------
    def status(self):
        with self.lock:
            pcs = [{"address": p, "connections": v["connections"],
                    "since": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(v["since"]))}
                   for p, v in sorted(self.pcs.items())]
        return {"pid": os.getpid(), "adapter": str(self.spec), "bitrate_kbit": self.bitrate // 1000,
                "port": self.port, "allow_changes": self.allow_changes, "pcs": pcs}

    def write_status(self):
        if not self.status_path:
            return
        try:
            tmp = "%s.%d.tmp" % (self.status_path, os.getpid())
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.status(), f, indent=2)
            replace_file(tmp, self.status_path, deadline_s=1.0)
        except OSError:
            pass

    def server_close(self):
        super().server_close()
        if self.status_path:
            try:
                os.remove(self.status_path)
            except OSError:
                pass


class _Handler(socketserver.BaseRequestHandler):
    def setup(self):
        self.peer = _peer(self.client_address)
        self.bus = None
        self.authed = False
        self.counted = False  # counted among the logged-in connections
        self.buf = b""

    def finish(self):
        if self.bus is not None:
            self.bus.close()  # its cyclic jobs, trace and PDO test end; the last one closes the adapter
            self.bus = None
        if self.counted:
            self.server.logged_out(self.peer)
        elif not self.authed:
            self.server.done_pending(self.peer)
        try:
            self.request.close()
        except OSError:
            pass

    # -- lines --------------------------------------------------------------------
    def _line(self):
        """The next request as a dict, or None (closed, timed out, or not JSON)."""
        while b"\n" not in self.buf:
            try:
                chunk = self.request.recv(65536)
            except (socket.timeout, OSError):
                return None
            if not chunk:
                return None
            self.buf += chunk
            if len(self.buf) > diag.MAX_LINE:
                self._send({"ok": False, "id": None, "error": "request line too long"})
                return None
        line, _, self.buf = self.buf.partition(b"\n")
        try:
            req = json.loads(line.decode("utf-8"))
        except ValueError:
            self._send({"ok": False, "id": None, "error": "not JSON"})
            return None
        return req if isinstance(req, dict) else None

    def _send(self, msg):
        try:
            self.request.sendall(json.dumps(msg).encode("utf-8") + b"\n")
            return True
        except OSError:
            return False

    def _answer(self, req, result=None, error=None, kind=None):
        msg = {"id": req.get("id"), "ok": error is None}
        if error is None:
            msg["result"] = result or {}
        else:
            msg["error"] = error
            if kind in ANSWER_KINDS:
                msg["kind"] = kind
        return self._send(msg)

    # -- the connection -----------------------------------------------------------
    def handle(self):
        srv = self.server
        deadline = time.monotonic() + LOGIN_S
        self.request.settimeout(LOGIN_S)
        try:
            self.request = srv.context.wrap_socket(self.request, server_side=True)
        except (ssl.SSLError, OSError):
            return  # not TLS (or not finished in time): closed, nothing reached the bus
        login = _Login(srv.verifier, srv.cert_hash)
        req = self._line()
        first = login.hello(req) if req else None
        if first is None or not self._answer(req, first):
            return
        self.request.settimeout(max(0.1, deadline - time.monotonic()))
        req = self._line()
        if req is None or not srv.wait_backoff(self.peer):
            return
        sig = login.check(req)
        if sig is None:
            srv.failed(self.peer)
            return  # as the bridge: closed without an answer
        refused = srv.logged_in(self.peer)
        srv.done_pending(self.peer)
        self.authed, self.counted = True, not refused
        if refused:
            self._answer(req, error=refused)
            return
        try:
            self.bus = self._open()
        except DiagError as e:
            srv.log("%s: %s" % (self.peer, e))
            self._answer(req, error=str(e), kind=e.kind)
            return
        if not self._answer(req, dict(self._hello(), signature=sig)):
            return
        self.request.settimeout(IDLE_S)
        while True:
            req = self._line()
            if req is None:
                return  # closed, or idle for IDLE_S
            if not self._request(req):
                return

    def _open(self):
        srv = self.server
        bus = client_mod.LocalBus(srv.spec, srv.bitrate, allow_changes=False, listen_s=srv.listen_s,
                                  check_node=srv.check_node)
        bus.connect()
        if bus.core.bitrate != srv.bitrate:
            # A SocketCAN interface that is up already keeps its own rate: never another one than --bitrate.
            kbit, want = bus.core.bitrate // 1000, srv.bitrate // 1000
            bus.close()
            raise DiagError("bitrate", "CAN interface %s is up at %d kbit/s, not at %d kbit/s as the adapter server "
                                       "on %s was started" % (srv.spec.channel, kbit, want, srv.name))
        return bus

    def _hello(self):
        info = self.bus.request("hello")
        info.update(remote=self.server.name, server_allow_changes=self.server.allow_changes)
        return info

    def _request(self, req):
        """One request after the login. False: close the connection."""
        srv = self.server
        op = req.get("op")
        fields = {k: v for k, v in req.items() if k not in ("op", "id", "network", "timeout")}
        if not isinstance(op, str):
            return self._answer(req, error="field 'op' missing")
        if op in ("hello", "login"):
            return self._answer(req, self._hello())
        if op == "session":
            try:
                self._session(fields)
            except DiagError as e:
                return self._answer(req, error=str(e))
            return self._answer(req, self._hello())
        if op in client_mod.CHANGES and not srv.allow_changes:
            return self._answer(req, error=NO_CHANGES % srv.name)
        try:
            result = self.bus.request(op, **fields)
        except DiagError as e:
            ok = self._answer(req, error=str(e), kind=e.kind)
            return ok and e.kind != "eof"  # the adapter is gone: the PC sees the connection end
        except Exception as e:  # pragma: no cover - a bug must not end the server
            srv.log("%s: %s failed: %r" % (self.peer, op, e))
            return self._answer(req, error="the adapter server could not do %s: %s" % (op, e))
        if op == "status":
            result = dict(result, remote=srv.name, server_allow_changes=srv.allow_changes)
        return self._answer(req, result)

    def _session(self, f):
        """The PC's session settings: its allow-changes switch, --force, the
        configured nodes ({node_id: {name, expect}}) and the network's name."""
        bus = self.bus
        for key in ("allow_changes", "force"):
            if key in f and not isinstance(f[key], bool):
                raise DiagError("refused", "field '%s' must be true or false" % key)
        if "allow_changes" in f:
            bus.allow_changes = f["allow_changes"] and self.server.allow_changes
        if "force" in f:
            bus.force = f["force"]
        if "nodes" in f:
            nodes = f["nodes"] if isinstance(f["nodes"], dict) else {}
            try:
                bus.config = {int(k): v for k, v in nodes.items() if isinstance(v, dict) and 1 <= int(k) <= 127}
            except (TypeError, ValueError):
                raise DiagError("refused", "field 'nodes' must map node IDs to nodes")
        if isinstance(f.get("network_name"), str):
            bus.network = f["network_name"] or None


# ---------------------------------------------------------------------------
# The command


def status_path(port, folder=None):
    return os.path.join(folder or config_dir(), "adapter-serve-%d.status.json" % port)


def serve(args, out=sys.stdout):
    """canworks-diag adapter-serve (runs until Ctrl-C or SIGTERM)."""
    if args.install_service or args.remove_service or args.status:
        return service_command(args, out)
    spec, bitrate = _spec_and_bitrate(args)
    try:
        verifier = prepare_token(args.port, args.new_token, getattr(args, "serve_token_file", None), out=out)
        srv = AdapterServer(spec, bitrate, verifier, args.bind or "", args.port, args.allow_changes, args.check_node,
                            status_path=status_path(args.port))
    except (ServeError, OSError) as e:
        raise DiagError("usage", str(e))
    srv.write_status()
    import signal
    how = ["Ctrl-C"]

    def stop(*_):
        how[0] = "SIGTERM"
        raise KeyboardInterrupt
    try:
        signal.signal(signal.SIGTERM, stop)
    except ValueError:  # pragma: no cover - not the main thread
        pass
    stopped, pcs = False, 0
    try:
        # Logged inside the try: a Ctrl-C right after the line still stops cleanly.
        _log("serving adapter %s at %d kbit/s on port %d%s, %s" % (
            spec, bitrate // 1000, srv.port, " of %s" % args.bind if args.bind else "",
            "changes allowed (each PC still allows changes for its session)" if args.allow_changes else "read-only"))
        srv.serve_forever()
    except KeyboardInterrupt:
        stopped = True
    finally:
        with srv.lock:
            pcs = len(srv.pcs)
        srv.server_close()
    if stopped:  # the service's journal shows the stop (systemctl stop sends SIGTERM)
        _log(stop_line(how[0], pcs))
    return 0


def stop_line(how, pcs):
    """The log line of a stopped server: how (SIGTERM, Ctrl-C) and how many PCs were connected."""
    return "stopped (%s), %d %s connected" % (how, pcs, "PC was" if pcs == 1 else "PCs were")


def _spec_and_bitrate(args):
    if not args.adapter:
        raise DiagError("usage", "give the adapter to serve with --adapter TYPE:CHANNEL")
    if args.adapter.startswith("remote:"):
        raise DiagError("usage", "an adapter server serves an adapter of this machine, not remote:")
    if not args.bitrate:
        raise DiagError("usage", "give the bus's bit rate with --bitrate KBIT; the server never guesses it")
    try:
        spec = adapter_mod.parse(args.adapter, args.adapter_option)
    except adapter_mod.AdapterError as e:
        raise DiagError("usage", str(e))
    return spec, args.bitrate * 1000


# ---------------------------------------------------------------------------
# The systemd service


def unit_name(spec):
    return "canworks-adapter-%s.service" % (re.sub(r"[^A-Za-z0-9_-]+", "-", spec.channel).strip("-") or spec.kind)


def _command():
    """How the service starts this canworks-diag: the installed command, else
    this Python with the module."""
    exe = os.path.realpath(sys.argv[0]) if sys.argv and sys.argv[0] else ""
    if os.path.basename(exe) == "canworks-diag" and os.access(exe, os.X_OK):
        return [exe]
    return [sys.executable, "-m", "canworks.diag"]


def serve_options(args):
    """The adapter-serve options the service runs with (no token options:
    the token is made before the unit starts)."""
    opts = ["--adapter", args.adapter, "--bitrate", str(args.bitrate), "--port", str(args.port)]
    for o in args.adapter_option or []:
        opts += ["--adapter-option", o]
    if args.bind:
        opts += ["--bind", args.bind]
    if args.check_node:
        opts += ["--check-node", str(args.check_node)]
    if args.allow_changes:
        opts.append("--allow-changes")
    return opts


def unit_text(spec, user, command):
    return ("[Unit]\n"
            "Description=canworks adapter server (%s)\n"
            "After=network-online.target\n"
            "Wants=network-online.target\n"
            "\n"
            "[Service]\n"
            "User=%s\n"
            "# Only what bringing a SocketCAN interface up at the bit rate needs (ip link set ... up).\n"
            "AmbientCapabilities=CAP_NET_ADMIN\n"
            "CapabilityBoundingSet=CAP_NET_ADMIN\n"
            "ExecStart=%s\n"
            "Restart=on-failure\n"
            "RestartSec=5\n"
            "\n"
            "[Install]\n"
            "WantedBy=multi-user.target\n") % (spec, user, " ".join(shlex.quote(c) for c in command))


def _systemctl(*args):
    try:
        r = subprocess.run(["systemctl"] + list(args), capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as e:
        raise ServeError("systemctl %s failed: %s" % (" ".join(args), e))
    return r


def _user_config_dir(user):
    import pwd
    return os.path.join(pwd.getpwnam(user).pw_dir, ".config", "canworks")


def _owner(user):
    import pwd
    info = pwd.getpwnam(user)
    return info.pw_uid, info.pw_gid


def install_service(args, out=sys.stdout, unit_dir=UNIT_DIR, avahi_dir=AVAHI_DIR):
    spec, bitrate = _spec_and_bitrate(args)
    if hasattr(os, "geteuid") and os.geteuid() != 0:
        raise ServeError("--install-service writes a systemd unit: run it with sudo")
    user = os.environ.get("SUDO_USER")
    if not user or user == "root":
        raise ServeError("run --install-service with sudo from the user the server runs as (not as root)")
    name = unit_name(spec)
    # The token, as the user's, before the unit starts.
    prepare_token(args.port, args.new_token, getattr(args, "serve_token_file", None), folder=_user_config_dir(user),
                  owner=_owner(user), out=out)
    unit = os.path.join(unit_dir, name)
    with open(unit, "w", encoding="utf-8") as f:
        f.write(unit_text(spec, user, _command() + ["adapter-serve"] + serve_options(args)))
    out.write("wrote %s\n" % unit)
    if os.path.isdir(avahi_dir):
        from ..link import discovery
        path = os.path.join(avahi_dir, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(discovery.avahi_adapter_service(args.port, socket.gethostname(), str(spec), bitrate // 1000))
        out.write("wrote %s (PCs on the local network find the server)\n" % path)
    else:
        out.write("Avahi is not installed: PCs connect by host name or address (no discovery)\n")
    for cmd in (("daemon-reload",), ("enable", "--now", name)):
        r = _systemctl(*cmd)
        if r.returncode != 0:
            raise ServeError("systemctl %s failed: %s" % (" ".join(cmd), (r.stderr or r.stdout).strip()))
    out.write("service %s runs as %s; it starts again after a reboot\n" % (name, user))
    return 0


def remove_service(args, out=sys.stdout, unit_dir=UNIT_DIR, avahi_dir=AVAHI_DIR):
    if hasattr(os, "geteuid") and os.geteuid() != 0:
        raise ServeError("--remove-service removes a systemd unit: run it with sudo")
    if args.adapter:
        try:
            names = [unit_name(adapter_mod.parse(args.adapter, args.adapter_option))]
        except adapter_mod.AdapterError as e:
            raise ServeError(str(e))
    else:
        names = sorted(os.path.basename(p) for p in glob.glob(os.path.join(unit_dir, "canworks-adapter-*.service")))
    if not names:
        out.write("no adapter server service is installed\n")
        return 0
    for name in names:
        _systemctl("disable", "--now", name)
        for path in (os.path.join(unit_dir, name), os.path.join(avahi_dir, name)):
            if os.path.exists(path):
                os.remove(path)
                out.write("removed %s\n" % path)
    _systemctl("daemon-reload")
    return 0


def show_status(args, out=sys.stdout, unit_dir=UNIT_DIR):
    """Whether the service runs, and which PCs are connected."""
    user = os.environ.get("SUDO_USER") if hasattr(os, "geteuid") and os.geteuid() == 0 else None
    folder = _user_config_dir(user) if user and user != "root" else None
    units = sorted(os.path.basename(p) for p in glob.glob(os.path.join(unit_dir, "canworks-adapter-*.service")))
    for name in units:
        r = _systemctl("is-active", name)
        out.write("service %s: %s\n" % (name, (r.stdout or "").strip() or "unknown"))
    if not units:
        out.write("no adapter server service is installed\n")
    found = False
    for path in sorted(glob.glob(os.path.join(folder or config_dir(), "adapter-serve-*.status.json"))):
        try:
            with open(path, encoding="utf-8") as f:
                st = json.load(f)
            os.kill(int(st["pid"]), 0)
        except (OSError, ValueError, KeyError, TypeError):
            continue  # left by a server that ended without cleaning up
        found = True
        pcs = st.get("pcs") or []
        out.write("server on port %s: adapter %s at %s kbit/s, %s, %s\n" % (
            st.get("port"), st.get("adapter"), st.get("bitrate_kbit"),
            "changes allowed" if st.get("allow_changes") else "read-only",
            "%d PC%s connected" % (len(pcs), "" if len(pcs) == 1 else "s") if pcs else "no PC connected"))
        for pc in pcs:
            out.write("  %s since %s (%d connection%s)\n" % (pc["address"], pc["since"], pc["connections"],
                                                              "" if pc["connections"] == 1 else "s"))
    if not found:
        out.write("no adapter server runs as this user\n")
    return 0


def service_command(args, out=sys.stdout):
    try:
        if args.install_service:
            return install_service(args, out)
        if args.remove_service:
            return remove_service(args, out)
        return show_status(args, out)
    except (ServeError, OSError, KeyError) as e:
        raise DiagError("usage", str(e))
