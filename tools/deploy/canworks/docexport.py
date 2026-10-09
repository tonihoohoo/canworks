"""Builds the network documentation of a config (canopen-network-docs spec).

The document model is a plain JSON-serialisable dict built from the same code
the other exports use, so it shows what the plugin puts on the bus:
contract.check_config and location_uses (checks, networks, PLC addresses),
dbcexport.build and frames (frames, COB-IDs, PDO layouts), and
dcfexport.plugin_downloads (the boot SDO writes). docwriter turns it into one
HTML file, which also carries the model as JSON.

    model = build(cfg, config_path, names=dbcexport.project_names(config_path))
    html = docwriter.write(model)
"""

import base64
import datetime
import hashlib
import json
import os
import struct
import tempfile

from . import __version__, bundle, contract, dbcexport, dcfexport, edslint, editorproject
from . import eds as eds_mod
from .iec import CO_TYPE_BY_CODE, parse_location

DOC_SCHEMA_VERSION = 1
DEFAULT_TITLE = "CANopen network documentation"
OD_OPTIONS = ("used", "all")
LOAD_WARNING_PCT = 60.0
# The master looks for changed event-driven outputs this often without SYNC
# (docs/config.md, At runtime).
OUTPUT_CHECK_MS = 1.0

NMT_START_FIELDS = (
    ("start", True, "Master starts itself (0x1F80)"),
    ("start_nodes", True, "Master starts the nodes (0x1F80)"),
    ("start_all_nodes", False, "One broadcast NMT start (0x1F80)"),
    ("reset_all_nodes", False, "Reset all nodes when a mandatory node is lost (0x1F80)"),
    ("stop_all_nodes", False, "Stop all nodes when a mandatory node is lost (0x1F80)"),
)
MASTER_LOCATIONS = (
    ("bus_state_location", "CAN bus state (0 none, 1 error-active, 2 warning, 3 passive, 4 bus-off)"),
    ("tx_error_count_location", "transmit error counter"),
    ("rx_error_count_location", "receive error counter"),
    ("bus_off_count_location", "bus-off count since the PLC started"),
    ("state_location", "master NMT state (5 operational, 127 pre-operational, 4 stopped)"),
)
NODE_LOCATIONS = (
    ("status_location", "TRUE while the node and the master are OPERATIONAL"),
    ("state_location", "node NMT state (5, 127, 4, 0 no contact)"),
    ("boot_error_location", "boot error letter (ASCII; 0 booted)"),
    ("emcy_code_location", "error code of the latest EMCY"),
    ("error_register_location", "error register of the latest EMCY"),
    ("nmt_command_location", "NMT command from the program (0/1 run, 2 stop, 128 pre-op, 129/130 reset)"),
)


class ExportFailed(Exception):
    """The export stopped: `problems` is a list of (message, [JSON path])."""

    def __init__(self, problems):
        super().__init__("\n".join(m for m, _ in problems))
        self.problems = problems


def _u(value, default=None):
    v = contract._uint(value) if value is not None else None
    return default if v is None else v


def hx(value, digits=4):
    return "0x%0*X" % (digits, value)


def anchor(*parts):
    """A stable HTML id from the parts: lower case letters, digits and -."""
    text = "-".join(str(p) for p in parts if p != "")
    out = "".join(c if c.isalnum() else "-" for c in text.lower())
    while "--" in out:
        out = out.replace("--", "-")
    return out.strip("-") or "x"


def shown_path(value):
    """A file reference as the document shows it: the config's own relative
    value, only the file name of an absolute one (no paths of this PC)."""
    return os.path.basename(value) if os.path.isabs(value) else value.replace("\\", "/")


def frame_bits(dlc, rtr=False):
    """Bits of an 11-bit identifier data frame with worst-case bit stuffing
    and the 3-bit interframe space: 44 fixed bits + 8 per data byte + the
    stuff bits of the 34 + 8n stuffed bits + 3."""
    data = 0 if rtr else dlc
    return 47 + 8 * data + (34 + 8 * data - 1) // 4


def interval_ms(text):
    """An IEC duration (T#20ms) in milliseconds, or None."""
    try:
        editorproject.check_interval(text)
    except editorproject.NewProjectError:
        return None
    total = 0.0
    for part in editorproject._PART.finditer(text.split("#", 1)[1]):
        total += float(part.group(1)) * editorproject._UNITS[part.group(2).lower()]
    return total


def project_cycle_ms(config_path):
    """The task interval of the editor project a config belongs to
    (<project>/canworks/<file>): the fastest cyclic task's, in ms. None
    outside a project or without a cyclic task."""
    folder = os.path.dirname(os.path.abspath(config_path))
    path = os.path.join(os.path.dirname(folder), "project.json")
    if os.path.basename(folder) != "canworks" or not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            tasks = json.load(f)["data"]["configuration"]["resource"]["tasks"]
    except (OSError, ValueError, KeyError, TypeError):
        return None
    found = [interval_ms(t.get("interval", "")) for t in tasks
             if isinstance(t, dict) and str(t.get("triggering", "Cyclic")).lower() == "cyclic"]
    found = [v for v in found if v]
    return min(found) if found else None


def _plc_names(names, loc_text):
    if not loc_text or not names:
        return []
    loc = parse_location(loc_text)
    return list(names.get(str(loc) if loc else loc_text, []))


def _yes(value):
    return "yes" if value else "no"


# -- values ---------------------------------------------------------------------

def _int_of(data, type_name):
    if not data:
        return None
    if type_name == "REAL32" and len(data) == 4:
        return struct.unpack("<f", data)[0]
    if type_name == "REAL64" and len(data) == 8:
        return struct.unpack("<d", data)[0]
    signed = bool(type_name and type_name.startswith("INTEGER"))
    return int.from_bytes(data, "little", signed=signed)


def _value_text(data, type_name):
    v = _int_of(data, type_name)
    if v is None:
        return ""
    if isinstance(v, float):
        return repr(v)
    if type_name in ("VISIBLE_STRING",) or (type_name is None and all(32 <= b < 127 for b in data) and len(data) > 4):
        return '"%s"' % data.decode("latin-1")
    if v < 0:
        return "%d" % v
    return "%d (0x%0*X)" % (v, max(2, 2 * len(data)), v)


def _transmission_meaning(t):
    if t is None:
        return ""
    if t == 0:
        return "synchronous, acyclic"
    if 1 <= t <= 240:
        return "synchronous, every SYNC" if t == 1 else "synchronous, every %d SYNCs" % t
    if t in (252, 253):
        return "on remote request"
    if t in (254, 255):
        return "event-driven"
    return "reserved"


