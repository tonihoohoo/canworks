"""PDO layouts of nodes that are not in a configuration (canopen-bus-trace:
"PDO decoding without a configuration").

A node's PDO communication and mapping objects come from three sources:
the defaults of its EDS ("eds"), the device read over SDO ("device") and
SDO writes seen in the trace ("bus"); SDO reads seen in the trace count as
read from the device. NodeLayouts keeps the node's
current values with the source of each, and turns them into PdoLayouts
(decode.PdoLayout) whenever they change; the Decoder keeps every version
with the time it starts, so a frame decodes with the layout in force at its
time.

Signal names and types come from the node's EDS, else from the built-in
CiA 301/401/402 notes (builtin_notes/), else the object's index and
subindex with its mapped length as an unsigned value.
"""

from .. import notes as notes_mod
from ..iec import CO_TYPE_BY_CODE

INVALID = 0x80000000
MAX_PDOS = 512
SOURCES = ("eds", "device", "bus")  # rank: a later one is more certain
# (direction, communication base, mapping base, name prefix)
KINDS = ((True, 0x1800, 0x1A00, "TPDO"), (False, 0x1400, 0x1600, "RPDO"))
TYPE_BITS = {"BOOLEAN": 1, "INTEGER8": 8, "INTEGER16": 16, "INTEGER24": 24, "INTEGER32": 32, "INTEGER40": 40,
             "INTEGER48": 48, "INTEGER56": 56, "INTEGER64": 64, "UNSIGNED8": 8, "UNSIGNED16": 16, "UNSIGNED24": 24,
             "UNSIGNED32": 32, "UNSIGNED40": 40, "UNSIGNED48": 48, "UNSIGNED56": 56, "UNSIGNED64": 64,
             "REAL32": 32, "REAL64": 64}


def is_pdo_object(index):
    """Whether `index` is a PDO communication or mapping object."""
    return 0x1400 <= index <= 0x1BFF


def eds_values(eds, node_id):
    """{(index, sub): value} of the PDO objects' defaults in an EDS: the
    communication objects' COB-ID and transmission type, the mapping
    objects' count and entries."""
    out = {}
    for _tx, comm, mapping, _p in KINDS:
        for n in range(MAX_PDOS):
            if not eds.has(comm + n) and not eds.has(mapping + n):
                if n >= 4:
                    break
                continue
            for sub in (1, 2):
                o = eds.find(comm + n, sub)
                v = o.value(node_id) if o is not None else None
                if isinstance(v, int):
                    out[(comm + n, sub)] = v
            o = eds.find(mapping + n, 0)
            count = o.value(node_id) if o is not None else None
            if not isinstance(count, int):
                continue
            out[(mapping + n, 0)] = count
            for k in range(1, min(count, 64) + 1):
                o = eds.find(mapping + n, k)
                v = o.value(node_id) if o is not None else None
                if isinstance(v, int):
                    out[(mapping + n, k)] = v
    return out


def _title(text):
    """A built-in note's object name: its text up to the first colon or
    comma ("Statusword: the drive's ..." -> "Statusword")."""
    return text.split(":", 1)[0].split(",", 1)[0].strip()


def builtin_name(index, sub, profile=None):
    """The object's name from the built-in CiA 301/401/402 notes: the
    device's profile when known, else a profile whose notes alone have the
    index. "" when none does."""
    tables = [notes_mod._builtin_file("cia301")["objects"]]
    if index >= 0x6000:
        if profile in notes_mod.PROFILES:
            tables = [notes_mod._builtin_file("cia%d" % profile)["objects"]]
        else:
            having = [notes_mod._builtin_file("cia%d" % p)["objects"] for p in notes_mod.PROFILES]
            having = [t for t in having if notes_mod.key(index) in t or notes_mod.key(index, sub) in t]
            tables = having if len(having) == 1 else []
    for t in tables:
        n = t.get(notes_mod.key(index, sub))
        if n and n.get("text"):
            return _title(n["text"])
        n = t.get(notes_mod.key(index))
        if n and n.get("text"):
            return _title(n["text"]) + (" %d" % sub if sub else "")
    return ""


def object_name(eds, index, sub, profile=None):
    """The name a trace shows for a mapped object."""
    if eds is not None:
        parent, name = eds.object_name(index, sub)
        if parent and name and parent != name:
            return "%s: %s" % (parent, name)
        if name or parent:
            return name or parent
    return builtin_name(index, sub, profile) or "0x%04X:%d" % (index, sub)


