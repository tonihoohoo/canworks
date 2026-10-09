"""Exports each configured node as a CiA 306 DCF (canopen-dcf-export spec).

The DCF is the node's EDS (the prepared copy the plugin uses) with a
ParameterValue on every sub-object the plugin writes during the node's
configuration download, a [DeviceComissioning] section and updated [FileInfo]
keys. The download is built the way the plugin builds it on the PLC
(plugin/src/canopen/dcf_gen.cpp): the dcfgen input of make_dcfgen_yaml(), Lely
dcfgen's own Slave/Master code (vendored as _lely_dcf/dcfgen_cli.py), then
the plugin's post-processing of generate_device_config(). CI compares the
result with `canopen_check --dump-writes` for the fixture configs.
"""

import datetime
import importlib.util
import os
import re
import shutil
import struct
import sys
import tempfile
import types
import warnings

from . import __version__, _lely_dcf, bundle, contract, edslint
from . import eds as eds_mod
from ._lely_dcf.parse import parse_file as _parse_file

NETWORK_NAME = "OpenPLC CANopen"
# CiA 306 bit rates for [DeviceComissioning] Baudrate (kbit/s).
BAUDRATES = (10, 20, 50, 125, 250, 500, 800, 1000)
# Objects whose writes are commands, not settings (store, restore): listed
# as boot steps in the DCF's comment, never as ParameterValue.
COMMAND_OBJECTS = (0x1010, 0x1011)
# Where a boot write comes from (Download.sources).
WRITE_SOURCES = {
    "pdo": "PDO configuration",
    "node": "node settings",
    "startup_sdo": "startup SDO",
    "config_check": "configuration check",
}


def _config_source(index):
    """The source of a write dcfgen generates from the config."""
    return "pdo" if 0x1400 <= index <= 0x1BFF else "node"


class ExportFailed(Exception):
    """The export stopped: `problems` is a list of (message, [JSON path])."""

    def __init__(self, problems):
        super().__init__("\n".join(m for m, _ in problems))
        self.problems = problems


# -- dcfgen ---------------------------------------------------------------

_CLI = None


