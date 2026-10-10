"""Exports the configured CANopen network as a DBC file (canopen-dbc-export spec).

The DBC describes every configured PDO at the COB-ID the plugin gives it,
laid out from the config's entries or, for a PDO that keeps the device's
mapping, from the EDS default mapping; each node's heartbeat and EMCY, NMT
and SYNC; and, on request, each node's SDO frames as multiplexed messages.
It is built from the same checks and resolution rules the deploy tool uses
(contract.check_config, contract.auto_cob_ids, eds.mapping_info), so it
matches what the plugin puts on the bus.

    model = build(cfg, config_path, sdo="config", names=plc_names(uses))
    text = write(model)
"""

import os
import re
import tempfile

from . import __version__, bundle, contract, edslint
from . import notes as notes_mod
from . import eds as eds_mod
from . import links as links_mod
from .iec import CO_TYPES, CO_TYPE_BY_CODE, parse_location
from .raw.mux import merge as mux_merge

SDO_OPTIONS = ("none", "config", "all")
MASTER = "Master"
NO_RECEIVER = "Vector__XXX"
PLC_NODE = "PLC"  # the sender of a plain CAN network's raw messages

NMT_STATES = [(0, "Boot-up"), (4, "Stopped"), (5, "Operational"), (127, "Pre-operational")]
NMT_COMMANDS = [(1, "Start"), (2, "Stop"), (128, "Enter pre-operational"), (129, "Reset node"),
                (130, "Reset communication")]
# Expedited SDO command specifiers (CiA 301), per direction.
SDO_REQUESTS = [(0x22, "Download"), (0x23, "Download 4 bytes"), (0x27, "Download 3 bytes"),
                (0x2B, "Download 2 bytes"), (0x2F, "Download 1 byte"), (0x40, "Upload request"), (0x80, "Abort")]
SDO_RESPONSES = [(0x42, "Upload"), (0x43, "Upload 4 bytes"), (0x47, "Upload 3 bytes"), (0x4B, "Upload 2 bytes"),
                 (0x4F, "Upload 1 byte"), (0x60, "Download response"), (0x80, "Abort")]
SDO_COMMAND_COMMENT = ("SDO command specifier. Only expedited transfers (up to 4 bytes) decode; on an abort (0x80) "
                       "bytes 4-7 hold the abort code, shown as the object's data.")
# Types an expedited SDO transfer carries whole (canopen-dbc-export: "all").
SDO_TYPES = ("BOOLEAN", "INTEGER8", "INTEGER16", "INTEGER32", "UNSIGNED8", "UNSIGNED16", "UNSIGNED32", "REAL32")


class ExportFailed(Exception):
    """The export stopped: `problems` is a list of (message, [JSON path])."""

    def __init__(self, problems):
        super().__init__("\n".join(m for m, _ in problems))
        self.problems = problems


class Signal:
    """A DBC signal. `start` is the DBC start bit (big byte order: the most
    significant bit). The CANopen export takes scale, unit and value names
    from the object's device notes (canopen-device-notes), else 1, "" and
    none; its offset is 0."""

    def __init__(self, name, start, length, signed=False, float_kind=0, receivers=(), comment="",
                 mux=None, multiplexer=False, values=None, scale=1, offset=0, unit="", big_endian=False,
                 minimum=None, maximum=None, mux_on=None, mux_ranges=None):
        self.name, self.start, self.length = name, start, length
        self.signed, self.float_kind = signed, float_kind  # float_kind: 0, 1 (single) or 2 (double)
        self.receivers = list(receivers)
        # Multiplexing: `multiplexer` marks a switch; `mux` is the one switch
        # value of a simple dependent (mN). Extended multiplexing (raw and
        # J1939 signals with `mux`): `mux_on` names the switch's DBC signal
        # and `mux_ranges` holds its values as [(low, high)].
        self.comment, self.mux, self.multiplexer = comment, mux, multiplexer
        self.mux_on, self.mux_ranges = mux_on, mux_ranges
        self.values = values or []  # [(value, text)]
        self.scale, self.offset, self.unit, self.big_endian = scale, offset, unit, big_endian
        self.minimum, self.maximum = minimum, maximum  # physical limits; None: the raw range's

    def raw_range(self):
        if self.float_kind:
            return 0, 0
        if self.signed:
            return -(1 << (self.length - 1)), (1 << (self.length - 1)) - 1
        return 0, (1 << self.length) - 1

    def range(self):
        """[minimum, maximum] in physical units."""
        if self.minimum is not None and self.maximum is not None:
            return self.minimum, self.maximum
        lo, hi = self.raw_range()
        if self.scale == 1 and self.offset == 0:
            return lo, hi
        lo, hi = lo * self.scale + self.offset, hi * self.scale + self.offset
        return (lo, hi) if lo <= hi else (hi, lo)


