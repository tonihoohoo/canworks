"""openplc-canopen-diag: talk to the CANopen plugin's diagnostics channel.

  openplc-canopen-diag --runtime plc.local status
  openplc-canopen-diag --runtime plc.local sdo-read 23 0x1008 0 --type VISIBLE_STRING
  openplc-canopen-diag --runtime plc.local sdo-read 2 0x1018 1 --network drives
  openplc-canopen-diag --runtime plc.local send 0x60A "40 18 10 01 00 00 00 00"
  openplc-canopen-diag --runtime plc.local detect-bitrate --rates 125,250,500
  openplc-canopen-diag hash-token
  openplc-canopen-diag --runtime plc.local sim fault 5 emcy 0x5000 --register 1
  openplc-canopen-diag sim --sim 127.0.0.1 status

`sim` controls simulated devices (docs/simulator.md): the plugin's, with
--runtime, or a standalone openplc-canopen-sim's, with --sim HOST[:PORT].

The channel is opt-in (master.diagnostics in canopen.json) and speaks
line-delimited JSON over TLS, port 7531 by default, after a SCRAM-SHA-256
login bound to the server's certificate, so the token never crosses the
network; see docs/diagnostics.md.
With several CAN networks every command but status needs --network NAME;
status then prints every network.
The token comes from --token, $OPENPLC_CANOPEN_TOKEN or a prompt. The
configurator's online view uses the Client class of this module.
"""

import argparse
import base64
import getpass
import hashlib
import hmac
import json
import os
import secrets
import socket
import ssl
import struct
import sys
import time

from . import __version__, localruntime

DEFAULT_PORT = 7531
PROTOCOL = 2        # TLS and the SCRAM login
PLAIN_PROTOCOL = 1  # a standalone simulator without a token, on loopback
SCRAM_MECH = "SCRAM-SHA-256-PLUS"
SCRAM_ITERATIONS = 4096
SCRAM_MIN_ITERATIONS, SCRAM_MAX_ITERATIONS = 4096, 1000000
TOKEN_ENV = "OPENPLC_CANOPEN_TOKEN"
MAX_LINE = 1024 * 1024
NMT_COMMANDS = ("start", "stop", "preop", "reset", "reset-comm")
LSS_BITRATES = (10, 20, 50, 125, 250, 500, 800, 1000)  # kbit/s, the CiA 305 bit timing table
LSS_KEYS = ("vendor_id", "product_code", "revision_number", "serial_number")
DETECT_RATES = (1000, 800, 500, 250, 125, 50, 20, 10)  # kbit/s, the order a bit rate sweep listens in
FORCE_NEEDED = "force needed"  # the end of a refusal the request may be repeated with force: true
TOO_OLD = "the runtime's CANopen plugin is too old for this command (update it)"
SILENT_HINT = ("The bus was silent. A listening adapter sends no acknowledge, so frames only count when "
               "another device acknowledges them: with one device on the bus, add a second device or a second "
               "adapter in normal mode. A device that only sends its boot-up message: power-cycle it during the "
               "sweep, or run more rounds.")


# ---------------------------------------------------------------------------
# The SCRAM-SHA-256 login (plugin/src/secure_channel.h has the same math).


def _b64(data):
    return base64.b64encode(data).decode("ascii")


def _salted(token, salt, iterations):
    return hashlib.pbkdf2_hmac("sha256", token.encode("utf-8"), salt, iterations)


def _hmac(key, data):
    return hmac.new(key, data if isinstance(data, bytes) else data.encode("utf-8"), hashlib.sha256).digest()


def token_verifier(token, salt=None, iterations=SCRAM_ITERATIONS):
    """What goes in master.diagnostics.token_verifier: SCRAM-SHA-256 with a
    fresh random salt. It does not let anyone log in."""
    salt = salt if salt is not None else secrets.token_bytes(16)
    sp = _salted(token, salt, iterations)
    stored = hashlib.sha256(_hmac(sp, "Client Key")).digest()
    return "SCRAM-SHA-256$%d:%s$%s:%s" % (iterations, _b64(salt), _b64(stored), _b64(_hmac(sp, "Server Key")))


def parse_verifier(text):
    """(iterations, salt, stored_key, server_key), or None when `text` is not
    a valid token_verifier."""
    try:
        if not isinstance(text, str) or not text.startswith("SCRAM-SHA-256$"):
            return None
        params, keys = text[len("SCRAM-SHA-256$"):].split("$")
        it, salt = params.split(":")
        stored, server = keys.split(":")
        it = int(it)
        salt, stored, server = (base64.b64decode(x, validate=True) for x in (salt, stored, server))
    except (ValueError, TypeError):
        return None
    if not SCRAM_MIN_ITERATIONS <= it <= SCRAM_MAX_ITERATIONS or len(salt) < 16 or len(stored) != 32 or len(server) != 32:
        return None
    return it, salt, stored, server


def token_matches(token, verifier):
    """Whether `token` is the token of `verifier`."""
    v = parse_verifier(verifier)
    if not v or not token:
        return False
    it, salt, stored, _ = v
    return hmac.compare_digest(hashlib.sha256(_hmac(_salted(token, salt, it), "Client Key")).digest(), stored)


def scram_auth_message(cnonce, snonce, salt_b64, iterations, cbind):
    return "openplc-canopen-diag/2,%s,%s,%s,%d,%s" % (cnonce, snonce, salt_b64, iterations, _b64(cbind))


def scram_client(token, salt, iterations, auth_message):
    """(ClientProof, the ServerSignature the server must send back)."""
    sp = _salted(token, salt, iterations)
    client_key = _hmac(sp, "Client Key")
    sig = _hmac(hashlib.sha256(client_key).digest(), auth_message)
    proof = bytes(a ^ b for a, b in zip(client_key, sig))
    return proof, _hmac(_hmac(sp, "Server Key"), auth_message)


def _client_context():
    # The login checks the server (channel binding to its certificate), so
    # the chain is not checked: the plugin makes a new self-signed
    # certificate whenever it starts.
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    return ctx


def new_token():
    """A random token of 192 bits, safe to type and paste."""
    return secrets.token_urlsafe(24)


def parse_runtime(text):
    """"host", "host:port" or "[v6]:port" -> (host, port)."""
    text = (text or "").strip()
    if not text:
        raise ValueError("no runtime host given")
    if localruntime.is_local(text):
        # The local simulator runtime (openplc-canopen-sim-runtime): its published diagnostics port.
        try:
            saved = localruntime.load_settings() or {}
        except localruntime.LocalRuntimeError:
            saved = {}
        return "127.0.0.1", int(saved.get("diag_port") or localruntime.DIAG_PORT)
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


# ---------------------------------------------------------------------------
# Values

# EDS DataType code -> name. Integers of every width CiA 301 defines; the
# config itself only uses the 8/16/32/64-bit ones (iec.CO_TYPES).
TYPE_CODES = {
    0x0001: "BOOLEAN", 0x0002: "INTEGER8", 0x0003: "INTEGER16", 0x0004: "INTEGER32", 0x0005: "UNSIGNED8",
    0x0006: "UNSIGNED16", 0x0007: "UNSIGNED32", 0x0008: "REAL32", 0x0009: "VISIBLE_STRING",
    0x000A: "OCTET_STRING", 0x000B: "UNICODE_STRING", 0x000F: "DOMAIN", 0x0010: "INTEGER24", 0x0011: "REAL64",
    0x0012: "INTEGER40", 0x0013: "INTEGER48", 0x0014: "INTEGER56", 0x0015: "INTEGER64", 0x0016: "UNSIGNED24",
    0x0018: "UNSIGNED40", 0x0019: "UNSIGNED48", 0x001A: "UNSIGNED56", 0x001B: "UNSIGNED64",
}
TYPE_NAMES = sorted(set(TYPE_CODES.values()))


def _int_type(name):
    """(bytes, signed) for an integer type name, else None."""
    for prefix, signed in (("INTEGER", True), ("UNSIGNED", False)):
        if name.startswith(prefix) and name[len(prefix):].isdigit():
            return int(name[len(prefix):]) // 8, signed
    return None


def type_name(t):
    """A type given as a name ("unsigned16") or an EDS code (6, "0x0006")."""
    if isinstance(t, int):
        return TYPE_CODES.get(t)
    t = str(t or "").strip()
    if not t:
        return None
    try:
        return TYPE_CODES.get(int(t, 0))
    except ValueError:
        pass
    t = t.upper()
    return t if t in TYPE_NAMES else None


def hex_bytes(data):
    return " ".join("%02X" % b for b in data)


def parse_hex(text):
    digits = "".join((text or "").split())
    if digits.lower().startswith("0x"):
        digits = digits[2:]
    if not digits or len(digits) % 2:
        raise ValueError("%r is not hexadecimal bytes such as \"1E 00\"" % text)
    return bytes.fromhex(digits)


def decode(t, data):
    """How to show bytes read from an object of type t: {"text", "hex"} and,
    for numbers, "value"."""
    name = type_name(t)
    out = {"hex": hex_bytes(data), "text": hex_bytes(data) or "(empty)"}
    if name == "VISIBLE_STRING":
        out["text"] = data.split(b"\0", 1)[0].decode("latin-1")
    elif name == "UNICODE_STRING" and len(data) % 2 == 0:
        out["text"] = data.decode("utf-16-le", "replace").split("\0", 1)[0]
    elif name == "BOOLEAN" and len(data) == 1:
        out["value"] = bool(data[0])
        out["text"] = "TRUE" if data[0] else "FALSE"
    elif name in ("REAL32", "REAL64") and len(data) == (4 if name == "REAL32" else 8):
        v = struct.unpack("<f" if name == "REAL32" else "<d", data)[0]
        out["value"] = v
        out["text"] = repr(v)
    elif name and _int_type(name) and len(data) == _int_type(name)[0]:
        size, signed = _int_type(name)
        v = int.from_bytes(data, "little", signed=signed)
        out["value"] = v
        u = int.from_bytes(data, "little")
        out["text"] = "%d (0x%0*X)" % (v, size * 2, u)
    return out


