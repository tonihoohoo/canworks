"""canworks-config: serves the configurator page on 127.0.0.1.

  canworks-config [PATH] [--port N] [--no-browser]

PATH opens directly: as an editor project when it has project.json (the
config is PATH/canworks/canworks.json), otherwise as a standalone config folder
(PATH/canworks.json). Without PATH the page opens on its start page.

Every request must carry the session token: the URL printed at start sets it
as a cookie for the page, and the page sends it as a header on API calls.
Requests whose Host is not loopback are refused (DNS rebinding).
"""

import argparse
import base64
import hashlib
import http.server
import io
import json
import mimetypes
import os
import re
import secrets
import shutil
import sys
import tempfile
import threading
import time
import traceback
import urllib.parse
import webbrowser
import zipfile

from .. import __version__, axis, contract, dbcexport, dcfexport, diag, docexport, editorproject, edslint, parameters, project as project_mod, sdolibrary
from .. import slaveeds
from .. import eds as eds_mod
from ..bustrace import explain as explain_mod, framebuild
from ..bustrace import formats as formats_mod, recorder as recorder_mod, sequences as sequences_mod, triggers as triggers_mod
from ..eds import Eds, EdsError
from ..iec import CO_TYPES, parse_location
from ..userdirs import config_dir
from ..j1939 import dbc as j1939_dbc
from . import cia402map, declare, layout, online, params, scan, simulation, tracing

STATIC = os.path.join(os.path.dirname(__file__), "static")
TOKEN_HEADER = "X-CANopen-Token"
COOKIE = "canopen_session"
CONFIG = "canworks.json"
MAX_BODY = 32 * 1024 * 1024
MAX_TRACE_FILE = 1024 * 1024 * 1024
RECENT_MAX = 10
UNEXPECTED_ERROR = "The configurator hit an error; see its terminal."

# Key order of a saved file; keys not listed keep their place after these.
ORDER = {
    "": ["$schema", "schema_version", "adapter", "master", "nodes", "networks", "gateway", "diagnostics"],
    "network": ["name", "protocol", "role", "adapter", "master", "nodes", "slave", "j1939"],
    "adapter": ["type", "simulate", "interface", "bitrate", "configure_link", "restart_ms"],
    "master": ["node_id", "sync_period_us", "heartbeat_ms", "eds_lint", "strict_eds", "bus_state_location",
               "tx_error_count_location", "rx_error_count_location", "bus_off_count_location", "state_location",
               "vendor_id", "product_code", "revision_number", "serial_number", "sync_window_us",
               "sync_counter_overflow", "time_cob_id", "time_period_ms", "emcy_inhibit_time_us", "heartbeat_consumer",
               "heartbeat_multiplier", "error_behavior", "nmt_inhibit_time_us", "start", "start_nodes",
               "start_all_nodes", "reset_all_nodes", "stop_all_nodes", "boot_time_ms", "sdo_timeout_ms",
               "diagnostics"],
    "node": ["node_id", "name", "eds", "simulate", "heartbeat_ms", "heartbeat_timeout_ms", "guard_time_ms",
             "life_time_factor",
             "status_location", "state_location", "boot_error_location", "emcy_code_location",
             "error_register_location", "nmt_command_location", "mandatory", "boot",
             "reset_communication", "revision_number", "serial_number", "lss", "heartbeat_consumer", "retry_factor",
             "time_cob_id", "error_behavior", "restore_configuration", "config_check", "store_configuration",
             "software_file", "software_version",
             "tx_pdos", "rx_pdos", "sdo", "sdo_variables"],
    "pdo": ["number", "cob_id", "transmission", "inhibit_time_us", "event_timer_ms", "sync_start", "timeout_ms",
            "on_timeout", "timeout_location", "entries"],
    "entry": ["index", "subindex", "type", "iec_location"],
    "sdo": ["index", "subindex", "type", "value"],
    "sdo_variable": ["name", "index", "subindex", "type", "direction", "iec_location", "period_ms",
                     "trigger_location", "status_location", "abort_code_location", "timeout_ms"],
    "diagnostics": ["token_verifier", "token_sha256", "port", "bind", "allow_changes"],
    "lss": ["assign", "store"],
    "slave": ["node_id", "eds", "eds_lint", "inputs_on_loss", "state_location", "comm_ok_location",
              "sync_count_location", "emcy_code_location", "error_register_location", "objects"],
    "slave_object": ["index", "subindex", "name", "iec_location"],
    "gateway": ["upper", "routes", "status", "emcy_forward", "on_upper_loss", "sdo_bridge", "sdo_bridge_index",
                "sdo_bridge_write"],
    "route": ["name", "slave", "field"],
    "route_field": ["network", "node", "index", "subindex"],
}


THEMES = ("auto", "light", "dark")


# Page settings kept in ui.json, with their choices and defaults.
UI_SETTINGS = {"theme": (THEMES, "auto"), "dbc_sdo": (dbcexport.SDO_OPTIONS, "none")}


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
    return {k: stored.get(k) if stored.get(k) in choices else default
            for k, (choices, default) in UI_SETTINGS.items()}


def load_theme():
    return load_ui()["theme"]


def save_ui(changes):
    """Stores the settings in `changes` (any of UI_SETTINGS), keeping the rest."""
    if not isinstance(changes, dict) or not changes:
        raise ApiError(400, "give at least one of: " + ", ".join(UI_SETTINGS))
    ui = load_ui()
    for key, value in changes.items():
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
    os.replace(tmp, os.path.join(config_dir(), "ui.json"))
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
    if isinstance(cfg.get("diagnostics"), dict):
        cfg["diagnostics"] = _ordered(cfg["diagnostics"], "diagnostics")
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


def empty_config():
    return {"schema_version": 1,
            "adapter": {"type": "socketcan", "interface": "can0", "bitrate": 250000},
            "master": {"node_id": 1, "sync_period_us": 10000},
            "nodes": []}


SCHEMA_FILE = "canworks.v%d.schema.json"


