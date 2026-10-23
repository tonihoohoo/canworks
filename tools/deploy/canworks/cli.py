"""canworks-deploy: check a canworks config, put it on canworks-bridge,
export it, or make an OpenPLC Editor project from it.

  canworks-deploy --config canworks.json --check

runs the checks the bridge runs at load (schema, EDS files, simulation file)
and uploads nothing.

  canworks-deploy --config canworks.json --bridge HOST[:PORT] [--token TOKEN]

uploads the config and every file it names to canworks-bridge over its
diagnostics channel (put_config), which restarts on it. HOST may be a
remembered device's name (link:NAME over the remote link only), or `local`
for the local runtime's bridge (canworks-local-runtime). See docs/deploy.md.

  canworks-deploy --config canworks.json --into-project <project>

copies the config and its files into an OpenPLC Editor project's canworks/
folder and, for an OpenPLC through Modbus config, writes the editor's remote
device, the canworks_in and canworks_out programs and the `canworks`
variable list (docs/modbus-bridge.md).

  canworks-deploy --config canworks.json --export-dcf <dir>

writes each node's configuration as a CiA 306 DCF (node_<id>.dcf) into
<dir>, checked against CiA 306, and uploads nothing. With several networks
each network's files go into <dir>/<network>/; --network NAME exports one.

  canworks-deploy --config canworks.json --export-dbc bus.dbc [--dbc-sdo config]

writes the network's PDOs, heartbeat, EMCY, NMT and SYNC (and optionally its
SDO frames) as a DBC file for CAN bus tools, and uploads nothing. With
several networks it writes bus_<network>.dbc per network; --network NAME
writes only that network to bus.dbc. A J1939 network's DBC holds its rx and
tx parameter groups with 29-bit identifiers (VFrameFormat J1939PG).

  canworks-deploy --config canworks.json --export-html network.html [--doc-od all] [--doc-embed-eds]

writes one HTML document of the networks for people: topology, settings,
COB-ID map, bus-load estimate, every node's identity, PDO layouts, boot SDO
writes, J1939 messages and signals, and PLC addresses (docs/network-docs.md).
Uploads nothing.

  canworks-deploy --config canworks.json --new-project <dir> [--task-interval T#10ms]

creates an OpenPLC Editor project in <dir> with openplc-cli create: target
OpenPLC Runtime v4, the config in its canworks/ folder and, for an OpenPLC
through Modbus config, the editor files of --into-project. Uploads nothing.
With --blocks the project also enables the canworks function block library
(the CO_* blocks over the bridge and the CAN and J1939 helpers).

  canworks-deploy --config canworks.json --export-codesys <dir> [--codesys-net NAME=N]
  canworks-deploy --config canworks.json --codesys-import [<project.project>] [--codesys-new TYPE:ID:VERSION]

writes the CANopen networks for CODESYS: node DCFs, a plan and the script
import_canworks.py that builds the CANbus, CANopen Manager, nodes and
variable names in a CODESYS project (in the IDE, or headless). With
--codesys-import the tool runs CODESYS headless on the project itself
(docs/codesys.md). A CODESYS config (one with a "codesys" object) holds
these settings itself; the options override them.

A simulation file (simulation.json next to the config, or --sim FILE) is
checked and travels with the config (docs/simulator.md). A config that
simulates the network or any node is uploaded to a bridge only after a
confirmation, --yes or --simulated.

  canworks-deploy library [--out DIR] [--install] [--project DIR]

writes the canworks function block library for the PLC program (the CO_*
blocks over the bridge, CAN and J1939 helpers) as canworks.stlib into DIR, installs it
into OpenPLC Editor on this computer, and/or enables it in an editor
project. See docs/plc-library.md.

  canworks-deploy slave-eds slave.json -o canworks/openplc-slave.eds [--gateway canworks.json [--update-config]]

writes the EDS of a canworks slave from a description of its objects
(docs/slave.md), checked with the bridge's EDS lint; with --gateway
it adds the gateway's route, status and SDO bridge objects (docs/gateway.md).

  canworks-deploy notes skeleton [--all] [--index LOW-HIGH] valve.eds [-o FILE]
  canworks-deploy notes builtin valve.eds [-o FILE]
  canworks-deploy notes check valve.eds valve.eds.notes.json

prints the device notes skeleton of an EDS (manufacturer objects with their
names, types and access; with --all every object with its default, limits
and PDO mapping), the built-in notes that apply to it, or the findings the
configurator shows for a notes file (docs/configurator.md, Device notes).
"""

import argparse
import json
import os
import shutil
import sys
import tempfile
import time

from . import (__version__, bundle, contract, dbcexport, dcfexport, diag, docexport, editorproject,
               localruntime, modbusmap, nodered, notes, project, plclibrary, simfile, slaveeds, targets)
from .userdirs import replace_file


class Failure(Exception):
    def __init__(self, message, uploaded=False):
        super().__init__(message)
        self.uploaded = uploaded


class MissingProject(Failure):
    """--codesys-import on a project file that does not exist, with no PLC
    device for a new one."""
    def __init__(self, message, project):
        super().__init__(message)
        self.project = project