def encode(t, text):
    """Bytes to write for a value given as text, checked against the type's
    range. OCTET_STRING, DOMAIN and unknown types take hex bytes."""
    name = type_name(t)
    text = str(text)
    if name == "VISIBLE_STRING":
        try:
            return text.encode("latin-1")
        except UnicodeEncodeError:
            raise ValueError("VISIBLE_STRING takes ISO 8859-1 characters only")
    if name == "UNICODE_STRING":
        return text.encode("utf-16-le")
    if name == "BOOLEAN":
        v = text.strip().lower()
        if v in ("1", "true", "on"):
            return b"\x01"
        if v in ("0", "false", "off"):
            return b"\x00"
        raise ValueError("BOOLEAN takes 0/1 or true/false, not %r" % text)
    if name in ("REAL32", "REAL64"):
        try:
            v = float(text)
        except ValueError:
            raise ValueError("%r is not a number" % text)
        try:
            return struct.pack("<f" if name == "REAL32" else "<d", v)
        except OverflowError:
            raise ValueError("%s is out of range for REAL32" % text)
    it = _int_type(name) if name else None
    if it:
        size, signed = it
        try:
            v = int(text.strip(), 0)
        except ValueError:
            raise ValueError("%r is not an integer (decimal, or hex as 0x...)" % text)
        lo, hi = (-(1 << (size * 8 - 1)), (1 << (size * 8 - 1)) - 1) if signed else (0, (1 << (size * 8)) - 1)
        if not lo <= v <= hi:
            raise ValueError("%d is out of range for %s (%d to %d)" % (v, name, lo, hi))
        return v.to_bytes(size, "little", signed=signed)
    return parse_hex(text)


# CiA 301 SDO abort codes.
ABORT_TEXT = {
    0x05030000: "toggle bit not alternated",
    0x05040000: "SDO protocol timed out",
    0x05040001: "client/server command specifier not valid or unknown",
    0x05040002: "invalid block size",
    0x05040003: "invalid sequence number",
    0x05040004: "CRC error",
    0x05040005: "out of memory",
    0x06010000: "unsupported access to an object",
    0x06010001: "attempt to read a write only object",
    0x06010002: "attempt to write a read only object",
    0x06020000: "object does not exist in the object dictionary",
    0x06040041: "object cannot be mapped to the PDO",
    0x06040042: "the number and length of the objects to be mapped would exceed the PDO length",
    0x06040043: "general parameter incompatibility",
    0x06040047: "general internal incompatibility in the device",
    0x06060000: "access failed due to a hardware error",
    0x06070010: "data type does not match, length of service parameter does not match",
    0x06070012: "data type does not match, length of service parameter too high",
    0x06070013: "data type does not match, length of service parameter too low",
    0x06090011: "sub-index does not exist",
    0x06090030: "invalid value for parameter (download only)",
    0x06090031: "value of parameter written too high (download only)",
    0x06090032: "value of parameter written too low (download only)",
    0x06090036: "maximum value is less than minimum value",
    0x060A0023: "resource not available: SDO connection",
    0x08000000: "general error",
    0x08000020: "data cannot be transferred or stored to the application",
    0x08000021: "data cannot be transferred or stored to the application because of local control",
    0x08000022: "data cannot be transferred or stored to the application because of the present device state",
    0x08000023: "object dictionary dynamic generation fails or no object dictionary is present",
    0x08000024: "no data available",
}


def abort_text(code):
    return ABORT_TEXT.get(code, "abort code 0x%08X" % code)


# CiA 301 emergency error code classes, by the code's upper bits.
EMCY_CLASSES = [
    (0xFFFF, 0x0000, "error reset or no error"),
    (0xFF00, 0x1000, "generic error"),
    (0xF000, 0x2000, "current"),
    (0xF000, 0x3000, "voltage"),
    (0xF000, 0x4000, "temperature"),
    (0xFF00, 0x5000, "device hardware"),
    (0xF000, 0x6000, "device software"),
    (0xFF00, 0x7000, "additional modules"),
    (0xFF00, 0x8100, "communication"),
    (0xFF00, 0x8200, "protocol error"),
    (0xF000, 0x8000, "monitoring"),
    (0xFF00, 0x9000, "external error"),
    (0xFF00, 0xF000, "additional functions"),
    (0xFF00, 0xFF00, "device specific"),
]


def emcy_class(code):
    for mask, value, name in EMCY_CLASSES:
        if code & mask == value:
            return name
    return "reserved"


STATE_NAMES = {0: "unknown", 4: "STOPPED", 5: "OPERATIONAL", 127: "PRE-OPERATIONAL"}
BUS_STATES = {0: "no bus", 1: "error active", 2: "error warning", 3: "error passive", 4: "bus off"}


def state_name(state):
    return STATE_NAMES.get(state, str(state))


# ---------------------------------------------------------------------------
# Client


class DiagError(Exception):
    """kind: unreachable, closed (port closed), token, timeout, protocol,
    old (no TLS: the plugin is too old), impostor (the server could not prove
    it knows the token), or refused (the plugin answered with an error)."""

    def __init__(self, kind, message):
        super().__init__(message)
        self.kind = kind


class Client:
    """One connection to the plugin. `network` names the network every
    request after the hello is for; it is sent only when the plugin runs
    several networks (an older plugin knows no networks).

    With a token the connection is TLS with the SCRAM login (the plugin
    always; a standalone simulator with a token); without one it is plain,
    for a local simulator without a token."""

    def __init__(self, host, port=DEFAULT_PORT, token="", timeout=5.0, network=None):
        self.host, self.port, self.token, self.timeout = host, port, token, timeout
        self.network = network
        self.sock = None
        self.buf = b""
        self.info = None
        self.next_id = 1

    @property
    def where(self):
        return "%s:%d" % (self.host, self.port)

    @property
    def networks(self):
        """The hello's networks ([{name, interface, bitrate, role,
        master_node_id}], a slave network with node_id instead);
        [] from a plugin that runs one network and does not list it."""
        nets = (self.info or {}).get("networks")
        return nets if isinstance(nets, list) else []

    def several(self):
        return len(self.networks) > 1

    def connect(self):
        """Connect and authenticate; the hello result (protocol, version,
        allow_changes, master_node_id)."""
        self.close()
        try:
            self.sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        except socket.gaierror as e:
            raise DiagError("unreachable", "host %s is unknown: %s" % (self.host, e.strerror or e))
        except ConnectionRefusedError:
            raise DiagError("closed", "port %d on %s is closed: online access is not enabled in the configuration "
                                      "the runtime runs, or the PLC program is stopped" % (self.port, self.host))
        except socket.timeout:
            raise DiagError("unreachable", "host %s does not answer (timed out)" % self.host)
        except OSError as e:
            raise DiagError("unreachable", "host %s is unreachable: %s" % (self.host, e.strerror or e))
        self.buf = b""
        if not self.token:
            try:
                self.info = self.request("hello")
            except DiagError:
                self.close()
                raise
            want = PLAIN_PROTOCOL
        else:
            self._login()
            want = PROTOCOL
        if self.info.get("protocol") != want:
            proto = self.info.get("protocol")
            self.close()
            raise DiagError("protocol", "%s speaks diagnostics protocol %s; this tool speaks %d"
                            % (self.where, proto, want))
        return self.info

    def _login(self):
        old = DiagError("old", "%s does not speak encrypted diagnostics: the plugin (or simulator) there is too old; "
                               "update it" % self.where)
        try:
            self.sock = _client_context().wrap_socket(self.sock, server_hostname=None)
        except socket.timeout:
            self.close()
            raise old
        except (ssl.SSLError, OSError):
            self.close()
            raise old
        cbind = hashlib.sha256(self.sock.getpeercert(binary_form=True) or b"").digest()
        cnonce = _b64(secrets.token_bytes(18))
        try:
            first = self.request("hello", mech=SCRAM_MECH, nonce=cnonce)
            salt_b64, snonce, it = first.get("salt"), first.get("nonce"), first.get("iterations")
            try:
                salt = base64.b64decode(salt_b64, validate=True)
            except (ValueError, TypeError):
                salt = None
            if (not isinstance(snonce, str) or salt is None or not isinstance(it, int)
                    or not SCRAM_MIN_ITERATIONS <= it <= SCRAM_MAX_ITERATIONS):
                raise DiagError("protocol", "%s sent an unexpected login answer" % self.where)
            auth = scram_auth_message(cnonce, snonce, salt_b64, it, cbind)
            proof, want = scram_client(self.token, salt, it, auth)
            info = self.request("login", proof=_b64(proof))
        except DiagError as e:
            self.close()
            if e.kind == "eof":
                raise DiagError("token", "%s refused the token (wrong token for this configuration)" % self.where)
            raise
        sig = info.pop("signature", None)
        try:
            got = base64.b64decode(sig or "", validate=True)
        except (ValueError, TypeError):
            got = b""
        if not hmac.compare_digest(got, want):
            self.close()
            raise DiagError("impostor", "%s could not prove it knows this project's token (a machine in the "
                                        "middle?); nothing was sent" % self.where)
        self.info = info
        self.next_id = 2  # requests are numbered from 2 after the login, as after a plain hello

    def close(self):
        if self.sock:
            try:
                self.sock.close()
            except OSError:
                pass
        self.sock = None

    def _line(self):
        while b"\n" not in self.buf:
            try:
                chunk = self.sock.recv(65536)
            except socket.timeout:
                raise DiagError("timeout", "%s did not answer in %g s" % (self.where, self.timeout))
            except OSError as e:
                raise DiagError("eof", "connection to %s lost: %s" % (self.where, e.strerror or e))
            if not chunk:
                raise DiagError("eof", "%s closed the connection" % self.where)
            self.buf += chunk
            if len(self.buf) > MAX_LINE:
                raise DiagError("protocol", "%s sent a line longer than %d bytes" % (self.where, MAX_LINE))
        line, _, self.buf = self.buf.partition(b"\n")
        return line

    def request(self, op, timeout=None, **fields):
        """Send one request and return its result; raise DiagError("refused")
        with the plugin's reason when it answers ok: false."""
        if not self.sock:
            raise DiagError("eof", "not connected to %s" % self.where)
        rid = self.next_id
        self.next_id += 1
        msg = dict(fields, op=op, id=rid)
        if op != "hello" and self.network and "network" not in msg and self.several():
            msg["network"] = self.network
        if timeout is not None:
            self.sock.settimeout(timeout)
        try:
            try:
                self.sock.sendall(json.dumps(msg).encode("utf-8") + b"\n")
            except OSError as e:
                raise DiagError("eof", "connection to %s lost: %s" % (self.where, e.strerror or e))
            while True:
                try:
                    answer = json.loads(self._line().decode("utf-8"))
                except ValueError:
                    raise DiagError("protocol", "%s sent something that is not JSON" % self.where)
                if not isinstance(answer, dict):
                    raise DiagError("protocol", "%s sent something that is not a JSON object" % self.where)
                if answer.get("id") not in (rid, None):
                    continue  # an answer to an earlier request that timed out here
                if answer.get("ok"):
                    return answer.get("result") or {}
                raise DiagError("refused", str(answer.get("error") or "request refused"))
        finally:
            if timeout is not None and self.sock:
                self.sock.settimeout(self.timeout)

    # -- the ops ------------------------------------------------------------
    def status(self):
        return self.request("status")

    def emcy(self, node):
        return self.request("emcy", node=node)

    def sdo_read(self, node, index, subindex, timeout_ms=1000):
        return self.request("sdo_read", timeout=self.timeout + timeout_ms / 1000.0, node=node, index=index,
                            subindex=subindex, timeout_ms=timeout_ms)

    def sdo_write(self, node, index, subindex, data, timeout_ms=1000):
        return self.request("sdo_write", timeout=self.timeout + timeout_ms / 1000.0, node=node, index=index,
                            subindex=subindex, data=hex_bytes(data), timeout_ms=timeout_ms)

    def nmt(self, node, command):
        return self.request("nmt", node=node, command=command)

    def scan(self, start=True):
        return self.request("scan" if start else "scan_status")

    # LSS (CiA 305). An address is (vendor_id, product_code, revision_number,
    # serial_number). Everything but lss_find_status needs allow_changes.
    def lss_find(self, start=True, vendor_id=None, product_code=None):
        """Start (or poll) the search for a device without a node ID. Give
        vendor and product together to narrow it."""
        fields = {}
        if start and vendor_id is not None and product_code is not None:
            fields = {"vendor_id": vendor_id, "product_code": product_code}
        return self.request("lss_find" if start else "lss_find_status", **fields)

    def lss_inquire(self, address):
        return self.request("lss_inquire", **dict(zip(LSS_KEYS, address)))

    def lss_set_id(self, address, node, store=False):
        return self.request("lss_set_id", node=node, store=bool(store), **dict(zip(LSS_KEYS, address)))

    def lss_set_bitrate(self, address, bitrate_kbit, store=False):
        return self.request("lss_set_bitrate", bitrate_kbit=bitrate_kbit, store=bool(store),
                            **dict(zip(LSS_KEYS, address)))

    # Traces (frame capture). Read-only: the token is enough.
    def trace_start(self, filters=None, error_frames=False):
        """Starts this connection's trace; filters: [(id, mask)]. The result's
        "next" is the cursor for the first trace_fetch."""
        fields = {"error_frames": bool(error_frames)}
        if filters:
            fields["filters"] = [{"id": i, "mask": m} for i, m in filters]
        return self.request("trace_start", **fields)

    def trace_fetch(self, after, max_frames=4000):
        """Frames after the cursor: the result has "frames" (base64 of
        24-byte records), "count", "next", "more", "lost", "kernel_drops"
        and "session"."""
        return self.request("trace_fetch", after=after, max=max_frames)

    def trace_stop(self):
        return self.request("trace_stop")

    # Raw frames and bit rate detection (allow_changes). A refusal that ends in
    # "force needed" may be repeated with force=True once the user agrees.
    def send_frame(self, can_id, data=b"", ext=False, rtr=False, dlc=None, period_ms=None, count=None, force=False):
        """One frame, or with period_ms a cyclic job of this connection: the
        result has "sent", or "job", "period_ms" and "count"."""
        # The identifier is can_id: "id" is the request's own (echoed in the answer).
        fields = {"can_id": can_id, "ext": bool(ext), "rtr": bool(rtr)}
        if rtr:
            fields["dlc"] = dlc or 0
        elif data:
            fields["data"] = hex_bytes(data)
        if period_ms:
            fields["period_ms"] = period_ms
            if count:
                fields["count"] = count
        if force:
            fields["force"] = True
        return self.request("send_frame", **fields)

    def send_frame_stop(self, job=None):
        """Stops one cyclic job of this connection, or all of them: "stopped"
        lists each with its "sent" count and "reason"."""
        return self.request("send_frame_stop", **({} if job is None else {"job": job}))

    def detect_bitrate(self, rates=None, per_rate_ms=None, rounds=None, force=False):
        """Starts a bit rate sweep (unless one runs) and returns its progress."""
        fields = {}
        if rates:
            fields["rates"] = list(rates)
        if per_rate_ms:
            fields["per_rate_ms"] = per_rate_ms
        if rounds:
            fields["rounds"] = rounds
        if force:
            fields["force"] = True
        return self.request("detect_bitrate", **fields)

    def detect_bitrate_status(self):
        return self.request("detect_bitrate_status")


