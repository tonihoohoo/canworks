"""openplc-canopen-deploy: add a CANopen config to an OpenPLC editor build,
check it, and upload it to an OpenPLC Runtime v4.

  openplc-canopen-deploy --bundle <project>/build/"OpenPLC Runtime v4"/src \\
      --config canopen_config.json --runtime 192.168.1.20 --user openplc --fingerprint AB:CD:...

The runtime switches the CANopen plugin on because the upload carries
conf/canopen.json, exactly as it does for EtherCAT. See docs/deploy.md.

  openplc-canopen-deploy --config canopen_config.json --into-project <project>

copies the config and its EDS files into the project's canopen/ folder
instead, for runtimes with the editor hook (docs/install-stock.md).

  openplc-canopen-deploy --config canopen_config.json --export-dcf <dir>

writes each node's configuration as a CiA 306 DCF (node_<id>.dcf) into
<dir>, checked against CiA 306, and uploads nothing. With several networks
each network's files go into <dir>/<network>/; --network NAME exports one.

  openplc-canopen-deploy --config canopen_config.json --export-dbc bus.dbc [--dbc-sdo config]

writes the network's PDOs, heartbeat, EMCY, NMT and SYNC (and optionally its
SDO frames) as a DBC file for CAN bus tools, and uploads nothing. With
several networks it writes bus_<network>.dbc per network; --network NAME
writes only that network to bus.dbc.

  openplc-canopen-deploy --config canopen_config.json --new-project <dir> [--task-interval T#10ms]

creates an OpenPLC Editor project in <dir> with openplc-cli create: target
OpenPLC Runtime v4, the config in its canopen/ folder, and a program main
declaring every CANopen location. Uploads nothing. With --sdo-blocks the
project also enables the openplc_canopen library (the CO_SDO_* blocks).

A simulation file (simulation.json next to the config, or --sim FILE) is
checked and travels with the config (docs/simulator.md). A config that
simulates the network or any node is uploaded only after a confirmation,
--yes or --simulated.

  openplc-canopen-deploy library [--out DIR] [--install] [--project DIR]

writes the openplc_canopen editor library (SDO function blocks for the PLC
program) as openplc_canopen.stlib into DIR, installs it into OpenPLC Editor
on this computer, and/or enables it in an editor project. See docs/plc-sdo.md.

  openplc-canopen-deploy slave-eds slave.json -o canopen/openplc-slave.eds [--gateway canopen.json [--update-config]]

writes the EDS of OpenPLC as a CANopen slave from a description of its
objects (docs/slave.md), checked with the plugin's EDS lint; with --gateway
it adds the gateway's route, status and SDO bridge objects (docs/gateway.md).
"""

import argparse
import getpass
import json
import os
import shutil
import subprocess
import sys

from . import (__version__, bundle, clash, contract, dbcexport, dcfexport, editorproject, project, runtime, sdolibrary,
               simfile, slaveeds)

EDITOR_WARNING = (
    "Note: uploading this program from the editor's own \"Build and upload\" sends no conf/canopen.json, so the "
    "runtime switches CANopen off until you deploy with openplc-canopen-deploy again.")
EDITOR_HOOK_NOTE = (
    "Note: this runtime has the CANopen editor hook, so the editor's own \"Build and upload\" keeps CANopen on if "
    "the project has a canopen/ folder (openplc-canopen-deploy --into-project) and switches it off if not.")
# Logged by the editor hook (tools/editor-hook) for an upload that carries conf/canopen.json.
HOOK_LOG_LINE = "CANopen: the upload carries conf/canopen.json"

DEFAULT_TARGET = "OpenPLC Runtime v4"


class Failure(Exception):
    def __init__(self, message, uploaded=False):
        super().__init__(message)
        self.uploaded = uploaded


