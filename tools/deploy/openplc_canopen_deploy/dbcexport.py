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
from . import eds as eds_mod
from .iec import CO_TYPES, CO_TYPE_BY_CODE, parse_location

SDO_OPTIONS = ("none", "config", "all")
MASTER = "Master"
NO_RECEIVER = "Vector__XXX"

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
    def __init__(self, name, start, length, signed=False, float_kind=0, receivers=(), comment="",
                 mux=None, multiplexer=False, values=None):
        self.name, self.start, self.length = name, start, length
        self.signed, self.float_kind = signed, float_kind  # float_kind: 0, 1 (single) or 2 (double)
        self.receivers = list(receivers)
        self.comment, self.mux, self.multiplexer = comment, mux, multiplexer
        self.values = values or []  # [(value, text)]

    def range(self):
        if self.float_kind:
            return 0, 0
        if self.signed:
            return -(1 << (self.length - 1)), (1 << (self.length - 1)) - 1
        return 0, (1 << self.length) - 1


class Message:
    def __init__(self, cob_id, name, length, sender, comment="", cycle_ms=None):
        self.cob_id, self.name, self.length, self.sender = cob_id, name, length, sender
        self.comment, self.cycle_ms = comment, cycle_ms
        self.signals = []


class Model:
    def __init__(self, nodes, messages, comment, warnings):
        self.nodes, self.messages, self.comment, self.warnings = nodes, messages, comment, warnings


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
    <project>/canopen/<file> and <project> has project.json. None otherwise."""
    folder = os.path.dirname(os.path.abspath(config_path))
    root = os.path.dirname(folder)
    if os.path.basename(folder) != "canopen" or not os.path.isfile(os.path.join(root, "project.json")):
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


def _node_identifiers(cfg):
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


def _pdo_messages(n, node_name, eds, pdos, cfg, names, warnings):
    sync_us = _u(cfg["master"].get("sync_period_us"), 0)
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
            msg = Message(cob, "%s_%s%d" % (node_name, kind, num), (total + 7) // 8,
                          node_name if tx else MASTER,
                          "node %d %s %d, transmission %s%s" % (n_id(n), kind, num,
                                                                 trans if trans is not None else "not set", source),
                          cycle)
            receiver = MASTER if tx else node_name
            taken = _Names()
            bit = 0
            for index, sub, length in layout:
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
                if entry:
                    what = "-> " + loc_text
                elif tx:
                    what = "(not used by the PLC)"
                else:
                    what = "(not used by the PLC, sent as 0 by the master)"
                msg.signals.append(Signal(name, bit, length, signed, float_kind, [receiver],
                                          "0x%04X:%d %s %s" % (index, sub, type_name or "unknown type", what)))
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


def _sdo_messages(n, node_name, eds, option):
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
            data.append(Signal(name, 32, length, signed, float_kind, [receiver],
                               "0x%04X:%d %s%s" % (index, sub, type_name, ", " + comment if comment else ""),
                               mux=value))
        msg.signals.append(Signal("Object", 8, 24, receivers=[receiver], multiplexer=True,
                                  comment="index + subindex * 65536 (bytes 1-3 of the frame)", values=table))
        msg.signals += data
        msgs.append(msg)
    return msgs


def build(cfg, config_path, eds_paths=None, sdo="none", names=None):
    """The DBC model of a checked config. Raises ExportFailed with the config
    checks' errors. `names`: plc_names() of the editor project, or None."""
    if sdo not in SDO_OPTIONS:
        raise ValueError("sdo must be one of %s" % ", ".join(SDO_OPTIONS))
    paths = eds_paths if eds_paths is not None else bundle.eds_files(cfg, config_path)
    result = contract.check_config(cfg, config_path, eds_paths=paths)
    if not result.ok:
        raise ExportFailed([(i["message"], i["paths"]) for i in result.items if i["level"] == "error"])
    warnings = list(result.warnings)
    eds_list = _load_eds(cfg, config_path, paths)
    pdos = _normalized_pdos(cfg)
    node_names = _node_identifiers(cfg)
    messages = []
    for n, eds, norm, node_name in zip(cfg["nodes"], eds_list, pdos, node_names):
        node_id = n_id(n)
        messages += _pdo_messages(n, node_name, eds, norm, cfg, names, warnings)
        hb = Message(0x700 + node_id, "%s_Heartbeat" % node_name, 1, node_name, "node %d heartbeat" % node_id)
        hb.signals.append(Signal("NMT_State", 0, 7, receivers=[MASTER], values=NMT_STATES))
        messages.append(hb)
        em = Message(0x80 + node_id, "%s_EMCY" % node_name, 8, node_name, "node %d emergency" % node_id)
        em.signals += [Signal("Error_Code", 0, 16, receivers=[MASTER]),
                       Signal("Error_Register", 16, 8, receivers=[MASTER]),
                       Signal("Manufacturer_Data", 24, 40, receivers=[MASTER])]
        messages.append(em)
        if sdo != "none":
            messages += _sdo_messages(n, node_name, eds, sdo)
    nmt = Message(0x000, "NMT", 2, MASTER, "NMT node control; Node_ID 0 addresses all nodes")
    nmt.signals += [Signal("Command", 0, 8, receivers=node_names or [NO_RECEIVER], values=NMT_COMMANDS),
                    Signal("Node_ID", 8, 8, receivers=node_names or [NO_RECEIVER])]
    messages.append(nmt)
    # Without a SYNC period the master produces no SYNC.
    if _u(cfg["master"].get("sync_period_us"), 0):
        messages.append(Message(0x080, "SYNC", 0, MASTER, "SYNC"))
    comment = "CANopen network of %s, exported by openplc-canopen-deploy %s" % (
        os.path.basename(config_path), __version__)
    return Model([MASTER] + node_names, messages, comment, warnings)


