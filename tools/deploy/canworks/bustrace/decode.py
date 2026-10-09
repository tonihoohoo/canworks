"""CANopen decoding of trace frames (canopen-bus-trace: "CANopen decoding").

The PDO layouts, signal names (PLC variable names in editor-project mode),
heartbeat and EMCY identifiers come from the DBC export's model
(dbcexport.build), so the trace shows the same names as the exported DBC.
SDO object names and types come from the nodes' EDS files. Without a config
(or with one that does not check) the predefined connection set of CiA 301
is used. A trace records one network: with several networks in the config
the decoder takes the traced network's nodes (`network`). A J1939 network
(`"protocol": "j1939"`) gets a j1939.J1939Decoder instead. Raw messages of
the network's `raw` object (spec can-raw-messages) decode on every network
where the protocol does not use the identifier; a plain CAN network
(`"protocol": "none"`) decodes nothing else.

    dec = Decoder.from_config(cfg, config_path, names=dbcexport.plc_names(uses), network="drives")
    d = dec.decode(frame)   # Decoded: kind, node, name, text, signals

decode() keeps state for segmented SDO transfers: feed it the frames in
order (reset() before a new pass).
"""

import os
import re
import struct

from .. import bundle, contract, dbcexport, diag, edslint
from .. import eds as eds_mod
from ..iec import CO_TYPE_BY_CODE
from .model import Frame

# J1939 kinds (j1939.py) come last so the CANopen codes stay as they were.
KINDS = ("nmt", "sync", "time", "emcy", "heartbeat", "sdo", "pdo", "lss", "error", "gap", "other",
         "pgn", "claim", "request", "ack", "tp", "raw")
# Kinds whose frames a later frame's decoding depends on (segmented SDO
# transfers, J1939 transport sessions): decoded again before a window.
CONTEXT_KINDS = ("sdo", "tp")

NMT_COMMANDS = {1: "start", 2: "stop", 128: "enter pre-operational", 129: "reset node", 130: "reset communication"}
HB_STATES = {0: "boot-up", 4: "STOPPED", 5: "OPERATIONAL", 127: "PRE-OPERATIONAL"}
ERROR_REGISTER_BITS = ((0, "generic"), (1, "current"), (2, "voltage"), (3, "temperature"), (4, "communication"),
                       (5, "device profile"), (7, "manufacturer"))
LSS_COMMANDS = {
    0x04: "switch state global", 0x11: "configure node ID", 0x13: "configure bit timing",
    0x15: "activate bit timing", 0x17: "store configuration", 0x40: "switch selective vendor",
    0x41: "switch selective product", 0x42: "switch selective revision", 0x43: "switch selective serial",
    0x44: "switch selective response", 0x46: "identify remote slave vendor",
    0x47: "identify remote slave product", 0x48: "identify revision low", 0x49: "identify revision high",
    0x4A: "identify serial low", 0x4B: "identify serial high", 0x4C: "identify non-configured remote slave",
    0x4F: "identify slave", 0x50: "identify non-configured slave", 0x51: "fastscan",
    0x5A: "inquire vendor", 0x5B: "inquire product", 0x5C: "inquire revision", 0x5D: "inquire serial",
    0x5E: "inquire node ID",
}
# SocketCAN error classes (linux/can/error.h), bit of the CAN ID.
ERROR_CLASSES = ((0x001, "TX timeout"), (0x002, "lost arbitration"), (0x004, "controller problem"),
                 (0x008, "protocol violation"), (0x010, "transceiver status"), (0x020, "no acknowledgement"),
                 (0x040, "bus-off"), (0x080, "bus error"), (0x100, "controller restarted"))
CONTROLLER_BITS = ((0x01, "RX overflow"), (0x02, "TX overflow"), (0x04, "RX warning"), (0x08, "TX warning"),
                   (0x10, "RX passive"), (0x20, "TX passive"), (0x40, "back to error active"))


class Decoded:
    __slots__ = ("kind", "node", "name", "text", "signals")

    def __init__(self, kind, node=None, name="", text="", signals=None):
        self.kind, self.node, self.name, self.text = kind, node, name, text
        self.signals = signals or []  # [(series key, value)]

    def as_dict(self):
        return {"kind": self.kind, "node": self.node, "name": self.name, "text": self.text}