class Message:
    """A DBC message. `extended`: a 29-bit identifier (written with bit 31
    set, as DBC files mark it); `j1939`: a J1939 parameter group
    (VFrameFormat J1939PG)."""

    def __init__(self, cob_id, name, length, sender, comment="", cycle_ms=None, extended=False, j1939=False):
        self.cob_id, self.name, self.length, self.sender = cob_id, name, length, sender
        self.comment, self.cycle_ms = comment, cycle_ms
        self.extended, self.j1939 = extended or j1939, j1939
        self.signals = []

    @property
    def dbc_id(self):
        return self.cob_id | 0x80000000 if self.extended else self.cob_id


class Model:
    """`protocol`: "J1939" writes the J1939 attributes (ProtocolType,
    VFrameFormat); None for CANopen."""

    def __init__(self, nodes, messages, comment, warnings, protocol=None):
        self.nodes, self.messages, self.comment, self.warnings = nodes, messages, comment, warnings
        self.protocol = protocol


# -- names --------------------------------------------------------------------

def identifier(text):
    """`text` as a DBC identifier: ASCII letters, digits and _, not starting
    with a digit. "" when nothing usable is left."""
    s = re.sub(r"[^A-Za-z0-9_]+", "_", str(text)).strip("_")
    s = re.sub(r"_+", "_", s)
    if s and s[0].isdigit():
        s = "_" + s
    return s


def od_name(eds, index, subindex):
    """The signal name from the object dictionary: a VAR's ParameterName; for
    a record/array sub-object the parent's name, _, the sub-object's, without
    the parent part when the sub-object's name already starts with it."""
    parent, sub = eds.object_name(index, subindex)
    parent, sub = identifier(parent), identifier(sub)
    if parent and sub and not sub.lower().startswith(parent.lower()):
        return "%s_%s" % (parent, sub)
    return sub or parent


def plc_names(uses):
    """{location text: [variable names]} from configurator/scan.py uses: the
    located variables of an editor project, names compared ignoring case."""
    out = {}
    for u in uses:
        if u.kind != "variable" or not u.name:
            continue
        names = out.setdefault(str(u.loc), [])
        if u.name.lower() not in (n.lower() for n in names):
            names.append(u.name)
    return out


def project_names(config_path):
    """plc_names() of the editor project a config belongs to: `config_path` is
    <project>/canworks/<file> and <project> has project.json. None otherwise."""
    folder = os.path.dirname(os.path.abspath(config_path))
    root = os.path.dirname(folder)
    if os.path.basename(folder) != "canworks" or not os.path.isfile(os.path.join(root, "project.json")):
        return None
    from .configurator import scan
    uses, _ = scan.scan(root)
    return plc_names(uses)


class _Names:
    """Unique names within one scope (a message, or the node list)."""

    def __init__(self, taken=()):
        self.taken = {t.lower() for t in taken}

    def add(self, name, suffix):
        if name.lower() in self.taken:
            name = "%s_%s" % (name, suffix)
        self.taken.add(name.lower())
        return name


# -- building -----------------------------------------------------------------

def _u(value, default=None):
    v = contract._uint(value) if value is not None else None
    return default if v is None else v


def _ascii(text):
    return str(text).encode("ascii", "replace").decode("ascii").replace('"', "'")


def _bits_of(type_name):
    return CO_TYPES[type_name][1]


def _signal_type(type_name, length):
    """(signed, float_kind) for a CANopen type name (None: unsigned)."""
    if type_name in ("REAL32", "REAL64"):
        return False, 1 if type_name == "REAL32" else 2
    return bool(type_name and type_name.startswith("INTEGER")), 0


def file_notes(paths):
    """The notes source of an export run from files: each EDS's notes file
    next to it, over the built-in notes. `paths`: {eds value: EDS path}."""
    def source(value, eds):
        path = paths.get(value)
        return notes_mod.Notes.for_eds(eds, value, path if path and os.path.isfile(path) else None)
    return source


def note_signal(note, signal, type_name):
    """Unit, scale, value names and the note text of an object's merged note
    on its signal."""
    if not note:
        return
    if note.get("unit"):
        signal.unit = note["unit"]
    if isinstance(note.get("scale"), (int, float)) and not isinstance(note.get("scale"), bool) and note["scale"]:
        signal.scale = note["scale"]
    if note.get("values") and not signal.float_kind:
        signal.values = sorted((int(v), t) for v, t in note["values"].items())
    if note.get("text"):
        signal.comment += "; " + note["text"]


def _load_eds(cfg, config_path, eds_paths):
    paths = eds_paths if eds_paths is not None else bundle.eds_files(cfg, config_path)
    out = []
    for n in cfg["nodes"]:
        node_id = _u(n["node_id"])
        with open(paths[n["eds"]], "rb") as f:
            text, _, _ = edslint.check(f.read(), node_id)
        out.append(eds_mod.Eds.read(n["eds"], text))
    return out