def too_old(e):
    """The plugin does not know the op: it predates the command."""
    return e.kind == "refused" and str(e).startswith("unknown op")


def needs_force(e):
    """A refusal the request may be repeated for with force: true."""
    return e.kind == "refused" and str(e).rstrip().endswith(FORCE_NEEDED)


def parse_frame_id(value, ext=False):
    """A CAN identifier: an int, or text as 0x60A or decimal; 11 bits, or 29
    with ext."""
    if isinstance(value, bool):
        raise ValueError("identifier %r is not a number" % value)
    if not isinstance(value, int):
        try:
            value = int(str(value).strip(), 0)
        except ValueError:
            raise ValueError("identifier %r is not a number (write hex as 0x60A)" % value)
    top = 0x1FFFFFFF if ext else 0x7FF
    if not 0 <= value <= top:
        raise ValueError("identifier 0x%X is out of range: 0x0-0x%X%s" % (value, top, "" if ext else
                                                                          " (an extended identifier needs ext)"))
    return value


def parse_frame_data(parts):
    """Up to 8 data bytes from "40 18 10 01", "40181001" or several pieces."""
    if isinstance(parts, str):
        parts = [parts]
    digits = "".join("".join(parts or []).split())
    if not digits:
        return b""
    data = parse_hex(digits)
    if len(data) > 8:
        raise ValueError("a CAN frame carries at most 8 data bytes, not %d" % len(data))
    return data


def frame_text(can_id, ext=False, rtr=False, dlc=None, data=b""):
    """A frame as the CLI and the logs show it: "0x60A [4] 40 18 10 01"."""
    ident = ("0x%08X" if ext else "0x%03X") % can_id
    if rtr:
        return "%s remote [%d]" % (ident, dlc or 0)
    return "%s [%d] %s" % (ident, len(data), hex_bytes(data)) if data else "%s [0]" % ident


def verdict_text(res):
    """One line for a finished bit rate sweep."""
    v = res.get("verdict")
    if v == "detected":
        rate, conf = res.get("bitrate_kbit"), res.get("configured_kbit")
        if res.get("matches_config"):
            return "%s kbit/s detected, as configured" % rate
        return "%s kbit/s detected%s" % (rate, " (the configuration has %s kbit/s)" % conf if conf else "")
    if v == "ambiguous":
        cands = res.get("candidates") or []
        return "ambiguous: frames at %s kbit/s" % ", ".join(str(c) for c in cands) if cands else "ambiguous"
    if v == "silent":
        return SILENT_HINT
    if v == "failed":
        return "the sweep failed: %s" % (res.get("error") or "no reason given")
    return "no result"


def skipped_text(res):
    """The rates a sweep left out because the adapter cannot be set to them,
    or ''."""
    skipped = res.get("skipped_kbit") or []
    if not skipped:
        return ""
    return "not tried: %s kbit/s (the adapter cannot be set to %s)" % (
        ", ".join(str(k) for k in skipped), "it" if len(skipped) == 1 else "them")


def lss_address_text(a):
    """An LSS address as the plugin logs it."""
    return "vendor 0x%08X, product 0x%08X, revision 0x%08X, serial 0x%08X" % tuple(
        a.get(k, 0) if isinstance(a, dict) else a[i] for i, k in enumerate(LSS_KEYS))


def sdo_failure(result):
    """The reason an SDO answer with success false gives."""
    code = result.get("abort_code")
    if code is not None:
        return "abort 0x%08X: %s" % (code, abort_text(code))
    return result.get("error") or "failed"


# ---------------------------------------------------------------------------
# Command line


def _uint(text, what, top):
    try:
        v = int(str(text), 0)
    except ValueError:
        raise argparse.ArgumentTypeError("%s %r is not a number" % (what, text))
    if not 0 <= v <= top:
        raise argparse.ArgumentTypeError("%s %r is out of range" % (what, text))
    return v


def _node(t):
    v = _uint(t, "node ID", 127)
    if v < 1:
        raise argparse.ArgumentTypeError("node ID must be 1-127")
    return v


def _type(t):
    name = type_name(t)
    if not name:
        raise argparse.ArgumentTypeError("unknown type %r (one of %s)" % (t, ", ".join(TYPE_NAMES)))
    return name


def _u32(what):
    return lambda t: _uint(t, what, 0xFFFFFFFF)


def _lss_address_args(p):
    for key in LSS_KEYS:
        p.add_argument(key, type=_u32(key.replace("_", " ")), metavar=key.split("_")[0].upper())


def _network_arg(p, text="the network to talk to (needed when the runtime runs several)"):
    p.add_argument("--network", metavar="NAME", help=text)


# The commands that talk to one network of the plugin (status takes --network
# too, but goes over every network without it).
NETWORK_COMMANDS = ("emcy", "sdo-read", "sdo-write", "nmt", "scan", "lss-find", "lss-inquire", "lss-set-id",
                    "lss-set-bitrate", "trace", "backup", "compare", "restore", "store", "send", "send-stop",
                    "detect-bitrate")


def _int_range(what, lo, hi):
    def parse(t):
        v = _uint(t, what, hi)
        if v < lo:
            raise argparse.ArgumentTypeError("%s must be %d-%d" % (what, lo, hi))
        return v
    return parse


def _rates(text):
    try:
        rates = [int(r) for r in text.replace(" ", "").split(",") if r]
    except ValueError:
        raise argparse.ArgumentTypeError("--rates %r: write kbit/s separated by commas, e.g. 125,250,500" % text)
    bad = [r for r in rates if r not in DETECT_RATES]
    if bad or not rates:
        raise argparse.ArgumentTypeError("--rates takes kbit/s out of %s" % ", ".join(str(r) for r in DETECT_RATES))
    return rates


