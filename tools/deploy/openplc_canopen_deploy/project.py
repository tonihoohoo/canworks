"""--into-project: the config and its EDS files in an editor project's
canopen/ folder, where the editor's project snapshot carries them to the
runtime's editor hook (tools/editor-hook):

    <project>/canopen/canopen.json    (each node's eds -> "<name>")
    <project>/canopen/<name>.eds
    <project>/canopen/<name>          (a node's software_file, if any)
    <project>/canopen/simulation.json (the simulation file, if any: each
                                       extra device's eds and each CSV
                                       file -> "<name>")
    <project>/canopen/<name>.csv      (the simulation file's CSV files)

The editor reads every project file as UTF-8 text when it builds the
snapshot, so EDS files are stored as UTF-8; one that is not valid UTF-8 is
converted from CP1252 (Latin-1 for the bytes CP1252 leaves undefined). A
program file that is not valid UTF-8 would arrive corrupted, so it is
refused: deploy such a project with the deploy tool instead.
"""

import json
import os
import shutil

from . import bundle, contract, simfile
from .eds import to_utf8  # noqa: F401 (the configurator imports it from here)

DIR = "canopen"
CONFIG = "canopen.json"
SIM = simfile.FILE_NAME


class ProjectError(Exception):
    pass


def write(cfg, config_path, project_dir, force=False, sim_path=None):
    """Writes the project's canopen/ folder. Returns (paths written, names of
    converted EDS files). The config (and the simulation file sim_path, when
    given) must already have passed the checks."""
    if not os.path.isdir(project_dir):
        raise ProjectError("%s is not a directory" % project_dir)
    if not os.path.isfile(os.path.join(project_dir, "project.json")):
        raise ProjectError("%s is not an OpenPLC editor project (it has no project.json)" % project_dir)
    target = os.path.join(project_dir, DIR)
    if os.path.lexists(target) and not force:
        raise ProjectError("%s already exists; pass --force to replace it" % target)
    try:
        _, by_name = bundle.rewrite(cfg, config_path)
    except bundle.BundleError as e:
        raise ProjectError(str(e))
    files = bundle.eds_files(cfg, config_path)
    try:
        fw = bundle.software_by_name(cfg, config_path)
    except bundle.BundleError as e:
        raise ProjectError(str(e))
    software = bundle.software_files(cfg, config_path)
    out = json.loads(json.dumps(cfg))
    for n in contract.all_nodes(out):
        n["eds"] = os.path.basename(files[n["eds"]])
        if n.get("software_file"):
            n["software_file"] = os.path.basename(software[n["software_file"]])
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
        if reserved in by_name or reserved in fw or reserved in csv:
            raise ProjectError("an EDS, program or CSV file may not be named %s" % reserved)
    for name in set(by_name) & set(fw):
        raise ProjectError("an EDS file and a program file are both named %s; rename one" % name)
    for name in set(csv) & (set(by_name) | set(fw)):
        raise ProjectError("a CSV file of the simulation and an EDS or program file are both named %s; rename one"
                           % name)
    csv_data = {}
    for name, src in sorted(csv.items()):
        with open(src, "rb") as f:
            csv_data[name] = f.read()
        try:
            csv_data[name].decode("utf-8")
        except UnicodeDecodeError:
            raise ProjectError("CSV file %s is not UTF-8 text: the editor's project upload would corrupt it" % src)
    fw_data = {}
    for name, src in sorted(fw.items()):
        with open(src, "rb") as f:
            fw_data[name] = f.read()
        try:
            fw_data[name].decode("utf-8")
        except UnicodeDecodeError:
            raise ProjectError("program file %s is binary: the editor's project upload would corrupt it. Deploy "
                               "this config with openplc-canopen-deploy --runtime instead of --into-project" % src)

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
        for name, data in list(fw_data.items()) + list(csv_data.items()):
            with open(os.path.join(staged, name), "wb") as f:
                f.write(data)
        if sim_out is not None:
            with open(os.path.join(staged, SIM), "w", encoding="utf-8") as f:
                json.dump(sim_out, f, indent=2)
                f.write("\n")
        with open(os.path.join(staged, CONFIG), "w", encoding="utf-8") as f:
            json.dump(out, f, indent=2)
            f.write("\n")
        # What the editor hook will check, on the files as they now are.
        result = contract.check_config(out, os.path.join(target, CONFIG),
                                       eds_paths={v: os.path.join(staged, v) for v in by_name},
                                       software_paths={v: os.path.join(staged, v) for v in fw})
        if not result.ok:
            raise ProjectError("\n".join(result.errors))
        if sim_out is not None:
            result = simfile.check(sim_out, os.path.join(staged, SIM), out, os.path.join(staged, CONFIG),
                                   eds_paths={v: os.path.join(staged, v) for v in by_name})
            if not result.ok:
                raise ProjectError("\n".join(result.errors))
        if os.path.lexists(target):
            shutil.rmtree(target) if os.path.isdir(target) and not os.path.islink(target) else os.remove(target)
        os.rename(staged, target)
    finally:
        shutil.rmtree(staged, ignore_errors=True)
    written = [os.path.join(target, CONFIG)] + ([os.path.join(target, SIM)] if sim_out is not None else []) + [
        os.path.join(target, n) for n in sorted(set(by_name) | set(fw) | set(csv))]
    return written, converted