def _normalized_pdos(cfg):
    """Per node {"tx_pdos": [...], "rx_pdos": [...]} with number and resolved
    COB-ID, as the plugin resolves them."""
    nodes = []
    for n in cfg["nodes"]:
        node = {"node_id": _u(n["node_id"]), "tx_pdos": [], "rx_pdos": []}
        for key in ("tx_pdos", "rx_pdos"):
            for j, p in enumerate(n.get(key, [])):
                pdo = {"number": _u(p.get("number"), j + 1)}
                if "cob_id" in p:
                    pdo["cob_id"] = "auto" if p["cob_id"] == "auto" else _u(p["cob_id"])
                node[key].append(pdo)
        nodes.append(node)
    for (i, key, j), cob in contract.auto_cob_ids(nodes).items():
        nodes[i][key][j]["cob_id"] = cob
    for node in nodes:
        for key in ("tx_pdos", "rx_pdos"):
            for p in node[key]:
                if not isinstance(p.get("cob_id"), int) or not p["cob_id"]:
                    p["cob_id"] = contract.default_cob_id(node["node_id"], p["number"], key == "tx_pdos")
    return nodes


def node_identifiers(cfg):
    """The DBC network node name of each configured node, in config order."""
    names = _Names([MASTER])
    out = []
    for n in cfg["nodes"]:
        node_id = _u(n["node_id"])
        base = identifier(n.get("name") or "") or "node%d" % node_id
        out.append(names.add(base, node_id))
    return out


def _location_label(loc, names):
    """(signal name or None, comment text) for a PLC location."""
    if not loc:
        return None, ""
    key = str(parse_location(loc) or loc)
    found = (names or {}).get(key, [])
    text = key + (" (%s)" % ", ".join(found) if found else "")
    name = identifier(found[0]) if len(found) == 1 else None
    return name or None, text


def pdo_layout(p, eds, tx, num):
    """([(index, subindex, bits)] in the order the PDO carries them, {(index,
    subindex): config entry}) of a configured PDO: the device's EDS default
    mapping when the PDO uses it, else the config's entries."""
    mi = eds_mod.mapping_info(eds, (0x1A00 if tx else 0x1600) + num - 1)
    used = {(_u(e["index"]), _u(e.get("subindex"), 0)): e for e in p["entries"]}
    if eds_mod.uses_device_mapping(p, mi):
        layout = [(v >> 16, (v >> 8) & 0xFF, v & 0xFF) for v in mi["defaults"]]
    else:
        layout = [(_u(e["index"]), _u(e.get("subindex"), 0), _bits_of(e["type"])) for e in p["entries"]]
    return layout, used


def pdo_marks(n, eds):
    """{(index, subindex): [{"pdo": "TPDO1", "bits": [first, last], "location": ...}]}
    for every object a configured node's PDOs carry (dummy entries left
    out). PDO numbers as the config gives them (default: position + 1)."""
    out = {}
    for key, tx in (("tx_pdos", True), ("rx_pdos", False)):
        for j, p in enumerate(n.get(key, [])):
            num = _u(p.get("number"), j + 1)
            layout, used = pdo_layout(p, eds, tx, num)
            bit = 0
            for index, sub, length in layout:
                if index >= 0x0008:
                    entry = used.get((index, sub))
                    mark = {"pdo": "%s%d" % ("TPDO" if tx else "RPDO", num), "bits": [bit, bit + length - 1]}
                    if entry and entry.get("iec_location"):
                        mark["location"] = entry["iec_location"]
                    out.setdefault((index, sub), []).append(mark)
                bit += length
    return out


