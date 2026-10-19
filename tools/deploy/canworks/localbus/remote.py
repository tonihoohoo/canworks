"""An adapter on another machine (canopen-remote-adapter): `--adapter
remote:HOST[:PORT]` and the configurator's Adapter on another machine.

RemoteBus is a diag.Client to an adapter server (canworks-diag adapter-serve,
localbus/serve.py) with LocalBus's interface: the session's allow-changes
switch, --force, the configured nodes and the network's name go to the
server in a "session" request, and the operations only a local adapter has
(the PDO test, SYNC, scan_stop) are LocalBus's own methods, which only call
request(). The bus timing stays on the server; only results cross the
network.
"""

import socket

from .. import diag
from ..diag import DiagError
from .client import LocalBus
from .serve import DEFAULT_PORT

PREFIX = "remote:"
LOGIN_TIMEOUT_S = 10.0  # the login opens the adapter and runs the bit rate check


def is_remote(text):
    return isinstance(text, str) and text.strip().lower().startswith(PREFIX)


def parse(text):
    """"HOST", "HOST:PORT" or "[v6]:PORT", with or without remote: ->
    (host, port); port 7536 when not given. Raises ValueError."""
    text = (text or "").strip()
    if is_remote(text):
        text = text[len(PREFIX):].strip()
    if not text:
        raise ValueError("give the adapter server's host: remote:HOST[:PORT]")
    host, port = text, DEFAULT_PORT
    if text.startswith("["):
        host, _, rest = text[1:].partition("]")
        if rest.startswith(":"):
            port = rest[1:]
    elif text.count(":") == 1:
        host, port = text.split(":")
    try:
        port = int(port)
    except ValueError:
        raise ValueError("port in %r is not a number" % text)
    if not host or not 1 <= port <= 65535:
        raise ValueError("%r is not HOST or HOST:PORT" % text)
    return host, port


def host_key(host, port):
    """How online.json keeps a server's token: HOST, with :PORT when not 7536."""
    h = "[%s]" % host if ":" in host else host
    return h if port == DEFAULT_PORT else "%s:%d" % (h, port)


def _open(host, port, timeout):
    try:
        return socket.create_connection((host, port), timeout=timeout)
    except OSError:
        return None


class RemoteBus(diag.Client):
    """One connection to an adapter server, used like a LocalBus. `config`
    names the configured nodes ({node_id: {name, expect}}), `network` the
    network (for the hello's network name)."""

    remember = False  # not a runtime: never remembered or paired for the remote link

    def __init__(self, host, port=DEFAULT_PORT, token="", timeout=5.0, allow_changes=False, force=False,
                 config=None, network=None):
        super().__init__(host, port, token, timeout)
        self._allow, self._force = bool(allow_changes), bool(force)
        self.config = dict(config or {})
        self.network_name = network

    # The session settings: sent at once on an open connection.
    @property
    def allow_changes(self):
        return self._allow

    @allow_changes.setter
    def allow_changes(self, on):
        if bool(on) != self._allow:
            self._allow = bool(on)
            self._session(allow_changes=self._allow)

    @property
    def force(self):
        return getattr(self, "_force", False)

    @force.setter
    def force(self, on):
        # diag.Client.__init__ sets it before the connection exists.
        if bool(on) != getattr(self, "_force", False):
            self._force = bool(on)
            self._session(force=self._force)

    def _session(self, **fields):
        if self.sock is None:
            return
        try:
            self.info = self.request("session", **fields)
        except DiagError:
            pass  # the next request says what went wrong

    @property
    def where(self):
        return "adapter server %s" % super().where

    def _open(self):
        # Directly: an adapter server is not remembered or reached over the remote link.
        self.path = "LAN"
        return socket.create_connection((self.host, self.port), timeout=self.timeout)

    def connect(self):
        timeout, self.timeout = self.timeout, max(self.timeout, LOGIN_TIMEOUT_S)
        try:
            super().connect()
        except DiagError as e:
            if e.kind == "closed":
                raise DiagError("closed", self._closed_text())
            if e.kind == "token":
                raise DiagError("token", "%s: wrong token" % self.where)
            raise
        finally:
            self.timeout = timeout
            if self.sock is not None:
                self.sock.settimeout(timeout)
        if not (self.info or {}).get("local"):
            self.close()
            raise DiagError("protocol", "%s is a runtime, not an adapter server: connect without remote: "
                                        "(--runtime %s)" % (self.host, self.host))
        self.rtts = []  # the login's round trip includes the bit rate check
        self.info = self.request("session", allow_changes=self._allow, force=self._force,
                                 nodes={str(k): v for k, v in self.config.items()},
                                 **({"network_name": self.network_name} if self.network_name else {}))
        return self.info

    def _closed_text(self):
        # A runtime there answers on its diagnostics port: say so rather than "closed".
        s = _open(self.host, diag.DEFAULT_PORT, min(self.timeout, 2.0)) if self.port != diag.DEFAULT_PORT else None
        if s is not None:
            s.close()
            return ("%s is a runtime, not an adapter server: connect without remote: (--runtime %s)"
                    % (self.host, self.host))
        return ("port %d on %s is closed: no adapter server runs there (canworks-diag adapter-serve on that "
                "machine, docs/pc-adapter.md)" % (self.port, self.host))

    # What a local adapter has and a runtime does not.
    scan_stop = LocalBus.scan_stop
    pdo_test_start = LocalBus.pdo_test_start
    pdo_test_status = LocalBus.pdo_test_status
    pdo_test_set = LocalBus.pdo_test_set
    pdo_test_stop = LocalBus.pdo_test_stop
    sync_start = LocalBus.sync_start
    sync_stop = LocalBus.sync_stop