class PdoLayout:
    """A configured PDO: message name, node, direction and its signals as
    (key, display name, start bit, length, signed, float kind, type name)."""

    def __init__(self, cob_id, name, node, tx, signals, length=None, info=None):
        self.cob_id, self.name, self.node, self.tx, self.signals = cob_id, name, node, tx, signals
        self.length = length  # bytes, from the mapping
        self.transmission = None  # transmission type, when the config or the EDS gives it
        # per signal: {"index", "subindex", "type", "location", "variables", "used"} (frame explanation)
        self.info = info or [{} for _ in signals]


_SIGNAL_COMMENT = re.compile(r"0x([0-9A-Fa-f]{4}):(\d+) (\S+) (.*)$")


def _signal_info(comment):
    """What the DBC model's signal comment says: object, type and the PLC
    location (dbcexport._pdo_messages writes "0xIIII:S TYPE -> %IW100 (name)")."""
    m = _SIGNAL_COMMENT.match(comment or "")
    if not m:
        return {}
    out = {"index": int(m.group(1), 16), "subindex": int(m.group(2)), "type": m.group(3), "used": False,
           "location": None, "variables": []}
    what = m.group(4)
    if what.startswith("-> "):
        loc = what[3:]
        out["used"] = True
        out["location"] = loc.split(" ", 1)[0]
        if "(" in loc:
            out["variables"] = [v.strip() for v in loc[loc.index("(") + 1:loc.rindex(")")].split(",")]
    return out


def _bits(data, start, length):
    v = int.from_bytes(data.ljust(8, b"\0"), "little")
    return (v >> start) & ((1 << length) - 1)


def signal_value(data, start, length, signed, float_kind):
    raw = _bits(data, start, length)
    if float_kind == 1 and length == 32:
        return struct.unpack("<f", raw.to_bytes(4, "little"))[0]
    if float_kind == 2 and length == 64:
        return struct.unpack("<d", raw.to_bytes(8, "little"))[0]
    if signed and raw & (1 << (length - 1)):
        raw -= 1 << length
    return raw


def _value_text(v):
    if isinstance(v, float):
        return "%g" % v
    return str(v)


def error_register_text(reg):
    names = [n for bit, n in ERROR_REGISTER_BITS if reg & (1 << bit)]
    return ", ".join(names) if names else "none"


def error_frame_text(f):
    classes = [n for bit, n in ERROR_CLASSES if f.can_id & bit]
    if f.can_id & 0x004 and len(f.data) > 1:
        ctrl = [n for bit, n in CONTROLLER_BITS if f.data[1] & bit]
        if ctrl:
            classes.append("(%s)" % ", ".join(ctrl))
    return " ".join(classes) or "error frame"


def network_entry(cfg, network=None):
    """The contract.networks() entry of `network` (or of the config's only
    network), else None."""
    if not isinstance(cfg, dict):
        return None
    nets = contract.networks(cfg)
    found = [n for n in nets if n["name"] == network] if network is not None else nets if len(nets) == 1 else []
    return found[0] if found else None


def j1939_network(cfg, network=None):
    """The contract.networks() entry of `network` (or of the config's only
    network) when its protocol is "j1939", else None."""
    net = network_entry(cfg, network)
    return net if net is not None and net["json"].get("protocol") == "j1939" else None


