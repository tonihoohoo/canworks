"""canworks-config: serves the configurator page on 127.0.0.1.

  canworks-config [PATH] [--port N] [--no-browser] [--foreground] [--keep-running] [--new-instance]
  canworks-config --create-shortcut | --remove-shortcut

PATH opens directly: as an editor project when it has project.json (the
config is PATH/canworks/canworks.json), otherwise as a standalone config folder
(PATH/canworks.json). Without PATH the page opens on its start page.

By default the configurator runs in the background (launch.py), and it stops
when its last page is closed: 10 s after the page said so, or 60 minutes
after the last page without unsaved changes stopped answering (a page with
unsaved changes never times out, and time the computer slept does not
count); --keep-running keeps it. A second
canworks-config opens a page of the running one.

Every request must carry the session token: the URL printed at start carries
a one-time code that the server swaps for the token as a cookie for the page
(the token itself is never in a URL), and the page sends it as a header on API
calls.
Requests whose Host is not loopback are refused (DNS rebinding).
"""

import base64
import copy
import datetime
import hashlib
import http.server
import io
import json
import mimetypes
import os
import re
import secrets
import shutil
import signal
import string
import sys
import tempfile
import threading
import time
import traceback
import urllib.parse
import webbrowser
import zipfile

from .. import __version__, bridgecheck, contract, dbcexport, dcfexport, diag, docexport, editorproject, edslint, mainmove, modbusmap, parameters, project as project_mod, plclibrary
from .. import bundle, connections, mailboxlayout, mailboxuse, nodered, openplcmodbus, targets
from .. import notes as notes_mod, slaveeds
from .. import eds as eds_mod
from ..bustrace import explain as explain_mod, framebuild
from ..bustrace import formats as formats_mod, recorder as recorder_mod, sequences as sequences_mod, triggers as triggers_mod
from ..eds import Eds, EdsError
from ..iec import CO_TYPES, element_str, parse_location
from ..devices import service as devices_service
from ..userdirs import FileLockedError, config_dir, replace_file
from ..j1939 import dbc as j1939_dbc, dm as j1939_dm, stcall as j1939_stcall
from . import declare, launch, layout, online, params, rawpage, scan, simulation, start, tracing, transmit
from . import update as update_mod

STATIC = os.path.join(os.path.dirname(__file__), "static")
TOKEN_HEADER = "X-CANopen-Token"
COOKIE = "canopen_session"  # + "_<port>": configurators on different ports keep their own sessions
CONFIG = "canworks.json"
MAX_BODY = 32 * 1024 * 1024
MAX_TRACE_FILE = 1024 * 1024 * 1024
RECENT_MAX = 10
UNEXPECTED_ERROR = "The configurator hit an error; see its terminal, or configurator.log in its settings folder."

# When the configurator stops by itself (Server.unused): a page that said it
# was closing ends this long after (a reload comes back sooner); a page that
# stopped answering ends PAGE_SILENT_S after its last heartbeat when that
# said it had no unsaved changes, and never by silence when it had some (a
# locked screen or a background tab stops a page's timers, and only the
# server can save its changes); a start address nobody opened ends after
# STARTUP_GRACE_S. A page "answers" (a second start asks it first) while its
# last heartbeat is less than PAGE_ANSWERING_S old. A watch tick more than
# SLEEP_GAP_S after the one before means the process did not run (the
# computer slept): that time does not count as silence.
PAGE_CLOSED_S = 10.0
PAGE_SILENT_S = 3600.0
PAGE_ANSWERING_S = 180.0
STARTUP_GRACE_S = 600.0
WATCH_TICK_S = 1.0
SLEEP_GAP_S = 30.0

# Key order of a saved file; keys not listed keep their place after these.
ORDER = {
    "": ["$schema", "schema_version", "adapter", "master", "nodes", "links", "networks", "gateway", "bridge", "diagnostics", "cia309"],
    "network": ["name", "protocol", "role", "adapter", "master", "nodes", "links", "slave", "j1939"],
    "adapter": ["type", "simulate", "interface", "bitrate", "configure_link", "restart_ms"],
    "master": ["node_id", "sync_period_us", "heartbeat_ms", "eds_lint", "strict_eds", "bus_state_location",
               "tx_error_count_location", "rx_error_count_location", "bus_off_count_location", "state_location",
               "vendor_id", "product_code", "revision_number", "serial_number", "sync_window_us",
               "sync_counter_overflow", "time_cob_id", "time_period_ms", "emcy_inhibit_time_us", "heartbeat_consumer",
               "heartbeat_multiplier", "error_behavior", "nmt_inhibit_time_us", "start", "start_nodes",
               "start_all_nodes", "reset_all_nodes", "stop_all_nodes", "boot_time_ms", "sdo_timeout_ms",
               "diagnostics", "cia309"],
    "node": ["node_id", "name", "eds", "simulate", "heartbeat_ms", "heartbeat_timeout_ms", "guard_time_ms",
             "life_time_factor",
             "status_location", "state_location", "boot_error_location", "emcy_code_location",
             "error_register_location", "emcy_cob_id", "nmt_command_location", "mandatory", "boot",
             "reset_communication", "revision_number", "serial_number", "lss", "heartbeat_consumer", "heartbeat_watch",
             "retry_factor",
             "time_cob_id", "error_behavior", "restore_configuration", "config_check", "store_configuration",
             "tx_pdos", "rx_pdos", "sdo", "sdo_variables"],
    "pdo": ["number", "cob_id", "transmission", "inhibit_time_us", "event_timer_ms", "sync_start", "timeout_ms",
            "on_timeout", "timeout_location", "entries"],
    "entry": ["index", "subindex", "type", "iec_location"],
    "sdo": ["index", "subindex", "type", "value"],
    "sdo_variable": ["name", "index", "subindex", "type", "direction", "iec_location", "period_ms",
                     "trigger_location", "status_location", "abort_code_location", "timeout_ms"],
    "diagnostics": ["token_verifier", "token_sha256", "port", "bind", "allow_changes", "allow_config_upload",
                    "remote_link"],
    "cia309": list(contract.CIA309_FIELDS),
    "lss": ["assign", "store"],
    "slave": ["node_id", "eds", "eds_lint", "inputs_on_loss", "state_location", "comm_ok_location",
              "sync_count_location", "emcy_code_location", "error_register_location", "objects"],
    "slave_object": ["index", "subindex", "name", "iec_location"],
    "gateway": ["upper", "routes", "status", "emcy_forward", "on_upper_loss", "sdo_bridge", "sdo_bridge_index",
                "sdo_bridge_write"],
    "route": ["name", "slave", "field"],
    "route_field": ["network", "node", "index", "subindex"],
    "bridge": list(bridgecheck.KEYS),
    "live_list": ["network", "location"],
    "sdo_bridge_location": ["request", "response"],
}


THEMES = ("auto", "light", "dark")


# Page settings kept in ui.json, with their choices and defaults.
UI_SETTINGS = {"theme": (THEMES, "auto"), "dbc_sdo": (dbcexport.SDO_OPTIONS, "none"),
               "workspace": (("configure", "commission", "devices"), "configure"), "panel": (("open", "closed"), "open"),
               "node_tab": (("general", "pdos", "sdos", "supervision", "simulation", "notes", "advanced"), "general"),
               "update_check": (("on", "off"), "on")}

# The network tree's folded networks: a list of network names (or "#<index>").
TREE_FOLDED_MAX = 8

# The heights of the resizable list boxes, per kind of box: {"sdo_picker": 600}.
BOX_KIND = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
BOX_HEIGHTS_MAX = 32
BOX_RANGE = (120, 3000)


def _tree_folded(value):
    if not isinstance(value, list) or len(value) > TREE_FOLDED_MAX or \
            not all(isinstance(v, str) and 0 < len(v) <= 17 for v in value):
        return None
    return value


def _box_heights(value):
    """The stored box heights, or None when `value` is not a valid table."""
    if not isinstance(value, dict) or len(value) > BOX_HEIGHTS_MAX:
        return None
    for k, v in value.items():
        if not isinstance(k, str) or not BOX_KIND.match(k) or isinstance(v, bool) or not isinstance(v, int) \
                or not BOX_RANGE[0] <= v <= BOX_RANGE[1]:
            return None
    return value


def load_ui():
    """The page settings kept in ui.json in the settings folder (theme, the
    DBC export's SDO choice): not in the browser, whose storage goes with the
    port, which changes at each start. Unknown or broken values read as the
    defaults."""
    try:
        with open(os.path.join(config_dir(), "ui.json"), encoding="utf-8") as f:
            stored = json.load(f)
        if not isinstance(stored, dict):
            stored = {}
    except (OSError, ValueError):
        stored = {}
    out = {k: stored.get(k) if stored.get(k) in choices else default
           for k, (choices, default) in UI_SETTINGS.items()}
    out["tree_folded"] = _tree_folded(stored.get("tree_folded")) or []
    out["box_heights"] = _box_heights(stored.get("box_heights")) or {}
    return out


def load_theme():
    return load_ui()["theme"]