def parser():
    p = argparse.ArgumentParser(
        prog="openplc-canopen-diag",
        description="Read the live state of the CANopen network from the plugin's diagnostics channel "
                    "(master.diagnostics in canopen.json), and, when the configuration allows changes, write "
                    "objects and send NMT commands.")
    p.add_argument("--runtime", metavar="HOST[:PORT]",
                   help="the runtime host (diagnostics port, default %d); `local` is the local simulator runtime "
                        "of openplc-canopen-sim-runtime" % DEFAULT_PORT)
    p.add_argument("--adapter", metavar="TYPE:CHANNEL",
                   help="talk to the bus through a CAN adapter on this PC instead of a runtime: slcan:COM5, "
                        "slcan:/dev/tty.usbmodem14101, socketcan:can0, ... (see 'adapters' and docs/pc-adapter.md)")
    p.add_argument("--bitrate", type=int, metavar="KBIT",
                   help="--adapter: the bus's bit rate in kbit/s (default: the network's adapter.bitrate from --config)")
    p.add_argument("--adapter-option", action="append", default=[], metavar="KEY=VALUE",
                   help="--adapter: an option passed to python-can (repeatable), e.g. tty_baudrate=115200")
    p.add_argument("--allow-changes", action="store_true",
                   help="--adapter: allow SDO writes, NMT, LSS, restore and store in this session")
    p.add_argument("--force", action="store_true",
                   help="--adapter: run LSS even while another master is active on the bus")
    p.add_argument("--sim", dest="sim_addr", metavar="HOST[:PORT]",
                   help="sim commands: a standalone simulator's control channel (default port 7532)")
    p.add_argument("--token", help="access token (default: $%s, else a prompt)" % TOKEN_ENV)
    p.add_argument("--token-file", metavar="FILE", help="read the access token from this file")
    p.add_argument("--json", action="store_true", help="print the plugin's answer as JSON")
    p.add_argument("--timeout", type=float, default=5.0, metavar="S", help="network timeout (default %(default)s s)")
    p.add_argument("--version", action="version", version="%(prog)s " + __version__)
    sub = p.add_subparsers(dest="command", metavar="COMMAND")
    sub.required = True
    s = sub.add_parser("status", help="master, bus and node states")
    _network_arg(s, "the network to show (default: every network)")
    s.add_argument("--config", metavar="canopen.json", help="--adapter: name the network's nodes from this config")
    e = sub.add_parser("emcy", help="a node's emergency history, newest first")
    e.add_argument("node", type=_node)
    r = sub.add_parser("sdo-read", help="read an object")
    r.add_argument("node", type=_node)
    r.add_argument("index", type=lambda t: _uint(t, "index", 0xFFFF))
    r.add_argument("subindex", type=lambda t: _uint(t, "subindex", 0xFF))
    r.add_argument("--type", type=_type, help="decode the value as this type (default: hex bytes)")
    r.add_argument("--sdo-timeout", type=int, default=1000, metavar="MS", help="SDO timeout (default %(default)s)")
    w = sub.add_parser("sdo-write", help="write an object (needs allow_changes)")
    w.add_argument("node", type=_node)
    w.add_argument("index", type=lambda t: _uint(t, "index", 0xFFFF))
    w.add_argument("subindex", type=lambda t: _uint(t, "subindex", 0xFF))
    w.add_argument("value", help="the value; hex bytes for OCTET_STRING and DOMAIN")
    w.add_argument("--type", type=_type, required=True, help="the object's type")
    w.add_argument("--sdo-timeout", type=int, default=1000, metavar="MS", help="SDO timeout (default %(default)s)")
    n = sub.add_parser("nmt", help="send an NMT command to a configured node (needs allow_changes)")
    n.add_argument("node", type=_node)
    n.add_argument("nmt_command", choices=NMT_COMMANDS, metavar="|".join(NMT_COMMANDS))
    sc = sub.add_parser("scan", help="find the devices on the bus (node IDs 1-127)")
    sc.add_argument("--config", metavar="canopen.json", help="--adapter: compare the devices with this config")
    lf = sub.add_parser("lss-find", help="find a device without a node ID with LSS fastscan (needs allow_changes)")
    lf.add_argument("--vendor", type=_u32("vendor ID"), help="only devices with this vendor ID (needs --product)")
    lf.add_argument("--product", type=_u32("product code"), help="only devices with this product code")
    li = sub.add_parser("lss-inquire", help="a device's node ID, by its LSS address (needs allow_changes)")
    _lss_address_args(li)
    ls = sub.add_parser("lss-set-id", help="give a device a node ID by its LSS address (needs allow_changes)")
    _lss_address_args(ls)
    ls.add_argument("node", type=_node)
    ls.add_argument("--store", action="store_true", help="also store the node ID in the device's memory")
    lb = sub.add_parser("lss-set-bitrate", help="set a device's bit rate for its next power cycle "
                                                "(needs allow_changes)")
    _lss_address_args(lb)
    lb.add_argument("bitrate_kbit", type=int, choices=LSS_BITRATES, metavar="KBIT",
                    help="kbit/s: " + ", ".join(str(b) for b in LSS_BITRATES))
    lb.add_argument("--store", action="store_true", help="also store the bit rate in the device's memory")
    sf = sub.add_parser("send", help="send a CAN frame, once or cyclically (needs allow_changes)",
                        description="Sends one frame, or with --period-ms one every period until --count frames, "
                                    "--duration seconds or Ctrl-C; the job is stopped on exit. Identifiers the "
                                    "network uses, and any frame while a node is OPERATIONAL, need --force.")
    sf.add_argument("id", metavar="ID", help="the identifier, e.g. 0x60A")
    sf.add_argument("data", nargs="*", metavar="DATA",
                    help='0-8 data bytes in hex: "40 18 10 01", 40181001 or 40 18 10 01')
    sf.add_argument("--ext", action="store_true", help="extended (29-bit) identifier")
    sf.add_argument("--rtr", action="store_true", help="a remote frame (no data; give --dlc)")
    sf.add_argument("--dlc", type=_int_range("DLC", 0, 8), metavar="N", help="the remote frame's DLC, 0-8")
    sf.add_argument("--period-ms", type=_int_range("period", 10, 60000), metavar="MS",
                    help="send cyclically at this period (10-60000 ms)")
    sf.add_argument("--count", type=_int_range("count", 1, 1000000), metavar="N",
                    help="cyclic: stop after N frames")
    sf.add_argument("--duration", type=float, metavar="S", help="cyclic: stop after S seconds (default: Ctrl-C)")
    sf.add_argument("--force", action="store_true", default=argparse.SUPPRESS,
                    help="send even when the network uses the identifier or a node is OPERATIONAL")
    sf.add_argument("--config", metavar="canopen.json",
                    help="--adapter: the configured nodes' EMCY, PDO, SDO and heartbeat identifiers need --force")
    ss = sub.add_parser("send-stop", help="stop cyclic send jobs of this connection (for scripts that keep one)")
    ss.add_argument("job", nargs="?", type=_int_range("job", 0, 0xFFFFFFFF), metavar="JOB",
                    help="the job number (default: every job of this connection)")
    db = sub.add_parser("detect-bitrate", help="find the bus's bit rate by listening (needs allow_changes)",
                        description="Stops CANopen on the network, listens in listen-only mode at each bit rate "
                                    "and starts CANopen again; nodes boot again afterwards. Nothing is sent. "
                                    "Exits 0 only when one bit rate was detected.")
    db.add_argument("--rates", type=_rates, metavar="KBIT,...",
                    help="the rates to try, e.g. 125,250,500 (default %s)" % ",".join(str(r) for r in DETECT_RATES))
    db.add_argument("--per-rate-ms", type=_int_range("per-rate time", 100, 10000), metavar="MS",
                    help="how long to listen at each rate (100-10000, default 1000)")
    db.add_argument("--rounds", type=_int_range("rounds", 1, 20), metavar="N",
                    help="sweep N times, for devices that send rarely (1-20, default 1)")
    db.add_argument("--force", action="store_true", default=argparse.SUPPRESS,
                    help="sweep even while a node is OPERATIONAL")
    tr = sub.add_parser("trace", help="record the frames on the bus into a file (read-only)",
                        description="Records every CAN frame on the runtime's CANopen interface (with several "
                                    "networks, the one --network names) until --duration ends, a single-mode "
                                    "trigger has fired and its post-trigger time passed, or Ctrl-C; then writes "
                                    "the file. The format follows the file's extension: .pcapng, .log (candump), "
                                    ".asc, .blf, .trc or .csv.")
    tr.add_argument("-o", "--output", required=True, metavar="FILE", help="the trace file to write")
    tr.add_argument("--format", help="the file format when the extension does not say it")
    tr.add_argument("--duration", type=float, metavar="S", help="stop after S seconds (default: Ctrl-C)")
    tr.add_argument("--filter", action="append", default=[], metavar="ID[/MASK]",
                    help="only frames whose identifier matches (repeatable), e.g. 0x180/0x780")
    tr.add_argument("--error-frames", action="store_true", help="also record CAN error frames")
    tr.add_argument("--config", metavar="canopen.json", help="decode with this config (CSV names, signal triggers)")
    tr.add_argument("--trigger", metavar="CONDITION",
                    help='e.g. "emcy node=23", "frame id=0x197 data=10", "state node=23 state=stopped", '
                         '"signal NAME>3", "bus state=off", "a && b", "a -> b" (see docs/trace.md)')
    tr.add_argument("--mode", choices=("single", "normal"), default="single",
                    help="single: stop after the post-trigger time; normal: mark every hit (default %(default)s)")
    tr.add_argument("--count", type=int, default=1, metavar="N", help="fire on every Nth match")
    tr.add_argument("--pre", type=float, default=5.0, metavar="S", help="pre-trigger time (default %(default)s)")
    tr.add_argument("--post", type=float, default=2.0, metavar="S", help="post-trigger time (default %(default)s)")
    tr.add_argument("--autosave", metavar="FORMAT",
                    help="normal mode: write the pre/post window of each hit next to the output in this format")
    cv = sub.add_parser("convert", help="convert a trace file (no connection)")
    cv.add_argument("input", help=".pcapng, .pcap, .log (candump) or .asc")
    cv.add_argument("output", help=".pcapng, .log, .asc, .blf, .trc or .csv")
    cv.add_argument("--format", help="the output format when the extension does not say it")
    cv.add_argument("--config", metavar="canopen.json", help="decode with this config (CSV)")
    _network_arg(cv, "decode with this network of --config (default: the one the trace file names)")
    def _source(q):
        q.add_argument("--config", metavar="FILE", help="canopen.json naming the node's EDS (default %s when "
                                                        "present)" % os.path.join("canopen", "canopen.json"))
        q.add_argument("--eds", metavar="FILE", help="the node's EDS (for a node not in a configuration)")

    b = sub.add_parser("backup", help="read all parameters of a node into a DCF file")
    b.add_argument("node", type=_node)
    b.add_argument("-o", "--output", metavar="FILE", help="the DCF to write (default node<N>-<name>-<date>-<time>.dcf)")
    _source(b)
    c = sub.add_parser("compare", help="compare a node's values with a backup, the configuration or the EDS defaults")
    c.add_argument("node", type=_node)
    ref = c.add_mutually_exclusive_group(required=True)
    ref.add_argument("--with", dest="with_file", metavar="FILE", help="a backup DCF")
    ref.add_argument("--with-config", action="store_true", help="the values the configuration writes at boot")
    ref.add_argument("--with-eds-defaults", action="store_true", help="the EDS DefaultValues")
    c.add_argument("--read-only", action="store_true", help="also compare read-only entries")
    _source(c)
    rs = sub.add_parser("restore", help="write a backup's values to a node (needs allow_changes; never stores)")
    rs.add_argument("node", type=_node)
    rs.add_argument("file", help="the backup DCF")
    rs.add_argument("--include-comm", action="store_true", help="also restore communication objects 0x1000-0x1FFF")
    rs.add_argument("--hold-preop", action="store_true", help="hold the node in PRE-OPERATIONAL while writing")
    rs.add_argument("--ignore-identity", action="store_true",
                    help="restore even when the vendor ID or product code differs from the backup's")
    rs.add_argument("--dry-run", action="store_true", help="show the plan and write nothing")
    rs.add_argument("--yes", action="store_true", help="do not ask for confirmation")
    _source(rs)
    st = sub.add_parser("store", help="store a node's parameters in its non-volatile memory, 0x1010 "
                                      "(needs allow_changes)")
    st.add_argument("node", type=_node)
    st.add_argument("--subindex", type=lambda t: _uint(t, "subindex", 0xFE), default=1,
                    help="0x1010 sub-index (default 1: all parameters)")
    st.add_argument("--yes", action="store_true", help="do not ask for confirmation")
    _source(st)
    for name in NETWORK_COMMANDS:
        _network_arg(sub.choices[name])
    sub.add_parser("adapters", help="list the CAN adapters on this PC (for --adapter; no connection)")
    h = sub.add_parser("hash-token", help="print the token_verifier for a token (no connection)")
    h.add_argument("value", nargs="?", help="the token (default: --token, $%s or a prompt)" % TOKEN_ENV)
    _sim_parser(sub)
    return p