def _slave_config(net, eds_paths):
    """A version 1 style config with the PLC as the one node of a slave
    network (contract.networks() entry): its PDOs are the default mappings
    of its own EDS, the objects it binds carry their PLC locations."""
    s = net["slave"]
    nid = dbcexport._u(s.get("node_id"))
    with open(eds_paths[s["eds"]], "rb") as f:
        text, _, _ = edslint.check(f.read(), nid)
    eds = eds_mod.Eds.read(s["eds"], text)
    bound = {(dbcexport._u(o.get("index")), dbcexport._u(o.get("subindex"), 0)): o
             for o in s.get("objects") or [] if isinstance(o, dict)}
    node = {"node_id": nid, "name": net["name"] or "plc", "eds": s["eds"], "tx_pdos": [], "rx_pdos": []}
    for key, base in (("tx_pdos", 0x1A00), ("rx_pdos", 0x1600)):
        for k in range(512):
            mi = eds_mod.mapping_info(eds, base + k)
            if not eds.has(base + k) or not mi["has_default"]:
                continue
            entries = []
            for v in mi["defaults"]:
                index, sub = v >> 16, (v >> 8) & 0xFF
                o, obj = bound.get((index, sub)), eds.find(index, sub)
                if o and o.get("iec_location") and obj is not None and CO_TYPE_BY_CODE.get(obj.data_type):
                    entries.append({"index": "0x%04X" % index, "subindex": sub,
                                    "type": CO_TYPE_BY_CODE[obj.data_type], "iec_location": o["iec_location"]})
            pdo = {"number": k + 1, "mapping": "device", "entries": entries}
            comm = eds.find(base - 0x200 + k, 1)
            cob = comm.value(nid) if comm is not None else None
            if isinstance(cob, int) and not cob & 0x80000000:
                pdo["cob_id"] = cob & 0x7FF
            elif k >= 4:
                continue  # off in the EDS and no default: the other master gives it its COB-ID
            node[key].append(pdo)
    return {"schema_version": 1, "adapter": net["adapter"], "master": {}, "nodes": [node]}


def _config_problem(cfg, one, config_path, eds_paths, error):
    """Why the network `one` of the config `cfg` cannot be decoded with its
    PDOs, in the user's terms: a missing EDS file, else the first error of
    the config's check, without the config file's path."""
    paths = eds_paths if eds_paths is not None else bundle.eds_files(one, config_path)
    for n in one.get("nodes") or []:
        path = paths.get(n.get("eds")) if isinstance(n, dict) else None
        if path and not os.path.isfile(path):
            return "node %s: the EDS file %s is missing" % (n.get("node_id"), os.path.basename(path))
    try:
        result = contract.check_config(cfg, config_path, eds_paths=eds_paths)
        errors = [i["message"] for i in result.items if i["level"] == "error"]
    except Exception:  # noqa: BLE001 - the build's own error is named instead
        errors = []
    text = errors[0] if errors else (str(error).splitlines() or [""])[0] or type(error).__name__
    for prefix in (config_path, os.path.abspath(config_path)):
        if text.startswith(prefix + ": "):
            text = text[len(prefix) + 2:]
    return text