def lowest_version(cfg):
    """The config in the lowest schema version that holds it (canopen-config-
    contract): a version 2 file with one network that has no name of its own
    (none, or its interface's) becomes version 1, its diagnostics back in the
    master. Anything else comes back as it is, also a file the checks will
    refuse, so they report it as the user wrote it."""
    if not isinstance(cfg, dict) or cfg.get("schema_version") != 2 or not isinstance(cfg.get("networks"), list) \
            or len(cfg["networks"]) != 1 or not isinstance(cfg["networks"][0], dict):
        return cfg
    net = cfg["networks"][0]
    adapter, master, name = net.get("adapter"), net.get("master"), net.get("name")
    if name not in (None, "") and not (isinstance(adapter, dict) and name == adapter.get("interface")):
        return cfg
    if any(k not in ("name", "adapter", "master", "nodes") for k in net) or \
            (isinstance(master, dict) and "diagnostics" in master) or \
            ("diagnostics" in cfg and not (isinstance(cfg["diagnostics"], dict) and isinstance(master, dict))):
        return cfg
    out = {}
    for k, v in cfg.items():
        if k == "networks":
            out.update((key, net[key]) for key in ("adapter", "master", "nodes") if key in net)
        elif k != "diagnostics":
            out[k] = 1 if k == "schema_version" else v
    ref = out.get("$schema")
    if isinstance(ref, str) and ref.endswith(SCHEMA_FILE % 2):
        out["$schema"] = ref[:-len(SCHEMA_FILE % 2)] + SCHEMA_FILE % 1
    if "diagnostics" in cfg:
        out["master"] = dict(master, diagnostics=cfg["diagnostics"])
    return out


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
    place. A master with both keeps both, for the check to report."""
    master = cfg.get("master") if isinstance(cfg, dict) else None
    if isinstance(master, dict) and master.get("eds_lint") == "communication" and "strict_eds" not in master:
        # The default; the page saves it as no field.
        cfg = dict(cfg)
        cfg["master"] = {k: v for k, v in master.items() if k != "eds_lint"}
        return cfg, None
    if not isinstance(master, dict) or not isinstance(master.get("strict_eds"), bool) or "eds_lint" in master:
        return cfg, None
    mode = "all" if master["strict_eds"] else "off"
    cfg = dict(cfg)
    cfg["master"] = {("eds_lint" if k == "strict_eds" else k): (mode if k == "strict_eds" else v)
                     for k, v in master.items()}
    return cfg, ("This file uses the old 'strict_eds': %s. It is shown as EDS lint \"%s\", and saving writes it as "
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
               "type_code": o.data_type,
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
    pdo_maps = {}
    for direction, base in (("input", 0x1A00), ("output", 0x1600)):
        pdo_maps[direction] = {}
        for k in range(eds.pdo_count(direction)):
            m = eds_mod.mapping_info(eds, base + k)
            pdo_maps[direction][str(k + 1)] = {
                "writable": m["writable"], "has_default": m["has_default"],
                "defaults": [{"index": "0x%04X" % (v >> 16), "subindex": (v >> 8) & 0xFF, "bits": v & 0xFF}
                             for v in m["defaults"]]}
    # [DeviceInfo]: identity and LSS_Supported.
    return {"objects": objects, "pdo_count": {"input": eds.pdo_count("input"), "output": eds.pdo_count("output")},
            "pdo_maps": pdo_maps, "device": eds_mod.device_info(path) if path else None}


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

    def eds_path(self, value):
        if value in self.pending:
            return os.path.join(self.pending_dir, value)
        return value if os.path.isabs(value) else os.path.join(self.canopen_dir, value)

    # -- recent folders -----------------------------------------------------
    def recent(self):
        try:
            with open(os.path.join(config_dir(), "recent.json"), encoding="utf-8") as f:
                items = json.load(f)
            return [r for r in items if isinstance(r, dict) and isinstance(r.get("path"), str)][:RECENT_MAX]
        except (OSError, ValueError):
            return []

    def remember(self):
        if os.path.dirname(self.folder) == os.path.abspath(config_dir()):
            return  # the "Commission a device" scratch folder
        items = [r for r in self.recent() if r["path"] != self.folder]
        items.insert(0, {"path": self.folder, "mode": self.mode})
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
            os.replace(tmp, os.path.join(config_dir(), "recent.json"))
        except OSError:
            pass  # a convenience only

    # -- open / close -------------------------------------------------------
    def open(self, path, mode="auto", new=None):
        """Opens a folder. `new` False ("Open standalone config") wants an
        existing canworks.json, True ("New standalone config") refuses one;
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
                raise ApiError(404, "%s has no %s; pick New standalone config to start one there" % (path, CONFIG),
                               no_config=True)
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

    def commission_device(self):
        """"Commission a device": a scratch standalone folder in the settings
        folder, with the online pages on a USB adapter and no config needed."""
        folder = os.path.join(config_dir(), "commission")
        os.makedirs(folder, exist_ok=True)
        self.open(folder, "standalone")
        self.commission = True
        online.Settings(config_dir()).update_project(self.folder, target="adapter")

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
    def read_config(self):
        """(config, notices, error)."""
        if not os.path.isfile(self.config_path):
            return empty_config(), [], None
        try:
            with open(self.config_path, encoding="utf-8") as f:
                cfg = json.load(f)
        except OSError as e:
            return empty_config(), [], "%s cannot be read: %s" % (self.config_path, (e.strerror or str(e)).lower())
        except ValueError as e:
            return empty_config(), [], "%s cannot be read: %s" % (self.config_path, e)
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
                out[name] = eds_summary(Eds.read(path), path)
            except EdsError as e:
                out[name] = {"error": "EDS file %s cannot be parsed: %s" % (path, e)}
        return out

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
        base = {"version": __version__, "recent": self.recent(), "home": os.path.expanduser("~"),
                "mode": self.mode, "type_bits": {k: v[1] for k, v in CO_TYPES.items()},
                "default_start": layout.DEFAULT_START, "commission": self.commission}
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
        sim = simulation.read(self.sim_path)
        sim_eds = simulation.eds_files(self.canopen_dir)
        referenced = {n.get("eds") for n in contract.eds_users(cfg)}
        referenced.update(simulation.extra_eds(sim["doc"]))
        names = self.eds_names(cfg)
        base.update({
            "folder": self.folder, "name": os.path.basename(self.folder.rstrip(os.sep)) or self.folder,
            "canopen_dir": self.canopen_dir, "config_path": self.config_path,
            "config_exists": os.path.isfile(self.config_path), "config": cfg, "notices": notices,
            "load_error": error, "eds": self.eds_info(names),
            "unused_eds": [n for n in names if n not in referenced and n not in self.pending],
            "slave_descriptions": self.slave_descriptions(names),
            "project_uses": [u.as_dict() for u in self.uses], "scan_problems": self.scan_problems,
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
        mode = eds_lint if eds_lint in edslint.MODES else edslint.effective_mode(self.read_config()[0].get("master"))
        text, corrections, lint = edslint.check(data)
        data, converted = utf8_eds(data)
        try:
            eds = Eds.read(name, text)
        except EdsError as e:
            raise ApiError(422, "%s is not an EDS the configurator can use: %s" % (name, e))
        if lint.read_error:
            raise ApiError(422, "%s cannot be used: %s" % (name, lint.read_error))
        failing = lint.failing(mode)
        if failing:
            raise ApiError(422, edslint.error_text(None, name, failing, mode),
                           findings=[f.to_json() for f in failing])
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
        return {"name": name, "converted": converted, "summary": eds_summary(eds, os.path.join(self.pending_dir, name)),
                "lint": {"mode": mode, "corrections": [c.to_json() for c in corrections],
                         "accepted": [f.to_json() for f in lint.accepted(mode)]}}

    # -- J1939 DBC import (j1939-pc-tools "J1939 network in the configurator") --
    def dbc_path(self, name):
        if name in self.pending_dbc:
            return os.path.join(self.pending_dir, name)
        return os.path.join(self.canopen_dir, name)

    def import_dbc(self, name, data=None, on_conflict=None):
        """A DBC file for a J1939 network's message picker: with `data` a
        new file, kept for the draft and written to the config folder on
        save (a different file of that name: 409 unless `on_conflict` is
        "replace" or "keep_both"); without it the file the network already
        names. Returns {name, messages, problems}: dbc.load()'s messages
        without their frame IDs' parts the page does not use."""
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
                                  signals=[s["name"] for s in m["signals"]]) for m in imported.messages]}

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

    # -- checks -------------------------------------------------------------
    def check(self, cfg, allow_overlap=False, task_interval=None):
        if not isinstance(cfg, dict):
            raise ApiError(400, "config must be a JSON object")
        eds_paths = self.eds_paths(cfg)
        result = contract.check_config(cfg, self.config_path, eds_paths=eds_paths)
        items = list(result.items)
        extra, declared = layout.project_checks(cfg, self.uses, allow_overlap)
        items += extra
        # A cyclic axis's fCycleTime line: the task interval the page gives.
        cycle_s = editorproject.interval_seconds(editorproject.DEFAULT_INTERVAL)
        if task_interval:
            try:
                cycle_s = editorproject.interval_seconds(task_interval)
            except editorproject.NewProjectError as e:
                items.append({"level": "warning", "message": str(e), "paths": ["task_interval"]})
        decls, block = [], ""
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
                cfg, lambda i, ix, sub: names.get((nodes[i].get("eds"), ix, sub)), declared, slave_object)
            block = declare.st_block(decls)
            axes = axis.text_block(cfg, decls, cycle_s)
            if axes:
                block = (block + "\n" if block else "") + axes
        except (KeyError, TypeError, ValueError, AttributeError):
            pass  # the contract errors already say what is wrong with the entries
        errors = sum(1 for i in items if i["level"] == "error")
        return {"items": items, "errors": errors, "declared": declared, "declarations": decls, "block": block,
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

    # -- DBC export ---------------------------------------------------------
    def export_dbc(self, cfg, sdo="none", network=None):
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
                                                        names=names, network=network)
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
    def export_html(self, cfg):
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
                plc_cycle_ms=docexport.project_cycle_ms(self.config_path) if project else None)
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
        "j1939_address", "j1939_status", "j1939_valid" (no node needed), or
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
                parsed = parse_location(loc)
                used.add((parsed.area, parsed.size, parsed.element))
            bindings.append({"index": "0x%04X" % o["index"], "subindex": o["subindex"], "name": o["name"],
                             "iec_location": loc})
        objects = [dict(o, index="0x%04X" % o["index"]) for o in info["objects"]]
        return {"name": name, "summary": eds_summary(Eds.read(os.path.join(self.pending_dir, name), text),
                                                     os.path.join(self.pending_dir, name)),
                "objects": objects, "bindings": bindings, "revision_number": info["revision_number"],
                "routes": [{"index": "0x%04X" % r["index"], "subindex": r["subindex"]} for r in info["routes"]]}

    def export_eds(self, cfg, network):
        """A slave network's EDS as the plugin runs it, for the other
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

    # -- CiA 402 axis -------------------------------------------------------
    def map_cia402(self, cfg, node, start=None, network=0):
        """Node `node` of network `network` (an index) of the draft with the
        standard CiA 402 objects its EDS has put into PDOs (cia402map), and
        its status bit when it has none: {node, mapped, missing, changes}. Suggested
        locations skip those of every network. Nothing is saved."""
        if not isinstance(cfg, dict):
            raise ApiError(400, "config must be a JSON object")
        try:
            n = contract.networks(cfg)[int(network or 0)]["nodes"][int(node)]
        except (KeyError, IndexError, TypeError, ValueError):
            raise ApiError(400, "no node %r in the config" % node)
        info = self.eds_info([n.get("eds")]).get(n.get("eds"), {}) if n.get("eds") else {}
        if not info or info.get("error"):
            raise ApiError(400, info.get("error") or "the node has no EDS file")
        start = layout.DEFAULT_START if start in (None, "") else int(start)
        changes = []
        new, mapped, missing = cia402map.map_objects(n, info, layout.taken(cfg, self.uses), start, changes)
        return {"node": new, "mapped": mapped, "missing": missing, "changes": changes}

    # -- save ---------------------------------------------------------------
    def save(self, cfg, allow_overlap=False, overwrite=False):
        cfg = lowest_version(cfg)
        checked = self.check(cfg, allow_overlap)
        if checked["errors"]:
            raise ApiError(422, "the config has %d error%s; nothing was saved"
                           % (checked["errors"], "" if checked["errors"] == 1 else "s"), check=checked)
        if not overwrite and self.changed_on_disk():
            raise ApiError(409, "%s changed on disk after it was loaded" % self.config_path, changed_on_disk=True)
        try:
            return self._save(cfg, checked)
        except OSError as e:
            raise folder_error(e, "write to", self.canopen_dir)

    def _save(self, cfg, checked):
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
            os.replace(tmp, target)
            written.append(target)
            if name in self.descriptions:
                target = description_path(self.canopen_dir, name)
                with open(target + ".tmp", "w", encoding="utf-8") as f:
                    json.dump(self.descriptions[name], f, indent=2, ensure_ascii=False)
                    f.write("\n")
                os.replace(target + ".tmp", target)
                written.append(target)
        dbc_names = {n["j1939"].get("dbc") for n in contract.networks(cfg) if n["role"] == "j1939"}
        for name, data in sorted(self.pending_dbc.items()):
            if name in dbc_names:
                target = os.path.join(self.canopen_dir, name)
                with open(target + ".tmp", "wb") as f:
                    f.write(data)
                os.replace(target + ".tmp", target)
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
        os.replace(tmp, self.config_path)
        written.append(self.config_path)
        for name in [n for n in self.pending if n in referenced]:
            del self.pending[name]
            self.descriptions.pop(name, None)
        for name in [n for n in self.pending_dbc if n in dbc_names]:
            del self.pending_dbc[name]
        self.loaded = (os.path.getmtime(self.config_path), sha256(self.config_path))
        return {"written": written, "check": checked}

    # -- the simulation file -------------------------------------------------
    def sim_changed_on_disk(self):
        exists = os.path.isfile(self.sim_path)
        if self.sim_loaded is None:
            return exists
        return not exists or sha256(self.sim_path) != self.sim_loaded

    def save_simulation(self, doc, overwrite=False):
        """Writes canworks/simulation.json after the schema check, with the EDS
        files its extra devices name that were imported but not saved yet.
        Like canworks.json, only into the project's config folder."""
        problems = simulation.check(doc)
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
            os.replace(target + ".tmp", target)
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
            cfg = json.load(f)
        result = contract.check_config(cfg, self.config_path)
        if not result.ok:
            raise ApiError(422, "\n".join(result.errors))
        try:
            written, converted = project_mod.write(cfg, self.config_path, target, force=replace,
                                                   sim_path=self._sim_to_move())
        except project_mod.ProjectError as e:
            raise ApiError(422, str(e))
        written += self._move_descriptions(cfg, os.path.join(target, project_mod.DIR))
        self.open(target, "project")
        return {"written": written, "converted": converted}


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
    def new_project(self, parent, name, interval=None, sdo_blocks=False):
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
        if os.path.lexists(target):
            raise ApiError(409, "%s already exists; pick a new name" % target, exists=True)
        with open(self.config_path, encoding="utf-8") as f:
            cfg = json.load(f)
        result = contract.check_config(cfg, self.config_path)
        if not result.ok:
            raise ApiError(422, "\n".join(result.errors))
        address = None
        host = online.Settings(config_dir()).project(self.folder).get("host")
        if host:
            try:
                address = diag.parse_runtime(host)[0]
            except ValueError:
                address = None
        try:
            path, decls = editorproject.create(cfg, self.config_path, target,
                                               interval=interval or editorproject.DEFAULT_INTERVAL,
                                               runtime_address=address, sdo_blocks=sdo_blocks,
                                               sim_path=self._sim_to_move())
        except editorproject.NewProjectError as e:
            raise ApiError(422, str(e))
        self._move_descriptions(cfg, os.path.join(path, project_mod.DIR))
        self.open(path, "project")
        out = {"project": path, "declared": len(decls)}
        if sdo_blocks:
            out["library_ok"], out["library"] = sdolibrary.ensure_installed()
        return out