def object_type(eds, index, sub, bits):
    o = eds.find(index, sub) if eds is not None else None
    t = CO_TYPE_BY_CODE.get(o.data_type) if o is not None else None
    if t and TYPE_BITS.get(t) == bits:
        return t
    if bits == 1:
        return "BOOLEAN"
    return "UNSIGNED%d" % bits if bits in (8, 16, 24, 32, 40, 48, 56, 64) else None


class NodeLayouts:
    """A node's PDO objects with the source of each value, and the PDOs they
    make. `make_pdo(cob, name, node, tx, signals, length, info)` builds a
    decode.PdoLayout."""

    def __init__(self, node, eds=None, profile=None):
        self.node, self.eds, self.profile = node, eds, profile
        self.values = {}  # (index, sub) -> (value, source, time_us)
        self.pending = {}

    def set(self, source, values, time_us):
        """Merges values from a source; a source never overrides values of a
        more certain one set earlier (EDS defaults under a device read)."""
        rank = SOURCES.index(source)
        for key, v in values.items():
            old = self.values.get(key)
            if old is not None and SOURCES.index(old[1]) > rank and source == "eds":
                continue
            self.values[key] = (int(v), source, time_us)

    def pdos(self, make_pdo):
        """{cob_id: PdoLayout} of the PDOs the values make usable."""
        out = {}
        for tx, comm, mapping, prefix in KINDS:
            numbers = sorted({i - comm for (i, _s) in self.values if comm <= i < comm + MAX_PDOS}
                             | {i - mapping for (i, _s) in self.values if mapping <= i < mapping + MAX_PDOS})
            for n in numbers:
                cob = self.values.get((comm + n, 1))
                count = self.values.get((mapping + n, 0))
                if cob is None or count is None or not count[0] or count[0] > 64:
                    continue
                # An EDS default marked invalid is still the best guess for
                # frames that do arrive on its identifier.
                if cob[0] & INVALID and cob[1] != "eds":
                    continue
                entries = [self.values.get((mapping + n, k)) for k in range(1, count[0] + 1)]
                if any(e is None for e in entries):
                    continue
                used = [cob, count] + entries
                best = max(used, key=lambda x: (SOURCES.index(x[1]), x[2]))
                if cob[1] == "eds" and count[1] == "eds" and all(e[1] == "eds" for e in entries):
                    best = ("", "eds", None)
                name = "%s%d" % (prefix, n + 1)
                cob_id = cob[0] & (0x1FFFFFFF if cob[0] & 0x20000000 else 0x7FF)
                trans = self.values.get((comm + n, 2))
                p = self._layout(make_pdo, cob_id, name, tx, [e[0] for e in entries])
                p.source, p.since_us = best[1], best[2]
                p.transmission = trans[0] if trans is not None else None
                out[cob_id] = p
        return out

    def _layout(self, make_pdo, cob_id, name, tx, entries):
        sigs, info, seen = [], [], {}
        bit = 0
        for v in entries:
            index, sub, bits = v >> 16, (v >> 8) & 0xFF, v & 0xFF
            if index < 0x1000 or not bits:  # a dummy entry fills bits only
                bit += bits
                continue
            label = object_name(self.eds, index, sub, self.profile)
            seen[label] = seen.get(label, 0) + 1
            if seen[label] > 1:
                label = "%s #%d" % (label, seen[label])
            t = object_type(self.eds, index, sub, bits)
            signed = bool(t and t.startswith("INTEGER"))
            float_kind = 1 if t == "REAL32" else 2 if t == "REAL64" else 0
            key = "node%d.%s.%s" % (self.node, name, label)
            sigs.append((key, label, bit, bits, signed, float_kind, t or ""))
            info.append({"index": index, "subindex": sub, "type": t or "", "used": False, "location": None,
                         "variables": []})
            bit += bits
        return make_pdo(cob_id, name, self.node, tx, sigs, (bit + 7) // 8, info)

    # -- SDO transfers seen on the bus --------------------------------------
    def learn(self, index, sub, data, time_us, source="bus"):
        """A value the bus wrote and the device confirmed ("bus"), or one a
        client read from the device ("device")."""
        if not data:
            return False
        v = int.from_bytes(bytes(data[:4]), "little")
        old = self.values.get((index, sub))
        if old is not None and old[0] == v and old[1] == source:
            return False
        self.values[(index, sub)] = (v, source, time_us)
        return True
