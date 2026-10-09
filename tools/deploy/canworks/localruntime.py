"""canworks-sim-runtime: the local simulator runtime (docs/local-runtime.md).

Runs the image ghcr.io/tonihoohoo/canworks-sim-runtime (OpenPLC Runtime v4
with the CANopen plugin built in, every network simulated) on this PC with a
container engine: Docker or Podman, or either of them inside WSL2 on Windows.
Docker Desktop is not needed. The runtime listens on 127.0.0.1 only; its
first user gets a generated password, saved with the certificate fingerprint
in local-runtime.json next to the other settings of the PC tools, so the
editor, `canworks-deploy --runtime local`, `canworks-diag
--runtime local` and the configurator (host `local`) can reach it.
"""

import argparse
import http.client
import json
import os
import secrets
import shutil
import socket
import ssl
import subprocess
import sys
import time

from . import __version__, runtime
from .userdirs import config_dir

PROG = "canworks-sim-runtime"
IMAGE_REPO = "ghcr.io/tonihoohoo/canworks-sim-runtime"
CONTAINER = PROG
VOLUME = PROG + "-data"
# The name of PC tools 0.30.x (canopen-local-runtime: taking over a local
# runtime from the earlier name); its command stays an alias for one release.
OLD_NAME = "openplc-canopen-runtime"
DATA_PATH = "/var/run/runtime"  # upstream's data directory in its image
RUNTIME_PORT = 8443
DIAG_PORT = 7531
USER = "openplc"
SETTINGS_FILE = "local-runtime.json"
ENGINE_ENV = "CANWORKS_ENGINE"
LOCAL = "local"
READY_TIMEOUT = 180.0

ENGINES = {
    "docker": ["docker"],
    "podman": ["podman"],
    "wsl-docker": ["wsl", "-e", "docker"],
    "wsl-podman": ["wsl", "-e", "podman"],
}

DOCS = "docs/local-runtime.md (https://github.com/tonihoohoo/canworks/blob/main/docs/local-runtime.md)"


class LocalRuntimeError(Exception):
    pass


def default_image():
    return "%s:%s" % (IMAGE_REPO, __version__)


# --- Settings ----------------------------------------------------------------

def settings_path():
    return os.path.join(config_dir(), SETTINGS_FILE)


def load_settings():
    """The saved settings, or None when there are none."""
    try:
        with open(settings_path(), encoding="utf-8") as f:
            doc = json.load(f)
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as e:
        raise LocalRuntimeError("cannot read %s: %s" % (settings_path(), e))
    return doc if isinstance(doc, dict) else None


def save_settings(doc):
    path = settings_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    # The password is in it: readable by this user only, where modes exist.
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2, sort_keys=True)
        f.write("\n")
    os.replace(tmp, path)


def delete_settings():
    try:
        os.remove(settings_path())
        return True
    except FileNotFoundError:
        return False


def target():
    """The saved settings for `--runtime local`, or an error naming `start`."""
    doc = load_settings()
    if not doc or not doc.get("password"):
        raise LocalRuntimeError("no local runtime: run `%s start` first" % PROG)
    return doc


def is_local(text):
    return (text or "").strip().lower() == LOCAL


# --- Container engine --------------------------------------------------------

def _run(argv, capture=True, timeout=None, merge=False):
    """subprocess.run on an argument list (never a shell); tests replace it.
    `merge` sends the program's stderr to stdout (uncaptured only)."""
    try:
        return subprocess.run(argv, stdout=subprocess.PIPE if capture else None,
                              stderr=subprocess.PIPE if capture else subprocess.STDOUT if merge else None,
                              timeout=timeout,
                              universal_newlines=True if capture else None)
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(argv, 124, "", "timed out after %s s" % timeout)
    except OSError as e:
        return subprocess.CompletedProcess(argv, 127, "", str(e))