def _token_file(args):
    path = getattr(args, "token_file", None)
    if not path:
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return f.read().strip()
    except OSError as e:
        raise DiagError("usage", "cannot read the token file %s: %s" % (path, e.strerror or e))


def _token(args, prompt="Diagnostics token: "):
    token = args.token or _token_file(args) or os.environ.get(TOKEN_ENV)
    if token:
        return token
    if not sys.stdin.isatty():
        raise DiagError("token", "give the token with --token or $%s" % TOKEN_ENV)
    return getpass.getpass(prompt)


def network_names(client):
    return [n.get("name") or "" for n in client.networks if isinstance(n, dict)]


def check_network(client, network):
    """Checks --network against the networks the plugin runs: several need
    one, and a name the plugin lists must be among them. An older plugin
    lists none and runs one network, so any name goes there. Raises
    DiagError("network")."""
    names = network_names(client)
    if network is None:
        if client.several():
            raise DiagError("network", "%s runs %d networks (%s); give --network NAME"
                            % (client.where, len(names), ", ".join(names)))
        return
    if any(names) and network not in names:
        raise DiagError("network", "%s runs no network '%s' (%s)" % (client.where, network, ", ".join(names)))


def format_sync(sy):
    """One line for the status answer's SYNC object, or None (plugins before 0.24)."""
    if not sy:
        return None
    src = sy.get("source")
    if src == "none":
        return "SYNC: off"
    if src == "plc_cycle":
        n = sy.get("cycles") or 1
        head = "SYNC: PLC cycle" + ("" if n == 1 else ", every %d cycles" % n)
    else:
        head = "SYNC: timer %s us" % sy.get("period_us")
    line = "%s, %d sent" % (head, sy.get("count") or 0)
    if sy.get("count", 0) > 1:
        line += ", interval %s us (min %s, max %s)" % (sy.get("last_us"), sy.get("min_us"), sy.get("max_us"))
    return line + ", skipped %d, late PDOs %d" % (sy.get("skipped") or 0, sy.get("late_pdos") or 0)


def _print_status(st, out):
    bus = st.get("bus") or {}
    m = st.get("master") or {}
    if not st.get("session", True):
        out.write("no CANopen session: the CAN interface %s is missing or down\n" % (bus.get("interface") or "?"))
    out.write("plugin %s, up %d s, config %s\n" % (st.get("version"), int(st.get("uptime_s") or 0),
                                                   (st.get("config_sha256") or "?")[:12]))
    if st.get("role") == "slave":
        _print_slave_status(st, out)
        return
    line = "bus %s: %s" % (bus.get("interface"), BUS_STATES.get(bus.get("state"), bus.get("state")))
    if "tx_errors" in bus:
        line += ", tx errors %s, rx errors %s, bus-off %s" % (bus.get("tx_errors"), bus.get("rx_errors"),
                                                              bus.get("bus_off_count"))
    out.write(line + "\n")
    out.write("master node %s: %s\n" % (m.get("node_id"), state_name(m.get("state"))))
    sync_line = format_sync(st.get("sync"))
    if sync_line:
        out.write(sync_line + "\n")
    if (st.get("bitrate_sweep") or {}).get("running"):
        out.write("bit rate sweep running: CANopen on this network is paused until it ends\n")
    for j in st.get("send_jobs") or []:
        out.write("send job %s: %s every %s ms, %s sent%s%s\n" % (
            j.get("job"), ("0x%08X" if j.get("ext") else "0x%03X") % (j.get("id") or 0), j.get("period_ms"),
            j.get("sent", 0), " of %s" % j["count"] if j.get("count") else "",
            ", by %s" % j["peer"] if j.get("peer") else ""))
    sim_nodes = [str(nd.get("node_id")) for nd in st.get("nodes") or [] if nd.get("simulated")]
    if st.get("simulation_forced"):
        out.write("simulation forced by the runtime (local simulator runtime): every network runs simulated\n")
    if st.get("simulated_network"):
        out.write("simulated network: no CAN interface is used%s\n"
                  % ("; simulated nodes " + ", ".join(sim_nodes) if sim_nodes else "; no node is simulated"))
    elif sim_nodes:
        out.write("simulated devices on this network: node%s %s\n" % ("s" if len(sim_nodes) > 1 else "",
                                                                     ", ".join(sim_nodes)))
    for nd in st.get("nodes") or []:
        if nd.get("sim_conflict"):
            out.write("node %s: marked simulated, but a device on the bus already uses node ID %s; "
                      "the real device is used\n" % (nd.get("node_id"), nd.get("node_id")))
    rows = [("NODE", "NAME", "STATE", "OK", "BOOT", "HOLD", "LAST EMCY")]
    for nd in st.get("nodes") or []:
        if nd.get("boot_error"):
            boot = "error %s: %s" % (nd["boot_error"], nd.get("boot_error_text") or "")
        else:
            boot = "booted" if nd.get("booted") else "-"
        if nd.get("retry_pending"):
            boot += " (retrying)"
        hold = nd.get("hold") or "none"
        if nd.get("hold_by"):
            hold += " (%s)" % nd["hold_by"]
        em = nd.get("emcy") or {}
        emcy = "-"
        if em.get("count"):
            emcy = "0x%04X %s, reg 0x%02X (%d total)" % (em.get("code", 0), emcy_class(em.get("code", 0)),
                                                        em.get("error_register", 0), em["count"])
        rows.append((str(nd.get("node_id")), nd.get("name") or "", state_name(nd.get("state")),
                     "yes" if nd.get("status") else "no", boot, hold, emcy))
    widths = [max(len(r[i]) for r in rows) for i in range(len(rows[0]) - 1)]
    for r in rows:
        out.write("  ".join(c.ljust(w) for c, w in zip(r, widths)) + "  " + r[-1] + "\n")
    for nd in st.get("nodes") or []:
        for t in nd.get("pdo_timeouts") or []:
            since = t.get("since_ms")
            out.write("node %s TPDO %s: %s (timeout %s ms, %d timeout%s, last PDO %s)\n" % (
                nd.get("node_id"), t.get("tpdo"), "TIMED OUT" if t.get("timed_out") else "receiving",
                t.get("timeout_ms"), t.get("count") or 0, "" if t.get("count") == 1 else "s",
                "never" if since is None else "%d ms ago" % since))
    for nd in st.get("nodes") or []:
        for v in nd.get("sdo_variables") or []:
            line = "node %s %s, %s %s: raw %s, status %s" % (
                nd.get("node_id"), v.get("name"), v.get("type"),
                v.get("direction"), v.get("raw"), v.get("status"))
            if v.get("abort_code"):
                line += ", " + abort_text(v["abort_code"])
            out.write(line + "\n")
    for nd in st.get("nodes") or []:
        if nd.get("interpolation_period_us"):
            out.write("node %s: cyclic synchronous axis, interpolation time period %s us\n"
                      % (nd.get("node_id"), nd["interpolation_period_us"]))


def transmission_text(t):
    """A PDO transmission type in words."""
    if t == 0:
        return "synchronous (acyclic)"
    if isinstance(t, int) and 1 <= t <= 240:
        return "every SYNC" if t == 1 else "every %d SYNCs" % t
    if t in (254, 255):
        return "event (%d)" % t
    return "type %s" % t


