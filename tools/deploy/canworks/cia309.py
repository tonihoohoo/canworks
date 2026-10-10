"""A small CiA 309-3 client for the plugin's gateway (docs/cia309-gateway.md).

Standard library only. A session is a socket that carries CiA 309-3 text
lines: the plugin's plain port on the loopback address, or a diagnostics
connection switched with the ``cia309`` op (``Client.tunnel``):

    c = Client.plain("127.0.0.1", 7533)
    c.command("1 2 r 0x1018 1 u32")      # -> "0x000001A2"
    c.request("1 2 w 0x2000 1 u8 3")     # -> "OK" or "ERROR: 102 (...)"
    c.notifications                      # "1 3 EMCY 5030 01 0 0 0 0 0", ...

``request`` puts the sequence number in front ("[5] ...") and returns the
answer's text after it. Lines without a sequence number are notifications
(EMCY, boot-up, error control); lines starting with "#" are the gateway's
comments (notifications lost).
"""

import re
import socket
import time

DEFAULT_PORT = 7533
_ANSWER = re.compile(r"^\s*\[(\d+)\]\s?(.*)$")


class GatewayError(Exception):
    """An "ERROR: <code>" answer; `code` is the CiA 309-3 internal error
    code (100-107, ...) or the SDO abort code."""

    def __init__(self, answer):
        super().__init__(answer)
        self.answer = answer
        m = re.match(r"ERROR:\s*(0x)?([0-9A-Fa-f]+)", answer)
        self.code = None
        if m:
            text = m.group(2)
            self.code = int(text, 16) if (m.group(1) or len(text) == 8) else int(text)


def error_code(answer):
    """The code of an "ERROR: ..." answer, or None."""
    return GatewayError(answer).code if answer.startswith("ERROR") else None


class Client:
    def __init__(self, sock, buf=b"", timeout=10.0):
        self.sock = sock
        self.buf = buf
        self.timeout = timeout
        self.seq = 0
        self.notifications = []
        self.comments = []
        self.answers = {}  # answers that came for other sequence numbers
        sock.settimeout(timeout)

    @classmethod
    def plain(cls, host="127.0.0.1", port=DEFAULT_PORT, timeout=10.0):
        return cls(socket.create_connection((host, port), timeout=timeout), timeout=timeout)

    @classmethod
    def tunnel(cls, diag_client, timeout=10.0):
        """Switches a logged-in diag.Client to CiA 309-3 lines (the cia309
        op). Returns (client, op result: protocol, version, nets). The diag
        client is detached from its socket."""
        info = diag_client.request("cia309")
        sock, buf = diag_client.sock, diag_client.buf
        diag_client.sock, diag_client.buf = None, b""
        return cls(sock, buf, timeout), info

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass

    def send_line(self, line):
        self.sock.sendall(line.encode("utf-8") + b"\r\n")

    def line(self, timeout=None):
        """The next line (without its line end); socket.timeout when none
        comes, EOFError when the gateway closed."""
        end = time.monotonic() + (self.timeout if timeout is None else timeout)
        while b"\n" not in self.buf:
            left = end - time.monotonic()
            if left <= 0:
                raise socket.timeout("no line from the gateway")
            self.sock.settimeout(left)
            try:
                chunk = self.sock.recv(65536)
            except socket.timeout:
                raise socket.timeout("no line from the gateway")
            if not chunk:
                raise EOFError("the gateway closed the connection")
            self.buf += chunk
        raw, _, self.buf = self.buf.partition(b"\n")
        return raw.decode("utf-8", "replace").rstrip("\r")

    def _sort(self, line):
        """Files a line: (seq, text) for an answer, else None."""
        if line.startswith("#"):
            self.comments.append(line)
            return None
        m = _ANSWER.match(line)
        if not m:
            if line.strip():
                self.notifications.append(line)
            return None
        return int(m.group(1)), m.group(2)

    def answer(self, seq, timeout=None):
        """The answer text for sequence number `seq`."""
        if seq in self.answers:
            return self.answers.pop(seq)
        end = time.monotonic() + (self.timeout if timeout is None else timeout)
        while True:
            got = self._sort(self.line(max(0.01, end - time.monotonic())))
            if got is None:
                continue
            if got[0] == seq:
                return got[1]
            self.answers[got[0]] = got[1]

    def send(self, text):
        """Sends a command without waiting; returns its sequence number."""
        self.seq += 1
        self.send_line("[%d] %s" % (self.seq, text))
        return self.seq

    def request(self, text, timeout=None):
        """Sends a command and returns its answer text ("OK", a value, or
        "ERROR: ...")."""
        return self.answer(self.send(text), timeout)

    def command(self, text, timeout=None):
        """As request(), raising GatewayError for an ERROR answer."""
        a = self.request(text, timeout)
        if a.startswith("ERROR"):
            raise GatewayError(a)
        return a

    def wait_notification(self, pattern, timeout=5.0):
        """The first notification (already received or coming) that matches
        the regular expression; socket.timeout when none comes."""
        rx = re.compile(pattern)
        end = time.monotonic() + timeout
        while True:
            for i, n in enumerate(self.notifications):
                if rx.search(n):
                    return self.notifications.pop(i)
            left = end - time.monotonic()
            if left <= 0:
                raise socket.timeout("no notification matching %r" % pattern)
            try:
                got = self._sort(self.line(left))
            except socket.timeout:
                continue
            if got is not None:
                self.answers[got[0]] = got[1]