class Engine:
    def __init__(self, name):
        self.name = name
        self.argv = ENGINES[name]

    def __call__(self, *args, capture=True, timeout=None, merge=False):
        if merge:
            return _run(self.argv + list(args), capture=capture, timeout=timeout, merge=True)
        return _run(self.argv + list(args), capture=capture, timeout=timeout)

    def __repr__(self):
        return self.name


def _last_line(text):
    lines = [x for x in (text or "").strip().splitlines() if x.strip()]
    return lines[-1].strip() if lines else ""


def _engine_hint(platform):
    if platform == "darwin":
        return ("On macOS install Colima and the Docker command line with Homebrew (brew install colima docker) "
                "and run `colima start`, or start Podman with `podman machine start`.")
    if platform.startswith("win"):
        return ("On Windows install Docker Engine or Podman inside a WSL2 Linux distribution, or Podman for "
                "Windows, and make sure it runs.")
    return "On Linux install Docker Engine or Podman and make sure it runs (Docker: sudo systemctl start docker)."


def detect_engine(choice=None, platform=None, which=None):
    """The container engine to use: `choice`, else $CANWORKS_ENGINE,
    else the first that answers `info`: docker, podman, and on Windows the
    same two inside the default WSL distribution."""
    platform = platform or sys.platform
    which = which or shutil.which
    choice = choice or os.environ.get(ENGINE_ENV) or None
    if choice and choice not in ENGINES:
        raise LocalRuntimeError("unknown container engine %r (choose from %s)" % (choice, ", ".join(ENGINES)))
    order = [choice] if choice else ["docker", "podman"] + (
        ["wsl-docker", "wsl-podman"] if platform.startswith("win") else [])
    found = []
    for name in order:
        eng = Engine(name)
        if not which(eng.argv[0]):
            found.append("%s: not installed" % name)
            continue
        r = eng("info", timeout=30)
        if r.returncode == 0:
            return eng
        found.append("%s: %s" % (name, _last_line(r.stderr) or _last_line(r.stdout) or "not running"))
    raise LocalRuntimeError("no container engine is running (%s). %s See %s."
                            % ("; ".join(found), _engine_hint(platform), DOCS))


def container_state(eng, name=CONTAINER):
    """(status, image) of the runtime container, or None when there is none."""
    r = eng("inspect", "--type", "container", "--format", "{{.State.Status}}|{{.Config.Image}}", name,
            timeout=30)
    if r.returncode != 0:
        return None
    status, _, image = (r.stdout or "").strip().partition("|")
    return status.lower(), image


def saved_volume(settings):
    """The data volume in use: the one saved (a runtime taken over from the
    earlier name keeps its volume), else the default."""
    return (settings or {}).get("volume") or VOLUME


def _volume_of(eng, name):
    r = eng("inspect", "--type", "container", "--format",
            '{{range .Mounts}}{{if eq .Destination "%s"}}{{.Name}}{{end}}{{end}}' % DATA_PATH, name, timeout=30)
    return (r.stdout or "").strip() if r.returncode == 0 else ""


def _old_note(eng):
    return ("note: an older local runtime container %s exists as well; remove it with `%s rm -f %s`"
            % (OLD_NAME, " ".join(eng.argv), OLD_NAME))


def take_over(eng, out):
    """A container from the earlier name (PC tools 0.30.x) and none under the
    current one: removes the old container and returns its data volume, so the
    new container keeps the program, user and certificate. None otherwise."""
    if container_state(eng, OLD_NAME) is None:
        return None
    if container_state(eng) is not None:
        out(_old_note(eng))
        return None
    volume = _volume_of(eng, OLD_NAME) or OLD_NAME + "-data"
    eng("stop", OLD_NAME, timeout=120)
    r = eng("rm", OLD_NAME, timeout=60)
    if r.returncode != 0:
        raise LocalRuntimeError("%s could not remove the old container %s: %s"
                                % (eng.name, OLD_NAME, _last_line(r.stderr)))
    out("took over the local runtime %s (renamed %s): same data volume %s" % (OLD_NAME, CONTAINER, volume))
    return volume