# J1939 locations /api/place suggests: direction -> (area, size letter).
J1939_PLACES = {"j1939_state": ("I", "B"), "j1939_address": ("I", "B"), "j1939_status": ("I", "X"),
                "j1939_valid": ("I", "X")}


def _bitrate_arg(v):
    """A bit rate the page chose (bit/s), or None."""
    if v in (None, "", 0):
        return None
    try:
        v = int(v)
    except (TypeError, ValueError):
        raise ApiError(400, "bitrate must be a number of bit/s")
    if not 10000 <= v <= 1000000:
        raise ApiError(400, "bitrate must be 10000 to 1000000 bit/s")
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


def list_folders(path):
    path = os.path.abspath(os.path.expanduser(path or "~"))
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
        entries.append({"name": name, "path": full,
                        "project": os.path.isfile(os.path.join(full, "project.json")),
                        "config": os.path.isfile(os.path.join(full, CONFIG))})
    parent = os.path.dirname(path)
    return {"path": path, "parent": parent if parent != path else None, "entries": entries,
            "project": os.path.isfile(os.path.join(path, "project.json")),
            "config": os.path.isfile(os.path.join(path, CONFIG))}


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

    def _cookie_token(self):
        for part in (self.headers.get("Cookie") or "").split(";"):
            k, _, v = part.strip().partition("=")
            if k == COOKIE:
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
        self._send(403, {"error": why})

    def do_GET(self):
        if not self._host_ok():
            return self._deny("requests must address 127.0.0.1")
        url = urllib.parse.urlsplit(self.path)
        query = urllib.parse.parse_qs(url.query)
        token = self.server.token
        if url.path == "/" and query.get("token", [None])[0] == token:
            # The URL printed at start: keep the token in a cookie and drop it from the address bar.
            return self._send(303, b"", "text/plain", [
                ("Location", "/"), ("Set-Cookie", "%s=%s; HttpOnly; SameSite=Strict; Path=/" % (COOKIE, token))])
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
        self._api("POST", url, urllib.parse.parse_qs(url.query))

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
            if url.path.startswith("/api/trace/"):
                if (method, url.path) == ("POST", "/api/trace/open") and \
                        (self.headers.get("Content-Type") or "").startswith("application/octet-stream"):
                    # A trace file as it is: large files do not fit a JSON body.
                    length = int(self.headers.get("Content-Length") or 0)
                    if length > MAX_TRACE_FILE:
                        raise ApiError(413, "the file is larger than %d MiB" % (MAX_TRACE_FILE >> 20))
                    body = {"raw": self.rfile.read(length), "name": query.get("name", ["trace"])[0],
                            "network": query.get("network", [None])[0]}
                else:
                    body = self._body() if method == "POST" else {}
                try:
                    return self._send(200, self._trace((method, url.path), body))
                except tracing.Refused as e:
                    raise ApiError(e.status, str(e), **e.extra)
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
                elif route == ("GET", "/api/folders"):
                    out = list_folders(query.get("path", [None])[0])
                elif route == ("POST", "/api/open"):
                    s.open(body.get("path"), body.get("mode", "auto"), body.get("new"))
                    out = s.state()
                elif route == ("POST", "/api/recent/forget"):
                    s.forget(body.get("path"))
                    out = {"recent": s.recent()}
                elif route == ("POST", "/api/commission"):
                    s.commission_device()
                    self.server.adapter_allow = False
                    self.server.connection.close()
                    out = s.state()
                elif route == ("POST", "/api/close"):
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
                elif route == ("POST", "/api/check"):
                    self._need_open(s)
                    out = s.check(body.get("config"), bool(body.get("allow_overlap")), body.get("task_interval"))
                elif route == ("POST", "/api/export_dbc"):
                    self._need_open(s)
                    out = s.export_dbc(body.get("config"), body.get("sdo", "none"), body.get("network"))
                elif route == ("POST", "/api/export_html"):
                    self._need_open(s)
                    out = s.export_html(body.get("config"))
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
                elif route == ("POST", "/api/map_cia402"):
                    self._need_open(s)
                    out = s.map_cia402(body.get("config"), body.get("node"), body.get("start"),
                                       body.get("network", 0))
                elif route == ("POST", "/api/save"):
                    self._need_open(s)
                    out = s.save(body.get("config"), bool(body.get("allow_overlap")), bool(body.get("overwrite")))
                    out["state"] = s.state()
                elif route == ("POST", "/api/move"):
                    self._need_open(s)
                    out = s.move(body.get("project"), bool(body.get("replace")))
                    out["state"] = s.state()
                elif route == ("POST", "/api/new_project"):
                    self._need_open(s)
                    out = s.new_project(body.get("parent"), body.get("name"), body.get("interval"),
                                        bool(body.get("sdo_blocks")))
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
                threading.Thread(target=self.server.shutdown, daemon=True).start()
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

    @staticmethod
    def _need_open(s):
        if not s.mode:
            raise ApiError(409, "no project or config folder is open")

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
        to the plugin's diagnostics channel through one kept-open connection."""
        s, conn = self.server.session, self.server.connection
        settings = online.Settings(config_dir())
        with s.lock:
            self._need_open(s)
            folder, config_path, canopen_dir = s.folder, s.config_path, s.canopen_dir
        proj = settings.project(folder)

        def view():
            p = settings.project(folder)
            return {"token": p.get("token"), "host": p.get("host") or "", "eds_library": settings.eds_library,
                    "connected": conn.connected, "target": "adapter" if s.commission else p.get("target") or "runtime",
                    "adapter": p.get("adapter") or "", "adapter_bitrate": p.get("adapter_bitrate"),
                    "allow_changes": self.server.adapter_allow, "commission": bool(s.commission)}

        if route == ("GET", "/api/online/settings"):
            return view()
        if route == ("GET", "/api/online/adapters"):
            from .. import localbus
            return {"adapters": localbus.list_adapters()}
        if route == ("POST", "/api/online/settings"):
            if "target" in body:
                target = body.get("target")
                if target not in ("runtime", "adapter"):
                    raise ApiError(422, "target must be runtime or adapter")
                if s.commission and target != "adapter":
                    raise ApiError(422, "Commission a device works through a USB adapter on this PC")
                settings.update_project(folder, target=None if target == "runtime" else target)
                self.server.adapter_allow = False
                conn.close()
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
            if "allow_changes" in body:
                # This connection only: never saved, off again after the next target change or restart.
                self.server.adapter_allow = body.get("allow_changes") is True
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
        if route in (("POST", "/api/online/adapter_detect"), ("POST", "/api/online/adapter_detect_status")):
            return self._adapter_detect(route, body)
        if route == ("POST", "/api/online/use_eds"):
            return self._use_eds(s, settings, canopen_dir, body.get("path"), body.get("eds_lint"))
        if route == ("POST", "/api/online/watch"):
            return self._watch(settings, folder, body)

        # The network the page picked; sent only to a plugin that runs several.
        network = body.get("network") if isinstance(body.get("network"), str) and body.get("network") else None
        hostname, port, token = self._online_target(proj, config_path, network, body)
        host = str(hostname) if isinstance(hostname, online.AdapterTarget) else proj.get("host")
        local = isinstance(hostname, online.AdapterTarget)

        def call(fn):
            def run(c):
                if local:
                    c.force = body.get("force") is True  # LSS while another master is active, after asking
                return fn(c)
            try:
                return conn.call(hostname, port, token, run, network)
            except diag.DiagError as e:
                raise ApiError(422 if e.kind in ("refused", "usage", "busy") else 502, str(e), kind=e.kind)

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

        if route in params.ROUTES:
            node = None if route[1].endswith("/job") else node_arg()
            client = params.Client(conn, hostname, port, token, network)
            try:
                return params.handle(route, body, s, conn, self.server.jobs, client, node, settings.eds_library,
                                     host)
            except params.Refused as e:
                raise ApiError(e.status, str(e))
            except diag.DiagError as e:
                raise ApiError(422 if e.kind == "refused" else 502, str(e), kind=e.kind)
        if route == ("POST", "/api/online/status"):
            used, st = call(lambda c: (picked(c), c.status()))
            prints = online.fingerprints(config_path)
            same = st.get("config_sha256") in prints
            out = {"hello": conn.info, "status": st, "networks": (conn.info or {}).get("networks") or [],
                   "network": used, "config": "none" if not prints else ("same" if same else "different")}
            if local:
                out["config"] = "local"
                out["config_bitrate"] = self._config_bitrate(config_path, network)
            return out
        if route == ("POST", "/api/online/emcy"):
            node = node_arg()
            res = call(lambda c: c.emcy(node))
            for e in res.get("emcy") or []:
                e["class"] = diag.emcy_class(e.get("code", 0))
            return res
        if route in (("POST", "/api/online/sdo_read"), ("POST", "/api/online/sdo_write")):
            node = node_arg()
            index, sub = object_arg()
            timeout_ms = body.get("timeout_ms") if isinstance(body.get("timeout_ms"), int) else 1000
            if route[1].endswith("write"):
                try:
                    data = diag.encode(body.get("type"), body.get("value", ""))
                except ValueError as e:
                    raise ApiError(422, str(e))
                res = call(lambda c: c.sdo_write(node, index, sub, data, timeout_ms))
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
        if route == ("POST", "/api/online/nmt"):
            node, command = node_arg(), body.get("command")
            if command not in diag.NMT_COMMANDS:
                raise ApiError(400, "command must be one of " + ", ".join(diag.NMT_COMMANDS))
            return call(lambda c: c.nmt(node, command))
        if route == ("POST", "/api/online/lss_find"):
            vendor, product = body.get("vendor_id"), body.get("product_code")
            known = isinstance(vendor, int) and isinstance(product, int)
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
                raise ApiError(400, "bitrate_kbit must be one of " + ", ".join(str(b) for b in diag.LSS_BITRATES))
            return call(lambda c: c.lss_set_bitrate(address, kbit, store))
        if route in SEND_ROUTES:
            return self._send_frames(route, body, (hostname, port, token), network)
        if route in (("POST", "/api/online/detect_bitrate"), ("POST", "/api/online/detect_bitrate_status")):
            if local and not route[1].endswith("status"):
                self.server.sender.close()  # the sweep needs the adapter to itself; the Send panel's jobs end
            if route[1].endswith("status"):
                fn = lambda c: c.detect_bitrate_status()  # noqa: E731
            else:
                rates = body.get("rates")
                if rates is not None and (not isinstance(rates, list) or not rates or
                                          any(r not in diag.DETECT_RATES for r in rates)):
                    raise ApiError(400, "rates must be kbit/s out of " + ", ".join(str(r) for r in diag.DETECT_RATES))
                rounds = body.get("rounds")
                if rounds is not None and (isinstance(rounds, bool) or not isinstance(rounds, int) or
                                           not 1 <= rounds <= 20):
                    raise ApiError(400, "rounds must be 1-20")
                lone = body.get("lone_device") is True  # after the page asked; LSS probe
                fn = lambda c: c.detect_bitrate(rates, None, rounds, body.get("force") is True,  # noqa: E731
                                                body.get("disturb_bus") is True, lone, "lss" if lone else None)
            try:
                return conn.call(hostname, port, token, fn, network)
            except diag.DiagError as e:
                raise frame_error(e)
        if route == ("POST", "/api/online/scan"):
            used, res = call(lambda c: (picked(c), c.scan(bool(body.get("start")))))
            res["networks"], res["network"] = (conn.info or {}).get("networks") or [], used
            if res.get("nodes") is not None:
                self._match_scan(s, settings, canopen_dir, res, body.get("config"), used)
            return res
        raise ApiError(404, "no such API: %s %s" % route)

    def _config_bitrate(self, config_path, network):
        """The saved config's bit rate of `network` in bit/s, or None."""
        from ..localbus import configinfo
        if not os.path.isfile(config_path):
            return None
        try:
            return configinfo.load(config_path, network)[0]
        except (OSError, ValueError):
            return None

    def _online_target(self, proj, config_path, network, body):
        """(host, port, token) for the kept-open connection: the runtime of the
        online access settings, or an online.AdapterTarget for a USB adapter on
        this PC (no token; the bit rate from the settings, else the network's)."""
        if proj.get("target") == "adapter":
            from ..localbus import configinfo
            adapter = proj.get("adapter")
            if not adapter:
                raise ApiError(409, "pick the USB adapter for online access", need="adapter")
            nodes, cfg_bitrate = {}, None
            if os.path.isfile(config_path):
                try:
                    cfg_bitrate, nodes = configinfo.load(config_path, network)
                except (OSError, ValueError):
                    pass
            kbit = proj.get("adapter_bitrate")
            bitrate = kbit * 1000 if isinstance(kbit, int) else cfg_bitrate
            if not bitrate:
                raise ApiError(409, "pick the bus's bit rate for the USB adapter", need="adapter")
            return online.AdapterTarget(adapter, bitrate, self.server.adapter_allow, nodes, network), None, None
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

    def _adapter_detect(self, route, body):
        """/api/online/adapter_detect and _status: "Detect" next to the bit
        rate in the USB adapter connection form. The adapter is opened
        listen-only at each rate, so the online connections on this PC are
        closed first; nothing is sent, so no allow-changes is needed. With
        `lone_device` (after the page asked whether only the bench device is
        on the bus) it joins the bus in normal mode and sends the LSS probe."""
        from .. import localbus
        from ..localbus import sweep as sweep_mod
        if route[1].endswith("status"):
            job = self.server.adapter_sweep
            if job is None:
                return sweep_mod.idle_status(None)
            return dict(job.status(), adapter=str(job.spec))
        job = self.server.adapter_sweep
        if job is not None and job.running:
            return dict(job.status(), adapter=str(job.spec))
        try:
            spec = localbus.parse(body.get("adapter") or "")
        except localbus.AdapterError as e:
            raise ApiError(422, str(e))
        rounds = body.get("rounds", 1)
        if isinstance(rounds, bool) or not isinstance(rounds, int) or not 1 <= rounds <= 20:
            raise ApiError(400, "rounds must be 1-20")
        kbit = body.get("adapter_bitrate")
        self.server.connection.close()
        self.server.sender.close()
        job = sweep_mod.Sweep(spec, rounds=rounds, configured_kbit=kbit if isinstance(kbit, int) else None,
                              disturb_bus=body.get("disturb_bus") is True, lone_device=body.get("lone_device") is True,
                              probe="lss" if body.get("lone_device") is True else None)
        try:
            job.start()
        except localbus.AdapterError as e:
            raise ApiError(422, str(e), kind=e.kind, disturb_bus=e.kind == "unconfirmed")
        self.server.adapter_sweep = job
        return dict(job.status(), adapter=str(spec))

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
        access settings) or to a standalone simulator (address and token kept
        on this PC), through the online view's kept-open connection."""
        s, conn = self.server.session, self.server.connection
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
                conn.close()
            return simulation.settings_view(settings.update_project(folder, **values))
        if route == ("POST", "/api/sim/close"):
            conn.close()
            return {"closed": True}
        if route == ("POST", "/api/sim/check"):
            problems = simulation.check(body.get("doc"))
            if not problems:
                with s.lock:
                    problems = self._machine_problems(s, body.get("doc"))
            return {"problems": problems}
        if route == ("GET", "/api/sim/machine"):
            # The machine file of the network's section, for the Machine tab offline.
            name = body.get("network") or ""
            with s.lock:
                doc = simulation.read(s.sim_path)["doc"]
                out = simulation.read_machine(doc, s.sim_path, name)
                problems = []
                if out["file"] and not simulation.check(doc):
                    problems = [{"path": p["path"], "message": p["message"]}
                                for p in self._machine_problems(s, doc, name)]
            error = out.pop("error", None)
            if error and not problems:
                problems = [{"path": "networks.%s.machine" % name, "message": error}]
            return dict(out, problems=problems)
        if route == ("POST", "/api/sim/save"):
            with s.lock:
                out = s.save_simulation(body.get("doc"), bool(body.get("overwrite")))
                out["state"] = s.state()
            return out

        proj = settings.project(folder)

        def where():
            try:
                return simulation.target(proj, body.get("port"))
            except LookupError as e:
                need = str(e).strip("'")
                raise ApiError(409, "enter the runtime host for online access" if need == "host"
                               else "enter the access token for online access", need=need)
            except ValueError as e:
                raise ApiError(422, str(e))

        # The network the page picked; sent only to a plugin that runs several.
        network = body.get("network") if isinstance(body.get("network"), str) and body.get("network") else None

        def call(fn):
            host, port, token, kind = where()
            try:
                return conn.call(host, port, token, fn, network), kind
            except diag.DiagError as e:
                raise ApiError(422 if e.kind == "refused" else 502, str(e), kind=e.kind)

        def hello(kind):
            info = dict(conn.info or {})
            standalone = bool(info.get("simulator"))
            # The standalone simulator takes changes from anyone with its token.
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
        if route == ("POST", "/api/sim/machine"):
            # One sim_machine answer per page poll, on the kept-open connection.
            res, kind = call(lambda c: c.request("sim_machine"))
            return dict(hello(kind), machine=res)
        if route == ("POST", "/api/sim/request"):
            op = body.get("op")
            if op not in simulation.OPS:
                raise ApiError(400, "op must be one of " + ", ".join(simulation.OPS))
            fields = {k: v for k, v in body.items() if k not in ("op", "port", "network")}
            res, kind = call(lambda c: c.request(op, **fields))
            return {"result": res, "target": kind}
        raise ApiError(404, "no such API: %s %s" % route)

    @staticmethod
    def _machine_problems(s, doc, network=None):
        """The machine file problems of a schema-valid simulation file
        (simulation.machine_problems) against the saved config; the caller
        holds s.lock."""
        cfg = s.read_config()[0]
        try:
            return simulation.machine_problems(doc, s.sim_path, cfg, s.config_path,
                                               s.eds_paths(cfg) if isinstance(cfg, dict) else {}, network)
        except (KeyError, TypeError, ValueError, AttributeError):
            return []  # a config the contract check refuses: its problems show there

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
                groups = framebuild.examples(dec)
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

        def decoder():
            cfg = body.get("config")
            with s.lock:
                if not isinstance(cfg, dict):
                    cfg = s.read_config()[0]
                eds_paths = s.eds_paths(cfg)
            return tracing.decoder_for(cfg, config_path, eds_paths, names, network)

        def time_range():
            return tracing._opt_time(body.get("start_us"), "start_us"), tracing._opt_time(body.get("end_us"), "end_us")

        def state():
            return dict(ws.state(), traces_dir=traces_dir)

        if route == ("GET", "/api/trace/state"):
            return state()
        if route == ("POST", "/api/trace/frames"):
            flt = tracing.DisplayFilter(body.get("filter"))
            at = tracing._opt_time(body.get("at_us"), "at_us")
            return ws.rows(tracing._int(body.get("offset", 0), "offset", 0),
                           tracing._int(body.get("count", 200), "count", 1), flt, at)
        if route == ("POST", "/api/trace/ids"):
            return ws.ids()
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
            if proj.get("target") != "adapter" and (not proj.get("host") or not proj.get("token")):
                raise ApiError(409, "set up online access (runtime host and access token, or a USB adapter) in the "
                                    "Online view to record a trace; opening trace files works without it",
                               need="online")
            hostname, port, token = self._online_target(proj, s.config_path, network, body)
            connect = tracing.connector(hostname, port, token, network=network)
            try:  # a wrong host, token or an old plugin is said at once instead of retried
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
            if spec or (spec is None and ws.trigger):
                try:
                    triggers_mod.resolve_signals(spec or ws.trigger, dec.signal_keys())
                except triggers_mod.TriggerError as e:
                    raise ApiError(422, str(e))
            ws.start(connect, dec, filters, bool(body.get("error_frames")), spec, traces_dir, base_name, network)
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
            target = tracing.check_folder(body.get("folder") or traces_dir, canopen_dir)
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

    def _match_scan(self, s, settings, canopen_dir, res, cfg, network=None):
        """Adds to each scanned device the EDS files that match it and, for a
        configured node of the scanned network, what the config expects."""
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
            d["eds_matches"] = self.server.eds_index.matches(folders, d.get("vendor_id"), d.get("product_code"),
                                                             d.get("revision_number"))

    def _use_eds(self, s, settings, canopen_dir, path, eds_lint=None):
        """An EDS file a scan match offered, made available to the draft: one
        in canworks/ as it is, one from the EDS library imported as an EDS
        import would (kept both under a new name if a different file has its
        name)."""
        if not isinstance(path, str) or not path.lower().endswith(".eds"):
            raise ApiError(400, "path must be an EDS file")
        real = os.path.realpath(path)
        roots = [os.path.realpath(r) for r in (canopen_dir, settings.eds_library) if r]
        if not any(real.startswith(r + os.sep) for r in roots) or not os.path.isfile(real):
            raise ApiError(403, "only EDS files in the project's canopen folder or the EDS library can be used")
        with s.lock:
            if os.path.dirname(real) == os.path.realpath(canopen_dir):
                name = os.path.basename(real)
                return {"name": name, "summary": s.eds_info([name])[name], "converted": False}
            with open(real, "rb") as f:
                data = f.read()
            return s.import_eds(os.path.basename(real), data, "keep_both", eds_lint)