def parser():
    p = argparse.ArgumentParser(
        prog="openplc-canopen-deploy",
        description="Add a CANopen config and its EDS files to an OpenPLC editor build, check them, and upload "
                    "the program to an OpenPLC Runtime v4.",
        epilog=EDITOR_WARNING)
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--bundle", metavar="DIR",
                     help="the editor's \"Build only\" output: <project>/build/<target>/src")
    src.add_argument("--project", metavar="DIR",
                     help="an editor project: build it with openplc-cli compile first")
    src.add_argument("--into-project", metavar="DIR",
                     help="copy the config and its EDS files into this editor project's canopen/ folder instead of "
                          "deploying, so the editor's own \"Build and upload\" carries them (needs the editor hook "
                          "on the runtime)")
    src.add_argument("--export-dcf", metavar="DIR",
                     help="write each node's configuration as a CiA 306 DCF (node_<id>.dcf) into DIR instead of "
                          "deploying; nothing is built or uploaded")
    src.add_argument("--export-dbc", metavar="FILE",
                     help="write the network as a DBC file for CAN bus tools (PDOs, heartbeat, EMCY, NMT, SYNC) "
                          "instead of deploying; nothing is built or uploaded")
    src.add_argument("--new-project", metavar="DIR",
                     help="create an OpenPLC Editor project in DIR (with openplc-cli create) that holds this config "
                          "and declares its I/O in the program main")
    p.add_argument("--sdo-blocks", action="store_true",
                   help="with --new-project: enable the openplc_canopen library (SDO function blocks for the "
                        "program) in the project, and install it into the editor if it is missing or older")
    p.add_argument("--task-interval", metavar="T#...",
                   help="with --new-project: the task interval (default: %s)" % editorproject.DEFAULT_INTERVAL)
    p.add_argument("--dbc-sdo", choices=dbcexport.SDO_OPTIONS,
                   help="with --export-dbc: SDO frames to include: none (default), config (the config's SDO "
                        "variables and startup SDOs) or all (every EDS object up to 32 bits)")
    p.add_argument("--network", metavar="NAME",
                   help="with --export-dcf or --export-dbc and a config with several networks: export only this "
                        "network (default: every network, DCFs in a folder per network, a DBC file per network)")
    p.add_argument("--force", action="store_true", help="with --into-project: replace an existing canopen/ folder")
    p.add_argument("--target", default=DEFAULT_TARGET,
                   help="board target for --project (default: %(default)s)")
    p.add_argument("--config", required=True, metavar="FILE",
                   help="the CANopen config (canopen_config.json); EDS paths are relative to it")
    p.add_argument("--runtime", metavar="HOST[:PORT]", help="the runtime to upload to (HTTPS, default port 8443)")
    p.add_argument("--user", default=os.environ.get("OPENPLC_USER"),
                   help="runtime user (default: $OPENPLC_USER); the password comes from $OPENPLC_PASSWORD or a "
                        "prompt")
    p.add_argument("--allow-clash", action="store_true",
                   help="report input address clashes with other plugins as warnings instead of errors")
    tls = p.add_mutually_exclusive_group()
    tls.add_argument("--ca", metavar="FILE", help="verify the runtime's certificate against this CA/certificate file")
    tls.add_argument("--fingerprint", metavar="SHA256",
                     help="verify the runtime's certificate by its SHA-256 fingerprint")
    tls.add_argument("--insecure", action="store_true", help="do not verify the runtime's certificate")
    p.add_argument("--sim", metavar="FILE",
                   help="the simulation file to check and carry with the config (default: %s next to --config, "
                        "when it exists)" % simfile.FILE_NAME)
    p.add_argument("--simulated", action="store_true",
                   help="upload a config that simulates the network or some nodes without asking")
    p.add_argument("--yes", action="store_true", help="do not ask for confirmation")
    p.add_argument("--output", metavar="ZIP", help="also write the program zip to this file")
    p.add_argument("--check-only", action="store_true", help="check and assemble, but do not upload")
    p.add_argument("--no-start", action="store_true",
                   help="leave the PLC stopped after the upload (by default the tool starts it)")
    p.add_argument("--timeout", type=float, default=900.0, metavar="S",
                   help="how long to wait for the runtime's build (default: %(default)s s)")
    p.add_argument("--version", action="version", version="%(prog)s " + __version__)
    return p


