"""An OpenPLC Editor project made from a CANopen config.

The editor's own New Project command (`openplc-cli create`) writes the
project, so its files and the editor's recent-projects entry are the editor's.
This module then changes only what `create` cannot set:

    devices/configuration.json   deviceBoard -> OpenPLC Runtime v4 (and the
                                 runtime address, when one is known)
    pous/programs/main.st        a VAR block declaring every CANopen location,
                                 and for each CiA 402 axis node the axis, its
                                 drive bridge and the bridge call
    canopen/                     the config and its files (project.write())
    project.json                 with sdo_blocks: the openplc_canopen library
                                 enabled (sdolibrary.enable_in_project())

The project is created in place (the editor records its path), so a failure
after `create` removes the folder it made.
"""

import json
import os
import re
import shutil
import subprocess

from . import axis, bundle, contract, sdolibrary
from . import project as project_mod
from .configurator import declare
from .eds import Eds, EdsError

TARGET = "OpenPLC Runtime v4"
DEFAULT_INTERVAL = "T#20ms"
BODY = "(* CANopen I/O declared from canopen/canopen.json *)"

_UNITS = {"d": 86400000.0, "h": 3600000.0, "m": 60000.0, "s": 1000.0, "ms": 1.0, "us": 0.001, "ns": 0.000001}
_PART = re.compile(r"(\d+(?:\.\d+)?)(ms|us|ns|d|h|m|s)_?", re.IGNORECASE)


class NewProjectError(Exception):
    pass


def interval_seconds(text):
    """An IEC duration's length in seconds (check_interval's rules)."""
    value = check_interval(text)
    rest = re.match(r"^(?:T|TIME)#(.+)$", value, re.IGNORECASE).group(1)
    return sum(float(p.group(1)) * _UNITS[p.group(2).lower()] for p in _PART.finditer(rest)) / 1000.0


def check_interval(text):
    """The interval as given, if it is an IEC duration (T#... or TIME#...) of at
    least 1 ms; NewProjectError otherwise."""
    value = (text or "").strip()
    m = re.match(r"^(?:T|TIME)#(.+)$", value, re.IGNORECASE)
    total, pos = 0.0, 0
    if m:
        rest = m.group(1)
        for part in _PART.finditer(rest):
            if part.start() != pos:
                break
            total += float(part.group(1)) * _UNITS[part.group(2).lower()]
            pos = part.end()
    if not m or pos != len(m.group(1)) or pos == 0:
        raise NewProjectError("task interval %r is not an IEC duration such as T#20ms" % text)
    if total < 1.0:
        raise NewProjectError("task interval %s is shorter than 1 ms" % value)
    return value


def cli_program():
    return os.environ.get("OPENPLC_CLI") or "openplc-cli"


def _on_path(name):
    for d in os.environ.get("PATH", "").split(os.pathsep):
        path = os.path.join(d, name)
        if d and os.path.isfile(path):
            return path
    return None


def cli_command(cli):
    """The arguments that start openplc-cli, or None when it cannot be found.

    Windows starts only .exe files by a bare name, and the editor installs
    openplc-cli there as a .cmd or PowerShell shim: resolve the name on PATH
    first (with PATHEXT), and run a .ps1 through PowerShell."""
    path = cli if os.path.dirname(cli) else shutil.which(cli)
    if not path and os.name == "nt":
        path = _on_path(cli + ".ps1")
    if not path or not os.path.isfile(path):
        return None
    if path.lower().endswith(".ps1"):
        return ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", path]
    if os.name != "nt" and not os.access(path, os.X_OK):
        return None
    return [path]


def declarations(cfg, config_path):
    """The config's declarations in program order, named from its EDS files."""
    files = bundle.eds_files(cfg, config_path)
    nodes = contract.all_nodes(cfg)
    eds = {}

    def find(value, index, sub):
        if value not in eds:
            try:
                eds[value] = Eds.read(files[value])
            except (KeyError, OSError, EdsError):
                eds[value] = None
        return eds[value].find(index, sub) if eds[value] else None

    def object_name(i, index, sub):
        o = find(nodes[i].get("eds"), index, sub)
        return o.name if o else None

    def slave_object(value, index, sub):
        o = find(value, index, sub)
        return (o.name, o.type_name) if o else None

    return declare.program_order(declare.declarations(cfg, object_name, {}, slave_object))