def parser():
    p = argparse.ArgumentParser(
        prog="canworks-deploy",
        description="Check a canworks config, put it on canworks-bridge, export it, or make an OpenPLC Editor "
                    "project from it.")
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--check", action="store_true",
                     help="run the checks the bridge runs at load (schema, EDS files, simulation file) and stop")
    src.add_argument("--bridge", metavar="HOST[:PORT]",
                     help="upload the config to canworks-bridge over its diagnostics channel (default port %d; "
                          "needs allow_changes and allow_config_upload). A remembered device's name connects "
                          "directly or over the remote link, link:NAME over the link only, and `local` is the "
                          "local runtime's bridge (canworks-local-runtime)" % diag.DEFAULT_PORT)
    src.add_argument("--into-project", metavar="DIR",
                     help="copy the config and its files into this editor project's canworks/ folder; for an "
                          "OpenPLC through Modbus config also write the editor's remote device, canworks_in, "
                          "canworks_out and the canworks variable list")
    src.add_argument("--export-dcf", metavar="DIR",
                     help="write each node's configuration as a CiA 306 DCF (node_<id>.dcf) into DIR instead of "
                          "deploying; nothing is built or uploaded")
    src.add_argument("--export-dbc", metavar="FILE",
                     help="write the network as a DBC file for CAN bus tools (PDOs, heartbeat, EMCY, NMT, SYNC) "
                          "instead of deploying; nothing is built or uploaded")
    src.add_argument("--export-html", metavar="FILE",
                     help="write an HTML document of the networks (CANopen: topology, COB-ID map, bus load, nodes, "
                          "PDOs, boot SDO writes; J1939: ECU, messages, signals, frame map, bus load; PLC I/O) "
                          "instead of deploying; nothing is built or uploaded")
    src.add_argument("--export-modbus-map", metavar="FILE",
                     help="write the Modbus register map of a bridge config (one with a \"bridge\" object) as CSV, "
                          "JSON or an ST variable list, chosen by the extension (.csv, .json, .st), instead of "
                          "deploying; nothing is built or uploaded")
    src.add_argument("--export-nodered", metavar="FILE",
                     help="write a Node-RED flow (for node-red-contrib-modbus) that reads and writes a bridge config's "
                          "values by name through the bridge, instead of deploying; nothing is built or uploaded "
                          "(docs/node-red.md)")
    src.add_argument("--export-codesys", metavar="DIR",
                     help="write the CANopen networks for CODESYS into DIR (node DCFs, canworks-codesys.json and "
                          "the script import_canworks.py to run in CODESYS) instead of deploying")
    src.add_argument("--codesys-import", metavar="PROJECT", nargs="?", const="",
                     help="write the CODESYS export and run CODESYS headless on this .project file (default: the "
                          "config's codesys.project), which gets the CANbus, CANopen Manager, nodes and variable "
                          "names (Windows, CODESYS installed)")
    src.add_argument("--new-project", metavar="DIR",
                     help="create an OpenPLC Editor project in DIR (with openplc-cli create) that holds this config "
                          "and, for an OpenPLC through Modbus config, the editor files of --into-project")
    p.add_argument("--blocks", action="store_true",
                   help="with --new-project: enable the canworks function block library (the CO_* blocks over "
                        "the bridge, CAN and J1939 helpers) in the project, and install it into the editor if it is "
                        "missing or older")
    p.add_argument("--task-interval", metavar="T#...",
                   help="with --new-project: the task interval (default: %s)" % editorproject.DEFAULT_INTERVAL)
    p.add_argument("--nodered-host", metavar="HOST[:PORT]",
                   help="with --export-nodered: the bridge address the flow connects to (default: the bridge's "
                        "listen address, 127.0.0.1 when it listens on all addresses)")
    p.add_argument("--nodered-poll-ms", metavar="MS", type=int,
                   help="with --export-nodered: how often the flow reads the inputs (default %d ms, at most a third "
                        "of the bridge's watchdog_ms)" % nodered.DEFAULT_POLL_MS)
    p.add_argument("--dbc-sdo", choices=dbcexport.SDO_OPTIONS,
                   help="with --export-dbc: SDO frames to include: none (default), config (the config's SDO "
                        "variables and startup SDOs) or all (every EDS object up to 32 bits)")
    p.add_argument("--network", metavar="NAME",
                   help="with --export-dcf, --export-dbc, --export-html or --export-codesys and a config with "
                        "several networks: export "
                        "only this network (default: every network, DCFs in a folder per network, a DBC file per "
                        "network, one HTML document)")
    p.add_argument("--codesys-net", metavar="NAME=N", action="append",
                   help="with --export-codesys or --codesys-import: the CODESYS network number of network NAME "
                        "(default: the number its interface ends in, can1 -> 1); repeat per network")
    p.add_argument("--codesys-plc", metavar="NAME",
                   help="with --export-codesys or --codesys-import: the device in the CODESYS project that gets "
                        "the CANbus (default: the device of the project's active application, or its only device)")
    p.add_argument("--codesys-can", metavar="NETWORK=OBJECT", action="append",
                   help="with --export-codesys or --codesys-import: the CAN interface object in the CODESYS device "
                        "that gets network NETWORK's bus (default: the device's only CAN interface, or the one "
                        "whose name ends in the network number); repeat per network")
    p.add_argument("--codesys-no-variables", action="store_true",
                   help="with --export-codesys or --codesys-import: do not name the I/O channels")
    p.add_argument("--codesys-dir", metavar="DIR",
                   help="with --codesys-import: write the export here and keep it (default: a temporary folder)")
    p.add_argument("--codesys-new", metavar="TYPE:ID:VERSION",
                   help="with --codesys-import: create the project with this PLC device from CODESYS's device "
                        "repository, for example \"4096:0000 0004:3.5.22.40\"")
    p.add_argument("--codesys-exe", metavar="FILE",
                   help="with --codesys-import: CODESYS.exe (default: the newest CODESYS in the program folders)")
    p.add_argument("--codesys-profile", metavar="NAME",
                   help="with --codesys-import: the CODESYS profile (default: the newest of that install)")
    p.add_argument("--doc-title", metavar="TEXT", help="with --export-html: the document's title")
    p.add_argument("--doc-od", choices=docexport.OD_OPTIONS,
                   help="with --export-html: the object dictionary extract per node: used (default: the objects "
                        "the configuration writes or maps) or all")
    p.add_argument("--doc-embed-eds", action="store_true",
                   help="with --export-html: embed each node's EDS file so it can be saved from the document")
    p.add_argument("--force", action="store_true", help="with --into-project: replace an existing canworks/ folder")
    p.add_argument("--config", required=True, metavar="FILE",
                   help="the config (canworks.json); EDS and DBC paths are relative to it")
    p.add_argument("--token", help="with --bridge: the diagnostics token (default: $%s, else a prompt)" % diag.TOKEN_ENV)
    p.add_argument("--token-file", metavar="FILE", help="with --bridge: read the diagnostics token from this file")
    p.add_argument("--sim", metavar="FILE",
                   help="the simulation file to check and carry with the config (default: %s next to --config, "
                        "when it exists)" % simfile.FILE_NAME)
    p.add_argument("--simulated", action="store_true",
                   help="upload a config that simulates the network or some nodes without asking")
    p.add_argument("--yes", action="store_true", help="do not ask for confirmation")
    p.add_argument("--check-only", action="store_true", help="with --bridge: check and assemble, but do not upload")
    p.add_argument("--version", action="version", version="%(prog)s " + __version__)
    return p