def save_ui(changes):
    """Stores the settings in `changes` (any of UI_SETTINGS), keeping the rest."""
    if not isinstance(changes, dict) or not changes:
        raise ApiError(400, "give at least one of: " + ", ".join(list(UI_SETTINGS) + ["tree_folded", "box_heights"]))
    ui = load_ui()
    for key, value in changes.items():
        if key == "tree_folded":
            if _tree_folded(value) is None:
                raise ApiError(400, "tree_folded must be a list of at most %d network names" % TREE_FOLDED_MAX)
            ui[key] = value
            continue
        if key == "box_heights":
            if _box_heights(value) is None:
                raise ApiError(400, "box_heights must map at most %d box kinds to heights of %d to %d px"
                               % ((BOX_HEIGHTS_MAX,) + BOX_RANGE))
            ui[key] = value
            continue
        if key not in UI_SETTINGS:
            raise ApiError(400, "unknown setting %r" % key)
        choices, _ = UI_SETTINGS[key]
        if value not in choices:
            raise ApiError(400, "%s must be one of: %s" % (key, ", ".join(choices)))
        ui[key] = value
    os.makedirs(config_dir(), exist_ok=True)
    tmp = os.path.join(config_dir(), "ui.json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(ui, f, indent=2)
    replace_file(tmp, os.path.join(config_dir(), "ui.json"))
    return ui


def _ordered(obj, kind):
    if not isinstance(obj, dict):
        return obj
    keys = ORDER.get(kind, [])
    out = {k: obj[k] for k in keys if k in obj}
    out.update((k, v) for k, v in obj.items() if k not in out)
    return out


def canonical(cfg):
    """The config with its keys in a fixed order (unknown keys kept): the
    top level of version 1, or of each network of version 2."""
    cfg = _canonical_network(_ordered(cfg, ""))
    if isinstance(cfg.get("gateway"), dict):
        g = cfg["gateway"] = _ordered(cfg["gateway"], "gateway")
        if isinstance(g.get("routes"), list):
            g["routes"] = [_ordered(rt, "route") for rt in g["routes"]]
            for rt in g["routes"]:
                if isinstance(rt, dict):
                    for key, kind in (("slave", "entry"), ("field", "route_field")):
                        if isinstance(rt.get(key), dict):
                            rt[key] = _ordered(rt[key], kind)
    if isinstance(cfg.get("bridge"), dict):
        b = cfg["bridge"] = _ordered(cfg["bridge"], "bridge")
        if isinstance(b.get("live_lists"), list):
            b["live_lists"] = [_ordered(e, "live_list") for e in b["live_lists"]]
        if isinstance(b.get("sdo_bridge_location"), dict):
            b["sdo_bridge_location"] = _ordered(b["sdo_bridge_location"], "sdo_bridge_location")
    if isinstance(cfg.get("diagnostics"), dict):
        cfg["diagnostics"] = _ordered(cfg["diagnostics"], "diagnostics")
    if isinstance(cfg.get("cia309"), dict):
        cfg["cia309"] = _ordered(cfg["cia309"], "cia309")
    if isinstance(cfg.get("networks"), list):
        cfg["networks"] = [_canonical_network(_ordered(net, "network")) if isinstance(net, dict) else net
                           for net in cfg["networks"]]
    return cfg


def keep_order(new, old):
    """`new` with the keys of each object in the order `old` (the file on
    disk) has them, so a save changes only the lines of what changed. Keys
    `old` lacks go after the key that precedes them in `new`; lists match
    item by item."""
    if isinstance(new, dict) and isinstance(old, dict):
        keys = [k for k in old if k in new]
        for i, k in enumerate(new):
            if k not in old:
                before = next((p for p in reversed(list(new)[:i]) if p in keys), None)
                keys.insert(keys.index(before) + 1 if before is not None else 0, k)
        return {k: keep_order(new[k], old.get(k)) for k in keys}
    if isinstance(new, list) and isinstance(old, list):
        return [keep_order(v, old[i] if i < len(old) else None) for i, v in enumerate(new)]
    return new


def _canonical_network(cfg):
    if isinstance(cfg.get("adapter"), dict):
        cfg["adapter"] = _ordered(cfg["adapter"], "adapter")
    if isinstance(cfg.get("master"), dict):
        cfg["master"] = _ordered(cfg["master"], "master")
        if isinstance(cfg["master"].get("diagnostics"), dict):
            cfg["master"]["diagnostics"] = _ordered(cfg["master"]["diagnostics"], "diagnostics")
        if isinstance(cfg["master"].get("cia309"), dict):
            cfg["master"]["cia309"] = _ordered(cfg["master"]["cia309"], "cia309")
    if isinstance(cfg.get("slave"), dict):
        cfg["slave"] = _ordered(cfg["slave"], "slave")
        if isinstance(cfg["slave"].get("objects"), list):
            cfg["slave"]["objects"] = [_ordered(o, "slave_object") for o in cfg["slave"]["objects"]]
    nodes = []
    for n in cfg.get("nodes") or []:
        n = _ordered(n, "node")
        if isinstance(n, dict):
            if isinstance(n.get("lss"), dict):
                n["lss"] = _ordered(n["lss"], "lss")
            for key in ("tx_pdos", "rx_pdos"):
                if isinstance(n.get(key), list):
                    n[key] = [dict(_ordered(p, "pdo"), entries=[_ordered(e, "entry") for e in p.get("entries", [])])
                              if isinstance(p, dict) and isinstance(p.get("entries"), list) else p for p in n[key]]
            if isinstance(n.get("sdo"), list):
                n["sdo"] = [_ordered(s, "sdo") for s in n["sdo"]]
            if isinstance(n.get("sdo_variables"), list):
                n["sdo_variables"] = [_ordered(v, "sdo_variable") for v in n["sdo_variables"]]
        nodes.append(n)
    if "nodes" in cfg:
        cfg["nodes"] = nodes
    return cfg


# The contract's error for a master network without nodes ("Empty network is a warning").
NO_NODES = re.compile(r"field 'nodes' lists no slave nodes")


def empty_config():
    """A new config before its target's marker (switch_target adds it)."""
    return {"schema_version": 2,
            "networks": [{"adapter": {"type": "socketcan", "interface": "can0", "bitrate": 500000,
                                      "restart_ms": BUS_OFF_RESTART_MS},
                          "master": {"node_id": 1}, "nodes": []}]}


# A SocketCAN adapter the bridge sets up without a bus-off restart (Problems
# for bridge stop and bus-off); the page offers the 100 ms fix.
BUS_OFF_RESTART_MS = 100  # app.js BUS_OFF_RESTART_MS
BUS_OFF_TEXT = "restart_ms is not set: after a bus-off the interface stays off until it is restarted by hand"


def bus_off_problems(cfg):
    """Problems-pane warnings for every SocketCAN adapter the bridge
    configures (configure_link on) without restart_ms; a simulated bus and
    a vcan interface have no bus-off. CODESYS sets up its own adapter."""
    if targets.target(cfg) != targets.BRIDGE:
        return []
    v2 = isinstance(cfg.get("networks"), list)
    out = []
    for k, net in enumerate(cfg["networks"] if v2 else [cfg]):
        a = net.get("adapter") if isinstance(net, dict) else None
        if not isinstance(a, dict) or a.get("type", "socketcan") != "socketcan" or a.get("simulate") is True:
            continue
        iface = a.get("interface")
        if isinstance(iface, str) and iface.startswith("vcan"):
            continue
        if a.get("configure_link") is False or "restart_ms" in a:
            continue
        at = ("networks[%d]." % k if v2 else "") + "adapter.restart_ms"
        out.append({"level": "warning", "message": ("networks[%d]: " % k if v2 else "") + "adapter: " + BUS_OFF_TEXT,
                    "paths": [at]})
    return out


SCHEMA_FILE = "canworks.v%d.schema.json"


def codesys_found():
    """Whether this PC has CODESYS (Build into CODESYS project runs it)."""
    from ..codesys import run as codesys_run
    return bool(codesys_run.find_codesys())


def version2(cfg):
    """The config as a version 2 file (a removed plugin config of version 1,
    for the switch)."""
    if not isinstance(cfg, dict) or contract.version_of(cfg) == 2:
        return cfg
    net, out = {}, {}
    for k, v in cfg.items():
        if k in ("adapter", "master", "nodes", "links", "interface", "bitrate"):
            net[k] = copy.deepcopy(v)
        elif k == "schema_version":
            continue
        else:
            out[k] = v
    master = net.get("master")
    for key in ("diagnostics", "cia309"):
        if isinstance(master, dict) and key in master:
            out[key] = master.pop(key)
    ref = out.get("$schema")
    if isinstance(ref, str) and ref.endswith(SCHEMA_FILE % 1):
        out["$schema"] = ref[:-len(SCHEMA_FILE % 1)] + SCHEMA_FILE % 2
    return dict({"$schema": out.pop("$schema")} if "$schema" in out else {}, schema_version=2, networks=[net], **out)


def device_networks(cfg):
    """The open config's networks for the Devices page's remote CAN adapter
    (devices.plan.adapter_row): interface, bit rate in kbit/s and serial device."""
    out = []
    for net in contract.networks(cfg or {}):
        a = net.get("adapter") if isinstance(net.get("adapter"), dict) else {}
        try:
            kbit = int(str(a.get("bitrate")), 0) // 1000 if a.get("bitrate") is not None else None
        except ValueError:
            kbit = None
        out.append({"interface": a.get("interface"), "bitrate_kbit": kbit, "device": a.get("device")})
    return out


def device_target(cfg):
    """The project's kind for the Devices page (devices.plan): "codesys",
    "openplc_modbus" for a bridge config with an OpenPLC connection (the
    runtime goes on the device too), else "bridge"; None for a plugin config."""
    tgt = targets.target(cfg)
    if tgt == targets.BRIDGE and bridgecheck.is_openplc(cfg):
        return "openplc_modbus"
    return None if tgt == targets.PLUGIN else tgt


def _at(cfg, path):
    """The value at a JSON path ("networks[0].nodes[1].tx_pdos[0].entries[2]"), or None."""
    obj = cfg
    for part in re.findall(r"[^.[\]]+", path):
        try:
            obj = obj[int(part)] if part.isdigit() else obj[part]
        except (KeyError, IndexError, TypeError):
            return None
    return obj


def place_entries(cfg):
    """Gives every PDO entry of a master network that has no location a
    stand-in one of its type's size (%IB0, %QW0, ...), for a pack to place
    it (an RPDO entry with bits too: the bridge serves its bits there);
    returns how many."""
    n = 0
    for net in contract.networks(cfg):
        for node in net["nodes"]:
            if not isinstance(node, dict):
                continue
            for key, direction in (("tx_pdos", "input"), ("rx_pdos", "output")):
                for p in node.get(key) or []:
                    for e in (p.get("entries") or []) if isinstance(p, dict) else []:
                        if not isinstance(e, dict) or e.get("iec_location") or e.get("type") not in CO_TYPES:
                            continue
                        area, size = layout.area_size(direction, e["type"])
                        e["iec_location"] = element_str(area, size, 0)
                        n += 1
    return n


# What only the removed OpenPLC plugin had: unknown fields in a bridge config.
PLUGIN_MASTER_FIELDS = ("sync_source", "sync_cycles", "scan_watchdog_ms")


def strip_plugin_fields(cfg):
    """Removes from a version 2 config what only the removed OpenPLC plugin
    used: the master's PLC-cycle SYNC and scan watchdog, the J1939 and raw
    scan watchdogs, a node's CiA 402 `axis` and the bit channels' own
    locations (the bridge serves bits in the entry's location). Returns how
    many values went."""
    n = 0

    def pop(obj, key):
        nonlocal n
        if isinstance(obj, dict) and key in obj:
            del obj[key]
            n += 1

    for net in cfg.get("networks") or []:
        if not isinstance(net, dict):
            continue
        for key in PLUGIN_MASTER_FIELDS:
            pop(net.get("master"), key)
        pop(net.get("j1939"), "scan_watchdog_ms")
        pop(net.get("raw"), "scan_watchdog_ms")
        for node in net.get("nodes") or []:
            pop(node, "axis")
            for key in ("tx_pdos", "rx_pdos"):
                for p in (node.get(key) or []) if isinstance(node, dict) else []:
                    for e in (p.get("entries") or []) if isinstance(p, dict) else []:
                        for b in (e.get("bits") or []) if isinstance(e, dict) else []:
                            pop(b, "iec_location")
    return n


def migrate(cfg):
    """Pre-contract keys in their current form. Returns (config, [notice])."""
    notices = []
    cfg, notice = migrate_adapter(cfg)
    if notice:
        notices.append(notice)
    cfg, notice = migrate_strict_eds(cfg)
    if notice:
        notices.append(notice)
    return cfg, notices


def migrate_strict_eds(cfg):
    """master.strict_eds as eds_lint (true "all", false "off"), in its
    place, in a version 1 file and in each network of a version 2 file. A
    master with both keeps both, for the check to report."""
    if not isinstance(cfg, dict):
        return cfg, None
    if isinstance(cfg.get("networks"), list):
        cfg = dict(cfg)
        nets, notice = [], None
        for net in cfg["networks"]:
            net, n = _migrate_strict_eds(net)
            nets.append(net)
            notice = notice or n
        cfg["networks"] = nets
        return cfg, notice
    return _migrate_strict_eds(cfg)


def _migrate_strict_eds(holder):
    """migrate_strict_eds for one object with a `master`."""
    master = holder.get("master") if isinstance(holder, dict) else None
    if isinstance(master, dict) and master.get("eds_lint") == "communication" and "strict_eds" not in master:
        # The default; the page saves it as no field.
        holder = dict(holder)
        holder["master"] = {k: v for k, v in master.items() if k != "eds_lint"}
        return holder, None
    if not isinstance(master, dict) or not isinstance(master.get("strict_eds"), bool) or "eds_lint" in master:
        return holder, None
    mode = "all" if master["strict_eds"] else "off"
    holder = dict(holder)
    holder["master"] = {("eds_lint" if k == "strict_eds" else k): (mode if k == "strict_eds" else v)
                        for k, v in master.items()}
    return holder, ("This file uses the old 'strict_eds': %s. It is shown as EDS lint \"%s\", and saving writes it as "
                    "'eds_lint'." % ("true" if mode == "all" else "false", {"all": "every object", "off": "off"}[mode]))


def migrate_adapter(cfg):
    """Pre-contract top-level interface/bitrate as an adapter. Returns
    (config, notice or None)."""
    if isinstance(cfg, dict) and "adapter" not in cfg and ("interface" in cfg or "bitrate" in cfg):
        cfg = dict(cfg)
        adapter = {"type": "socketcan"}
        if "interface" in cfg:
            adapter["interface"] = cfg.pop("interface")
        if "bitrate" in cfg:
            adapter["bitrate"] = cfg.pop("bitrate")
        adapter["configure_link"] = False
        out = {}
        for k, v in cfg.items():
            out[k] = v
            if k == "schema_version":
                out["adapter"] = adapter
        out.setdefault("adapter", adapter)
        return out, ("This file uses the old top-level 'interface' and 'bitrate' keys. They are shown as a SocketCAN "
                     "adapter with 'configure link' off, and saving writes them as 'adapter'.")
    return cfg, None


def eds_summary(eds, path=None):
    objects = []
    for index, sub, o in eds.items():
        obj = {"index": "0x%04X" % index, "subindex": sub, "name": o.name, "type": o.type_name,
               "type_code": o.data_type, "var": eds.object_types.get(index, 0x7) == 0x7,
               "access": o.access, "directions": list(o.directions) if o.type_name else [],
               "readable": o.access != "wo", "writable": o.writable, "default": o.default}
        # LowLimit/HighLimit as numbers (the Simulation view's sliders).
        for key in ("low_limit", "high_limit"):
            v = parameters.limit_number(getattr(o, key, ""), o.data_type, 0)
            if v is not None:
                obj[key] = v
        objects.append(obj)
    # Each PDO's mapping object: whether the master can write it, and the
    # device's default mapping (for "Set by the device" and "Map all").
    # `enabled`: the PDO is on as the device starts (COB-ID bit 31 clear), for
    # the default PDOs of a new node.
    pdo_maps = {}
    for direction, base, comm in (("input", 0x1A00, 0x1800), ("output", 0x1600, 0x1400)):
        pdo_maps[direction] = {}
        for k in range(eds.pdo_count(direction)):
            m = eds_mod.mapping_info(eds, base + k)
            cob = eds.find(comm + k, 1)
            cob_value = cob.value(1) if cob is not None else None
            pdo_maps[direction][str(k + 1)] = {
                "writable": m["writable"], "has_default": m["has_default"],
                "enabled": cob_value is not None and not cob_value & 0x80000000,
                "defaults": [{"index": "0x%04X" % (v >> 16), "subindex": (v >> 8) & 0xFF, "bits": v & 0xFF}
                             for v in m["defaults"]]}
    # [DeviceInfo]: identity and LSS_Supported.
    return {"objects": objects, "pdo_count": {"input": eds.pdo_count("input"), "output": eds.pdo_count("output")},
            "pdo_maps": pdo_maps, "dummy": sorted(eds.dummy), "device": eds_mod.device_info(path) if path else None}


def utf8_eds(data):
    """(UTF-8 bytes, converted from CP1252?) - the project route's rule."""
    return project_mod.to_utf8(data)


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()



def _token_matches(token, body):
    """Whether `token` is the one in body's token_verifier (or, for a config
    from before the encrypted channel, its token_sha256). True when the body
    gives neither."""
    if not token:
        return False
    verifier = (body.get("token_verifier") or "").strip()
    old = (body.get("token_sha256") or "").strip().lower()
    if verifier:
        return diag.token_matches(token, verifier)
    if old:
        return hashlib.sha256(token.encode("utf-8")).hexdigest() == old
    return True

class ApiError(Exception):
    def __init__(self, status, message, **extra):
        super().__init__(message)
        self.status = status
        self.body = dict(error=message, **extra)


def folder_error(e, doing, folder):
    """An OSError as one sentence naming the folder: "cannot read the
    folder /x: permission denied"."""
    if isinstance(e, FileLockedError):
        return ApiError(409, "cannot %s the folder %s: %s" % (doing, folder, e))
    reason = (e.strerror or str(e)).lower() if isinstance(e, OSError) else str(e)
    return ApiError(403 if isinstance(e, PermissionError) else 500,
                    "cannot %s the folder %s: %s" % (doing, folder, reason))


class Session:
    """What the page is editing. One user, one folder at a time."""

    def __init__(self):
        self.lock = threading.RLock()
        self.mode = None  # "project" | "standalone"
        self.commission = False  # "Commission a device": a scratch folder, online pages on a USB adapter
        self.folder = None
        self.loaded = None  # (mtime, sha256) of canworks.json as loaded, or None when there was none
        self.saved_cfg = None  # canworks.json as the last state read it (outdated editor files are for it)
        self.sim_loaded = None  # sha256 of simulation.json as loaded, or None when there was none
        self.pending = {}  # EDS name -> UTF-8 bytes imported but not yet saved
        self.descriptions = {}  # EDS name -> slave EDS description built but not yet saved
        self.pending_dbc = {}  # DBC name -> bytes imported for a J1939 network but not yet saved
        self.pending_dir = tempfile.mkdtemp(prefix="canopen-config-")
        self.uses, self.scan_problems, self.scanned_at = [], [], None

    # -- paths --------------------------------------------------------------
    @property
    def canopen_dir(self):
        return os.path.join(self.folder, "canworks") if self.mode == "project" else self.folder

    @property
    def config_path(self):
        return os.path.join(self.canopen_dir, CONFIG)

    @property
    def sim_path(self):
        return os.path.join(self.canopen_dir, simulation.SIM_FILE)

    def notes_eds_path(self, value):
        """Where an EDS's notes file lives: next to it in the canopen folder,
        also for an EDS imported but not saved yet."""
        return value if os.path.isabs(value) else os.path.join(self.canopen_dir, value)

    def eds_path(self, value):
        if value in self.pending:
            return os.path.join(self.pending_dir, value)
        return value if os.path.isabs(value) else os.path.join(self.canopen_dir, value)

    def carry_source(self, value, library):
        """(name, bytes) of the EDS a node uses in Commission a device, for
        "Add to a config…": an EDS imported in this session and not saved yet,
        a file in this folder or a file in the EDS library. Read before the
        config opens, which drops this session's unsaved imports."""
        if not isinstance(value, str) or not value.lower().endswith(".eds"):
            raise ApiError(400, "carry_eds must be an EDS file")
        if value in self.pending:
            return value, self.pending[value]
        path = self.eds_path(value)
        if not under(path, (self.canopen_dir, library)) or not os.path.isfile(path):
            raise ApiError(403, "%s cannot be carried into the config: only EDS files of this session or the "
                                "EDS library can be" % os.path.basename(value))
        try:
            with open(path, "rb") as f:
                return os.path.basename(path), f.read()
        except OSError as e:
            raise ApiError(404, "%s cannot be carried into the config: %s" % (os.path.basename(value),
                                                                               e.strerror or e))

    # -- recent folders -----------------------------------------------------
    def recent(self):
        try:
            with open(os.path.join(config_dir(), "recent.json"), encoding="utf-8") as f:
                items = json.load(f)
            return [r for r in items if isinstance(r, dict) and isinstance(r.get("path"), str)][:RECENT_MAX]
        except (OSError, ValueError):
            return []

    def recent_listed(self):
        """Recent for the start page: each entry with its config's target
        (None when the config is missing or cannot be read)."""
        out = []
        for r in self.recent():
            folder = os.path.join(r["path"], project_mod.DIR) if r.get("mode") == "project" else r["path"]
            try:
                with open(os.path.join(folder, CONFIG), encoding="utf-8") as f:
                    target = targets.target(json.load(f))
            except (OSError, ValueError):
                target = None
            out.append(dict(r, target=target))
        return out

    def remember(self):
        if os.path.dirname(self.folder) == os.path.abspath(config_dir()):
            return  # the "Commission a device" scratch folder
        items = [r for r in self.recent() if r["path"] != self.folder]
        items.insert(0, {"path": self.folder, "mode": self.mode, "opened": int(time.time())})
        self._write_recent(items)

    def forget(self, path):
        """Drops a folder from Recent (one that was moved or deleted)."""
        self._write_recent([r for r in self.recent() if r["path"] != path])

    def _write_recent(self, items):
        try:
            os.makedirs(config_dir(), exist_ok=True)
            tmp = os.path.join(config_dir(), "recent.json.tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(items[:RECENT_MAX], f, indent=2)
            replace_file(tmp, os.path.join(config_dir(), "recent.json"))
        except OSError:
            pass  # a convenience only

    # -- open / close -------------------------------------------------------
    def open(self, path, mode="auto", new=None):
        """Opens a folder. `new` False (Open… on the start page) wants an
        existing canworks.json, True (New config…) refuses one;
        None (Recent, the command line) takes either."""
        path = os.path.abspath(os.path.expanduser(path or ""))
        try:
            if os.path.isdir(path):
                os.listdir(path)  # what is in it can only be told when it can be read
        except OSError as e:
            raise folder_error(e, "read", path)
        is_project = os.path.isfile(os.path.join(path, "project.json"))
        if mode == "auto":
            mode = "project" if is_project else "standalone"
        if mode == "project":
            if not os.path.isdir(path):
                raise ApiError(404, "%s does not exist" % path)
            if not is_project:
                raise ApiError(422, "%s is not an OpenPLC Editor project (it has no project.json)" % path,
                               not_a_project=True, path=path)
        elif mode == "standalone":
            if os.path.isfile(os.path.join(path, "project.json")):
                raise ApiError(422, "%s is an editor project; open it as a project" % path, is_project=True)
            if os.path.exists(path) and not os.path.isdir(path):
                raise ApiError(422, "%s is not a folder" % path)
            if new is False and not os.path.isdir(path):
                raise ApiError(404, "%s does not exist" % path)
            if new is False and not os.path.isfile(os.path.join(path, CONFIG)):
                raise ApiError(404, "%s has no config yet" % path, no_config=True, path=path)
            if new is True and os.path.isfile(os.path.join(path, CONFIG)):
                raise ApiError(409, "%s already has a %s" % (path, CONFIG), has_config=True, path=path)
        else:
            raise ApiError(400, "unknown mode %r" % mode)
        # Read what state() reads before anything changes: an unreadable
        # folder leaves the page where it was.
        folder = os.path.join(path, "canworks") if mode == "project" else path
        try:
            if os.path.isdir(folder):
                os.listdir(folder)
            for f in (os.path.join(folder, CONFIG), os.path.join(folder, simulation.SIM_FILE)):
                if os.path.isfile(f):
                    open(f, "rb").close()
        except OSError as e:
            raise folder_error(e, "read", folder)
        self.mode, self.folder = mode, path
        self.commission = False
        self.pending.clear()
        self.descriptions.clear()
        self.pending_dbc.clear()
        try:
            self.reload()
        except OSError as e:
            self.close()
            raise folder_error(e, "read", folder)
        self.remember()

    def new_config(self, path, editor_project=False, target=None):
        """New config… on the start page: a config folder, or with
        `editor_project` a new OpenPLC Editor project with a Modbus bridge
        config and its OpenPLC connection, opened as a project. Either way
        the target's empty config is written on Create, so a reload shows the
        new config with its target."""
        if target is not None and target not in targets.TARGETS:
            raise ApiError(400, "target must be one of: " + ", ".join(targets.TARGETS))
        if not editor_project:
            self.open(path, "standalone", new=True)
            return self._write_new(target)
        path = os.path.abspath(os.path.expanduser(path or ""))
        if os.path.isfile(os.path.join(path, "project.json")):
            raise ApiError(409, "%s is already an editor project" % path, is_project=True, path=path)
        if os.path.isfile(os.path.join(path, CONFIG)):
            raise ApiError(409, "%s already has a %s" % (path, CONFIG), has_config=True, path=path)
        try:
            editorproject.create(None, None, path)
        except editorproject.NewProjectError as e:
            raise ApiError(422, str(e))
        self.open(path, "project")
        self._write_new(target, openplc=target in (None, targets.BRIDGE))
        if bridgecheck.is_openplc(self.read_config()[0]):
            cfg = self.read_config()[0]
            try:
                self.sync_openplc(cfg, force=True)
            except OSError as e:
                raise folder_error(e, "write to", self.folder)
            self.rescan()

    def default_config(self):
        """The empty config of the default target, the Modbus bridge; in an
        editor project with an OpenPLC connection."""
        cfg = self.switch_target(empty_config(), targets.BRIDGE, openplc=False)["config"]
        return self._with_openplc(cfg) if self.mode == "project" else cfg

    def _write_new(self, target, openplc=False):
        """Writes the empty config of `target` (default the Modbus bridge),
        with an OpenPLC connection when `openplc`, into the folder just
        opened, unless it has one."""
        if os.path.isfile(self.config_path):
            return
        cfg = self.switch_target(empty_config(), target or targets.BRIDGE, openplc=False)["config"]
        if openplc:
            cfg = self.add_connection(cfg, {"kind": "openplc"})["config"]
        try:
            self._save(cfg, None)
        except OSError as e:
            raise folder_error(e, "write to", self.canopen_dir)

    def commission_device(self):
        """"Commission a device": a scratch standalone folder in the settings
        folder, with the online pages on a USB adapter and no config needed."""
        folder = os.path.join(config_dir(), "commission")
        os.makedirs(folder, exist_ok=True)
        self.open(folder, "standalone")
        self.commission = True

    def close(self):
        self.commission = False
        self.mode = self.folder = self.loaded = self.sim_loaded = None
        self.pending.clear()
        self.descriptions.clear()
        self.pending_dbc.clear()

    def reload(self):
        self.pending.clear()
        self.descriptions.clear()
        self.pending_dbc.clear()
        if os.path.isfile(self.config_path):
            self.loaded = (os.path.getmtime(self.config_path), sha256(self.config_path))
        else:
            self.loaded = None
        self.sim_loaded = sha256(self.sim_path) if os.path.isfile(self.sim_path) else None
        self.rescan()

    def rescan(self):
        if self.mode == "project":
            self.uses, self.scan_problems = scan.scan(self.folder)
        else:
            self.uses, self.scan_problems = [], []
        self.scanned_at = time.strftime("%Y-%m-%d %H:%M:%S")

    def changed_on_disk(self):
        exists = os.path.isfile(self.config_path)
        if self.loaded is None:
            return exists
        return not exists or sha256(self.config_path) != self.loaded[1]

    # -- state --------------------------------------------------------------
    def adapter_online(self):
        """Whether online access goes through a USB adapter on this PC: in
        Commission a device, and in a saved CODESYS config, whose bus no
        canworks runtime runs."""
        if self.commission:
            return True
        if not self.mode or not os.path.isfile(self.config_path):
            return False
        cfg, _, error = self.read_config()
        return not error and targets.target(cfg) == targets.CODESYS

    def read_config(self):
        """(config, notices, error)."""
        # Without a readable file: the new config of the default target, as New config... writes it.
        if not os.path.isfile(self.config_path):
            return self.default_config(), [], None
        try:
            with open(self.config_path, encoding="utf-8") as f:
                cfg = contract.load(f)
        except OSError as e:
            return self.default_config(), [], "%s cannot be read: %s" % (self.config_path, (e.strerror or str(e)).lower())
        except ValueError as e:
            return self.default_config(), [], "%s cannot be read: %s" % (self.config_path, e)
        cfg, notices = migrate(cfg)
        return cfg, notices, None

    def eds_info(self, names):
        out = {}
        for name in names:
            path = self.eds_path(name)
            if not os.path.isfile(path):
                out[name] = {"error": "EDS file %s not found" % path}
                continue
            try:
                eds = Eds.read(path)
                out[name] = eds_summary(eds, path)
            except EdsError as e:
                out[name] = {"error": "EDS file %s cannot be parsed: %s" % (path, e)}
                continue
            built = self.built_eds(name)
            out[name]["notes"] = notes_mod.Notes.for_eds(
                eds, name, None if built else self.notes_eds_path(name)).to_json()
            out[name]["notes"]["editable"] = not built and not self.commission
        return out

    def built_eds(self, name):
        """Whether the configurator built this EDS (a slave network's own): it
        gets built-in notes only and no notes file."""
        return name in self.descriptions or os.path.isfile(os.path.join(self.canopen_dir, description_name(name)))

    # -- device notes (spec canopen-device-notes) --------------------------
    def notes_targets(self, cfg):
        """{eds name: EDS path} of the EDS files of the draft that get a notes
        file: in the canopen folder, not built by the configurator."""
        out = {}
        for name, path in self.eds_paths(cfg).items():
            if os.path.isabs(name) or self.built_eds(name) or not os.path.isfile(path):
                continue
            out[name] = path
        return out

    def notes_problems(self, cfg, changes):
        """Warnings of the notes files of the draft, with the page's unsaved edits."""
        items = []
        changes = changes if isinstance(changes, dict) else {}
        for name, path in sorted(self.notes_targets(cfg).items()):
            npath = notes_mod.notes_path(self.notes_eds_path(name))
            fname = os.path.basename(npath)
            doc, error = notes_mod.load(npath)
            if error:
                items.append({"level": "warning", "message": error + "; its notes are not used and it is not changed on save",
                              "paths": [], "notes": name})
                continue
            if doc is None and not changes.get(name):
                continue
            try:
                eds = Eds.read(path)
            except EdsError:
                continue
            doc = notes_mod.update(doc or {"format": notes_mod.FORMAT, "objects": {}}, changes.get(name), eds)
            items += [{"level": "warning", "message": m, "paths": [], "notes": name}
                      for m in notes_mod.check(eds, doc, fname, name)]
        return items

    def save_notes(self, cfg, changes):
        """Writes the notes file of each EDS of the draft: a new one (skeleton
        plus edits) where there is none, the edits into an existing one, and
        nothing into a file that cannot be read. Returns the files written."""
        written = []
        changes = changes if isinstance(changes, dict) else {}
        for name, path in sorted(self.notes_targets(cfg).items()):
            npath = notes_mod.notes_path(self.notes_eds_path(name))
            doc, error = notes_mod.load(npath)
            if error:
                continue
            try:
                with open(path, encoding="utf-8") as f:
                    text = f.read()
                eds = Eds.read(name, text)
            except (OSError, UnicodeDecodeError, EdsError):
                continue
            edits = changes.get(name) if isinstance(changes.get(name), dict) else None
            if doc is not None and not edits:
                continue
            base = doc if doc is not None else notes_mod.skeleton(eds, name, eds_text=text)
            new = notes_mod.update(base, edits, eds)
            with open(npath + ".tmp", "w", encoding="utf-8", newline="\n") as f:
                f.write(notes_mod.dumps(new))
            replace_file(npath + ".tmp", npath)
            written.append(npath)
        return written

    def notes_source(self, changes=None):
        """The notes of the draft's EDS files for the exports: each one's notes
        file over the built-in notes, with the page's unsaved edits."""
        changes = changes if isinstance(changes, dict) else {}

        def source(value, eds):
            built = self.built_eds(value)
            n = notes_mod.Notes.for_eds(eds, value, None if built else self.notes_eds_path(value))
            return n.edited(changes.get(value) if not built and isinstance(changes.get(value), dict) else None)
        return source

    def _draft_notes(self, cfg, name):
        """(EDS, its notes, its path) of one EDS of the draft."""
        paths = self.eds_paths(cfg)
        if name not in paths:
            raise ApiError(422, "no node of the configuration uses the EDS %r" % name)
        try:
            eds = Eds.read(paths[name])
        except (OSError, EdsError) as e:
            raise ApiError(422, "EDS file %s cannot be read: %s" % (paths[name], e))
        built = self.built_eds(name)
        return eds, notes_mod.Notes.for_eds(eds, name, None if built else self.notes_eds_path(name)), paths[name]

    def export_notes(self, cfg, name, changes, own=False):
        """The notes of one EDS of the draft, with the page's edits, as a notes
        document: merged (built-in and device), or with `own` the user's own
        notes only (the device file's filled entries)."""
        eds, n, path = self._draft_notes(cfg, name)
        edits = (changes or {}).get(name) if isinstance(changes, dict) else None
        if own:
            ident = (n.document or {}).get("eds") or notes_mod.identity(name, path)
            doc = {"format": notes_mod.FORMAT, "eds": ident,
                   "objects": notes_mod.own_objects(notes_mod.apply_changes(n.device, edits))}
            return {"name": os.path.basename(name) + notes_mod.SUFFIX, "data": notes_mod.dumps(doc),
                    "count": len(doc["objects"])}
        doc = {"format": notes_mod.FORMAT, "eds": notes_mod.identity(name, path), "objects": n.merged(edits)}
        return {"name": os.path.basename(name) + ".merged" + notes_mod.SUFFIX, "data": notes_mod.dumps(doc)}

    def import_notes(self, cfg, name, text, file_name, changes):
        """What importing a notes file into one EDS of the draft would do, for
        the page to preview and apply as one draft edit (spec
        canopen-device-notes, Import notes). Nothing is written."""
        eds, n, path = self._draft_notes(cfg, name)
        if self.built_eds(name) or self.commission or n.error:
            raise ApiError(422, "the notes of %s cannot be edited here" % name)
        file_name = os.path.basename(file_name or "") or "the file"
        if not isinstance(text, str):
            raise ApiError(422, "no file text")
        doc, error = notes_mod.load_text(text, file_name)
        if error:
            raise ApiError(422, "%s is not a canworks notes file (%s); nothing was imported"
                           % (file_name, error.split(": ", 1)[-1] if error.startswith(file_name) else error))
        edits = (changes or {}).get(name) if isinstance(changes, dict) else None
        n.edited(edits if isinstance(edits, dict) else None)
        out, preview, warnings = notes_mod.plan_import(eds, n, doc, notes_mod.identity(name, path))
        names = {}
        for keys in preview.values():
            for k in keys:
                pk = notes_mod.parse_key(k)
                o = eds.find(pk[0], pk[1] or 0) if pk else None
                if o is not None and o.name:
                    names[k] = o.name
        return {"changes": out, "preview": preview, "names": names, "warnings": warnings}

    def _commission_notes(self, eds_path):
        """(EDS, its name, its text, where its notes file goes) of the EDS a
        node of Commission a device uses; refused when its notes cannot be
        written there (notes are written at once, there is no Save)."""
        if not self.commission:
            raise ApiError(409, "notes are written at once only in Commission a device; use Save in a config")
        if not isinstance(eds_path, str) or not eds_path:
            raise ApiError(400, "eds_path must name the node's EDS file")
        try:
            real, notes_at = params.eds_file(self, eds_path, online.Settings(config_dir()).eds_library)
        except params.Refused as e:
            raise ApiError(e.status, str(e))
        name = os.path.basename(real)
        try:
            eds = Eds.read(real)
            with open(real, encoding="utf-8", errors="replace") as f:
                text = f.read()
        except (OSError, EdsError) as e:
            raise ApiError(422, "EDS file %s cannot be read: %s" % (name, e))
        block = notes_mod.Notes.for_eds(eds, name, notes_at).to_json()
        why = notes_mod.access(notes_at, block)
        if not why["editable"]:
            raise ApiError(422, "the notes of %s cannot be written: %s" % (name, why["why"]))
        return eds, name, text, notes_at

    def write_notes(self, eds_path, changes=None, restore=False, text=None):
        """POST /api/notes/write (Commission a device): the page's changes
        written at once to the notes file next to the node's EDS, or an
        earlier text put back (Undo). Returns the notes block as od_entries
        gives it, the file's name and its text before."""
        eds, name, eds_text, notes_at = self._commission_notes(eds_path)
        if not restore and (not isinstance(changes, dict) or not changes):
            raise ApiError(400, "changes must be {key: note}")
        if restore and text is not None and not isinstance(text, str):
            raise ApiError(400, "text must be the notes file's text or null")
        try:
            before = notes_mod.write(eds, name, eds_text, notes_at, changes, restore, text)
        except notes_mod.NotesError as e:
            raise ApiError(422, str(e))
        except OSError as e:
            raise ApiError(422, "%s cannot be written: %s" % (notes_mod.notes_path(notes_at), e.strerror or e))
        block = notes_mod.Notes.for_eds(eds, name, notes_at).to_json()
        block.update(notes_mod.access(notes_at, block))
        return {"notes": block, "file": os.path.basename(notes_mod.notes_path(notes_at)),
                "path": notes_mod.notes_path(notes_at), "previous": before}

    def import_notes_commission(self, eds_path, text, file_name):
        """Import notes… in Commission a device: the preview of a notes file
        against the node's EDS and its notes file; the page writes the
        changes with write_notes."""
        eds, name, eds_text, notes_at = self._commission_notes(eds_path)
        file_name = os.path.basename(file_name or "") or "the file"
        if not isinstance(text, str):
            raise ApiError(422, "no file text")
        doc, error = notes_mod.load_text(text, file_name)
        if error:
            raise ApiError(422, "%s is not a canworks notes file (%s); nothing was imported"
                           % (file_name, error.split(": ", 1)[-1] if error.startswith(file_name) else error))
        n = notes_mod.Notes.for_eds(eds, name, notes_at)
        out, preview, warnings = notes_mod.plan_import(eds, n, doc, notes_mod.identity(name, text=eds_text))
        names = {}
        for keys in preview.values():
            for k in keys:
                pk = notes_mod.parse_key(k)
                o = eds.find(pk[0], pk[1] or 0) if pk else None
                if o is not None and o.name:
                    names[k] = o.name
        return {"changes": out, "preview": preview, "names": names, "warnings": warnings}

    def eds_paths(self, cfg):
        """{eds value: path} of every node of every network, and of every
        slave network's own EDS."""
        return {n.get("eds"): self.eds_path(n.get("eds")) for n in contract.eds_users(cfg)
                if isinstance(n.get("eds"), str) and n.get("eds")}

    def eds_names(self, cfg):
        names = [n.get("eds") for n in contract.eds_users(cfg)]
        names = [n for n in names if isinstance(n, str) and n]
        if os.path.isdir(self.canopen_dir):
            names += [f for f in sorted(os.listdir(self.canopen_dir)) if f.lower().endswith(".eds")]
        names += list(self.pending)
        names += simulation.extra_eds(simulation.read(self.sim_path)["doc"])
        return list(dict.fromkeys(names))

    def state(self):
        base = {"version": __version__, "recent": self.recent_listed(), "home": home_folder(),
                "openplc_cli": bool(editorproject.cli_command(editorproject.cli_program())),
                "mode": self.mode, "type_bits": {k: v[1] for k, v in CO_TYPES.items()},
                "default_start": layout.DEFAULT_START, "commission": self.commission, "j1939_dm": J1939_DM_TEXTS,
                "targets": targets.table(), "codesys_found": codesys_found()}
        if not self.mode:
            return base
        try:
            return self._state(base)
        except OSError as e:
            # The folder became unreadable: back to the start page, with why.
            error = folder_error(e, "read", self.canopen_dir).body["error"]
            self.close()
            return dict(base, mode=None, commission=False, open_error=error)

    def _state(self, base):
        cfg, notices, error = self.read_config()
        self.saved_cfg = cfg
        sim = simulation.read(self.sim_path)
        sim_eds = simulation.eds_files(self.canopen_dir)
        referenced = {n.get("eds") for n in contract.eds_users(cfg)}
        referenced.update(simulation.extra_eds(sim["doc"]))
        names = self.eds_names(cfg)
        base.update({
            "folder": self.folder, "name": os.path.basename(self.folder.rstrip(os.sep)) or self.folder,
            "canopen_dir": self.canopen_dir, "config_path": self.config_path,
            "config_exists": os.path.isfile(self.config_path), "config": cfg, "notices": notices,
            "load_error": error, "eds": self.eds_info(names), "dbc_files": self.dbc_files(),
            "unused_eds": [n for n in names if n not in referenced and n not in self.pending],
            "slave_descriptions": self.slave_descriptions(names),
            "project_uses": [u.as_dict() for u in self.uses], "scan_problems": self.scan_problems,
            "openplc": self.openplc_info(cfg) if isinstance(cfg, dict) else None,
            "scanned_at": self.scanned_at,
            "simulation": {k: sim[k] for k in ("path", "exists", "doc", "error")},
            "sim_eds": sim_eds + [n for n in self.pending if n not in sim_eds],
        })
        return base

    # -- EDS import ---------------------------------------------------------
    def import_eds(self, name, data, on_conflict=None, eds_lint=None):
        """Stores an EDS for the draft after the checks the PLC runs before
        dcfgen (edslint: prepared copy, read, lint under `eds_lint`, else the
        saved config's setting). Node ID 1 stands in for $NODEID."""
        name = os.path.basename(name or "").strip()
        if not name or name in (".", "..") or name == CONFIG:
            raise ApiError(422, "invalid EDS file name %r" % name)
        mode = eds_lint if eds_lint in edslint.MODES else edslint.effective_mode(lint_master(self.read_config()[0]))
        corrections, lint = check_eds(name, data, mode)
        data, converted = utf8_eds(data)
        existing = None
        if name in self.pending:
            existing = self.pending[name]
        elif os.path.isfile(os.path.join(self.canopen_dir, name)):
            with open(os.path.join(self.canopen_dir, name), "rb") as f:
                existing = f.read()
        if existing is not None and existing != data:
            if on_conflict == "replace":
                pass
            elif on_conflict == "keep_both":
                stem, ext = os.path.splitext(name)
                n = 2
                while (os.path.exists(os.path.join(self.canopen_dir, "%s-%d%s" % (stem, n, ext)))
                       or "%s-%d%s" % (stem, n, ext) in self.pending):
                    n += 1
                name = "%s-%d%s" % (stem, n, ext)
            else:
                raise ApiError(409, "a different EDS named %s is already in %s" % (name, self.canopen_dir),
                               conflict=name)
        self.pending[name] = data
        with open(os.path.join(self.pending_dir, name), "wb") as f:
            f.write(data)
        return {"name": name, "converted": converted, "summary": self.eds_info([name])[name],
                "lint": {"mode": mode, "corrections": [c.to_json() for c in corrections],
                         "accepted": [f.to_json() for f in lint.accepted(mode)]}}

    def import_eds_path(self, path, on_conflict=None, eds_lint=None):
        """An EDS (or a simulation's DCF) picked in the page's file browser
        (one-eds-picker): one in the config folder as it is, any other
        imported as an EDS import would be, with the notes next to it."""
        if not isinstance(path, str) or not path.lower().endswith((".eds", ".dcf")):
            raise ApiError(400, "path must be an EDS or DCF file")
        real = os.path.realpath(os.path.expanduser(path))
        if not os.path.isfile(real):
            raise ApiError(404, "%s is not a file" % path)
        with self.lock:
            if os.path.normcase(os.path.dirname(real)) == os.path.normcase(os.path.realpath(self.canopen_dir)):
                name = os.path.basename(real)
                return {"name": name, "summary": self.eds_info([name])[name], "converted": False}
        try:
            with open(real, "rb") as f:
                data = f.read()
        except OSError as e:
            raise folder_error(e, "read", real)
        with self.lock:
            res = self.import_eds(os.path.basename(real), data, on_conflict, eds_lint)
            res.update(self.notes_beside(real, res["name"]))
        return res

    def notes_beside(self, eds_path, name):
        """The notes next to an EDS taken from a folder (canopen-device-notes
        "Notes come with a picked EDS"), for the import `name`. In a config:
        the notes file's own entries, which the page adds as unsaved edits
        when the config has no notes for that EDS. In Commission a device,
        which has no Save: the file copied at once next to the import, unless
        one is there. A datasheet notes file is only named."""
        out = {}
        datasheet = eds_path + ".datasheet" + notes_mod.SUFFIX
        if os.path.isfile(datasheet):
            out["datasheet_notes"] = os.path.basename(datasheet)
        src = notes_mod.notes_path(eds_path)
        if not os.path.isfile(src):
            return out
        try:
            with open(src, encoding="utf-8") as f:
                text = f.read()
        except (OSError, UnicodeDecodeError):
            return out
        doc, error = notes_mod.load_text(text, os.path.basename(src))
        objects = notes_mod.own_objects(doc["objects"]) if doc else {}
        if error or not objects:
            return out
        if not self.commission:
            out["notes"] = {"file": os.path.basename(src), "objects": objects}
            return out
        dest = notes_mod.notes_path(self.notes_eds_path(name))
        if os.path.exists(dest):
            out["notes_kept"] = {"file": os.path.basename(src), "count": len(objects)}
            return out
        try:
            with open(dest, "w", encoding="utf-8") as f:
                f.write(text)
        except OSError:
            return out
        out["notes_copied"] = {"file": os.path.basename(dest), "count": len(objects)}
        return out

    # -- J1939 DBC import (j1939-pc-tools "J1939 network in the configurator") --
    def dbc_path(self, name):
        if name in self.pending_dbc:
            return os.path.join(self.pending_dir, name)
        return os.path.join(self.canopen_dir, name)

    @staticmethod
    def dbc_names(cfg):
        """The DBC files the config names: each J1939 network's `j1939.dbc`
        and each network's `raw.dbc`."""
        names = set()
        for n in contract.networks(cfg):
            raw = n["json"].get("raw") if isinstance(n.get("json"), dict) else None
            for name in (n["j1939"].get("dbc") if n["role"] == "j1939" else None,
                         raw.get("dbc") if isinstance(raw, dict) else None):
                if isinstance(name, str) and name:
                    names.add(name)
        return names

    def dbc_files(self):
        """The DBC files the draft can use: in the config folder or imported."""
        names = set(self.pending_dbc)
        if os.path.isdir(self.canopen_dir):
            names.update(f for f in os.listdir(self.canopen_dir) if f.lower().endswith(".dbc"))
        return sorted(names)

    def import_dbc(self, name, data=None, on_conflict=None, kind="j1939"):
        """A DBC file for a message picker, of a J1939 network (`kind`
        "j1939") or of the CAN messages page ("raw"): with `data` a new
        file, kept for the draft and written to the config folder on save
        (a different file of that name: 409 unless `on_conflict` is
        "replace" or "keep_both"); without it the file the network already
        names. Returns {name, messages, problems}: for J1939 dbc.load()'s
        messages without their frame IDs' parts the page does not use, for
        raw rawpage.dbc_messages()."""
        name = os.path.basename(name or "").strip()
        if not name or name in (".", "..") or name == CONFIG or not name.lower().endswith(".dbc"):
            raise ApiError(422, "invalid DBC file name %r (it must end in .dbc)" % name)
        new = data is not None
        if not new:
            path = self.dbc_path(name)
            if not os.path.isfile(path):
                raise ApiError(404, "DBC file %s not found" % path)
            with open(path, "rb") as f:
                data = f.read()
        else:
            existing = self.pending_dbc.get(name)
            if existing is None and os.path.isfile(os.path.join(self.canopen_dir, name)):
                with open(os.path.join(self.canopen_dir, name), "rb") as f:
                    existing = f.read()
            if existing is not None and existing != data:
                if on_conflict == "keep_both":
                    stem, ext = os.path.splitext(name)
                    n = 2
                    while (os.path.exists(os.path.join(self.canopen_dir, "%s-%d%s" % (stem, n, ext)))
                           or "%s-%d%s" % (stem, n, ext) in self.pending_dbc):
                        n += 1
                    name = "%s-%d%s" % (stem, n, ext)
                elif on_conflict != "replace":
                    raise ApiError(409, "a different DBC file named %s is already in %s" % (name, self.canopen_dir),
                                   conflict=name)
        if kind == "raw":
            try:
                messages = rawpage.dbc_messages(data.decode("utf-8", "replace"))["messages"]
            except rawpage.RawPageError as e:
                raise ApiError(422, "%s: %s" % (name, e))
            if not messages:
                raise ApiError(422, "%s has no messages to import" % name)
            if new:
                self.pending_dbc[name] = data
                with open(os.path.join(self.pending_dir, name), "wb") as f:
                    f.write(data)
            return {"name": name, "messages": messages, "problems": []}
        try:
            imported = j1939_dbc.load(text=data.decode("utf-8", "replace"))
        except j1939_dbc.ImportFailed as e:
            raise ApiError(422, "%s: %s" % (name, e))
        if not imported.messages:
            raise ApiError(422, "%s has no J1939 messages (29-bit identifiers) to import%s"
                           % (name, ": " + "; ".join(imported.problems) if imported.problems else ""))
        if new:
            self.pending_dbc[name] = data
            with open(os.path.join(self.pending_dir, name), "wb") as f:
                f.write(data)
        return {"name": name, "problems": imported.problems,
                "messages": [dict({k: m[k] for k in ("name", "pgn", "priority", "source", "destination", "length",
                                                     "cycle_ms", "sender", "comment")},
                                  signals=[s["name"] for s in m["signals"]], mux_problem=m.get("mux_problem"),
                                  **rawpage.mux_summary(m["signals"])) for m in imported.messages]}

    def dbc_entries(self, cfg, network, name, picks):
        """rx and tx entries of picked DBC messages for J1939 network
        `network` (index): picks [{index (of import_dbc()'s messages),
        direction "rx"|"tx"}], each signal at a free location of the right
        size (none the config or the editor project uses). Returns
        {entries: [{direction, entry}]}."""
        if not isinstance(cfg, dict) or not isinstance(picks, list):
            raise ApiError(400, "config must be a JSON object and picks a list")
        nets = contract.networks(cfg)
        try:
            if nets[int(network or 0)]["role"] != "j1939":
                raise ApiError(400, "network %s is not a J1939 network" % (int(network or 0) + 1))
        except (IndexError, TypeError, ValueError):
            raise ApiError(400, "no network %r in the config" % network)
        path = self.dbc_path(os.path.basename(name or ""))
        try:
            messages = j1939_dbc.load(path).messages
        except (OSError, j1939_dbc.ImportFailed) as e:
            raise ApiError(422, "%s cannot be read: %s" % (path, e))
        used = j1939_dbc.free_locations(cfg, self.uses)
        out = []
        for p in picks:
            try:
                message = messages[int(p["index"])]
                out.append({"direction": p["direction"], "entry": j1939_dbc.config_entry(message, p["direction"], used)})
            except (KeyError, IndexError, TypeError, ValueError):
                raise ApiError(400, "picks must be {index, direction \"rx\" or \"tx\"} of the DBC's messages")
        return {"entries": out}

    def raw_page(self, op, body):
        """The CAN messages page's requests (rawpage.py)."""
        cfg = body.get("config")
        if not isinstance(cfg, dict):
            raise ApiError(400, "config must be a JSON object")
        try:
            if op == "suggest":
                return rawpage.suggest(cfg, body.get("network", 0), body.get("kind"), body.get("index"), self.uses,
                                       body.get("start"))
            if op == "st":
                return rawpage.st_call(cfg, body.get("network", 0), body.get("kind"), body.get("index"))
            path = self.dbc_path(os.path.basename(body.get("name") or ""))
            try:
                with open(path, "rb") as f:
                    text = f.read().decode("utf-8", "replace")
            except OSError:
                raise ApiError(404, "DBC file %s not found" % path)
            picks = body.get("picks")
            if not isinstance(picks, dict):
                raise ApiError(400, "picks must map message names to receive or send")
            return rawpage.dbc_import(cfg, body.get("network", 0), text, picks, self.uses, body.get("start"))
        except rawpage.RawPageError as e:
            raise ApiError(422 if op == "dbc_import" else 400, str(e))

    def j1939_st(self, cfg, network, kind, index):
        """Copy as ST call for a J1939 rx or tx entry (j1939/stcall.py)."""
        nets = cfg.get("networks") if isinstance(cfg, dict) and isinstance(cfg.get("networks"), list) else [cfg]
        try:
            n = int(network or 0)
            net = nets[n]
            entry = net["j1939"][kind][int(index)]
        except (IndexError, KeyError, TypeError, ValueError):
            raise ApiError(400, "no J1939 %s entry %r on network %r" % (kind, index, network))
        if kind not in ("rx", "tx") or not isinstance(entry, dict):
            raise ApiError(400, "no J1939 %s entry %r on network %r" % (kind, index, network))
        name = net.get("name") if isinstance(net.get("name"), str) and net.get("name") else None
        try:
            return {"text": j1939_stcall.st_call(entry, kind, n, name)}
        except (TypeError, ValueError) as e:
            raise ApiError(400, "cannot write the call: %s" % e)

    # -- checks -------------------------------------------------------------
    def check(self, cfg, notes=None):
        if not isinstance(cfg, dict):
            raise ApiError(400, "config must be a JSON object")
        eds_paths = self.eds_paths(cfg)
        result = contract.check_config(cfg, self.config_path, eds_paths=eds_paths)
        items = list(result.items)
        try:
            items += self.notes_problems(cfg, notes)
        except (OSError, ValueError, TypeError, AttributeError):
            pass  # notes are documentation: they never stop a check
        # The bridge's byte addresses are not the editor project's: no project addresses to clash with.
        tgt = targets.target(cfg)
        if bridgecheck.is_openplc(cfg) and self.mode == "project":
            items += self.openplc_items(cfg)
            items += self.mailbox_items(cfg)
        if tgt == targets.BRIDGE:
            items += connections.problems(cfg)
        items += bus_off_problems(cfg)
        if self.mode == "project":
            items += layout.macro_problems(self.uses)
        decls = []
        try:
            summaries = self.eds_info(list(eds_paths))
            names = {}
            for name, info in summaries.items():
                for o in info.get("objects", []):
                    names[(name, int(o["index"], 16), o["subindex"])] = o["name"]
            types = {}
            for name, info in summaries.items():
                for o in info.get("objects", []):
                    types[(name, int(o["index"], 16), o["subindex"])] = o["type"]
            nodes = contract.all_nodes(cfg)  # declare's node index runs over every network

            def slave_object(value, ix, sub):
                return (names[(value, ix, sub)], types[(value, ix, sub)]) if (value, ix, sub) in names else None

            decls = declare.declarations(
                cfg, lambda i, ix, sub: names.get((nodes[i].get("eds"), ix, sub)), {}, slave_object,
                unlocated=tgt == targets.CODESYS)
        except (KeyError, TypeError, ValueError, AttributeError):
            pass  # the contract errors already say what is wrong with the entries
        for it in items:
            # A master network without nodes is the first step of every config,
            # not a mistake: a warning here, while the hand-off steps refuse it.
            if it["level"] == "error" and NO_NODES.search(it.get("message", "")):
                it["level"], it["handoff"] = "warning", True
        errors = sum(1 for i in items if i["level"] == "error")
        return {"items": items, "errors": errors, "declarations": decls,
                "overlaps": sum(1 for i in items if i.get("overlap"))}

    # -- DCF export ---------------------------------------------------------
    def export_dcf(self, cfg, node_id=None, network=None):
        """The draft's nodes as CiA 306 DCFs (canopen-dcf-export): one node's
        `node_<id>.dcf`, or all of them in `<folder>_dcf.zip`, base64 in
        `data`. With several networks `network` names the one to export
        (`<folder>_<network>_dcf.zip` for all its nodes); without it every
        network goes into the zip, in a folder per network. On a problem:
        the /api/check shape, and no file. Nothing is written to the folder."""
        if not isinstance(cfg, dict):
            raise ApiError(400, "config must be a JSON object")
        if node_id is not None and (isinstance(node_id, bool) or not isinstance(node_id, int)):
            raise ApiError(400, "node must be a node ID")
        network = self._network_arg(cfg, network)
        if node_id is not None and network is None and len(contract.networks(cfg)) > 1:
            raise ApiError(400, "name the network of the node")
        try:
            files, _ = dcfexport.export(cfg, self.config_path, eds_paths=self.eds_paths(cfg), node_id=node_id,
                                        network=network)
        except dcfexport.ExportFailed as e:
            items = [{"level": "error", "message": m, "paths": p} for m, p in e.problems]
            return {"items": items, "errors": len(items)}
        if node_id is not None:
            name, = files
            data, ctype = files[name].encode("utf-8"), "application/octet-stream"
        else:
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
                for n in sorted(files):
                    z.writestr(n, files[n].encode("utf-8"))
            folder = os.path.basename(self.folder.rstrip(os.sep)) or "canworks"
            if network:
                folder += "_" + network
            name, data, ctype = folder + "_dcf.zip", buf.getvalue(), "application/zip"
        return {"items": [], "errors": 0, "name": name, "content_type": ctype,
                "files": sorted(files), "data": base64.b64encode(data).decode("ascii")}

    # -- project target (canopen-configurator "Switching the target") --------
    def switch_target(self, cfg, target, openplc=None):
        """The draft switched to `target`: the target's marker added and the
        old one removed; to CODESYS every PDO entry without a name gets its
        generated name; from CODESYS every entry gets a location, packed for
        the new target; for the bridge every location is repacked.
        What the new target does not use is removed and counted in
        `removed`, from a removed plugin config also what only the plugin
        had (strip_plugin_fields). A plugin config inside an editor project
        gets an OpenPLC connection (Use with canworks-bridge); `openplc`
        False leaves it out (a new config)."""
        if not isinstance(cfg, dict):
            raise ApiError(400, "config must be a JSON object")
        if target not in targets.TARGETS:
            raise ApiError(400, "target must be one of: " + ", ".join(targets.TARGETS))
        out = copy.deepcopy(cfg)
        old = targets.target(out)
        if old == target:
            return {"config": out, "removed": 0, "target": target}
        out = version2(out)
        plugin_only = strip_plugin_fields(out) if old == targets.PLUGIN else 0
        if target == targets.CODESYS:
            self._name_entries(out)
        out.pop("bridge", None)
        out.pop("codesys", None)
        for k, net in enumerate(out.get("networks") or []):
            if isinstance(net, dict) and old == targets.CODESYS:
                net.pop("codesys", None)
                # A runtime needs the adapter's type and interface, which CODESYS does not.
                adapter = net.get("adapter")
                if isinstance(adapter, dict):
                    adapter.setdefault("type", "socketcan")
                    adapter.setdefault("interface", "can%d" % k)
                    # A new adapter for the bridge: restarts itself after a bus-off.
                    if adapter["type"] == "socketcan" and not str(adapter["interface"]).startswith("vcan"):
                        adapter.setdefault("restart_ms", BUS_OFF_RESTART_MS)
        if openplc is None:
            openplc = old == targets.PLUGIN and self.mode == "project"
        openplc = openplc and target == targets.BRIDGE
        if target == targets.BRIDGE:
            out["bridge"] = {"listen": "0.0.0.0:502", "writers": []}
            if openplc:
                out["bridge"] = {"connections": [connections.new("openplc", out)]}
                connections.sync_writers(out)
                connections.openplc_settings(out, out["bridge"]["connections"][0])
        elif target == targets.CODESYS:
            out["codesys"] = {}
        located = 0
        if target in targets.BRIDGES:
            located = place_entries(out)
        gone = [p for p, k, _ in targets.unused(out, target) if targets.removable(k)]
        targets.remove(out, gone)
        if target != targets.CODESYS:
            try:
                out = modbusmap.pack(out)
            except modbusmap.MapError as e:
                raise ApiError(400, str(e))
        old = self.old_main(out) if openplc else None
        return {"config": out, "removed": len(gone) + plugin_only, "located": located, "target": target,
                "old_main": old["count"] if old else 0}

    def _name_entries(self, cfg):
        """Gives every PDO entry without a `name` the name part of its
        generated name, so its CODESYS channel keeps the name it had."""
        eds_paths = self.eds_paths(cfg)
        try:
            summaries = self.eds_info(list(eds_paths))
        except (OSError, ValueError):
            summaries = {}
        names = {(name, int(o["index"], 16), o["subindex"]): o["name"]
                 for name, info in summaries.items() for o in info.get("objects", [])}
        nodes = contract.all_nodes(cfg)
        try:
            decls = declare.declarations(cfg, lambda i, ix, sub: names.get((nodes[i].get("eds"), ix, sub)), {},
                                         unlocated=True)
        except (KeyError, TypeError, ValueError, AttributeError):
            return  # the check says what is wrong with the entries
        for d in decls:
            if d.get("kind") != "pdo":
                continue
            entry = _at(cfg, d["path"][: -len(".iec_location")])
            if isinstance(entry, dict) and not entry.get("name"):
                entry["name"] = d["entry_name"]

    def codesys_build(self, cfg_path, runner=None, remove=None):
        """Builds the saved CODESYS config into its CODESYS project
        (canworks-deploy --codesys-import): {ok, report, output}. Runs
        outside the server lock: CODESYS takes minutes. Nodes an earlier
        build or import managed that the config no longer has are removed
        from the project only with `remove` True; with `remove` None they
        come back as {ok: False, removals: [{network, node_ids}]} for the
        page to ask (canopen-configurator "Build asks before removing
        nodes"). After a build each network's codesys.managed is its
        node IDs (`managed` True when that changed the saved config)."""
        from .. import cli
        from ..codesys import plan as codesys_plan, run as codesys_run
        flags = ["--config", cfg_path, "--codesys-import"] + (["--codesys-remove-nodes"] if remove else [])
        args = cli.parser().parse_args(flags)
        lines = []
        try:
            with open(cfg_path, encoding="utf-8") as f:
                cfg = contract.load(f)
            result = contract.check_config(cfg, cfg_path, eds_paths=bundle.eds_files(cfg, cfg_path))
            if not result.ok:
                return {"ok": False, "output": "\n".join(result.errors), "report": ""}
            gone = codesys_plan.removals(cfg)
            if gone and remove is None:
                return {"ok": False, "output": "", "report": "",
                        "removals": [{"network": n, "node_ids": ids} for n, ids in sorted(gone.items())]}
            cli._codesys(args, cfg, None, lines.append, runner=runner)
            return {"ok": True, "output": "\n".join(lines), "report": "\n".join(lines),
                    "managed": self._set_managed(cfg_path)}
        except cli.MissingProject as e:
            return {"ok": False, "output": "\n".join(lines + [
                "The project file %s does not exist. Pick a PLC device for a new project on the CODESYS page, "
                "or choose an existing project with Browse…." % e.project]), "report": "\n".join(lines)}
        except cli.Failure as e:
            text = str(e)
            hint = None
            if re.search(r"lock|in use|opened by|being used", "\n".join(lines) + text, re.I):
                hint = "Close the project in CODESYS first: a project open in the CODESYS window cannot be built " \
                       "from here."
            return {"ok": False, "output": "\n".join(lines + [text]), "report": "\n".join(lines), "hint": hint}
        except (OSError, ValueError, codesys_run.CodesysError) as e:
            return {"ok": False, "output": "\n".join(lines + [str(e)]), "report": ""}

    def _set_managed(self, cfg_path):
        """Each CANopen master network's codesys.managed set to its node IDs
        in the saved config, after a build; True when the file changed."""
        with self.lock:
            try:
                with open(cfg_path, encoding="utf-8") as f:
                    raw = json.load(f)
            except (OSError, ValueError):
                return False
            if not isinstance(raw.get("networks"), list):
                return False
            changed = False
            for net in contract.networks(raw):
                if net["role"] != "master":
                    continue
                ids = sorted({n["node_id"] for n in net["nodes"] if isinstance(n, dict) and isinstance(n.get("node_id"), int)})
                own = net["json"].get("codesys")
                if not isinstance(own, dict):
                    if not ids:
                        continue
                    own = net["json"]["codesys"] = {}
                if own.get("managed") != ids:
                    own["managed"] = ids
                    changed = True
            if not changed:
                return False
            tmp = cfg_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(raw, f, indent=2, ensure_ascii=False)
                f.write("\n")
            replace_file(tmp, cfg_path)
            if os.path.abspath(cfg_path) == os.path.abspath(self.config_path or ""):
                self.loaded = (os.path.getmtime(cfg_path), sha256(cfg_path))
            return True

    # -- CODESYS export -----------------------------------------------------
    def export_codesys(self, cfg):
        """The draft's master networks for CODESYS (codesys-export): node
        DCFs, canworks-codesys.json and import_canworks.py in
        `<folder>_codesys.zip`, base64 in `data`. On a problem: the /api/check
        shape, and no file. Nothing is written to the folder."""
        from ..codesys import plan as codesys_plan
        if not isinstance(cfg, dict):
            raise ApiError(400, "config must be a JSON object")
        try:
            files, _ = codesys_plan.export_files(cfg, self.config_path, eds_paths=self.eds_paths(cfg))
        except codesys_plan.ExportFailed as e:
            items = [{"level": "error", "message": m, "paths": p} for m, p in e.problems]
            return {"items": items, "errors": len(items)}
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for n in sorted(files):
                z.writestr(n, files[n].encode("utf-8"))
        folder = os.path.basename(self.folder.rstrip(os.sep)) or "canworks"
        return {"items": [], "errors": 0, "name": folder + "_codesys.zip", "content_type": "application/zip",
                "files": sorted(files), "data": base64.b64encode(buf.getvalue()).decode("ascii")}

    # -- DBC export ---------------------------------------------------------
    def export_dbc(self, cfg, sdo="none", network=None, notes=None):
        """The draft as a DBC file (canopen-dbc-export): `<folder>.dbc`, or
        with several networks `<folder>_<network>.dbc` of the one `network`
        names, base64 in `data`, with the export's warnings as items. Signal
        names use the project's located variables in project mode. On a
        problem: the /api/check shape, and no file. Nothing is written to the
        folder."""
        if not isinstance(cfg, dict):
            raise ApiError(400, "config must be a JSON object")
        if sdo not in dbcexport.SDO_OPTIONS:
            raise ApiError(400, "sdo must be one of: " + ", ".join(dbcexport.SDO_OPTIONS))
        network = self._network_arg(cfg, network)
        if network is None and len(contract.networks(cfg)) > 1:
            raise ApiError(400, "name the network to export")
        names = dbcexport.plc_names(self.uses) if self.mode == "project" else None
        try:
            texts, warnings = dbcexport.export_networks(cfg, self.config_path, eds_paths=self.eds_paths(cfg), sdo=sdo,
                                                        names=names, network=network, notes=self.notes_source(notes))
        except dbcexport.ExportFailed as e:
            items = [{"level": "error", "message": m, "paths": p} for m, p in e.problems]
            return {"items": items, "errors": len(items)}
        folder = os.path.basename(self.folder.rstrip(os.sep)) or "canworks"
        name = dbcexport.network_file(folder + ".dbc", network) if network else folder + ".dbc"
        text = texts[0][1]
        return {"items": [{"level": "warning", "message": w, "paths": []} for w in warnings], "errors": 0,
                "name": name, "content_type": "application/octet-stream",
                "data": base64.b64encode(text.encode("ascii")).decode("ascii")}

    # -- network documentation ---------------------------------------------
    def export_html(self, cfg, notes=None):
        """The draft as an HTML document of every network
        (canopen-network-docs): `<folder>.html`, base64 in `data`, with the
        export's warnings as items. PLC variable names and the PLC cycle come
        from the project in project mode. On a problem: the /api/check shape,
        and no file. Nothing is written to the folder."""
        if not isinstance(cfg, dict):
            raise ApiError(400, "config must be a JSON object")
        project = self.mode == "project"
        try:
            text, warnings = docexport.export(
                cfg, self.config_path, eds_paths=self.eds_paths(cfg),
                names=dbcexport.plc_names(self.uses) if project else None,
                notes=self.notes_source(notes))
        except docexport.ExportFailed as e:
            items = [{"level": "error", "message": m, "paths": p} for m, p in e.problems]
            return {"items": items, "errors": len(items)}
        folder = os.path.basename(self.folder.rstrip(os.sep)) or "canworks"
        return {"items": [{"level": "warning", "message": w, "paths": []} for w in warnings], "errors": 0,
                "name": folder + ".html", "content_type": "text/html",
                "data": base64.b64encode(text.encode("utf-8")).decode("ascii")}

    @staticmethod
    def _network_arg(cfg, network):
        """The network name a request gives, or None for a version 1 file
        (whose one network has no name) and when none is given."""
        if network in (None, "") or contract.version_of(cfg) == 1:
            return None
        if not isinstance(network, str):
            raise ApiError(400, "network must be a network name")
        return network

    # -- where a new entry or status bit goes ------------------------------
    def place(self, cfg, node, direction, type_name, start=None, network=0, access=None):
        """Suggested location (and PDO, for an entry) for something new in
        node `node`: direction "input"/"output" with a CANopen type, or
        direction "status" for the node's status bit, "state" for its
        state byte, "boot_error" for its boot error byte, "emcy" for its
        EMCY code word, "errreg" for its error register byte, "nmt" for its
        NMT command byte, "sdo_read"/"sdo_write" with a CANopen type for an
        SDO variable's value, "sdo_trigger", "sdo_status" or "sdo_abort" for
        an SDO variable's other locations, or a master diagnostic key (no
        node needed). For a slave network: "slave_object" with the object's
        CANopen type and EDS `access`, or "slave_state", "slave_comm_ok",
        "slave_sync_count", "slave_emcy", "slave_errreg" (no node needed).
        `network` is the index of the node's network; the suggestion skips
        the locations of every network. For a J1939 network: "j1939_state",
        "j1939_address", "j1939_status", "j1939_valid" and the diagnostics
        keys of J1939_PLACES (no node needed), "j1939_dm_dtcs" with the number
        of codes as type (that many free consecutive %ID), or
        "j1939_rx"/"j1939_tx" with the signal's length in bits as type."""
        used = layout.taken(cfg, self.uses) if isinstance(cfg, dict) else set()
        start = layout.DEFAULT_START if start in (None, "") else int(start)
        for key, size, _, _ in layout.MASTER_LOCATIONS:
            if direction == key:
                return {"location": layout.suggest("I", size, used, start)}
        for _, area, size, suffix, _ in layout.SLAVE_LOCATIONS:
            if direction == "slave_" + suffix:
                return {"location": layout.suggest(area, size, used, start)}
        if direction == "slave_object":
            side = contract.slave_direction(access)
            if side is None or type_name not in CO_TYPES:
                raise ApiError(400, "a slave object needs a CANopen type and AccessType rww, rw, ro or rwr "
                                    "(const and wo cannot be bound)")
            return {"location": layout.suggest(*layout.area_size(side, type_name), used, start)}
        if direction in J1939_PLACES:
            return {"location": layout.suggest(*J1939_PLACES[direction], used, start)}
        if direction == "j1939_dm_dtcs":
            # A watched ECU's codes: `type_name` consecutive double words.
            try:
                count = int(type_name)
            except (TypeError, ValueError):
                count = 0
            if not 1 <= count <= 32:
                raise ApiError(400, "the codes of a watched ECU need their number, 1 to 32, as type")
            return {"location": layout.suggest("I", "D", used, start, count)}
        if direction in ("j1939_rx", "j1939_tx"):
            # A signal: `type_name` is its length in bits.
            try:
                size = j1939_dbc.location_size(int(type_name))
            except (StopIteration, TypeError, ValueError):
                raise ApiError(400, "a J1939 signal needs its length, 1 to 64 bits, as type")
            return {"location": layout.suggest("I" if direction == "j1939_rx" else "Q", size, used, start)}
        try:
            n = contract.networks(cfg)[int(network or 0)]["nodes"][int(node)]
        except (KeyError, IndexError, TypeError, ValueError, AttributeError):
            raise ApiError(400, "no node %r in the config" % node)
        if direction == "status":
            return {"location": layout.suggest("I", "X", used, start)}
        if direction in ("state", "boot_error", "errreg"):
            return {"location": layout.suggest("I", "B", used, start)}
        if direction == "emcy":
            return {"location": layout.suggest("I", "W", used, start)}
        if direction == "nmt":
            return {"location": layout.suggest("Q", "B", used, start)}
        sdo_extra = {"sdo_trigger": ("Q", "X"), "sdo_status": ("I", "B"), "sdo_abort": ("I", "D")}
        if direction in sdo_extra:
            return {"location": layout.suggest(*sdo_extra[direction], used, start)}
        if direction in ("sdo_read", "sdo_write") and type_name in CO_TYPES:
            area, size = layout.area_size("input" if direction == "sdo_read" else "output", type_name)
            return {"location": layout.suggest(area, size, used, start)}
        if direction not in ("input", "output") or type_name not in CO_TYPES:
            raise ApiError(400, "direction must be input, output, status, state, boot_error, emcy, errreg, nmt, "
                                "sdo_read, sdo_write, sdo_trigger, sdo_status or sdo_abort, with a CANopen type "
                                "where it needs one")
        area, size = layout.area_size(direction, type_name)
        info = self.eds_info([n.get("eds")]).get(n.get("eds"), {}) if n.get("eds") else {}
        count = info.get("pdo_count", {}).get(direction, 0)
        pdos = n.get("tx_pdos" if direction == "input" else "rx_pdos") or []
        pdo, reason = layout.pack(pdos, type_name, count)
        return {"location": layout.suggest(area, size, used, start), "pdo": pdo, "reason": reason}

    # -- slave EDS (canopen-slave-eds) --------------------------------------
    def _slave_network(self, cfg, network):
        try:
            net = contract.networks(cfg)[int(network or 0)]
        except (IndexError, TypeError, ValueError):
            raise ApiError(400, "no network %r in the config" % network)
        if net["role"] != "slave":
            raise ApiError(400, "network %s is not a slave network" % (net["name"] or int(network or 0) + 1))
        return net

    def slave_descriptions(self, names):
        """{EDS name: the description it was built from} for the EDS files
        that have one: built in this session, or saved next to the EDS as
        `<name>.json`."""
        out = {}
        for name in names:
            if name in self.descriptions:
                out[name] = self.descriptions[name]
                continue
            path = description_path(self.canopen_dir, name)
            try:
                with open(path, encoding="utf-8") as f:
                    desc = json.load(f)
            except (OSError, ValueError):
                continue
            if isinstance(desc, dict):
                out[name] = desc
        return out

    def build_slave_eds(self, cfg, network, desc, name=None, gateway=False, start=None, replace=False):
        """Builds a slave network's EDS from a description with the
        generator `slave-eds` uses, as a pending EDS saved with the config
        (and its description next to it). With `gateway` the config's gateway
        routes, status and SDO bridge go in too. Returns {name, summary,
        objects, bindings, routes}: bindings the generated objects (route
        objects left out) with the location each has now or a suggested
        free one, routes the slave end of each gateway route."""
        if not isinstance(cfg, dict):
            raise ApiError(400, "config must be a JSON object")
        net = self._slave_network(cfg, network)
        if not isinstance(desc, dict):
            raise ApiError(400, "description must be a JSON object")
        name = os.path.basename(name or "").strip() or slave_eds_name(desc.get("device_name"))
        if not name.lower().endswith(".eds") or name in (".eds",):
            raise ApiError(422, "the EDS file name must end in .eds")
        if desc.get("date") is None:
            # The file's dates stay those of its first build, so building it
            # again from the same objects gives the same file.
            saved = self.slave_descriptions([name]).get(name) or {}
            desc = dict(desc, date=saved.get("date") or datetime.date.today().isoformat())
        try:
            text, info = slaveeds.generate(desc, cfg if gateway else None, name)
        except slaveeds.DescriptionError as e:
            raise ApiError(422, str(e))
        data = text.encode("utf-8")
        target = os.path.join(self.canopen_dir, name)
        built = name in self.descriptions or os.path.isfile(description_path(self.canopen_dir, name))
        if not replace and not built and name not in self.pending and os.path.isfile(target):
            with open(target, "rb") as f:
                if f.read() != data:
                    raise ApiError(409, "a different EDS named %s is already in %s" % (name, self.canopen_dir),
                                   conflict=name)
        self.pending[name] = data
        self.descriptions[name] = desc
        with open(os.path.join(self.pending_dir, name), "wb") as f:
            f.write(data)
        start = layout.DEFAULT_START if start in (None, "") else int(start)
        used = layout.taken(cfg, self.uses)
        have = {}
        for o in net["slave"].get("objects") or []:
            if isinstance(o, dict) and isinstance(o.get("iec_location"), str):
                have[(contract._uint(o.get("index")), contract._uint(o.get("subindex", 0)))] = o["iec_location"]
        bindings = []
        own = info["objects"][:len(info["objects"]) - len(info["routes"])]
        for o in own:
            loc = have.get((o["index"], o["subindex"]))
            if loc is None:
                area, size = layout.area_size("input" if o["direction"] == "from_master" else "output", o["type"])
                loc = layout.suggest(area, size, used, start)
                layout.mark(used, parse_location(loc))
            bindings.append({"index": "0x%04X" % o["index"], "subindex": o["subindex"], "name": o["name"],
                             "iec_location": loc})
        objects = [dict(o, index="0x%04X" % o["index"]) for o in info["objects"]]
        return {"name": name, "summary": self.eds_info([name])[name],
                "objects": objects, "bindings": bindings, "revision_number": info["revision_number"],
                "routes": [{"index": "0x%04X" % r["index"], "subindex": r["subindex"]} for r in info["routes"]]}

    def export_eds(self, cfg, network):
        """A slave network's EDS as the bridge runs it, for the other
        master's tool: the exact bytes, named after its device name."""
        net = self._slave_network(cfg, network)
        value = net["slave"].get("eds")
        if not isinstance(value, str) or not value:
            raise ApiError(422, "the slave network has no EDS yet")
        path = self.eds_path(value)
        if not os.path.isfile(path):
            raise ApiError(422, "EDS file %s not found" % path)
        with open(path, "rb") as f:
            data = f.read()
        device = eds_mod.device_info(path) or {}
        name = slave_eds_name(device.get("product_name")) if device.get("product_name") else os.path.basename(value)
        return {"name": name, "content_type": "application/octet-stream",
                "data": base64.b64encode(data).decode("ascii")}

    # -- Modbus bridge (canopen-configurator "Modbus bridge target") ---------
    @staticmethod
    def _bridge_config(cfg):
        if not isinstance(cfg, dict):
            raise ApiError(400, "config must be a JSON object")
        if not modbusmap.is_bridge_config(cfg):
            raise ApiError(400, "not a bridge config: it has no top-level \"bridge\" object")
        return cfg

    def bridge_map(self, cfg):
        """The register map of the draft for the bridge page: {rows,
        channels, input_bytes, output_bytes}, or {rows: [], problem} when
        the locations break the byte rules (Check says where)."""
        self._bridge_config(cfg)
        try:
            rows = modbusmap.register_map(cfg)
        except modbusmap.MapError as e:
            return {"rows": [], "channels": [], "problem": str(e)}
        except (AttributeError, KeyError, TypeError, ValueError):
            return {"rows": [], "channels": [], "problem": "the config cannot be read for the register map (see Problems)"}
        inputs, outputs = modbusmap.image_sizes(rows)
        channels = modbusmap.suggest_channels(rows)
        out = {"rows": rows, "input_bytes": inputs, "output_bytes": outputs,
               "channels": [{"function": f, "start": st, "count": c, "direction": d} for f, st, c, d in channels],
               "requests": len(channels), "request_budget": openplcmodbus.REQUEST_BUDGET,
               "map_hash": connections.map_hash_text(cfg)}
        if modbusmap.is_openplc(cfg):
            try:
                out["requests"] = openplcmodbus.request_count(openplcmodbus.layout(cfg, [], 0)[0])
            except (openplcmodbus.OpenplcError, modbusmap.MapError):
                pass
        mb = cfg["bridge"].get("mailboxes")
        if isinstance(mb, dict):
            # What the Function blocks section costs (modbus-bridge-mailboxes).
            ins, outs = mailboxlayout.area_bytes(mb, len(cfg.get("networks") or []))
            out["mailboxes"] = {"input_registers": ins // 2, "output_registers": (outs + 1) // 2}
            s = mailboxlayout.settings(mb, len(cfg.get("networks") or []))
            if s["receive"]:
                # One batch per two polls: the master reads, then acknowledges.
                can = mailboxlayout.records_per_batch("can", s["receive_blocks"])
                out["mailboxes"]["can_per_batch"] = can
                if modbusmap.is_openplc(cfg):
                    poll = bridgecheck.openplc_settings(cfg)["poll_ms"]
                    out["mailboxes"]["can_per_second"] = round(can * 1000 / poll / 2)
        out["mailbox_cost"] = self.mailbox_cost(cfg)
        if modbusmap.is_openplc(cfg) and self.mode == "project" and self.folder:
            # Who needs them: the editor project's mailbox blocks.
            found = mailboxuse.scan_project(self.folder)
            out["program_blocks"] = [{"block": b, "pous": sorted(found[b]), "parts": list(mailboxuse.BLOCK_PARTS[b])}
                                     for b in sorted(found)]
        # and the connections whose canworks blocks choice asks for them
        out["connection_blocks"] = [{"index": i, "name": c.get("name") or connections.TITLES[c["kind"]],
                                     "blocks": c["blocks"], "text": connections.blocks_text(c["blocks"])}
                                    for i, c in enumerate(cfg["bridge"].get("connections") or [])
                                    if isinstance(c, dict) and c.get("kind") in ("trust", "plc", "nodered")
                                    and c.get("blocks") in ("sdo_send", "receive", "all")]
        return out

    def mailbox_cost(self, cfg):
        """The mailboxes' cost as a difference (canopen-configurator
        "Function blocks section"): their registers and, for OpenPLC, the
        Modbus requests per poll with and without them. Without mailboxes:
        what the default parts would add, placed as Suggest places them."""
        mb = cfg["bridge"].get("mailboxes")
        on = isinstance(mb, dict)
        ins, outs = mailboxlayout.area_bytes(mb if on else {}, len(cfg.get("networks") or []))
        cost = {"on": on, "input_registers": ins // 2, "output_registers": (outs + 1) // 2}
        if not modbusmap.is_openplc(cfg):
            return cost
        bare = copy.deepcopy(cfg)
        bare["bridge"].pop("mailboxes", None)
        if on:
            with_mb = cfg
        else:
            with_mb = copy.deepcopy(cfg)
            with_mb["bridge"]["mailboxes"] = {}
            try:
                with_mb["bridge"]["mailboxes"]["input_location"] = self.bridge_suggest(with_mb, "mailbox_input")["location"]
                with_mb["bridge"]["mailboxes"]["output_location"] = self.bridge_suggest(with_mb, "mailbox_output")["location"]
            except (ApiError, KeyError, TypeError):
                return cost
        try:
            cost["requests_with"] = openplcmodbus.request_count(openplcmodbus.layout(with_mb, [], 0)[0])
            cost["requests_without"] = openplcmodbus.request_count(openplcmodbus.layout(bare, [], 0)[0])
        except (openplcmodbus.OpenplcError, modbusmap.MapError, KeyError, TypeError, ValueError, AttributeError):
            pass
        return cost

    def bridge_pack(self, cfg):
        """The draft with every location packed for Modbus (modbusmap.pack)."""
        self._bridge_config(cfg)
        try:
            return {"config": modbusmap.pack(cfg)}
        except modbusmap.MapError as e:
            raise ApiError(400, str(e))

    # The bridge blocks Suggest places: (area, bytes).
    BRIDGE_BLOCKS = {"status_location": ("I", bridgecheck.STATUS_BYTES),
                     "control_location": ("Q", bridgecheck.CONTROL_BYTES),
                     "live_list": ("I", bridgecheck.LIVE_LIST_BYTES),
                     "sdo_request": ("Q", bridgecheck.SDO_BYTES),
                     "sdo_response": ("I", bridgecheck.SDO_BYTES),
                     "mailbox_input": ("I", None), "mailbox_output": ("Q", None)}

    def bridge_suggest(self, cfg, block, index=None):
        """A free place for one bridge block: the first even byte after the
        packed data (data and status locations) of its area where the whole
        block overlaps nothing. `block` is a key of BRIDGE_BLOCKS, `index`
        the live list's. The block's own location is left out, so Suggest
        can also move it."""
        self._bridge_config(cfg)
        if block not in self.BRIDGE_BLOCKS:
            raise ApiError(400, "block must be one of: " + ", ".join(self.BRIDGE_BLOCKS))
        cfg = copy.deepcopy(cfg)
        b = cfg["bridge"]
        if block == "live_list":
            lists = b.get("live_lists")
            try:
                entry = lists[int(index)]
            except (IndexError, TypeError, ValueError):
                raise ApiError(400, "no live list %r" % index)
            if not isinstance(entry, dict):
                raise ApiError(400, "no live list %r" % index)
            entry.pop("location", None)
        elif block.startswith("sdo_"):
            if isinstance(b.get("sdo_bridge_location"), dict):
                b["sdo_bridge_location"].pop(block[4:], None)
        elif block.startswith("mailbox_"):
            if not isinstance(b.get("mailboxes"), dict):
                raise ApiError(400, "the bridge has no mailboxes")
            b["mailboxes"].pop(block[8:] + "_location", None)
        else:
            b.pop(block, None)
        try:
            items = modbusmap.collect(cfg)
        except modbusmap.MapError as e:
            raise ApiError(400, str(e))
        area, nbytes = self.BRIDGE_BLOCKS[block]
        if nbytes is None:
            # A mailbox area: its size follows the counts.
            sizes = mailboxlayout.area_bytes(b["mailboxes"], len(cfg.get("networks") or []))
            nbytes = sizes[0 if area == "I" else 1]
        mine = [it for it in items if it.loc.area == area]
        end = max((it.loc.index + it.nbytes for it in mine if it.kind != "bridge"), default=0)
        pos = end + end % 2
        ranges = sorted((it.loc.index, it.loc.index + it.nbytes) for it in mine)
        moved = True
        while moved:
            moved = False
            for lo, hi in ranges:
                if lo < pos + nbytes and pos < hi:
                    pos = hi + hi % 2
                    moved = True
        if pos + nbytes > bridgecheck.IMAGE_BYTES:
            raise ApiError(400, "no free %d-byte range left in the %s image" % (nbytes, "input" if area == "I" else "output"))
        return {"location": "%%%sB%d" % (area, pos)}

    # -- connections (modbus-connections) -----------------------------------
    def add_connection(self, cfg, conn):
        """Add connection: the draft with `conn` (a new one of its kind, its
        fields over the defaults) added, the bridge set for an OpenPLC
        connection and repacked, the writers following the connections."""
        self._bridge_config(cfg)
        if not isinstance(conn, dict) or conn.get("kind") not in connections.KINDS:
            raise ApiError(400, "connection.kind must be one of: " + ", ".join(connections.KINDS))
        new = connections.new(conn["kind"], cfg, conn.get("name"), conn.get("address"))
        new.update({k: v for k, v in conn.items() if k not in ("kind", "name") and v is not None})
        try:
            out = connections.add(cfg, new)
        except (ValueError, modbusmap.MapError) as e:
            raise ApiError(400, str(e))
        return {"config": out, "index": len(out["bridge"]["connections"]) - 1,
                "old_main": (self.old_main(out) or {}).get("count", 0) if new["kind"] == "openplc" else 0}

    def connection_download(self, cfg, index):
        """A connection's Download for the draft: {name, content_type,
        data (base64), map_hash, notes}, the same file as the command line
        writes; on a problem the /api/check shape, and no file."""
        self._bridge_config(cfg)
        items = cfg["bridge"].get("connections")
        try:
            conn = items[int(index)]
        except (IndexError, TypeError, ValueError):
            raise ApiError(400, "no connection %r" % index)
        if not isinstance(conn, dict) or conn.get("kind") not in connections.KINDS or conn["kind"] == "openplc":
            raise ApiError(400, "connection %r has no download" % index)
        folder = os.path.basename(self.folder.rstrip(os.sep)) or "canworks"
        try:
            name, mime, data, notes = connections.download(
                cfg, conn, editorproject.declarations(cfg, self.config_path), folder)
        except connections.DownloadError as e:
            return self._map_problems(cfg, e.problems)
        out = {"items": [], "errors": 0, "name": name, "content_type": mime, "notes": notes,
               "map_hash": connections.map_hash_text(cfg), "data": connections.encode(data)}
        if conn["kind"] == "nodered":
            out["package"] = nodered.package_name()
        return out

    def nodered_package(self):
        """Package on a Node-RED connection: the .tgz `canworks-deploy
        --export-nodered-package` writes."""
        return {"name": nodered.package_name(), "content_type": "application/gzip",
                "data": connections.encode(nodered.package_tgz())}

    def _map_problems(self, cfg, problems):
        """A stopped register map or Node-RED export in the /api/check shape:
        the config check's errors, which say where (the same byte rules, with
        their paths), or else the export's own problems, one item each."""
        items = []
        try:
            items = [it for it in contract.check_config(cfg, self.config_path, eds_paths=self.eds_paths(cfg)).items
                     if it.get("level") == "error"]
        except (AttributeError, KeyError, TypeError, ValueError, OSError):
            pass
        if not items:
            items = [{"level": "error", "message": m,
                      "paths": ["bridge.watchdog_ms"] if '"watchdog_ms"' in m else []} for m in problems]
        return {"items": items, "errors": len(items)}

    # -- the OpenPLC connection (canopen-configurator "OpenPLC remote device on save") --
    def openplc_info(self, cfg):
        """The facts of a config's OpenPLC connection: the
        remote device's name, poll and port, the map hash, the requests per
        poll and its warning, the %IW/%QW base; None when the map cannot be
        made (the check says why)."""
        if not bridgecheck.is_openplc(cfg):
            return None
        try:
            s = openplcmodbus.settings(cfg)
            groups, _ = openplcmodbus.layout(cfg, [], 0)
            base = s["iec_base"]
            if base is None and self.mode == "project":
                base = openplcmodbus.free_iec_base(cfg, [], self.uses)
        except (openplcmodbus.OpenplcError, modbusmap.MapError, KeyError, TypeError, ValueError, AttributeError):
            return None
        return {"remote_device": s["remote_device"], "poll_ms": s["poll_ms"], "port": s["port"],
                "watchdog_ms": s["watchdog_ms"], "map_hash": "0x%08x" % modbusmap.map_hash(cfg),
                "requests": openplcmodbus.request_count(groups), "warning": openplcmodbus.budget_warning(groups),
                "iec_base": base, "files": openplcmodbus.own_files(cfg), "old_main": self.old_main(cfg),
                "outdated": self.outdated(cfg)}

    def outdated(self, cfg):
        """The editor files Save would write again for `cfg` when it is the
        saved config (openplcmodbus.outdated_files), else []: a draft
        with changes is saved anyway."""
        if self.mode != "project" or not self.folder or cfg != self.saved_cfg:
            return []
        try:
            decls = editorproject.declarations(cfg, self.config_path)
            return openplcmodbus.outdated_files(self.folder, cfg, decls, self.uses)
        except (openplcmodbus.OpenplcError, modbusmap.MapError, KeyError, TypeError, ValueError, AttributeError,
                OSError):
            return []  # a config the check refuses: Save writes no editor files for it

    def main_members(self, cfg):
        """The `canworks` list's member names for `cfg`."""
        decls = editorproject.declarations(cfg, self.config_path)
        return [d["name"] for d, _ in openplcmodbus._typed(decls)]

    def old_main(self, cfg):
        """The project's main.st still declaring canworks values at the
        removed plugin's locations (mainmove.project_scan), or None."""
        if self.mode != "project" or not self.folder:
            return None
        try:
            with open(os.path.join(self.folder, mainmove.MAIN), encoding="utf-8") as f:
                if " AT " not in f.read().upper():
                    return None  # nothing located: no need to read the EDS files
            return mainmove.project_scan(self.folder, self.main_members(cfg))
        except (OSError, KeyError, TypeError, ValueError, AttributeError):
            return None

    def move_main(self, cfg):
        """Use canworks.* in main: rewrites the project's main.st
        (mainmove.move_project) for the saved OpenPLC config."""
        if not bridgecheck.is_openplc(cfg) or self.mode != "project":
            raise ApiError(422, "main is moved only in an OpenPLC project")
        try:
            return mainmove.move_project(self.folder, self.main_members(cfg))
        except mainmove.MainError as e:
            raise ApiError(422, str(e))

    def openplc_items(self, cfg):
        info = self.openplc_info(cfg)
        if not info:
            return []
        items = []
        if info["warning"]:
            i = next(k for k, c in enumerate(cfg["bridge"]["connections"])
                     if isinstance(c, dict) and c.get("kind") == "openplc")
            items.append({"level": "warning", "message": info["warning"], "paths": ["bridge.connections[%d].poll_ms" % i]})
        old = info["old_main"]
        if old:
            items.append({"level": "warning", "paths": ["project"], "message": (
                "main declares %d canworks value%s at the removed plugin's locations (%s%s), which read nothing "
                "now: Use canworks.* in main on the Project page" % (
                    old["count"], "" if old["count"] == 1 else "s", ", ".join(old["locations"]),
                    ", ..." if old["count"] > len(old["locations"]) else ""))})
        if info["outdated"]:
            items.append({"level": "warning", "paths": ["project"], "message": (
                "The editor files were made by an older canworks (%s): Save writes them again"
                % ", ".join(info["outdated"]))})
        return items

    def mailbox_items(self, cfg):
        """The mailbox blocks the editor project declares against the
        config's mailboxes (canopen-configurator "Mailbox blocks the OpenPLC
        program declares", "Mailboxes nobody needs"): an error per block
        whose part is off, with the mailboxes that add what the program
        uses, or a warning when nothing uses the config's mailboxes."""
        found = mailboxuse.scan_project(self.folder) if self.folder else {}
        mb = (cfg.get("bridge") or {}).get("mailboxes")
        need = mailboxuse.parts_needed(found)
        items = []
        add = mailboxuse.mailboxes_for(need, mb)
        for block in sorted(found):
            gone = mailboxuse.missing(mb, mailboxuse.parts_needed({block: found[block]}))
            if gone:
                items.append({"level": "error", "paths": ["bridge.mailboxes"], "mailbox_fix": add,
                              "message": "%s: Turn on what the program uses on the Modbus bridge page"
                              % mailboxuse.describe(block, found[block], gone)})
        if isinstance(mb, dict) and not need:
            saved = self.mailbox_requests(cfg)
            items.append({"level": "warning", "paths": ["bridge.mailboxes"], "mailbox_fix": "off",
                          "message": "The program declares no mailbox block, but the mailboxes take %s: "
                          "Turn off the mailboxes" % (saved or "registers on every poll")})
        return items

    @staticmethod
    def mailbox_requests(cfg):
        """'2 of the 7 Modbus requests per poll' for an OpenPLC config's
        mailboxes, or None when the map cannot be laid out."""
        try:
            with_mb = openplcmodbus.request_count(openplcmodbus.layout(cfg, [], 0)[0])
            bare = copy.deepcopy(cfg)
            bare["bridge"].pop("mailboxes", None)
            without = openplcmodbus.request_count(openplcmodbus.layout(bare, [], 0)[0])
        except (openplcmodbus.OpenplcError, modbusmap.MapError, KeyError, TypeError, ValueError, AttributeError):
            return None
        return "%d of the %d Modbus requests per poll" % (with_mb - without, with_mb)

    def sync_openplc(self, cfg, force=False):
        """Writes the editor's remote device, canworks_in, canworks_out and
        the `canworks` list into the open project for a saved OpenPLC
        through Modbus config; 409 with `editor_changed` when one of those
        files was changed outside canworks and `force` is not set."""
        decls = editorproject.declarations(cfg, self.config_path)
        try:
            out = openplcmodbus.sync_project(self.folder, cfg, decls, self.uses, force=force)
        except openplcmodbus.ChangedFiles as e:
            raise ApiError(409, "changed outside canworks: %s" % ", ".join(e.files), editor_changed=e.files)
        except openplcmodbus.OpenplcError as e:
            raise ApiError(422, str(e))
        # The project enables the library; the editor needs it installed to build.
        out["library_ok"], out["library"] = plclibrary.ensure_installed()
        return out

    def openplc_check(self, cfg):
        """The 409 of sync_openplc before anything is written."""
        try:
            decls = editorproject.declarations(cfg, self.config_path)
            _, texts = openplcmodbus.own_texts(cfg, decls, self.uses)
        except (openplcmodbus.OpenplcError, modbusmap.MapError, KeyError, TypeError, ValueError, AttributeError,
                OSError):
            return  # a config the check refuses: nothing is written for it
        changed = openplcmodbus.changed_files(self.folder, cfg, texts)
        if changed:
            raise ApiError(409, "changed outside canworks: %s" % ", ".join(changed), editor_changed=changed)

    # -- save ---------------------------------------------------------------
    def save(self, cfg, overwrite=False, notes=None, editor_overwrite=False):
        """Writes the draft; settings the target does not use are left out
        (spec "Settings the target does not use are left out on save") and
        counted in `left_out`."""
        left_out = 0
        if isinstance(cfg, dict):
            cfg = copy.deepcopy(cfg)
            gone = [p for p, k, _ in targets.unused(cfg) if targets.removable(k)]
            targets.remove(cfg, gone)
            left_out = len(gone)
        if targets.target(cfg) == targets.PLUGIN:
            raise ApiError(409, contract.NOT_BRIDGE_MESSAGE[0].upper() + contract.NOT_BRIDGE_MESSAGE[1:] + " first",
                           plugin=True)
        # A draft with errors is saved too: the steps that hand the config
        # over refuse it (spec "Hand-off steps need a config without errors").
        checked = self.check(cfg, notes=notes)
        if not overwrite and self.changed_on_disk():
            raise ApiError(409, "%s changed on disk after it was loaded" % self.config_path, changed_on_disk=True)
        openplc = self.mode == "project" and bridgecheck.is_openplc(cfg)
        if openplc and not checked["errors"] and not editor_overwrite:
            self.openplc_check(cfg)
        try:
            out = self._save(cfg, checked, notes)
        except OSError as e:
            raise folder_error(e, "write to", self.canopen_dir)
        out["left_out"] = left_out
        out["errors"] = checked["errors"]
        if openplc and not checked["errors"]:
            # The editor's files follow the saved config (spec "OpenPLC remote device on save").
            try:
                out["editor"] = self.sync_openplc(cfg, force=True)
            except OSError as e:
                raise folder_error(e, "write to", self.folder)
            out["written"] += out["editor"]["written"]
            self.rescan()
        elif openplc:
            out["editor"] = {"skipped": True}
        return out

    def _save(self, cfg, checked, notes=None):
        os.makedirs(self.canopen_dir, exist_ok=True)
        written = []
        referenced = {n["eds"] for n in contract.eds_users(cfg)}
        for name, data in sorted(self.pending.items()):
            if name not in referenced:
                continue
            target = os.path.join(self.canopen_dir, name)
            tmp = target + ".tmp"
            with open(tmp, "wb") as f:
                f.write(data)
            replace_file(tmp, target)
            written.append(target)
            if name in self.descriptions:
                target = description_path(self.canopen_dir, name)
                with open(target + ".tmp", "w", encoding="utf-8") as f:
                    json.dump(self.descriptions[name], f, indent=2, ensure_ascii=False)
                    f.write("\n")
                replace_file(target + ".tmp", target)
                written.append(target)
        dbc_names = self.dbc_names(cfg)
        for name, data in sorted(self.pending_dbc.items()):
            if name in dbc_names:
                target = os.path.join(self.canopen_dir, name)
                with open(target + ".tmp", "wb") as f:
                    f.write(data)
                replace_file(target + ".tmp", target)
                written.append(target)
        out = canonical(cfg)
        try:
            with open(self.config_path, encoding="utf-8") as f:
                out = keep_order(out, json.load(f))
        except (OSError, ValueError):
            pass  # a new file, or one that cannot be read: the fixed order
        tmp = self.config_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(out, f, indent=2, ensure_ascii=False)
            f.write("\n")
        replace_file(tmp, self.config_path)
        written.append(self.config_path)
        written += self.save_notes(cfg, notes)
        for name in [n for n in self.pending if n in referenced]:
            del self.pending[name]
            self.descriptions.pop(name, None)
        for name in [n for n in self.pending_dbc if n in dbc_names]:
            del self.pending_dbc[name]
        self.loaded = (os.path.getmtime(self.config_path), sha256(self.config_path))
        return {"written": written, "check": checked}

    def need_no_errors(self):
        """Refuses a hand-off step while the saved config has errors (spec
        "Hand-off steps need a config without errors"): 422 with
        `config_errors`, the count."""
        cfg, _, error = self.read_config()
        if error:
            raise ApiError(422, error, config_errors=1)
        try:
            result = contract.check_config(cfg, self.config_path, eds_paths=self.eds_paths(cfg))
            errors = len(result.errors)
        except (AttributeError, KeyError, TypeError, ValueError, OSError) as e:
            raise ApiError(422, "the saved config cannot be checked: %s" % e, config_errors=1)
        if errors:
            raise ApiError(422, "the saved config has %d error%s; fix %s in Problems first"
                           % (errors, "" if errors == 1 else "s", "it" if errors == 1 else "them"),
                           config_errors=errors)

    # -- the simulation file -------------------------------------------------
    def sim_changed_on_disk(self):
        exists = os.path.isfile(self.sim_path)
        if self.sim_loaded is None:
            return exists
        return not exists or sha256(self.sim_path) != self.sim_loaded

    def sim_problems(self, doc, network=None):
        """simulation.config_problems() of a schema-valid simulation file
        against the saved config."""
        if not os.path.isfile(self.config_path):
            return []  # nothing to check against yet
        cfg = self.read_config()[0]
        try:
            out = simulation.config_problems(doc, self.sim_path, cfg, self.config_path,
                                             self.eds_paths(cfg) if isinstance(cfg, dict) else {}, network)
        except (KeyError, TypeError, ValueError, AttributeError):
            return []  # a config the contract check refuses: its problems show there
        # An extra device's EDS imported but not saved yet is written with the file.
        nets = doc.get("networks") if simulation.version(doc) >= 2 else None
        parts = [("networks.%s." % k, b) for k, b in nets.items()] if isinstance(nets, dict) else [("", doc)]
        pending = {"%sextra_devices[%d].eds" % (prefix, i) for prefix, body in parts if isinstance(body, dict)
                   for i, d in enumerate(body.get("extra_devices") or [])
                   if isinstance(d, dict) and d.get("eds") in self.pending}
        return [p for p in out if p["path"] not in pending]

    def save_simulation(self, doc, overwrite=False):
        """Writes canworks/simulation.json after the schema check, with the EDS
        files its extra devices name that were imported but not saved yet.
        Like canworks.json, only into the project's config folder."""
        problems = simulation.check(doc)
        if not problems:
            problems = [p for p in self.sim_problems(doc) if p["level"] == "error"]
        if problems:
            raise ApiError(422, "the simulation file has %d error%s; nothing was saved"
                           % (len(problems), "" if len(problems) == 1 else "s"), problems=problems)
        if not overwrite and self.sim_changed_on_disk():
            raise ApiError(409, "%s changed on disk after it was loaded" % self.sim_path, changed_on_disk=True)
        try:
            return self._save_simulation(doc)
        except OSError as e:
            raise folder_error(e, "write to", self.canopen_dir)

    def _save_simulation(self, doc):
        os.makedirs(self.canopen_dir, exist_ok=True)
        written = []
        wanted = set(simulation.extra_eds(doc))
        for name in sorted(n for n in self.pending if n in wanted):
            target = os.path.join(self.canopen_dir, name)
            with open(target + ".tmp", "wb") as f:
                f.write(self.pending[name])
            replace_file(target + ".tmp", target)
            written.append(target)
            del self.pending[name]
        simulation.write(self.sim_path, doc)
        written.append(self.sim_path)
        self.sim_loaded = sha256(self.sim_path)
        return {"written": written}

    # -- move a standalone config into a project ---------------------------
    def move(self, target, replace=False):
        if self.mode != "standalone":
            raise ApiError(400, "only a standalone config can be moved into a project")
        if self.pending or self.pending_dbc or self.changed_on_disk() or not os.path.isfile(self.config_path):
            raise ApiError(409, "save the config before moving it into a project", unsaved=True)
        target = os.path.abspath(os.path.expanduser(target or ""))
        if not os.path.isfile(os.path.join(target, "project.json")):
            raise ApiError(422, "%s is not an OpenPLC Editor project (it has no project.json)" % target)
        if os.path.lexists(os.path.join(target, "canworks")) and not replace:
            raise ApiError(409, "%s already has a canworks/ folder" % target, exists=True)
        with open(self.config_path, encoding="utf-8") as f:
            cfg = contract.load(f)
        result = contract.check_config(cfg, self.config_path)
        if not result.ok and not self._blank(result):
            raise ApiError(422, "\n".join(result.errors))
        cfg = self._with_openplc(cfg)
        try:
            written, converted = project_mod.write(cfg, self.config_path, target, force=replace,
                                                   sim_path=self._sim_to_move())
        except project_mod.ProjectError as e:
            raise ApiError(422, str(e))
        written += self._move_descriptions(cfg, os.path.join(target, project_mod.DIR))
        self.open(target, "project")
        return {"written": written, "converted": converted}


    @staticmethod
    def _blank(result):
        """Whether a check failed only because the networks have no nodes
        yet: such a new config may still go into an editor project."""
        return bool(result.errors) and all("lists no slave nodes" in e for e in result.errors)

    @staticmethod
    def _with_openplc(cfg):
        """A bridge config going into an editor project gets an OpenPLC
        connection when it has none (modbus-connections)."""
        if not modbusmap.is_bridge_config(cfg) or bridgecheck.is_openplc(cfg):
            return cfg
        try:
            return connections.add(cfg, connections.new("openplc", cfg))
        except (ValueError, modbusmap.MapError) as e:
            raise ApiError(422, str(e))

    def _sim_to_move(self):
        """The simulation file that goes along into a project, or None."""
        if self.sim_changed_on_disk():
            raise ApiError(409, "save the simulation before moving the config into a project", unsaved=True)
        return self.sim_path if os.path.isfile(self.sim_path) else None

    def _move_descriptions(self, cfg, target):
        """Copies the description of each slave network's EDS (what Build
        the EDS shows) into a project's canworks/ folder: the paths written."""
        written = []
        for net in contract.networks(cfg):
            eds = (net.get("slave") or {}).get("eds") if net["role"] == "slave" else None
            if not isinstance(eds, str) or not eds:
                continue
            src = description_path(os.path.dirname(self.eds_path(eds)), os.path.basename(eds))
            dst = os.path.join(target, os.path.basename(src))
            if os.path.isfile(src) and not os.path.exists(dst):
                shutil.copyfile(src, dst)
                written.append(dst)
        return written

    # -- a new editor project around a standalone config --------------------
    def new_project(self, parent, name, interval=None, blocks=False):
        if self.mode != "standalone":
            raise ApiError(400, "only a standalone config can become a new editor project")
        if self.pending or self.pending_dbc or self.changed_on_disk() or not os.path.isfile(self.config_path):
            raise ApiError(409, "save the config before creating a project from it", unsaved=True)
        name = (name or "").strip()
        if not name or name in (".", "..") or "/" in name or os.sep in name:
            raise ApiError(422, "give the project a folder name (no slashes)")
        parent = os.path.abspath(os.path.expanduser(parent or ""))
        if not os.path.isdir(parent):
            raise ApiError(422, "%s is not a folder" % parent)
        target = os.path.join(parent, name)
        in_the_way = os.path.lexists(target) and editorproject.existing_folder_problem(target)
        if in_the_way:
            raise ApiError(409, in_the_way, exists=True)
        with open(self.config_path, encoding="utf-8") as f:
            cfg = contract.load(f)
        result = contract.check_config(cfg, self.config_path)
        blank = not result.ok and self._blank(result)
        if not result.ok and not blank:
            raise ApiError(422, "\n".join(result.errors))
        address = None
        host = online.Settings(config_dir()).project(self.folder).get("host")
        if host:
            try:
                address = diag.parse_runtime(host)[0]
            except ValueError:
                address = None
        cfg = self._with_openplc(cfg)
        sim = self._sim_to_move()
        try:
            # A config without nodes yet: the project first, then the config
            # and the editor files, as New config… did.
            path, synced = editorproject.create(None if blank else cfg, self.config_path, target,
                                               interval=interval or editorproject.DEFAULT_INTERVAL,
                                               runtime_address=address, blocks=blocks,
                                               sim_path=None if blank else sim)
        except editorproject.NewProjectError as e:
            raise ApiError(422, str(e))
        if blank:
            self.open(path, "project")
            try:
                self._save(cfg, None)
                synced = self.sync_openplc(cfg, force=True)
            except OSError as e:
                raise folder_error(e, "write to", self.folder)
            self.rescan()
        self._move_descriptions(cfg, os.path.join(path, project_mod.DIR))
        self.open(path, "project")
        out = {"project": path, "editor": synced}
        if blocks or editorproject.uses_library(cfg):
            out["library_ok"], out["library"] = plclibrary.ensure_installed()
        return out


def j1939_address(value, global_ok):
    """A destination address of the DM operations: 0..253, or 255 (every
    ECU) when `global_ok`."""
    if isinstance(value, int) and not isinstance(value, bool) and (0 <= value <= 253 or global_ok and value == 255):
        return value
    raise ApiError(400, "address must be 0-253" + (" or 255 (every ECU)" if global_ok else ""))


def dm_texts(res):
    """A DM answer with each code's FMI text."""
    for c in res.get("dtcs") or []:
        if isinstance(c, dict) and isinstance(c.get("fmi"), int):
            c["fmi_text"] = j1939_dm.fmi_text(c["fmi"])
    return res


# J1939 locations /api/place suggests: direction -> (area, size letter).
J1939_PLACES = {"j1939_state": ("I", "B"), "j1939_address": ("I", "B"), "j1939_status": ("I", "X"),
                "j1939_valid": ("I", "X"),
                # Diagnostics (j1939-diagnostics "Diagnostics config"): a watched ECU's status bit and
                # lamp, flash and count bytes, an own code's bit, the lamps output and the clears counter.
                "j1939_dm_status": ("I", "X"), "j1939_dm_lamps": ("I", "B"), "j1939_dm_flash": ("I", "B"),
                "j1939_dm_count": ("I", "B"), "j1939_dtc_active": ("Q", "X"), "j1939_dm_lamps_out": ("Q", "B"),
                "j1939_dm_clears": ("I", "B")}

# The page's words for trouble codes (j1939/dm.py): FMI texts, the lamps as
# [key, label, shift] in byte order, and the PGNs diagnostics handles.
J1939_DM_TEXTS = {"fmi": list(j1939_dm.FMI_TEXT), "lamps": [list(x) for x in j1939_dm.LAMPS],
                  "pgns": {str(pgn): name for pgn, name in j1939_dm.DM_PGNS.items()},
                  "titles": dict(j1939_dm.DM_TITLES)}


def location_slots(cfg):
    """[(dict, key, Location)] of every %I and %Q location of a config, in
    file order: each `iec_location` and `*_location` value (the rule of
    modbusmap.collect), the bridge object and the diagnostics left out."""
    out = []

    def walk(value):
        if isinstance(value, dict):
            for key, sub in value.items():
                if isinstance(sub, str) and (key == "iec_location" or key.endswith("_location")):
                    loc = parse_location(sub)
                    if loc is not None and loc.area in "IQ":
                        out.append((value, key, loc))
                elif isinstance(sub, (dict, list)):
                    walk(sub)
        elif isinstance(value, list):
            for sub in value:
                walk(sub)

    walk({k: v for k, v in cfg.items() if k not in ("bridge", "diagnostics")})
    return out


def _bitrate_arg(v):
    """A bit rate the page chose (bit/s), or None."""
    if v in (None, "", 0):
        return None
    try:
        v = int(v)
    except (TypeError, ValueError):
        raise ApiError(400, "The bit rate must be a number of bit/s.")
    if not 10000 <= v <= 1000000:
        raise ApiError(400, "The bit rate must be 10000 to 1000000 bit/s.")
    return v


def description_name(eds_name):
    """The file a configurator-built slave EDS keeps its description in."""
    return eds_name + ".json"


def description_path(folder, eds_name):
    """The description of a slave EDS in folder: <name>.eds.json, or
    <stem>_eds.json as `canworks-deploy slave-eds` examples name it, when
    that one is there."""
    other = os.path.join(folder, os.path.splitext(eds_name)[0] + "_eds.json")
    path = os.path.join(folder, description_name(eds_name))
    return other if not os.path.isfile(path) and os.path.isfile(other) else path


def slave_eds_name(device_name):
    """An EDS file name from a device name: "OpenPLC slave" -> openplc-slave.eds."""
    stem = re.sub(r"[^a-z0-9]+", "-", str(device_name or "").lower()).strip("-")
    return (stem or "openplc-slave") + ".eds"


def _eds_here(names):
    return sum(1 for n in names if n.lower().endswith(".eds"))


def windows_drives():
    """The drive roots of a Windows PC ("C:\\", "D:\\" …) that exist."""
    if hasattr(os, "listdrives"):  # Python 3.12
        try:
            return sorted(os.listdrives())
        except OSError:
            pass
    return ["%s:\\" % c for c in string.ascii_uppercase if os.path.isdir("%s:\\" % c)]


def plain_examples(dec):
    """A plain CAN network's Frame lab examples: one frame of each
    configured message, data all zero (no NMT or SYNC there)."""
    from ..bustrace.model import Frame
    from ..raw import contract as raw_contract
    out = []
    for kind, m in (dec.raw.entries if dec.raw is not None else []):
        if kind not in ("rx", "tx") or not isinstance(m.get("id"), int) or isinstance(m.get("id"), bool):
            continue
        rtr = m.get("rtr") is True
        try:
            n = 0 if rtr else raw_contract.tx_dlc(m) if kind == "tx" else m.get("dlc", 8)
        except (TypeError, ValueError, KeyError):  # an unfinished draft
            n = 8
        n = n if isinstance(n, int) and 0 <= n <= 8 else 8
        name = m.get("name") or "0x%X" % m["id"]
        frame = Frame(0, m["id"], bytes(n), ext=m.get("extended") is True, rtr=rtr, dlc=n if rtr else None)
        out.append({"group": "Received messages" if kind == "rx" else "Sent messages", "label": name,
                    "frames": [{"label": name, "frame": frame}]})
    return out


def home_folder():
    """Where the folder browsers start: the home folder, else (a HOME that
    does not exist) the current folder, else the file system's root."""
    for where in (lambda: os.path.expanduser("~"), os.getcwd):
        try:
            path = where()
        except OSError:  # the current folder was removed
            continue
        if os.path.isdir(path):
            return os.path.abspath(path)
    return os.path.abspath(os.sep)


def runtime_host_only(text):
    """HOST of an Online access runtime host "HOST", "HOST:PORT" or
    "[v6]:PORT"; None for none and for "local" (the local runtime)."""
    t = (text or "").strip() if isinstance(text, str) else ""
    m = re.match(r"^\[(.*)\](?::\d+)?$", t) or re.match(r"^([^:]*):\d+$", t)
    t = m.group(1) if m else t
    return t if t and t != "local" else None


_codesys_devices = None  # the installed PLC devices, read once per server start


def codesys_devices(project=None, refresh=False):
    """The PLC devices installed in CODESYS on this PC (codesys-new-project-
    picker), and whether the project file `project` exists (None: no path)."""
    global _codesys_devices
    from ..codesys import run as codesys_run
    if _codesys_devices is None or refresh:
        try:
            _codesys_devices = codesys_run.list_plc_devices()
        except OSError:
            _codesys_devices = []
    exists = None
    if project:
        exists = os.path.isfile(codesys_run.project_path(os.path.expanduser(project)))
    return {"devices": _codesys_devices, "exists": exists}


def list_folders(path, drives=False, files=None):
    """A folder's subfolders for the folder browsers, each with its number of
    EDS files (`eds`). On Windows, `drives` lists the drive roots, and a
    drive root says so (`drive`), so Up can go there. `files` (an extension
    such as ".project") adds the folder's files with that extension after
    the subfolders, each with `file` true; several are comma-separated
    (".eds,.dcf")."""
    if drives:
        if os.name != "nt":
            raise ApiError(404, "only Windows has drives")
        return {"path": "", "parent": None, "drive": False, "drive_list": True, "project": False, "config": False,
                "eds": 0, "entries": [{"name": d, "path": d, "project": False, "config": False, "eds": None}
                                      for d in windows_drives()]}
    path = os.path.abspath(os.path.expanduser(path)) if path else home_folder()
    if not os.path.isdir(path):
        raise ApiError(404, "%s is not a folder" % path)
    entries = []
    try:
        names = sorted(os.listdir(path), key=str.lower)
    except OSError as e:
        raise folder_error(e, "list", path)
    for name in names:
        full = os.path.join(path, name)
        if name.startswith(".") or not os.path.isdir(full):
            continue
        try:
            eds = _eds_here(os.listdir(full))
        except OSError:
            eds = None  # not readable: listed, without a count
        entries.append({"name": name, "path": full, "eds": eds,
                        "project": os.path.isfile(os.path.join(full, "project.json")),
                        "config": os.path.isfile(os.path.join(full, CONFIG))})
    if files:
        ext = tuple(x.strip() for x in files.lower().split(",") if x.strip())
        entries.extend({"name": name, "path": os.path.join(path, name), "file": True}
                       for name in names if not name.startswith(".") and name.lower().endswith(ext)
                       and os.path.isfile(os.path.join(path, name)))
    parent = os.path.dirname(path)
    return {"path": path, "parent": parent if parent != path else None,
            "drive": os.name == "nt" and parent == path, "eds": _eds_here(names), "entries": entries,
            "project": os.path.isfile(os.path.join(path, "project.json")),
            "config": os.path.isfile(os.path.join(path, CONFIG))}


def under(path, roots):
    """Whether `path` is inside one of the folders `roots` (None skipped),
    links resolved and, on Windows, case ignored."""
    real = os.path.normcase(os.path.realpath(path))
    return any(real.startswith(os.path.normcase(os.path.realpath(r)) + os.sep) for r in roots if r)


def check_eds(name, data, mode):
    """The checks the PLC runs before dcfgen on an EDS (edslint under `mode`):
    (corrections, lint), or ApiError 422 naming what is wrong."""
    text, corrections, lint = edslint.check(data)
    try:
        Eds.read(name, text)
    except EdsError as e:
        raise ApiError(422, "%s is not an EDS the configurator can use: %s" % (name, e))
    if lint.read_error:
        raise ApiError(422, "%s cannot be used: %s" % (name, lint.read_error))
    failing = lint.failing(mode)
    if failing:
        raise ApiError(422, edslint.error_text(None, name, failing, mode),
                       findings=[f.to_json() for f in failing])
    return corrections, lint


def folder_lint_mode(path):
    """The eds_lint mode of the config in a project or standalone config
    folder; the default when it has none."""
    try:
        with open(params.config_file(path.strip()), encoding="utf-8") as f:
            cfg = json.load(f)
    except (params.Refused, OSError, ValueError, TypeError, AttributeError):
        cfg = {}
    return edslint.effective_mode(lint_master(cfg))


def lint_master(cfg):
    """The master object whose eds_lint an EDS import uses: the first
    master network's; None without one."""
    try:
        nets = contract.networks(cfg) if isinstance(cfg, dict) else []
    except (ValueError, TypeError, AttributeError):
        return None
    for net in nets:
        if net["role"] != "slave" and isinstance(net.get("master"), dict):
            return net["master"]
    return None


def folder_nodes(path):
    """{"nodes": [node IDs]} of the first network of the config in a project
    or standalone config folder, for "Add to a config…" before it opens the
    folder; no IDs when the folder has no config yet."""
    if not isinstance(path, str) or not path.strip():
        raise ApiError(400, "path must be a folder")
    try:
        with open(params.config_file(path.strip()), encoding="utf-8") as f:
            nets = contract.networks(json.load(f))
    except (params.Refused, OSError, ValueError, TypeError, AttributeError):
        return {"nodes": []}
    nodes = nets[0]["nodes"] if nets else []
    ids = []
    for n in nodes if isinstance(nodes, list) else []:
        try:
            ids.append(int(str(n.get("node_id")), 0))
        except (AttributeError, ValueError):
            pass
    return {"nodes": ids}


JOB_LABELS = {"read": "Read all", "backup": "Back up", "compare": "Compare", "restore_plan": "Restore plan",
              "restore": "Restore", "configure": "Write configuration", "configure_plan": "Write configuration plan",
              "configure_verify": "Verify"}


def connection_summary(out, host, local):
    """What the connection bar shows, the same shape for a USB adapter, an
    adapter on another machine and a runtime: the target, how the bit rate
    was confirmed or the path and round trip, the bus, another master and
    whether changes are allowed."""
    st = out.get("status") or {}
    hello = out.get("hello") or {}
    bus = st.get("bus") or {}
    if local:
        other = st.get("other_master_seen")
        remote = out.get("remote")
        return {"kind": "adapter", "target": "%s on %s" % (st.get("adapter") or "", remote) if remote
                else st.get("adapter") or "", "remote": remote, "bitrate": st.get("bitrate"),
                "check": st.get("bitrate_check"), "path": None, "rtt_ms": out.get("rtt_ms") if remote else None,
                "bus": {"state": bus.get("adapter_state") or "active", "frames": bus.get("frames"),
                        "error_frames": bus.get("error_frames")},
                "other_master": other, "allow_changes": bool(st.get("allow_changes")),
                "server_allow_changes": st.get("server_allow_changes", True) is not False,
                "allow_changes_source": "switch", "networks": []}
    states = {0: "no bus", 1: "error-active", 2: "error-warning", 3: "error-passive", 4: "bus-off"}
    return {"kind": "runtime", "target": host or "", "name": hello.get("name") or hello.get("hostname"),
            "bitrate": bus.get("bitrate"), "check": None, "path": out.get("path"), "rtt_ms": out.get("rtt_ms"),
            "bus": {"state": states.get(bus.get("state"), bus.get("state")), "interface": bus.get("interface"),
                    "tx_errors": bus.get("tx_errors"), "rx_errors": bus.get("rx_errors"),
                    "bus_off_count": bus.get("bus_off_count")},
            "other_master": None, "allow_changes": bool(hello.get("allow_changes")),
            "allow_changes_source": "runtime", "networks": [n.get("name") for n in out.get("networks") or []],
            "network": out.get("network")}


class Handler(http.server.BaseHTTPRequestHandler):
    server_version = "canworks-config/" + __version__

    def log_message(self, fmt, *args):
        if self.server.verbose:
            super().log_message(fmt, *args)

    # -- access control -----------------------------------------------------
    def _host_ok(self):
        host = (self.headers.get("Host") or "").strip().lower()
        allowed = {"127.0.0.1:%d" % self.server.server_port, "localhost:%d" % self.server.server_port}
        return host in allowed

    def _cookie_name(self):
        # _host_ok() let only this port's Host through.
        return "%s_%d" % (COOKIE, self.server.server_port)

    def _cookie_token(self):
        name = self._cookie_name()
        for part in (self.headers.get("Cookie") or "").split(";"):
            k, _, v = part.strip().partition("=")
            if k == name:
                return v
        return None

    def _send(self, status, body, ctype="application/json", headers=()):
        data = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy",
                         "default-src 'self'; style-src 'self'; script-src 'self'; img-src 'self' data:; "
                         "connect-src 'self'; frame-ancestors 'none'")
        for k, v in headers:
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def _deny(self, why):
        # Read the unread request body first: Windows resets a connection
        # closed with unread data, and the client then sees no 403 at all.
        length = int(self.headers.get("Content-Length") or 0)
        if 0 < length <= MAX_BODY:
            self.rfile.read(length)
        self._send(403, {"error": why})

    def do_GET(self):
        if not self._host_ok():
            return self._deny("requests must address 127.0.0.1")
        url = urllib.parse.urlsplit(self.path)
        query = urllib.parse.parse_qs(url.query)
        token = self.server.token
        if url.path == "/" and "code" in query:
            # The URL printed at start: its one-time code becomes the token in
            # a cookie, and the code leaves the address bar.
            if not self.server.take_start_code(query["code"][0]):
                return self._deny("this start address was used already: open the configurator from the browser "
                                  "tab it opened, or start canworks-config again for a new address")
            return self._send(303, b"", "text/plain", [
                ("Location", "/"),
                ("Set-Cookie", "%s=%s; HttpOnly; SameSite=Strict; Path=/" % (self._cookie_name(), token))])
        if url.path.startswith("/api/"):
            return self._api("GET", url, query)
        if not secrets.compare_digest(self._cookie_token() or "", token):
            return self._deny("open the URL printed by canworks-config (it carries the session token)")
        name = "index.html" if url.path == "/" else url.path.lstrip("/")
        full = os.path.normpath(os.path.join(STATIC, name))
        if not full.startswith(STATIC + os.sep) or not os.path.isfile(full):
            return self._send(404, {"error": "not found"})
        with open(full, "rb") as f:
            data = f.read()
        if name == "index.html":
            data = data.replace(b"{{TOKEN}}", token.encode("ascii")).replace(b"{{THEME}}", load_theme().encode("ascii"))
        ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype.endswith("javascript"):
            ctype += "; charset=utf-8"
        self._send(200, data, ctype)

    def do_POST(self):
        if not self._host_ok():
            return self._deny("requests must address 127.0.0.1")
        url = urllib.parse.urlsplit(self.path)
        if not url.path.startswith("/api/"):
            return self._send(404, {"error": "not found"})
        if url.path == "/api/page/closed":
            # The page's pagehide beacon: it cannot send the token header, so
            # the session cookie (SameSite=Strict) is what it shows, and all it
            # can do is mark one page closed.
            if not secrets.compare_digest(self._cookie_token() or "", self.server.token):
                return self._deny("missing or wrong session cookie")
            try:
                page = self._body().get("page")
            except ApiError as e:
                return self._send(e.status, e.body)
            self.server.page_closed(page)
            return self._send(204, b"", "text/plain")
        if url.path.startswith("/api/instance/"):
            return self._instance(url.path)
        self._api("POST", url, urllib.parse.parse_qs(url.query))

    def _instance(self, path):
        """A second canworks-config of the same user (launch.py): with the
        secret of instance.json instead of the session token, a new start
        address (/api/instance/start, with a PATH to open), and whether the
        browser opened it (/api/instance/page)."""
        secret = self.server.instance_secret
        if not secret or not secrets.compare_digest(self.headers.get(launch.HEADER) or "", secret):
            return self._deny("missing or wrong instance secret")
        try:
            body = self._body()
            if path == "/api/instance/start":
                out = self.server.second_start(body.get("path"), body.get("browser") is not False,
                                               from_shortcut=body.get("shortcut") is True)
            elif path == "/api/instance/page":
                out = {"opened": not self.server.start_code_waiting(str(body.get("code") or ""))}
            elif path == "/api/instance/update":
                # canworks-config --update while this configurator runs: it updates (the guard applies).
                if body.get("go") is True:
                    out = self.server.update_now(body.get("version"))
                else:
                    out = self.server.updates.view(load_ui()["update_check"] == "on")
            else:
                raise ApiError(404, "no such API: POST %s" % path)
        except ApiError as e:
            return self._send(e.status, e.body)
        self._send(200, out)
        if out.get("updating"):
            self.wfile.flush()
            threading.Thread(target=self.server.stop, args=("update",), daemon=True).start()

    def _body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            raise ApiError(413, "request too large")
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw.decode("utf-8"))
        except ValueError:
            raise ApiError(400, "request body must be JSON")
        if not isinstance(body, dict):
            raise ApiError(400, "request body must be a JSON object")
        return body

    def _api(self, method, url, query):
        quitting = False
        if not secrets.compare_digest(self.headers.get(TOKEN_HEADER) or "", self.server.token):
            return self._deny("missing or wrong session token")
        s = self.server.session
        try:
            if url.path.startswith("/api/online/"):
                # Network calls: outside the session lock, so editing never waits on the runtime.
                body = self._body() if method == "POST" else {}
                return self._send(200, self._online((method, url.path), body))
            if url.path.startswith("/api/sim/"):
                body = self._body() if method == "POST" else {k: v[0] for k, v in query.items() if v}
                return self._send(200, self._sim((method, url.path), body))
            if url.path == "/api/devices" or url.path.startswith("/api/devices/"):
                # SSH to devices: outside the session lock, like the runtime calls.
                body = self._body() if method == "POST" else {}
                return self._send(200, self._devices((method, url.path), body))
            if url.path.startswith("/api/trace/"):
                if (method, url.path) == ("POST", "/api/trace/open") and \
                        (self.headers.get("Content-Type") or "").startswith("application/octet-stream"):
                    # A trace file as it is: large files do not fit a JSON body.
                    length = int(self.headers.get("Content-Length") or 0)
                    if length > MAX_TRACE_FILE:
                        raise ApiError(413, "the file is larger than %d MiB" % (MAX_TRACE_FILE >> 20))
                    body = {"raw": self.rfile.read(length), "name": query.get("name", ["trace"])[0],
                            "network": query.get("network", [None])[0]}
                    try:  # Commission a device: the Nodes tab's EDS files, for decoding
                        body["eds"] = json.loads(query.get("eds", ["{}"])[0])
                    except ValueError:
                        pass
                else:
                    body = self._body() if method == "POST" else {}
                try:
                    return self._send(200, self._trace((method, url.path), body))
                except tracing.Refused as e:
                    raise ApiError(e.status, str(e), **e.extra)
            if url.path.startswith("/api/codesys/import/") and method == "POST":
                # Outside the lock: exporting a .project runs CODESYS for minutes.
                return self._send(200, self._codesys_import(url.path.rsplit("/", 1)[1], self._body()))
            if url.path == "/api/codesys/build" and method == "POST":
                # Outside the lock: CODESYS takes minutes, the page goes on.
                body = self._body()
                with s.lock:
                    self._need_open(s)
                    if s.pending or s.pending_dbc or s.changed_on_disk() or not os.path.isfile(s.config_path):
                        raise ApiError(409, "save the config before building it into the CODESYS project",
                                       unsaved=True)
                    cfg_path = s.config_path
                remove = body.get("remove") if isinstance(body.get("remove"), bool) else None
                return self._send(200, s.codesys_build(cfg_path, runner=self.server.codesys_runner, remove=remove))
            if (method, url.path) == ("POST", "/api/heartbeat"):
                body = self._body()
                return self._send(200, self.server.heartbeat(body.get("page"), body.get("unsaved") is True))
            if (method, url.path) == ("POST", "/api/second_start/done"):
                # The page took a second start's PATH, or its user said no.
                self.server.open_taken(self._body().get("id"))
                return self._send(200, {})
            if url.path == "/api/update" or url.path.startswith("/api/update/"):
                body = self._body() if method == "POST" else {}
                out = self._update((method, url.path), body)
                self._send(200, out)
                if out.get("updating"):
                    # As Quit: only after the answer is out.
                    self.wfile.flush()
                    threading.Thread(target=self.server.stop, args=("update",), daemon=True).start()
                return None
            if url.path in ("/api/explain", "/api/explain/build"):
                body = self._body() if method == "POST" else {}
                return self._send(200, self._explain((method, url.path), body))
            with s.lock:
                body = self._body() if method == "POST" else {}
                route = (method, url.path)
                if route == ("GET", "/api/state"):
                    out = s.state()
                elif route == ("GET", "/api/ui"):
                    out = load_ui()
                elif route == ("POST", "/api/ui"):
                    out = save_ui(body)
                elif route == ("GET", "/api/codesys/devices"):
                    out = codesys_devices(query.get("project", [None])[0], query.get("refresh", [""])[0] == "1")
                elif route == ("GET", "/api/folders"):
                    out = list_folders(query.get("path", [None])[0], query.get("drives", [""])[0] == "1",
                                       query.get("files", [None])[0])
                elif route == ("POST", "/api/folder_nodes"):
                    out = folder_nodes(body.get("path"))
                    if body.get("carry_eds") is not None:
                        # "Add to a config…": an EDS the config could not take is refused before leaving Commission.
                        name, data = s.carry_source(body.get("carry_eds"), online.Settings(config_dir()).eds_library)
                        check_eds(name, data, folder_lint_mode(body.get("path")))
                elif route == ("POST", "/api/open"):
                    carry = None
                    if body.get("carry_eds") is not None:
                        carry = s.carry_source(body.get("carry_eds"), online.Settings(config_dir()).eds_library)
                    self._leave_commission(s)
                    s.open(body.get("path"), body.get("mode", "auto"), body.get("new"))
                    carried = None
                    if carry is not None:
                        try:
                            carried = s.import_eds(carry[0], carry[1], "keep_both")
                        except ApiError as e:
                            carried = {"error": str(e)}
                    out = s.state()
                    if carried is not None:
                        out["carried_eds"] = carried
                elif route == ("POST", "/api/recent/forget"):
                    s.forget(body.get("path"))
                    out = {"recent": s.recent_listed()}
                elif route == ("POST", "/api/commission"):
                    s.commission_device()
                    self.server.adapter_allow = False
                    self.server.connection.close()
                    out = s.state()
                elif route == ("POST", "/api/close"):
                    self._leave_commission(s)
                    s.close()
                    out = s.state()
                elif route == ("POST", "/api/reload"):
                    self._need_open(s)
                    s.reload()
                    out = s.state()
                elif route == ("POST", "/api/rescan"):
                    self._need_open(s)
                    s.rescan()
                    out = s.state()
                elif route == ("POST", "/api/eds"):
                    self._need_open(s)
                    try:
                        data = base64.b64decode(body.get("data") or "", validate=True)
                    except ValueError:
                        raise ApiError(400, "data must be base64")
                    out = s.import_eds(body.get("name"), data, body.get("on_conflict"), body.get("eds_lint"))
                elif route == ("POST", "/api/eds_path"):
                    self._need_open(s)
                    out = s.import_eds_path(body.get("path"), body.get("on_conflict"), body.get("eds_lint"))
                elif route == ("POST", "/api/j1939/dbc"):
                    self._need_open(s)
                    data = None
                    if body.get("data") is not None:
                        try:
                            data = base64.b64decode(body.get("data") or "", validate=True)
                        except ValueError:
                            raise ApiError(400, "data must be base64")
                    out = s.import_dbc(body.get("name"), data, body.get("on_conflict"))
                elif route == ("POST", "/api/j1939/entries"):
                    self._need_open(s)
                    out = s.dbc_entries(body.get("config"), body.get("network", 0), body.get("name"),
                                        body.get("picks"))
                elif route == ("POST", "/api/raw/dbc"):
                    self._need_open(s)
                    data = None
                    if body.get("data") is not None:
                        try:
                            data = base64.b64decode(body.get("data") or "", validate=True)
                        except ValueError:
                            raise ApiError(400, "data must be base64")
                    out = s.import_dbc(body.get("name"), data, body.get("on_conflict"), kind="raw")
                elif route in (("POST", "/api/raw/suggest"), ("POST", "/api/raw/st"), ("POST", "/api/raw/dbc_import")):
                    self._need_open(s)
                    out = s.raw_page(route[1].rsplit("/", 1)[1], body)
                elif route == ("POST", "/api/j1939/st"):
                    self._need_open(s)
                    out = s.j1939_st(body.get("config"), body.get("network", 0), body.get("kind"), body.get("index"))
                elif route == ("POST", "/api/check"):
                    self._need_open(s)
                    out = s.check(body.get("config"), notes=body.get("notes"))
                elif route == ("POST", "/api/export_dbc"):
                    self._need_open(s)
                    out = s.export_dbc(body.get("config"), body.get("sdo", "none"), body.get("network"), body.get("notes"))
                elif route == ("POST", "/api/export_html"):
                    self._need_open(s)
                    out = s.export_html(body.get("config"), body.get("notes"))
                elif route == ("POST", "/api/export_codesys"):
                    self._need_open(s)
                    out = s.export_codesys(body.get("config"))
                elif route == ("POST", "/api/openplc/move_main"):
                    self._need_open(s)
                    out = s.move_main(body.get("config"))
                elif route == ("POST", "/api/switch_target"):
                    self._need_open(s)
                    out = s.switch_target(body.get("config"), body.get("target"))
                elif route == ("POST", "/api/export_dcf"):
                    self._need_open(s)
                    out = s.export_dcf(body.get("config"), body.get("node"), body.get("network"))
                elif route == ("POST", "/api/place"):
                    self._need_open(s)
                    out = s.place(body.get("config"), body.get("node"), body.get("direction"), body.get("type"),
                                  body.get("start"), body.get("network", 0), body.get("access"))
                elif route == ("POST", "/api/slave_eds"):
                    self._need_open(s)
                    out = s.build_slave_eds(body.get("config"), body.get("network", 0), body.get("description"),
                                            body.get("name"), bool(body.get("gateway")), body.get("start"),
                                            bool(body.get("replace")))
                elif route == ("POST", "/api/export_eds"):
                    self._need_open(s)
                    out = s.export_eds(body.get("config"), body.get("network", 0))
                elif route == ("POST", "/api/bridge/map"):
                    self._need_open(s)
                    out = s.bridge_map(body.get("config"))
                elif route == ("POST", "/api/bridge/pack"):
                    self._need_open(s)
                    out = s.bridge_pack(body.get("config"))
                elif route == ("POST", "/api/bridge/suggest"):
                    self._need_open(s)
                    out = s.bridge_suggest(body.get("config"), body.get("block"), body.get("index"))
                elif route == ("POST", "/api/connections/add"):
                    self._need_open(s)
                    out = s.add_connection(body.get("config"), body.get("connection"))
                elif route == ("POST", "/api/connections/download"):
                    self._need_open(s)
                    out = s.connection_download(body.get("config"), body.get("index"))
                elif route == ("POST", "/api/nodered_package"):
                    out = s.nodered_package()
                elif route == ("POST", "/api/export_notes"):
                    self._need_open(s)
                    out = s.export_notes(body.get("config"), body.get("eds"), body.get("notes"), body.get("own") is True)
                elif route == ("POST", "/api/import_notes") and s.commission:
                    out = s.import_notes_commission(body.get("eds_path"), body.get("text"), body.get("file"))
                elif route == ("POST", "/api/notes/write"):
                    self._need_open(s)
                    out = s.write_notes(body.get("eds_path"), body.get("changes"), body.get("restore") is True,
                                        body.get("text"))
                elif route == ("POST", "/api/import_notes"):
                    self._need_open(s)
                    out = s.import_notes(body.get("config"), body.get("eds"), body.get("text"), body.get("file"), body.get("notes"))
                elif route == ("POST", "/api/save"):
                    self._need_open(s)
                    out = s.save(body.get("config"), bool(body.get("overwrite")),
                                 body.get("notes"), bool(body.get("editor_overwrite")))
                    out["state"] = s.state()
                elif route == ("POST", "/api/move"):
                    self._need_open(s)
                    out = s.move(body.get("project"), bool(body.get("replace")))
                    out["state"] = s.state()
                elif route == ("POST", "/api/new"):
                    self._leave_commission(s)
                    s.new_config(body.get("path"), bool(body.get("editor_project")), body.get("target"))
                    out = s.state()
                elif route == ("POST", "/api/new_project"):
                    self._need_open(s)
                    out = s.new_project(body.get("parent"), body.get("name"), body.get("interval"),
                                        bool(body.get("blocks")))
                    out["state"] = s.state()
                elif route == ("POST", "/api/quit"):
                    quitting = True
                    out = {"bye": True}
                else:
                    raise ApiError(404, "no such API: %s %s" % route)
            self._send(200, out)
            if quitting:
                # Only after the answer is out, or the client may see the socket close first.
                self.wfile.flush()
                threading.Thread(target=self.server.stop, args=("Quit",), daemon=True).start()
        except ApiError as e:
            self._send(e.status, e.body)
        except OSError as e:
            if not e.filename:  # pragma: no cover
                traceback.print_exc()
                return self._send(500, {"error": UNEXPECTED_ERROR})
            # A file the configurator could not read or write: say which.
            e = folder_error(e, "use", os.path.dirname(os.path.abspath(e.filename)))
            self._send(e.status, e.body)
        except Exception:  # pragma: no cover - the page gets one sentence, the terminal the details
            traceback.print_exc()
            self._send(500, {"error": UNEXPECTED_ERROR})

    def _update(self, route, body):
        """The update check and Update (pc-tools-self-update)."""
        u = self.server.updates
        ui_on = load_ui()["update_check"] == "on"
        if route == ("GET", "/api/update"):
            return u.view(ui_on)
        if route == ("POST", "/api/update/check"):
            threading.Thread(target=u.check, daemon=True, name="update-check").start()
            return dict(u.view(ui_on), checking=True)
        if route == ("POST", "/api/update/dismiss"):
            try:
                u.dismiss(body.get("version"))
            except ValueError as e:
                raise ApiError(400, str(e))
            return u.view(ui_on)
        if route == ("POST", "/api/update/start"):
            when = body.get("when") or "now"
            if when == "now":
                return self.server.update_now(body.get("version"))
            if when == "quit":
                self.server.update_target(body.get("version"))
                u.on_quit = body.get("version")
                return u.view(ui_on)
            if when == "cancel":
                u.on_quit = None
                return u.view(ui_on)
            raise ApiError(400, "when must be now, quit or cancel")
        raise ApiError(404, "no such API: %s %s" % route)

    @staticmethod
    def _need_open(s):
        if not s.mode:
            raise ApiError(409, "no project or config folder is open")

    # -- Import from CODESYS (codesys-import) ---------------------------------
    def _codesys_import(self, step, body):
        """/api/codesys/import/<step>: open (a .project path, an .xml path, or
        an uploaded file as `name` and base64 `data`), device (the device
        picked), eds (an EDS for a node's device type), create (a new config
        folder at `path`) and add (the networks into the open draft
        `config`, `answers` for name conflicts). open, device and eds give
        the device list or the preview; nothing is written before create or
        add."""
        from . import codesysimport as ci
        from ..codesys import run as codesys_run
        s = self.server.session
        imp = self.server.codesys_import
        found = codesys_found()
        runner = self.server.codesys_runner

        def preview():
            lib = online.Settings(config_dir()).eds_library
            folders = ([("project", s.canopen_dir)] if s.mode and not s.commission and os.path.isdir(s.canopen_dir)
                       else []) + ([("library", lib)] if lib else [])
            roots = codesys_run.repository_roots() if found else ()
            return ci.convert(imp, self.server.eds_index.matches, folders, roots)

        def need():
            if imp is None or (step != "device" and imp.result is None):
                raise ApiError(409, "no import in progress: pick the CODESYS file again")
        try:
            if step == "open":
                data = None
                if body.get("data") is not None:
                    try:
                        data = base64.b64decode(body.get("data") or "", validate=True)
                    except ValueError:
                        raise ApiError(400, "data must be base64")
                elif not isinstance(body.get("path"), str) or not body["path"].strip():
                    raise ApiError(400, "give path, or name and data")
                if imp is not None:
                    imp.close()
                imp = self.server.codesys_import = ci.Import()
                out = ci.open_source(imp, path=body.get("path") if data is None else None, name=body.get("name"),
                                     data=data, found=found, runner=runner)
                return out or preview()
            if step == "device":
                need()
                device = body.get("device")
                if not isinstance(device, str) or not device:
                    raise ApiError(400, "device must be a device name")
                if imp.project:
                    out = ci.open_source(imp, path=imp.project, device=device, found=found, runner=runner)
                else:
                    out = ci.open_source(imp, name=imp.source, data=imp.xml, device=device, found=found)
                if out:
                    raise ApiError(422, "%s has no device %s with a CANopen Manager" % (imp.source, device))
                return preview()
            need()
            if step == "eds":
                try:
                    data = base64.b64decode(body.get("data") or "", validate=True)
                except ValueError:
                    raise ApiError(400, "data must be base64")
                name = os.path.basename(str(body.get("name") or "")).strip()
                if not name.lower().endswith((".eds", ".dcf")):
                    raise ApiError(422, "%s is not an EDS file (.eds or .dcf)" % (name or "the file"))
                check_eds(name, data, edslint.effective_mode(None))
                path = os.path.join(imp.folder, "upload.eds")
                with open(path, "wb") as f:
                    f.write(utf8_eds(data)[0])
                ci.add_eds(imp, body.get("device"), name, path)
                return preview()
            if step == "create":
                if imp.result.missing:
                    raise ApiError(422, "no EDS for %s: add one for each first" % ", ".join(
                        "%s (node %s)" % (m["name"], m["node_id"]) for m in imp.result.missing))
                with s.lock:
                    self._leave_commission(s)
                    s.open(body.get("path"), "standalone", new=True)
                    ci.create(imp, os.path.dirname(s.config_path))
                    s.open(body.get("path"), "standalone")
                    out = s.state()
                imp.close()
                self.server.codesys_import = None
                return out
            if step == "add":
                if imp.result.missing:
                    raise ApiError(422, "no EDS for %s: add one for each first" % ", ".join(
                        "%s (node %s)" % (m["name"], m["node_id"]) for m in imp.result.missing))
                cfg = body.get("config")
                if not isinstance(cfg, dict):
                    raise ApiError(400, "config must be a JSON object")
                answers = body.get("answers") if isinstance(body.get("answers"), dict) else {}
                with s.lock:
                    self._need_open(s)
                    if targets.target(cfg) != targets.CODESYS:
                        raise ApiError(409, "Add to this config needs a CODESYS config; Create config makes a new one")
                    cfg = version2(cfg)
                    pending = [c for c in ci.conflicts(imp, cfg) if answers.get(c["name"]) not in ("rename", "replace")]
                    if pending:
                        raise ApiError(409, "network names or numbers in use", conflicts=pending)
                    renamed = {}
                    for name, src in sorted(imp.result.eds_files.items()):
                        with open(src, "rb") as f:
                            renamed[name] = s.import_eds(name, f.read(), "keep_both")["name"]
                    out = ci.merge(imp, cfg, answers, renamed)
                    names = sorted(set(renamed.values()))
                    summaries = s.eds_info(names)
                imp.close()
                self.server.codesys_import = None
                return {"config": out, "networks": [n["name"] for n in imp.result.cfg["networks"]], "eds": summaries}
            raise ApiError(404, "no such API: POST /api/codesys/import/%s" % step)
        except ci.Refused as e:
            raise ApiError(e.status, str(e), **e.extra)

    # -- devices (device-install) -------------------------------------------
    def _devices(self, route, body):
        """/api/devices/*: the Devices workspace, with a config open or none
        (the start page's Install on a device). A question the user has to
        answer (trust a host key, a password, the sudo password) is a 409 with
        `need`; passwords are only in the request that carries them."""
        from ..devices import jobs as djobs, ssh as dssh, store as dstore
        from .. import __version__
        s, dev = self.server.session, self.server.devices
        with s.lock:
            if s.commission:
                raise ApiError(409, "Commission a device has no devices; open a project or config folder, "
                                    "or Install on a device from the start page")
            if s.mode:
                project, folder, config_path = s.folder, s.canopen_dir, s.config_path
                cfg = s.read_config()[0]
            else:
                project = folder = config_path = cfg = None
        target = device_target(cfg) if project else None
        instance = djobs.instance_name(os.path.basename(os.path.normpath(project))) if project else None
        saved = config_path if config_path and os.path.isfile(config_path) else None
        networks = device_networks(cfg) if project else None
        from ..localbus import remote as remote_mod
        settings = online.Settings(config_dir())
        # The remote CAN adapter's token is this PC's, as for Adapter on another machine.
        dev.has_token = lambda host, port: bool(settings.adapter_token(remote_mod.host_key(host, port or 7536)))
        did = body.get("device")
        if did is not None and not isinstance(did, str):
            raise ApiError(400, "device must be a device id")
        password = body.get("password") if isinstance(body.get("password"), str) and body.get("password") else None
        sudo = body.get("sudo_password") if isinstance(body.get("sudo_password"), str) and body.get("sudo_password") \
            else None
        try:
            if route == ("GET", "/api/devices"):
                return {"devices": dev.view(target, instance, saved, __version__, self._own_host(project), networks),
                        "target": target, "instance": instance, "pc_version": __version__, "jobs": dev.running_jobs()}
            if route == ("GET", "/api/devices/discovered"):
                found = devices_service.not_saved([r for r in online.runtimes_list().get("discovered") or []
                                                   if r.get("addresses")], [d["host"] for d in dev.store.devices()])
                return {"discovered": [{"name": r.get("name") or "", "host": sorted(r["addresses"], key=lambda a: ":" in a)[0]}
                                       for r in found]}
            if route == ("POST", "/api/devices/add"):
                port = body.get("port")
                return {"device": dev.add(body.get("host"), body.get("user") or "",
                                          int(port) if isinstance(port, str) and port.isdigit() else port)}
            if not did:
                raise ApiError(400, "which device?")
            trust = body.get("trust") if isinstance(body.get("trust"), str) else None
            if route not in (("POST", "/api/devices/remove"), ("POST", "/api/devices/forget_key"),
                             ("POST", "/api/devices/probe")) and (password or trust):
                # A page that answered a password or host key question for another call: log in first.
                dev.connection(did, password=password, trust=trust)
            if route == ("POST", "/api/devices/remove"):
                dev.remove(did)
                return {}
            if route == ("POST", "/api/devices/forget_key"):
                return {"forgotten": dev.forget_key(did)}
            if route == ("POST", "/api/devices/probe"):
                return dev.probe(did, target, instance, saved, __version__, password=password, trust=trust,
                                 refresh=body.get("refresh") is True, networks=networks)
            if route == ("POST", "/api/devices/adapter_token"):
                # Copy token: the one answer that carries an adapter server's token, on request.
                port = body.get("port")
                if isinstance(port, bool) or not isinstance(port, int):
                    raise ApiError(400, "port must be the adapter server's port")
                token = settings.adapter_token(remote_mod.host_key(dev.store.get(did)["host"], port))
                if not token:
                    raise ApiError(404, "this PC has no token for that adapter server: use New token…")
                return {"token": token}
            if route == ("POST", "/api/devices/key_login"):
                dev.key_login(did)
                return {}
            if route == ("POST", "/api/devices/start"):
                action = body.get("action")
                if action == "bridge_config" and not project:
                    raise ApiError(409, "starting a bridge with a config needs that config open")
                if action in djobs.BRIDGE_ACTIONS and project:
                    if not saved:
                        raise ApiError(409, "save the config first: the bridge starts with the saved config", unsaved=True)
                    with s.lock:
                        if s.pending or s.pending_dbc or s.changed_on_disk():
                            raise ApiError(409, "save the config first: the bridge starts with the saved config",
                                           unsaved=True)
                        s.need_no_errors()
                options = body.get("options") if isinstance(body.get("options"), dict) else {}
                verifier = token = key = None
                if action in ("adapter_on", "adapter_token"):
                    # The token is made here and kept on this PC; only its verifier goes to the device.
                    probe = dev.store.get(did).get("probe") or {}
                    port = options.get("port") if action == "adapter_on" else next(
                        (a.get("port") for a in probe.get("adapters") or []
                         if isinstance(a, dict) and a.get("adapter") == options.get("adapter")), None)
                    if isinstance(port, bool) or not isinstance(port, int):
                        raise ApiError(400, "port must be the adapter server's port")
                    token = diag.new_token()
                    verifier = diag.token_verifier(token)
                    key = remote_mod.host_key(dev.store.get(did)["host"], port)
                job = dev.start(did, action, options, sudo, instance=instance, config_dir=folder if project else None,
                                verifier=verifier)
                if token:
                    # Kept once the job runs: a job that fails leaves a token the next Turn on… replaces.
                    settings.set_adapter_token(key, token)
                return {"job": job}
            if route == ("POST", "/api/devices/job"):
                job = body.get("job")
                offset = body.get("offset") if isinstance(body.get("offset"), int) else 0
                out = dev.follow(did, job, offset)
                if out.get("done") and out.get("exit") == 0 and project and target in ("bridge", "openplc_modbus"):
                    # The device becomes the project's runtime host when it had none.
                    settings = online.Settings(config_dir())
                    if not settings.project(project).get("host"):
                        settings.update_project(project, host=dev.store.get(did)["host"])
                return out
            if route == ("POST", "/api/devices/stop"):
                dev.stop(did, body.get("job"), sudo)
                return {}
        except dssh.NeedTrust as e:
            raise ApiError(409, str(e), need="trust", fingerprint=e.fingerprint, key_type=e.key_type)
        except dssh.KeyChanged as e:
            raise ApiError(409, str(e), need="forget_key", fingerprint=e.fingerprint)
        except dssh.NeedPassword as e:
            raise ApiError(409, str(e), need="password", wrong=e.wrong)
        except djobs.NeedSudo as e:
            raise ApiError(409, str(e), need="sudo", wrong=e.wrong)
        except dssh.Unreachable as e:
            raise ApiError(422, str(e), unreachable=True)
        except dstore.DeviceError as e:
            raise ApiError(422, str(e), **({"field": e.field} if e.field else {}))
        except dssh.SshError as e:
            raise ApiError(422, str(e))
        raise ApiError(404, "no such API: %s %s" % route)

    @staticmethod
    def _own_host(project):
        """The open project's Online access runtime host (its devices are
        listed first), or None with no config."""
        if not project:
            return None
        p = (online.Settings(config_dir()).load().get("projects") or {}).get(project)
        return runtime_host_only((p or {}).get("host") if isinstance(p, dict) else None)

    def _watch(self, settings, folder, body):
        """The object dictionary watch lists of this project, kept per node in
        online.json on this PC: {"node": N} reads one, with "keys" (and
        "period_ms") it is replaced; an empty key list removes it. With a
        `network` the list is that network's node's ("<network>/<node>")."""
        node = body.get("node")
        if isinstance(node, bool) or not isinstance(node, int) or not 1 <= node <= 127:
            raise ApiError(400, "node must be 1-127")
        network = body.get("network")
        key = "%s/%d" % (network, node) if isinstance(network, str) and network else str(node)
        lists = settings.project(folder).get("watch")
        lists = dict(lists) if isinstance(lists, dict) else {}
        if "keys" in body:
            keys = body.get("keys")
            if not isinstance(keys, list) or len(keys) > params.WATCH_MAX:
                raise ApiError(400, "the watch list holds at most %d entries" % params.WATCH_MAX)
            clean = []
            for k in keys:
                if (not isinstance(k, list) or len(k) != 2 or any(isinstance(x, bool) or not isinstance(x, int) for x in k)
                        or not 0 <= k[0] <= 0xFFFF or not 0 <= k[1] <= 0xFF):
                    raise ApiError(400, "keys must be [index, subindex] pairs")
                if k not in clean:
                    clean.append(k)
            period = body.get("period_ms", 1000)
            if isinstance(period, bool) or not isinstance(period, int) or not 500 <= period <= 60000:
                raise ApiError(400, "period_ms must be 500-60000")
            if clean:
                lists[key] = {"keys": clean, "period_ms": period}
            else:
                lists.pop(key, None)
            settings.update_project(folder, watch=lists or None)
        got = lists.get(key) or {}
        return {"node": node, "keys": got.get("keys") or [], "period_ms": got.get("period_ms") or 1000}

    # -- online access ------------------------------------------------------
    def _online(self, route, body):
        """/api/online/*: the token and host for this project, and requests
        to the bridge's diagnostics channel through one kept-open connection."""
        s, conn = self.server.session, self.server.connection
        settings = online.Settings(config_dir())
        with s.lock:
            self._need_open(s)
            folder, config_path, canopen_dir = s.folder, s.config_path, s.canopen_dir
            native = s.adapter_online()
        proj = settings.project(folder)
        if route == ("POST", "/api/online/settings") and "remote_adapter" in body:
            # The adapter on another machine as the target (Commission a device, a CODESYS
            # config, and a config in place of its runtime), or not; kept on this PC.
            on = body.get("remote_adapter") is True
            if on != bool(proj.get("remote_adapter")):
                self.server.sender.close()
                conn.close()
                self.server.adapter_allow = False
                proj = settings.update_project(folder, remote_adapter=True if on else None)
        # Online access through an adapter: a USB adapter on this PC, or an adapter server.
        adapter = native or bool(proj.get("remote_adapter"))

        def view():
            p = settings.project(folder)
            lib = settings.eds_library
            count, capped = online.count_eds(lib)
            remote_host = p.get("remote_host") or ""
            return {"token": p.get("token"), "host": p.get("host") or "", "eds_library": lib,
                    "eds_count": count, "eds_count_capped": capped,
                    "connected": conn.connected, "target": "adapter" if adapter else "runtime",
                    "adapter": p.get("adapter") or "", "adapter_bitrate": p.get("adapter_bitrate"),
                    "check_node": p.get("check_node"), "remote_adapter": bool(p.get("remote_adapter")),
                    "remote_host": remote_host,
                    "remote_token_set": bool(remote_host and settings.adapter_token(remote_host)),
                    "allow_changes": self.server.adapter_allow, "commission": bool(s.commission),
                    "remembered": online.remembered_view(p.get("host")),
                    "recent": [r for r in p.get("recent") or [] if isinstance(r, dict)]}

        if route == ("GET", "/api/online/settings"):
            return view()
        if route == ("GET", "/api/online/runtimes"):
            # The connect box's list: runtimes that answer on the local
            # network (two seconds of mDNS) and the ones this PC remembers.
            return online.runtimes_list()
        if route in (("POST", "/api/online/paired_pcs"), ("POST", "/api/online/remove_pc")):
            return self._paired_pcs(route, proj, body)
        if route == ("GET", "/api/online/adapters"):
            from .. import localbus
            return {"adapters": localbus.list_adapters()}
        if route == ("GET", "/api/online/adapter_servers"):
            # The connect panel's adapter servers on the local network (two seconds of mDNS).
            return online.adapter_servers_list()
        if route == ("POST", "/api/online/settings"):
            if not adapter and any(k in body for k in ("adapter", "adapter_bitrate", "check_node", "allow_changes")):
                raise ApiError(422, "a USB adapter on this PC is used in Commission a device and in a CODESYS "
                                    "project; here online access goes through the runtime")
            if "adapter" in body:
                text = (body.get("adapter") or "").strip()
                if text:
                    from .. import localbus
                    try:
                        localbus.parse(text)
                    except localbus.AdapterError as e:
                        raise ApiError(422, str(e))
                settings.update_project(folder, adapter=text or None)
                self.server.adapter_allow = False
                conn.close()
            if "adapter_bitrate" in body:
                kbit = body.get("adapter_bitrate")
                if kbit is not None and (not isinstance(kbit, int) or isinstance(kbit, bool) or not 10 <= kbit <= 1000):
                    raise ApiError(422, "the bit rate must be 10-1000 kbit/s")
                settings.update_project(folder, adapter_bitrate=kbit)
                conn.close()
            if "check_node" in body:
                node = body.get("check_node")
                if node is not None and (not isinstance(node, int) or isinstance(node, bool) or not 1 <= node <= 127):
                    raise ApiError(422, "the node ID for the bit rate check must be 1-127")
                settings.update_project(folder, check_node=node)
                conn.close()
            if "allow_changes" in body:
                # This connection only: never saved, off again after the next
                # adapter change or restart. The open connection takes it at
                # once, without closing.
                self.server.adapter_allow = body.get("allow_changes") is True
                conn.set_allow_changes(self.server.adapter_allow)
            if "remote_host" in body:
                text = (body.get("remote_host") or "").strip()
                if text:
                    from ..localbus import remote
                    try:
                        text = remote.host_key(*remote.parse(text))
                    except ValueError as e:
                        raise ApiError(422, str(e))
                if text != (proj.get("remote_host") or ""):
                    settings.update_project(folder, remote_host=text or None)
                    self.server.sender.close()
                    conn.close()
            if "remote_token" in body:
                # This PC's token for the adapter server of remote_host, for every project; "" forgets it.
                host = settings.project(folder).get("remote_host")
                if not host:
                    raise ApiError(422, "enter the adapter server's host first")
                token = (body.get("remote_token") or "").strip()
                settings.set_adapter_token(host, token or None)
                self.server.sender.close()
                conn.close()
            if "host" in body:
                host = (body.get("host") or "").strip()
                if host:
                    try:
                        diag.parse_runtime(host)
                    except ValueError as e:
                        raise ApiError(422, str(e))
                settings.update_project(folder, host=host or None)
                conn.close()
                self.server.sender.close()
            if "eds_library" in body:
                lib = os.path.expanduser((body.get("eds_library") or "").strip())
                if lib and not os.path.isdir(lib):
                    raise ApiError(422, "%s is not a folder" % lib)
                settings.set_eds_library(os.path.abspath(lib) if lib else "")
            return view()
        if route == ("POST", "/api/online/token"):
            action = body.get("action")
            if action == "generate":
                token = diag.new_token()
            elif action == "set":
                token = (body.get("token") or "").strip()
                if not token:
                    raise ApiError(422, "enter the token")
                if not _token_matches(token, body):
                    raise ApiError(422, "this token does not match the token in the configuration")
            elif action == "check":
                # Whether this PC's token is the config's (token_verifier, or the former token_sha256).
                return dict(view(), match=_token_matches(proj.get("token"), body))
            elif action == "verifier":
                # A token_verifier for this PC's token: Upgrade of a config with the former token_sha256.
                if not proj.get("token"):
                    raise ApiError(409, "this PC has no token for this project", need="token")
                return dict(view(), token_verifier=diag.token_verifier(proj["token"]))
            elif action == "forget":
                settings.update_project(folder, token=None)
                conn.close()
                self.server.sender.close()
                return view()
            else:
                raise ApiError(400, "action must be generate, set, check, verifier or forget")
            settings.update_project(folder, token=token)
            conn.close()
            self.server.sender.close()
            return dict(view(), token_verifier=diag.token_verifier(token))
        if route == ("POST", "/api/online/close"):
            conn.close()
            return {"closed": True}
        if route == ("POST", "/api/online/disconnect"):
            # Disconnect in Commission a device: the adapter is closed with
            # every job on it (trace, Send panel), free for other tools.
            self.server.traces.stop_all()
            self.server.sender.close()
            conn.close()
            self.server.adapter_allow = False
            self.server.watch.update(scan=False, lss_find=False, pdo_test=None, sync=False)
            return view()
        if route == ("POST", "/api/online/use_eds"):
            return self._use_eds(s, settings, canopen_dir, body.get("path"), body.get("eds_lint"))
        if route == ("POST", "/api/online/eds_library"):
            # The Add node dialog's library list: the files with their product names.
            return {"library": settings.eds_library or "",
                    "files": self.server.eds_index.listing([("library", settings.eds_library)])}
        if route == ("POST", "/api/online/watch"):
            return self._watch(settings, folder, body)

        if route == ("POST", "/api/online/jobs"):
            def bus_call(fn):
                net = body.get("network") if isinstance(body.get("network"), str) and body.get("network") else None
                target = self._online_target(proj, config_path, net, body)
                try:
                    return conn.call(*target, fn, net)
                except diag.DiagError as e:
                    raise ApiError(502, str(e), kind=e.kind)
            return {"jobs": self._jobs(folder, conn, bus_call)}

        # The network the page picked; sent only to a bridge that runs several.
        network = body.get("network") if isinstance(body.get("network"), str) and body.get("network") else None
        hostname, port, token = self._online_target(proj, config_path, network, body)
        host = str(hostname) if isinstance(hostname, online.AdapterTarget) else proj.get("host")
        local = isinstance(hostname, online.AdapterTarget)
        remote_target = isinstance(hostname, online.RemoteAdapterTarget)

        def call(fn):
            def run(c):
                if local:
                    c.force = body.get("force") is True  # LSS while another master is active, after asking
                return fn(c)
            try:
                return conn.call(hostname, port, token, run, network)
            except diag.DiagError as e:
                # `force`: a change to a running node the page may send again with force after asking.
                raise ApiError(422 if e.kind in ("refused", "usage", "busy", "bitrate") else 502, str(e), kind=e.kind,
                               force=diag.needs_force(e))

        # A change to an OPERATIONAL node (an SDO write, NMT but START) and a
        # scan while a node is OPERATIONAL need force; the page sends it
        # after asking. Only then is the field sent.
        forced = {"force": True} if body.get("force") is True else {}

        def picked(c):
            """The page's network, or the first one when the runtime does not
            run it (a picker that starts on a tab the runtime does not know):
            for status and scan, which only read."""
            names = [n.get("name") for n in c.networks]
            if c.several() and c.network not in names:
                c.network = names[0]
            return c.network if c.several() else None

        def node_arg(key="node"):
            try:
                v = int(body.get(key))
            except (TypeError, ValueError):
                raise ApiError(400, "%s must be a node ID" % key)
            if not 1 <= v <= 127:
                raise ApiError(400, "%s must be 1-127" % key)
            return v

        def object_arg():
            try:
                index, sub = int(str(body.get("index")), 0), int(str(body.get("subindex", 0)), 0)
            except ValueError:
                raise ApiError(400, "index and subindex must be numbers")
            if not (0 <= index <= 0xFFFF and 0 <= sub <= 0xFF):
                raise ApiError(400, "index must be 0x0000-0xFFFF and subindex 0-255")
            return index, sub

        if route == ("POST", "/api/online/pdo_layout"):
            # The trace's PDO layout of a node, read from the device (canopen-configurator:
            # "Automatic PDO layout reads in Commission a device"). Reads only.
            node = node_arg()
            client = params.Client(conn, hostname, port, token, network, False)
            try:
                values, dtype, failed = params.pdo_values(client, node)
            except diag.DiagError as e:
                raise ApiError(422 if e.kind == "refused" else 502, str(e), kind=e.kind)
            # Each PDO with a valid COB-ID and whether its frames now decode,
            # with why not (canopen-configurator: "Result of a PDO layout read").
            pdos = tracing.read_result(node, values, dtype, failed)
            ws = self.server.traces.get(folder)
            ws.add_device_read(node, values, dtype, pdos)
            return {"node": node, "pdos": pdos, "device_type": dtype}
        if route in params.ROUTES:
            node = None if route[1].endswith("/job") else node_arg()
            watch = self.server.watch
            if route[1].endswith("/pdo_test_start"):
                watch["pdo_test"] = node
            elif route[1].endswith("/pdo_test_stop"):
                watch["pdo_test"] = None
            elif route[1].endswith("/sync_start"):
                watch["sync"] = True
            elif route[1].endswith("/sync_stop"):
                watch["sync"] = False
            # force: the page asked about an OPERATIONAL node first.
            client = params.Client(conn, hostname, port, token, network, body.get("force") is True)
            try:
                return params.handle(route, body, s, conn, self.server.jobs, client, node, settings.eds_library,
                                     host)
            except params.Refused as e:
                raise ApiError(e.status, str(e), force=str(e).rstrip().endswith(diag.FORCE_NEEDED))
            except diag.DiagError as e:
                raise ApiError(422 if e.kind == "refused" else 502, str(e), kind=e.kind, force=diag.needs_force(e))
        if route == ("POST", "/api/online/status"):
            try:
                # The hello from the same client: conn.info is None when another
                # request closed the connection in between.
                used, st, info = call(lambda c: (picked(c), c.status(), c.info))
            except ApiError as e:
                if e.status != 502:
                    raise
                # Not answering: said in the answer, not as an HTTP error on every poll.
                return dict(e.body, reachable=False)
            prints = online.fingerprints(config_path)
            same = st.get("config_sha256") in prints
            out = {"hello": info, "status": st, "networks": (info or {}).get("networks") or [],
                   "network": used, "config": "none" if not prints else ("same" if same else "different")}
            # The path the connection took (LAN, internet direct or relayed)
            # and its round trip; the background pairing's line, once.
            out.update(conn.link_info())
            out["recent"] = self._remember_recent(settings, folder, proj, local, remote_target)
            if remote_target:
                out["remote"] = host
            if local:
                out["config"] = "local"
                out["config_bitrate"] = self._config_bitrate(config_path, network)
            if st.get("protocol") == "j1939" and isinstance((st.get("j1939") or {}).get("dm"), dict):
                # The Faults panel names codes by the SPN attributes of the network's DBC.
                out["spn_names"] = {str(k): v for k, v in self._spn_names(config_path, canopen_dir, used).items()}
            out["conn"] = connection_summary(out, host, local)
            return out
        if route == ("POST", "/api/online/emcy"):
            node = node_arg()
            res = call(lambda c: c.emcy(node))
            for e in res.get("emcy") or []:
                e["class"] = diag.emcy_class(e.get("code", 0))
            return res
        if route in (("POST", "/api/online/error_field"), ("POST", "/api/online/error_field_clear")):
            # The device's error history (0x1003) through the manual SDO read
            # and write, so the bridge's guards apply to the clear: changes
            # allowed, and force (after the page asked) on an OPERATIONAL node.
            from .. import errorfield
            node = node_arg()
            if route[1].endswith("clear"):
                return call(lambda c: (errorfield.clear(c, node, force=body.get("force") is True),
                                       errorfield.read(c, node))[1])
            return call(lambda c: errorfield.read(c, node))
        if route in (("POST", "/api/online/sdo_read"), ("POST", "/api/online/sdo_write")):
            node = node_arg()
            index, sub = object_arg()
            timeout_ms = body.get("timeout_ms") if isinstance(body.get("timeout_ms"), int) else 1000
            if route[1].endswith("write"):
                try:
                    data = diag.encode(body.get("type"), body.get("value", ""))
                except ValueError as e:
                    raise ApiError(422, str(e))
                res = call(lambda c: c.request("sdo_write", timeout=c.timeout + timeout_ms / 1000.0, node=node,
                                               index=index, subindex=sub, data=diag.hex_bytes(data),
                                               timeout_ms=timeout_ms, **forced))
                if res.get("success"):
                    res["data"] = diag.hex_bytes(data)  # what was written, for Keep in configuration
            else:
                res = call(lambda c: c.sdo_read(node, index, sub, timeout_ms))
                if res.get("success"):
                    res["decoded"] = diag.decode(body.get("type"), diag.parse_hex(res["data"]) if res.get("data")
                                                 else b"")
            if not res.get("success"):
                res["reason"] = diag.sdo_failure(res)
                if res.get("abort_code") is not None:
                    res["abort_text"] = diag.abort_text(res["abort_code"])
            return res
        if route == ("POST", "/api/online/identify"):
            # A heard node's identity for the Nodes table: a few manual SDO
            # reads, no force or allow_changes (identity.py).
            from .. import identity
            node = node_arg()
            res = call(lambda c: identity.read(c, node))
            folders = [("project", canopen_dir), ("library", settings.eds_library)]
            res["eds_matches"] = self.server.eds_index.matches(folders, res.get("vendor_id"), res.get("product_code"),
                                                               res.get("revision_number"))
            return res
        if route == ("POST", "/api/online/nmt"):
            node, command = node_arg(), body.get("command")
            if command not in diag.NMT_COMMANDS:
                raise ApiError(400, "command must be one of " + ", ".join(diag.NMT_COMMANDS))
            return call(lambda c: c.request("nmt", node=node, command=command,
                                            **(forced if command != "start" else {})))
        if route == ("POST", "/api/online/lss_find"):
            vendor, product = body.get("vendor_id"), body.get("product_code")
            known = isinstance(vendor, int) and isinstance(product, int)
            if body.get("start"):
                self.server.watch["lss_find"] = True
            res = call(lambda c: c.lss_find(bool(body.get("start")), vendor if known else None,
                                            product if known else None))
            dev = res.get("device")
            if isinstance(dev, dict):
                folders = [("project", canopen_dir), ("library", settings.eds_library)]
                dev["eds_matches"] = self.server.eds_index.matches(folders, dev.get("vendor_id"),
                                                                   dev.get("product_code"), dev.get("revision_number"))
            return res
        if route in (("POST", "/api/online/lss_set_id"), ("POST", "/api/online/lss_set_bitrate")):
            addr = body.get("address") if isinstance(body.get("address"), dict) else {}
            try:
                address = tuple(int(addr[k]) for k in diag.LSS_KEYS)
            except (KeyError, TypeError, ValueError):
                raise ApiError(400, "address must have " + ", ".join(diag.LSS_KEYS))
            store = body.get("store") is True
            if route[1].endswith("set_id"):
                node = node_arg()
                return call(lambda c: c.lss_set_id(address, node, store))
            kbit = body.get("bitrate_kbit")
            if kbit not in diag.LSS_BITRATES:
                raise ApiError(400, "The bit rate must be one of these kbit/s values: " + ", ".join(str(b) for b in diag.LSS_BITRATES))
            return call(lambda c: c.lss_set_bitrate(address, kbit, store))
        if route in SEND_ROUTES:
            return self._send_frames(route, body, (hostname, port, token), network)
        if route == ("POST", "/api/online/scan_stop"):
            return call(lambda c: c.scan_stop())
        if route == ("POST", "/api/online/scan"):
            start = bool(body.get("start"))
            if start:
                self.server.watch["scan"] = True
            used, res = call(lambda c: (picked(c), c.request("scan", **forced) if start else c.scan(False)))
            res["networks"], res["network"] = (conn.info or {}).get("networks") or [], used
            if res.get("nodes") is not None:
                self._match_scan(s, settings, canopen_dir, res, body.get("config"), used)
            return res
        if route == ("POST", "/api/online/j1939_dm_read"):
            # The previously active codes (DM2) of an ECU, through the PLC's address.
            address = j1939_address(body.get("address"), False)
            timeout_ms = body.get("timeout_ms") if isinstance(body.get("timeout_ms"), int) else 1000
            if not 10 <= timeout_ms <= 10000:
                raise ApiError(400, "timeout_ms must be 10-10000")
            res = call(lambda c: c.request("j1939_dm_read", timeout=c.timeout + timeout_ms / 1000.0,
                                           address=address, timeout_ms=timeout_ms))
            return dm_texts(res)
        if route == ("POST", "/api/online/j1939_dm_clear"):
            # DM3 (previous) or DM11 to an ECU or globally (255). It acts on
            # another ECU: the page asks first, then sends force.
            address = j1939_address(body.get("address"), True)
            previous = body.get("previous") is True
            return call(lambda c: c.request("j1939_dm_clear", timeout=c.timeout + 1.0, address=address,
                                            previous=previous, **forced))
        raise ApiError(404, "no such API: %s %s" % route)

    def _spn_names(self, config_path, canopen_dir, network):
        """{SPN: signal name} from the SPN attributes of the DBC the saved
        config names for J1939 network `network` (None: the first J1939
        network); cached by the file's time. Empty when there is none."""
        try:
            with open(config_path, encoding="utf-8") as f:
                cfg = json.load(f)
            nets = [n for n in contract.networks(cfg) if n["role"] == "j1939"]
            net = next((n for n in nets if network is None or n.get("name") == network), None)
            dbc = os.path.basename(str(((net or {}).get("j1939") or {}).get("dbc") or ""))
            reader = getattr(j1939_dbc, "spn_names", None)
            if not dbc or reader is None:
                return {}
            path = os.path.join(canopen_dir, dbc)
            key = (path, os.path.getmtime(path))
        except (OSError, ValueError, AttributeError, TypeError):
            return {}
        cache = self.server.spn_cache
        if cache.get("key") != key:
            try:
                names = reader(path)
            except (OSError, j1939_dbc.ImportFailed):
                names = {}
            cache.update(key=key, names=names if isinstance(names, dict) else {})
        return cache["names"]

    def _paired_pcs(self, route, proj, body):
        """/api/online/paired_pcs and remove_pc: the PCs paired with the
        runtime of the online access settings (its remembered entry), over the
        remote link's manage stream with this PC's token. Removing this PC
        itself needs no token."""
        from ..link import pc as linkpc
        from ..link.protocol import LinkError
        host, token = proj.get("host"), proj.get("token")
        if not host:
            raise ApiError(409, "enter the runtime host for online access", need="host")
        if not token:
            raise ApiError(409, "enter the access token for online access", need="token")
        entry = linkpc.find(host)
        if not entry or not entry.get("id"):
            raise ApiError(409, "%s has no link ID yet: connect to it once on its local network"
                           % (entry["name"] if entry else host), need="link")
        try:
            if route[1].endswith("remove_pc"):
                pc_id = body.get("id")
                if not isinstance(pc_id, str) or not pc_id:
                    raise ApiError(400, "id must be a paired PC's link ID")
                try:
                    mine = linkpc.available() and pc_id == linkpc.my_id()
                except Exception:  # no key yet, or iroh refuses it
                    mine = False
                if mine:
                    return {"removed": linkpc.unpair(entry), "runtime": entry["name"]}
                return {"removed": linkpc.remove_pc(entry, token, pc_id), "runtime": entry["name"]}
            pcs, me = linkpc.paired_pcs(entry, token)
        except LinkError as e:
            raise ApiError(422 if e.kind in ("token", "refused", "unpaired", "unavailable") else 502, str(e),
                           kind=e.kind)
        return {"runtime": entry["name"], "pcs": pcs, "you": me}

    def _config_bitrate(self, config_path, network):
        """The saved config's bit rate of `network` in bit/s, or None."""
        from ..localbus import configinfo
        if not os.path.isfile(config_path):
            return None
        try:
            return configinfo.load(config_path, network)[0]
        except (OSError, ValueError):
            return None

    def _leave_commission(self, s):
        """Leaving Commission a device closes its adapter connection and the jobs on it."""
        if s.commission:
            self.server.traces.stop_all()
            self.server.sender.close()
            self.server.connection.close()
            self.server.adapter_allow = False

    def _online_target(self, proj, config_path, network, body):
        """(host, port, token) for the kept-open connection: the runtime of the
        online access settings, or in Commission a device an
        online.AdapterTarget for the USB adapter on this PC (no token), also
        in a CODESYS project; with the adapter on another machine picked
        (remote_adapter), an online.RemoteAdapterTarget, also with a config."""
        if proj.get("remote_adapter"):
            from ..localbus import configinfo, remote
            key = proj.get("remote_host")
            if not key:
                raise ApiError(409, "enter the adapter server's host", need="remote_host")
            token = online.Settings(config_dir()).adapter_token(key)
            if not token:
                raise ApiError(409, "enter the adapter server's token", need="remote_token")
            nodes = {}
            if os.path.isfile(config_path):
                try:
                    nodes = configinfo.load(config_path, network)[1]
                except (OSError, ValueError):
                    pass
            host, port = remote.parse(key)
            return online.RemoteAdapterTarget(host, port, token, self.server.adapter_allow, nodes, network), None, None
        if self.server.session.adapter_online():
            from ..localbus import configinfo
            adapter = proj.get("adapter")
            if not adapter:
                raise ApiError(409, "pick the USB adapter for online access", need="adapter")
            nodes, listen_only = {}, False
            if os.path.isfile(config_path):
                try:
                    nodes = configinfo.load(config_path, network)[1]
                    listen_only = configinfo.load_listen_only(config_path, network)
                except (OSError, ValueError):
                    pass
            kbit = proj.get("adapter_bitrate")
            if not isinstance(kbit, int):
                raise ApiError(409, "pick the bus's bit rate for the USB adapter", need="adapter")
            return online.AdapterTarget(adapter, kbit * 1000, self.server.adapter_allow, nodes, network,
                                        proj.get("check_node"), listen_only), None, None
        host, token = proj.get("host"), proj.get("token")
        if not host:
            raise ApiError(409, "enter the runtime host for online access", need="host")
        if not token:
            raise ApiError(409, "enter the access token for online access", need="token")
        try:
            hostname, port = diag.parse_runtime(host)
        except ValueError as e:
            raise ApiError(422, str(e))
        if ":" not in host.rsplit("]", 1)[-1] and isinstance(body.get("port"), int):
            port = body["port"]  # the diagnostics port of the config, when the host gives none
        return hostname, port, token

    def _jobs(self, folder, conn, call):
        """The status bar's job list: what runs for this page, with its
        progress and the request that stops it. Jobs on the bus are asked for
        their progress only while the connection is open and one was started."""
        out = []
        job = self.server.jobs.get()
        if job is not None and job.state == "running":
            out.append({"id": "params-%d" % job.id, "kind": job.kind, "node": job.node,
                        "label": "%s node %s" % (JOB_LABELS.get(job.kind, job.kind), job.node),
                        "done": job.done, "total": job.total, "started": job.started,
                        "stop": {"path": "/api/online/job", "body": {"job": job.id, "cancel": True}}
                        if not job.cancel else None,
                        "confirm": "Cancel %s of node %s? What was written stays written." % (
                            JOB_LABELS.get(job.kind, job.kind).lower(), job.node)
                        if job.kind in ("restore", "configure") else None})
        ws = self.server.traces.get(folder)
        if ws.recording():
            st = ws.state()
            out.append({"id": "trace", "kind": "trace", "label": "Trace recording", "done": st["frames"], "total": None,
                        "unit": "frames", "stop": {"path": "/api/trace/stop", "body": {}}, "confirm": None})
        with self.server.sender.lock:
            sends = list(self.server.sender.jobs.values())
        for j in sends:
            out.append({"id": "send-%s-%s" % (j["network"], j["job"]), "kind": "send",
                        "label": "Cyclic send 0x%X every %s ms" % (j["id"], j.get("period_ms")),
                        "done": j.get("sent"), "total": j.get("count"), "unit": "frames",
                        "stop": {"path": "/api/online/send_stop", "body": {"job": j["job"], "network": j["network"]}},
                        "confirm": None})
        for j in self.server.devices.running_jobs():
            # Install jobs run on the device by themselves: no Cancel here, the device's page has Stop.
            out.append({"id": "device-%s" % j["job"], "kind": "device", "label": "Installing on %s" % j["device"],
                        "done": None, "total": None, "stop": None, "confirm": None, "device": j["device"]})
        watch = self.server.watch
        if not conn.connected:
            watch.update(scan=False, lss_find=False, pdo_test=None, sync=False)
            return out
        try:
            if watch["scan"]:
                r = call(lambda c: c.scan(False))
                if r.get("running"):
                    out.append({"id": "scan", "kind": "scan", "label": "Scan the bus", "done": r.get("done"),
                                "total": r.get("total"), "unit": "node IDs",
                                "stop": {"path": "/api/online/scan_stop", "body": {}}, "confirm": None})
                else:
                    watch["scan"] = False
            if watch["lss_find"]:
                r = call(lambda c: c.lss_find(False))
                if r.get("running"):
                    # The search ends by itself, after about 15 seconds at most.
                    out.append({"id": "lss_find", "kind": "lss_find", "label": "LSS: finding a device without node ID",
                                "done": round(r.get("seconds") or 0), "total": None, "unit": "s",
                                "stop": None, "confirm": None})
                else:
                    watch["lss_find"] = False
            if watch["pdo_test"] is not None:
                node = watch["pdo_test"]
                r = call(lambda c: c.request("pdo_test_status", node=node))
                if r.get("running"):
                    out.append({"id": "pdo_test", "kind": "pdo_test", "label": "PDO test node %d" % node,
                                "done": None, "total": None, "stop": {"path": "/api/online/pdo_test_stop",
                                                                      "body": {"node": node}}, "confirm": None})
                else:
                    watch["pdo_test"] = None
                if (r.get("sync") or {}).get("running"):
                    watch["sync"] = True
            if watch["sync"]:
                out.append({"id": "sync", "kind": "sync", "label": "SYNC from this PC", "done": None, "total": None,
                            "stop": {"path": "/api/online/sync_stop", "body": {}}, "confirm": None})
        except ApiError:
            pass  # the status bar shows what it could learn; the views say what failed
        return out

    def _send_frames(self, route, body, where, network):
        """/api/online/send_frame, send_stop and send_jobs: the Trace view's
        Send panel, through the server's Sender."""
        sender = self.server.sender
        try:
            if route[1].endswith("send_jobs"):
                return sender.poll(where)
            if route[1].endswith("send_stop"):
                job = body.get("job")
                if job is not None and (isinstance(job, bool) or not isinstance(job, int)):
                    raise ApiError(400, "job must be a job number")
                return {"stopped": sender.stop(where, network if job is not None else None, job)}
            return sender.send(where, network, frame_from(body), body.get("force") is True)
        except diag.DiagError as e:
            raise frame_error(e)

    # -- simulation ---------------------------------------------------------
    def _sim(self, route, body):
        """/api/sim/*: the Simulation view. The simulation file of this
        project, and requests to the runtime's simulated devices (online
        access settings) or to a CANopen simulator (address and token kept
        on this PC), through the online view's kept-open connection."""
        # The runtime's simulated devices go through the shared connection (the
        # connection bar's); a CANopen simulator has a connection of its
        # own, so the Simulation view never closes or retargets the runtime's.
        s, conn, simconn = self.server.session, self.server.connection, self.server.sim_connection
        settings = online.Settings(config_dir())
        with s.lock:
            self._need_open(s)
            folder = s.folder

        if route == ("GET", "/api/sim/settings"):
            return simulation.settings_view(settings.project(folder))
        if route == ("POST", "/api/sim/settings"):
            try:
                values = simulation.clean_settings(body)
            except ValueError as e:
                raise ApiError(422, str(e))
            if any(k in values for k in ("sim_target", "sim_address", "sim_token")):
                simconn.close()
            return simulation.settings_view(settings.update_project(folder, **values))
        if route == ("POST", "/api/sim/close"):
            simconn.close()
            return {"closed": True}
        if route == ("POST", "/api/sim/check"):
            problems = simulation.check(body.get("doc"))
            if not problems:
                with s.lock:
                    problems = s.sim_problems(body.get("doc"))
            return {"problems": problems}
        if route == ("POST", "/api/sim/save"):
            with s.lock:
                out = s.save_simulation(body.get("doc"), bool(body.get("overwrite")))
                out["state"] = s.state()
            return out

        proj = settings.project(folder)

        def where():
            # A simulated node's Status tab in Commission: always the runtime,
            # whichever target the Simulation tool has.
            target = dict(proj, sim_target="runtime") if body.get("target") == "runtime" else proj
            try:
                return simulation.target(target, body.get("port"))
            except LookupError as e:
                need = str(e).strip("'")
                raise ApiError(409, "enter the runtime host for online access" if need == "host"
                               else "enter the access token for online access", need=need)
            except ValueError as e:
                raise ApiError(422, str(e))

        # The network the page picked; sent only to a bridge that runs several.
        network = body.get("network") if isinstance(body.get("network"), str) and body.get("network") else None

        def call(fn):
            host, port, token, kind = where()
            try:
                return (simconn if kind == "simulator" else conn).call(host, port, token, fn, network), kind
            except diag.DiagError as e:
                if kind == "simulator" and e.kind == "closed":
                    e = simulation.simclient.closed_error(host, port)
                raise ApiError(422 if e.kind == "refused" else 502, str(e), kind=e.kind)

        def hello(kind):
            info = dict((simconn if kind == "simulator" else conn).info or {})
            standalone = bool(info.get("simulator"))
            # The CANopen simulator takes changes from anyone with its token.
            return {"hello": info, "target": kind, "standalone": standalone,
                    "allow_changes": True if standalone else bool(info.get("allow_changes"))}

        if route == ("POST", "/api/sim/check_expr"):
            expr = body.get("expr")
            if not isinstance(expr, str) or not expr.strip():
                raise ApiError(400, "expr must be the expression text")
            node = body.get("node")
            if body.get("online"):
                try:
                    res, kind = call(lambda c: c.request("sim_check_expr", node=node, expr=expr))
                    return simulation.remote_result(res, kind)
                except ApiError:
                    pass  # not reachable, or the node is not simulated there: checked here instead
            return self._check_expr_offline(s, expr, node, body.get("doc"), network)
        if route == ("POST", "/api/sim/poll"):
            node = body.get("node")
            objects = [o for o in body.get("objects") or [] if isinstance(o, str)]

            def poll(c):
                status = c.request("sim_status")
                values, pdo_error = [], None
                if node not in (None, ""):
                    try:
                        values = c.request("sim_get", node=node, pdo=True).get("values") or []
                    except diag.DiagError as e:
                        if e.kind != "refused":
                            raise
                        pdo_error = str(e)
                    seen = {(v.get("object") or "").upper() for v in values if isinstance(v, dict)}
                    items = [{"node": node, "object": o} for o in objects if o.upper() not in seen]
                    if items:
                        values += c.request("sim_get", items=items).get("values") or []
                return {"status": status, "values": values, "pdo_error": pdo_error}

            res, kind = call(poll)
            return dict(hello(kind), **res)
        if route == ("POST", "/api/sim/request"):
            op = body.get("op")
            if op not in simulation.OPS:
                raise ApiError(400, "op must be one of " + ", ".join(simulation.OPS))
            fields = {k: v for k, v in body.items() if k not in ("op", "port", "network", "target")}
            res, kind = call(lambda c: c.request(op, **fields))
            return {"result": res, "target": kind}
        raise ApiError(404, "no such API: %s %s" % route)

    @staticmethod
    def _check_expr_offline(s, expr, node, doc, network=None):
        """An expression checked on this PC (simulation.check_offline), with
        the devices of the config's network (the picked one when there are
        several) and of the draft simulation file's part (`doc`)."""
        with s.lock:
            cfg = s.read_config()[0]
            if isinstance(cfg, dict) and contract.version_of(cfg) != 1:
                try:
                    cfg = contract.network_config(cfg, network)
                except ValueError:
                    cfg = {}
            if not isinstance(doc, dict):
                doc = simulation.read(s.sim_path)["doc"]
                if simulation.version(doc) >= 2:
                    doc = ((doc.get("networks") or {}).get(network or "") or {})
            devices = {}
            for n in cfg.get("nodes") or []:
                if isinstance(n, dict) and isinstance(n.get("eds"), str):
                    try:
                        devices[int(str(n.get("node_id")), 0)] = s.eds_path(n["eds"])
                    except ValueError:
                        pass
            for d in doc.get("extra_devices") or []:
                if isinstance(d, dict) and isinstance(d.get("eds"), str):
                    key = d.get("name") if not d.get("node") else d.get("node")
                    devices[key] = s.eds_path(d["eds"])
            summaries = s.eds_info([p for p in devices.values()])
        objects = {}
        for dev, path in devices.items():
            info = summaries.get(path) or {}
            objects[dev] = {(int(o["index"], 16), o["subindex"]) for o in info.get("objects", [])}
            objects[str(dev)] = objects[dev]

        def has_object(device, obj):
            """Whether a device (None: the expression's own) has an object
            ("0xIIII:S" or (index, subindex))."""
            dev = node if device is None else device
            key = obj if isinstance(obj, tuple) else simulation.parse_object(obj)
            known = objects.get(dev, objects.get(str(dev)))
            return known is None or key in known

        known = set(devices) | {str(d) for d in devices}
        return simulation.check_offline(expr, known, has_object)

    # -- frame lab ----------------------------------------------------------
    def _explain(self, route, body):
        """/api/explain*: the Frame lab's explanations and built frames, from
        the configuration on the page (canopen-configurator: "Frame lab
        view"). Nothing here touches a runtime or a bus."""
        if route[0] != "POST":
            raise ApiError(405, "use POST")
        s = self.server.session
        cfg, eds_paths, names, config_path = body.get("config"), {}, None, None
        with s.lock:
            if s.mode:
                if not isinstance(cfg, dict):
                    cfg = s.read_config()[0]
                eds_paths, names, config_path = s.eds_paths(cfg), tracing.plc_names(s), s.config_path
        if not isinstance(cfg, dict):
            cfg = None
        nets = [n["name"] for n in contract.networks(cfg) if n["role"] == "master"] if cfg else []
        network = body.get("network") if isinstance(body.get("network"), str) and body.get("network") else None
        if network is None and cfg and contract.version_of(cfg) != 1 and nets:
            network = nets[0]
        warnings = []
        try:
            if s.commission:  # no config: the Nodes tab's EDS files
                with s.lock:
                    dec = tracing.commission_decoder(body.get("eds"), s.eds_path)
            else:
                dec = tracing.decoder_for(cfg, config_path, eds_paths, names, network) if cfg else explain_mod.Decoder()
            warnings += dec.warnings
        except Exception as e:  # noqa: BLE001 - an unfinished configuration still explains frames
            dec = explain_mod.Decoder()
            warnings.append("the configuration cannot be read for names and PDO mappings: %s" % e)
        bitrate = _bitrate_arg(body.get("bitrate"))
        assumed = bitrate is None
        if bitrate is None and cfg:
            bitrate = explain_mod.bitrate_of(cfg, network)
        info = {"networks": nets, "network": network, "warnings": warnings,
                "bitrate": bitrate, "bitrate_from": "chosen" if not assumed else ("config" if bitrate else None)}

        def model(f):
            m = explain_mod.explain(f, dec, bitrate)
            m["candump"] = explain_mod.candump_text(f)
            return m

        if route == ("POST", "/api/explain"):
            text = body.get("frame")
            if not isinstance(text, str):
                raise ApiError(400, "frame must be a frame in candump syntax (ID#DATA)")
            try:
                f = explain_mod.parse_frame(text)
                return dict(info, explanation=model(f))
            except ValueError as e:
                raise ApiError(422, str(e), field="frame")
        what = body.get("what")
        try:
            if what == "examples":
                groups = plain_examples(dec) if getattr(dec, "protocol", "canopen") == "none" else framebuild.examples(dec)
                return dict(info, examples=[{"group": g["group"], "label": g["label"],
                                             "frames": [{"label": x["label"], "frame": explain_mod.candump_text(x["frame"])}
                                                        for x in g["frames"]]} for g in groups])
            if what == "sdo":
                built = framebuild.sdo(dec, body.get("node"), body.get("index"), body.get("subindex", 0),
                                       body.get("op") or "read", body.get("value"), body.get("type") or None,
                                       bool(body.get("segmented")))
            elif what == "pdo":
                values = body.get("values") if isinstance(body.get("values"), dict) else {}
                built = framebuild.pdo(dec, body.get("cob_id"), values)
            elif what == "nmt":
                built = framebuild.nmt(body.get("command") or "start", body.get("node") or 0)
            elif what == "heartbeat":
                built = framebuild.heartbeat(body.get("node"), body.get("state") or "operational")
            elif what == "emcy":
                built = framebuild.emcy(body.get("node"), body.get("code", 0x1000), body.get("register", 1),
                                        body.get("manufacturer") or "")
            elif what == "pdos":
                return dict(info, pdos=[{"cob_id": cob, "id": "%03X" % cob, "name": p.name, "node": p.node,
                                         "direction": "TPDO" if p.tx else "RPDO",
                                         "signals": [dict(key=sg[0], name=sg[1], bits=sg[3], signed=bool(sg[4]),
                                                          type=sg[6], **{k: v for k, v in (p.info[k2] if k2 < len(p.info) else {}).items()
                                                                         if k in ("location", "variables", "index", "subindex")})
                                                     for k2, sg in enumerate(p.signals)]}
                                        for cob, p in sorted(dec.pdos.items())],
                            nodes=[{"node": n, "label": dec.node_label(n)} for n in sorted(dec.node_names)])
            else:
                raise ApiError(400, "what must be examples, pdos, sdo, pdo, nmt, heartbeat or emcy")
        except framebuild.BuildError as e:
            raise ApiError(422, str(e), field=e.field)
        return dict(info, frames=[{"label": x["label"], "frame": explain_mod.candump_text(x["frame"]),
                                   "explanation": model(x["frame"])} for x in built])

    # -- trace --------------------------------------------------------------
    def _trace_decoding(self, route, body, settings, folder, ws, decoder):
        """/api/trace/decoding: the DBC files of the trace and each node's EDS
        and PDO layout source (canopen-configurator: "Decoding panel in the
        Trace view"). POST with an action changes the DBC files (add by path
        or upload, remove, order) or, with "refresh", decodes the trace again
        after the nodes' EDS files changed."""
        paths = tracing.dbc_entries(settings.project(folder))
        if route[0] == "POST" and body.get("action") is not None:
            action = body.get("action")
            if action == "add":
                path = body.get("path")
                if isinstance(path, str) and path.strip():
                    path = os.path.abspath(os.path.expanduser(path.strip()))
                    if not path.lower().endswith(".dbc"):
                        raise ApiError(422, "%s is not a DBC file (the name must end in .dbc)" % path, field="path")
                    if not os.path.isfile(path):
                        raise ApiError(422, "the file %s does not exist" % path, field="path")
                else:
                    try:
                        data = base64.b64decode(body.get("data") or "", validate=True)
                    except ValueError:
                        raise ApiError(400, "data must be base64")
                    if not data:
                        raise ApiError(400, "choose a DBC file")
                    try:
                        path = tracing.save_uploaded_dbc(os.path.join(config_dir(), "dbc"), body.get("name"), data)
                    except tracing.Refused as e:
                        raise ApiError(e.status, str(e))
                _, check = tracing.load_dbc([path])
                if check[0]["error"]:
                    raise ApiError(422, "%s cannot be read as a DBC file: %s" % (os.path.basename(path),
                                                                                  check[0]["error"]))
                if path not in paths:
                    if len(paths) >= tracing.MAX_DBC_FILES:
                        raise ApiError(422, "a trace decodes with at most %d DBC files; remove one first"
                                       % tracing.MAX_DBC_FILES)
                    paths.append(path)
            elif action == "remove":
                paths = [p for p in paths if p != body.get("path")]
            elif action == "order":
                order = body.get("paths")
                if not isinstance(order, list) or sorted(order) != sorted(paths):
                    raise ApiError(400, "paths must list the trace's DBC files in their new order")
                paths = list(order)
            elif action != "refresh":
                raise ApiError(400, "action must be add, remove, order or refresh")
            if action != "refresh":
                settings.update_project(folder, trace_dbc=paths)
            ws.redecode(decoder())
        _, view = tracing.load_dbc(paths)
        return tracing.decoding_view(ws.decoding(), view)

    def _trace(self, route, body):
        """/api/trace/*: the Trace view's recording or opened file for this
        project folder (canopen-configurator: "Trace view")."""
        s = self.server.session
        with s.lock:
            self._need_open(s)
            folder, config_path, canopen_dir = s.folder, s.config_path, s.canopen_dir
            names = tracing.plc_names(s)
        ws = self.server.traces.get(folder)
        base_name = os.path.basename(folder.rstrip(os.sep)) or "canworks"
        traces_dir = os.path.join(config_dir(), "traces")

        # A trace records and decodes one network (canopen-bus-trace).
        network = body.get("network") if isinstance(body.get("network"), str) and body.get("network") else None

        settings = online.Settings(config_dir())

        def decoder():
            if s.commission:
                with s.lock:
                    dec = tracing.commission_decoder(body.get("eds"), s.eds_path)
            else:
                cfg = body.get("config")
                with s.lock:
                    if not isinstance(cfg, dict):
                        cfg = s.read_config()[0]
                    eds_paths = s.eds_paths(cfg)
                dec = tracing.decoder_for(cfg, config_path, eds_paths, names, network)
            # The DBC files added to the trace (canopen-bus-trace: "DBC files in a trace").
            files, _ = tracing.load_dbc(tracing.dbc_entries(settings.project(folder)))
            if files:
                dec.attach_dbc(files)
            return dec

        def time_range():
            return tracing._opt_time(body.get("start_us"), "start_us"), tracing._opt_time(body.get("end_us"), "end_us")

        def state():
            return dict(ws.state(), traces_dir=traces_dir)

        if route == ("GET", "/api/trace/state"):
            return state()
        if route[1] == "/api/trace/decoding":
            return self._trace_decoding(route, body, settings, folder, ws, decoder)
        if route[1].startswith(("/api/trace/transmit", "/api/trace/prefs")):
            return self._transmit(route, body, folder, network)
        if route == ("POST", "/api/trace/ids/reference"):
            at = body.get("at")
            if at not in (None, "now"):
                at = tracing._int(at, "at", 0)
            ws.set_reference(at)
            return ws.ids(None, tracing.DisplayFilter(body.get("filter")))
        if route == ("POST", "/api/trace/frames"):
            flt = tracing.DisplayFilter(body.get("filter"))
            at = tracing._opt_time(body.get("at_us"), "at_us")
            return ws.rows(tracing._int(body.get("offset", 0), "offset", 0),
                           tracing._int(body.get("count", 200), "count", 1), flt, at)
        if route == ("POST", "/api/trace/ids"):
            since = body.get("since") if isinstance(body.get("since"), dict) else None
            return ws.ids(since, tracing.DisplayFilter(body.get("filter")))
        if route == ("POST", "/api/trace/series"):
            keys = [k for k in body.get("keys") or [] if isinstance(k, str)]
            start, end = time_range()
            points = tracing._int(body.get("points") or 2000, "points", 10, 20000)
            return ws.series(keys, start, end, points)
        if route == ("POST", "/api/trace/trigger"):
            spec = tracing.check_trigger(body.get("trigger"))
            if spec and spec.get("autosave") and spec["autosave"].get("folder"):
                spec["autosave"]["folder"] = tracing.check_folder(spec["autosave"]["folder"], canopen_dir)
            if spec and ws.recording():
                try:
                    triggers_mod.resolve_signals(spec, ws.session.decoder.signal_keys())
                except triggers_mod.TriggerError as e:
                    raise ApiError(422, str(e))
            ws.set_trigger(spec)
            return state()
        if route == ("POST", "/api/trace/stop"):
            ws.stop()
            return state()
        if route == ("POST", "/api/trace/clear"):
            ws.clear()
            return state()
        if route == ("POST", "/api/trace/start"):
            filters = tracing.capture_filters(body.get("filters"))
            spec = None
            if "trigger" in body:
                spec = tracing.check_trigger(body.get("trigger")) or {}
                if spec and spec.get("autosave") and spec["autosave"].get("folder"):
                    spec["autosave"]["folder"] = tracing.check_folder(spec["autosave"]["folder"], canopen_dir)
            proj = online.Settings(config_dir()).project(folder)
            on_adapter = s.adapter_online() or bool(proj.get("remote_adapter"))
            if on_adapter and not self.server.connection.connected:
                raise ApiError(409, "connect to the %s with Connect… in the connection bar to record a trace; opening trace files "
                                    "works without it" % ("adapter server" if proj.get("remote_adapter")
                                                          else "USB adapter"), need="online")
            if not on_adapter and (not proj.get("host") or not proj.get("token")):
                raise ApiError(409, "connect to the runtime with Connect… in the connection bar to record a trace "
                                    "(online access is set in Configure → Project); opening trace files works without it",
                               need="online")
            hostname, port, token = self._online_target(proj, s.config_path, network, body)
            connect = tracing.connector(hostname, port, token, network=network)
            adapter = hasattr(hostname, "client")
            try:  # a wrong host, token or an old bridge is said at once instead of retried
                c = connect()
                try:
                    c.trace_stop()
                finally:
                    c.close()
            except diag.DiagError as e:
                if e.kind == "refused" and "unknown op" in str(e):
                    raise ApiError(422, recorder_mod.TOO_OLD, kind="too_old")
                raise ApiError(422 if e.kind == "refused" else 502, str(e), kind=e.kind)
            dec = decoder()
            if s.commission:
                ws.apply_device_reads(dec)
            if spec or (spec is None and ws.trigger):
                try:
                    triggers_mod.resolve_signals(spec or ws.trigger, dec.signal_keys())
                except triggers_mod.TriggerError as e:
                    raise ApiError(422, str(e))
            ws.start(connect, dec, filters, bool(body.get("error_frames")), spec, traces_dir, base_name, network,
                     continue_=bool(body.get("continue")), ended=self._trace_ended(adapter),
                     connection="adapter" if adapter else "runtime",
                     adapter_host=proj.get("remote_host") if adapter and proj.get("remote_adapter") else None)
            return state()
        if route == ("POST", "/api/trace/open"):
            path, name = body.get("path"), body.get("name") or "trace"
            try:
                if isinstance(path, str) and path:
                    trace = formats_mod.read_file(path)
                    name = os.path.basename(path)
                else:
                    if "raw" in body:
                        data = body["raw"]
                    else:
                        try:
                            data = base64.b64decode(body.get("data") or "", validate=True)
                        except ValueError:
                            raise ApiError(400, "data must be base64")
                    trace = formats_mod.read(data, name)
                    trace.meta.setdefault("source", name)
            except formats_mod.FormatError as e:
                raise ApiError(422, str(e))
            except OSError as e:
                raise ApiError(422, "%s cannot be read: %s" % (path, e.strerror or e))
            ws.open(trace, name, decoder(), network)
            return state()
        if route == ("POST", "/api/trace/explain"):
            seq = tracing._int(body.get("seq"), "seq", 0)
            with s.lock:
                fallback = explain_mod.bitrate_of(s.read_config()[0], ws.network)
            return ws.explain(seq, _bitrate_arg(body.get("bitrate")), fallback)
        if route == ("POST", "/api/trace/sequence"):
            kind = body.get("kind")
            node = body.get("node")
            node = None if node in (None, "", 0) else tracing._int(node, "node", 1, 127)
            n = body.get("n")
            if n != "slowest" and n is not None:
                n = tracing._int(n, "n", 0)
            expected = None
            if kind == "boot":
                with s.lock:
                    cfg = s.read_config()[0]
                    eds_paths = s.eds_paths(cfg)
                expected = sequences_mod.expected_writes(cfg, config_path, ws.network, eds_paths)
            at = body.get("at")
            at = None if at is None else tracing._int(at, "at", 0)
            return ws.sequence(kind, n, node, expected, at)
        if route == ("POST", "/api/trace/export"):
            start, end = time_range()
            fmt = body.get("format") or "pcapng"
            return tracing.encode_export(ws, fmt, start, end, body.get("keys"), base_name + "-trace")
        if route == ("POST", "/api/trace/save"):
            start, end = time_range()
            fmt = body.get("format") or "pcapng"
            if fmt not in formats_mod.FORMATS and fmt not in [v[0] for v in formats_mod.FORMATS.values()]:
                raise ApiError(400, "format must be one of " + ", ".join(sorted(formats_mod.FORMATS)))
            target = tracing.check_folder(body.get("folder") or traces_dir, canopen_dir, exists=bool(body.get("folder")))
            fid = formats_mod.format_of("x", fmt)
            ext = next(e for e, (f, _) in formats_mod.FORMATS.items() if f == fid)
            part, dec = ws.part(start, end)
            path = os.path.join(target, triggers_mod.autosave_name(base_name, part.start_us or 0, ext))
            try:
                formats_mod.write_file(part, path, fid, dec if fid == "csv" else None)
            except OSError as e:
                raise ApiError(422, "cannot save to %s: %s" % (target, e.strerror or e))
            return {"path": path, "frames": len(part)}
        raise ApiError(404, "no such API: %s %s" % route)

    def _trace_ended(self, adapter):
        """The recording's check for the page's connection: an adapter
        connection closed by Disconnect (or after the bus ended it) ends the
        recording; a runtime connection is the recorder's own and ends when
        the runtime stops answering."""
        if not adapter:
            return None
        conn = self.server.connection
        return lambda: None if conn.connected else "disconnected"

    def _transmit(self, route, body, folder, network):
        """/api/trace/transmit*, /api/trace/prefs: the transmit list of this
        folder and network, list files and the trace view's settings, kept on
        this PC (canopen-configurator: "Transmit list storage and files")."""
        store = transmit.Store(config_dir())
        try:
            if route == ("GET", "/api/trace/prefs"):
                return store.prefs()
            if route == ("POST", "/api/trace/prefs"):
                return store.set_prefs(body.get("prefs") if isinstance(body.get("prefs"), dict) else body)
            if route == ("POST", "/api/trace/transmit"):
                if "frames" in body:
                    return {"network": network, "frames": store.set_rows(folder, network, body["frames"])}
                return {"network": network, "frames": store.rows(folder, network)}
            if route == ("POST", "/api/trace/transmit/check"):
                return transmit.check_row(body.get("frame"))
            if route == ("POST", "/api/trace/transmit/dump"):
                name = "%s.transmit.json" % (network or os.path.basename(folder.rstrip(os.sep)) or "canworks")
                return {"name": name, "text": transmit.dump_file(network, body.get("frames") or [])}
            if route == ("POST", "/api/trace/transmit/load"):
                net, rows = transmit.load_file(body.get("text") or "")
                return {"network": net, "frames": rows, "other_network": bool(net and network and net != network)}
        except transmit.Invalid as e:
            raise ApiError(422, str(e))
        raise ApiError(404, "no such API: %s %s" % route)

    def _remember_recent(self, settings, folder, proj, local, remote=False):
        """Puts the connection that just answered first in the recent
        connections of this folder (the Nodes table's one-click list)."""
        if remote:
            entry = online.recent_entry(proj.get("remote_host"), remote=True)
        elif local:
            entry = online.recent_entry(proj.get("adapter"), proj.get("adapter_bitrate"), proj.get("check_node"))
        else:
            mem = online.remembered_view(proj.get("host"))
            entry = online.recent_entry(proj.get("host"), name=(mem or {}).get("name"))
        recent = online.add_recent(proj.get("recent"), entry)
        if recent is None:
            return [r for r in proj.get("recent") or [] if isinstance(r, dict)]
        settings.update_project(folder, recent=recent)
        return recent

    def _match_scan(self, s, settings, canopen_dir, res, cfg, network=None):
        """Adds to each scanned device the EDS files that match it and, for a
        configured node of the scanned network, what the config expects and
        how the device compares with it; `missing` lists the configured nodes
        that did not answer."""
        if not isinstance(cfg, dict):
            with s.lock:
                cfg = s.read_config()[0]
        by_id = {}
        try:
            nodes = contract.network_config(cfg, network if contract.version_of(cfg) == 2 else None)["nodes"]
        except (ValueError, TypeError, AttributeError):
            nodes = []  # a network the draft does not have: nothing is configured there
        for n in nodes or []:
            if isinstance(n, dict):
                try:
                    by_id[int(str(n.get("node_id")), 0)] = n
                except ValueError:
                    pass
        folders = [("project", canopen_dir), ("library", settings.eds_library)]
        for d in res["nodes"]:
            n = by_id.get(d.get("node_id"))
            if n is not None:
                with s.lock:
                    path = s.eds_path(n["eds"]) if isinstance(n.get("eds"), str) and n["eds"] else None
                d["config_name"] = n.get("name") or ""
                d["config_eds"] = n.get("eds") or ""
                d["expected"] = online.expected_identity(n, path)
            d["compare"] = online.compare_scanned(d, d.get("expected") or {}, n is not None)
            d["eds_matches"] = self.server.eds_index.matches(folders, d.get("vendor_id"), d.get("product_code"),
                                                             d.get("revision_number"))
        found = {d.get("node_id") for d in res["nodes"]}
        res["missing"] = [{"node_id": i, "name": by_id[i].get("name") or "", "eds": by_id[i].get("eds") or ""}
                          for i in sorted(by_id) if i not in found]

    def _use_eds(self, s, settings, canopen_dir, path, eds_lint=None):
        """An EDS file a scan match offered, made available to the draft: one
        in canworks/ as it is, one from the EDS library imported as an EDS
        import would (kept both under a new name if a different file has its
        name)."""
        if not isinstance(path, str) or not path.lower().endswith(".eds"):
            raise ApiError(400, "path must be an EDS file")
        with s.lock:
            if path in s.pending:  # imported in this session and not saved yet: already in the draft
                return {"name": path, "summary": s.eds_info([path])[path], "converted": False}
        real = os.path.realpath(path)
        if not under(real, (canopen_dir, settings.eds_library)) or not os.path.isfile(real):
            raise ApiError(403, "only EDS files in the project's canopen folder or the EDS library can be used")
        with s.lock:
            if os.path.normcase(os.path.dirname(real)) == os.path.normcase(os.path.realpath(canopen_dir)):
                name = os.path.basename(real)
                return {"name": name, "summary": s.eds_info([name])[name], "converted": False}
            with open(real, "rb") as f:
                data = f.read()
            res = s.import_eds(os.path.basename(real), data, "keep_both", eds_lint)
            res.update(s.notes_beside(real, res["name"]))
            return res


SEND_ROUTES = (("POST", "/api/online/send_frame"), ("POST", "/api/online/send_stop"),
               ("POST", "/api/online/send_jobs"))
TOO_OLD_FRAMES = "the bridge is too old for sending frames; update it (install-bridge.sh)"


def frame_from(body):
    """The Send panel's frame: the identifier as hex text ("60A", "0x60A") or
    a number, the data as hex bytes."""
    ext, rtr = body.get("ext") is True, body.get("rtr") is True
    raw = body.get("id")
    if isinstance(raw, str):
        text = raw.strip()
        text = text[2:] if text.lower().startswith("0x") else text
        if not text or any(c not in "0123456789abcdefABCDEF" for c in text):
            raise ApiError(422, "the identifier must be hex, for example 60A")
        raw = int(text, 16)
    try:
        can_id = diag.parse_frame_id(raw, ext)
    except ValueError:
        raise ApiError(422, "the identifier must be hex, for example 60A" if not isinstance(raw, int) else
                       "identifier %X is out of range: 0-%X%s" % (raw, 0x1FFFFFFF if ext else 0x7FF,
                                                                 "" if ext else " (tick Extended for a 29-bit one)"))
    try:
        data = b"" if rtr else diag.parse_frame_data(body.get("data") or "")
    except ValueError as e:
        raise ApiError(422, str(e) if "at most 8" in str(e) else
                       "the data must be whole hex bytes, for example 40 18 10 01")
    dlc = body.get("dlc")
    if rtr and (isinstance(dlc, bool) or not isinstance(dlc, int) or not 0 <= dlc <= 8):
        raise ApiError(422, "a remote frame needs a DLC of 0-8")
    period = body.get("period_ms") or None
    if period is not None and (isinstance(period, bool) or not isinstance(period, int) or not 10 <= period <= 60000):
        raise ApiError(422, "the period must be 10-60000 ms")
    count = body.get("count") or None
    if count is not None and (isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 1000000):
        raise ApiError(422, "the count must be 1-1000000")
    return {"can_id": can_id, "ext": ext, "rtr": rtr, "dlc": dlc if rtr else None, "data": data,
            "period_ms": period, "count": count if period else None}


def frame_error(e):
    """The ApiError for a refused or failed send: `force` true when the
    bridge's reason says the request may be repeated with force."""
    if diag.too_old(e):
        return ApiError(422, TOO_OLD_FRAMES, kind="too_old")
    return ApiError(422 if e.kind == "refused" else 502, str(e), kind=e.kind, force=diag.needs_force(e))


class Server(http.server.ThreadingHTTPServer):
    daemon_threads = True
    # The page loads many modules at once. On
    # Windows a full listen backlog refuses connections instead of letting
    # them wait, so the default of 5 made imports fail now and then.
    request_queue_size = 128

    def __init__(self, port=0, token=None, verbose=False):
        super().__init__(("127.0.0.1", port), Handler)
        self.token = token or secrets.token_urlsafe(32)
        self.start_codes = set()  # one-time codes of the start URLs handed out, not used yet
        self.start_lock = threading.Lock()
        self.session = Session()
        self.verbose = verbose
        self.connection = online.Connection()
        self.adapter_allow = False  # the USB adapter's allow-changes switch: this connection only, never saved
        self.codesys_runner = None  # tests: runs the CODESYS command line instead of CODESYS
        self.sender = online.Sender()
        self.devices = devices_service.Devices(config_dir())
        self.sim_connection = online.Connection()  # the Simulation view's CANopen simulator
        self.eds_index = online.EdsIndex()
        self.codesys_import = None  # Import from CODESYS: the import between the dialog's steps
        self.spn_cache = {}  # Handler._spn_names
        self.traces = tracing.Traces()
        self.jobs = params.Jobs()
        # Jobs on the bus the page started, for the status bar's job list
        # (/api/online/jobs): asked for their progress only while one runs.
        self.watch = {"scan": False, "lss_find": False, "pdo_test": None, "sync": False}
        # The pages of this configurator, by the page's random id: {"seen", "closed", "unsaved"}
        # (monotonic times). main() turns on stopping without them unless --keep-running.
        self.pages = {}
        self.page_lock = threading.Lock()
        self.stop_unused = False
        self.closed_s, self.silent_s, self.startup_s = PAGE_CLOSED_S, PAGE_SILENT_S, STARTUP_GRACE_S
        self.answering_s, self.sleep_gap_s = PAGE_ANSWERING_S, SLEEP_GAP_S
        self.no_page_s, self.tick_s = launch.NO_PAGE_S, WATCH_TICK_S
        self.since = time.monotonic()  # start, or the last second start: a page is due after it
        self.new_page_at = None  # when a page id was first seen, the latest; None again on a second start
        self.last_end = None  # when the last page closed or stopped answering
        self.last_reason = None  # how that page ended: "closed" or "silent"
        self.last_tick = None  # the watch loop's last tick (monotonic)
        self.asked = {}  # start code -> (monotonic time, url, from_shortcut): addresses the browser was asked to open
        self.timing, self.timing_how = None, None  # this start's launch.StartTiming and where it came from (run())
        self.instance_secret = None  # instance.json's secret (launch.py), when written
        self.instance_file = None
        self.open_request = None  # a second start's PATH for the page with unsaved changes: {"id", "path"}
        self.open_epoch = 0  # +1 when a second start opened a folder: the pages show it
        self.stopped_why = None
        self.watch_stop = threading.Event()
        self.updates = update_mod.Updates()  # run() hands in the one that read the last update's result

    # -- pages, and stopping without them -----------------------------------
    def heartbeat(self, page, unsaved=False, now=None):
        """A page is open (every 30 s, on becoming visible or getting focus).
        The answer carries a second start's PATH for a page with unsaved
        changes."""
        if not isinstance(page, str) or not 0 < len(page) <= 64:
            raise ApiError(400, "page must be the page's id")
        now = time.monotonic() if now is None else now
        unsaved = bool(unsaved)
        with self.page_lock:
            if page not in self.pages:
                self.new_page_at = now
            self.pages[page] = {"seen": now, "closed": None, "unsaved": unsaved}
            req = self.open_request
            if req is not None and not unsaved and any(p["unsaved"] for p in self._live(now)):
                # The page with unsaved changes asks; this one says where it waits.
                return {"open": None, "waiting": req["path"], "epoch": self.open_epoch}
            return {"open": req, "waiting": None, "epoch": self.open_epoch}

    def page_closed(self, page, now=None):
        with self.page_lock:
            p = self.pages.get(page) if isinstance(page, str) else None
            if p is not None and p["closed"] is None:
                p["closed"] = time.monotonic() if now is None else now

    def _live(self, now):
        """The pages that answer: no close beacon and a heartbeat within
        answering_s (a second start asks these first)."""
        return [p for p in self.pages.values() if p["closed"] is None and now - p["seen"] < self.answering_s]

    def _page_end(self, p):
        """When a page ends and how: (time, "closed"|"silent"), or (None,
        "silent") when silence alone never ends it (unsaved changes)."""
        if p["closed"] is not None:
            return p["closed"] + self.closed_s, "closed"
        if p["unsaved"]:
            return None, "silent"
        return p["seen"] + self.silent_s, "silent"

    def unused(self, now=None):
        """Why the configurator should stop now, or None: every page has
        ended (closed_s after its close beacon; silent_s after its last
        heartbeat when that said nothing was unsaved; never by silence with
        unsaved changes), or none came after the start or a second start
        (startup_s)."""
        if not self.stop_unused:
            return None
        now = time.monotonic() if now is None else now
        with self.page_lock:
            ends = [(k,) + self._page_end(p) for k, p in self.pages.items()]
            if any(how == "silent" and (end is None or now < end) for _, end, how in ends):
                return None  # a page without a close beacon that has not timed out
            for k, end, how in ends:
                if self.last_end is None or end >= self.last_end:
                    self.last_end, self.last_reason = end, how
                del self.pages[k]  # it ended: only its end time counts
            if self.new_page_at is None or self.new_page_at < self.since:
                if now - self.since >= self.startup_s:
                    return "no page was opened within %d minutes of its start" % round(self.startup_s / 60)
                return None
            if self.last_end is not None and now >= self.last_end:
                if self.last_reason == "silent":
                    return "its last page sent no heartbeat for %d minutes" % round(self.silent_s / 60)
                return "its last page was closed"
            return None

    def tick(self, now):
        """One tick of the watch loop at monotonic time `now`. A gap of more
        than sleep_gap_s since the last tick means this process did not run
        (the computer slept): every page's last heartbeat and close, the
        start and the last end move later by that time (less one tick), so
        it does not count as silence on any system. Returns why the
        configurator should stop now, or None."""
        with self.page_lock:
            last, self.last_tick = self.last_tick, now
            if last is not None and now - last > self.sleep_gap_s:
                gap = now - last - self.tick_s

                def later(t):  # a time from before the sleep (the process slept within a tick of `last`)
                    return t + gap if t is not None and t <= last + self.tick_s else t

                for p in self.pages.values():
                    p["seen"], p["closed"] = later(p["seen"]), later(p["closed"])
                self.since, self.new_page_at = later(self.since), later(self.new_page_at)
                self.last_end = later(self.last_end)
        self._report_unopened()
        return self.unused(now)

    def start_watch(self):
        self.last_tick = time.monotonic()
        threading.Thread(target=self._watch_pages, daemon=True).start()

    def _watch_pages(self):
        while not self.watch_stop.wait(self.tick_s):
            why = self.tick(time.monotonic())
            if why:
                self.stop(why)
                return

    def asked_browser(self, url, from_shortcut=False):
        """The browser was asked to open `url`: if no page comes in
        no_page_s, its address is printed (the terminal, or the log) and,
        for a start from the app shortcut, shown in a message window."""
        if self.timing is not None:
            self.timing.mark("browser asked")
        with self.page_lock:
            self.asked[url.rsplit("code=", 1)[-1]] = (time.monotonic(), url, from_shortcut)

    def _report_unopened(self):
        now = time.monotonic()
        with self.page_lock:
            due = [(c, u, sc) for c, (t, u, sc) in self.asked.items() if now - t >= self.no_page_s]
            for c, _, _ in due:
                del self.asked[c]
        for code, url, from_shortcut in due:
            if self.start_code_waiting(code):
                print(launch.NO_BROWSER % url, flush=True)
                if self.timing is not None:
                    self.timing.log_once(self.timing_how)
                if from_shortcut:
                    threading.Thread(target=launch.message_window, args=(url,), daemon=True).start()

    def start_code_waiting(self, code):
        with self.start_lock:
            return any(secrets.compare_digest(known, code) for known in self.start_codes)

    def publish(self, path):
        """Writes instance.json (launch.py), so a later canworks-config of
        this user finds this configurator; FileExistsError when there is one."""
        secret = secrets.token_urlsafe(32)
        launch.write_instance(path, self.server_port, secret)
        self.instance_secret, self.instance_file = secret, path

    def second_start(self, path, browser=True, now=None, from_shortcut=False):
        """canworks-config started again: a new start address; with PATH that
        folder opens now, or, when a page has unsaved changes, that page asks
        first."""
        now = time.monotonic() if now is None else now
        if path is not None:
            if not isinstance(path, str) or not path:
                raise ApiError(400, "path must be a folder")
            s = self.session
            with self.page_lock:
                ask_first = any(p["unsaved"] for p in self._live(now)) or (s.commission and self._live(now))
            if ask_first:
                with self.page_lock:
                    self.open_request = {"id": secrets.token_hex(8), "path": path}
            else:
                with s.lock:
                    s.open(path)
                self.open_epoch += 1
        with self.page_lock:
            # Only a page seen after this start is its page: the clock alone
            # cannot tell (Windows' monotonic clock moves in 15.6 ms steps,
            # so a page's first heartbeat just before can have the same time).
            self.since, self.new_page_at = now, None
        url = self.url
        if browser:
            self.asked_browser(url, from_shortcut)
        return {"url": url}

    def open_taken(self, request_id):
        with self.page_lock:
            if self.open_request is not None and self.open_request["id"] == request_id:
                self.open_request = None

    def handle_error(self, request, client_address):
        if isinstance(sys.exc_info()[1], (BrokenPipeError, ConnectionResetError)):
            return  # the browser went away mid-response
        super().handle_error(request, client_address)

    @property
    def url(self):
        """A new start URL: its one-time code is swapped for the session
        cookie on first use, then forgotten."""
        code = secrets.token_urlsafe(32)
        with self.start_lock:
            self.start_codes.add(code)
        return "http://127.0.0.1:%d/?code=%s" % (self.server_port, code)

    def take_start_code(self, code):
        with self.start_lock:
            for known in self.start_codes:
                if secrets.compare_digest(known, code):
                    self.start_codes.discard(known)
                    break
            else:
                return False
        if self.timing is not None:
            self.timing.mark("page")
            self.timing.log_once(self.timing_how)
        return True

    def server_close(self):
        super().server_close()
        if not hasattr(self, "watch_stop"):
            return  # binding the port failed: __init__ stopped before setting up the rest
        self.watch_stop.set()
        if self.instance_file:
            launch.remove_instance(self.instance_file, self.instance_secret)
        self.close_connections()
        shutil.rmtree(self.session.pending_dir, ignore_errors=True)

    def close_connections(self):
        # As Disconnect does: a USB adapter is free for other tools at once.
        self.traces.stop_all()
        self.connection.close()
        self.sim_connection.close()
        self.sender.close()

    # -- updates (pc-tools-self-update) -----------------------------------------
    def update_target(self, version):
        """The version Update goes to: the newest release, asked again now
        (the offered `version` may have gone since), or the installed version
        when the tools were reinstalled while this configurator runs (a
        restart into it). ApiError when there is nothing to update to."""
        if update_mod.version_key(version) is None:
            raise ApiError(400, "version must look like 1.2.3")
        view = self.updates.view()
        if view["kind"] != "uv-tool":
            raise ApiError(409, "This copy cannot update itself: %s." % view["why"], kind=view["kind"],
                           command=view["command"])
        installed = view["installed"]
        if not (view["restart"] and version == installed):
            latest = self.updates.check()
            if latest is None and self.updates.error:
                raise ApiError(409, "Could not reach GitHub to find the newest release (%s); nothing was changed."
                               % self.updates.error)
            latest = latest or self.updates.view()["latest"]
            if update_mod.is_newer(latest, self.updates.base()):
                return latest
        if view["restart"]:
            return installed
        raise ApiError(409, "%s is the newest release, and it is installed already." % self.updates.base())

    def update_now(self, version):
        """Update now: refused with the reasons while work would be lost;
        else the updater starts and this configurator stops (the caller,
        after answering)."""
        why = update_mod.guard(self)
        if why:
            raise ApiError(409, "Not now: %s." % "; ".join(why), reasons=why, on_quit=True)
        target = self.update_target(version)
        try:
            data = self.updates.run_file(target, os.getpid(), self.server_port, self.token, restart=True)
            self.updates.start_updater(data)
        except (OSError, ValueError) as e:
            raise ApiError(409, "The update could not start: %s" % (getattr(e, "strerror", None) or e))
        return {"updating": True, "version": target, "asked": version,
                "restart": target == self.updates.installed_fn(), "boot": self.updates.boot}

    def _update_on_stop(self, why):
        """Update when I quit: the stop runs the update, without a restart."""
        version = self.updates.on_quit
        if not version or why == "update" or why.startswith("it was told"):
            return
        self.updates.on_quit = None
        try:
            data = self.updates.run_file(self.update_target(version), os.getpid(), None, None, restart=False)
            self.updates.start_updater(data)
        except (ApiError, OSError, ValueError) as e:
            print("canworks-config: the update chosen for quitting did not start: %s" % e, flush=True)

    def stop(self, why):
        """Quit, or no page left: serving ends (main() then closes the
        rest) and every connection closes."""
        self._update_on_stop(why)
        self.stopped_why = why
        print("canworks-config stopped: %s." % why, flush=True)
        self.shutdown()
        self.close_connections()


parser = start.parser  # the arguments live in start.py, the command's light entry


def serve(server):
    """Serves until Quit, Ctrl-C or no page is left; then closes every
    connection as Disconnect does."""
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


# When the macOS app's script ends, macOS stops the processes the app started
# (SIGINT, then SIGTERM): the configurator it started in the background lets
# those go by for this long after its start (the script also ignores them).
APP_TEARDOWN_S = 10.0


def outside_stop(server, mode, platform=None, now=time.monotonic):
    """The handler for a stop from outside, and the signals it takes."""
    grace = APP_TEARDOWN_S if mode == "shortcut" and (platform or sys.platform) == "darwin" else 0.0
    started = now()

    def handler(*_):
        if now() - started < grace:
            return  # the app's script ended
        threading.Thread(target=server.stop, args=("it was told to stop (a signal)",), daemon=True).start()

    return handler, ("SIGTERM", "SIGHUP") + (("SIGINT",) if grace else ())


def main(argv=None):
    return start.main(argv, serving=sys.modules[__name__])


def run(args, mode, timing=None):
    """Serves in this process (start.main): `mode` is "terminal" (the
    background configurator a terminal started), "shortcut" (the app
    shortcut's process, itself in the background) or "foreground"."""
    background = mode in ("terminal", "shortcut")
    # The last update's result; after an update, its port and the session
    # token, so the open tab reloads into this version.
    updates = update_mod.Updates()
    resume = updates.take_result(getattr(args, "resume", None))
    server = None
    if resume:
        try:
            server = Server(resume["port"], token=resume["token"], verbose=args.verbose)
        except OSError:
            resume = None  # the port was taken meanwhile: a new address and a new tab
    try:
        server = server or Server(args.port, verbose=args.verbose)
    except OSError as e:
        print("canworks-config: cannot listen on 127.0.0.1:%d: %s" % (args.port, e.strerror or e),
              file=sys.stderr)
        return 2
    server.updates = updates
    server.timing, server.timing_how = timing, mode
    if timing is not None:
        timing.mark("listening")
    if args.path:
        try:
            server.session.open(args.path)
        except ApiError as e:
            print("canworks-config: %s" % e, file=sys.stderr)
            server.server_close()
            return 2
    if background or not args.new_instance:
        # A background configurator with --new-instance has a file of its own, for its starter only.
        path = launch.instance_path(launch.own_instance_name(args.new_instance))
        for attempt in (1, 2):
            try:
                server.publish(path)
                break
            except FileExistsError:
                inst = launch.running(path)
                if inst is not None and attempt == 1 and launch.ask(inst, "/api/instance/page", {"code": ""}):
                    # Another canworks-config started at the same moment: that one stays.
                    server.server_close()
                    if mode == "terminal":
                        return launch.TAKEN_OVER
                    done = launch.hand_over(inst, args.path, browser=not args.no_browser,
                                            out=None if mode == "shortcut" else sys.stdout,
                                            from_shortcut=mode == "shortcut")
                    return 2 if done is None else done
                try:
                    os.remove(path)  # a configurator that no longer runs left it
                except OSError:
                    pass
            except OSError as e:
                print("canworks-config: cannot write %s: %s (a second canworks-config starts a second "
                      "configurator)" % (path, e.strerror or e), file=sys.stderr)
                break
    server.stop_unused = not args.keep_running
    if background:
        print("canworks configurator started on 127.0.0.1:%d (pid %d, version %s%s)"
              % (server.server_port, os.getpid(), __version__, ", started again by the updater" if resume
                 else ", from the app shortcut" if mode == "shortcut" else ""),
              flush=True)
    if updates.result:
        print("canworks-config: last update: %s" % updates.result.get("message"), flush=True)
    if resume:
        print("canworks-config: started again after an update; the open tab reloads", flush=True)
    elif mode == "shortcut":
        url = server.url
        server.asked_browser(url, from_shortcut=True)
        webbrowser.open(url)
    elif mode == "foreground":
        url = server.url  # one start code: the browser's first visit uses it up
        print("canworks configurator: %s" % url, flush=True)
        print("Press Ctrl-C to stop." if args.keep_running
              else "It stops when its last browser tab is closed; Ctrl-C stops it too.", flush=True)
        if not args.no_browser:
            server.asked_browser(url)
            webbrowser.open(url)
    # Stopped from outside (kill, the terminal closed): stops as Quit does, so
    # the connections close and instance.json goes.
    handler, names = outside_stop(server, mode)
    for name in names:
        try:
            signal.signal(getattr(signal, name), handler)
        except (AttributeError, ValueError, OSError):
            pass  # not on this system, or not the main thread
    server.start_watch()
    updates.check_in_background(ui_on=load_ui()["update_check"] == "on", every_s=update_mod.START_CHECK_S)
    return serve(server)


if __name__ == "__main__":
    sys.exit(main())