def with_axes(cfg, decls, interval=DEFAULT_INTERVAL):
    """(declarations, body lines before BODY): `decls` with each CiA 402
    axis and its bridge after the last declaration of its node, and the
    bridge calls (a cyclic axis's cycle time from the task `interval`)."""
    axes, body = axis.glue(cfg, decls, interval_seconds(interval))
    out = list(decls)
    for a in axes:
        last = max([k for k, d in enumerate(out) if d.get("node") == a["node"]] or
                   [k for k, d in enumerate(out) if d.get("node") is not None and d["node"] < a["node"]] or [-1])
        out.insert(last + 1, a)
    return out, body


def uses_library(cfg):
    """Whether the program needs the openplc_canopen library without
    --sdo-blocks: a cyclic CiA 402 axis (its CO402_Cyclic* blocks)."""
    return any(axis.is_cyclic(n) for n in contract.all_nodes(cfg))


def main_st(decls, body=()):
    """pous/programs/main.st in the form the editor writes a Structured Text program."""
    lines = "\n".join(list(body) + ["", BODY]) if body else BODY
    return "PROGRAM main\n%s\n\n%s\n\nEND_PROGRAM" % (declare.editor_block(decls), lines)


def program(cfg, config_path, interval=DEFAULT_INTERVAL):
    """The whole main.st for a config (the text `create` writes)."""
    decls, body = with_axes(cfg, declarations(cfg, config_path), interval)
    return main_st(decls, body)


def create(cfg, config_path, project_dir, interval=DEFAULT_INTERVAL, runtime_address=None, progress=None,
           sdo_blocks=False, sim_path=None):
    """Creates the project. Returns (project folder, located declarations). The config
    (and the simulation file sim_path, when given) must already have passed
    the deploy tool's checks."""
    progress = progress or (lambda m: None)
    project_dir = os.path.abspath(os.path.expanduser(project_dir))
    parent, name = os.path.split(project_dir.rstrip(os.sep))
    interval = check_interval(interval)
    if not name:
        raise NewProjectError("no project name in %s" % project_dir)
    if os.path.lexists(project_dir):
        raise NewProjectError("%s already exists; pick a new folder for the project" % project_dir)
    if not os.path.isdir(parent):
        raise NewProjectError("%s is not a folder" % parent)
    result = contract.check_config(cfg, config_path)
    if not result.ok:
        raise NewProjectError("\n".join(result.errors))
    decls, body = with_axes(cfg, declarations(cfg, config_path), interval)
    cli = cli_program()
    start = cli_command(cli)
    if not start:
        raise NewProjectError("cannot find %s: install it from the editor with 'openplc-cli install-cli', or set "
                              "$OPENPLC_CLI to the editor's openplc-cli" % cli)

    cmd = start + ["create", name, "--path=" + parent, "--language=st", "--time=" + interval, "--no-json"]
    progress("$ " + " ".join('"%s"' % c if " " in c else c for c in cmd))
    try:
        run = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True)
    except OSError as e:
        raise NewProjectError("cannot run %s: %s (install it from the editor with 'openplc-cli install-cli', or set "
                              "$OPENPLC_CLI)" % (cli, e))
    if run.returncode != 0 or not os.path.isfile(os.path.join(project_dir, "project.json")):
        made = os.path.isdir(project_dir)
        if made:
            shutil.rmtree(project_dir, ignore_errors=True)
        raise NewProjectError("openplc-cli create failed (exit %d)%s" % (
            run.returncode, ":\n" + run.stdout.strip() if run.stdout.strip() else ""))
    try:
        _patch(project_dir, decls, body, runtime_address)
        project_mod.write(cfg, config_path, project_dir, sim_path=sim_path)
        if sdo_blocks or uses_library(cfg):
            sdolibrary.enable_in_project(project_dir)
    except (OSError, ValueError, project_mod.ProjectError, NewProjectError, sdolibrary.LibraryError) as e:
        shutil.rmtree(project_dir, ignore_errors=True)
        raise NewProjectError("%s (the new project folder was removed)" % e)
    return project_dir, [d for d in decls if d.get("location")]


def _patch(project_dir, decls, body, runtime_address):
    conf = os.path.join(project_dir, "devices", "configuration.json")
    with open(conf, encoding="utf-8") as f:
        device = json.load(f)
    if not isinstance(device, dict):
        raise NewProjectError("%s is not a JSON object" % conf)
    device["deviceBoard"] = TARGET
    if runtime_address:
        device["runtimeIpAddress"] = runtime_address
    _write(conf, json.dumps(device, indent=2))
    programs = os.path.join(project_dir, "pous", "programs")
    os.makedirs(programs, exist_ok=True)
    _write(os.path.join(programs, "main.st"), main_st(decls, body))


def _write(path, text):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)
