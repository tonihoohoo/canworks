"""Frames built for explanation, never sent (canopen-frame-explain: "Frame
builder"; design D6).

Every builder returns [{"label", "frame"}] with model.Frame objects; values
are checked against their types and a bad value raises BuildError naming
the field. examples() makes example frames from a configuration's decoder.
"""

import struct

from .. import diag
from .decode import Decoder
from .model import Frame

NMT = {"start": 0x01, "stop": 0x02, "preop": 0x80, "reset": 0x81, "reset-comm": 0x82}
STATES = {"boot-up": 0, "stopped": 4, "operational": 5, "preop": 127}


class BuildError(ValueError):
    def __init__(self, field, message):
        super().__init__("%s: %s" % (field, message) if field else message)
        self.field, self.message = field, message


def _node(n):
    try:
        n = int(n, 0) if isinstance(n, str) else int(n)
    except (TypeError, ValueError):
        raise BuildError("node", "a node ID is a number 1-127")
    if not 1 <= n <= 127:
        raise BuildError("node", "a node ID is 1-127")
    return n


def _uint(v, field, top):
    try:
        n = int(v, 0) if isinstance(v, str) else int(v)
    except (TypeError, ValueError):
        raise BuildError(field, "%r is not a number" % (v,))
    if not 0 <= n <= top:
        raise BuildError(field, "out of range 0 to %d" % top)
    return n


def _f(can_id, data=b"", **kw):
    return Frame(0, can_id, bytes(data), **kw)


def nmt(command, node=0):
    cmd = NMT.get(command, command)
    cmd = _uint(cmd, "command", 0xFF)
    target = 0 if node in (0, "0", None, "") else _node(node)
    return [{"label": "NMT %s" % command, "frame": _f(0x000, bytes([cmd, target]))}]


def heartbeat(node, state="operational"):
    n = _node(node)
    st = STATES.get(state, state)
    st = _uint(st, "state", 0x7F)
    return [{"label": "Heartbeat of node %d" % n, "frame": _f(0x700 + n, bytes([st]))}]


def emcy(node, code=0x1000, register=0x01, manufacturer=""):
    n = _node(node)
    code = _uint(code, "error code", 0xFFFF)
    reg = _uint(register, "error register", 0xFF)
    try:
        mfr = diag.parse_hex(manufacturer) if str(manufacturer or "").strip() else b""
    except ValueError as e:
        raise BuildError("manufacturer data", str(e))
    if len(mfr) > 5:
        raise BuildError("manufacturer data", "at most 5 bytes")
    data = code.to_bytes(2, "little") + bytes([reg]) + mfr.ljust(5, b"\0")
    return [{"label": "EMCY of node %d" % n, "frame": _f(0x080 + n, data)}]


def _type_of(dec, node, index, sub, type_name):
    t = diag.type_name(type_name) if type_name else dec.object_type(node, index, sub)
    if type_name and not t:
        raise BuildError("type", "unknown type %r" % type_name)
    return t


def _encode(t, value):
    if value is None or str(value).strip() == "":
        raise BuildError("value", "give a value")
    try:
        return diag.encode(t, value)
    except ValueError as e:
        raise BuildError("value", str(e))


def _segments(data):
    return [data[k:k + 7] for k in range(0, len(data), 7)] or [b""]


def sdo(dec, node, index, sub, op="read", value=None, type_name=None, segmented=None):
    """An SDO read or write with its answers. Values of up to 4 bytes go
    expedited unless segmented=True; longer ones always in segments."""
    dec = dec or Decoder()
    n = _node(node)
    index = _uint(index, "index", 0xFFFF)
    sub = _uint(sub, "subindex", 0xFF)
    if op not in ("read", "write"):
        raise BuildError("operation", "read or write")
    t = _type_of(dec, n, index, sub, type_name)
    mux = index.to_bytes(2, "little") + bytes([sub])
    req, ans = 0x600 + n, 0x580 + n
    what = "%04Xh:%02X" % (index, sub)
    if op == "read" and (value is None or str(value).strip() == ""):
        value = _default(dec, n, index, sub, t)
    data = _encode(t, value) if t else _encode(None, value)
    out = []
    expedited = len(data) <= 4 and not segmented
    if op == "read":
        out.append({"label": "read request %s" % what, "frame": _f(req, bytes([0x40]) + mux + bytes(4))})
        if expedited:
            nfree = 4 - len(data)
            out.append({"label": "read answer", "frame": _f(ans, bytes([0x43 | nfree << 2]) + mux + data.ljust(4, b"\0"))})
            return out
        out.append({"label": "read answer, size", "frame": _f(ans, bytes([0x41]) + mux + len(data).to_bytes(4, "little"))})
        for k, seg in enumerate(_segments(data)):
            last = k == len(_segments(data)) - 1
            t_bit = (k & 1) << 4
            out.append({"label": "segment %d request" % (k + 1), "frame": _f(req, bytes([0x60 | t_bit]) + bytes(7))})
            out.append({"label": "segment %d" % (k + 1), "frame": _f(
                ans, bytes([t_bit | (7 - len(seg)) << 1 | (1 if last else 0)]) + seg.ljust(7, b"\0"))})
        return out
    if expedited:
        nfree = 4 - len(data)
        out.append({"label": "write %s" % what, "frame": _f(req, bytes([0x23 | nfree << 2]) + mux + data.ljust(4, b"\0"))})
        out.append({"label": "write confirmed", "frame": _f(ans, bytes([0x60]) + mux + bytes(4))})
        return out
    out.append({"label": "write %s, size" % what, "frame": _f(req, bytes([0x21]) + mux + len(data).to_bytes(4, "little"))})
    out.append({"label": "write accepted", "frame": _f(ans, bytes([0x60]) + mux + bytes(4))})
    segs = _segments(data)
    for k, seg in enumerate(segs):
        last = k == len(segs) - 1
        t_bit = (k & 1) << 4
        out.append({"label": "segment %d" % (k + 1), "frame": _f(
            req, bytes([t_bit | (7 - len(seg)) << 1 | (1 if last else 0)]) + seg.ljust(7, b"\0"))})
        out.append({"label": "segment %d confirmed" % (k + 1), "frame": _f(ans, bytes([0x20 | t_bit]) + bytes(7))})
    return out


