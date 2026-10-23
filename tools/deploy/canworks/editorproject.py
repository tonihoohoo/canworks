"""An OpenPLC Editor project made from a CANopen config.

The editor's own New Project command (`openplc-cli create`) writes the
project, so its files and the editor's recent-projects entry are the editor's.
This module then changes only what `create` cannot set:

    devices/configuration.json   deviceBoard -> OpenPLC Runtime v4 (and the
                                 runtime address, when one is known)
    pous/programs/main.st        an empty program main
    canworks/                     the config and its files (project.write())
    devices/remote/, canworks_in, for an OpenPLC through Modbus config: the
    canworks_out, project.json   editor's remote device, the generated
                                 programs and the `canworks` variable list
                                 (write_editor_files(), openplcmodbus)
    project.json                 with blocks or generated programs: the
                                 canworks library enabled
                                 (plclibrary.enable_in_project())

The project is created in place (the editor records its path), so a failure
after `create` removes the folder it made.
"""

import json
import os
import re
import shutil
import subprocess

from . import bundle, contract, openplcmodbus, plclibrary, targets
from . import project as project_mod
from .configurator import declare, scan
from .eds import Eds, EdsError
from .userdirs import replace_file

TARGET = "OpenPLC Runtime v4"
DEFAULT_INTERVAL = "T#20ms"
BODY = "(* canworks values: the canworks variable list, such as canworks.ok *)"

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


CMD_SPECIAL = '&|^%<>"'
WINDOWS = os.name == "nt"


def unsafe_for_cmd(cmd):
    """On Windows openplc-cli is a .cmd shim, and cmd.exe reads & | ^ % < > "
    in its arguments as commands, not text. Returns a message naming the
    first argument (a project or editor path) with such a character, or None
    (always None elsewhere)."""
    if not WINDOWS:
        return None
    for arg in cmd:
        bad = [c for c in CMD_SPECIAL if c in arg]
        if bad:
            return ("%s contains %s, which the editor's openplc-cli cannot take on Windows; move or rename the "
                    "folder so that its path has none of %s" % (arg, " and ".join("'%s'" % c for c in bad),
                                                                 " ".join(CMD_SPECIAL)))
    return None


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


def uses_library(cfg):
    """Whether the project needs the canworks library without --blocks: an
    OpenPLC through Modbus config, whose canworks_in and canworks_out use its
    word helpers."""
    return cfg is not None and targets.target(cfg) == targets.OPENPLC_MODBUS


def main_st():
    """pous/programs/main.st in the form the editor writes a Structured Text
    program: empty, for the user's own code."""
    return "PROGRAM main\n  VAR\n  END_VAR\n\n%s\n\nEND_PROGRAM" % BODY


def write_editor_files(cfg, config_path, project_dir, force=False):
    """For an OpenPLC through Modbus config: the editor's remote device,
    canworks_in, canworks_out and the `canworks` list in the project
    (openplcmodbus.sync_project), with the I/O placed clear of the
    project's other located variables. Returns sync_project's result, or
    None for another target. NewProjectError when a generated file was
    changed by hand and `force` is not set."""
    if targets.target(cfg) != targets.OPENPLC_MODBUS:
        return None
    uses, _ = scan.scan(project_dir)
    try:
        return openplcmodbus.sync_project(project_dir, cfg, declarations(cfg, config_path), uses, force=force)
    except openplcmodbus.ChangedFiles as e:
        raise NewProjectError("changed outside canworks since it wrote them: %s (--force replaces them)"
                              % ", ".join(e.files))
    except openplcmodbus.OpenplcError as e:
        raise NewProjectError(str(e))