def _has_image(eng, image):
    return eng("image", "inspect", image, timeout=60).returncode == 0


def pull(eng, image, out):
    out("pulling %s with %s" % (image, eng.name))
    r = eng("pull", image, capture=False)
    if r.returncode != 0:
        hint = ""
        if image == default_image():
            hint = (" If this version was released only just now, its image may still be building: try again "
                    "later, or use --image %s:latest." % IMAGE_REPO)
        raise LocalRuntimeError("could not pull %s.%s" % (image, hint))


def _run_args(image, port, diag_port, caps=True, volume=VOLUME):
    args = ["run", "-d", "--name", CONTAINER,
            "-p", "127.0.0.1:%d:%d" % (port, RUNTIME_PORT),
            "-p", "127.0.0.1:%d:%d" % (diag_port, diag_port),
            "-v", "%s:%s" % (volume, DATA_PATH),
            "--restart", "unless-stopped"]
    if caps:
        # Upstream's flags for its real-time scheduling, and an unlimited
        # memlock so the runtime's mlockall works; timing only.
        args += ["--cap-add", "SYS_NICE", "--cap-add", "SYS_RESOURCE", "--ulimit", "memlock=-1:-1"]
    return args + [image]


def create(eng, image, port, diag_port, out, volume=VOLUME):
    """Creates and starts the container; removes what a failed attempt left."""
    r = eng(*_run_args(image, port, diag_port, volume=volume), timeout=600)
    if r.returncode != 0:
        msg = (r.stderr or r.stdout or "").strip()
        eng("rm", "-f", CONTAINER, timeout=60)
        low = msg.lower()
        if ("cap" in low and ("sys_nice" in low or "sys_resource" in low or "capabilit" in low)) or \
                "memlock" in low or "rlimit" in low or "ulimit" in low:
            out("note: %s refused the real-time capabilities; starting without them (only timing is affected)"
                % eng.name)
            r = eng(*_run_args(image, port, diag_port, caps=False, volume=volume), timeout=600)
            if r.returncode == 0:
                return
            msg = (r.stderr or r.stdout or "").strip()
            low = msg.lower()
            eng("rm", "-f", CONTAINER, timeout=60)
        if "address already in use" in low or "port is already allocated" in low:
            raise LocalRuntimeError("port %d or %d is already in use on this PC: choose others with --port and "
                                    "--diag-port (%s)" % (port, diag_port, _last_line(msg)))
        raise LocalRuntimeError("%s could not start the container: %s" % (eng.name, _last_line(msg) or "no reason"))


# --- The runtime's HTTPS API ---------------------------------------------------

def read_fingerprint(port, host="127.0.0.1", timeout=5.0):
    pem = ssl.get_server_certificate((host, port), timeout=timeout) if sys.version_info >= (3, 10) \
        else ssl.get_server_certificate((host, port))
    return runtime.fingerprint_of(ssl.PEM_cert_to_DER_cert(pem))


def wait_ready(port, timeout=READY_TIMEOUT, sleep=time.sleep, out=None):
    """Waits until the runtime answers /api/version; returns its certificate
    fingerprint."""
    deadline = time.monotonic() + timeout
    said = False
    while True:
        try:
            fp = read_fingerprint(port)
            client = runtime.Client("127.0.0.1:%d" % port, fingerprint=fp, timeout=5.0)
            status, _ = client._request("GET", "/api/version")
            if status == 200:
                return fp
        except (OSError, ssl.SSLError, runtime.RuntimeError_, http.client.HTTPException, socket.timeout):
            pass
        if time.monotonic() > deadline:
            raise LocalRuntimeError("the runtime did not answer on https://localhost:%d within %d s; see "
                                    "`canworks-sim-runtime logs`" % (port, timeout))
        if out and not said:
            out("waiting for the runtime to answer on https://localhost:%d" % port)
            said = True
        sleep(1.0)