def meaning(index, sub, data, eds, master_id):
    """What a boot write means, for the objects whose meaning is fixed by
    CiA 301; "" otherwise."""
    if not data:
        return ""
    v = int.from_bytes(data, "little")
    if 0x1400 <= index <= 0x15FF or 0x1800 <= index <= 0x19FF:
        if sub == 1:
            return "COB-ID %s, %s" % (hx(v & 0x7FF, 3), "PDO switched off" if v & 0x80000000 else "PDO valid")
        if sub == 2:
            return "transmission type: " + _transmission_meaning(v)
        if sub == 3:
            return "inhibit time %d µs" % (v * 100)
        if sub == 5:
            return ("event timer %d ms" % v) if index >= 0x1800 else ("deadline %d ms" % v)
        if sub == 6:
            return "SYNC start value %d" % v
    if 0x1600 <= index <= 0x17FF or 0x1A00 <= index <= 0x1BFF:
        if sub == 0:
            return "%d mapped object%s" % (v, "" if v == 1 else "s")
        i, s, bits = v >> 16, (v >> 8) & 0xFF, v & 0xFF
        name = _od_text(eds, i, s)
        return "maps %s:%d, %d bits%s" % (hx(i), s, bits, " (%s)" % name if name else "")
    if index == 0x1017:
        return "heartbeat every %d ms" % v if v else "heartbeat off"
    if index == 0x1016 and sub >= 1:
        node, ms = (v >> 16) & 0x7F, v & 0xFFFF
        if not node or not ms:
            return "entry cleared"
        who = "the master" if node == master_id else "node %d" % node
        return "watches %s's heartbeat, timeout %d ms" % (who, ms)
    if index == 0x100C:
        return "guard time %d ms" % v
    if index == 0x100D:
        return "life time factor %d" % v
    if index == 0x1012:
        return "TIME COB-ID %s%s" % (hx(v & 0x7FF, 3), ", consumer" if v & 0x80000000 else "")
    if index == 0x1020:
        return "configuration stamp (%s)" % ("date" if sub == 1 else "time")
    if index == 0x1010:
        return 'store parameters ("save")'
    if index == 0x1029:
        return {0: "pre-operational on error", 1: "no state change on error", 2: "stopped on error"}.get(
            v, "manufacturer-specific")
    return ""


def _od_text(eds, index, sub):
    parent, name = eds.object_name(index, sub)
    if parent and name and not name.lower().startswith(parent.lower()):
        return "%s / %s" % (parent, name)
    return name or parent


# -- bus load --------------------------------------------------------------------

class _Rates:
    """Frame rates of one network (frames per second), cyclic and worst case."""

    def __init__(self, cfg, plc_cycle_ms):
        m = cfg["master"]
        self.plc_cycle = m.get("sync_source") == "plc_cycle"
        cycles = _u(m.get("sync_cycles"), 1) or 1
        if self.plc_cycle:
            self.sync_ms = plc_cycle_ms * cycles if plc_cycle_ms else None
        else:
            us = _u(m.get("sync_period_us"), 0)
            self.sync_ms = us / 1000.0 if us else None
        self.has_sync = self.plc_cycle or bool(_u(m.get("sync_period_us"), 0))
        self.sync_cycles = cycles


def _per(ms):
    return 1000.0 / ms if ms else 0.0


def _pct(bits, rate, bitrate):
    return round(100.0 * bits * rate / bitrate, 3) if bitrate and rate else 0.0


def _sync_text(rates, n=1):
    if not rates.plc_cycle:
        return "%g ms" % (rates.sync_ms * n)
    cycles = rates.sync_cycles * n
    base = "every PLC cycle" if cycles == 1 else "every %d PLC cycles" % cycles
    return base + (" (%g ms)" % (rates.sync_ms * n) if rates.sync_ms else "")


def _pdo_rates(pdo, rates):
    """(cyclic Hz, worst Hz, trigger text, unbounded) of a PDO entry of the
    model."""
    t = pdo["transmission"]
    tx = pdo["kind"] == "TPDO"
    if t is not None and 1 <= t <= 240:
        if not rates.has_sync:
            return 0.0, 0.0, "synchronous, no SYNC produced", False
        text = "SYNC, " + _sync_text(rates, t)
        if rates.sync_ms is None:
            return 0.0, 0.0, text + "; not counted: PLC cycle not given", False
        hz = _per(rates.sync_ms * t)
        return hz, hz, text, False
    if t == 0:
        if rates.sync_ms is None:
            return 0.0, 0.0, "SYNC (acyclic)", False
        return 0.0, _per(rates.sync_ms), "SYNC when changed (acyclic), at most " + _sync_text(rates), False
    if t in (252, 253):
        return 0.0, 0.0, "on remote request", False
    # Event-driven (254/255) or not known.
    if not tx:
        if rates.has_sync:
            if rates.sync_ms is None:
                return 0.0, 0.0, "on change, sent at the next SYNC; not counted: PLC cycle not given", False
            return 0.0, _per(rates.sync_ms), "on change, sent at the next SYNC, at most " + _sync_text(rates), False
        return 0.0, _per(OUTPUT_CHECK_MS), "on change, at most every %g ms (the master's output check)" % \
            OUTPUT_CHECK_MS, False
    inhibit_us, timer = pdo["inhibit_time_us"], pdo["event_timer_ms"]
    if inhibit_us:
        text = "on change, inhibit time %g ms" % (inhibit_us / 1000.0)
        if timer:
            text += ", event timer %d ms" % timer
        return 0.0, _per(inhibit_us / 1000.0), text, False
    if timer:
        return 0.0, _per(timer), "event timer %d ms; no inhibit time, changes can be sent faster" % timer, False
    return 0.0, 0.0, "on change, no inhibit time or event timer: unbounded", True


# -- building ---------------------------------------------------------------------

def _eds_value(eds, index, sub, node_id):
    obj = eds.find(index, sub)
    return obj.value(node_id) if obj is not None else None


def _load_node_eds(n, paths):
    with open(paths[n["eds"]], "rb") as f:
        raw = f.read()
    text, _, _ = edslint.check(raw, _u(n["node_id"]))
    return eds_mod.Eds.read(n["eds"], text), raw


