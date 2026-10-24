"""Import from CODESYS in the configurator (canopen-configurator "Import
from CODESYS", "Import preview"): one import at a time, kept between the
dialog's steps. A .project is exported headless by CODESYS on this PC first
(minutes), so the server calls open() outside its session lock."""

import copy
import os
import re
import shutil
import tempfile

from ..codesys import run as codesys_run, xmlimport


class Refused(Exception):
    def __init__(self, message, status=400, **extra):
        super().__init__(message)
        self.status, self.extra = status, extra


NO_CODESYS = ("CODESYS is not installed on this PC, so a .project cannot be read here. In CODESYS, export the "
              "device with the CANopen Manager (Project > Export PLCopenXML) and import that .xml file.")


class Import(object):
    """One import: the source, the chosen device, EDS files added in the
    preview, the last conversion."""

    def __init__(self):
        self.source = None      # the name the user picked
        self.project = None     # the .project path, when it came from one
        self.xml = None         # bytes of the PLCopenXML
        self.device = None
        self.choice = None      # the device's entry of xmlimport.choices()
        self.result = None
        self.added = {}         # (type, id, version) -> EDS path added in the preview
        self.folder = tempfile.mkdtemp(prefix="canworks-codesys-import-")

    def close(self):
        shutil.rmtree(self.folder, ignore_errors=True)


def open_source(imp, path=None, name=None, data=None, device=None, found=False, runner=None):
    """Reads the source into `imp`: {"devices": [...]} when the device is
    still to be chosen, else None (convert next)."""
    if path:
        path = os.path.abspath(os.path.expanduser(path))
        imp.source = os.path.basename(path)
        if path.lower().endswith(".project"):
            if not found:
                raise Refused(NO_CODESYS, no_codesys=True)
            if not os.path.isfile(path):
                raise Refused("%s does not exist" % path, 404)
            export = os.path.join(imp.folder, "export")
            os.makedirs(export, exist_ok=True)
            try:
                devices, xml = codesys_run.export_project(path, device=device, runner=runner, folder=export)
            except codesys_run.CodesysError as e:
                raise Refused(str(e), 422)
            imp.project = path
            if xml is None:
                if not devices:
                    raise Refused("%s has no device with a CANopen Manager" % imp.source, 422)
                return {"devices": devices}
            with open(xml, "rb") as f:
                imp.xml = f.read()
        else:
            try:
                with open(path, "rb") as f:
                    imp.xml = xmlimport.read_text(f.read())
            except OSError as e:
                raise Refused("%s cannot be read: %s" % (path, e.strerror or e), 404)
    else:
        imp.source = name or "the file"
        if imp.source.lower().endswith(".project"):
            raise Refused(NO_CODESYS if not found else
                          "Pick the .project with Choose project… so CODESYS on this PC can read it.", no_codesys=not found)
        imp.xml = xmlimport.read_text(data or b"")
    try:
        choices = xmlimport.choices(xmlimport.read(imp.xml))
    except xmlimport.ImportError_ as e:
        raise Refused("%s: %s" % (imp.source, e), 422)
    if not choices:
        raise Refused("%s holds no CANopen Manager" % imp.source, 422)
    if device and len(choices) > 1:
        choices = [c for c in choices if c["name"] == device]
        if not choices:
            raise Refused("%s has no device %s with a CANopen Manager" % (imp.source, device), 422)
    if len(choices) > 1:
        return {"devices": [{"name": c["name"], "buses": [b.name for b in c["buses"]], "nodes": c["nodes"],
                             "active": False} for c in choices]}
    imp.choice = choices[0]
    imp.device = choices[0]["name"] or device
    return None


def convert(imp, index_matches, folders, roots):
    """The preview of the import: networks with their node rows, the
    not-carried report, and whether Create config can go."""
    find = xmlimport.library_finder(lambda v, p, r: index_matches(folders, v, p, r), roots)

    def with_added(ident):
        d = ident.get("device") or {}
        path = imp.added.get((d.get("type"), d.get("id"), d.get("version")))
        return {"path": path, "state": "added"} if path else find(ident)
    try:
        imp.result = xmlimport.convert(imp.choice, with_added, project=imp.project)
    except xmlimport.ImportError_ as e:
        raise Refused(str(e), 422)
    if imp.device:
        imp.result.cfg["codesys"].setdefault("device", imp.device)
    return preview(imp)


def preview(imp):
    res = imp.result
    nets = []
    for net in res.cfg["networks"]:
        rows = [r for r in res.nodes if r["network"] == net["name"]]
        nets.append({"name": net["name"], "net_id": net["codesys"]["net_id"],
                     "bitrate": net["adapter"].get("bitrate"), "nodes": [_row(r) for r in rows]})
    return {"source": imp.source, "project": imp.project, "device": imp.device, "networks": nets,
            "report": res.report, "missing": len(res.missing)}