def _pdo_messages(n, node_name, eds, pdos, cfg, names, warnings, notes=None):
    sync_us = _u(cfg["master"].get("sync_period_us"), 0)
    plc_cycle = cfg["master"].get("sync_source") == "plc_cycle"
    sync_cycles = _u(cfg["master"].get("sync_cycles"), 1) or 1
    msgs = []
    for key in ("tx_pdos", "rx_pdos"):
        tx = key == "tx_pdos"
        kind = "TPDO" if tx else "RPDO"
        for p, norm in zip(n.get(key, []), pdos[key]):
            num, cob = norm["number"], norm["cob_id"]
            layout, used = pdo_layout(p, eds, tx, num)
            total = sum(b for _, _, b in layout)
            trans = _u(p.get("transmission")) if "transmission" in p else None
            source = ""
            if trans is None:
                sub = eds.find((0x1800 if tx else 0x1400) + num - 1, 2)
                trans = sub.value(n_id(n)) if sub is not None else None
                source = " from EDS"
            cycle = None
            if trans is not None and 1 <= trans <= 240 and sync_us:
                cycle = int(round(sync_us * trans / 1000.0)) or None
            text = "node %d %s %d, transmission %s%s" % (n_id(n), kind, num,
                                                        trans if trans is not None else "not set", source)
            if trans is not None and 1 <= trans <= 240 and plc_cycle:
                # The SYNC period is the PLC task's, which the config does not hold.
                text += ", sent at %s, one SYNC every %s" % (
                    "every SYNC" if trans == 1 else "every %d SYNCs" % trans,
                    "PLC cycle" if sync_cycles == 1 else "%d PLC cycles" % sync_cycles)
            msg = Message(cob, "%s_%s%d" % (node_name, kind, num), (total + 7) // 8,
                          node_name if tx else MASTER, text, cycle)
            receiver = MASTER if tx else node_name
            msg.pdo = (kind, num)
            taken = _Names()
            bit = 0
            for position, (index, sub, length) in enumerate(layout):
                if index < 0x0008:  # dummy entry: its bits, no signal
                    bit += length
                    continue
                entry = used.get((index, sub))
                obj = eds.find(index, sub)
                type_name = entry["type"] if entry else (CO_TYPE_BY_CODE.get(obj.data_type) if obj else None)
                plc_name, loc_text = _location_label(entry.get("iec_location") if entry else None, names)
                name = plc_name or od_name(eds, index, sub) or "obj_%04X_%d" % (index, sub)
                name = taken.add(name, "%04X_%d" % (index, sub))
                signed, float_kind = _signal_type(type_name, length)
                if entry and loc_text:
                    what = "-> " + loc_text
                elif entry:  # a version 2 entry a gateway route uses: no PLC location
                    what = "(gateway route, no PLC location)"
                elif tx:
                    what = "(not used by the PLC)"
                else:
                    what = "(not used by the PLC, sent as 0 by the master)"
                signal = Signal(name, bit, length, signed, float_kind, [receiver],
                                "0x%04X:%d %s %s" % (index, sub, type_name or "unknown type", what))
                signal.position = position
                if notes is not None and obj is not None:
                    note_signal(notes.note(index, sub), signal, type_name)
                msg.signals.append(signal)
                bit += length
            msgs.append(msg)
    for s in n.get("sdo", []):
        index, sub = _u(s["index"]), _u(s.get("subindex"), 0)
        if not 0x1400 <= index <= 0x1BFF:
            continue
        pdo_kind = "RPDO" if index < 0x1800 else "TPDO"
        num = (index & 0x1FF) + 1
        if any(q["number"] == num for q in pdos["tx_pdos" if pdo_kind == "TPDO" else "rx_pdos"]):
            warnings.append(("node %d: a startup SDO writes 0x%04X subindex %d; the DBC follows the config's settings "
                             "for %s %d and may not match the bus" % (n_id(n), index, sub, pdo_kind, num)))
    return msgs


def n_id(n):
    return _u(n["node_id"])


def _link_receivers(cfg, messages, eds_list, node_names):
    """PDO links add no message (canopen-dbc-export "Linked PDOs in the DBC"):
    the producer TPDO's signals get the consumers whose layout maps a real
    object at their position as receivers, and its comment names the link."""
    ids = [n_id(n) for n in cfg["nodes"]]
    for link in links_mod.parse(cfg):
        if link["producer"] not in ids:
            continue
        pname = node_names[ids.index(link["producer"])]
        msg = next((m for m in messages if getattr(m, "pdo", None) == ("TPDO", link["tpdo"])
                    and m.sender == pname), None)
        if msg is None:
            continue
        parts = []
        for c in link["consumers"]:
            if c["node"] not in ids or c["node"] == link["producer"]:
                continue
            k = ids.index(c["node"])
            layout, _ = links_mod.consumer_layout(c, eds_list[k])
            objects = []
            for pos, x in enumerate(layout):
                real = x["index"] >= 0x0008
                objects.append("0x%04X:%d" % (x["index"], x["subindex"]) if real else "dummy")
                for s in msg.signals:
                    if real and getattr(s, "position", None) == pos and node_names[k] not in s.receivers:
                        s.receivers.append(node_names[k])
            parts.append("node %d RPDO %d writes %s" % (c["node"], c["rpdo"], ", ".join(objects)))
        msg.comment += "; %s to %s" % (link["label"], "; ".join(parts))