def has_users(client):
    """Whether the runtime has any user (unauthenticated: 404 none, 200 some)."""
    status, doc = client._request("GET", "/api/get-users-info")
    if status == 404:
        return False
    if status == 200:
        return True
    raise LocalRuntimeError("cannot tell whether the runtime has users (HTTP %d): %s" % (status, doc))


def create_user(client, user, password):
    status, doc = client._request("POST", "/api/create-user", json.dumps({"username": user, "password": password}),
                                  {"Content-Type": "application/json"})
    if status not in (200, 201):
        raise LocalRuntimeError("the runtime refused to create user %s (HTTP %d): %s" % (user, status, doc))


def new_password():
    return secrets.token_urlsafe(18)[:24]  # 24 characters from the URL-safe alphabet


# --- Commands ----------------------------------------------------------------

def _engine_for(args, settings):
    return detect_engine(args.engine or (settings or {}).get("engine"))


def _editor_text(doc):
    return ("Connect the OpenPLC Editor to it: target OpenPLC Runtime v4, address localhost:%d, user %s, "
            "password %s.\n"
            "Deploy with:   canworks-deploy --runtime local ...\n"
            "Diagnostics:   canworks-diag --runtime local status   (configurator: host \"local\")\n"
            "Every CANopen network runs simulated here: no CAN interface is used."
            % (doc["port"], doc["user"], doc["password"]))


def _credentials(eng, image, port, diag_port, settings, out, volume=VOLUME):
    """After the runtime answers: first user, fingerprint and saved settings.
    Returns the settings, or raises when the credentials are lost."""
    fp = wait_ready(port, out=out)
    client = runtime.Client("127.0.0.1:%d" % port, fingerprint=fp)
    doc = dict(settings or {})
    doc.update({"engine": eng.name, "image": image, "port": port, "diag_port": diag_port, "volume": volume,
                "url": "https://127.0.0.1:%d" % port, "fingerprint": fp})
    if not has_users(client):
        doc["user"], doc["password"] = USER, new_password()
        create_user(client, doc["user"], doc["password"])
        out("created runtime user %s" % doc["user"])
        save_settings(doc)
        return doc
    if not settings or not settings.get("password"):
        raise LocalRuntimeError("the local runtime already has a user, but its password is not saved on this PC "
                                "(%s is missing). It cannot be recovered: run `canworks-sim-runtime remove "
                                "--data` and `start` again for new credentials." % settings_path())
    if runtime.normalize_fingerprint(settings.get("fingerprint") or "") != runtime.normalize_fingerprint(fp):
        out("note: the runtime's certificate changed; the new fingerprint is saved")
    try:
        client.login(settings["user"], settings["password"])
    except runtime.RuntimeError_ as e:
        raise LocalRuntimeError("the saved credentials do not log in (%s). Run `canworks-sim-runtime remove "
                                "--data` and `start` again for new ones." % e)
    save_settings(doc)
    return doc


def cmd_start(args, out):
    settings = load_settings()
    eng = _engine_for(args, settings)
    image = args.image or default_image()
    port = args.port or (settings or {}).get("port") or RUNTIME_PORT
    diag_port = args.diag_port or (settings or {}).get("diag_port") or DIAG_PORT
    volume = take_over(eng, out) or saved_volume(settings)
    state = container_state(eng)
    if state is None:
        if not _has_image(eng, image):
            pull(eng, image, out)
        out("starting %s (%s) with %s" % (CONTAINER, image, eng.name))
        create(eng, image, port, diag_port, out, volume)
    else:
        status, running_image = state
        if args.image and running_image != args.image:
            raise LocalRuntimeError("the local runtime runs image %s, not %s: run `canworks-sim-runtime update "
                                    "--image %s`" % (running_image, args.image, args.image))
        if running_image != image:
            out("note: the local runtime runs image %s; `canworks-sim-runtime update` switches it to %s"
                % (running_image, image))
            image = running_image
        if args.port and settings and args.port != settings.get("port") or \
                args.diag_port and settings and args.diag_port != settings.get("diag_port"):
            raise LocalRuntimeError("the container exists with other ports; run `canworks-sim-runtime update` "
                                    "with --port/--diag-port to change them")
        if status == "running":
            out("the local runtime is already running")
        else:
            r = eng("start", CONTAINER, timeout=120)
            if r.returncode != 0:
                raise LocalRuntimeError("%s could not start %s: %s" % (eng.name, CONTAINER, _last_line(r.stderr)))
            out("started %s" % CONTAINER)
    doc = _credentials(eng, image, port, diag_port, settings, out, volume)
    out(_editor_text(doc))
    return 0