def create(cfg, config_path, project_dir, interval=DEFAULT_INTERVAL, runtime_address=None, progress=None,
           blocks=False, sim_path=None):
    """Creates the project. Returns (project folder, write_editor_files'
    result or None). The config
    (and the simulation file sim_path, when given) must already have passed
    the deploy tool's checks. With cfg None the project gets no canworks/
    folder and an empty main (the start page's New config with a project)."""
    progress = progress or (lambda m: None)
    project_dir = os.path.abspath(os.path.expanduser(project_dir))
    parent, name = os.path.split(project_dir.rstrip(os.sep))
    interval = check_interval(interval)
    if not name:
        raise NewProjectError("no project name in %s" % project_dir)
    existed = os.path.lexists(project_dir)
    if existed:
        in_the_way = existing_folder_problem(project_dir)
        if in_the_way:
            raise NewProjectError(in_the_way)
    elif not os.path.isdir(parent):
        raise NewProjectError("%s is not a folder" % parent)
    if cfg is not None:
        result = contract.check_config(cfg, config_path)
        if not result.ok:
            raise NewProjectError("\n".join(result.errors))
    cli = cli_program()
    start = cli_command(cli)
    if not start:
        raise NewProjectError("cannot find %s: install it from the editor with 'openplc-cli install-cli', or set "
                              "$OPENPLC_CLI to the editor's openplc-cli" % cli)

    cmd = start + ["create", name, "--path=" + parent, "--language=st", "--time=" + interval, "--no-json"]
    if existed:
        cmd.append("--force")  # writes into the existing folder; nothing in it is one of its files (checked above)
    unsafe = unsafe_for_cmd(cmd)
    if unsafe:
        raise NewProjectError(unsafe)
    progress("$ " + " ".join('"%s"' % c if " " in c else c for c in cmd))
    before = _contents(project_dir) if existed else None
    try:
        run = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                             universal_newlines=True, **NO_WINDOW)
    except OSError as e:
        raise NewProjectError("cannot run %s: %s (install it from the editor with 'openplc-cli install-cli', or set "
                              "$OPENPLC_CLI)" % (cli, e))
    if run.returncode != 0 or not os.path.isfile(os.path.join(project_dir, "project.json")):
        _undo(project_dir, before)
        raise NewProjectError("openplc-cli create failed (exit %d)%s" % (
            run.returncode, ":\n" + run.stdout.strip() if run.stdout.strip() else ""))
    synced = None
    try:
        _patch(project_dir, runtime_address)
        if cfg is not None:
            project_mod.write(cfg, config_path, project_dir, sim_path=sim_path)
            synced = write_editor_files(cfg, config_path, project_dir, force=True)
        if blocks or uses_library(cfg):
            plclibrary.enable_in_project(project_dir)
    except (OSError, ValueError, project_mod.ProjectError, NewProjectError, plclibrary.LibraryError) as e:
        _undo(project_dir, before)
        raise NewProjectError("%s (%s)" % (e, "the new project folder was removed" if before is None else
                                           "what was added to the folder was removed"))
    return project_dir, synced


def _patch(project_dir, runtime_address):
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
    _write(os.path.join(programs, "main.st"), main_st())


def _write(path, text):
    # A file of the project being made: nothing reads it yet, and a failure
    # removes it, so when the swap stays refused it is written in place.
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    replace_file(tmp, path, in_place=True)


# What `openplc-cli create` writes, and what makes a folder a project or
# config already: an existing folder holding any of them is refused.
EDITOR_FILES = ("project.json", os.path.join("devices", "configuration.json"),
                os.path.join("devices", "pin-mapping.json"), os.path.join("pous", "programs", "main.st"))
CANWORKS_FILES = ("canworks.json", "canworks")

# On Windows openplc-cli is a .cmd shim: without this a console window opens
# for it, since the configurator itself has none.
NO_WINDOW = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}


def existing_folder_problem(project_dir):
    """Why an existing folder cannot become the project, or None."""
    if not os.path.isdir(project_dir):
        return "%s is not a folder" % project_dir
    for rel in EDITOR_FILES + CANWORKS_FILES:
        if os.path.lexists(os.path.join(project_dir, rel)):
            return "%s already has %s; pick an empty folder or a new name" % (project_dir, rel)
    return None


def _contents(folder):
    """Every path under folder, relative to it."""
    out = set()
    for root, dirs, files in os.walk(folder):
        for n in dirs + files:
            out.add(os.path.relpath(os.path.join(root, n), folder))
    return out


def _undo(project_dir, before):
    """Removes what creation added: the whole folder when it made it
    (before None), else each added file and then each added folder left
    empty, deepest first; nothing that was there before."""
    if before is None:
        shutil.rmtree(project_dir, ignore_errors=True)
        return
    added = sorted(_contents(project_dir) - before, key=lambda r: r.count(os.sep), reverse=True)
    for rel in added:
        path = os.path.join(project_dir, rel)
        try:
            if os.path.isdir(path) and not os.path.islink(path):
                os.rmdir(path)
            else:
                os.remove(path)
        except OSError:
            pass