def _sdo_objects(n, eds, option):
    """[(index, sub, type name, config name, comment)] for the node's SDO messages."""
    out, seen = [], set()

    def add(index, sub, type_name, name, comment):
        if (index, sub) in seen or type_name not in SDO_TYPES:
            return
        seen.add((index, sub))
        out.append((index, sub, type_name, name, comment))

    if option == "config":
        for v in n.get("sdo_variables", []):
            add(_u(v["index"]), _u(v.get("subindex"), 0), v["type"], v.get("name"),
                "SDO variable, %s -> %s" % (v["direction"], v["iec_location"]))
        for s in n.get("sdo", []):
            add(_u(s["index"]), _u(s.get("subindex"), 0), s["type"], None, "startup SDO, value %s" % s["value"])
    elif option == "all":
        configured = {}
        for v in n.get("sdo_variables", []):
            configured[(_u(v["index"]), _u(v.get("subindex"), 0))] = (
                v.get("name"), "SDO variable, %s -> %s" % (v["direction"], v["iec_location"]))
        for s in n.get("sdo", []):
            configured.setdefault((_u(s["index"]), _u(s.get("subindex"), 0)),
                                  (None, "startup SDO, value %s" % s["value"]))
        for index, sub, obj in eds.items():
            name, comment = configured.get((index, sub), (None, ""))
            add(index, sub, obj.type_name, name, comment)
    return out


def _sdo_messages(n, node_name, eds, option, notes=None):
    objects = _sdo_objects(n, eds, option)
    node_id = n_id(n)
    msgs = []
    for cob, suffix, sender, receiver, commands in (
            (0x600 + node_id, "SDO_Rx", MASTER, node_name, SDO_REQUESTS),
            (0x580 + node_id, "SDO_Tx", node_name, MASTER, SDO_RESPONSES)):
        msg = Message(cob, "%s_%s" % (node_name, suffix), 8, sender,
                      "node %d SDO %s" % (node_id, "request (client to server)" if sender == MASTER
                                          else "response (server to client)"))
        taken = _Names(["Command", "Object"])
        msg.signals.append(Signal("Command", 0, 8, receivers=[receiver], comment=SDO_COMMAND_COMMENT,
                                  values=commands))
        table = []
        data = []
        for index, sub, type_name, config_name, comment in objects:
            value = index + (sub << 16)
            name = identifier(config_name or "") or od_name(eds, index, sub) or "obj_%04X_%d" % (index, sub)
            name = taken.add(name, "%04X_%d" % (index, sub))
            table.append((value, "0x%04X:%d %s" % (index, sub, name)))
            length = 8 if type_name == "BOOLEAN" else _bits_of(type_name)
            signed, float_kind = _signal_type(type_name, length)
            signal = Signal(name, 32, length, signed, float_kind, [receiver],
                            "0x%04X:%d %s%s" % (index, sub, type_name, ", " + comment if comment else ""), mux=value)
            if notes is not None:
                note_signal(notes.note(index, sub), signal, type_name)
            data.append(signal)
        msg.signals.append(Signal("Object", 8, 24, receivers=[receiver], multiplexer=True,
                                  comment="index + subindex * 65536 (bytes 1-3 of the frame)", values=table))
        msg.signals += data
        msgs.append(msg)
    return msgs


def build(cfg, config_path, eds_paths=None, sdo="none", names=None, checked=False, notes=None):
    """The DBC model of a config with one network. Raises ExportFailed with
    the config checks' errors; `checked`: the caller ran them, and the model's
    warnings are only the export's own. `names`: plc_names() of the editor
    project, or None. `notes`: a callable (eds value, Eds) -> notes.Notes;
    default: each EDS's notes file next to it."""
    if sdo not in SDO_OPTIONS:
        raise ValueError("sdo must be one of %s" % ", ".join(SDO_OPTIONS))
    paths = eds_paths if eds_paths is not None else bundle.eds_files(cfg, config_path)
    warnings = []
    if not checked:
        result = contract.check_config(cfg, config_path, eds_paths=paths)
        if not result.ok:
            raise ExportFailed([(i["message"], i["paths"]) for i in result.items if i["level"] == "error"])
        warnings = list(result.warnings)
    eds_list = _load_eds(cfg, config_path, paths)
    pdos = _normalized_pdos(cfg)
    node_names = node_identifiers(cfg)
    notes = notes or file_notes(paths)
    messages = []
    for n, eds, norm, node_name in zip(cfg["nodes"], eds_list, pdos, node_names):
        node_id = n_id(n)
        nt = notes(n["eds"], eds)
        messages += _pdo_messages(n, node_name, eds, norm, cfg, names, warnings, nt)
        hb = Message(0x700 + node_id, "%s_Heartbeat" % node_name, 1, node_name, "node %d heartbeat" % node_id)
        hb.signals.append(Signal("NMT_State", 0, 7, receivers=[MASTER], values=NMT_STATES))
        messages.append(hb)
        em = Message(0x80 + node_id, "%s_EMCY" % node_name, 8, node_name, "node %d emergency" % node_id)
        em.signals += [Signal("Error_Code", 0, 16, receivers=[MASTER]),
                       Signal("Error_Register", 16, 8, receivers=[MASTER]),
                       Signal("Manufacturer_Data", 24, 40, receivers=[MASTER])]
        messages.append(em)
        if sdo != "none":
            messages += _sdo_messages(n, node_name, eds, sdo, nt)
    _link_receivers(cfg, messages, eds_list, node_names)
    nmt = Message(0x000, "NMT", 2, MASTER, "NMT node control; Node_ID 0 addresses all nodes")
    nmt.signals += [Signal("Command", 0, 8, receivers=node_names or [NO_RECEIVER], values=NMT_COMMANDS),
                    Signal("Node_ID", 8, 8, receivers=node_names or [NO_RECEIVER])]
    messages.append(nmt)
    # Without a SYNC period or PLC-cycle SYNC the master produces no SYNC.
    if _u(cfg["master"].get("sync_period_us"), 0) or cfg["master"].get("sync_source") == "plc_cycle":
        messages.append(Message(0x080, "SYNC", 0, MASTER, "SYNC"))
    comment = "CANopen network of %s, exported by canworks-deploy %s" % (
        os.path.basename(config_path), __version__)
    return Model([MASTER] + node_names, messages, comment, warnings)