def cmd_stop(args, out):
    settings = load_settings()
    eng = _engine_for(args, settings)
    state = container_state(eng)
    if state is None:
        out("there is no local runtime container")
        return 0
    if state[0] != "running":
        out("the local runtime is not running (%s)" % state[0])
        return 0
    r = eng("stop", CONTAINER, timeout=120)
    if r.returncode != 0:
        raise LocalRuntimeError("%s could not stop %s: %s" % (eng.name, CONTAINER, _last_line(r.stderr)))
    out("stopped %s" % CONTAINER)
    return 0


def canopen_lines(log_text, limit=3):
    """The last CANopen lines of the runtime log."""
    lines = [x.strip() for x in (log_text or "").splitlines() if "[CANOPEN]" in x]
    return lines[-limit:]


def cmd_status(args, out):
    settings = load_settings()
    eng = _engine_for(args, settings)
    out("engine: %s" % eng.name)
    state = container_state(eng)
    old = container_state(eng, OLD_NAME)
    if state is None:
        if old is not None:
            out("container: none; the older local runtime %s (%s) is there: `%s update` takes it over with "
                "its data" % (OLD_NAME, old[0], PROG))
        else:
            out("container: none (run `%s start`)" % PROG)
        return 1
    out("container: %s, %s" % (CONTAINER, state[0]))
    if old is not None:
        out(_old_note(eng))
    out("image: %s" % state[1])
    if not settings:
        out("credentials: not saved on this PC (%s)" % settings_path())
    else:
        out("runtime: https://localhost:%s, user %s%s" % (settings.get("port"), settings.get("user"),
                                                          ", password " + settings.get("password", "")
                                                          if args.show_password else ""))
        out("diagnostics: localhost:%s" % settings.get("diag_port"))
    if state[0] != "running":
        return 1
    if settings:
        try:
            client = runtime.Client("127.0.0.1:%d" % settings["port"], fingerprint=settings.get("fingerprint"),
                                    timeout=5.0)
            client.login(settings["user"], settings["password"])
            out("PLC: %s" % client.plc_status())
        except (runtime.RuntimeError_, OSError, ssl.SSLError) as e:
            out("PLC: unknown (%s)" % e)
    r = eng("logs", "--tail", "400", CONTAINER, timeout=60)
    lines = canopen_lines((r.stdout or "") + "\n" + (r.stderr or ""))
    out("CANopen: %s" % ("\n  ".join([""] + lines) if lines else "no CANopen lines in the log yet (no upload "
                                                                 "with a CANopen config, or the PLC not started)"))
    return 0


def cmd_logs(args, out):
    eng = _engine_for(args, load_settings())
    if container_state(eng) is None:
        out("there is no local runtime container")
        return 1
    # The runtime writes to both streams: one stream, so `logs | grep` sees all.
    return eng(*(["logs"] + (["-f"] if args.follow else []) + [CONTAINER]), capture=False, merge=True).returncode