def _ask(question):
    """y/N on the terminal; None when there is no terminal to ask on."""
    if not sys.stdin or not sys.stdin.isatty():
        return None
    sys.stdout.write(question + " [y/N] ")
    sys.stdout.flush()
    return sys.stdin.readline().strip().lower() in ("y", "yes")


def _export_modbus_map(config, path, out):
    try:
        with open(config, encoding="utf-8") as f:
            cfg = contract.load(f)
    except OSError as e:
        raise Failure("cannot read %s: %s" % (config, e))
    except ValueError as e:
        raise Failure("%s: not valid JSON (%s)" % (config, e))
    try:
        rows = modbusmap.export(cfg, path)
    except modbusmap.MapError as e:
        raise Failure("%s: %s" % (config, e))
    except OSError as e:
        raise Failure("cannot write %s: %s" % (path, e))
    out("wrote %s: %d register map entries, map hash 0x%08x" % (path, len(rows), modbusmap.map_hash(cfg)))
    return 0


def _export_nodered(config, path, host, poll_ms, out):
    try:
        with open(config, encoding="utf-8") as f:
            cfg = contract.load(f)
    except OSError as e:
        raise Failure("cannot read %s: %s" % (config, e))
    except ValueError as e:
        raise Failure("%s: not valid JSON (%s)" % (config, e))
    try:
        inputs, outputs, notes = nodered.export(cfg, path, host=host, poll_ms=poll_ms)
    except nodered.FlowError as e:
        raise Failure("%s: %s" % (config, e))
    except OSError as e:
        raise Failure("cannot write %s: %s" % (path, e))
    for note in notes:
        out("note: " + note)
    out("wrote %s: Node-RED flow with %d values in, %d out (import it in Node-RED; needs node-red-contrib-modbus)"
        % (path, inputs, outputs))
    return 0


def bridge_files(cfg, config_path, sim_path=None):
    """The files canworks-bridge gets for a config: {path: bytes} with
    "canworks.json" the config (bundle.files)."""
    try:
        deployed, eds_by_name = bundle.rewrite(cfg, config_path)
        sim = None
        if sim_path:
            sim_data, sim_eds, sim_csv = bundle.sim_rewrite(simfile.load(sim_path), sim_path)
            bundle.merge_by_name(eds_by_name, sim_eds, "EDS files")
            sim = (sim_data, sim_csv)
        return bundle.files(deployed, eds_by_name, sim)
    except (bundle.BundleError, simfile.SimFileError) as e:
        raise Failure(str(e))
    except OSError as e:
        raise Failure("cannot read %s: %s" % (e.filename, e.strerror))


