"""openplc-canopen-config: serves the configurator page on 127.0.0.1.

  openplc-canopen-config [PATH] [--port N] [--no-browser]

PATH opens directly: as an editor project when it has project.json (the
config is PATH/canopen/canopen.json), otherwise as a standalone config folder
(PATH/canopen.json). Without PATH the page opens on its start page.

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
import secrets
import shutil
import sys
import tempfile
import threading
import time
import urllib.parse
import webbrowser
import zipfile

from .. import __version__, axis, contract, dbcexport, dcfexport, diag, editorproject, edslint, parameters, project as project_mod, sdolibrary
from .. import eds as eds_mod
from ..bustrace import formats as formats_mod, recorder as recorder_mod, triggers as triggers_mod
from ..eds import Eds, EdsError
from ..iec import CO_TYPES
from . import cia402map, declare, layout, online, params, scan, simulation, tracing

STATIC = os.path.join(os.path.dirname(__file__), "static")
TOKEN_HEADER = "X-CANopen-Token"
COOKIE = "canopen_session"
CONFIG = "canopen.json"
MAX_BODY = 32 * 1024 * 1024
MAX_TRACE_FILE = 1024 * 1024 * 1024
RECENT_MAX = 10

# Key order of a saved file; keys not listed keep their place after these.
ORDER = {
    "": ["$schema", "schema_version", "adapter", "master", "nodes"],
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
    "pdo": ["number", "cob_id", "transmission", "inhibit_time_us", "event_timer_ms", "sync_start", "entries"],
    "entry": ["index", "subindex", "type", "iec_location"],
    "sdo": ["index", "subindex", "type", "value"],
    "sdo_variable": ["name", "index", "subindex", "type", "direction", "iec_location", "period_ms",
                     "trigger_location", "status_location", "abort_code_location", "timeout_ms"],
    "diagnostics": ["token_sha256", "port", "bind", "allow_changes"],
    "lss": ["assign", "store"],
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


def config_dir():
    env = os.environ.get("OPENPLC_CANOPEN_CONFIG_DIR")
    if env:
        return env
    if sys.platform == "darwin":
        return os.path.expanduser("~/Library/Application Support/openplc-canopen")
    if os.name == "nt":
        return os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "openplc-canopen")
    return os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), "openplc-canopen")


def _ordered(obj, kind):
    if not isinstance(obj, dict):
        return obj
    keys = ORDER.get(kind, [])
    out = {k: obj[k] for k in keys if k in obj}
    out.update((k, v) for k, v in obj.items() if k not in out)
    return out


def canonical(cfg):
    """The config with its keys in a fixed order (unknown keys kept)."""
    cfg = _ordered(cfg, "")
    if isinstance(cfg.get("adapter"), dict):
        cfg["adapter"] = _ordered(cfg["adapter"], "adapter")
    if isinstance(cfg.get("master"), dict):
        cfg["master"] = _ordered(cfg["master"], "master")
        if isinstance(cfg["master"].get("diagnostics"), dict):
            cfg["master"]["diagnostics"] = _ordered(cfg["master"]["diagnostics"], "diagnostics")
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


class ApiError(Exception):
    def __init__(self, status, message, **extra):
        super().__init__(message)
        self.status = status
        self.body = dict(error=message, **extra)


class Session:
    """What the page is editing. One user, one folder at a time."""

    def __init__(self):
        self.lock = threading.RLock()
        self.mode = None  # "project" | "standalone"
        self.folder = None
        self.loaded = None  # (mtime, sha256) of canopen.json as loaded, or None when there was none
        self.sim_loaded = None  # sha256 of simulation.json as loaded, or None when there was none
        self.pending = {}  # EDS name -> UTF-8 bytes imported but not yet saved
        self.pending_dir = tempfile.mkdtemp(prefix="canopen-config-")
        self.uses, self.scan_problems, self.scanned_at = [], [], None

    # -- paths --------------------------------------------------------------
    @property
    def canopen_dir(self):
        return os.path.join(self.folder, "canopen") if self.mode == "project" else self.folder

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
        items = [r for r in self.recent() if r["path"] != self.folder]
        items.insert(0, {"path": self.folder, "mode": self.mode})
        try:
            os.makedirs(config_dir(), exist_ok=True)
            tmp = os.path.join(config_dir(), "recent.json.tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(items[:RECENT_MAX], f, indent=2)
            os.replace(tmp, os.path.join(config_dir(), "recent.json"))
        except OSError:
            pass  # a convenience only

    # -- open / close -------------------------------------------------------
    def open(self, path, mode="auto"):
        path = os.path.abspath(os.path.expanduser(path or ""))
        is_project = os.path.isfile(os.path.join(path, "project.json"))
        if mode == "auto":
            mode = "project" if is_project else "standalone"
        if mode == "project":
            if not os.path.isdir(path):
                raise ApiError(404, "%s does not exist" % path)
            if not is_project:
                raise ApiError(422, "%s is not an OpenPLC editor project (it has no project.json)" % path,
                               not_a_project=True, path=path)
        elif mode == "standalone":
            if os.path.isfile(os.path.join(path, "project.json")):
                raise ApiError(422, "%s is an editor project; open it as a project" % path, is_project=True)
            if os.path.exists(path) and not os.path.isdir(path):
                raise ApiError(422, "%s is not a folder" % path)
        else:
            raise ApiError(400, "unknown mode %r" % mode)
        self.mode, self.folder = mode, path
        self.pending.clear()
        self.reload()
        self.remember()

    def close(self):
        self.mode = self.folder = self.loaded = self.sim_loaded = None
        self.pending.clear()

    def reload(self):
        self.pending.clear()
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
        except (OSError, ValueError) as e:
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

    def eds_names(self, cfg):
        names = [n.get("eds") for n in (cfg.get("nodes") or []) if isinstance(n, dict)]
        names = [n for n in names if isinstance(n, str) and n]
        if os.path.isdir(self.canopen_dir):
            names += [f for f in sorted(os.listdir(self.canopen_dir)) if f.lower().endswith(".eds")]
        names += list(self.pending)
        names += simulation.extra_eds(simulation.read(self.sim_path)["doc"])
        return list(dict.fromkeys(names))

    def state(self):
        base = {"version": __version__, "recent": self.recent(), "home": os.path.expanduser("~"),
                "mode": self.mode, "type_bits": {k: v[1] for k, v in CO_TYPES.items()},
                "default_start": layout.DEFAULT_START}
        if not self.mode:
            return base
        cfg, notices, error = self.read_config()
        sim = simulation.read(self.sim_path)
        sim_eds = simulation.eds_files(self.canopen_dir)
        referenced = {n.get("eds") for n in cfg.get("nodes", []) if isinstance(n, dict)}
        referenced.update(simulation.extra_eds(sim["doc"]))
        names = self.eds_names(cfg)
        base.update({
            "folder": self.folder, "name": os.path.basename(self.folder.rstrip(os.sep)) or self.folder,
            "canopen_dir": self.canopen_dir, "config_path": self.config_path,
            "config_exists": os.path.isfile(self.config_path), "config": cfg, "notices": notices,
            "load_error": error, "eds": self.eds_info(names),
            "unused_eds": [n for n in names if n not in referenced and n not in self.pending],
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

    # -- checks -------------------------------------------------------------
    def check(self, cfg, allow_overlap=False):
        if not isinstance(cfg, dict):
            raise ApiError(400, "config must be a JSON object")
        eds_paths = {n.get("eds"): self.eds_path(n.get("eds")) for n in cfg.get("nodes") or []
                     if isinstance(n, dict) and isinstance(n.get("eds"), str) and n.get("eds")}
        result = contract.check_config(cfg, self.config_path, eds_paths=eds_paths)
        items = list(result.items)
        extra, declared = layout.project_checks(cfg, self.uses, allow_overlap)
        items += extra
        decls, block = [], ""
        try:
            summaries = self.eds_info(list(eds_paths))
            names = {}
            for name, info in summaries.items():
                for o in info.get("objects", []):
                    names[(name, int(o["index"], 16), o["subindex"])] = o["name"]
            nodes = cfg.get("nodes") or []
            decls = declare.declarations(
                cfg, lambda i, ix, sub: names.get((nodes[i].get("eds"), ix, sub)), declared)
            block = declare.st_block(decls)
            axes = axis.text_block(cfg, decls)
            if axes:
                block = (block + "\n" if block else "") + axes
        except (KeyError, TypeError, ValueError, AttributeError):
            pass  # the contract errors already say what is wrong with the entries
        errors = sum(1 for i in items if i["level"] == "error")
        return {"items": items, "errors": errors, "declared": declared, "declarations": decls, "block": block,
                "overlaps": sum(1 for i in items if i.get("overlap"))}

    # -- DCF export ---------------------------------------------------------
    def export_dcf(self, cfg, node_id=None):
        """The draft's nodes as CiA 306 DCFs (canopen-dcf-export): one node's
        `node_<id>.dcf`, or all of them in `<folder>_dcf.zip`, base64 in
        `data`. On a problem: the /api/check shape, and no file. Nothing is
        written to the folder."""
        if not isinstance(cfg, dict):
            raise ApiError(400, "config must be a JSON object")
        if node_id is not None and (isinstance(node_id, bool) or not isinstance(node_id, int)):
            raise ApiError(400, "node must be a node ID")
        eds_paths = {n.get("eds"): self.eds_path(n.get("eds")) for n in cfg.get("nodes") or []
                     if isinstance(n, dict) and isinstance(n.get("eds"), str) and n.get("eds")}
        try:
            files, _ = dcfexport.export(cfg, self.config_path, eds_paths=eds_paths, node_id=node_id)
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
            folder = os.path.basename(self.folder.rstrip(os.sep)) or "canopen"
            name, data, ctype = folder + "_dcf.zip", buf.getvalue(), "application/zip"
        return {"items": [], "errors": 0, "name": name, "content_type": ctype,
                "files": sorted(files), "data": base64.b64encode(data).decode("ascii")}

    # -- DBC export ---------------------------------------------------------
    def export_dbc(self, cfg, sdo="none"):
        """The draft as a DBC file (canopen-dbc-export): `<folder>.dbc`, base64
        in `data`, with the export's warnings as items. Signal names use the
        project's located variables in project mode. On a problem: the
        /api/check shape, and no file. Nothing is written to the folder."""
        if not isinstance(cfg, dict):
            raise ApiError(400, "config must be a JSON object")
        if sdo not in dbcexport.SDO_OPTIONS:
            raise ApiError(400, "sdo must be one of: " + ", ".join(dbcexport.SDO_OPTIONS))
        eds_paths = {n.get("eds"): self.eds_path(n.get("eds")) for n in cfg.get("nodes") or []
                     if isinstance(n, dict) and isinstance(n.get("eds"), str) and n.get("eds")}
        names = dbcexport.plc_names(self.uses) if self.mode == "project" else None
        try:
            text, warnings = dbcexport.export(cfg, self.config_path, eds_paths=eds_paths, sdo=sdo, names=names)
        except dbcexport.ExportFailed as e:
            items = [{"level": "error", "message": m, "paths": p} for m, p in e.problems]
            return {"items": items, "errors": len(items)}
        folder = os.path.basename(self.folder.rstrip(os.sep)) or "canopen"
        return {"items": [{"level": "warning", "message": w, "paths": []} for w in warnings], "errors": 0,
                "name": folder + ".dbc", "content_type": "application/octet-stream",
                "data": base64.b64encode(text.encode("ascii")).decode("ascii")}

    # -- where a new entry or status bit goes ------------------------------
    def place(self, cfg, node, direction, type_name, start=None):
        """Suggested location (and PDO, for an entry) for something new in
        node `node`: direction "input"/"output" with a CANopen type, or
        direction "status" for the node's status bit, "state" for its
        state byte, "boot_error" for its boot error byte, "emcy" for its
        EMCY code word, "errreg" for its error register byte, "nmt" for its
        NMT command byte, "sdo_read"/"sdo_write" with a CANopen type for an
        SDO variable's value, "sdo_trigger", "sdo_status" or "sdo_abort" for
        an SDO variable's other locations, or a master diagnostic key (no
        node needed)."""
        used = layout.taken(cfg, self.uses) if isinstance(cfg, dict) else set()
        start = layout.DEFAULT_START if start in (None, "") else int(start)
        for key, size, _, _ in layout.MASTER_LOCATIONS:
            if direction == key:
                return {"location": layout.suggest("I", size, used, start)}
        try:
            n = cfg["nodes"][int(node)]
        except (KeyError, IndexError, TypeError, ValueError):
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

    # -- CiA 402 axis -------------------------------------------------------
    def map_cia402(self, cfg, node, start=None):
        """Node `node` of the draft with the standard CiA 402 objects its EDS
        has put into PDOs (cia402map), and its status bit when it has none:
        {node, mapped, missing}. Nothing is saved."""
        if not isinstance(cfg, dict):
            raise ApiError(400, "config must be a JSON object")
        try:
            n = cfg["nodes"][int(node)]
        except (KeyError, IndexError, TypeError, ValueError):
            raise ApiError(400, "no node %r in the config" % node)
        info = self.eds_info([n.get("eds")]).get(n.get("eds"), {}) if n.get("eds") else {}
        if not info or info.get("error"):
            raise ApiError(400, info.get("error") or "the node has no EDS file")
        start = layout.DEFAULT_START if start in (None, "") else int(start)
        new, mapped, missing = cia402map.map_objects(n, info, layout.taken(cfg, self.uses), start)
        return {"node": new, "mapped": mapped, "missing": missing}

    # -- save ---------------------------------------------------------------
    def save(self, cfg, allow_overlap=False, overwrite=False):
        checked = self.check(cfg, allow_overlap)
        if checked["errors"]:
            raise ApiError(422, "the config has %d error%s; nothing was saved"
                           % (checked["errors"], "" if checked["errors"] == 1 else "s"), check=checked)
        if not overwrite and self.changed_on_disk():
            raise ApiError(409, "%s changed on disk after it was loaded" % self.config_path, changed_on_disk=True)
        os.makedirs(self.canopen_dir, exist_ok=True)
        written = []
        referenced = {n["eds"] for n in cfg.get("nodes", [])}
        for name, data in sorted(self.pending.items()):
            if name not in referenced:
                continue
            target = os.path.join(self.canopen_dir, name)
            tmp = target + ".tmp"
            with open(tmp, "wb") as f:
                f.write(data)
            os.replace(tmp, target)
            written.append(target)
        tmp = self.config_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(canonical(cfg), f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp, self.config_path)
        written.append(self.config_path)
        for name in [n for n in self.pending if n in referenced]:
            del self.pending[name]
        self.loaded = (os.path.getmtime(self.config_path), sha256(self.config_path))
        return {"written": written, "check": checked}

    # -- the simulation file -------------------------------------------------
    def sim_changed_on_disk(self):
        exists = os.path.isfile(self.sim_path)
        if self.sim_loaded is None:
            return exists
        return not exists or sha256(self.sim_path) != self.sim_loaded

    def save_simulation(self, doc, overwrite=False):
        """Writes canopen/simulation.json after the schema check, with the EDS
        files its extra devices name that were imported but not saved yet.
        Like canopen.json, only into the project's config folder."""
        problems = simulation.check(doc)
        if problems:
            raise ApiError(422, "the simulation file has %d error%s; nothing was saved"
                           % (len(problems), "" if len(problems) == 1 else "s"), problems=problems)
        if not overwrite and self.sim_changed_on_disk():
            raise ApiError(409, "%s changed on disk after it was loaded" % self.sim_path, changed_on_disk=True)
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
        if self.pending or self.changed_on_disk() or not os.path.isfile(self.config_path):
            raise ApiError(409, "save the config before moving it into a project", unsaved=True)
        target = os.path.abspath(os.path.expanduser(target or ""))
        if not os.path.isfile(os.path.join(target, "project.json")):
            raise ApiError(422, "%s is not an OpenPLC editor project (it has no project.json)" % target)
        if os.path.lexists(os.path.join(target, "canopen")) and not replace:
            raise ApiError(409, "%s already has a canopen folder" % target, exists=True)
        with open(self.config_path, encoding="utf-8") as f:
            cfg = json.load(f)
        result = contract.check_config(cfg, self.config_path)
        if not result.ok:
            raise ApiError(422, "\n".join(result.errors))
        try:
            written, converted = project_mod.write(cfg, self.config_path, target, force=replace)
        except project_mod.ProjectError as e:
            raise ApiError(422, str(e))
        self.open(target, "project")
        return {"written": written, "converted": converted}


    # -- a new editor project around a standalone config --------------------
    def new_project(self, parent, name, interval=None, sdo_blocks=False):
        if self.mode != "standalone":
            raise ApiError(400, "only a standalone config can become a new editor project")
        if self.pending or self.changed_on_disk() or not os.path.isfile(self.config_path):
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
                                               runtime_address=address, sdo_blocks=sdo_blocks)
        except editorproject.NewProjectError as e:
            raise ApiError(422, str(e))
        self.open(path, "project")
        out = {"project": path, "declared": len(decls)}
        if sdo_blocks:
            out["library_ok"], out["library"] = sdolibrary.ensure_installed()
        return out