def build_project(project, target, out):
    # openplc-cli treats a path that is not absolute as a cloud project id and
    # builds into its own scratch directory instead of <project>/build.
    project = os.path.abspath(project)
    cli = editorproject.cli_program()
    cmd = (editorproject.cli_command(cli) or [cli]) + ["compile", project, "--target", target, "--no-json"]
    out("$ " + " ".join('"%s"' % c if " " in c else c for c in cmd))
    try:
        rc = subprocess.call(cmd)
    except OSError as e:
        raise Failure("cannot run %s: %s (install it from the editor with 'openplc-cli install-cli', or set "
                      "$OPENPLC_CLI)" % (cli, e))
    if rc != 0:
        raise Failure("openplc-cli compile failed (exit %d)" % rc)
    return os.path.join(project, "build", target, "src")


def _ask(question):
    """y/N on the terminal; None when there is no terminal to ask on."""
    if not sys.stdin or not sys.stdin.isatty():
        return None
    sys.stdout.write(question + " [y/N] ")
    sys.stdout.flush()
    return sys.stdin.readline().strip().lower() in ("y", "yes")


def run(args, out=print, err=None, password_source=None, confirm_source=None):
    err = err or (lambda m: print(m, file=sys.stderr))

    into = getattr(args, "into_project", None)
    export_dir = getattr(args, "export_dcf", None)
    if export_dir and (args.runtime or args.output or args.check_only):
        raise Failure("--export-dcf only writes DCF files; leave out --runtime, --output and --check-only")
    dbc_file = getattr(args, "export_dbc", None)
    dbc_sdo = getattr(args, "dbc_sdo", None)
    if dbc_sdo and not dbc_file:
        raise Failure("--dbc-sdo needs --export-dbc")
    if dbc_file and (args.runtime or args.output or args.check_only):
        raise Failure("--export-dbc only writes a DBC file; leave out --runtime, --output and --check-only")
    network = getattr(args, "network", None)
    if network and not export_dir and not dbc_file:
        raise Failure("--network needs --export-dcf or --export-dbc")
    new_project = getattr(args, "new_project", None)
    interval = getattr(args, "task_interval", None)
    if interval and not new_project:
        raise Failure("--task-interval needs --new-project")
    sdo_blocks = getattr(args, "sdo_blocks", False)
    if sdo_blocks and not new_project:
        raise Failure("--sdo-blocks needs --new-project")
    if new_project and (args.runtime or args.output or args.check_only):
        raise Failure("--new-project only creates an editor project; leave out --runtime, --output and --check-only")
    if not into and not export_dir and not dbc_file and not new_project and not args.check_only and not args.runtime:
        raise Failure("give --runtime to upload, or --check-only")

    # 1. The config and its checks.
    try:
        with open(args.config, encoding="utf-8") as f:
            cfg = json.load(f)
    except OSError as e:
        raise Failure("cannot read %s: %s" % (args.config, e))
    except ValueError as e:
        raise Failure("%s: not valid JSON (%s)" % (args.config, e))
    missing = bundle.missing_eds(cfg, args.config) if isinstance(cfg, dict) else []
    if missing:
        raise Failure("\n".join(missing))
    result = contract.check_config(cfg, args.config, eds_paths=bundle.eds_files(cfg, args.config),
                                   software_paths=bundle.software_files(cfg, args.config))
    for w in result.warnings:
        err("warning: " + w)
    if not result.ok:
        raise Failure("\n".join(result.errors))
    out("ok: %s passes the schema and EDS checks" % args.config)

    # The simulation file and what the config simulates (not for the exports).
    sim_path = None
    simulated = None
    if not export_dir and not dbc_file:
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
        uploading = not into and not new_project and not args.check_only
        if simulated:
            err("warning: this config simulates devices: %s. Outputs to a simulated device go nowhere; never leave "
                "a machine's config simulated." % simulated)
        if simulated and uploading and not (getattr(args, "yes", False) or getattr(args, "simulated", False)):
            answer = (confirm_source or _ask)("Upload this config with simulated devices to %s?" % args.runtime)
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

    if new_project:
        try:
            path, decls = editorproject.create(cfg, args.config, new_project,
                                               interval=interval or editorproject.DEFAULT_INTERVAL, progress=out,
                                               sim_path=sim_path, sdo_blocks=sdo_blocks)
        except editorproject.NewProjectError as e:
            raise Failure(str(e))
        out("created %s with %d CANopen variable%s declared in main" % (path, len(decls),
                                                                       "" if len(decls) == 1 else "s"))
        if sdo_blocks:
            out("the project enables the %s library (CO_SDO_* blocks)" % sdolibrary.NAME)
            ok, message = sdolibrary.ensure_installed()
            (out if ok else err)(message if ok else "warning: " + message)
        return 0

    if into:
        try:
            written, converted = project.write(cfg, args.config, into, force=args.force, sim_path=sim_path)
        except project.ProjectError as e:
            raise Failure(str(e))
        for name in converted:
            out("converted %s from CP1252 to UTF-8 (the editor sends project files as UTF-8)" % name)
        out("wrote %s" % ", ".join(written))
        out("The editor's \"Build and upload\" now carries this config, on a runtime with the CANopen editor hook "
            "(docs/install-stock.md).")
        return 0

    # 2. The bundle.
    bundle_dir = build_project(args.project, args.target, out) if args.project else args.bundle
    try:
        bundle.check_editor_bundle(bundle_dir)
        deployed, eds_by_name = bundle.rewrite(cfg, args.config)
        fw_by_name = bundle.software_by_name(cfg, args.config)
        sim = None
        if sim_path:
            sim_data, sim_eds, sim_csv = bundle.sim_rewrite(simfile.load(sim_path), sim_path)
            bundle.merge_by_name(eds_by_name, sim_eds, "EDS files")
            sim = (sim_data, sim_csv)
    except (bundle.BundleError, simfile.SimFileError) as e:
        raise Failure(str(e))
    work = bundle.temp_dir()
    try:
        staged, converted = bundle.assemble(bundle_dir, deployed, eds_by_name, work, fw_by_name, sim)
        for name in converted:
            out("converted %s from CP1252 to UTF-8 in the bundle" % name)

        # 3. Address clashes with the other plugins in the bundle.
        uses, problems = clash.bundle_uses(staged)
        for p in problems:
            err("warning: " + p)
        errors, warnings = clash.check(uses, args.allow_clash)
        for w in warnings:
            err("warning: " + w)
        if errors:
            raise Failure("\n".join(errors) + "\n(use --allow-clash to deploy anyway)")
        others = sorted({u.file for u in uses} - {"conf/canopen.json"})
        out("ok: no address clashes%s" % (" with " + ", ".join(others) if others else ""))

        zip_path = os.path.join(work, "program.zip")
        names = bundle.make_zip(staged, zip_path)
        out("ok: bundle of %d files with conf/canopen.json and %d EDS file%s%s%s"
            % (len(names), len(eds_by_name), "" if len(eds_by_name) == 1 else "s",
               " and %d program file%s" % (len(fw_by_name), "" if len(fw_by_name) == 1 else "s") if fw_by_name else "",
               ", conf/%s%s" % (bundle.SIM_FILE, " and %d CSV file%s" % (len(sim[1]), "" if len(sim[1]) == 1 else "s")
                                if sim[1] else "") if sim else ""))
        if args.output:
            shutil.copyfile(zip_path, args.output)
            out("wrote %s" % args.output)
        if args.check_only:
            return 0
        with open(zip_path, "rb") as f:
            data = f.read()
    finally:
        shutil.rmtree(work, ignore_errors=True)

    # 4. Upload.
    if not args.user:
        raise Failure("give --user (or set $OPENPLC_USER)")
    client = runtime.Client(args.runtime, ca=args.ca, fingerprint=args.fingerprint, insecure=args.insecure)
    if args.insecure:
        err("warning: --insecure: the runtime's certificate is not checked")
    sent = False
    try:
        client._connect().close()  # certificate first, before any credentials
        password = os.environ.get("OPENPLC_PASSWORD")
        if password is None:
            password = (password_source or getpass.getpass)("Password for %s on %s: " % (args.user, args.runtime))
        client.login(args.user, password)
        out("uploading to %s:%d" % (client.host, client.port))
        client.upload(data)
        sent = True
        ok, logs = client.wait_for_build(lambda line: out("  | " + line.rstrip("\n")), timeout=args.timeout)
    except runtime.RuntimeError_ as e:
        raise Failure(str(e), uploaded=sent)
    if not ok:
        raise Failure("the runtime's build failed (log above)", uploaded=True)
    state = runtime.canopen_state(logs)
    if state is False:
        raise Failure("the build succeeded, but the runtime did not enable the canopen plugin: is it installed on "
                      "the runtime (scripts/install-stock.sh)?", uploaded=True)
    errors = runtime.canopen_errors(logs)
    if errors:
        raise Failure("the build succeeded, but CANopen was turned off: %s" % errors[-1].split("CANopen: ", 1)[1],
                      uploaded=True)
    built = "program built%s" % (" and the canopen plugin enabled" if state else "")
    if args.no_start:
        out("ok: %s; the PLC is stopped (--no-start)" % built)
    else:
        try:
            client.start_plc()
        except runtime.RuntimeError_ as e:
            raise Failure("the %s, but %s" % (built, str(e)[0].lower() + str(e)[1:]), uploaded=True)
        out("ok: %s; the PLC is running" % built)
    out(EDITOR_HOOK_NOTE if any(HOOK_LOG_LINE in line for line in logs) else EDITOR_WARNING)
    return 0