def _print_slave_status(st, out):
    """The status of a slave network: the plugin's own device, its PDO
    mappings in force and, on a gateway's upper network, the gateway."""
    bus = st.get("bus") or {}
    s = st.get("slave") or {}
    out.write("bus %s\n" % (bus.get("interface") or "?"))
    nid = s.get("node_id")
    out.write("slave %s: %s, communication %s, SYNC count %s\n" % (
        "node %d" % nid if nid else "waiting for a node ID (LSS)",
        state_name(s.get("state")) if s.get("state") else "not started",
        "OK" if s.get("comm_ok") else "not OK", s.get("sync_count", "-")))
    if "emcy_code" in s:
        code = s.get("emcy_code") or 0
        out.write("EMCY %s, error register 0x%02X\n" % ("0x%04X %s" % (code, emcy_class(code)) if code else "none",
                                                       s.get("error_register") or 0))
    g = st.get("gateway")
    if g:
        out.write("gateway: %d routes, upper master %s, %d forwarded errors active\n" % (
            g.get("routes") or 0, "present" if g.get("upper_ok") else "missing", g.get("forwarded_errors") or 0))
    for key, label in (("tpdos", "TPDO"), ("rpdos", "RPDO")):
        for p in s.get(key) or []:
            cob = p.get("cob_id") or 0
            entries = ", ".join("0x%04X:%d (%d bit%s)" % (e.get("index", 0), e.get("subindex", 0), e.get("bits", 0),
                                                          "" if e.get("bits") == 1 else "s")
                                for e in p.get("entries") or []) or "nothing mapped"
            out.write("%s%d  COB-ID 0x%03X%s, %s: %s\n" % (label, p.get("number"), cob & 0x1FFFFFFF,
                                                       " (off)" if cob & 0x80000000 else "",
                                                       transmission_text(p.get("transmission")), entries))


def _print_scan(res, out):
    out.write("scanned in %.1f s (%s)\n" % (res.get("seconds") or 0, res.get("finished_at") or ""))
    nodes = res.get("nodes") or []
    if not nodes:
        out.write("no device answered\n")
    for nd in nodes:
        parts = ["node %3d" % nd["node_id"]]
        for key, label in (("vendor_id", "vendor"), ("product_code", "product"), ("revision_number", "revision"),
                           ("serial_number", "serial")):
            if key in nd:
                parts.append("%s 0x%08X" % (label, nd[key]))
        if nd.get("device_name"):
            parts.append(repr(nd["device_name"]))
        match = nd.get("match") or ""
        if nd.get("name"):
            match += " as %s" % nd["name"]
        if nd.get("differs"):
            match += " (%s)" % nd["differs"]
        parts.append(match)
        out.write("  ".join(parts) + "\n")
    if res.get("note"):
        out.write("note: %s\n" % res["note"])


def _progress(what):
    def show(done, total):
        if sys.stderr.isatty():
            sys.stderr.write("\r%s %d/%d" % (what, done, total))
            if done == total:
                sys.stderr.write("\r" + " " * 40 + "\r")
    return show


def _confirm(question, out):
    out.write(question + " [y/N] ")
    out.flush()
    answer = sys.stdin.readline().strip().lower()
    return answer in ("y", "yes")


def _parameters(client, args, host, out):
    """backup, compare, restore and store (canopen-device-parameters)."""
    from . import parameters as P
    try:
        ctx = P.node_context(args.node, args.config, args.eds, network=args.network)
    except P.ParameterError as e:
        raise DiagError("usage", str(e))
    node = args.node
    if args.command == "backup":
        boot = None
        st = client.status()
        for nd in (st.get("nodes") or []) if not st.get("local") else ():
            if nd.get("node_id") == node and not nd.get("booted"):
                boot = "not booted"
        reading = P.read_all(client, node, ctx.eds, _progress("reading"))
        text, name = P.build_backup(ctx.eds_text, ctx.eds, ctx.eds_name, reading, ctx.bitrate_kbit, ctx.name,
                                    host, boot_state=boot)
        path = args.output or name
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(text)
        res = {"file": path, "read": len(reading.values), "failed": len(reading.failed), "stopped": reading.stopped,
               "lint": P.lint_backup(text, ctx.eds_text, node)}
        if not args.json:
            out.write("%s: %d entries read, %d not read\n" % (path, len(reading.values), len(reading.failed)))
            for msg in res["lint"]:
                out.write("warning: %s\n" % msg)
        if reading.stopped:
            raise DiagError("refused", reading.stopped)
        return res
    if args.command == "compare":
        if args.with_file:
            with open(args.with_file, "rb") as f:
                reference = P.read_backup(f.read(), args.with_file, node).values
            only = False
        elif args.with_config:
            if not ctx.configured:
                raise DiagError("usage", "--with-config needs the node from a configuration (--config)")
            reference, _ = ctx.config_refs()
            only = True
        else:
            reference = P.reference_from_eds(ctx.eds, node)
            only = False
        keys = P.compare_keys(ctx.eds, reference, args.read_only, only)
        reading = P.read_entries(client, node, keys, _progress("reading"))
        rows = P.compare(ctx.eds, reading, reference, args.read_only, only)
        counts = P.summary(rows)
        res = {"rows": rows, "summary": counts, "stopped": reading.stopped}
        if not args.json:
            for r in rows:
                if r["result"] == "equal":
                    continue
                line = "0x%04X sub %-3d %-11s %s" % (r["index"], r["subindex"], r["result"], r["name"])
                if r["result"] == "different":
                    line += ": reference %s, device %s" % (r["reference"], r["device"])
                elif r["result"] == "not readable":
                    line += ": " + r["error"]
                out.write(line + "\n")
            out.write("%d equal, %d different, %d not readable, %d without a reference\n"
                      % (counts["equal"], counts["different"], counts["not readable"], counts["no reference"]))
        if reading.stopped:
            raise DiagError("refused", reading.stopped)
        if counts["not readable"]:
            raise DiagError("refused", "%d entries could not be read" % counts["not readable"])
        return res
    if args.command == "restore":
        with open(args.file, "rb") as f:
            backup = P.read_backup(f.read(), args.file, node)
        config, owned = ctx.config_refs()
        keys = P.plan_keys(backup, ctx.eds, args.include_comm, config, owned)
        live = P.read_entries(client, node, keys, _progress("reading"))
        if live.stopped:
            raise DiagError("refused", live.stopped)
        plan = P.restore_plan(backup, ctx.eds, live, args.include_comm, config, owned, args.ignore_identity)
        if not args.json or args.dry_run:
            for i in plan.identity:
                out.write("%s: %s\n" % (i["level"], i["text"]))
            for w in plan.writes:
                out.write("write 0x%04X sub %-3d %s: %s (device %s)\n" % (
                    w["index"], w["subindex"], w["name"], w["backup"],
                    w["device"] if w["device"] is not None else "not readable"))
            for sk in plan.skipped:
                out.write("skip  0x%04X sub %-3d %s: %s\n" % (sk["index"], sk["subindex"], sk["name"], sk["reason"]))
            out.write("%d to write, %d unchanged, %d skipped\n" % (len(plan.writes), len(plan.unchanged),
                                                                   len(plan.skipped)))
            if not ctx.configured:
                out.write("note: no configuration given, so entries the configuration writes at boot are not "
                          "left out\n")
        if plan.refused:
            raise DiagError("refused", "restore refused: %s (--ignore-identity restores anyway)" % plan.refused)
        if args.dry_run:
            return plan.to_json()
        if not plan.writes:
            out.write("nothing to write\n")
            return plan.to_json()
        if not client.info.get("allow_changes", True):
            raise DiagError("refused", "changes not allowed")
        if not args.yes and not _confirm("write %d values to node %d%s?" % (
                len(plan.writes), node, " holding it in PRE-OPERATIONAL" if args.hold_preop else ""), out):
            raise DiagError("refused", "not confirmed; nothing written")
        res = P.restore(client, node, plan, args.hold_preop, _progress("writing"))
        if not args.json:
            for fl in res["failed"]:
                out.write("failed 0x%04X sub %d %s: %s\n" % (fl["index"], fl["subindex"], fl["name"], fl["error"]))
            out.write("%d written, %d failed\n%s\n" % (len(res["written"]), len(res["failed"]), res["note"]))
            if res["released"] is False:
                out.write("warning: node %d is still held in PRE-OPERATIONAL: %s; release it with "
                          "'nmt %d start'\n" % (node, res.get("release_error"), node))
        if res["failed"]:
            raise DiagError("refused", "%d values could not be written" % len(res["failed"]))
        return res
    # store
    if not ctx.eds.has(0x1010):
        raise DiagError("refused", "node %d's EDS has no object 0x1010: the device has no store object" % node)
    if not args.yes and not _confirm("store node %d's parameters in its non-volatile memory (0x1010 sub %d)?"
                                     % (node, args.subindex), out):
        raise DiagError("refused", "not confirmed; nothing written")
    try:
        res = P.store(client, node, ctx.eds, args.subindex)
    except P.ParameterError as e:
        raise DiagError("refused", str(e))
    if not res["stored"]:
        raise DiagError("refused", "node %d did not store: %s" % (node, res["error"]))
    if not args.json:
        out.write("node %d: stored (0x1010 sub %d)\n" % (node, args.subindex))
    return res


def _local_client(args):
    """A localbus.LocalBus for --adapter: the bit rate from --bitrate or the
    network of --config, the configured nodes' names from --config."""
    from . import localbus
    from .localbus import configinfo
    try:
        spec = localbus.parse(args.adapter, args.adapter_option)
    except localbus.AdapterError as e:
        raise DiagError("usage", str(e))
    bitrate = args.bitrate * 1000 if args.bitrate else None
    nodes = {}
    config = getattr(args, "config", None)
    if config:
        try:
            cfg_bitrate, nodes = configinfo.load(config, args.network)
        except (OSError, ValueError) as e:
            raise DiagError("usage", "cannot use %s: %s" % (config, e))
        bitrate = bitrate or cfg_bitrate
    if not bitrate:
        raise DiagError("usage", "give the bus's bit rate with --bitrate KBIT (or --config with the network's "
                                 "adapter.bitrate); a wrong bit rate disturbs the bus, so there is no default")
    if localbus.untested(spec):
        print("openplc-canopen-diag: adapter type %s is passed to python-can untested" % spec.kind, file=sys.stderr)
    return localbus.LocalBus(spec, bitrate, allow_changes=args.allow_changes, force=args.force, config=nodes,
                             network=args.network, timeout=args.timeout)


def _adapters(args, out):
    from . import localbus
    found = localbus.list_adapters()
    if args.json:
        out.write(json.dumps(found, indent=2) + "\n")
        return 0
    if not found:
        out.write("no CAN adapter found (plug one in; an slcan adapter shows as a serial port)\n")
    for a in found:
        line = "--adapter %s" % a["text"]
        if a.get("known"):
            line += "  %s" % a["known"]
        elif a.get("description"):
            line += "  %s" % a["description"]
        if a.get("usb_id"):
            line += " [USB %s]" % a["usb_id"]
        out.write(line + "\n")
    return 0


