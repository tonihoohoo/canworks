"""PDO test on a USB adapter (canopen-local-bus, "PDO test on a local
adapter"): a node's PDO layout, read from the device over SDO or taken from
the configuration, and packing and unpacking of PDO data by that layout.

The adapter side (sending RPDOs and SYNC, receiving TPDOs) is in
localbus/client.py; this module is what the CLI and the configurator use to
build the layout they hand to pdo_test_start, and what both sides use to
pack and decode frames.
"""

from . import parameters as P
from .diag import DiagError, decode, encode, type_name

INVALID = 0x80000000
MAX_PDOS = 512
EVENT_TYPES = (252, 253, 254, 255)  # sent on a set (and repeated), not on SYNC
MAX_SYNC_TYPE = 240


def kinds():
    """(direction key, communication base, mapping base, name prefix)."""
    return (("tpdos", 0x1800, 0x1A00, "TPDO"), ("rpdos", 0x1400, 0x1600, "RPDO"))


def entry_key(e):
    return "0x%04X:%d" % (e["index"], e["subindex"])


def _entry(eds, value):
    index, sub, bits = value >> 16, (value >> 8) & 0xFF, value & 0xFF
    o = eds.find(index, sub) if eds is not None else None
    name = ""
    if o is not None:
        parent = eds.names.get(index, "")
        name = "%s: %s" % (parent, o.name) if parent and o.name and parent != o.name else (o.name or parent)
    t = type_name(o.data_type) if o is not None else None
    return {"index": index, "subindex": sub, "bits": bits, "type": t or ("UNSIGNED%d" % bits if bits in (8, 16, 32,
                                                                                                    64) else None),
            "name": name or "0x%04X:%d" % (index, sub)}


def _u(data):
    return int.from_bytes(data, "little") if data is not None else None


def layout(get, eds, node_id):
    """{"tpdos": [...], "rpdos": [...]} of the PDOs whose COB-ID is valid.
    `get(key)` returns an entry's bytes or None (from the device, or from a
    configuration with the device as fallback)."""
    out = {"tpdos": [], "rpdos": [], "node": node_id}
    for key, comm, mapping, prefix in kinds():
        for n in range(MAX_PDOS):
            if not (eds.has(comm + n) and eds.has(mapping + n)):
                if n >= 4:
                    break
                continue
            cob = _u(get((comm + n, 1)))
            if cob is None or cob & INVALID:
                continue
            trans = _u(get((comm + n, 2)))
            timer = _u(get((comm + n, 5))) if eds.find(comm + n, 5) is not None else None
            count = _u(get((mapping + n, 0))) or 0
            entries = []
            for k in range(1, min(count, 64) + 1):
                v = _u(get((mapping + n, k)))
                if v:
                    entries.append(_entry(eds, v))
            if not entries:
                continue
            out[key].append({"number": n + 1, "name": "%s%d" % (prefix, n + 1), "cob_id": cob & 0x7FF,
                             "transmission": trans if trans is not None else 255, "event_timer_ms": timer or 0,
                             "entries": entries})
    return out


class _Reader:
    """Reads entries over SDO as the layout asks for them, once each; stops
    after three timeouts in a row (the node is not there)."""

    def __init__(self, client, node_id, values=None):
        self.client, self.node_id = client, node_id
        self.values = dict(values or {})
        self.read = {}
        self.silent = 0

    def __call__(self, key):
        if key in self.values:
            return self.values[key]
        if key not in self.read:
            res = self.client.sdo_read(self.node_id, key[0], key[1], P.READ_TIMEOUT_MS)
            if res.get("success"):
                self.read[key] = bytes.fromhex(res.get("data") or "")
                self.silent = 0
            else:
                self.read[key] = None
                if res.get("abort_code") in (None, P.TIMEOUT_ABORT):
                    self.silent += 1
                    if self.silent >= P.SILENT_LIMIT:
                        raise DiagError("refused", "node %d does not answer SDO; it may be STOPPED or not on the "
                                                   "bus" % self.node_id)
        return self.read[key]


def from_device(client, node_id, eds):
    """The layout read from the device over SDO."""
    return layout(_Reader(client, node_id), eds, node_id)


def from_values(values, client, node_id, eds):
    """The layout of a configuration's final values ({(index, sub): bytes},
    commissioning's plan.desired), the device filling in what they leave out
    (a PDO whose mapping the device keeps)."""
    return layout(_Reader(client, node_id, values), eds, node_id)


# -- packing ------------------------------------------------------------------------

def _size(e):
    return (e["bits"] + 7) // 8


def unpack(entries, data):
    """[{name, key, value text, raw hex}] of a PDO's data by its entries."""
    v = int.from_bytes(bytes(data), "little")
    pos, out = 0, []
    for e in entries:
        bits = e["bits"]
        part = (v >> pos) & ((1 << bits) - 1)
        pos += bits
        raw = part.to_bytes(_size(e), "little")
        t = e.get("type")
        if t and type_name(t) and type_name(t).startswith("INTEGER") and bits % 8 == 0:
            text = decode(t, raw)["text"]
        elif t and type_name(t):
            text = decode(t, raw)["text"]
        else:
            text = "%d (0x%X)" % (part, part)
        out.append({"name": e["name"], "key": entry_key(e), "value": text, "raw": raw.hex(" ").upper(),
                    "missing": pos > len(data) * 8})
    return out


def encode_value(e, text):
    """Bytes of a value given as text for a mapped entry (its type's range,
    cut to the mapped bits)."""
    t = e.get("type") or "UNSIGNED%d" % (8 * _size(e))
    data = encode(t, text)
    v = int.from_bytes(data, "little") & ((1 << e["bits"]) - 1)
    return v.to_bytes(_size(e), "little")


def pack(entries, values):
    """The PDO's data bytes from {entry key: bytes} (0 for entries not set)."""
    v, pos = 0, 0
    for e in entries:
        part = int.from_bytes(values.get(entry_key(e), b""), "little") & ((1 << e["bits"]) - 1)
        v |= part << pos
        pos += e["bits"]
    return v.to_bytes((pos + 7) // 8, "little")


def find_entry(pdos, key):
    """(pdo, entry) for a key: an entry name (case-insensitive), "0xIIII:SS",
    or "RPDO1.name"; raises ValueError."""
    k = key.strip()
    pdo_name = None
    if "." in k and k.split(".", 1)[0].upper().startswith(("RPDO", "TPDO")):
        pdo_name, k = k.split(".", 1)
    hits = []
    for p in pdos:
        if pdo_name and p["name"].upper() != pdo_name.upper():
            continue
        for e in p["entries"]:
            if k.lower() == e["name"].lower() or k.lower() == entry_key(e).lower() or \
                    _same_key(k, e):
                hits.append((p, e))
    if not hits:
        raise ValueError("%s is not an entry of the node's RPDOs (%s)" % (key, ", ".join(
            "%s: %s" % (p["name"], ", ".join(e["name"] for e in p["entries"])) for p in pdos) or "none"))
    if len(hits) > 1:
        raise ValueError("%s is in %s; name the PDO, e.g. %s.%s" % (key, ", ".join(p["name"] for p, _ in hits),
                                                                    hits[0][0]["name"], k))
    return hits[0]


def _same_key(text, e):
    if ":" not in text:
        return False
    a, b = text.split(":", 1)
    try:
        return int(a, 0) == e["index"] and int(b, 0) == e["subindex"]
    except ValueError:
        return False


def is_event(transmission):
    return transmission in EVENT_TYPES or transmission > MAX_SYNC_TYPE