# -- writing ------------------------------------------------------------------

def write(model):
    """The model as DBC text (ASCII, CRLF)."""
    L = ['VERSION ""', "", "NS_ :", "\tNS_DESC_", "\tCM_", "\tBA_DEF_", "\tBA_", "\tVAL_", "\tBA_DEF_DEF_",
         "\tSIG_VALTYPE_", "", "BS_:", "", "BU_: " + " ".join(model.nodes), ""]
    for m in model.messages:
        L.append("BO_ %d %s: %d %s" % (m.cob_id, m.name, m.length, m.sender))
        for s in m.signals:
            mux = " M" if s.multiplexer else (" m%d" % s.mux if s.mux is not None else "")
            lo, hi = s.range()
            L.append(' SG_ %s%s : %d|%d@1%s (1,0) [%d|%d] "" %s'
                     % (s.name, mux, s.start, s.length, "-" if s.signed else "+", lo, hi,
                        ",".join(s.receivers) or NO_RECEIVER))
        L.append("")
    L.append('CM_ "%s";' % _ascii(model.comment))
    for m in model.messages:
        if m.comment:
            L.append('CM_ BO_ %d "%s";' % (m.cob_id, _ascii(m.comment)))
        for s in m.signals:
            if s.comment:
                L.append('CM_ SG_ %d %s "%s";' % (m.cob_id, s.name, _ascii(s.comment)))
    L.append('BA_DEF_ BO_ "GenMsgCycleTime" INT 0 65535;')
    L.append('BA_DEF_DEF_ "GenMsgCycleTime" 0;')
    for m in model.messages:
        if m.cycle_ms:
            L.append('BA_ "GenMsgCycleTime" BO_ %d %d;' % (m.cob_id, min(m.cycle_ms, 65535)))
    for m in model.messages:
        for s in m.signals:
            if s.values:
                L.append("VAL_ %d %s %s ;" % (m.cob_id, s.name,
                                              " ".join('%d "%s"' % (v, _ascii(t)) for v, t in s.values)))
    for m in model.messages:
        for s in m.signals:
            if s.float_kind:
                L.append("SIG_VALTYPE_ %d %s : %d;" % (m.cob_id, s.name, s.float_kind))
    return "\r\n".join(L) + "\r\n"


def export(cfg, config_path, eds_paths=None, sdo="none", names=None):
    """(DBC text, warnings [str]). Raises ExportFailed."""
    model = build(cfg, config_path, eds_paths, sdo, names)
    return write(model), model.warnings


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