def _default(dec, node, index, sub, t):
    eds = dec.eds.get(node)
    obj = eds.find(index, sub) if eds is not None else None
    if obj is not None:
        try:
            v = obj.value(node)
        except Exception:  # noqa: BLE001 - a default with $NODEID arithmetic the EDS module cannot read
            v = None
        if v is not None:
            if isinstance(v, (bytes, bytearray)):
                return v.hex()
            return str(v)
    if t in ("VISIBLE_STRING", "UNICODE_STRING"):
        return "example"
    if t in ("OCTET_STRING", "DOMAIN") or not t:
        return "00"
    return "0"


def _signal_lookup(p, key):
    for k, (skey, name, *_), in zip(range(len(p.signals)), p.signals):
        info = p.info[k] if k < len(p.info) else {}
        names = [skey, name, info.get("location")] + list(info.get("variables") or [])
        if key in names or str(key).lower() in [str(n).lower() for n in names if n]:
            return k
    return None


def pdo(dec, cob_id, values):
    """A configured PDO with a value per signal ({signal key, name, PLC
    location or variable: value}); signals not given are 0."""
    cob_id = _uint(cob_id, "COB-ID", 0x7FF)
    p = dec.pdos.get(cob_id)
    if p is None:
        raise BuildError("PDO", "0x%03X is not a configured PDO" % cob_id)
    raw = 0
    given = {}
    for key, v in (values or {}).items():
        k = _signal_lookup(p, key)
        if k is None:
            raise BuildError(str(key), "not a signal of %s" % p.name)
        given[k] = v
    for k, (skey, name, start, length, signed, fk, tname) in enumerate(p.signals):
        v = given.get(k, 0)
        bits = _signal_bits(name, v, length, signed, fk, tname)
        raw |= bits << start
    nbytes = p.length or max(((s[2] + s[3] + 7) // 8 for s in p.signals), default=0)
    return [{"label": p.name, "frame": _f(cob_id, raw.to_bytes(8, "little")[:nbytes])}]


def _signal_bits(name, v, length, signed, fk, tname):
    if fk:
        try:
            x = float(v)
        except (TypeError, ValueError):
            raise BuildError(name, "%r is not a number" % (v,))
        try:
            b = struct.pack("<f" if fk == 1 else "<d", x)
        except OverflowError:
            raise BuildError(name, "out of range for %s" % tname)
        return int.from_bytes(b, "little")
    if tname == "BOOLEAN" and str(v).strip().lower() in ("true", "false", "on", "off"):
        v = 1 if str(v).strip().lower() in ("true", "on") else 0
    try:
        x = int(v, 0) if isinstance(v, str) else int(v)
    except (TypeError, ValueError):
        raise BuildError(name, "%r is not an integer" % (v,))
    lo, hi = (-(1 << (length - 1)), (1 << (length - 1)) - 1) if signed else (0, (1 << length) - 1)
    if not lo <= x <= hi:
        raise BuildError(name, "out of range %d to %d" % (lo, hi))
    return x & ((1 << length) - 1)


def examples(dec):
    """Example frames from a configuration: [{"group", "label", "frames"}]."""
    out = [{"group": "Network", "label": "NMT start all nodes", "frames": nmt("start", 0)},
           {"group": "Network", "label": "SYNC", "frames": [{"label": "SYNC", "frame": _f(dec.sync_cob)}]}]
    for nid in sorted(dec.node_names):
        g = dec.node_label(nid)
        out.append({"group": g, "label": "Boot-up", "frames": heartbeat(nid, "boot-up")})
        out.append({"group": g, "label": "Heartbeat OPERATIONAL", "frames": heartbeat(nid, "operational")})
        try:
            out.append({"group": g, "label": "SDO read of 1018h:01 (vendor-ID)",
                        "frames": sdo(dec, nid, 0x1018, 1, "read", type_name="UNSIGNED32"
                                      if dec.object_type(nid, 0x1018, 1) is None else None)})
        except BuildError:
            pass
        out.append({"group": g, "label": "EMCY generic error", "frames": emcy(nid, 0x1000, 0x01)})
        for cob, p in sorted(dec.pdos.items()):
            if p.node != nid:
                continue
            vals = {}
            for k, (skey, name, start, length, signed, fk, tname) in enumerate(p.signals):
                vals[skey] = 1 if length == 1 else (k + 1) * 10 if length >= 8 else 1
            try:
                frames = pdo(dec, cob, vals)
            except BuildError:
                frames = pdo(dec, cob, {})
            out.append({"group": g, "label": p.name.rsplit("_", 1)[-1], "frames": frames})
    return out