def cmd_update(args, out):
    settings = load_settings()
    eng = _engine_for(args, settings)
    image = args.image or default_image()
    port = args.port or (settings or {}).get("port") or RUNTIME_PORT
    diag_port = args.diag_port or (settings or {}).get("diag_port") or DIAG_PORT
    try:
        pull(eng, image, out)
    except LocalRuntimeError:
        if not _has_image(eng, image):
            raise
        out("note: could not pull %s; using the copy on this PC" % image)
    volume = take_over(eng, out) or saved_volume(settings)
    if container_state(eng) is not None:
        eng("stop", CONTAINER, timeout=120)
        r = eng("rm", CONTAINER, timeout=60)
        if r.returncode != 0:
            raise LocalRuntimeError("%s could not remove the old container: %s" % (eng.name, _last_line(r.stderr)))
    out("starting %s (%s) with %s on the same data volume" % (CONTAINER, image, eng.name))
    create(eng, image, port, diag_port, out, volume)
    doc = _credentials(eng, image, port, diag_port, settings, out, volume)
    out("The container is new: upload the PLC program again (the editor's Build and Upload, or "
        "canworks-deploy --runtime local).")
    out(_editor_text(doc))
    return 0


def cmd_remove(args, out):
    settings = load_settings()
    eng = _engine_for(args, settings)
    if container_state(eng) is None:
        out("there is no local runtime container")
    else:
        r = eng("rm", "-f", CONTAINER, timeout=120)
        if r.returncode != 0:
            raise LocalRuntimeError("%s could not remove %s: %s" % (eng.name, CONTAINER, _last_line(r.stderr)))
        out("removed %s" % CONTAINER)
    if args.data:
        volume = saved_volume(settings)
        r = eng("volume", "rm", volume, timeout=60)
        out("removed the data volume %s" % volume if r.returncode == 0 else "no data volume %s" % volume)
        if delete_settings():
            out("removed %s" % settings_path())
    return 0


def parser():
    p = argparse.ArgumentParser(
        prog=PROG,
        description="Run OpenPLC Runtime v4 with the CANopen plugin on this PC, every CANopen network simulated, "
                    "in a container (Docker or Podman; Docker Desktop is not needed). See " + DOCS + ".")
    p.add_argument("--engine", choices=sorted(ENGINES),
                   help="the container engine (default: $%s, else the first that runs of docker, podman and, on "
                        "Windows, the two inside WSL)" % ENGINE_ENV)
    p.add_argument("--version", action="version", version="%(prog)s " + __version__)
    sub = p.add_subparsers(dest="command", metavar="COMMAND")
    sub.required = True

    def ports(sp):
        sp.add_argument("--image", help="the image (default %s)" % default_image())
        sp.add_argument("--port", type=int, help="the runtime's port on this PC (default %d)" % RUNTIME_PORT)
        sp.add_argument("--diag-port", type=int,
                        help="the diagnostics port (default %d; set it when the config's master.diagnostics uses "
                             "another)" % DIAG_PORT)

    ports(sub.add_parser("start", help="start the local runtime (creates it and its user the first time)"))
    sub.add_parser("stop", help="stop the local runtime")
    st = sub.add_parser("status", help="show the container, the runtime and the CANopen state")
    st.add_argument("--show-password", action="store_true", help="also print the saved password")
    lg = sub.add_parser("logs", help="print the runtime's log")
    lg.add_argument("-f", "--follow", action="store_true", help="keep following the log")
    ports(sub.add_parser("update", help="run the image for this version of the tools, keeping the data"))
    rm = sub.add_parser("remove", help="delete the container")
    rm.add_argument("--data", action="store_true", help="also delete its data volume and the saved credentials")
    return p


def old_main(argv=None):
    """The command's earlier name, kept for one release."""
    print("%s is now %s; this name goes away in the next release" % (OLD_NAME, PROG), file=sys.stderr, flush=True)
    return main(argv)


COMMANDS = {"start": cmd_start, "stop": cmd_stop, "status": cmd_status, "logs": cmd_logs, "update": cmd_update,
            "remove": cmd_remove}


def main(argv=None):
    args = parser().parse_args(argv)

    def out(text):
        print(text, flush=True)

    try:
        return COMMANDS[args.command](args, out)
    except LocalRuntimeError as e:
        print("%s: %s" % (PROG, e), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