def frames(cfg, model):
    """Every frame of a one-network config on the bus: the DBC model's
    messages plus those a DBC leaves out (the master's heartbeat, or its
    boot-up message alone when the heartbeat is off, TIME when the master
    produces it, each node's SDO server channel), sorted by
    COB-ID. Each added Message has `kind` "master_heartbeat", "time",
    "sdo_request" or "sdo_response"; the model's messages are not changed."""
    m = cfg["master"]
    master_id = _u(m.get("node_id"), 1)
    out = list(model.messages)
    hb = Message(0x700 + master_id, "Master_Heartbeat", 1, MASTER, "master (node %d) heartbeat" % master_id,
                 _u(m.get("heartbeat_ms"), 0) or None)
    hb.kind = "master_heartbeat"
    out.append(hb)
    if "time_period_ms" in m:
        cob = _u(m.get("time_cob_id"), 0x100) & 0x7FF or 0x100
        t = Message(cob, "TIME", 6, MASTER, "TIME_OF_DAY from the runtime host's clock", _u(m["time_period_ms"]))
        t.kind = "time"
        out.append(t)
    for n, name in zip(cfg["nodes"], node_identifiers(cfg)):
        node_id = n_id(n)
        req = Message(0x600 + node_id, "%s_SDO_Request" % name, 8, MASTER, "SDO client to node %d" % node_id)
        req.kind = "sdo_request"
        rsp = Message(0x580 + node_id, "%s_SDO_Response" % name, 8, name, "node %d SDO server" % node_id)
        rsp.kind = "sdo_response"
        out += [req, rsp]
    return sorted(out, key=lambda x: (x.cob_id, x.name))


# -- writing ------------------------------------------------------------------

def number(v):
    """A DBC number: 6425.5, 0.1, 255 (an integral value without a point)."""
    if isinstance(v, float):
        if v.is_integer() and abs(v) < 1e15:
            return "%d" % v
        return format(v, ".15g")
    return "%d" % v


def _extended_mux(m):
    """True when a message's multiplexing needs SG_MUL_VAL_ lines: several
    switches, a nested switch, or a signal on ranges or several values."""
    switches = [s for s in m.signals if s.multiplexer]
    for s in m.signals:
        if s.mux_ranges is not None and (len(s.mux_ranges) > 1 or s.mux_ranges[0][0] != s.mux_ranges[0][1]):
            return True
        if s.multiplexer and (s.mux is not None or s.mux_ranges is not None):
            return True
    return len(switches) > 1


def _mux_mark(s):
    """" M", " m3", " m3M" or "" for a signal's SG_ line."""
    value = s.mux if s.mux is not None else s.mux_ranges[0][0] if s.mux_ranges else None
    if value is None:
        return " M" if s.multiplexer else ""
    return " m%d%s" % (value, "M" if s.multiplexer else "")


def mux_signals(config_signals, signals):
    """Sets the multiplexing of DBC `signals` from the raw or J1939 config
    signals they were made from (same order; `multiplexer` and `mux` as in
    the config, `mux.on` defaulting to the message's one switch)."""
    switches = {}
    for c, s in zip(config_signals, signals):
        if c.get("multiplexer") is True:
            s.multiplexer = True
            switches.setdefault(c.get("name"), s.name)
    only = next(iter(switches.values())) if len(switches) == 1 else None
    for c, s in zip(config_signals, signals):
        mux = c.get("mux")
        if not isinstance(mux, dict) or not isinstance(mux.get("values"), list):
            continue
        on = switches.get(mux["on"]) if "on" in mux else only
        if on is None:
            continue
        ranges = [(v, v) if isinstance(v, int) else (v[0], v[1]) for v in mux["values"]]
        s.mux_on, s.mux_ranges = on, mux_merge(ranges)