def _deploy_bridge(args, cfg, sim_path, out, err, wait_s=60.0, local=None):
    """Uploads a bridge config to canworks-bridge (put_config) and reads back
    whether it started. To the local runtime's bridge (`local`, its saved
    settings) the files go in through the container engine."""
    files = bridge_files(cfg, args.config, sim_path)
    size = sum(len(v) for v in files.values())
    out("ok: %d file%s, %d bytes for canworks-bridge" % (len(files), "" if len(files) == 1 else "s", size))
    if args.check_only:
        out("not uploaded (--check-only)")
        return 0
    if local is not None:
        try:
            localruntime.put_config(local, files, out, timeout=wait_s)
        except localruntime.LocalRuntimeError as e:
            raise Failure(str(e))
        return 0
    try:
        host, port = diag.parse_runtime(args.bridge)
    except ValueError as e:
        raise Failure("--bridge: %s" % e)
    try:
        token = diag._token(args)
        client = diag.Client(host, port, token, timeout=10.0)
        info = client.connect()
        if info.get("host") != "bridge":
            client.close()
            raise Failure("%s is not canworks-bridge (it is %s)" % (client.where, info.get("host") or "unknown"))
        if not info.get("allow_config_upload"):
            client.close()
            raise Failure("config upload is off on %s: its running config needs \"allow_changes\": true and "
                          "\"allow_config_upload\": true in 'diagnostics'" % client.where)
        res = client.put_config(files)
        client.close()
    except diag.DiagError as e:
        raise Failure("%s: %s" % (args.bridge, e))
    number = res.get("upload")
    out("uploaded to %s; canworks-bridge restarts on it" % args.bridge)
    if not isinstance(cfg.get("diagnostics"), dict):
        out("the new config has no diagnostics channel, so whether it started cannot be read back")
        return 0
    deadline = time.monotonic() + wait_s
    last = None
    while time.monotonic() < deadline:
        time.sleep(1.0)
        try:
            c = diag.Client(host, port, token, timeout=5.0)
            c.connect()
            st = c.status()
            c.close()
        except diag.DiagError as e:
            last = e
            continue
        up = (st.get("bridge") or {}).get("last_upload") or {}
        if up.get("number") != number:
            continue
        if up.get("result") == "started":
            out("ok: canworks-bridge runs the new config")
            return 0
        raise Failure("canworks-bridge did not start the new config: %s" % up.get("detail"))
    raise Failure("canworks-bridge did not answer within %d s after the upload%s"
                  % (wait_s, ": %s" % last if last else ""))


def _codesys(args, cfg, network, out, runner=None):
    """--export-codesys DIR and --codesys-import [PROJECT]. The project and
    the device for a new one come from the config's `codesys` object when
    the options leave them out."""
    from .codesys import plan as codesys_plan, run as codesys_run
    own = cfg.get("codesys") if isinstance(cfg.get("codesys"), dict) else {}
    project = getattr(args, "codesys_import", None)
    if project == "":
        project = own.get("project") if isinstance(own.get("project"), str) else ""
        if not project:
            raise Failure("--codesys-import needs a project: give --codesys-import PROJECT, or set the project file "
                          "in the config (codesys.project)")
    if project:
        project = codesys_run.project_path(project)
    new_device = getattr(args, "codesys_new", None) or (own.get("create") if project else None)
    create = None
    try:
        overrides = codesys_run.parse_net(getattr(args, "codesys_net", None))
        interfaces = codesys_run.parse_can(getattr(args, "codesys_can", None))
        if project and new_device and (getattr(args, "codesys_new", None) or not os.path.exists(project)):
            create = {"path": os.path.abspath(project), "device": codesys_run.parse_device(new_device)}
    except ValueError as e:
        raise Failure(str(e))
    if project and not create and not os.path.isfile(project):
        raise MissingProject("%s does not exist; give --codesys-new TYPE:ID:VERSION to create it" % project, project)
    if create and os.path.exists(project):
        raise Failure("%s exists already; leave out --codesys-new to import into it" % project)
    exe = profile = None
    if project:
        exe = getattr(args, "codesys_exe", None) or codesys_run.find_codesys()
        if not exe or not os.path.isfile(exe):
            raise Failure("CODESYS not found%s: give --codesys-exe <path to CODESYS.exe>"
                          % (" at %s" % exe if exe else " in the program folders"))
        profile = getattr(args, "codesys_profile", None) or codesys_run.find_profile(exe)
        if not profile:
            raise Failure("no CODESYS profile found next to %s: give --codesys-profile NAME" % exe)
    try:
        files, _ = codesys_plan.export_files(
            cfg, args.config, overrides=overrides, interfaces=interfaces, plc=getattr(args, "codesys_plc", None),
            variables=False if getattr(args, "codesys_no_variables", False) else None, network=network,
            project=os.path.abspath(project) if project and not create else None, create=create)
    except codesys_plan.ExportFailed as e:
        raise Failure("\n".join(m for m, _ in e.problems) + "\nnothing was written")
    folder = getattr(args, "export_codesys", None) or getattr(args, "codesys_dir", None)
    temporary = folder is None
    if temporary:
        folder = tempfile.mkdtemp(prefix="canworks-codesys-")
    written = codesys_run.write_folder(files, folder)
    if not project:
        for path in written:
            out("wrote %s" % path)
        out("ok: run %s in CODESYS (Tools > Scripting > Execute Script File...) on the open project"
            % os.path.join(folder, codesys_plan.SCRIPT_NAME))
        return 0
    out("running CODESYS %s (profile %s) on %s" % (exe, profile, project))
    try:
        report = codesys_run.run_codesys(exe, profile, folder, runner=runner)
    except codesys_run.CodesysError as e:
        raise Failure("%s\nthe export is in %s" % (e, folder))
    for line in report.splitlines():
        out(line)
    if not codesys_run.report_ok(report):
        raise Failure("the CODESYS import reported errors (above); the export is in %s" % folder)
    if temporary:
        shutil.rmtree(folder, ignore_errors=True)
    return 0