def list_folders(path):
    path = os.path.abspath(os.path.expanduser(path or "~"))
    if not os.path.isdir(path):
        raise ApiError(404, "%s is not a folder" % path)
    entries = []
    try:
        names = sorted(os.listdir(path), key=str.lower)
    except OSError as e:
        raise ApiError(403, "%s cannot be listed: %s" % (path, e))
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
    server_version = "openplc-canopen-config/" + __version__

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
            return self._deny("open the URL printed by openplc-canopen-config (it carries the session token)")
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
                body = self._body() if method == "POST" else {}
                return self._send(200, self._sim((method, url.path), body))
            if url.path.startswith("/api/trace/"):
                if (method, url.path) == ("POST", "/api/trace/open") and \
                        (self.headers.get("Content-Type") or "").startswith("application/octet-stream"):
                    # A trace file as it is: large files do not fit a JSON body.
                    length = int(self.headers.get("Content-Length") or 0)
                    if length > MAX_TRACE_FILE:
                        raise ApiError(413, "the file is larger than %d MiB" % (MAX_TRACE_FILE >> 20))
                    body = {"raw": self.rfile.read(length), "name": query.get("name", ["trace"])[0]}
                else:
                    body = self._body() if method == "POST" else {}
                try:
                    return self._send(200, self._trace((method, url.path), body))
                except tracing.Refused as e:
                    raise ApiError(e.status, str(e), **e.extra)
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
                    s.open(body.get("path"), body.get("mode", "auto"))
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
                elif route == ("POST", "/api/check"):
                    self._need_open(s)
                    out = s.check(body.get("config"), bool(body.get("allow_overlap")))
                elif route == ("POST", "/api/export_dbc"):
                    self._need_open(s)
                    out = s.export_dbc(body.get("config"), body.get("sdo", "none"))
                elif route == ("POST", "/api/export_dcf"):
                    self._need_open(s)
                    out = s.export_dcf(body.get("config"), body.get("node"))
                elif route == ("POST", "/api/place"):
                    self._need_open(s)
                    out = s.place(body.get("config"), body.get("node"), body.get("direction"), body.get("type"),
                                  body.get("start"))
                elif route == ("POST", "/api/map_cia402"):
                    self._need_open(s)
                    out = s.map_cia402(body.get("config"), body.get("node"), body.get("start"))
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
        except Exception as e:  # pragma: no cover - shown in the page instead of a dropped connection
            self._send(500, {"error": "%s: %s" % (type(e).__name__, e)})

    @staticmethod
    def _need_open(s):
        if not s.mode:
            raise ApiError(409, "no project or config folder is open")

    def _watch(self, settings, folder, body):
        """The object dictionary watch lists of this project, kept per node in
        online.json on this PC: {"node": N} reads one, with "keys" (and
        "period_ms") it is replaced; an empty key list removes it."""
        node = body.get("node")
        if isinstance(node, bool) or not isinstance(node, int) or not 1 <= node <= 127:
            raise ApiError(400, "node must be 1-127")
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
                lists[str(node)] = {"keys": clean, "period_ms": period}
            else:
                lists.pop(str(node), None)
            settings.update_project(folder, watch=lists or None)
        got = lists.get(str(node)) or {}
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
                    "connected": conn.connected}

        if route == ("GET", "/api/online/settings"):
            return view()
        if route == ("POST", "/api/online/settings"):
            if "host" in body:
                host = (body.get("host") or "").strip()
                if host:
                    try:
                        diag.parse_runtime(host)
                    except ValueError as e:
                        raise ApiError(422, str(e))
                settings.update_project(folder, host=host or None)
                conn.close()
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
                want = (body.get("token_sha256") or "").strip().lower()
                if not token:
                    raise ApiError(422, "enter the token")
                if want and diag.hash_token(token) != want:
                    raise ApiError(422, "this token does not match token_sha256 in the configuration")
            elif action == "forget":
                settings.update_project(folder, token=None)
                conn.close()
                return view()
            else:
                raise ApiError(400, "action must be generate, set or forget")
            settings.update_project(folder, token=token)
            conn.close()
            return dict(view(), token_sha256=diag.hash_token(token))
        if route == ("POST", "/api/online/close"):
            conn.close()
            return {"closed": True}
        if route == ("POST", "/api/online/use_eds"):
            return self._use_eds(s, settings, canopen_dir, body.get("path"), body.get("eds_lint"))
        if route == ("POST", "/api/online/watch"):
            return self._watch(settings, folder, body)

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

        def call(fn):
            try:
                return conn.call(hostname, port, token, fn)
            except diag.DiagError as e:
                raise ApiError(422 if e.kind == "refused" else 502, str(e), kind=e.kind)

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
            client = params.Client(conn, hostname, port, token)
            try:
                return params.handle(route, body, s, conn, self.server.jobs, client, node, settings.eds_library,
                                     host)
            except params.Refused as e:
                raise ApiError(e.status, str(e))
            except diag.DiagError as e:
                raise ApiError(422 if e.kind == "refused" else 502, str(e), kind=e.kind)
        if route == ("POST", "/api/online/status"):
            st = call(lambda c: c.status())
            prints = online.fingerprints(config_path)
            same = st.get("config_sha256") in prints
            return {"hello": conn.info, "status": st,
                    "config": "none" if not prints else ("same" if same else "different")}
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
        if route == ("POST", "/api/online/scan"):
            res = call(lambda c: c.scan(bool(body.get("start"))))
            if res.get("nodes") is not None:
                self._match_scan(s, settings, canopen_dir, res, body.get("config"))
            return res
        raise ApiError(404, "no such API: %s %s" % route)

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
            return {"problems": simulation.check(body.get("doc"))}
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

        def call(fn):
            host, port, token, kind = where()
            try:
                return conn.call(host, port, token, fn), kind
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
            return self._check_expr_offline(s, expr, node, body.get("doc"))
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
            fields = {k: v for k, v in body.items() if k not in ("op", "port")}
            res, kind = call(lambda c: c.request(op, **fields))
            return {"result": res, "target": kind}
        raise ApiError(404, "no such API: %s %s" % route)

    @staticmethod
    def _check_expr_offline(s, expr, node, doc):
        """An expression checked on this PC (simulation.check_offline), with
        the devices of the config and of the draft simulation file."""
        with s.lock:
            cfg = s.read_config()[0]
            if not isinstance(doc, dict):
                doc = simulation.read(s.sim_path)["doc"]
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
        base_name = os.path.basename(folder.rstrip(os.sep)) or "canopen"
        traces_dir = os.path.join(config_dir(), "traces")

        def decoder():
            cfg = body.get("config")
            with s.lock:
                if not isinstance(cfg, dict):
                    cfg = s.read_config()[0]
                eds_paths = {n.get("eds"): s.eds_path(n.get("eds")) for n in cfg.get("nodes") or []
                             if isinstance(n, dict) and isinstance(n.get("eds"), str) and n.get("eds")}
            return tracing.decoder_for(cfg, config_path, eds_paths, names)

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
            host, token = proj.get("host"), proj.get("token")
            if not host or not token:
                raise ApiError(409, "set up online access (runtime host and access token) in the Online view to "
                                    "record a trace; opening trace files works without it", need="online")
            try:
                hostname, port = diag.parse_runtime(host)
            except ValueError as e:
                raise ApiError(422, str(e))
            if ":" not in host.rsplit("]", 1)[-1] and isinstance(body.get("port"), int):
                port = body["port"]
            connect = tracing.connector(hostname, port, token)
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
            ws.start(connect, dec, filters, bool(body.get("error_frames")), spec, traces_dir, base_name)
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
            ws.open(trace, name, decoder())
            return state()
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

    def _match_scan(self, s, settings, canopen_dir, res, cfg):
        """Adds to each scanned device the EDS files that match it and, for a
        configured node, what the config expects."""
        if not isinstance(cfg, dict):
            with s.lock:
                cfg = s.read_config()[0]
        by_id = {}
        for n in cfg.get("nodes") or []:
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
        in canopen/ as it is, one from the EDS library imported as an EDS
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


class Server(http.server.ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, port=0, token=None, verbose=False):
        super().__init__(("127.0.0.1", port), Handler)
        self.token = token or secrets.token_urlsafe(32)
        self.session = Session()
        self.verbose = verbose
        self.connection = online.Connection()
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
        self.traces.stop_all()
        self.connection.close()
        shutil.rmtree(self.session.pending_dir, ignore_errors=True)


def parser():
    p = argparse.ArgumentParser(
        prog="openplc-canopen-config",
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
    server = Server(args.port, verbose=args.verbose)
    if args.path:
        try:
            server.session.open(args.path)
        except ApiError as e:
            print("openplc-canopen-config: %s" % e, file=sys.stderr)
            server.server_close()
            return 2
    print("CANopen configurator: %s" % server.url, flush=True)
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