def library_parser():
    p = argparse.ArgumentParser(
        prog="openplc-canopen-deploy library",
        description="The %s editor library: SDO function blocks (CO_SDO_READ, CO_SDO_WRITE, ...) the PLC program "
                    "calls to read and write any object of any node at run time. See docs/plc-sdo.md."
                    % sdolibrary.NAME)
    p.add_argument("--out", metavar="DIR",
                   help="write %s into DIR, for the editor's Library Manager (install from file)"
                        % sdolibrary.FILE_NAME)
    p.add_argument("--install", action="store_true",
                   help="install the library into OpenPLC Editor on this computer, as its Library Manager does "
                        "(restart the editor afterwards)")
    p.add_argument("--project", metavar="DIR", help="enable the library in this editor project")
    p.add_argument("--list", action="store_true", help="list the library's function blocks")
    return p


def run_library(args, out=print, err=None):
    err = err or (lambda m: print(m, file=sys.stderr))
    if not (args.out or args.install or args.project or args.list):
        raise Failure("give --out DIR, --install, --project DIR or --list")
    try:
        if args.list:
            for name in sdolibrary.block_names():
                out(name)
        if args.out:
            out("wrote %s (%s %s)" % (sdolibrary.write(args.out), sdolibrary.NAME, __version__))
        if args.install:
            out("installed %s %s into the editor (%s); restart OpenPLC Editor if it is open"
                % (sdolibrary.NAME, __version__, sdolibrary.install()))
        if args.project:
            sdolibrary.enable_in_project(args.project)
            out("enabled %s in %s" % (sdolibrary.NAME, os.path.abspath(args.project)))
            if not args.install and sdolibrary.installed_version() is None:
                err("note: the editor does not have the library yet: run 'openplc-canopen-deploy library --install'")
    except (sdolibrary.LibraryError, OSError, ValueError) as e:
        raise Failure(str(e))
    return 0


def slave_eds_parser():
    p = argparse.ArgumentParser(
        prog="openplc-canopen-deploy slave-eds",
        description="Write the EDS of OpenPLC as a CANopen slave from a JSON description of its objects (identity, "
                    "heartbeat, layout and objects with name, type, direction and limits), checked with the plugin's "
                    "EDS lint. See docs/slave.md.")
    p.add_argument("description", help="the description (JSON)")
    p.add_argument("-o", "--output", required=True, metavar="FILE.eds",
                   help="the EDS to write, normally into the project's canopen/ folder")
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
        os.replace(tmp, args.gateway)
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


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
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