def run(args, out=print, err=None, confirm_source=None):
    err = err or (lambda m: print(m, file=sys.stderr))

    if not getattr(args, "export_nodered", None) and (getattr(args, "nodered_host", None)
                                                     or getattr(args, "nodered_poll_ms", None) is not None):
        raise Failure("--nodered-host and --nodered-poll-ms go with --export-nodered")
    map_file = getattr(args, "export_modbus_map", None)
    if map_file:
        if args.check_only:
            raise Failure("--export-modbus-map only writes the register map; leave out --check-only")
        return _export_modbus_map(args.config, map_file, out)

    flow_file = getattr(args, "export_nodered", None)
    if flow_file:
        if args.check_only:
            raise Failure("--export-nodered only writes the Node-RED flow; leave out --check-only")
        return _export_nodered(args.config, flow_file, args.nodered_host, args.nodered_poll_ms, out)
    into = getattr(args, "into_project", None)
    export_dir = getattr(args, "export_dcf", None)
    if export_dir and (args.check_only):
        raise Failure("--export-dcf only writes DCF files; leave out --check-only")
    dbc_file = getattr(args, "export_dbc", None)
    dbc_sdo = getattr(args, "dbc_sdo", None)
    if dbc_sdo and not dbc_file:
        raise Failure("--dbc-sdo needs --export-dbc")
    if dbc_file and (args.check_only):
        raise Failure("--export-dbc only writes a DBC file; leave out --check-only")
    html_file = getattr(args, "export_html", None)
    for opt, given in (("--doc-title", getattr(args, "doc_title", None)), ("--doc-od", getattr(args, "doc_od", None)),
                       ("--doc-embed-eds", getattr(args, "doc_embed_eds", False))):
        if given and not html_file:
            raise Failure("%s needs --export-html" % opt)
    if html_file and (args.check_only):
        raise Failure("--export-html only writes an HTML document; leave out --check-only")
    codesys_dir = getattr(args, "export_codesys", None)
    importing = getattr(args, "codesys_import", None) is not None
    codesys = bool(codesys_dir) or importing
    for opt, key in (("--codesys-net", "codesys_net"), ("--codesys-plc", "codesys_plc"),
                     ("--codesys-can", "codesys_can"),
                     ("--codesys-no-variables", "codesys_no_variables")):
        if getattr(args, key, None) and not codesys:
            raise Failure("%s needs --export-codesys or --codesys-import" % opt)
    for opt, key in (("--codesys-dir", "codesys_dir"), ("--codesys-new", "codesys_new"),
                     ("--codesys-exe", "codesys_exe"), ("--codesys-profile", "codesys_profile")):
        if getattr(args, key, None) and not importing:
            raise Failure("%s needs --codesys-import" % opt)
    if codesys and (args.check_only):
        raise Failure("the CODESYS export uploads nothing; leave out --check-only")
    network = getattr(args, "network", None)
    if network and not export_dir and not dbc_file and not html_file and not codesys:
        raise Failure("--network needs --export-dcf, --export-dbc, --export-html or --export-codesys")
    new_project = getattr(args, "new_project", None)
    interval = getattr(args, "task_interval", None)
    if interval and not new_project:
        raise Failure("--task-interval needs --new-project")
    blocks = getattr(args, "blocks", False)
    if blocks and not new_project:
        raise Failure("--blocks needs --new-project")
    if new_project and (args.check_only):
        raise Failure("--new-project only creates an editor project; leave out --check-only")
    bridge_target = getattr(args, "bridge", None)
    if (getattr(args, "token", None) or getattr(args, "token_file", None)) and not bridge_target:
        raise Failure("--token and --token-file go with --bridge")
    if args.check_only and not bridge_target:
        raise Failure("--check-only goes with --bridge (--check runs the checks alone)")
    local = None
    if localruntime.is_local(bridge_target):
        try:
            local = localruntime.target()
        except localruntime.LocalRuntimeError as e:
            raise Failure(str(e))

    # 1. The config and its checks.
    try:
        with open(args.config, encoding="utf-8") as f:
            cfg = contract.load(f)
    except OSError as e:
        raise Failure("cannot read %s: %s" % (args.config, e))
    except ValueError as e:
        raise Failure("%s: not valid JSON (%s)" % (args.config, e))
    missing = bundle.missing_eds(cfg, args.config) if isinstance(cfg, dict) else []
    if missing:
        raise Failure("\n".join(missing))
    result = contract.check_config(cfg, args.config, eds_paths=bundle.eds_files(cfg, args.config))
    for w in result.warnings:
        err("warning: " + w)
    if not result.ok:
        raise Failure("\n".join(result.errors))
    out("ok: %s passes the schema and EDS checks" % args.config)
    if targets.target(cfg) == targets.CODESYS and (into or new_project or bridge_target):
        raise Failure("%s is a CODESYS config (it has a 'codesys' object): CODESYS runs it, not canworks-bridge; "
                      "build it into a CODESYS project with --codesys-import" % args.config)

    # The simulation file and what the config simulates (not for the exports).
    sim_path = None
    simulated = None
    if not export_dir and not dbc_file and not html_file and not codesys:
        sim_path = getattr(args, "sim", None)
        if sim_path and not os.path.isfile(sim_path):
            raise Failure("simulation file %s not found" % sim_path)
        if not sim_path and os.path.isfile(simfile.default_path(args.config)):
            sim_path = simfile.default_path(args.config)
        if sim_path:
            _, sim_result = simfile.check_file(sim_path, cfg, args.config, eds_paths=bundle.eds_files(cfg, args.config))
            for w in sim_result.warnings:
                err("warning: " + w)
            if not sim_result.ok:
                raise Failure("\n".join(sim_result.errors))
            out("ok: %s passes the simulation file checks" % sim_path)
        simulated = simfile.describe_simulated(cfg)
        uploading = bool(bridge_target) and not args.check_only
        if simulated:
            err("warning: this config simulates devices: %s. Outputs to a simulated device go nowhere; never leave "
                "a machine's config simulated." % simulated)
        if local and uploading:
            out("local runtime: every network runs simulated on its bridge, whatever the config says")
        if simulated and uploading and not local and not (getattr(args, "yes", False) or getattr(args, "simulated", False)):
            answer = (confirm_source or _ask)("Upload this config with simulated devices to %s?" % bridge_target)
            if answer is None:
                raise Failure("not uploaded: %s. Pass --simulated (or --yes) to upload it anyway" % simulated)
            if not answer:
                raise Failure("not confirmed")

    if export_dir:
        try:
            files, _ = dcfexport.export(cfg, args.config, network=network)
        except dcfexport.ExportFailed as e:
            raise Failure("\n".join(m for m, _ in e.problems) + "\nno DCF was written")
        for path in dcfexport.write_files(files, export_dir):
            out("wrote %s" % path)
        out("ok: %d DCF file%s checked against CiA 306" % (len(files), "" if len(files) == 1 else "s"))
        return 0

    if codesys:
        return _codesys(args, cfg, network, out)

    if dbc_file:
        try:
            files, warnings = dbcexport.export_networks(cfg, args.config, sdo=dbc_sdo or "none",
                                                        names=dbcexport.project_names(args.config), network=network)
        except dbcexport.ExportFailed as e:
            raise Failure("\n".join(m for m, _ in e.problems) + "\nno DBC was written")
        for w in warnings:
            if w not in result.warnings:
                err("warning: " + w)
        for name, text in files:
            path = dbcexport.network_file(dbc_file, name) if len(files) > 1 else dbc_file
            out("wrote %s" % dbcexport.write_file(text, path))
        return 0

    if html_file:
        try:
            text, warnings = docexport.export(
                cfg, args.config, names=dbcexport.project_names(args.config), network=network,
                title=getattr(args, "doc_title", None), od=getattr(args, "doc_od", None) or "used",
                embed_eds=getattr(args, "doc_embed_eds", False))
        except docexport.ExportFailed as e:
            raise Failure("\n".join(m for m, _ in e.problems) + "\nno HTML document was written")
        for w in warnings:
            if w not in result.warnings:
                err("warning: " + w)
        out("wrote %s" % docexport.write_file(text, html_file))
        return 0

    if new_project:
        try:
            path, written = editorproject.create(cfg, args.config, new_project,
                                               interval=interval or editorproject.DEFAULT_INTERVAL, progress=out,
                                               sim_path=sim_path, blocks=blocks)
        except editorproject.NewProjectError as e:
            raise Failure(str(e))
        out("created %s" % path)
        for line in editor_lines(written):
            out(line)
        if blocks or editorproject.uses_library(cfg):
            out("the project enables the %s function block library" % plclibrary.NAME)
            ok, message = plclibrary.ensure_installed()
            (out if ok else err)(message if ok else "warning: " + message)
        return 0

    if into:
        try:
            report = {}
            written, converted = project.write(cfg, args.config, into, force=args.force, sim_path=sim_path,
                                               report=report)
        except project.ProjectError as e:
            raise Failure(str(e))
        for name in converted:
            out("converted %s from CP1252 to UTF-8 (the editor sends project files as UTF-8)" % name)
        if report.get("backup"):
            out("kept the old folder as %s" % report["backup"])
        out("wrote %s" % ", ".join(written))
        try:
            synced = editorproject.write_editor_files(cfg, args.config, into, force=args.force)
        except editorproject.NewProjectError as e:
            raise Failure(str(e))
        for line in editor_lines(synced):
            out(line)
        return 0

    if args.check:
        return 0
    return _deploy_bridge(args, cfg, sim_path, out, err, local=local)