def write(model):
    """The model as DBC text (ASCII, CRLF)."""
    extended = [m for m in model.messages if _extended_mux(m)]
    L = ['VERSION ""', "", "NS_ :", "\tNS_DESC_", "\tCM_", "\tBA_DEF_", "\tBA_", "\tVAL_", "\tBA_DEF_DEF_",
         "\tSIG_VALTYPE_"] + (["\tSG_MUL_VAL_"] if extended else []) + [
         "", "BS_:", "", "BU_: " + " ".join(model.nodes), ""]
    for m in model.messages:
        L.append("BO_ %d %s: %d %s" % (m.dbc_id, m.name, m.length, m.sender))
        for s in m.signals:
            mux = _mux_mark(s)
            lo, hi = s.range()
            L.append(' SG_ %s%s : %d|%d@%d%s (%s,%s) [%s|%s] "%s" %s'
                     % (s.name, mux, s.start, s.length, 0 if s.big_endian else 1, "-" if s.signed else "+",
                        number(s.scale), number(s.offset), number(lo), number(hi), _ascii(s.unit),
                        ",".join(s.receivers) or NO_RECEIVER))
        L.append("")
    L.append('CM_ "%s";' % _ascii(model.comment))
    for m in model.messages:
        if m.comment:
            L.append('CM_ BO_ %d "%s";' % (m.dbc_id, _ascii(m.comment)))
        for s in m.signals:
            if s.comment:
                L.append('CM_ SG_ %d %s "%s";' % (m.dbc_id, s.name, _ascii(s.comment)))
    j1939 = model.protocol == "J1939"
    if j1939:
        L.append('BA_DEF_ "ProtocolType" STRING ;')
    L.append('BA_DEF_ BO_ "GenMsgCycleTime" INT 0 65535;')
    if j1939:
        L.append('BA_DEF_ BO_ "VFrameFormat" ENUM "StandardCAN","ExtendedCAN","reserved","J1939PG";')
        L.append('BA_DEF_DEF_ "ProtocolType" "";')
    L.append('BA_DEF_DEF_ "GenMsgCycleTime" 0;')
    if j1939:
        L.append('BA_DEF_DEF_ "VFrameFormat" "J1939PG";')
        L.append('BA_ "ProtocolType" "J1939";')
    for m in model.messages:
        if m.cycle_ms:
            L.append('BA_ "GenMsgCycleTime" BO_ %d %d;' % (m.dbc_id, min(m.cycle_ms, 65535)))
    if j1939:
        for m in model.messages:
            L.append('BA_ "VFrameFormat" BO_ %d %d;' % (m.dbc_id, 3 if m.j1939 else 1 if m.extended else 0))
    for m in model.messages:
        for s in m.signals:
            if s.values:
                L.append("VAL_ %d %s %s ;" % (m.dbc_id, s.name,
                                              " ".join('%d "%s"' % (v, _ascii(t)) for v, t in s.values)))
    for m in model.messages:
        for s in m.signals:
            if s.float_kind:
                L.append("SIG_VALTYPE_ %d %s : %d;" % (m.dbc_id, s.name, s.float_kind))
    # Extended multiplexing, Vector style: a line for every dependent signal.
    for m in extended:
        for s in m.signals:
            if s.mux_on is not None and s.mux_ranges:
                L.append("SG_MUL_VAL_ %d %s %s %s;" % (m.dbc_id, s.name, s.mux_on,
                                                        ", ".join("%d-%d" % r for r in s.mux_ranges)))
    return "\r\n".join(L) + "\r\n"


def export(cfg, config_path, eds_paths=None, sdo="none", names=None, notes=None):
    """(DBC text, warnings [str]) of a config with one network. Raises
    ExportFailed."""
    model = build(cfg, config_path, eds_paths, sdo, names, notes=notes)
    return write(model), model.warnings


