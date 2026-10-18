"""--into-project: the config and its EDS files in an editor project's
canworks/ folder, where the editor's project snapshot carries them to the
runtime's editor hook (tools/editor-hook):

    <project>/canworks/canworks.json    (each node's and slave's eds -> "<name>")
    <project>/canworks/<name>.eds
    <project>/canworks/simulation.json (the simulation file, if any: each
                                       extra device's eds and each CSV
                                       file -> "<name>")
    <project>/canworks/<name>.csv      (the simulation file's CSV files)
    <project>/canworks/<name>.dbc      (each network's j1939.dbc and raw.dbc
                                       -> "<name>")
    <project>/canworks/<eds>.notes.json (each EDS file's device notes)

With force, an existing canworks/ folder is kept as canworks.bak-<time>,
so files only it holds are not lost.

The editor reads every project file as UTF-8 text when it builds the
snapshot, so EDS files are stored as UTF-8; one that is not valid UTF-8 is
converted from CP1252 (Latin-1 for the bytes CP1252 leaves undefined).
"""

import json
import os
import shutil
import time

from . import bundle, contract, notes, simfile
from .eds import to_utf8  # noqa: F401 (the configurator imports it from here)

DIR = "canworks"
CONFIG = "canworks.json"
SIM = simfile.FILE_NAME


class ProjectError(Exception):
    pass


def dbc_refs(cfg):
    """The objects of the config that name a DBC file in "dbc": each J1939
    network's j1939 object and each network's raw object."""
    out = []
    for n in contract.networks(cfg):
        net = n.get("json") if isinstance(n.get("json"), dict) else {}
        for obj in (net.get("j1939") if n["role"] == "j1939" else None, net.get("raw")):
            if isinstance(obj, dict) and isinstance(obj.get("dbc"), str) and obj["dbc"]:
                out.append(obj)
    return out


def _backup_path(target):
    stamp = time.strftime("%Y%m%d-%H%M%S")
    path, n = "%s.bak-%s" % (target, stamp), 1
    while os.path.lexists(path):
        n += 1
        path = "%s.bak-%s-%d" % (target, stamp, n)
    return path