def _master_settings(net, cfg):
    m, a = cfg["master"], net["adapter"]
    rows = []

    def add(label, value, obj=""):
        rows.append({"label": label, "value": value, "object": obj})

    kind = a.get("type", "socketcan")
    where = a.get("interface") or (shown_path(a["device"]) if a.get("device") else "")
    add("Adapter", "%s %s" % (kind, where))
    if a.get("bitrate"):
        add("Bitrate", "%d kbit/s" % (_u(a["bitrate"]) // 1000))
    if "serial_baudrate" in a:
        add("Serial baud rate", str(a["serial_baudrate"]))
    if "restart_ms" in a:
        add("Restart after bus-off", "%s ms" % a["restart_ms"])
    if a.get("simulate"):
        add("Simulated network", "yes: every node runs on the in-plugin virtual bus")
    add("Master node ID", str(_u(m.get("node_id"), 1)))
    if m.get("sync_source") == "plc_cycle":
        cyc = _u(m.get("sync_cycles"), 1)
        add("SYNC", "from the PLC cycle, every %s" % ("cycle" if cyc == 1 else "%d cycles" % cyc), "0x1005")
    elif _u(m.get("sync_period_us"), 0):
        add("SYNC", "every %g ms (master timer)" % (_u(m["sync_period_us"]) / 1000.0), "0x1006")
    else:
        add("SYNC", "off", "0x1005")
    if "sync_window_us" in m:
        add("SYNC window", "%s µs" % m["sync_window_us"], "0x1007")
    if "sync_counter_overflow" in m:
        add("SYNC counter overflow", str(m["sync_counter_overflow"]), "0x1019")
    hb = _u(m.get("heartbeat_ms"), 0)
    add("Master heartbeat", "%d ms" % hb if hb else "off", "0x1017")
    add("Watches node heartbeats", _yes(m.get("heartbeat_consumer", True) is not False), "0x1016")
    if "heartbeat_multiplier" in m:
        add("Heartbeat multiplier for nodes watching the master", str(m["heartbeat_multiplier"]))
    if "time_period_ms" in m:
        cob = _u(m.get("time_cob_id"), 0x100) & 0x7FF
        add("TIME", "produced every %s ms on %s" % (m["time_period_ms"], hx(cob, 3)), "0x1012")
    for key, default, label in NMT_START_FIELDS:
        if key in m:
            add(label, _yes(m[key]))
    if "boot_time_ms" in m:
        add("Boot time limit", "%s ms" % m["boot_time_ms"], "0x1F89")
    add("SDO timeout while booting", "%s ms" % m.get("sdo_timeout_ms", 1000))
    if "nmt_inhibit_time_us" in m:
        add("NMT inhibit time", "%s µs" % m["nmt_inhibit_time_us"], "0x102A")
    if "emcy_inhibit_time_us" in m:
        add("EMCY inhibit time", "%s µs" % m["emcy_inhibit_time_us"], "0x1015")
    if isinstance(m.get("error_behavior"), dict) and m["error_behavior"]:
        add("Error behaviour", ", ".join("sub %s = %s" % (k, v) for k, v in sorted(m["error_behavior"].items())),
            "0x1029")
    for key, obj in (("vendor_id", "0x1018:1"), ("product_code", "0x1018:2"), ("revision_number", "0x1018:3"),
                     ("serial_number", "0x1018:4")):
        if key in m:
            add("Master " + key.replace("_", " "), hx(_u(m[key]), 8), obj)
    lint = m.get("eds_lint") or ({True: "all", False: "off"}.get(m.get("strict_eds")) if "strict_eds" in m
                                 else "communication")
    add("EDS lint", lint)
    d = m.get("diagnostics")
    if isinstance(d, dict):
        add("Diagnostics channel", "on, port %s, %s" % (d.get("port", 7531),
                                                       "changes allowed" if d.get("allow_changes") else "read-only"))
    else:
        add("Diagnostics channel", "off")
    return rows


def _node_settings(n, master):
    rows = []

    def add(label, value, obj=""):
        rows.append({"label": label, "value": value, "object": obj})

    if "heartbeat_ms" in n:
        hb = _u(n["heartbeat_ms"])
        add("Heartbeat produced", "%d ms" % hb if hb else "off", "0x1017")
    else:
        add("Heartbeat produced", "as the EDS gives (nothing written)", "0x1017")
    if "heartbeat_timeout_ms" in n:
        add("Heartbeat timeout in the master", "%s ms" % n["heartbeat_timeout_ms"], "master 0x1016")
    if "guard_time_ms" in n:
        add("Node guarding", "guard time %s ms, life time factor %s" % (n["guard_time_ms"], n.get("life_time_factor")),
            "0x100C, 0x100D")
    if "heartbeat_consumer" in n:
        add("Watches the master's heartbeat", _yes(n["heartbeat_consumer"]), "0x1016")
    add("Mandatory", _yes(n.get("mandatory", False)), "master 0x1F81")
    add("Booted by the master", _yes(n.get("boot", True) is not False), "master 0x1F81")
    add("Reset communication before boot", _yes(n.get("reset_communication", True) is not False), "master 0x1F81")
    if "retry_factor" in n:
        add("Guarding retry factor", str(n["retry_factor"]), "master 0x1F81")
    if "time_cob_id" in n:
        v = _u(n["time_cob_id"])
        add("TIME", "COB-ID %s%s" % (hx(v & 0x7FF, 3), ", consumes TIME" if v & 0x80000000 else ""), "0x1012")
    if isinstance(n.get("error_behavior"), dict) and n["error_behavior"]:
        add("Error behaviour", ", ".join("sub %s = %s" % (k, v) for k, v in sorted(n["error_behavior"].items())),
            "0x1029")
    if "restore_configuration" in n:
        add("Restore before configuring", "0x1011 sub %s" % n["restore_configuration"], "0x1011")
    add("Configuration check", "on: skip the download when 0x1020 matches" if n.get("config_check") else "off",
        "0x1020")
    if "store_configuration" in n:
        add("Store after a download", "0x1010 sub %s" % n["store_configuration"], "0x1010")
    lss = n.get("lss") if isinstance(n.get("lss"), dict) else None
    if lss and lss.get("assign"):
        add("LSS", "node ID assigned by serial number%s" % (", stored in the device" if lss.get("store") else ""))
    if n.get("software_file"):
        add("Program download", "%s, version %s" % (
            shown_path(n["software_file"]), n.get("software_version", "not set")), "0x1F50, 0x1F56")
    ax = n.get("axis")
    if isinstance(ax, dict):
        add("CiA 402 axis", "scale %s/%s × %s" % (ax.get("scale_numerator", 1), ax.get("scale_denominator", 1),
                                                   ax.get("scale_factor", 1.0)))
    if "simulate" in n:
        add("Simulated device", _yes(n["simulate"]))
    return rows


def _identity(n, info):
    info = info or {}
    out = []
    for key, label, checked in (
            ("vendor_id", "Vendor ID", True),
            ("product_code", "Product code", True),
            ("revision_number", "Revision", None),
            ("serial_number", "Serial number", None)):
        eds_value = info.get(key)
        if key in n:
            expected = _u(n[key])
            check = bool(expected) if key == "revision_number" else True
        else:
            expected = eds_value if key != "serial_number" else None
            check = checked if checked is not None else (key == "revision_number" and eds_value is not None)
        out.append({"field": label, "eds": eds_value, "expected": expected, "checked": bool(check)})
    return out


def _pdos(n, eds, norm, cfg, names):
    out = []
    node_id = _u(n["node_id"])
    for key, kind in (("tx_pdos", "TPDO"), ("rx_pdos", "RPDO")):
        tx = key == "tx_pdos"
        comm_base = 0x1800 if tx else 0x1400
        for p, pn in zip(n.get(key, []), norm[key]):
            num = pn["number"]
            comm = comm_base + num - 1
            layout, used = dbcexport.pdo_layout(p, eds, tx, num)
            info = eds_mod.mapping_info(eds, comm + 0x200)
            device_map = eds_mod.uses_device_mapping(p, info)

            def comm_value(field, sub):
                if field in p:
                    return _u(p[field]), False
                return _eds_value(eds, comm, sub, node_id), True

            trans, trans_eds = comm_value("transmission", 2)
            inhibit, _ = comm_value("inhibit_time_us", 3)
            if "inhibit_time_us" not in p and inhibit is not None:
                inhibit *= 100
            timer, _ = comm_value("event_timer_ms", 5)
            timeout = None
            if tx and "timeout_ms" in p:
                if p["timeout_ms"] == "auto":
                    ms = min(2 * timer, 0xFFFF) if timer else None
                    timeout = {"ms": ms, "auto": True}
                else:
                    timeout = {"ms": _u(p["timeout_ms"]), "auto": False}
                timeout["on_timeout"] = p.get("on_timeout", "hold")
                loc = parse_location(p["timeout_location"]) if p.get("timeout_location") else None
                timeout["location"] = str(loc) if loc else p.get("timeout_location", "")
                timeout["variables"] = _plc_names(names, timeout["location"]) if timeout["location"] else []
            entries, bit = [], 0
            for index, sub, length in layout:
                if index < 0x0008:
                    entries.append({"bit": bit, "length": length, "index": index, "subindex": sub, "name": "dummy",
                                    "type": CO_TYPE_BY_CODE.get(index, ""), "location": "", "variables": [],
                                    "used": False, "dummy": True})
                    bit += length
                    continue
                entry = used.get((index, sub))
                obj = eds.find(index, sub)
                type_name = entry["type"] if entry else (obj.type_name if obj else "")
                loc = ""
                if entry and entry.get("iec_location"):
                    parsed = parse_location(entry["iec_location"])
                    loc = str(parsed) if parsed else entry["iec_location"]
                entries.append({"bit": bit, "length": length, "index": index, "subindex": sub,
                                "name": _od_text(eds, index, sub), "type": type_name or "", "location": loc,
                                "variables": _plc_names(names, loc), "used": bool(entry), "dummy": False})
                bit += length
            out.append({"kind": kind, "number": num, "anchor": "", "cob_id": pn["cob_id"],
                        "transmission": trans, "transmission_from_eds": bool(trans_eds and trans is not None),
                        "transmission_text": _transmission_meaning(trans),
                        "inhibit_time_us": inhibit if tx else None, "event_timer_ms": timer,
                        "sync_start": _u(p["sync_start"]) if "sync_start" in p else None,
                        "mapping": "device" if device_map else "config", "dlc": (bit + 7) // 8, "bits": bit,
                        "entries": entries})
            if timeout:
                out[-1]["timeout"] = timeout
    return out


def _boot(download, eds, master_id):
    writes = []
    sources = download.sources or ["node"] * len(download.writes)
    for (index, sub, data), source in zip(download.writes, sources):
        obj = eds.find(index, sub)
        type_name = obj.type_name if obj else None
        writes.append({"index": index, "subindex": sub, "name": _od_text(eds, index, sub),
                       "value": _value_text(data, type_name), "data": data.hex(),
                       "meaning": meaning(index, sub, data, eds, master_id),
                       "access": obj.access if obj else "", "eds_default": obj.default if obj else "",
                       "source": dcfexport.WRITE_SOURCES.get(source, source)})
    before, after = [], []
    if download.restore is not None:
        before.append('restore default parameters (0x1011 sub %d "load")' % download.restore)
    if download.firmware:
        before.append("download the program file %s (0x1F50 sub 1) when the version differs"
                      % shown_path(download.firmware))
    after.append("NMT start (unless the master or the node is held)")
    return {"before": before, "writes": writes, "after": after}


def _sdo_variables(n, eds, names):
    out = []
    for v in n.get("sdo_variables", []):
        index, sub = _u(v.get("index")), _u(v.get("subindex"), 0)
        loc = str(parse_location(v.get("iec_location", "")) or v.get("iec_location", ""))
        out.append({"name": v.get("name", ""), "index": index, "subindex": sub, "od_name": _od_text(eds, index, sub),
                    "type": v.get("type", ""), "direction": v.get("direction", ""), "location": loc,
                    "variables": _plc_names(names, loc),
                    "period_ms": v.get("period_ms"), "trigger_location": v.get("trigger_location", ""),
                    "status_location": v.get("status_location", ""),
                    "abort_code_location": v.get("abort_code_location", ""), "timeout_ms": v.get("timeout_ms")})
    return out


def _od(eds, node_id, pdos, download, n, mode):
    finals = download.final_values() if download else {}
    keys = set(finals)
    for p in pdos:
        for e in p["entries"]:
            if not e["dummy"]:
                keys.add((e["index"], e["subindex"]))
    for s in n.get("sdo", []) + n.get("sdo_variables", []):
        keys.add((_u(s.get("index")), _u(s.get("subindex"), 0)))
    for sub in range(0, 5):
        keys.add((0x1018, sub))
    keys.add((0x1000, 0))
    out = []
    for index, sub, obj in eds.items():
        if mode != "all" and (index, sub) not in keys:
            continue
        configured = finals.get((index, sub))
        out.append({"index": index, "subindex": sub, "name": _od_text(eds, index, sub), "type": obj.type_name or
                    eds_mod.data_type_name(obj.data_type), "access": obj.access, "low": obj.low_limit,
                    "high": obj.high_limit, "default": obj.default,
                    "configured": _value_text(configured, obj.type_name) if configured is not None else ""})
    return out


def _network(net, cfg, config_path, paths, names, od_mode, embed, plc_cycle_ms, several, warnings):
    nname = net["name"]
    model = dbcexport.build(cfg, config_path, paths, sdo="none", names=names, checked=True)
    all_frames = dbcexport.frames(cfg, model)
    downloads = dcfexport.plugin_downloads(cfg, config_path, paths)
    m = cfg["master"]
    master_id = _u(m.get("node_id"), 1)
    bitrate = _u(net["adapter"].get("bitrate"), 0) or 0
    rates = _Rates(cfg, plc_cycle_ms)
    norm = dbcexport._normalized_pdos(cfg)
    idents = dbcexport.node_identifiers(cfg)
    net_anchor = anchor("net", nname or "network")
    label = (nname + ": ") if several else ""

    nodes, pdo_by_cob = [], {}
    for n, pn, ident in zip(cfg["nodes"], norm, idents):
        node_id = _u(n["node_id"])
        eds, raw = _load_node_eds(n, paths)
        info = eds_mod.device_info(paths[n["eds"]]) or {}
        pdos = _pdos(n, eds, pn, cfg, names)
        node_anchor = anchor("node", nname, node_id)
        for p in pdos:
            p["anchor"] = anchor("pdo", nname, node_id, p["kind"].lower() + str(p["number"]))
            pdo_by_cob[p["cob_id"]] = (p, node_anchor)
        locations = []
        for key, what in NODE_LOCATIONS:
            if n.get(key):
                loc = str(parse_location(n[key]) or n[key])
                locations.append({"location": loc, "what": what, "variables": _plc_names(names, loc)})
        download = downloads.get(node_id)
        node = {"node_id": node_id, "name": n.get("name", ""), "ident": ident, "anchor": node_anchor,
                "eds": {"file": shown_path(n["eds"]), "sha256": hashlib.sha256(raw).hexdigest(),
                        "vendor_name": info.get("vendor_name", ""), "product_name": info.get("product_name", ""),
                        "lss_supported": bool(info.get("lss_supported"))},
                "identity": _identity(n, info), "settings": _node_settings(n, m), "locations": locations,
                "pdos": pdos, "boot": _boot(download, eds, master_id) if download else None,
                "startup_sdos": [{"index": _u(s["index"]), "subindex": _u(s.get("subindex"), 0),
                                  "name": _od_text(eds, _u(s["index"]), _u(s.get("subindex"), 0)),
                                  "type": s["type"], "value": str(s["value"])} for s in n.get("sdo", [])],
                "sdo_variables": _sdo_variables(n, eds, names),
                "od": _od(eds, node_id, pdos, download, n, od_mode)}
        if embed:
            node["eds"]["data"] = base64.b64encode(raw).decode("ascii")
        nodes.append(node)

    # Frames and bus load.
    hb_period = {}
    for n in cfg["nodes"]:
        node_id = _u(n["node_id"])
        if "guard_time_ms" in n:
            hb_period[node_id] = ("guarding", _u(n["guard_time_ms"]))
        elif "heartbeat_ms" in n:
            hb_period[node_id] = ("heartbeat", _u(n["heartbeat_ms"]))
        else:
            eds, _ = _load_node_eds(n, paths)
            hb_period[node_id] = ("heartbeat", _eds_value(eds, 0x1017, 0, node_id) or 0)
    frames, cyclic_bits, worst_bits, unbounded = [], 0.0, 0.0, []
    seen = {}
    for msg in all_frames:
        kind = getattr(msg, "kind", None)
        consumers = sorted({r for s in msg.signals for r in s.receivers}) if msg.signals else []
        bits = frame_bits(msg.length)
        cyc = worst = 0.0
        link = ""
        note = msg.comment
        if kind == "master_heartbeat":
            if msg.cycle_ms:
                cyc = worst = _per(msg.cycle_ms)
                trigger = "every %d ms" % msg.cycle_ms
            else:
                trigger = "off (boot-up message only)"
            consumers = [i for i, n in zip(idents, cfg["nodes"]) if n.get("heartbeat_consumer") is True]
        elif kind == "time":
            cyc = worst = _per(msg.cycle_ms)
            trigger = "every %d ms" % msg.cycle_ms
        elif kind in ("sdo_request", "sdo_response"):
            trigger = "on demand (boot configuration, SDO variables, diagnostics)"
            consumers = [msg.name.rsplit("_SDO_", 1)[0]] if kind == "sdo_request" else [dbcexport.MASTER]
        elif msg.cob_id == 0:
            kind, trigger = "nmt", "on demand"
        elif msg.cob_id == 0x80 and msg.name == "SYNC":
            kind = "sync"
            consumers = list(idents)
            if rates.sync_ms:
                cyc = worst = _per(rates.sync_ms)
            trigger = "every " + _sync_text(rates) if rates.sync_ms or rates.plc_cycle else "off"
            if rates.plc_cycle and not rates.sync_ms:
                trigger += "; not counted: PLC cycle not given"
        elif 0x81 <= msg.cob_id <= 0xFF:
            kind, trigger = "emcy", "on error"
        elif 0x701 <= msg.cob_id <= 0x77F and msg.name.endswith("_Heartbeat"):
            node_id = msg.cob_id - 0x700
            how, period = hb_period.get(node_id, ("heartbeat", 0))
            if how == "guarding" and period:
                kind = "guarding"
                trigger = "node guarding: master request and node answer every %d ms" % period
                cyc = worst = _per(period)
                bits = frame_bits(1) + frame_bits(0, rtr=True)
            elif period:
                kind = "heartbeat"
                trigger = "every %d ms" % period
                cyc = worst = _per(period)
            else:
                kind = "heartbeat"
                trigger = "off (boot-up message only)"
            consumers = [dbcexport.MASTER]
        elif msg.cob_id in pdo_by_cob and ("_TPDO" in msg.name or "_RPDO" in msg.name):
            p, node_anchor = pdo_by_cob[msg.cob_id]
            kind = p["kind"].lower()
            cyc, worst, trigger, unb = _pdo_rates(p, rates)
            link = p["anchor"]
            if unb:
                node_id = int(node_anchor.rsplit("-", 1)[1])
                text = "%snode %d %s %d is event-driven with no inhibit time or event timer: its bus load is " \
                       "unbounded" % (label, node_id, p["kind"], p["number"])
                unbounded.append(text)
                warnings.append(text)
            p["trigger"] = trigger
        else:
            kind, trigger = "other", ""
        cyclic_bits += bits * cyc
        worst_bits += bits * worst
        frames.append({"cob_id": msg.cob_id, "name": msg.name, "kind": kind, "producer": msg.sender,
                       "consumers": consumers, "dlc": msg.length, "bits": bits, "trigger": trigger,
                       "rate_cyclic": round(cyc, 4), "rate_worst": round(worst, 4),
                       "load_cyclic": _pct(bits, cyc, bitrate), "load_worst": _pct(bits, worst, bitrate),
                       "notes": note, "link": link, "duplicate": False})
        seen.setdefault(msg.cob_id, []).append(frames[-1])
    for cob, same in seen.items():
        if len(same) > 1:
            for f in same:
                f["duplicate"] = True
            warnings.append("%sCOB-ID %s is used by %s" % (label, hx(cob, 3), ", ".join(f["name"] for f in same)))
    cyclic = round(100.0 * cyclic_bits / bitrate, 2) if bitrate else None
    worst = round(100.0 * worst_bits / bitrate, 2) if bitrate else None
    notes = []
    if rates.plc_cycle and rates.sync_ms is None:
        notes.append("SYNC follows the PLC cycle, which was not given: SYNC and SYNC-driven PDOs are left out "
                     "of the totals.")
    if worst is not None and worst > LOAD_WARNING_PCT:
        warnings.append("%sestimated worst-case bus load %.1f %% is above %d %%" % (label, worst, LOAD_WARNING_PCT))

    io = []
    for key, who, path, text in contract.location_uses(net):
        io.append({"key": list(key), "location": text, "network": nname, "who": who, "path": path,
                   "variables": _plc_names(names, text)})
    master_locations = []
    for key, what in MASTER_LOCATIONS:
        if m.get(key):
            loc = str(parse_location(m[key]) or m[key])
            master_locations.append({"location": loc, "what": what, "variables": _plc_names(names, loc)})
    return {
        "name": nname, "anchor": net_anchor, "role": "master", "master_node_id": master_id,
        "interface": net["adapter"].get("interface") or net["adapter"].get("type", ""), "bitrate": bitrate,
        "settings": _master_settings(net, cfg), "locations": master_locations, "frames": frames,
        "bus_load": {"cyclic": cyclic, "worst": worst, "unbounded": unbounded, "notes": notes,
                     "sync_ms": rates.sync_ms, "plc_cycle_ms": plc_cycle_ms if rates.plc_cycle else None},
        "nodes": nodes, "io": io,
    }


SLAVE_LOCATIONS = (
    ("state_location", "own NMT state (0 not started, 4 stopped, 5 operational, 127 pre-operational)"),
    ("comm_ok_location", "TRUE while OPERATIONAL with no heartbeat or life guarding error"),
    ("sync_count_location", "SYNCs received (wraps at 65535)"),
    ("emcy_code_location", "EMCY error code the program sends (0 resets the error)"),
    ("error_register_location", "error register sent with the program's EMCY"),
)


def _slave_pdos(eds, node_id, bound, names):
    """The PDOs a slave's EDS defines, as `_pdos` gives a node's: the EDS
    communication and mapping values, entries bound to the config's PLC
    locations. PDOs whose COB-ID has the invalid bit set are left out."""
    out = []
    for tx, kind, comm_base in ((True, "TPDO", 0x1800), (False, "RPDO", 0x1400)):
        for k in range(eds.pdo_count("input" if tx else "output")):
            comm = comm_base + k
            cob = _eds_value(eds, comm, 1, node_id or 0)
            if cob is None or cob & 0x80000000:
                continue
            info = eds_mod.mapping_info(eds, comm + 0x200)
            entries, bit = [], 0
            for v in info["defaults"]:
                index, sub, length = v >> 16, (v >> 8) & 0xFF, v & 0xFF
                if index < 0x0008:
                    entries.append({"bit": bit, "length": length, "index": index, "subindex": sub, "name": "dummy",
                                    "type": CO_TYPE_BY_CODE.get(index, ""), "location": "", "variables": [],
                                    "used": False, "dummy": True})
                else:
                    obj = eds.find(index, sub)
                    loc = bound.get((index, sub), "")
                    entries.append({"bit": bit, "length": length, "index": index, "subindex": sub,
                                    "name": _od_text(eds, index, sub), "type": (obj.type_name if obj else "") or "",
                                    "location": loc, "variables": _plc_names(names, loc), "used": bool(loc),
                                    "dummy": False})
                bit += length
            trans = _eds_value(eds, comm, 2, node_id or 0)
            inhibit = _eds_value(eds, comm, 3, node_id or 0)
            out.append({"kind": kind, "number": k + 1, "anchor": "", "cob_id": cob & 0x7FF,
                        "transmission": trans, "transmission_from_eds": trans is not None,
                        "transmission_text": _transmission_meaning(trans),
                        "inhibit_time_us": inhibit * 100 if (tx and inhibit) else None,
                        "event_timer_ms": _eds_value(eds, comm, 5, node_id or 0), "sync_start": None,
                        "mapping": "eds", "direction": "this PLC → upper master" if tx else
                        "upper master → this PLC", "dlc": (bit + 7) // 8, "bits": bit, "entries": entries})
    return out


def _slave_frame(cob_id, name, kind, producer, consumers, dlc, trigger, bitrate, rate=0.0, worst=None, link="",
                 note=""):
    bits = frame_bits(dlc)
    worst = rate if worst is None else worst
    return {"cob_id": cob_id, "name": name, "kind": kind, "producer": producer, "consumers": consumers,
            "dlc": dlc, "bits": bits, "trigger": trigger, "rate_cyclic": round(rate, 4), "rate_worst": round(worst, 4),
            "load_cyclic": _pct(bits, rate, bitrate), "load_worst": _pct(bits, worst, bitrate), "notes": note,
            "link": link, "duplicate": False}


def _slave_network(net, paths, names, od_mode, embed, plc_cycle_ms, several, warnings, gateway):
    """A slave network (canopen-slave-device): the PLC is one device of it and
    another master runs the bus. Documents the device as its EDS and the
    config's bindings define it and the frames it takes part in."""
    nname, s, a = net["name"], net["slave"], net["adapter"]
    node_id = _u(s.get("node_id")) if s.get("node_id") is not None else None
    bitrate = _u(a.get("bitrate"), 0) or 0
    label = (nname + ": ") if several else ""
    net_anchor = anchor("net", nname or "network")
    with open(paths[s["eds"]], "rb") as f:
        raw = f.read()
    text, _, _ = edslint.check(raw, node_id or 1)
    eds = eds_mod.Eds.read(s["eds"], text)
    info = eds_mod.device_info(paths[s["eds"]]) or {}
    me = "OpenPLC"
    upper = "upper master"

    bound, objects = {}, []
    for o in s.get("objects", []):
        index, sub = _u(o.get("index")), _u(o.get("subindex"), 0)
        loc = str(parse_location(o.get("iec_location", "")) or o.get("iec_location", ""))
        bound[(index, sub)] = loc
        obj = eds.find(index, sub)
        access = obj.access if obj else ""
        side = contract.slave_direction(access)
        objects.append({"index": index, "subindex": sub, "name": o.get("name") or _od_text(eds, index, sub),
                        "type": (obj.type_name if obj else "") or "", "access": access,
                        "direction": {"input": "upper master writes, PLC reads",
                                      "output": "PLC writes, upper master reads"}.get(side, ""),
                        "location": loc, "variables": _plc_names(names, loc), "pdo": ""})
    pdos = _slave_pdos(eds, node_id, bound, names)
    dev_anchor = anchor("node", nname, node_id if node_id is not None else "lss")
    carried = {}
    for p in pdos:
        p["anchor"] = anchor("pdo", nname, node_id if node_id is not None else "lss",
                             p["kind"].lower() + str(p["number"]))
        for e in p["entries"]:
            if not e["dummy"]:
                carried.setdefault((e["index"], e["subindex"]), []).append(
                    "%s%d bits %d-%d" % (p["kind"], p["number"], e["bit"], e["bit"] + e["length"] - 1))
    for o in objects:
        o["pdo"] = ", ".join(carried.get((o["index"], o["subindex"]), [])) or "SDO only"

    hb = _eds_value(eds, 0x1017, 0, node_id or 0) or 0
    consumer = []
    for sub in range(1, 128):
        v = _eds_value(eds, 0x1016, sub, node_id or 0)
        if v is None:
            break
        if (v >> 16) & 0x7F and v & 0xFFFF:
            consumer.append("node %d, timeout %d ms" % ((v >> 16) & 0x7F, v & 0xFFFF))
    sync_cob = _eds_value(eds, 0x1005, 0, node_id or 0)
    emcy_cob = _eds_value(eds, 0x1014, 0, node_id or 0)

    rows = []

    def add(label_, value, obj=""):
        rows.append({"label": label_, "value": value, "object": obj})

    add("Adapter", "%s %s" % (a.get("type", "socketcan"), a.get("interface") or (
        shown_path(a["device"]) if a.get("device") else "")))
    if a.get("bitrate"):
        add("Bitrate", "%d kbit/s" % (bitrate // 1000))
    if a.get("simulate"):
        add("Simulated network", "yes: the network runs on the in-plugin virtual bus")
    add("Role", "slave: another master runs this bus and OpenPLC is one of its devices")
    add("Own node ID", str(node_id) if node_id is not None else "none at start: assigned by an LSS master")
    add("Heartbeat produced", "%d ms" % hb if hb else "off (boot-up message only)", "0x1017")
    add("Watches heartbeats", "; ".join(consumer) if consumer else "none", "0x1016")
    if sync_cob is not None:
        add("SYNC consumed", "COB-ID %s" % hx(sync_cob & 0x7FF, 3), "0x1005")
    if emcy_cob is not None:
        add("EMCY", "COB-ID %s" % hx(emcy_cob & 0x7FF, 3), "0x1014")
    add("Inputs while not OPERATIONAL or communication is lost", {"zero": "set to 0"}.get(
        s.get("inputs_on_loss"), "keep their last values"))
    add("EDS lint", s.get("eds_lint", "communication"))
    if gateway and gateway["upper"] == nname:
        add("Gateway", "%d routes to the master networks (see Gateway)" % len(gateway["routes"]))

    locations = []
    for key, what in SLAVE_LOCATIONS:
        if s.get(key):
            loc = str(parse_location(s[key]) or s[key])
            locations.append({"location": loc, "what": what, "variables": _plc_names(names, loc)})

    identity = []
    for key, sub, field in (("vendor_id", 1, "Vendor ID"), ("product_code", 2, "Product code"),
                            ("revision_number", 3, "Revision"), ("serial_number", 4, "Serial number")):
        v = _eds_value(eds, 0x1018, sub, node_id or 0)
        identity.append({"field": field, "eds": v if v is not None else info.get(key), "expected": None,
                         "checked": False})
    keys = {(0x1000, 0)} | {(0x1018, k) for k in range(5)} | set(bound)
    for p in pdos:
        keys |= {(e["index"], e["subindex"]) for e in p["entries"] if not e["dummy"]}
    od = [{"index": i, "subindex": k, "name": _od_text(eds, i, k), "type": o.type_name or
           eds_mod.data_type_name(o.data_type), "access": o.access, "low": o.low_limit, "high": o.high_limit,
           "default": o.default, "configured": ""}
          for i, k, o in eds.items() if od_mode == "all" or (i, k) in keys]
    device = {"node_id": node_id, "name": "OpenPLC", "ident": me, "anchor": dev_anchor, "role": "slave",
              "eds": {"file": shown_path(s["eds"]), "sha256": hashlib.sha256(raw).hexdigest(),
                      "vendor_name": info.get("vendor_name", ""), "product_name": info.get("product_name", ""),
                      "lss_supported": bool(info.get("lss_supported"))},
              "identity": identity, "settings": [], "locations": locations, "pdos": pdos, "boot": None,
              "startup_sdos": [], "sdo_variables": [], "objects": objects, "od": od}
    if embed:
        device["eds"]["data"] = base64.b64encode(raw).decode("ascii")

    # Frames: what this device sends and receives; the upper master's own
    # frames and timing are not in this config.
    frames, cyclic_bits, worst_bits, unbounded = [], 0.0, 0.0, []
    frames.append(_slave_frame(0x000, "NMT", "nmt", upper, [me], 2, "on demand", bitrate))
    if sync_cob is not None and sync_cob & 0x7FF:
        frames.append(_slave_frame(sync_cob & 0x7FF, "SYNC", "sync", upper, [me], 0,
                                   "set by the upper master; not counted", bitrate))
    if node_id is not None:
        hb_rate = _per(hb)
        frames.append(_slave_frame(0x700 + node_id, "OpenPLC_Heartbeat", "heartbeat", me, [upper], 1,
                                   "every %d ms" % hb if hb else "off (boot-up message only)", bitrate, hb_rate))
        if emcy_cob is not None and not emcy_cob & 0x80000000:
            frames.append(_slave_frame(emcy_cob & 0x7FF, "OpenPLC_EMCY", "emcy", me, [upper], 8, "on error",
                                       bitrate))
        frames.append(_slave_frame(0x600 + node_id, "OpenPLC_SDO_Request", "sdo_request", upper, [me], 8,
                                   "on demand (the upper master's configuration and SDO access)", bitrate))
        frames.append(_slave_frame(0x580 + node_id, "OpenPLC_SDO_Response", "sdo_response", me, [upper], 8,
                                   "on demand", bitrate))
        for p in pdos:
            if p["kind"] == "TPDO":
                t = p["transmission"]
                if t is not None and t <= 240:
                    cyc = worst = 0.0
                    trigger = "SYNC from the upper master; not counted"
                else:
                    # The plugin sends a changed event-driven TPDO at the end
                    # of the PLC scan (docs/slave.md), so at most once a scan
                    # unless the inhibit time is longer.
                    cyc, worst, trigger, _ = _pdo_rates(p, _NoSync())
                    scan = "at most once per PLC scan"
                    if plc_cycle_ms and (not worst or _per(plc_cycle_ms) < worst):
                        worst = _per(plc_cycle_ms)
                        trigger = "on change, %s (%g ms)" % (scan, plc_cycle_ms) + (
                            ", event timer %d ms" % p["event_timer_ms"] if p["event_timer_ms"] else "")
                    elif not worst:
                        trigger = "on change, %s; not counted: PLC cycle not given" % scan
                frames.append(_slave_frame(p["cob_id"], "OpenPLC_TPDO%d" % p["number"], "tpdo", me, [upper],
                                           p["dlc"], trigger, bitrate, cyc, worst, p["anchor"]))
            else:
                trigger = "sent by the upper master; not counted"
                frames.append(_slave_frame(p["cob_id"], "OpenPLC_RPDO%d" % p["number"], "rpdo", upper, [me],
                                           p["dlc"], trigger, bitrate, link=p["anchor"]))
            p["trigger"] = trigger
    frames.sort(key=lambda f: (f["cob_id"], f["name"]))
    seen = {}
    for f in frames:
        seen.setdefault(f["cob_id"], []).append(f)
        cyclic_bits += f["bits"] * f["rate_cyclic"]
        worst_bits += f["bits"] * f["rate_worst"]
    for cob, same in seen.items():
        if len(same) > 1:
            for f in same:
                f["duplicate"] = True
            warnings.append("%sCOB-ID %s is used by %s" % (label, hx(cob, 3), ", ".join(f["name"] for f in same)))
    notes = ["Another master runs this bus: its SYNC, its own frames, other devices and the RPDO rates are not in "
             "this configuration, so the totals count only the frames this device times itself."]
    if not plc_cycle_ms and any(p["kind"] == "TPDO" and (p["transmission"] or 0) > 240 for p in pdos):
        notes.append("The PLC cycle was not given: event-driven TPDOs, sent at most once per PLC scan, are left "
                     "out of the worst case.")
    if node_id is None:
        notes.append("The node ID is assigned by LSS at run time: the device's COB-IDs follow it and are not listed.")
    io = []
    for key, who, path, text_ in contract.location_uses(net):
        io.append({"key": list(key), "location": text_, "network": nname, "who": who, "path": path,
                   "variables": _plc_names(names, text_)})
    return {
        "name": nname, "anchor": net_anchor, "role": "slave", "master_node_id": None,
        "interface": a.get("interface") or a.get("type", ""), "bitrate": bitrate,
        "settings": rows, "locations": [], "frames": frames,
        "bus_load": {"cyclic": round(100.0 * cyclic_bits / bitrate, 2) if bitrate else None,
                     "worst": round(100.0 * worst_bits / bitrate, 2) if bitrate else None,
                     "unbounded": unbounded, "notes": notes, "sync_ms": None, "plc_cycle_ms": None},
        "nodes": [device], "io": io,
    }


class _NoSync:
    """Rates of a slave network for _pdo_rates: the SYNC is not this config's."""
    plc_cycle = False
    sync_ms = None
    has_sync = False
    sync_cycles = 1


def _gateway(cfg, networks):
    """The gateway section (canopen-gateway) of a config, or None."""
    g = cfg.get("gateway") if isinstance(cfg.get("gateway"), dict) else None
    if not g:
        return None
    by_name = {n["name"]: n for n in networks}
    upper = by_name.get(g.get("upper"))
    upper_dev = upper["nodes"][0] if upper and upper["role"] == "slave" and upper["nodes"] else None
    od = {(o["index"], o["subindex"]): o for o in (upper_dev["od"] if upper_dev else [])}
    routes = []
    for r in g.get("routes", []):
        sl, fd = r.get("slave", {}), r.get("field", {})
        si, ss = _u(sl.get("index")), _u(sl.get("subindex"), 0)
        fi, fs = _u(fd.get("index")), _u(fd.get("subindex"), 0)
        node = _u(fd.get("node"))
        o = od.get((si, ss))
        side = contract.slave_direction(o["access"]) if o else None
        field_net = by_name.get(fd.get("network"))
        link = ""
        if field_net:
            link = next((n["anchor"] for n in field_net["nodes"] if n["node_id"] == node), "")
        routes.append({"name": r.get("name", ""), "slave_index": si, "slave_subindex": ss,
                       "slave_name": o["name"] if o else "", "type": o["type"] if o else "",
                       "direction": {"input": "down: upper master → field node",
                                     "output": "up: field node → upper master"}.get(side, ""),
                       "field_network": fd.get("network", ""), "field_node": node, "field_index": fi,
                       "field_subindex": fs, "field_link": link})
    status = _u((g.get("status") or {}).get("index"), 0x5E00)
    return {"upper": g.get("upper", ""), "routes": routes, "status_index": status,
            "emcy_forward": bool(g.get("emcy_forward")), "on_upper_loss": g.get("on_upper_loss", "hold"),
            "sdo_bridge": bool(g.get("sdo_bridge")), "sdo_bridge_index": _u(g.get("sdo_bridge_index"), 0x5F00),
            "sdo_bridge_write": bool(g.get("sdo_bridge_write"))}


def build(cfg, config_path, eds_paths=None, names=None, network=None, title=None, od="used", embed_eds=False,
          plc_cycle_ms=None, now=None):
    """The document model of a config. `names`: {location: [PLC variable
    names]} of an editor project, or None. Raises ExportFailed with the
    config checks' errors."""
    if od not in OD_OPTIONS:
        raise ValueError("od must be one of %s" % ", ".join(OD_OPTIONS))
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
    warnings = list(result.warnings)
    several = len(every) > 1
    networks = []
    gateway_cfg = cfg.get("gateway") if isinstance(cfg.get("gateway"), dict) else None
    for net in nets:
        if net["role"] == "slave":
            networks.append(_slave_network(net, paths, names, od, embed_eds, plc_cycle_ms, several, warnings,
                                           gateway_cfg and {
                "upper": gateway_cfg.get("upper"), "routes": gateway_cfg.get("routes", [])}))
            continue
        one = contract.network_config(cfg, net["name"] if net["path"] else None)
        networks.append(_network(net, one, config_path, paths, names, od, embed_eds, plc_cycle_ms, several, warnings))
    gateway = _gateway(cfg, networks) if network is None else None
    io = sorted((r for n in networks for r in n["io"]), key=lambda r: (r["key"], r["network"], r["who"]))
    for n in networks:
        del n["io"]
    raw = json.dumps(cfg, indent=2, ensure_ascii=False) + "\n"
    try:
        with open(config_path, "rb") as f:
            data = f.read()
        if json.loads(data.decode("utf-8")) == cfg:
            raw = data.decode("utf-8")
    except (OSError, ValueError):
        pass  # an unsaved config (configurator): its JSON as the tools save it
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    raw = _without_token(raw, cfg)
    now = now or datetime.datetime.now()
    return {
        "doc_schema_version": DOC_SCHEMA_VERSION,
        "title": title or DEFAULT_TITLE,
        "generated": now.strftime("%Y-%m-%d %H:%M"),
        "tool": {"name": "canworks-deploy", "version": __version__},
        "config": {"file": os.path.basename(config_path), "sha256": digest,
                   "schema_version": contract.version_of(cfg), "text": raw},
        "warnings": warnings,
        "networks": networks,
        "gateway": gateway,
        "io": io,
    }


def _without_token(text, cfg):
    """The config text with every diagnostics token verifier (or former hash) replaced."""
    for net in contract.networks(cfg):
        for d in (net["master"].get("diagnostics"), net["json"].get("diagnostics"), cfg.get("diagnostics")):
            for key in ("token_verifier", "token_sha256"):
                if isinstance(d, dict) and isinstance(d.get(key), str) and d[key]:
                    text = text.replace(d[key], "(removed)")
    return text


def export(cfg, config_path, **kw):
    """(HTML text, warnings) of a config. Raises ExportFailed."""
    from . import docwriter
    model = build(cfg, config_path, **kw)
    return docwriter.write(model), model["warnings"]


def write_file(text, path):
    """Writes the document (UTF-8) through a temporary file and a rename;
    returns the path."""
    folder = os.path.dirname(os.path.abspath(path))
    fd, tmp = tempfile.mkstemp(prefix="." + os.path.basename(path) + ".", dir=folder)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise
    return path