def _print_local_status(st, out):
    """The status of a local adapter: what the bus showed since connecting."""
    out.write("adapter %s, %d kbit/s, %s, connected %d s\n" % (
        st.get("adapter"), (st.get("bitrate") or 0) // 1000,
        "changes allowed" if st.get("allow_changes") else "read-only", int(st.get("uptime_s") or 0)))
    if st.get("untested_adapter"):
        out.write("note: this adapter type is untested\n")
    other = st.get("other_master_seen")
    if other:
        out.write("another master is active on this bus: %s (since %s, last %s)\n"
                  % (other.get("what"), other.get("first_at"), other.get("last_at")))
    nodes = st.get("nodes") or []
    if not nodes:
        out.write("no node heard yet (a node without heartbeat shows up in a scan)\n")
        return
    rows = [("NODE", "NAME", "STATE", "HEARD", "LAST EMCY")]
    for nd in nodes:
        heard = "-" if nd.get("last_heard_s") is None else "%.1f s ago" % nd["last_heard_s"]
        em = nd.get("emcy") or {}
        emcy = "-"
        if em.get("count"):
            emcy = "0x%04X %s, reg 0x%02X (%d total)" % (em.get("code", 0), emcy_class(em.get("code", 0)),
                                                        em.get("error_register", 0), em["count"])
        state = "-" if nd.get("state") is None else state_name(nd.get("state"))
        rows.append((str(nd.get("node_id")), nd.get("name") or "", state, heard, emcy))
    widths = [max(len(r[i]) for r in rows) for i in range(len(rows[0]) - 1)]
    for r in rows:
        out.write("  ".join(c.ljust(w) for c, w in zip(r, widths)) + "  " + r[-1] + "\n")


def _stopped_text(s):
    return "job %s: %d frame%s sent, %s" % (s.get("job"), s.get("sent") or 0, "" if s.get("sent") == 1 else "s",
                                             s.get("reason") or "ended")


def _send(client, args, out):
    """send: one frame, or a cyclic job kept until --count, --duration or
    Ctrl-C and always stopped on the way out."""
    cyclic = args.period_ms is not None
    if args.rtr and args.data:
        raise DiagError("usage", "a remote frame (--rtr) carries no data; give its length with --dlc")
    if args.dlc is not None and not args.rtr:
        raise DiagError("usage", "--dlc is for remote frames (--rtr); a data frame's length is its data")
    if not cyclic and (args.count is not None or args.duration is not None):
        raise DiagError("usage", "--count and --duration are for cyclic sending (--period-ms)")
    try:
        can_id = parse_frame_id(args.id, args.ext)
        data = parse_frame_data(args.data)
    except ValueError as e:
        raise DiagError("usage", str(e))
    text = frame_text(can_id, args.ext, args.rtr, args.dlc, data)
    try:
        res = client.send_frame(can_id, data, args.ext, args.rtr, args.dlc, args.period_ms, args.count, args.force)
    except DiagError as e:
        if needs_force(e):
            raise DiagError("refused", "%s; add --force to send it anyway" % e)
        raise
    if not cyclic:
        if not args.json:
            out.write("sent %s%s\n" % (text, " (forced)" if args.force else ""))
        return res
    job = res.get("job")
    if not args.json:
        out.write("job %s: sending %s every %d ms%s; Ctrl-C stops\n" % (
            job, text, args.period_ms, ", %d frames" % args.count if args.count else ""))
        out.flush()
    started = time.monotonic()
    # With a count the plugin ends the job itself; wait a little longer than it takes.
    limit = args.duration
    if args.count:
        need = args.count * args.period_ms / 1000.0 + 2.0
        limit = need if limit is None else min(limit, need)
    sent = None
    try:
        while limit is None or time.monotonic() - started < limit:
            time.sleep(0.5)
            st = client.status()
            if "send_jobs" not in st:
                continue  # a plugin that does not list jobs: wait for the time
            mine = [j for j in st["send_jobs"] if j.get("job") == job]
            if not mine or mine[0].get("reason"):
                break  # ended by the plugin (count reached, transmit error, time limit)
            sent = mine[0].get("sent")
            if not args.json and sys.stderr.isatty():
                sys.stderr.write("\rjob %s: %s sent, %.0f s " % (job, sent, time.monotonic() - started))
    except KeyboardInterrupt:
        pass
    finally:
        if not args.json and sys.stderr.isatty():
            sys.stderr.write("\r" + " " * 40 + "\r")
        stopped = client.send_frame_stop(job).get("stopped") or []
    ended = next((s for s in stopped if s.get("job") == job), None) or {"job": job, "sent": sent, "reason": "ended"}
    if not args.json:
        out.write(_stopped_text(ended) + "\n")
    if ended.get("reason") not in ("stopped", "count reached"):
        if args.json:
            out.write(json.dumps({"job": job, "stopped": stopped}, indent=2) + "\n")
        raise DiagError("refused", "job %s ended early: %s" % (job, ended.get("reason") or "ended"))
    return {"job": job, "stopped": stopped}


def _send_stop(client, args, out):
    res = client.send_frame_stop(args.job)
    if not args.json:
        stopped = res.get("stopped") or []
        for s in stopped:
            out.write(_stopped_text(s) + "\n")
        if not stopped:
            out.write("no job of this connection was running\n")
    return res


def _print_sweep(res, out):
    rows = [("RATE", "FRAMES", "ERROR FRAMES", "IDENTIFIERS")]
    for r in res.get("results") or []:
        ids = r.get("ids") or []
        text = " ".join("0x%X" % i for i in ids) + (" ..." if len(ids) >= 16 else "")
        rows.append(("%s kbit/s" % r.get("bitrate_kbit"), str(r.get("frames", 0)), str(r.get("error_frames", 0)),
                     text or "-"))
    widths = [max(len(r[i]) for r in rows) for i in range(3)]
    for r in rows:
        out.write("  ".join(c.rjust(w) if i else c.ljust(w) for i, (c, w) in enumerate(zip(r, widths))) + "  " +
                  r[3] + "\n")


def _detect(client, args, out):
    """detect-bitrate: starts the sweep, follows it, prints the table and the
    verdict; exits 0 only when one rate was detected."""
    try:
        res = client.detect_bitrate(args.rates, args.per_rate_ms, args.rounds, args.force)
    except DiagError as e:
        if needs_force(e):
            raise DiagError("refused", "%s; add --force to stop CANopen on this network for the sweep" % e)
        raise
    shown = 0
    while True:
        if not args.json and sys.stderr.isatty():
            for r in (res.get("results") or [])[shown:]:
                sys.stderr.write("\r%s kbit/s: %d frames, %d error frames%s\n" % (
                    r.get("bitrate_kbit"), r.get("frames", 0), r.get("error_frames", 0), " " * 10))
            shown = len(res.get("results") or [])
            if res.get("running"):
                sys.stderr.write("\rlistening at %s kbit/s (%s/%s)%s " % (
                    res.get("rate_kbit"), res.get("done"), res.get("total"),
                    ", round %s" % res["round"] if (args.rounds or 1) > 1 and res.get("round") else ""))
        if not res.get("running"):
            break
        time.sleep(0.3)
        res = client.detect_bitrate_status()
    if not args.json and sys.stderr.isatty():
        sys.stderr.write("\r" + " " * 50 + "\r")
    if not args.json:
        _print_sweep(res, out)
        if skipped_text(res):
            out.write(skipped_text(res) + "\n")
        out.write(verdict_text(res) + "\n")
    if res.get("verdict") != "detected":
        if args.json:
            out.write(json.dumps(res, indent=2) + "\n")
        raise DiagError("refused", "no bit rate detected (%s)" % (res.get("verdict") or "no result"))
    return res


