"""What both ends of the remote link agree on: stream headers, the JSON
lines of the control streams, the pairing login and which addresses count as
the local network. Only the standard library: the device side runs it too."""

import base64
import hashlib
import hmac
import ipaddress
import json
import secrets

from .. import diag

MAX_LINE = 16 * 1024
AUTH_PREFIX = "canworks-link/1"
CBIND_LABEL = b"canworks-link-pair"

# Addresses token pairing accepts with pairing "lan": private, link-local and
# the device itself.
LAN_NETWORKS = [ipaddress.ip_network(n) for n in (
    "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "169.254.0.0/16", "127.0.0.0/8",
    "fc00::/7", "fe80::/10", "::1/128")]

PAIRING_SCOPES = ("lan", "anywhere", "off")


class LinkError(Exception):
    """kind: unavailable, unpaired, refused, unreachable, token, impostor, protocol."""

    def __init__(self, kind, message):
        super().__init__(message)
        self.kind = kind


def is_lan_address(addr):
    """Whether "ip:port", "[v6]:port" or a bare IP is private or link-local."""
    host = (addr or "").strip()
    if host.startswith("["):
        host = host[1:].partition("]")[0]
    elif host.count(":") == 1:
        host = host.split(":")[0]
    host = host.split("%")[0]
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return any(ip in n for n in LAN_NETWORKS)


def channel_binding(device_id, pc_id):
    """What the pairing login is bound to: both ends' keys, which iroh's TLS
    has already proven."""
    return hashlib.sha256(CBIND_LABEL + bytes(device_id) + bytes(pc_id)).digest()


def auth_message(cnonce, snonce, salt_b64, iterations, cbind):
    return "%s,%s,%s,%s,%d,%s" % (AUTH_PREFIX, cnonce, snonce, salt_b64, iterations, diag._b64(cbind))


def new_nonce():
    return diag._b64(secrets.token_bytes(18))


def server_check(verifier, auth, proof_b64):
    """The server side of SCRAM-SHA-256: the ServerSignature (base64) when
    `proof_b64` proves the token of `verifier` for `auth`, else None."""
    v = diag.parse_verifier(verifier)
    if not v:
        return None
    _, _, stored, server = v
    try:
        proof = base64.b64decode(proof_b64 or "", validate=True)
    except (ValueError, TypeError):
        return None
    if len(proof) != 32:
        return None
    sig = diag._hmac(stored, auth)
    client_key = bytes(a ^ b for a, b in zip(proof, sig))
    if not hmac.compare_digest(hashlib.sha256(client_key).digest(), stored):
        return None
    return diag._b64(diag._hmac(server, auth))


def encode(msg):
    return json.dumps(msg, separators=(",", ":")).encode("utf-8") + b"\n"


class LineReader:
    """Reads JSON lines, then raw bytes, from an iroh RecvStream."""

    def __init__(self, recv):
        self.recv = recv
        self.buf = b""

    async def line(self):
        while b"\n" not in self.buf:
            chunk = await self.recv.read(MAX_LINE)
            if not chunk:
                raise LinkError("protocol", "the stream ended")
            self.buf += chunk
            if len(self.buf) > MAX_LINE:
                raise LinkError("protocol", "a line longer than %d bytes" % MAX_LINE)
        line, _, self.buf = self.buf.partition(b"\n")
        try:
            msg = json.loads(line.decode("utf-8"))
        except ValueError:
            raise LinkError("protocol", "not JSON")
        if not isinstance(msg, dict):
            raise LinkError("protocol", "not a JSON object")
        return msg

    def rest(self):
        """Bytes read past the last line."""
        data, self.buf = self.buf, b""
        return data