def write(cfg, config_path, project_dir, force=False, sim_path=None, report=None):
    """Writes the project's canworks/ folder. Returns (paths written, names of
    converted EDS and DBC files). The config (and the simulation file
    sim_path, when given) must already have passed the checks. With force an
    existing folder is renamed to canworks.bak-<time>; its path goes into
    report["backup"] when `report` is a dict."""
    if not os.path.isdir(project_dir):
        raise ProjectError("%s is not a directory" % project_dir)
    if not os.path.isfile(os.path.join(project_dir, "project.json")):
        raise ProjectError("%s is not an OpenPLC Editor project (it has no project.json)" % project_dir)
    target = os.path.join(project_dir, DIR)
    if os.path.lexists(target) and not force:
        raise ProjectError("%s already exists; pass --force to replace it" % target)
    try:
        _, by_name = bundle.rewrite(cfg, config_path)
    except bundle.BundleError as e:
        raise ProjectError(str(e))
    files = bundle.eds_files(cfg, config_path)
    out = json.loads(json.dumps(cfg))
    for n in contract.eds_users(out):
        n["eds"] = os.path.basename(files[n["eds"]])
    # Each EDS's device notes go along (the configurator reads them next to it).
    notes_by_name = {name + notes.SUFFIX: notes.notes_path(src) for name, src in by_name.items()
                     if os.path.isfile(notes.notes_path(src))}
    base = os.path.dirname(os.path.abspath(config_path))
    dbcs = {}
    for obj in dbc_refs(out):
        src = obj["dbc"] if os.path.isabs(obj["dbc"]) else os.path.join(base, obj["dbc"])
        obj["dbc"] = os.path.basename(src)
        if os.path.isfile(src):
            try:
                bundle.merge_by_name(dbcs, {obj["dbc"]: src}, "DBC files")
            except bundle.BundleError as e:
                raise ProjectError(str(e))
    sim_out, csv = None, {}
    if sim_path:
        try:
            sim_data = simfile.load(sim_path)
            files = simfile.referenced_files(sim_data, sim_path)
            bundle.merge_by_name(by_name, bundle._by_name(files["eds"], "EDS files"), "EDS files")
            csv = bundle._by_name(files["csv"], "CSV files")
        except (simfile.SimFileError, bundle.BundleError) as e:
            raise ProjectError(str(e))
        sim_out = simfile.rewrite(sim_data, sim_path, os.path.basename, os.path.basename)
    for reserved in (CONFIG, SIM):
        if reserved in by_name or reserved in csv:
            raise ProjectError("an EDS or CSV file may not be named %s" % reserved)
    for name in set(dbcs) & (set(by_name) | set(csv) | set(notes_by_name)):
        raise ProjectError("a DBC file and another file are both named %s; rename one" % name)
    for name in set(notes_by_name) & set(csv):
        raise ProjectError("a CSV file and a notes file are both named %s; rename one" % name)
    for name in set(csv) & set(by_name):
        raise ProjectError("a CSV file of the simulation and an EDS file are both named %s; rename one" % name)
    csv_data = {}
    for name, src in sorted(csv.items()):
        with open(src, "rb") as f:
            csv_data[name] = f.read()
        try:
            csv_data[name].decode("utf-8")
        except UnicodeDecodeError:
            raise ProjectError("CSV file %s is not UTF-8 text: the editor's project upload would corrupt it"
                               % src)

    staged = target + ".new"
    shutil.rmtree(staged, ignore_errors=True)
    os.makedirs(staged)
    converted = []
    try:
        for name, src in sorted(by_name.items()):
            with open(src, "rb") as f:
                data, was = to_utf8(f.read())
            if was:
                converted.append(name)
            with open(os.path.join(staged, name), "wb") as f:
                f.write(data)
        for name, data in csv_data.items():
            with open(os.path.join(staged, name), "wb") as f:
                f.write(data)
        for name, src in sorted(dbcs.items()):
            with open(src, "rb") as f:
                data, was = to_utf8(f.read())
            if was:
                converted.append(name)
            with open(os.path.join(staged, name), "wb") as f:
                f.write(data)
        for name, src in sorted(notes_by_name.items()):
            shutil.copyfile(src, os.path.join(staged, name))
        if sim_out is not None:
            with open(os.path.join(staged, SIM), "w", encoding="utf-8") as f:
                json.dump(sim_out, f, indent=2)
                f.write("\n")
        with open(os.path.join(staged, CONFIG), "w", encoding="utf-8") as f:
            json.dump(out, f, indent=2)
            f.write("\n")
        # What the editor hook will check, on the files as they now are.
        result = contract.check_config(out, os.path.join(target, CONFIG),
                                       eds_paths={v: os.path.join(staged, v) for v in by_name})
        if not result.ok:
            raise ProjectError("\n".join(result.errors))
        if sim_out is not None:
            result = simfile.check(sim_out, os.path.join(staged, SIM), out, os.path.join(staged, CONFIG),
                                   eds_paths={v: os.path.join(staged, v) for v in by_name})
            if not result.ok:
                raise ProjectError("\n".join(result.errors))
        if os.path.lexists(target):
            # Kept, not deleted: it may hold notes, DBC or other files of the user's.
            backup = _backup_path(target)
            os.rename(target, backup)
            if isinstance(report, dict):
                report["backup"] = backup
        os.rename(staged, target)
    finally:
        shutil.rmtree(staged, ignore_errors=True)
    written = [os.path.join(target, CONFIG)] + ([os.path.join(target, SIM)] if sim_out is not None else []) + [
        os.path.join(target, n) for n in sorted(set(by_name) | set(csv) | set(dbcs)
                                                | set(notes_by_name))]
    return written, converted