def run(args, out=sys.stdout):
    if args.command == "hash-token":
        token = args.value or args.token or os.environ.get(TOKEN_ENV)
        if not token:
            token = getpass.getpass("Token: ")
        out.write(token_verifier(token) + "\n")
        return 0
    if args.command == "convert":
        return _convert(args, out)
    if args.command == "adapters":
        return _adapters(args, out)
    if getattr(args, "adapter", None) and (args.runtime or args.command == "sim"):
        raise DiagError("usage", "--adapter talks to the bus directly; give either --adapter or --runtime, not both"
                        if args.runtime else "sim commands need a runtime or a standalone simulator, not --adapter")
    if args.command == "sim":
        from . import simcli
        return simcli.run(args, out)
    if not args.runtime and not getattr(args, "adapter", None):
        raise DiagError("usage", "give --runtime HOST[:PORT], or --adapter TYPE:CHANNEL for a CAN adapter on this PC")
    if args.command == "trace":
        return _trace(args, out)
    if args.adapter:
        client = _local_client(args)
        host = str(client.spec)
    else:
        try:
            host, port = parse_runtime(args.runtime)
        except ValueError as e:
            raise DiagError("usage", str(e))
        client = Client(host, port, _token(args), args.timeout, network=args.network)
    client.connect()
    try:
        all_networks = args.command == "status" and not args.network and client.several()
        if not all_networks:
            check_network(client, args.network)
        if all_networks:
            # Every network, one after another, each headed by its name.
            res = []
            for i, net in enumerate(client.networks):
                st = client.request("status", network=net.get("name"))
                res.append(st)
                if not args.json:
                    out.write("%snetwork %s (%s)\n" % ("\n" if i else "", net.get("name"),
                                                       net.get("interface") or "no interface"))
                    _print_status(st, out)
            if args.json:
                res = {"networks": res}
        elif args.command == "status":
            res = client.status()
            if not args.json:
                (_print_local_status if res.get("local") else _print_status)(res, out)
        elif args.command == "emcy":
            res = client.emcy(args.node)
            if not args.json:
                hist = res.get("emcy") or []
                if not hist:
                    out.write("node %d has sent no EMCY since the plugin started\n" % args.node)
                for e in hist:
                    out.write("%s  0x%04X  %-22s register 0x%02X  manufacturer %s\n" % (
                        e["time"], e["code"], emcy_class(e["code"]), e["error_register"], e.get("manufacturer", "")))
        elif args.command == "scan":
            res = client.scan(True)
            while res.get("running"):
                if not args.json and sys.stderr.isatty():
                    sys.stderr.write("\rscanning %s/%s" % (res.get("done"), res.get("total")))
                time.sleep(0.25)
                res = client.scan(False)
            if not args.json and sys.stderr.isatty():
                sys.stderr.write("\r" + " " * 30 + "\r")
            if not args.json:
                _print_scan(res, out)
        elif args.command == "lss-find":
            if (args.vendor is None) != (args.product is None):
                raise DiagError("usage", "give --vendor and --product together")
            res = client.lss_find(True, args.vendor, args.product)
            while res.get("running"):
                if not args.json and sys.stderr.isatty():
                    sys.stderr.write("\rsearching %.0f s" % (res.get("seconds") or 0))
                time.sleep(0.25)
                res = client.lss_find(False)
            if not args.json and sys.stderr.isatty():
                sys.stderr.write("\r" + " " * 30 + "\r")
            if res.get("error"):
                if args.json:
                    out.write(json.dumps(res, indent=2) + "\n")
                raise DiagError("refused", "LSS search failed: %s" % res["error"])
            if not args.json:
                dev = res.get("device")
                if not res.get("found") or not dev:
                    out.write("no device without a node ID answered (%.1f s)\n" % (res.get("seconds") or 0))
                else:
                    nid = dev.get("node_id")
                    out.write("found %s, %s (%.1f s)\n" % (
                        lss_address_text(dev), "no node ID" if nid in (None, 255) else "node ID %d" % nid,
                        res.get("seconds") or 0))
        elif args.command in ("lss-inquire", "lss-set-id", "lss-set-bitrate"):
            addr = tuple(getattr(args, k) for k in LSS_KEYS)
            if args.command == "lss-inquire":
                res = client.lss_inquire(addr)
                if not args.json:
                    nid = res.get("node_id")
                    out.write("%s: %s\n" % (lss_address_text(addr),
                                            "no node ID" if nid == 255 else "node ID %s" % nid))
            elif args.command == "lss-set-id":
                res = client.lss_set_id(addr, args.node, args.store)
                if not args.json:
                    out.write("node ID %d set%s; %s\n" % (args.node, ", stored" if res.get("stored") else "",
                                                          res.get("note", "")))
            else:
                res = client.lss_set_bitrate(addr, args.bitrate_kbit, args.store)
                if not args.json:
                    out.write("bit rate %d kbit/s set%s; %s\n" % (args.bitrate_kbit,
                                                                  ", stored" if res.get("stored") else "",
                                                                  res.get("note", "")))
        elif args.command in ("backup", "compare", "restore", "store"):
            res = _parameters(client, args, host, out)
        elif args.command in ("send", "send-stop", "detect-bitrate"):
            try:
                res = {"send": _send, "send-stop": _send_stop, "detect-bitrate": _detect}[args.command](
                    client, args, out)
            except DiagError as e:
                if too_old(e):
                    raise DiagError("refused", TOO_OLD)
                raise
        elif args.command == "nmt":
            res = client.nmt(args.node, args.nmt_command)
            if not args.json:
                out.write("node %d: %s sent%s\n" % (args.node, args.nmt_command,
                                                     "; " + res["note"] if res.get("note") else ""))
        else:
            if args.command == "sdo-read":
                res = client.sdo_read(args.node, args.index, args.subindex, args.sdo_timeout)
            else:
                try:
                    data = encode(args.type, args.value)
                except ValueError as e:
                    raise DiagError("usage", str(e))
                res = client.sdo_write(args.node, args.index, args.subindex, data, args.sdo_timeout)
            if not res.get("success"):
                if args.json:
                    out.write(json.dumps(res, indent=2) + "\n")
                raise DiagError("refused", "node %d 0x%04X:%d: %s" % (args.node, args.index, args.subindex,
                                                                       sdo_failure(res)))
            if not args.json:
                if args.command == "sdo-read":
                    data = parse_hex(res.get("data", "")) if res.get("data") else b""
                    out.write(decode(args.type, data)["text"] + "\n")
                else:
                    out.write("written\n")
        if args.json:
            out.write(json.dumps(res, indent=2) + "\n")
    finally:
        client.close()
    return 0


def _filter(text):
    try:
        if "/" in text:
            i, m = text.split("/", 1)
            return int(i, 0) & 0x1FFFFFFF, int(m, 0) & 0x1FFFFFFF
        return int(text, 0) & 0x1FFFFFFF, 0x1FFFFFFF
    except ValueError:
        raise DiagError("usage", "--filter %r: write ID or ID/MASK, e.g. 0x180/0x780" % text)


def _decoder(config, network=None, default=None):
    """A decoder with the nodes of `network` in the config (a trace records
    one network). `default` is the network for a config with several when
    `network` is None: the one the trace or the plugin names."""
    from . import contract
    from .bustrace.decode import Decoder
    if not config:
        return Decoder()
    try:
        with open(config, encoding="utf-8") as f:
            cfg = json.load(f)
    except (OSError, ValueError) as e:
        raise DiagError("usage", "cannot read %s: %s" % (config, e))
    if network is None and len(contract.networks(cfg)) > 1:
        network = default
    try:
        contract.network_config(cfg, network)
    except ValueError as e:
        raise DiagError("network", "%s: %s%s" % (config, e, " with --network NAME" if network is None else ""))
    dec = Decoder.from_config(cfg, config, network=network)
    for w in dec.warnings:
        print("openplc-canopen-diag: %s" % w, file=sys.stderr)
    return dec


def _convert(args, out):
    from .bustrace import formats
    try:
        trace = formats.read_file(args.input)
        decoder = _decoder(args.config, args.network, trace.meta.get("network"))
        fmt = formats.write_file(trace, args.output, args.format, decoder)
    except (OSError, formats.FormatError) as e:
        raise DiagError("usage", str(e))
    out.write("%d frames written to %s (%s)\n" % (sum(1 for f in trace if not f.gap), args.output, fmt))
    return 0


def _trace(args, out):
    from .bustrace import formats, triggers
    try:
        fmt = formats.format_of(args.output, args.format)
    except formats.FormatError as e:
        raise DiagError("usage", str(e))
    filters = [_filter(f) for f in args.filter]
    spec = None
    if args.trigger:
        autosave = None
        if args.autosave:
            try:
                formats.format_of("x", args.autosave)
            except formats.FormatError as e:
                raise DiagError("usage", str(e))
            autosave = {"format": args.autosave, "folder": os.path.dirname(os.path.abspath(args.output))}
        try:
            spec = triggers.parse(args.trigger, mode=args.mode, count=args.count, pre_s=args.pre, post_s=args.post,
                                  autosave=autosave)
        except triggers.TriggerError as e:
            raise DiagError("usage", "--trigger: %s" % e)
    if args.adapter:
        # The adapter stays open for the whole recording: the recorder's
        # connections are handles on it, and reopening an slcan port is slow.
        first = _local_client(args)
        first.connect()

        def connect():
            c = _local_client(args)
            c.connect()
            return c
        names = network_names(first)
    else:
        host, port = parse_runtime(args.runtime)
        token = _token(args)

        def connect():
            c = Client(host, port, token, args.timeout, network=args.network)
            c.connect()
            return c

        # Fail early on a wrong host, token or network instead of retrying.
        first = connect()
        try:
            check_network(first, args.network)
            names = network_names(first)
        finally:
            first.close()
    try:
        return _record(args, out, fmt, filters, spec, connect, names)
    finally:
        if args.adapter:
            first.close()


def _record(args, out, fmt, filters, spec, connect, names):
    from .bustrace import formats, triggers
    from .bustrace.recorder import Recorder, Session
    # The traced network's nodes decode its frames; without --network that is
    # the plugin's only network.
    network = args.network or (names[0] if len(names) == 1 and names[0] else None)
    decoder = _decoder(args.config, args.network, network)
    if spec:
        try:
            triggers.resolve_signals(spec, decoder.signal_keys())
        except triggers.TriggerError as e:
            raise DiagError("usage", "--trigger: %s" % e)
    session = Session(decoder)
    session.trace.meta["runtime"] = args.runtime or args.adapter
    if network:
        session.trace.meta["network"] = network
    prefix = os.path.splitext(os.path.basename(args.output))[0]
    rec = Recorder(connect, session, filters, args.error_frames, spec, name_prefix=prefix)
    started = time.monotonic()
    rec.start()
    interrupted = False
    try:
        while rec.running:
            if args.duration is not None and time.monotonic() - started >= args.duration:
                break
            if sys.stderr.isatty():
                sys.stderr.write("\rrecording: %d frames%s " % (len(session.trace),
                                                                 ", %s" % rec.state if rec.state != "recording" else ""))
            time.sleep(0.25)
    except KeyboardInterrupt:
        interrupted = True
    rec.stop()
    if sys.stderr.isatty():
        sys.stderr.write("\r" + " " * 40 + "\r")
    info = rec.info()
    if info["state"] == "error" and not len(session.trace):
        raise DiagError("refused", info["message"])
    with session.lock:
        try:
            formats.write_file(session.trace, args.output, fmt, session.decoder if fmt == "csv" else None)
        except OSError as e:
            raise DiagError("usage", "cannot write %s: %s" % (args.output, e.strerror or e))
        summary = session.analysis.summary(info["lost"], info["kernel_drops"])
    seconds = ((summary["last_us"] or 0) - (summary["first_us"] or 0)) / 1e6
    rate = summary["frames"] / seconds if seconds > 0 else 0.0
    out.write("%d frames in %.1f s (%.0f frames/s), %d lost, %d dropped by the PLC's kernel%s -> %s\n" % (
        summary["frames"], seconds, rate, summary["lost"], summary["kernel_drops"],
        ", %d error frames" % summary["error_frames"] if summary["error_frames"] else "", args.output))
    if spec:
        hits = info["hits"]
        out.write("trigger %s: %s\n" % (triggers.describe(rec.engine.spec),
                                        "%d hit(s)" % len(hits) if hits else "did not fire"))
        for p in info["saved"]:
            out.write("saved %s\n" % p)
    if info["state"] == "error":
        out.write("stopped: %s\n" % info["message"])
    del interrupted
    return 0


def _sim_parser(sub):
    from . import simcli
    simcli.add_parser(sub)


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        return run(args, sys.stdout)
    except DiagError as e:
        print("openplc-canopen-diag: %s" % e, file=sys.stderr)
        if args.command == "sim" and getattr(args, "sim_command", None) == "test":
            return 2  # a test run that could not start
        return 2 if e.kind == "usage" else 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