class Decoder:
    """Decodes frames for one configuration (or none). A J1939 network gets
    a j1939.J1939Decoder, a subclass with protocol "j1939"."""

    protocol = "canopen"

    def __init__(self):
        self.node_names = {}   # node id -> config name
        self.eds = {}          # node id -> Eds
        self.pdos = {}         # cob id -> PdoLayout
        self.sync_cob = 0x080
        self.time_cob = 0x100
        self.master_id = None
        self.sync_window_us = None
        self.sync_period_us = None
        self.warnings = []
        self.raw = None        # raw.decode.RawDecoder of the network's raw messages
        self.raw_owner = None  # use(id, ext): what the protocol uses an identifier for
        self.reset()

    def attach_raw(self, net):
        """The raw messages of a contract.networks() entry."""
        from ..raw import ownership
        from ..raw.decode import RawDecoder
        raw = net["json"].get("raw") if isinstance(net["json"].get("raw"), dict) else None
        if raw and (raw.get("rx") or raw.get("tx")):
            self.raw = RawDecoder(raw)
            self.raw_owner = ownership.protocol_use(net)

    def decode_raw(self, f):
        """A Decoded for a frame of a configured raw message, else None."""
        if self.raw is None or f.gap or f.err:
            return None
        if self.raw_owner is not None and self.raw_owner(f.can_id, f.ext):
            return None
        found = self.raw.decode(f.can_id, f.ext, f.data, f.rtr)
        if not found:
            return None
        sigs = [("%s.%s" % (name, sname), scaled if scaled is not None else value)
                for name, values in found for sname, value, scaled, _ in values]
        return Decoded("raw", None, " / ".join(name for name, _ in found),
                       self.raw.text(f.can_id, f.ext, f.data, f.rtr), sigs)

    @classmethod
    def from_config(cls, cfg, config_path, eds_paths=None, names=None, network=None):
        """A decoder for a config, with the nodes of its network `network`
        (needed when it has several). A config that does not pass the checks,
        or has no such network, still decodes with the predefined connection
        set; the reason is in `warnings`."""
        d = cls()
        if not cfg:
            return d
        entry = network_entry(cfg, network)
        if entry is not None and entry["json"].get("protocol") == "none":
            d = PlainDecoder()
            d.attach_raw(entry)
            return d
        net = j1939_network(cfg, network)
        if net is not None:
            from .j1939 import J1939Decoder
            d = J1939Decoder.from_network(net, config_path)
            d.attach_raw(net)
            return d
        if entry is not None:
            d.attach_raw(entry)
        full = cfg
        try:
            cfg = contract.network_config(cfg, network)
        except ValueError as e:
            d.warnings.append("decoding without the config's nodes: %s" % e)
            return d
        slave = next((n for n in contract.networks(full) if n["role"] == "slave" and n["name"] == network
                      and n["slave"]), None) if network is not None else None
        if slave is not None:
            # A slave network: the PLC is the one node, with its EDS's PDOs.
            eds_paths = eds_paths if eds_paths is not None else bundle.eds_files(full, config_path)
            try:
                cfg = _slave_config(slave, eds_paths)
            except Exception as e:  # noqa: BLE001 - decodes without the PDOs, says why
                d.warnings.append("decoding without the config's PDOs: %s" % _config_problem(
                    full, {"nodes": [slave["slave"]]}, config_path, eds_paths, e))
                return d
        master = cfg.get("master") or {}
        d.master_id = dbcexport._u(master.get("node_id"))
        d.sync_window_us = dbcexport._u(master.get("sync_window_us")) or None
        d.sync_period_us = dbcexport._u(master.get("sync_period_us")) or None
        tc = master.get("time_cob_id")
        if tc is not None and dbcexport._u(tc) is not None:
            d.time_cob = dbcexport._u(tc) & 0x7FF
        for n in cfg.get("nodes") or []:
            nid = dbcexport._u(n.get("node_id"))
            if nid is not None:
                d.node_names[nid] = n.get("name") or "node%d" % nid
        # The network as the configurator's check passed it (a version 2
        # config's PDO entries fed by a gateway route have no PLC location,
        # which the version 1 schema would refuse); only when that build
        # fails does the check name the config's problem.
        try:
            model = dbcexport.build(cfg, config_path, eds_paths=eds_paths, sdo="none", names=names, checked=True)
            eds_list = dbcexport._load_eds(cfg, config_path, eds_paths)
        except Exception as e:  # noqa: BLE001 - a config that does not check still decodes without its PDOs
            d.warnings.append("decoding without the config's PDOs: %s" % _config_problem(full, cfg, config_path, eds_paths, e))
            return d
        d.warnings += model.warnings
        for n, eds in zip(cfg["nodes"], eds_list):
            d.eds[dbcexport.n_id(n)] = eds
        by_node_name = {}
        for nid, name in zip([dbcexport.n_id(n) for n in cfg["nodes"]], model.nodes[1:]):
            by_node_name[name] = nid
        for m in model.messages:
            if "PDO" not in m.name.rsplit("_", 1)[-1]:
                continue
            tx = "_TPDO" in m.name
            node_ident = m.sender if tx else next((s.receivers[0] for s in m.signals if s.receivers), None)
            node = by_node_name.get(node_ident)
            sigs, info = [], []
            for s in m.signals:
                type_name = s.comment.split(" ", 2)[1] if s.comment.startswith("0x") else ""
                sigs.append(("%s.%s" % (m.name, s.name), s.name, s.start, s.length, s.signed, s.float_kind, type_name))
                info.append(_signal_info(s.comment))
            d.pdos[m.cob_id] = PdoLayout(m.cob_id, m.name, node, tx, sigs, m.length, info)
            tm = re.search(r"transmission (\d+)", m.comment or "")
            d.pdos[m.cob_id].transmission = int(tm.group(1)) if tm else None
        return d

    def reset(self):
        self.sdo_state = {}  # node -> segmented transfer in progress

    def clone(self):
        """The same decoder with its own SDO transfer state."""
        import copy
        d = copy.copy(self)
        d.reset()
        return d

    # -- helpers --------------------------------------------------------------
    def node_label(self, nid):
        name = self.node_names.get(nid)
        return "node %d (%s)" % (nid, name) if name else "node %d" % nid

    def object_label(self, nid, index, sub):
        eds = self.eds.get(nid)
        text = "0x%04X:%d" % (index, sub)
        if eds is not None:
            parent, name = eds.object_name(index, sub)
            if parent and name:
                text += " %s / %s" % (parent, name)
            elif name or parent:
                text += " " + (name or parent)
        return text

    def object_type(self, nid, index, sub):
        eds = self.eds.get(nid)
        obj = eds.find(index, sub) if eds is not None else None
        if obj is None:
            return None
        return obj.type_name or diag.TYPE_CODES.get(obj.data_type)

    def value_text(self, nid, index, sub, data):
        t = self.object_type(nid, index, sub)
        if t:
            return diag.decode(t, data)["text"]
        if 0 < len(data) <= 4:
            v = int.from_bytes(data, "little")
            return "%d (0x%0*X)" % (v, len(data) * 2, v)
        return diag.hex_bytes(data) or "(empty)"

    def signal_keys(self):
        """[(key, label, node)] of every decodable PDO and raw message signal."""
        out = []
        for p in sorted(self.pdos.values(), key=lambda p: p.cob_id):
            for key, name, *_ in p.signals:
                out.append((key, "%s %s" % (p.name, name), p.node))
        for _, m in (self.raw.entries if self.raw is not None else []):
            mname = m.get("name") or "0x%X" % m["id"]
            for j, sg in enumerate(m.get("signals") or []):
                sname = sg.get("name") or "s%d" % j
                out.append(("%s.%s" % (mname, sname), "%s %s" % (mname, sname), None))
        return out

    # -- decoding -------------------------------------------------------------
    def decode(self, f):
        if f.gap:
            return Decoded("gap", text="capture restarted (frames may be missing)")
        if f.err:
            return Decoded("error", name="error frame", text=error_frame_text(f))
        r = self.decode_raw(f)
        if r is not None:
            return r
        if f.ext:
            return Decoded("other")
        cid = f.can_id
        d = f.data
        if cid == 0x000:
            if len(d) >= 2:
                cmd = NMT_COMMANDS.get(d[0], "command 0x%02X" % d[0])
                target = "all nodes" if d[1] == 0 else self.node_label(d[1])
                return Decoded("nmt", d[1] or None, "NMT", "%s %s" % (cmd, target))
            return Decoded("nmt", None, "NMT", "malformed")
        if cid in self.pdos:
            return self._pdo(f, self.pdos[cid])
        if cid == self.sync_cob:
            return Decoded("sync", None, "SYNC", "counter %d" % d[0] if d else "")
        if cid == self.time_cob:
            return Decoded("time", None, "TIME", self._time_text(d))
        if 0x081 <= cid <= 0x0FF:
            return self._emcy(f, cid - 0x80)
        if 0x701 <= cid <= 0x77F:
            nid = cid - 0x700
            if f.rtr:
                return Decoded("heartbeat", nid, "Node guarding", "request to %s" % self.node_label(nid))
            state = d[0] & 0x7F if d else None
            text = HB_STATES.get(state, "state %s" % state)
            if d and d[0] & 0x80:
                text += " (toggle)"
            return Decoded("heartbeat", nid, "Boot-up" if state == 0 else "Heartbeat",
                           "%s %s" % (self.node_label(nid), text))
        if 0x581 <= cid <= 0x5FF:
            return self._sdo(f, cid - 0x580, server=True)
        if 0x601 <= cid <= 0x67F:
            return self._sdo(f, cid - 0x600, server=False)
        if cid in (0x7E4, 0x7E5):
            return self._lss(f, cid == 0x7E5)
        for base, kind, tx in ((0x180, "TPDO", True), (0x200, "RPDO", False)):
            for k in range(4):
                lo = base + 0x100 * k
                if lo + 1 <= cid <= lo + 0x7F:
                    nid = cid - lo
                    return Decoded("pdo", nid, "%s%d" % (kind, k + 1),
                                   "%s %s" % (self.node_label(nid), diag.hex_bytes(d)))
        return Decoded("other")

    def _time_text(self, d):
        if len(d) < 6:
            return diag.hex_bytes(d)
        ms = int.from_bytes(d[:4], "little") & 0x0FFFFFFF
        days = int.from_bytes(d[4:6], "little")
        return "day %d since 1984-01-01, %02d:%02d:%02d.%03d" % (days, ms // 3600000, ms // 60000 % 60,
                                                                  ms // 1000 % 60, ms % 1000)

    def _pdo(self, f, p):
        if f.rtr:
            return Decoded("pdo", p.node, p.name, "remote request")
        parts, sigs = [], []
        total_bits = len(f.data) * 8
        for key, name, start, length, signed, float_kind, _t in p.signals:
            if start + length > total_bits:
                parts.append("%s=?" % name)
                continue
            v = signal_value(f.data, start, length, signed, float_kind)
            parts.append("%s=%s" % (name, _value_text(v)))
            sigs.append((key, v))
        return Decoded("pdo", p.node, p.name, ", ".join(parts), sigs)

    def _emcy(self, f, nid):
        d = f.data
        if len(d) < 3:
            return Decoded("emcy", nid, "EMCY", "%s malformed" % self.node_label(nid))
        code = int.from_bytes(d[:2], "little")
        reg = d[2]
        if code == 0:
            text = "%s error reset, register 0x%02X" % (self.node_label(nid), reg)
        else:
            text = "%s 0x%04X %s, register 0x%02X (%s)" % (self.node_label(nid), code, diag.emcy_class(code), reg,
                                                           error_register_text(reg))
        if len(d) > 3 and any(d[3:]):
            text += ", manufacturer %s" % diag.hex_bytes(d[3:])
        return Decoded("emcy", nid, "EMCY", text, [("emcy.%d" % nid, code)])

    def _sdo(self, f, nid, server):
        d = f.data
        who = self.node_label(nid)
        name = "SDO response" if server else "SDO request"
        if len(d) < 1:
            return Decoded("sdo", nid, name, "%s malformed" % who)
        cs = d[0] >> 5
        mux = (int.from_bytes(d[1:3], "little"), d[3]) if len(d) >= 4 else (0, 0)
        if d[0] != 0x80 and (nid, "b") in self.sdo_state:
            out = self._sdo_block(f, nid, server, name, who)
            if out is not None:
                return out
        if cs == 4:
            code = int.from_bytes(d[4:8], "little") if len(d) >= 8 else 0
            self.sdo_state.pop((nid, "x"), None)
            self.sdo_state.pop((nid, "b"), None)
            return Decoded("sdo", nid, name, "%s abort %s: 0x%08X %s" % (
                who, self.object_label(nid, *mux), code, diag.abort_text(code)), [("sdo_abort.%d" % nid, code)])
        if not server:
            if cs == 1:  # initiate download
                e, s = d[0] & 0x02, d[0] & 0x01
                if e:
                    size = 4 - ((d[0] >> 2) & 3) if s else 4
                    data = d[4:4 + size]
                    return Decoded("sdo", nid, name, "%s write %s = %s" % (
                        who, self.object_label(nid, *mux), self.value_text(nid, mux[0], mux[1], data)))
                size = int.from_bytes(d[4:8], "little") if s else None
                self.sdo_state[(nid, "x")] = {"dir": "write", "mux": mux, "data": bytearray(), "size": size}
                return Decoded("sdo", nid, name, "%s write %s, %s bytes (segmented)" % (
                    who, self.object_label(nid, *mux), size if size is not None else "?"))
            if cs == 0:  # download segment
                st = self.sdo_state.get((nid, "x"))
                n = 7 - ((d[0] >> 1) & 7)
                last = d[0] & 1
                if st and st["dir"] == "write":
                    st["data"] += d[1:1 + n]
                    if last:
                        self.sdo_state.pop((nid, "x"), None)
                        return Decoded("sdo", nid, name, "%s write %s = %s (segmented, done)" % (
                            who, self.object_label(nid, *st["mux"]),
                            self.value_text(nid, st["mux"][0], st["mux"][1], bytes(st["data"]))))
                return Decoded("sdo", nid, name, "%s download segment%s" % (who, ", last" if last else ""))
            if cs == 2:
                return Decoded("sdo", nid, name, "%s read %s" % (who, self.object_label(nid, *mux)))
            if cs == 3:
                return Decoded("sdo", nid, name, "%s upload segment request" % who)
            if cs == 6 and not d[0] & 1:  # initiate block download
                size = int.from_bytes(d[4:8], "little") if d[0] & 2 else None
                self.sdo_state[(nid, "b")] = {"dir": "write", "phase": "init", "mux": mux, "data": bytearray(),
                                              "sub": [], "last": False}
                return Decoded("sdo", nid, name, "%s write %s, %s bytes (block)" % (
                    who, self.object_label(nid, *mux), size if size is not None else "?"))
            if cs == 5 and d[0] & 3 == 0:  # initiate block upload
                self.sdo_state[(nid, "b")] = {"dir": "read", "phase": "init", "mux": mux, "data": bytearray(),
                                              "sub": [], "last": False}
                return Decoded("sdo", nid, name, "%s read %s (block)" % (who, self.object_label(nid, *mux)))
            if cs in (5, 6):
                return Decoded("sdo", nid, name, "%s block %s" % (who, "upload" if cs == 5 else "download"))
            return Decoded("sdo", nid, name, "%s command 0x%02X" % (who, d[0]))
        # server -> client
        if cs == 3:
            return Decoded("sdo", nid, name, "%s write %s confirmed" % (who, self.object_label(nid, *mux)))
        if cs == 2:  # initiate upload response
            self.sdo_state.pop((nid, "b"), None)  # the server chose a normal upload
            e, s = d[0] & 0x02, d[0] & 0x01
            if e:
                size = 4 - ((d[0] >> 2) & 3) if s else 4
                data = d[4:4 + size]
                return Decoded("sdo", nid, name, "%s read %s = %s" % (
                    who, self.object_label(nid, *mux), self.value_text(nid, mux[0], mux[1], data)))
            size = int.from_bytes(d[4:8], "little") if s else None
            self.sdo_state[(nid, "x")] = {"dir": "read", "mux": mux, "data": bytearray(), "size": size}
            return Decoded("sdo", nid, name, "%s read %s, %s bytes (segmented)" % (
                who, self.object_label(nid, *mux), size if size is not None else "?"))
        if cs == 0:  # upload segment
            st = self.sdo_state.get((nid, "x"))
            n = 7 - ((d[0] >> 1) & 7)
            last = d[0] & 1
            if st and st["dir"] == "read":
                st["data"] += d[1:1 + n]
                if last:
                    self.sdo_state.pop((nid, "x"), None)
                    return Decoded("sdo", nid, name, "%s read %s = %s (segmented, done)" % (
                        who, self.object_label(nid, *st["mux"]),
                        self.value_text(nid, st["mux"][0], st["mux"][1], bytes(st["data"]))))
            return Decoded("sdo", nid, name, "%s upload segment%s" % (who, ", last" if last else ""))
        if cs == 1:
            return Decoded("sdo", nid, name, "%s download segment confirmed" % who)
        if cs in (5, 6):
            return Decoded("sdo", nid, name, "%s block %s" % (who, "download" if cs == 5 else "upload"))
        return Decoded("sdo", nid, name, "%s command 0x%02X" % (who, d[0]))

    def _sdo_block(self, f, nid, server, name, who):
        """A frame of a block transfer in progress, or None when it is not one
        (the transfer is then forgotten)."""
        d = f.data
        st = self.sdo_state[(nid, "b")]
        sender = server == (st["dir"] == "read")  # this frame comes from the side sending data
        cs = d[0] >> 5
        mux = st["mux"]
        if st["phase"] == "data" and sender:
            st["sub"].append(bytes(d[1:8]))
            if d[0] & 0x80:
                st["last"] = True
            return Decoded("sdo", nid, name, "%s block segment %d%s" % (who, d[0] & 0x7F, ", last" if d[0] & 0x80 else ""))
        if st["phase"] == "data" and not sender and d[0] == 0xA2:
            ack = d[1] if len(d) > 1 else 0
            for seg in st["sub"][:ack]:
                st["data"] += seg
            if ack < len(st["sub"]):
                st["last"] = False  # the rest is sent again
            st["sub"] = []
            if st["last"]:
                st["phase"] = "end"
            return Decoded("sdo", nid, name, "%s block acknowledged %d segments" % (who, ack))
        if st["dir"] == "write":
            if st["phase"] == "init" and server and cs == 5 and d[0] & 3 == 0:
                st["phase"] = "data"
                return Decoded("sdo", nid, name, "%s block write %s accepted, %d segments per block" % (
                    who, self.object_label(nid, *mux), d[4] if len(d) > 4 else 0))
            if st["phase"] == "end" and not server and cs == 6 and d[0] & 1:
                unused = (d[0] >> 2) & 7
                data = bytes(st["data"][:len(st["data"]) - unused])
                st["phase"] = "done"
                return Decoded("sdo", nid, name, "%s write %s = %s (block, done)" % (
                    who, self.object_label(nid, *mux), self.value_text(nid, mux[0], mux[1], data)))
            if st["phase"] == "done" and server and d[0] == 0xA1:
                self.sdo_state.pop((nid, "b"), None)
                return Decoded("sdo", nid, name, "%s write %s confirmed (block)" % (who, self.object_label(nid, *mux)))
        else:
            if st["phase"] == "init" and server and cs == 6 and not d[0] & 1:
                size = int.from_bytes(d[4:8], "little") if d[0] & 2 else None
                st["phase"] = "start"
                return Decoded("sdo", nid, name, "%s read %s, %s bytes (block)" % (
                    who, self.object_label(nid, *mux), size if size is not None else "?"))
            if st["phase"] == "start" and not server and d[0] == 0xA3:
                st["phase"] = "data"
                return Decoded("sdo", nid, name, "%s block upload start" % who)
            if st["phase"] == "end" and server and cs == 6 and d[0] & 1:
                unused = (d[0] >> 2) & 7
                data = bytes(st["data"][:len(st["data"]) - unused])
                st["phase"] = "done"
                return Decoded("sdo", nid, name, "%s read %s = %s (block, done)" % (
                    who, self.object_label(nid, *mux), self.value_text(nid, mux[0], mux[1], data)))
            if st["phase"] == "done" and not server and d[0] == 0xA1:
                self.sdo_state.pop((nid, "b"), None)
                return Decoded("sdo", nid, name, "%s block upload finished" % who)
        self.sdo_state.pop((nid, "b"), None)
        return None

    def _lss(self, f, request):
        d = f.data
        if not d:
            return Decoded("lss", None, "LSS", "empty")
        cs = d[0]
        what = LSS_COMMANDS.get(cs, "command 0x%02X" % cs)
        detail = ""
        if cs == 0x04 and len(d) > 1:
            detail = " to %s" % ("configuration" if d[1] else "waiting")
        elif cs == 0x11 and len(d) > 1:
            detail = (" %d" % d[1]) if request else (" error %d" % d[1] if d[1] else " done")
        elif cs == 0x13 and len(d) > 2 and request:
            rates = {0: 1000, 1: 800, 2: 500, 3: 250, 4: 125, 6: 50, 7: 20, 8: 10}
            detail = " %s kbit/s" % rates.get(d[2], "index %d" % d[2])
        elif cs in (0x40, 0x41, 0x42, 0x43, 0x46, 0x47, 0x48, 0x49, 0x4A, 0x4B) and len(d) >= 5:
            detail = " 0x%08X" % int.from_bytes(d[1:5], "little")
        elif cs in (0x5A, 0x5B, 0x5C, 0x5D) and len(d) >= 5 and not request:
            detail = " = 0x%08X" % int.from_bytes(d[1:5], "little")
        elif cs == 0x5E and len(d) >= 2 and not request:
            detail = " = %d" % d[1]
        return Decoded("lss", None, "LSS", "%s %s%s" % ("request" if request else "answer", what, detail))


def decode_all(decoder, frames):
    """[Decoded] for frames in order (resets the SDO state first)."""
    decoder.reset()
    return [decoder.decode(f) for f in frames]


__all__ = ["Decoder", "Decoded", "decode_all", "signal_value", "j1939_network", "KINDS", "CONTEXT_KINDS", "Frame"]


class PlainDecoder(Decoder):
    """A plain CAN network (protocol "none"): its raw messages, nothing else."""

    protocol = "none"

    def decode(self, f):
        if f.gap or f.err:
            return super().decode(f)
        r = self.decode_raw(f)
        return r if r is not None else Decoded("other")