def editor_lines(synced):
    """What --new-project and --into-project say about the editor files of
    an OpenPLC through Modbus config (editorproject.write_editor_files)."""
    if not synced:
        return []
    out = ["wrote the editor's remote device, canworks_in, canworks_out and the canworks variable list (%d Modbus "
           "request%s per poll, I/O from %%IW%d/%%QW%d)" % (synced["requests"], "" if synced["requests"] == 1 else "s",
                                                           synced["iec_base"], synced["iec_base"])]
    if synced.get("warning"):
        out.append("warning: " + synced["warning"])
    return out


def library_parser():
    p = argparse.ArgumentParser(
        prog="canworks-deploy library",
        description="The %s function block library for the PLC program: CANopen blocks over the bridge "
                    "(SDO read and write, NMT, node live state) and CAN and J1939 helper functions. "
                    "See docs/plc-library.md." % plclibrary.NAME)
    p.add_argument("--out", metavar="DIR",
                   help="write %s into DIR, for the editor's Library Manager (install from file)"
                        % plclibrary.FILE_NAME)
    p.add_argument("--install", action="store_true",
                   help="install the library into OpenPLC Editor on this computer, as its Library Manager does "
                        "(restart the editor afterwards)")
    p.add_argument("--project", metavar="DIR", help="enable the library in this editor project")
    p.add_argument("--list", action="store_true", help="list the library's function blocks and functions")
    return p


