"""TLS and the SCRAM login for the fake servers (fake_diag.py, fake_sim.py),
as the plugin does them (plugin/src/can/secure_channel.h). The certificate in
data/tls is a test certificate; the real plugin makes a new one whenever it
starts."""

import base64
import hashlib
import hmac
import os
import secrets
import socket
import ssl

from canworks import diag

HERE = os.path.dirname(os.path.abspath(__file__))
CERT = os.path.join(HERE, "data", "tls", "test-cert.pem")
KEY = os.path.join(HERE, "data", "tls", "test-key.pem")
with open(CERT) as f:
    CERT_HASH = hashlib.sha256(ssl.PEM_cert_to_DER_cert(f.read())).digest()

_ctx = None


def server_context():
    global _ctx
    if _ctx is None:
        _ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        _ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        _ctx.load_cert_chain(CERT, KEY)
    return _ctx


def accept(handler):
    """From a StreamRequestHandler's setup(), before the base setup: wraps
    the connection in TLS when it starts with a TLS handshake. "tls",
    "plain", or None (the handshake failed)."""
    try:
        first = handler.request.recv(1, socket.MSG_PEEK)
    except OSError:
        return None
    if first != b"\x16":
        return "plain"
    try:
        handler.request = handler.connection = server_context().wrap_socket(handler.request, server_side=True)
    except (ssl.SSLError, OSError):
        return None
    return "tls"


def _b64(data):
    return base64.b64encode(data).decode("ascii")


class Login:
    """The server's side of the login for `token`."""

    def __init__(self, token):
        self.iterations, self.salt, self.stored, self.server = diag.parse_verifier(diag.token_verifier(token or ""))
        self.cnonce = self.snonce = None

    def hello(self, req):
        """The hello's result, or None (close without an answer)."""
        if req.get("op") != "hello" or req.get("mech") != diag.SCRAM_MECH or not isinstance(req.get("nonce"), str):
            return None
        self.cnonce, self.snonce = req["nonce"], _b64(secrets.token_bytes(18))
        return {"protocol": 2, "nonce": self.snonce, "salt": _b64(self.salt), "iterations": self.iterations}

    def login(self, req):
        """The server signature (base64) when the proof matches, else None."""
        if req.get("op") != "login" or self.snonce is None:
            return None
        try:
            proof = base64.b64decode(req.get("proof") or "", validate=True)
        except (ValueError, TypeError):
            return None
        auth = diag.scram_auth_message(self.cnonce, self.snonce, _b64(self.salt), self.iterations, CERT_HASH)
        sig = hmac.new(self.stored, auth.encode(), hashlib.sha256).digest()
        client_key = bytes(a ^ b for a, b in zip(proof, sig))
        if len(proof) != 32 or not hmac.compare_digest(hashlib.sha256(client_key).digest(), self.stored):
            return None
        return _b64(hmac.new(self.server, auth.encode(), hashlib.sha256).digest())