SEND_ROUTES = (("POST", "/api/online/send_frame"), ("POST", "/api/online/send_stop"),
               ("POST", "/api/online/send_jobs"))
TOO_OLD_FRAMES = ("the CANopen plugin on the runtime is too old for sending frames and bit rate detection; update "
                  "it (install-stock.sh) and upload again")


def frame_from(body):
    """The Send panel's frame: the identifier as hex text ("60A", "0x60A") or
    a number, the data as hex bytes."""
    ext, rtr = body.get("ext") is True, body.get("rtr") is True
    raw = body.get("id")
    try:
        if isinstance(raw, str):
            text = raw.strip()
            text = text[2:] if text.lower().startswith("0x") else text
            raw = int(text, 16)
        can_id = diag.parse_frame_id(raw, ext)
        data = b"" if rtr else diag.parse_frame_data(body.get("data") or "")
    except ValueError as e:
        if "invalid literal" in str(e):
            raise ApiError(422, "identifier %r is not hexadecimal" % body.get("id"))
        raise ApiError(422, str(e))
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
    """The ApiError for a refused or failed send or sweep: `force` true when
    the plugin's reason says the request may be repeated with force,
    `disturb_bus` when it may be repeated with disturb_bus."""
    if diag.too_old(e):
        return ApiError(422, TOO_OLD_FRAMES, kind="too_old")
    return ApiError(422 if e.kind == "refused" else 502, str(e), kind=e.kind, force=diag.needs_force(e),
                    disturb_bus=diag.needs_disturb(e))