def run_library(args, out=print, err=None):
    err = err or (lambda m: print(m, file=sys.stderr))
    if not (args.out or args.install or args.project or args.list):
        raise Failure("give --out DIR, --install, --project DIR or --list")
    try:
        if args.list:
            for name in plclibrary.block_names() + plclibrary.function_names():
                out(name)
        if args.out:
            out("wrote %s (%s %s)" % (plclibrary.write(args.out), plclibrary.NAME, __version__))
        if args.install:
            out("installed %s %s into the editor (%s); restart OpenPLC Editor if it is open"
                % (plclibrary.NAME, __version__, plclibrary.install()))
        if args.project:
            plclibrary.enable_in_project(args.project)
            out("enabled %s in %s" % (plclibrary.NAME, os.path.abspath(args.project)))
            if not args.install and plclibrary.installed_version() is None:
                err("note: the editor does not have the library yet: run 'canworks-deploy library --install'")
    except (plclibrary.LibraryError, OSError, ValueError) as e:
        raise Failure(str(e))
    return 0


def slave_eds_parser():
    p = argparse.ArgumentParser(
        prog="canworks-deploy slave-eds",
        description="Write the EDS of OpenPLC as a CANopen slave from a JSON description of its objects (identity, "
                    "heartbeat, layout and objects with name, type, direction and limits), checked with the bridge's "
                    "EDS lint. See docs/slave.md.")
    p.add_argument("description", help="the description (JSON)")
    p.add_argument("-o", "--output", required=True, metavar="FILE.eds",
                   help="the EDS to write, normally into the project's canworks/ folder")
    p.add_argument("--gateway", metavar="CONFIG",
                   help="a config with a 'gateway' section: add a slave object per route, the field node status "
                        "objects and the SDO bridge record (docs/gateway.md)")
    p.add_argument("--update-config", action="store_true",
                   help="with --gateway: write the slave object of each route (index, subindex) into that config")
    return p


def run_slave_eds(args, out=print):
    if args.update_config and not args.gateway:
        raise Failure("--update-config needs --gateway")
    try:
        desc = slaveeds.load_json(args.description, "description")
        cfg = slaveeds.load_json(args.gateway, "config") if args.gateway else None
        text, info = slaveeds.generate(desc, cfg, os.path.basename(args.output))
    except slaveeds.DescriptionError as e:
        raise Failure("%s: %s" % (args.gateway if str(e).startswith("gateway") else args.description, e))
    try:
        slaveeds.write(text, args.output)
    except OSError as e:
        raise Failure("cannot write %s: %s" % (args.output, e.strerror or e))
    objs = info["objects"]
    n_in = sum(1 for o in objs if o["direction"] == "from_master")
    out("wrote %s: %d object%s from the master, %d to the master, %d RPDO%s and %d TPDO%s, revision number 0x%08X"
        % (args.output, n_in, "" if n_in == 1 else "s", len(objs) - n_in, info["pdos"]["rx"],
           "" if info["pdos"]["rx"] == 1 else "s", info["pdos"]["tx"], "" if info["pdos"]["tx"] == 1 else "s",
           info["revision_number"]))
    for o in objs:
        out("  0x%04X:%d %s %s %s" % (o["index"], o["subindex"], o["type"],
                                      "rww (PLC input)" if o["direction"] == "from_master" else "ro (PLC output)",
                                      o["name"]))
    if args.update_config:
        changed = slaveeds.update_routes(cfg, info)
        tmp = args.gateway + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
            f.write("\n")
        replace_file(tmp, args.gateway)
        out("updated %s: %d route%s with a new slave object" % (args.gateway, changed, "" if changed == 1 else "s"))
    elif cfg is not None:
        stale = [j for j, (rt, place) in enumerate(zip(cfg["gateway"].get("routes") or [], info["routes"]))
                 if not isinstance(rt.get("slave"), dict)
                 or contract._uint(rt["slave"].get("index")) != place["index"]
                 or contract._uint(rt["slave"].get("subindex", 0)) != place["subindex"]]
        if stale:
            out("note: %d route%s of %s name%s another slave object than the EDS gives %s; run again with "
                "--update-config to write them" % (len(stale), "" if len(stale) == 1 else "s", args.gateway,
                                                   "s" if len(stale) == 1 else "", "it" if len(stale) == 1 else "them"))
    return 0