def _row(r):
    out = {k: r.get(k) for k in ("node_id", "name", "device", "eds", "eds_state", "note", "vendor_id",
                                 "product_code", "revision_number")}
    return out


def add_eds(imp, node_device, name, path):
    """An EDS added in the preview for a node's CODESYS device type: every
    node of that device type takes it."""
    if not imp.result:
        raise Refused("nothing to add an EDS to: import a file first", 409)
    key = None
    for dev in _devices(imp):
        if dev.name == node_device:
            key = (dev.type, dev.id, dev.version)
    if key is None:
        raise Refused("no device %s in the import" % node_device, 404)
    folder = os.path.join(imp.folder, "eds-%d" % len(imp.added))
    os.makedirs(folder, exist_ok=True)
    target = os.path.join(folder, os.path.basename(name))
    shutil.copyfile(path, target)
    imp.added[key] = target


def _devices(imp):
    out = []
    for bus in imp.choice["buses"]:
        for mgr in bus.children:
            out.extend(mgr.children)
    return out


def create(imp, folder):
    """Writes the imported config and its EDS files into folder."""
    if not imp.result:
        raise Refused("nothing imported yet", 409)
    try:
        return xmlimport.write(imp.result, folder)
    except xmlimport.ImportError_ as e:
        raise Refused("%s; nothing was written" % e, 422)


def _key(name):
    return str(name or "").lower()


def _net_id(net):
    """A config network's CODESYS network number, as a build gives it."""
    own = net.get("codesys") if isinstance(net.get("codesys"), dict) else {}
    if isinstance(own.get("net_id"), int):
        return own["net_id"]
    iface = (net.get("adapter") or {}).get("interface") if isinstance(net.get("adapter"), dict) else None
    m = re.search(r"(\d+)$", iface) if isinstance(iface, str) else None
    return int(m.group(1)) if m else 0


def _clashes(old, net):
    return _key(old.get("name")) == _key(net["name"]) or _net_id(old) == net["codesys"]["net_id"]


def conflicts(imp, cfg):
    """The imported networks whose name or CODESYS network number the
    config uses already: [{name, net_id, with, reason ("name" or "net_id"),
    with_net_id, with_role ("master" or "slave")}] (codesys-import "Clash
    reason in the import"; the imported networks are masters)."""
    have = [n for n in (cfg.get("networks") or []) if isinstance(n, dict)]
    out = []
    for net in imp.result.cfg["networks"]:
        for k, old in enumerate(have):
            if _clashes(old, net):
                out.append({"name": net["name"], "net_id": net["codesys"]["net_id"],
                            "with": old.get("name") or "network %d" % (k + 1),
                            "reason": "name" if _key(old.get("name")) == _key(net["name"]) else "net_id",
                            "with_net_id": _net_id(old),
                            "with_role": "slave" if old.get("role") == "slave" else "master"})
                break
    return out


def merge(imp, cfg, answers, renamed):
    """The config with the imported networks added: `answers` {network:
    "rename" | "replace"} for each conflict, `renamed` {EDS name in the
    import: its name in the config}."""
    out = copy.deepcopy(cfg)
    nets = out.setdefault("networks", [])
    for net in imp.result.cfg["networks"]:
        new = copy.deepcopy(net)
        for node in new["nodes"]:
            node["eds"] = renamed.get(node["eds"], node["eds"])
        clash = [c for c in conflicts(imp, out) if c["name"] == net["name"]]
        if clash:
            answer = answers.get(net["name"])
            if answer not in ("rename", "replace"):
                raise Refused("network %s: answer rename or replace" % net["name"], 409, conflicts=conflicts(imp, out))
            k = next(i for i, old in enumerate(nets) if isinstance(old, dict) and _clashes(old, net))
            if answer == "replace":
                nets[k] = new
                continue
            names = {_key(n.get("name")) for n in nets if isinstance(n, dict)}
            ids = {_net_id(n) for n in nets if isinstance(n, dict)}
            base = re.sub(r"\d+$", "", new["name"]) or "can"
            i = 2
            while _key("%s%d" % (base, i)) in names:
                i += 1
            new["name"] = ("%s%d" % (base, i))[:16]
            if new["codesys"]["net_id"] in ids:
                free = next(i for i in range(256) if i not in ids)
                new["codesys"]["net_id"] = free
                new["adapter"]["interface"] = "can%d" % free
        nets.append(new)
    top = out.setdefault("codesys", {})
    for key in ("project", "device"):
        if imp.result.cfg["codesys"].get(key) and not top.get(key):
            top[key] = imp.result.cfg["codesys"][key]
    return out