def dcfgen_cli():
    """Lely's dcfgen module (vendored), with this package's Lely dcf as its
    `dcf`. Its em, yaml and pkg_resources imports serve only the master DCF
    output, which the export does not use, so stand-ins satisfy them."""
    global _CLI
    if _CLI is not None:
        return _CLI
    names = ("dcf", "em", "yaml", "pkg_resources")
    saved = {k: sys.modules.get(k) for k in names}
    try:
        sys.modules["dcf"] = _lely_dcf
        for k in names[1:]:
            sys.modules[k] = types.ModuleType(k)
        path = os.path.join(os.path.dirname(_lely_dcf.__file__), "dcfgen_cli.py")
        spec = importlib.util.spec_from_file_location(__package__ + "._lely_dcf.dcfgen_cli", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        for k, v in saved.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v
    _CLI = module
    return module


# -- the plugin's configuration download -----------------------------------

class Download:
    """A node's configuration download as the plugin performs it."""

    def __init__(self, node_id):
        self.node_id = node_id
        self.writes = []  # (index, sub-index, data bytes), in download order
        self.sources = []  # what each write comes from, as WRITE_SOURCES names it, same order
        self.restore = None  # 0x1011 sub-index restored before the download
        self.firmware = None  # software_file, downloaded at boot

    def final_values(self):
        """{(index, sub-index): data} after the whole download, without the
        command objects."""
        out = {}
        for index, sub, data in self.writes:
            if index not in COMMAND_OBJECTS:
                out[(index, sub)] = data
        return out

    def steps(self):
        """The boot steps that are not settings, in boot order, as text."""
        out = []
        if self.restore is not None:
            out.append("restores the default parameters (0x1011 sub %d \"load\") before the configuration"
                       % self.restore)
        if self.firmware:
            out.append("downloads the program file %s (0x1F50 sub 1) when the software version differs"
                       % self.firmware)
        for index, sub, data in self.writes:
            if index in COMMAND_OBJECTS:
                text = data.decode("latin-1") if all(32 <= b < 127 for b in data) else data.hex()
                out.append("writes \"%s\" to 0x%04X sub %d after the configuration" % (text, index, sub))
        return out


def _u(value, default=None):
    v = contract._uint(value) if value is not None else None
    return default if v is None else v


def _bitrate(cfg):
    a = cfg.get("adapter")
    if isinstance(a, dict):
        return _u(a.get("bitrate"), 0)
    return _u(cfg.get("bitrate"), 0)


def _fmt6(x):
    # The plugin writes multipliers as "%.6f" into the YAML.
    return float("%.6f" % x)


def _normalized_nodes(cfg):
    """The config's nodes with numbers resolved like the plugin's parser:
    PDO numbers (default: position), COB-IDs ("auto" and the defaults)."""
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
                cob = p.get("cob_id")
                if not isinstance(cob, int) or not cob:
                    p["cob_id"] = (0x80 if key == "tx_pdos" else 0x100) + 0x100 * p["number"] + node["node_id"]
    return nodes


def _pdo_numbers(dev, comm_base):
    """PDO numbers the EDS defines (communication and mapping object)."""
    return [n for n in range(1, 513) if comm_base + n - 1 in dev and comm_base + 0x200 + n - 1 in dev]


def _ro_pdo_comm(dev):
    """The EDS's read-only PDO communication sub-indices (plugin:
    find_fixed_pdo_params)."""
    out = set()
    for base in (0x1400, 0x1800):
        for n in range(1, 513):
            obj = dev.get(base + n - 1)
            if obj is None:
                continue
            for k, sub in obj.items():
                if k >= 1 and not sub.access_type.write:
                    out.add((base + n - 1, k))
    return out


def _emit_pdos(node_json, norm, dev, eds, ro, is_tx):
    """The node's `tpdo`/`rpdo` dcfgen entry (plugin: emit_pdos), or None."""
    key = "tx_pdos" if is_tx else "rx_pdos"
    comm_base = 0x1800 if is_tx else 0x1400
    present = _pdo_numbers(dev, comm_base)
    pdos = node_json.get(key, [])
    configured = {p["number"] for p in norm[key]}
    kept = {num for num in present if num not in configured and (comm_base + num - 1, 1) in ro}
    off = [num for num in present if num not in configured and num not in kept]
    if not pdos and not off:
        return None
    out = {}
    for p, pn in zip(pdos, norm[key]):
        num = pn["number"]
        entry = {"enabled": True, "cob_id": pn["cob_id"]}
        if "transmission" in p:
            entry["transmission"] = _u(p["transmission"])
        if "inhibit_time_us" in p:
            entry["inhibit_time"] = _u(p["inhibit_time_us"]) // 100
        if is_tx and "event_timer_ms" in p:
            entry["event_timer"] = _u(p["event_timer_ms"])
        if "sync_start" in p:
            entry["sync_start"] = _u(p["sync_start"])
        info = eds_mod.mapping_info(eds, comm_base + 0x200 + num - 1)
        if not eds_mod.uses_device_mapping(p, info):
            entry["mapping"] = [{"index": _u(e["index"]), "sub_index": _u(e.get("subindex", 0), 0)}
                                for e in p["entries"]]
        out[num] = entry
    for num in off:
        out[num] = {"enabled": False}
    return out


def dcfgen_input(cfg, node_json, norm, dcf_path, dev, eds, ro, software_path=None):
    """The node's part of the plugin's dcfgen YAML (make_dcfgen_yaml), as
    the dict yaml.safe_load would read."""
    n = node_json
    y = {"dcf": dcf_path, "node_id": norm["node_id"]}
    hb = _u(n.get("heartbeat_ms"), 0)
    if "heartbeat_ms" in n:
        y["heartbeat_producer"] = hb
    timeout = _u(n.get("heartbeat_timeout_ms")) if "heartbeat_timeout_ms" in n else min(hb * 3, 0xFFFF)
    y["heartbeat_multiplier"] = _fmt6(timeout / hb if hb else 3.0)
    guard = _u(n.get("guard_time_ms"), 0)
    life = _u(n.get("life_time_factor"), 0)
    if guard:
        y["guard_time"] = guard
        y["life_time_factor"] = life
    y["retry_factor"] = _u(n["retry_factor"]) if "retry_factor" in n else (life if guard else 0)
    y["boot"] = n.get("boot", True) is not False
    y["mandatory"] = n.get("mandatory", False) is True
    if "reset_communication" in n:
        y["reset_communication"] = n["reset_communication"] is True
    if "revision_number" in n:
        y["revision_number"] = _u(n["revision_number"])
    if "serial_number" in n:
        y["serial_number"] = _u(n["serial_number"])
    if "heartbeat_consumer" in n:
        y["heartbeat_consumer"] = n["heartbeat_consumer"] is True
    if isinstance(n.get("error_behavior"), dict) and n["error_behavior"]:
        y["error_behavior"] = {_u(k): _u(v) for k, v in n["error_behavior"].items()}
    if "restore_configuration" in n:
        y["restore_configuration"] = _u(n["restore_configuration"])
    if n.get("software_file"):
        y["software_file"] = software_path or n["software_file"]
    if "software_version" in n:
        y["software_version"] = _u(n["software_version"])
    for is_tx in (True, False):
        pdos = _emit_pdos(n, norm, dev, eds, ro, is_tx)
        if pdos is not None:
            y["tpdo" if is_tx else "rpdo"] = pdos
    return y


def master_input(cfg):
    """The plugin's dcfgen `master` entry, as far as it shapes the slaves'
    downloads (the 0x1016 heartbeat consumer entry)."""
    m = cfg["master"]
    y = {"node_id": _u(m.get("node_id"), 1), "baudrate": _bitrate(cfg) // 1000,
         "sync_period": _u(m.get("sync_period_us"), 0), "heartbeat_producer": _u(m.get("heartbeat_ms"), 0),
         "heartbeat_consumer": m.get("heartbeat_consumer", True) is not False}
    if "heartbeat_multiplier" in m:
        y["heartbeat_multiplier"] = _fmt6(float(m["heartbeat_multiplier"]))
    return y


def _concise(sdo):
    """(index, sub-index, data) of one dcfgen concise DCF entry."""
    index, sub, size = struct.unpack_from("<HBI", sdo)
    return index, sub, bytes(sdo[7:7 + size])


def _eds_unsigned(dev, index, sub):
    """The EDS value of an UNSIGNED8/16/32 sub-object (plugin:
    eds_sub_value), or None."""
    try:
        s = dev[index][sub]
    except KeyError:
        return None
    if s.data_type.index not in (0x0005, 0x0006, 0x0007):
        return None
    try:
        return s.parse_value()
    except Exception:
        return None


def _fnv1a(h, data):
    for c in data:
        h ^= c
        h = (h * 0x100000001B3) & 0xFFFFFFFFFFFFFFFF
    return h


def config_stamp(writes, store_subindex):
    """The node's configuration date and time (plugin: config_stamp)."""
    h = _fnv1a(0xCBF29CE484222325, b"config stamp 1")
    for index, sub, data in writes:
        h = _fnv1a(h, bytes([index & 0xFF, index >> 8, sub, len(data) & 0xFF]) + data)
    h = _fnv1a(h, ("store %d" % store_subindex).encode())
    date, time = h >> 32, h & 0xFFFFFFFF
    return date or 1, time or 1


def _add_explicit_pdo_writes(n, norm, ro, sdos):
    """The PDO parameters the node's JSON sets explicitly, as writes after the
    write that switches their PDO off (else before the one that switches it
    on, else last), unless dcfgen already wrote them; as the plugin's
    add_explicit_pdo_writes."""
    sdos = list(sdos)
    for key, base in (("tx_pdos", 0x1800), ("rx_pdos", 0x1400)):
        tx = base == 0x1800
        for p, pn in zip(n.get(key, []), norm[key]):
            comm = base + pn["number"] - 1
            want = []
            if "transmission" in p:
                want.append((2, _u(p["transmission"]), 1))
            if tx and "inhibit_time_us" in p:
                want.append((3, _u(p["inhibit_time_us"]) // 100, 2))
            if tx and "event_timer_ms" in p:
                want.append((5, _u(p["event_timer_ms"]), 2))
            if tx and "sync_start" in p:
                want.append((6, _u(p["sync_start"]), 1))
            add = [(comm, sub, value.to_bytes(size, "little"), "pdo") for sub, value, size in want
                   if (comm, sub) not in ro and not any(w[0] == comm and w[1] == sub for w in sdos)]
            if not add:
                continue
            at = None
            for i, w in enumerate(sdos):
                if w[0] != comm or w[1] != 1 or len(w[2]) != 4:
                    continue
                if w[2][3] & 0x80:
                    at = i + 1
                    break
                if at is None:
                    at = i
            if at is None:
                at = len(sdos)
            sdos[at:at] = add
    return sdos


class _Node:
    """What the export needs of one node: JSON, prepared EDS, Lely device."""

    def __init__(self, json_node, norm, text, eds_name):
        self.json, self.norm, self.text, self.eds_name = json_node, norm, text, eds_name
        self.node_id = norm["node_id"]
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            self.dev = _lely_dcf.Device(_parse_text(text), {"NODEID": self.node_id})
        self.eds = eds_mod.Eds.read(eds_name, text)
        self.ro = _ro_pdo_comm(self.dev)


def _parse_text(text):
    fd, path = tempfile.mkstemp(suffix=".eds", prefix="dcfexport-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            f.write(text)
        return _parse_file(path)
    finally:
        os.remove(path)


def _load_nodes(cfg, config_path, eds_paths):
    paths = eds_paths if eds_paths is not None else bundle.eds_files(cfg, config_path)
    out = []
    for n, norm in zip(cfg["nodes"], _normalized_nodes(cfg)):
        with open(paths[n["eds"]], "rb") as f:
            text, _ = edslint.prepare(f.read())
        out.append(_Node(n, norm, text, n["eds"]))
    return out


def plugin_downloads(cfg, config_path, eds_paths=None, software_paths=None, nodes=None):
    """{node ID: Download} for a config that passes contract.check_config."""
    cli = dcfgen_cli()
    nodes = nodes if nodes is not None else _load_nodes(cfg, config_path, eds_paths)
    base = os.path.dirname(os.path.abspath(config_path))
    sw_paths = software_paths if software_paths is not None else contract.software_files(cfg, base)
    work = tempfile.mkdtemp(prefix="dcfexport-")
    try:
        options = {"cob_id": 0x680, "dcf_path": work, "heartbeat_multiplier": 3.0, "retry_factor": 3}
        args = types.SimpleNamespace(no_strict=True)
        slaves = {}
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            for node in nodes:
                path = os.path.join(work, "node_%d.eds" % node.node_id)
                with open(path, "w", encoding="utf-8", newline="") as f:
                    f.write(node.text)
                sw = node.json.get("software_file")
                y = dcfgen_input(cfg, node.json, node.norm, path, node.dev, node.eds, node.ro,
                                 sw_paths.get(sw) if sw else None)
                name = "node_%d" % node.node_id
                slaves[name] = cli.Slave.from_config(name, y, options, args)
            cli.Master.from_config(master_input(cfg), options, slaves)
    finally:
        shutil.rmtree(work, ignore_errors=True)

    master_id = _u(cfg["master"].get("node_id"), 1)
    out = {}
    for node in nodes:
        n = node.json
        d = Download(node.node_id)
        sdos = [_concise(s) + (_config_source(_concise(s)[0]),) for s in slaves["node_%d" % node.node_id].sdo]
        # dcfgen switches every configured PDO off and on again through its
        # COB-ID; the plugin drops writes to read-only PDO communication
        # sub-indices (generate_device_config).
        sdos = [w for w in sdos if (w[0], w[1]) not in node.ro]
        # Explicit PDO parameters equal to the EDS default, which dcfgen leaves
        # out (add_explicit_pdo_writes).
        sdos = _add_explicit_pdo_writes(n, node.norm, node.ro, sdos)
        # Without heartbeat_consumer the node keeps its 0x1016 entries.
        if "heartbeat_consumer" not in n:
            cleared = master_id << 16
            sdos = [w for w in sdos
                    if not (w[0] == 0x1016 and len(w[2]) == 4 and int.from_bytes(w[2], "little") == cleared)]
        # The node's TIME COB-ID, unless the EDS already has the value.
        if "time_cob_id" in n:
            tcob = _u(n["time_cob_id"])
            if _eds_unsigned(node.dev, 0x1012, 0) not in (None, tcob):
                sdos.append((0x1012, 0, tcob.to_bytes(4, "little"), "node"))
        # RPDO event timers (deadlines), unless the EDS already has the value.
        for p, pn in zip(n.get("rx_pdos", []), node.norm["rx_pdos"]):
            if "event_timer_ms" not in p:
                continue
            idx = 0x1400 + pn["number"] - 1
            ms = _u(p["event_timer_ms"])
            if _eds_unsigned(node.dev, idx, 5) == ms:
                continue
            sdos.append((idx, 5, ms.to_bytes(2, "little"), "pdo"))
        # Startup SDOs go last, in list order.
        for s in n.get("sdo", []):
            data, _ = contract.sdo_value(s["value"], s["type"])
            sdos.append((_u(s["index"]), _u(s.get("subindex"), 0), data, "startup_sdo"))
        # Configuration check: the stamp after everything else, then the save.
        if n.get("config_check") is True:
            store = _u(n.get("store_configuration"), 0)
            date, time = config_stamp([w[:3] for w in sdos], store)
            sdos.append((0x1020, 1, date.to_bytes(4, "little"), "config_check"))
            sdos.append((0x1020, 2, time.to_bytes(4, "little"), "config_check"))
            if store:
                sdos.append((0x1010, store, b"save", "config_check"))
        d.writes = [w[:3] for w in sdos]
        d.sources = [w[3] for w in sdos]
        if "restore_configuration" in n:
            d.restore = _u(n["restore_configuration"])
        if n.get("software_file") and "software_version" in n:  # without a version Lely never downloads it
            d.firmware = n["software_file"]
        out[node.node_id] = d
    return out


# -- the DCF ---------------------------------------------------------------

_SECTION = re.compile(r"^\s*\[([^\]]*)\]")
_ENTRY = re.compile(r"^\s*([A-Za-z_0-9]+)\s*=")


def parameter_value(data, data_type):
    """The CiA 306 text of a written value for its EDS data type, or None
    when the type has no numeric form the export writes."""
    n = int.from_bytes(data, "little")
    if data_type == 0x0001:  # BOOLEAN
        return "1" if n else "0"
    if data_type in (0x0002, 0x0003, 0x0004, 0x0010, 0x0012, 0x0013, 0x0014, 0x0015):  # INTEGERn
        bits = len(data) * 8
        if n >= 1 << (bits - 1):
            n -= 1 << bits
        return str(n)
    if data_type in (0x0005, 0x0006, 0x0007, 0x0016, 0x0018, 0x0019, 0x001A, 0x001B):  # UNSIGNEDn
        return "0x%X" % n
    if data_type == 0x0008 and len(data) == 4:  # REAL32: Lely's hex bit pattern
        return "0x%08X" % n
    if data_type == 0x0011 and len(data) == 8:  # REAL64
        return "0x%016X" % n
    return None


class _Lines:
    """The EDS text as lines, edited in place, line endings kept."""

    def __init__(self, text):
        self.lines = text.splitlines(True)
        first = self.lines[0] if self.lines else "\n"
        self.eol = first[len(first.rstrip("\r\n")):] or "\n"
        if self.lines and not self.lines[-1].endswith(("\n", "\r")):
            self.lines[-1] += self.eol

    def text(self):
        return "".join(self.lines)

    def _sections(self):
        """[(name lower case, start line, end line)]: end is past the last
        non-blank line of the section."""
        out, cur, start, last = [], None, 0, 0
        for i, line in enumerate(self.lines):
            m = _SECTION.match(line)
            if m:
                if cur is not None:
                    out.append((cur, start, last + 1))
                cur, start, last = m.group(1).strip().lower(), i, i
            elif line.strip() and not line.lstrip().startswith((";", "#")):
                last = i
        if cur is not None:
            out.append((cur, start, last + 1))
        return out

    def find(self, name):
        for sec, start, end in self._sections():
            if sec == name.lower():
                return start, end
        return None

    def set(self, section, key, value):
        """Sets `key=value` in `section` (replacing an existing key,
        case-insensitively); appends the section at the end if missing."""
        where = self.find(section)
        if where is None:
            if self.lines and self.lines[-1].strip():
                self.lines.append(self.eol)
            self.lines.append("[%s]%s" % (section, self.eol))
            self.lines.append("%s=%s%s" % (key, value, self.eol))
            return
        start, end = where
        for i in range(start + 1, end):
            m = _ENTRY.match(self.lines[i])
            if m and m.group(1).lower() == key.lower():
                body = self.lines[i].rstrip("\r\n")
                self.lines[i] = "%s=%s%s" % (m.group(1), value, self.lines[i][len(body):])
                return
        self.lines.insert(end, "%s=%s%s" % (key, value, self.eol))

    def drop_section(self, name):
        where = self.find(name)
        if where is None:
            return
        start, end = where
        while end < len(self.lines) and not self.lines[end].strip():
            end += 1
        del self.lines[start:end]

    def prepend(self, comment_lines):
        self.lines[0:0] = [";%s%s" % ((" " + c) if c else "", self.eol) for c in comment_lines]


def build_dcf(node, download, cfg, now, dcf_name):
    """(DCF text, [problem]) for a node. Problems here are values the
    export cannot express; validation comes later."""
    problems = []
    lines = _Lines(node.text)
    values = download.final_values()
    for (index, sub), data in sorted(values.items()):
        try:
            s = node.dev[index][sub]
        except KeyError:
            problems.append("0x%04X sub %d: the plugin writes it, but the EDS does not define it" % (index, sub))
            continue
        text = parameter_value(data, s.data_type.index)
        if text is None:
            problems.append("0x%04X sub %d: data type 0x%04X has no ParameterValue form the export writes"
                            % (index, sub, s.data_type.index))
            continue
        obj_section = "%04X" % index
        if lines.find("%ssub%X" % (obj_section, sub)) is not None:
            lines.set("%ssub%X" % (obj_section, sub), "ParameterValue", text)
        elif sub == 0 and lines.find(obj_section) is not None and not _is_compact(node, index):
            lines.set(obj_section, "ParameterValue", text)
        elif _is_compact(node, index) and sub >= 1:
            vsec = obj_section + "Value"
            lines.set(vsec, str(sub), text)
            where = lines.find(vsec)
            count = 0
            for i in range(where[0] + 1, where[1]):
                m = _ENTRY.match(lines.lines[i])
                if m and m.group(1).isdigit():
                    count += 1
            lines.set(vsec, "NrOfEntries", str(count))
        else:
            problems.append("0x%04X sub %d: no section to hold its ParameterValue" % (index, sub))

    n = node.json
    lines.drop_section("DeviceComissioning")
    lines.set("DeviceComissioning", "NodeID", str(node.node_id))
    lines.set("DeviceComissioning", "NodeName", n.get("name") or "node_%d" % node.node_id)
    lines.set("DeviceComissioning", "Baudrate", str(_bitrate(cfg) // 1000))
    lines.set("DeviceComissioning", "NetNumber", "1")
    lines.set("DeviceComissioning", "NetworkName", NETWORK_NAME)
    lines.set("DeviceComissioning", "CANopenManager", "0")
    if "serial_number" in n:
        lines.set("DeviceComissioning", "LSS_SerialNumber", "0x%08X" % _u(n["serial_number"]))

    lines.set("FileInfo", "FileName", dcf_name)
    lines.set("FileInfo", "LastEDS", os.path.basename(node.eds_name))
    lines.set("FileInfo", "ModifiedBy", "canworks-deploy %s" % __version__)
    lines.set("FileInfo", "ModificationDate", now.strftime("%m-%d-%Y"))
    lines.set("FileInfo", "ModificationTime", "%02d:%02d%s" % ((now.hour + 11) % 12 + 1, now.minute,
                                                                 "AM" if now.hour < 12 else "PM"))

    label = "node %d" % node.node_id + (" (%s)" % n["name"] if n.get("name") else "")
    comment = ["CiA 306 DCF of %s, exported by canworks-deploy %s from %s." % (label, __version__,
                                                                                   node.eds_name),
               "ParameterValue: the value each object holds after the OpenPLC CANopen master's",
               "configuration download. The master sends it in its own order; the DCF keeps one",
               "value per object."]
    steps = download.steps()
    if steps:
        comment.append("Boot steps the master also performs (not parameter values):")
        comment += ["- " + s for s in steps]
    lines.prepend(comment + [""])
    return lines.text(), problems


def _is_compact(node, index):
    try:
        section = node.dev.cfg["%04X" % index]
    except KeyError:
        return False
    return bool(section.get("CompactSubObj")) and not section.get("SubNumber")


# -- validation ------------------------------------------------------------

def _dev_warnings(cfg, node_id):
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        _lely_dcf.Device(cfg, {"NODEID": node_id})
    return [str(w.message) for w in caught]


def validate(node, download, text, cfg):
    """Problems of a finished DCF (canopen-dcf-export "Validated against
    CiA 306"), as (section, key, message)."""
    problems = []
    eds_lint = {f.message for f in edslint.lint_text(node.text, node.node_id).findings}
    dcf_lint = edslint.lint_text(text, node.node_id)
    if dcf_lint.read_error:
        problems.append(("", "", "Lely cannot read the DCF: %s" % dcf_lint.read_error))
        return problems
    for f in dcf_lint.findings:
        if f.message not in eds_lint:
            problems.append((f.section or "", "", f.message))
    try:
        parsed = _parse_text(text)
    except Exception as e:  # noqa: BLE001 - reported as a problem
        problems.append(("", "", "Lely cannot read the DCF: %s" % e))
        return problems
    eds_warn = set(_dev_warnings(_parse_text(node.text), node.node_id))
    for w in _dev_warnings(parsed, node.node_id):
        if w not in eds_warn:
            problems.append(("", "", w))

    for (index, sub), data in sorted(download.final_values().items()):
        try:
            s = node.dev[index][sub]
        except KeyError:
            continue  # reported by build_dcf
        if s.access_type.write:
            continue
        eds_value = _eds_unsigned(node.dev, index, sub)
        try:
            eds_value = s.parse_value() if eds_value is None else eds_value
        except Exception:
            eds_value = None
        value = int.from_bytes(data, "little")
        if eds_value != value:
            problems.append((_section_name(node, index, sub), "ParameterValue",
                             "ParameterValue %s on a sub-object with AccessType %s (EDS value %s)"
                             % (parameter_value(data, s.data_type.index), s.access_type.name,
                                eds_value if eds_value is None else "0x%X" % eds_value)))

    dc = _section(parsed, "DeviceComissioning")
    try:
        nid = int(dc.get("NodeID", ""), 0)
    except ValueError:
        nid = None
    if nid != node.node_id or not 1 <= (nid or 0) <= 127:
        problems.append(("DeviceComissioning", "NodeID", "NodeID %s is not the node ID %d (1-127)"
                         % (dc.get("NodeID"), node.node_id)))
    try:
        rate = int(dc.get("Baudrate", ""), 0)
    except ValueError:
        rate = None
    info = _section(parsed, "DeviceInfo")
    if rate not in BAUDRATES:
        problems.append(("DeviceComissioning", "Baudrate", "Baudrate %s kbit/s is not a CiA 306 bit rate (%s)"
                         % (dc.get("Baudrate"), ", ".join(map(str, BAUDRATES)))))
    elif str(info.get("BaudRate_%d" % rate, "1")).strip() == "0":
        problems.append(("DeviceComissioning", "Baudrate", "the EDS %s does not support %d kbit/s (BaudRate_%d=0)"
                         % (node.eds_name, rate, rate)))
    return problems


def _section(parsed, name):
    """A section of a parsed DCF as a plain dict (empty if missing)."""
    for sec in parsed.sections():
        if sec.lower() == name.lower():
            return dict(parsed[sec])
    return {}


def _section_name(node, index, sub):
    name = "%04Xsub%X" % (index, sub)
    if name in node.dev.cfg:
        return name
    return "%04XValue" % index if _is_compact(node, index) and sub else "%04X" % index


# -- export ----------------------------------------------------------------

def dcf_name(node_id):
    return "node_%d.dcf" % node_id


def export(cfg, config_path, eds_paths=None, software_paths=None, node_id=None, now=None, network=None):
    """{file name: DCF text} for every node (or the one with `node_id`), and
    the config checks' warnings. Raises ExportFailed with every problem and
    builds nothing when the config or any DCF fails.

    With several networks the names are <network>/node_<id>.dcf, unless
    `network` picks one network: then its files are named as with one."""
    result = contract.check_config(cfg, config_path,
                                   eds_paths=eds_paths if eds_paths is not None
                                   else bundle.eds_files(cfg, config_path),
                                   software_paths=software_paths)
    if not result.ok:
        raise ExportFailed([(i["message"], i["paths"]) for i in result.items if i["level"] == "error"])
    now = now or datetime.datetime.now()
    nets = contract.networks(cfg)
    if network is not None:
        nets = [n for n in nets if n["name"] == network]
        if not nets:
            raise ExportFailed([("no network '%s' in the config (%s)" % (
                network, ", ".join(n["name"] for n in contract.networks(cfg))), ["networks"])])
    several = len(nets) > 1
    files, problems = {}, []
    for net in _no_slave(nets, network, "DCF files"):
        one = contract.network_config(cfg, net["name"] if net["path"] else None)
        folder = net["name"] + "/" if several else ""
        at = net["path"] + "." if net["path"] else ""
        got, failed = _export_network(one, config_path, eds_paths, software_paths, node_id, now)
        files.update((folder + name, text) for name, text in got.items())
        problems += [((net["name"] + ": " if several else "") + msg, [at + p for p in paths])
                     for msg, paths in failed]
    if node_id is not None and not files:
        raise ExportFailed([("no node with node ID %d in the config" % node_id, ["nodes"])])
    if problems:
        raise ExportFailed(problems)
    return files, list(result.warnings)


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


def _export_network(cfg, config_path, eds_paths, software_paths, node_id, now):
    """export() of one network's version 1 style config: ({name: text},
    problems)."""
    nodes = _load_nodes(cfg, config_path, eds_paths)
    downloads = plugin_downloads(cfg, config_path, eds_paths, software_paths, nodes)
    files, problems = {}, []
    for i, node in enumerate(nodes):
        if node_id is not None and node.node_id != node_id:
            continue
        label = "node %d" % node.node_id + (" (%s)" % node.json["name"] if node.json.get("name") else "")
        name = dcf_name(node.node_id)
        text, build_problems = build_dcf(node, downloads[node.node_id], cfg, now, name)
        for msg in build_problems:
            problems.append(("%s: %s: %s" % (label, name, msg), ["nodes[%d]" % i]))
        for section, key, msg in validate(node, downloads[node.node_id], text, cfg):
            where = "[%s]%s" % (section, " " + key if key else "") if section else ""
            problems.append(("%s: %s%s: %s" % (label, name, " " + where if where else "", msg), ["nodes[%d]" % i]))
        files[name] = text
    return files, problems


def write_files(files, out_dir):
    """Writes {name: text} into out_dir (created if missing, and a name's
    network folder too), each through a temporary file and a rename. Returns
    the written paths."""
    written = []
    for name, text in sorted(files.items()):
        path = os.path.join(out_dir, *name.split("/"))
        folder = os.path.dirname(path)
        os.makedirs(folder, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix="." + os.path.basename(path) + ".", dir=folder)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
                f.write(text)
            os.replace(tmp, path)
        except BaseException:
            if os.path.exists(tmp):
                os.remove(tmp)
            raise
        written.append(path)
    return written