def notes_parser():
    p = argparse.ArgumentParser(
        prog="canworks-deploy notes",
        description="Device notes of an EDS (format %s): the skeleton to fill in, the built-in notes that apply, "
                    "or a check of a notes file. See docs/configurator.md, Device notes." % notes.FORMAT)
    sub = p.add_subparsers(dest="command", required=True, metavar="skeleton|builtin|check")
    for name, text in (("skeleton", "a notes document with an entry per manufacturer object (0x2000-0x5FFF) and its "
                                    "EDS name, data type (x-type) and access (x-access)"),
                       ("builtin", "the built-in CiA 301, 401 and 402 notes that apply to the EDS; stderr names "
                                   "the sets used")):
        c = sub.add_parser(name, help=text, description=text)
        c.add_argument("eds", help="the EDS file")
        c.add_argument("-o", "--output", metavar="FILE",
                       help="write the document to FILE instead of printing it (an existing FILE needs --force)")
        c.add_argument("--force", action="store_true", help="replace an existing -o FILE")
        if name == "skeleton":
            c.add_argument("--all", action="store_true", dest="all_objects",
                           help="every object of the EDS, standard ones included, with an entry for each ARRAY "
                                "and RECORD object and the EDS default (x-default), limits (x-low, x-high) and "
                                "PDO mapping (x-pdo)")
            c.add_argument("--index", metavar="LOW-HIGH", type=_index_range,
                           help="only the objects in this index range, for example 0x3000-0x30FF")
    c = sub.add_parser("check", help="the findings the configurator shows for a notes file; exit status 1 when "
                                     "there is any",
                       description="Print the findings the configurator shows for a notes file, one per line. Exit "
                                   "status 1 when there is any finding, 0 when there is none.")
    c.add_argument("eds", help="the EDS file")
    c.add_argument("notes", help="the notes file")
    return p


def _index_range(text):
    """(low, high) of an index range "0x3000-0x30FF" (or one index)."""
    parts = text.split("-")
    try:
        lo, hi = (int(parts[0], 16), int(parts[-1], 16)) if len(parts) <= 2 else (None, None)
    except ValueError:
        lo = hi = None
    if lo is None or not 0 <= lo <= hi <= 0xFFFF:
        raise argparse.ArgumentTypeError("%r is not an index range such as 0x3000-0x30FF" % text)
    return lo, hi


def run_notes(args, out=print, err=None):
    err = err or (lambda text: print(text, file=sys.stderr))
    from .eds import Eds, EdsError
    name = os.path.basename(args.eds)
    try:
        eds = Eds.read(args.eds)
    except (EdsError, OSError, UnicodeDecodeError) as e:
        raise Failure("cannot read %s: %s" % (args.eds, getattr(e, "strerror", None) or e))
    if args.command == "check":
        doc, error = notes.load(args.notes)
        if doc is None:
            raise Failure(error or "%s: no such file" % args.notes)
        findings = notes.check(eds, doc, os.path.basename(args.notes), name)
        for f in findings:
            out(f)
        return 1 if findings else 0
    if args.output and os.path.lexists(args.output) and not args.force:
        raise Failure("%s already exists (filled-in notes are lost if it is replaced); pass --force to replace it"
                      % args.output)
    if args.command == "skeleton":
        doc = notes.skeleton(eds, name, eds_path=args.eds, describe=True, all_objects=args.all_objects,
                             indices=args.index)
        missing = notes.missing_identity(doc["eds"])
        if missing:
            err("%s gives no %s; the notes file's identity leaves %s out"
                % (name, " or ".join(missing), "it" if len(missing) == 1 else "them"))
    else:
        doc = {"format": notes.FORMAT, "eds": notes.identity(name, args.eds), "objects": notes.builtin(eds)}
        sets, missing = notes.builtin_sets(eds)
        err("built-in notes: %s%s" % (", ".join(sets), "; " + missing if missing else ""))
    text = notes.dumps(doc)
    if args.output:
        try:
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(text)
        except OSError as e:
            raise Failure("cannot write %s: %s" % (args.output, e.strerror or e))
    else:
        out(text.rstrip("\n"))
    return 0


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    if argv[:1] == ["notes"]:
        try:
            return run_notes(notes_parser().parse_args(argv[1:]))
        except Failure as e:
            print("error: " + str(e), file=sys.stderr)
            return 1
    if argv[:1] == ["library"]:
        try:
            return run_library(library_parser().parse_args(argv[1:]))
        except Failure as e:
            print("error: " + str(e), file=sys.stderr)
            return 1
    if argv[:1] == ["slave-eds"]:
        try:
            return run_slave_eds(slave_eds_parser().parse_args(argv[1:]))
        except Failure as e:
            print("error: " + str(e), file=sys.stderr)
            return 1
    args = parser().parse_args(argv)
    try:
        return run(args)
    except Failure as e:
        print("error: " + str(e).replace("\n", "\nerror: "), file=sys.stderr)
        if not e.uploaded:
            print("nothing was uploaded", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