class Server(http.server.ThreadingHTTPServer):
    daemon_threads = True
    # The page loads many modules at once (three.js for the Machine tab). On
    # Windows a full listen backlog refuses connections instead of letting
    # them wait, so the default of 5 made imports fail now and then.
    request_queue_size = 128

    def __init__(self, port=0, token=None, verbose=False):
        super().__init__(("127.0.0.1", port), Handler)
        self.token = token or secrets.token_urlsafe(32)
        self.session = Session()
        self.verbose = verbose
        self.connection = online.Connection()
        self.adapter_allow = False  # the USB adapter's allow-changes switch: this connection only, never saved
        self.sender = online.Sender()
        self.adapter_sweep = None  # the connection form's bit rate sweep on a USB adapter (localbus.sweep.Sweep)
        self.eds_index = online.EdsIndex()
        self.traces = tracing.Traces()
        self.jobs = params.Jobs()

    def handle_error(self, request, client_address):
        if isinstance(sys.exc_info()[1], (BrokenPipeError, ConnectionResetError)):
            return  # the browser went away mid-response
        super().handle_error(request, client_address)

    @property
    def url(self):
        return "http://127.0.0.1:%d/?token=%s" % (self.server_port, self.token)

    def server_close(self):
        super().server_close()
        if not hasattr(self, "jobs"):
            return  # binding the port failed: __init__ stopped before setting up the rest
        self.traces.stop_all()
        self.connection.close()
        self.sender.close()
        if self.adapter_sweep is not None:
            self.adapter_sweep.stop()
        shutil.rmtree(self.session.pending_dir, ignore_errors=True)


def parser():
    p = argparse.ArgumentParser(
        prog="canworks-config",
        description="Edit the CANopen config of an OpenPLC editor project (or a standalone config folder) in a "
                    "local web page.")
    p.add_argument("path", nargs="?", help="editor project folder, or standalone config folder, to open directly")
    p.add_argument("--port", type=int, default=0, help="port on 127.0.0.1 (default: a free one)")
    p.add_argument("--no-browser", action="store_true", help="print the URL but do not open a browser")
    p.add_argument("--verbose", action="store_true", help="log every request")
    p.add_argument("--version", action="version", version="%(prog)s " + __version__)
    return p


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        server = Server(args.port, verbose=args.verbose)
    except OSError as e:
        print("canworks-config: cannot listen on 127.0.0.1:%d: %s" % (args.port, e.strerror or e),
              file=sys.stderr)
        return 2
    if args.path:
        try:
            server.session.open(args.path)
        except ApiError as e:
            print("canworks-config: %s" % e, file=sys.stderr)
            server.server_close()
            return 2
    print("canworks configurator: %s" % server.url, flush=True)
    print("Press Ctrl-C to stop.", flush=True)
    if not args.no_browser:
        webbrowser.open(server.url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