def export_networks(cfg, config_path, eds_paths=None, sdo="none", names=None, network=None, notes=None):
    """([(network name, DBC text)], warnings): one DBC per network, or only
    for the one `network` names; the name is "" for a version 1 file. A
    J1939 network's DBC comes from canworks/j1939/dbc.py. Every
    network is checked (and the checks across networks run) before any is
    built. Raises ExportFailed."""
    paths = eds_paths if eds_paths is not None else bundle.eds_files(cfg, config_path)
    result = contract.check_config(cfg, config_path, eds_paths=paths)
    if not result.ok:
        raise ExportFailed([(i["message"], i["paths"]) for i in result.items if i["level"] == "error"])
    every = contract.networks(cfg)
    nets = every
    if network is not None:
        nets = [n for n in every if n["name"] == network]
        if not nets:
            raise ExportFailed([("no network '%s' in the config (%s)" % (
                network, ", ".join(n["name"] or "unnamed" for n in every)), ["networks"])])
    files, warnings = [], list(result.warnings)
    j1939_nets = [n for n in nets if n["role"] == "j1939"]
    plain = [n for n in nets if n["role"] == "plain"]
    masters = [n for n in nets if n["role"] == "master"] if j1939_nets or plain \
        else _no_slave(nets, network, "a DBC file")
    for net in nets:
        raw = net["json"].get("raw") if net["path"] else None
        if net in plain:
            model = Model([PLC_NODE], raw_messages(raw, PLC_NODE),
                          "Plain CAN network %s of %s, exported by canworks-deploy %s" % (
                              net["name"], os.path.basename(config_path), __version__), [])
        elif net in j1939_nets:
            from .j1939 import dbc as j1939_dbc  # the J1939 export (canworks/j1939/dbc.py)
            model = j1939_dbc.build(net, config_path, names)
        elif net in masters:
            one = contract.network_config(cfg, net["name"] if net["path"] else None)
            model = build(one, config_path, paths, sdo, names, checked=True, notes=notes)
            if len(every) > 1:
                model.comment = "CANopen network %s of %s, exported by canworks-deploy %s" % (
                    net["name"], os.path.basename(config_path), __version__)
        else:
            continue
        if raw and net not in plain:
            sender = PLC_NODE if PLC_NODE in model.nodes else model.nodes[0]
            model.messages += raw_messages(raw, sender)
        files.append((net["name"], write(model)))
        warnings += [(net["name"] + ": " if len(every) > 1 else "") + w for w in model.warnings]
    return files, warnings


def raw_messages(raw, sender):
    """The raw messages of a network's `raw` object as DBC messages (spec
    canopen-dbc-export "Raw messages in the DBC"): send messages from
    `sender`, the cycle time from the period, or for a receive message a
    third of its timeout."""
    from .raw.contract import hex_id, tx_dlc
    out = []
    for kind in ("rx", "tx"):
        for m in (raw or {}).get(kind) or []:
            if not isinstance(m, dict) or not isinstance(m.get("id"), int):
                continue
            cycle = m.get("period_ms") if kind == "tx" else (m.get("timeout_ms") or 0) // 3
            msg = Message(m["id"], identifier(m.get("name") or "msg_%s" % hex_id(m["id"])[2:]),
                          tx_dlc(m) if kind == "tx" else m.get("dlc", 8), sender if kind == "tx" else NO_RECEIVER,
                          comment="raw message, %s" % ("sent by the PLC" if kind == "tx" else "received"),
                          cycle_ms=cycle or None, extended=bool(m.get("extended")))
            for j, sg in enumerate(m.get("signals") or []):
                msg.signals.append(Signal(
                    identifier(sg.get("name") or "s%d" % j), sg["start_bit"], sg["length"], signed=bool(sg.get("signed")),
                    receivers=[sender] if kind == "rx" else (), comment=sg.get("comment", ""),
                    scale=sg.get("scale", 1), offset=sg.get("offset", 0), unit=sg.get("unit", ""),
                    big_endian=sg.get("byte_order") == "big", minimum=sg.get("minimum"), maximum=sg.get("maximum")))
            mux_signals(m.get("signals") or [], msg.signals)
            out.append(msg)
    return out


def _no_slave(nets, network, what):
    """The master networks of `nets`; ExportFailed when `network` names a
    slave network or none is left (a slave network has no nodes to export:
    its own EDS is the file for the other master's tool)."""
    if network is not None and nets and nets[0]["role"] == "j1939":
        raise ExportFailed([("network '%s' is a J1939 network; it has no CANopen nodes to export as %s"
                             % (network, what), [nets[0]["path"]])])
    if network is not None and nets and nets[0]["role"] == "slave":
        raise ExportFailed([("network '%s' is a slave network; it has no nodes to export as %s (its EDS, %s, is "
                             "the file for the other master's tool)" % (network, what, nets[0]["slave"].get("eds")),
                             [nets[0]["path"]])])
    masters = [n for n in nets if n["role"] == "master"]
    if not masters:
        raise ExportFailed([("the config has no master network, so no nodes to export as %s" % what, ["networks"])])
    return masters


def network_file(path, network):
    """The file of one network when the export writes several:
    <stem>_<network>.dbc next to `path`."""
    stem, ext = os.path.splitext(path)
    return "%s_%s%s" % (stem, network, ext or ".dbc")


def write_file(text, path):
    """Writes the DBC through a temporary file and a rename."""
    folder = os.path.dirname(os.path.abspath(path))
    fd, tmp = tempfile.mkstemp(prefix="." + os.path.basename(path) + ".", dir=folder)
    try:
        with os.fdopen(fd, "w", encoding="ascii", newline="") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise
    return path
