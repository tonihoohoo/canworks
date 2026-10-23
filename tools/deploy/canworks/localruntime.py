"""canworks-local-runtime: the local runtime (docs/local-runtime.md).

Runs two containers on this PC with a container engine (Docker or Podman, or
either of them inside WSL2 on Windows; Docker Desktop is not needed):

- canworks-local-runtime: upstream's OpenPLC Runtime v4 image at the pinned
  version, unchanged, on 127.0.0.1 only (the runtime's port and the bridge's
  diagnostics port);
- canworks-local-bridge: the canworks-bridge image of the PC tools' version
  in the runtime container's network, so the runtime's Modbus master reaches
  it at 127.0.0.1:1502, with every network forced simulated. It waits for a
  config; `canworks-deploy --bridge local` and the configurator put one on it.

The runtime's first user gets a generated password, saved with the
certificate fingerprint in local-runtime.json next to the other settings of
the PC tools, so the editor, `canworks-diag --runtime local` and the
configurator (host `local`) can reach it.
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
import tempfile
import time

from . import __version__, runtime
from .devices import plan
from .userdirs import config_dir, replace_file

PROG = "canworks-local-runtime"
IMAGE_REPO = "ghcr.io/tonihoohoo/canworks-bridge"
RUNTIME_IMAGE_REPO = "ghcr.io/autonomy-logic/openplc-runtime"
CONTAINER = PROG
BRIDGE = "canworks-local-bridge"
VOLUME = PROG + "-data"
BRIDGE_VOLUME = BRIDGE + "-config"
DATA_PATH = "/var/run/runtime"  # upstream's data directory in its image
BRIDGE_CONF = "/etc/canworks-bridge"  # the bridge image's config folder
# The runtime makes its HTTPS certificate at first start next to its code;
# `update` carries it to the new container, so the pinned fingerprint holds.
CERT_DIR = "/workdir/webserver"
CERT_FILES = ("certOPENPLC.pem", "keyOPENPLC.pem")
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
    """The bridge image of these PC tools."""
    return "%s:%s" % (IMAGE_REPO, __version__)


def runtime_image():
    """Upstream's runtime image at the pinned version (plan.TESTED_RUNTIME)."""
    return "%s:%s" % (RUNTIME_IMAGE_REPO, plan.TESTED_RUNTIME)


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
    replace_file(tmp, path)


def delete_settings():
    try:
        os.remove(settings_path())
        return True
    except FileNotFoundError:
        return False


def target():
    """The saved settings for `--bridge local`, or an error naming `start`."""
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
    """(status, image) of a container (default the runtime's), or None when
    there is none."""
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


def ensure_image(eng, image, out):
    if not _has_image(eng, image):
        pull(eng, image, out)


def _run_args(image, port, diag_port, caps=True, volume=VOLUME):
    args = ["create", "--name", CONTAINER,
            "-p", "127.0.0.1:%d:%d" % (port, RUNTIME_PORT),
            "-p", "127.0.0.1:%d:%d" % (diag_port, diag_port),
            "-v", "%s:%s" % (volume, DATA_PATH),
            "--restart", "unless-stopped"]
    if caps:
        # Upstream's flags for its real-time scheduling, and an unlimited
        # memlock so the runtime's mlockall works; timing only.
        args += ["--cap-add", "SYS_NICE", "--cap-add", "SYS_RESOURCE", "--ulimit", "memlock=-1:-1"]
    return args + [image]


def _bridge_args(image):
    return ["run", "-d", "--name", BRIDGE, "--network", "container:" + CONTAINER,
            "-e", "CANWORKS_FORCE_SIMULATE=1", "-v", "%s:%s" % (BRIDGE_VOLUME, BRIDGE_CONF),
            "--restart", "unless-stopped", image]


def _start_runtime(eng, image, port, diag_port, out, volume, caps, cert):
    """Creates the runtime container (with the certificate files in `cert`,
    a folder, when given) and starts it; (returncode, message)."""
    r = eng(*_run_args(image, port, diag_port, caps=caps, volume=volume), timeout=600)
    if r.returncode != 0:
        return r.returncode, (r.stderr or r.stdout or "").strip()
    if cert:
        for name in CERT_FILES:
            if os.path.isfile(os.path.join(cert, name)):
                eng("cp", os.path.join(cert, name), "%s:%s/%s" % (CONTAINER, CERT_DIR, name), timeout=60)
    r = eng("start", CONTAINER, timeout=600)
    return r.returncode, (r.stderr or r.stdout or "").strip()


def create(eng, image, port, diag_port, out, volume=VOLUME, bridge_image=None, cert=None):
    """Creates and starts the runtime container from `image` and the bridge
    container from `bridge_image` in its network; removes what a failed
    attempt left. `cert`: a folder with the runtime's certificate files to
    put in first (update keeps the fingerprint)."""
    rc, msg = _start_runtime(eng, image, port, diag_port, out, volume, True, cert)
    if rc != 0:
        eng("rm", "-f", CONTAINER, timeout=60)
        low = msg.lower()
        if ("cap" in low and ("sys_nice" in low or "sys_resource" in low or "capabilit" in low)) or \
                "memlock" in low or "rlimit" in low or "ulimit" in low:
            out("note: %s refused the real-time capabilities; starting without them (only timing is affected)"
                % eng.name)
            rc, msg = _start_runtime(eng, image, port, diag_port, out, volume, False, cert)
            low = msg.lower()
            if rc != 0:
                eng("rm", "-f", CONTAINER, timeout=60)
        if rc != 0:
            if "address already in use" in low or "port is already allocated" in low:
                raise LocalRuntimeError("port %d or %d is already in use on this PC: choose others with --port "
                                        "and --diag-port (%s)" % (port, diag_port, _last_line(msg)))
            raise LocalRuntimeError("%s could not start the container: %s" % (eng.name, _last_line(msg) or
                                                                              "no reason"))
    r = eng(*_bridge_args(bridge_image or default_image()), timeout=600)
    if r.returncode != 0:
        msg = (r.stderr or r.stdout or "").strip()
        eng("rm", "-f", BRIDGE, timeout=60)
        eng("rm", "-f", CONTAINER, timeout=60)
        hint = " (the engine cannot share the runtime container's network)" if "network" in msg.lower() else ""
        raise LocalRuntimeError("%s could not start the bridge container%s: %s"
                                % (eng.name, hint, _last_line(msg) or "no reason"))


def _save_cert(eng, folder):
    """Copies the runtime container's certificate files into `folder`;
    the folder when both were copied, else None."""
    for name in CERT_FILES:
        r = eng("cp", "%s:%s/%s" % (CONTAINER, CERT_DIR, name), os.path.join(folder, name), timeout=60)
        if r.returncode != 0:
            return None
    return folder


def put_config(settings, files, out, timeout=60.0, sleep=time.sleep, clock=time.time):
    """Puts a config's files ({path: bytes}, bundle.files) on the local
    bridge through the container engine and restarts the bridge on it;
    returns once its log says the config started, raises with the bridge's
    reason when it did not."""
    eng = detect_engine((settings or {}).get("engine"))
    state = container_state(eng, BRIDGE)
    if state is None:
        raise LocalRuntimeError("there is no local bridge container: run `%s start`" % PROG)
    work = tempfile.mkdtemp(prefix="canworks-local-")
    try:
        for rel, data in files.items():
            path = os.path.join(work, *rel.split("/"))
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as f:
                f.write(data)
        if state[0] == "running":
            # Files of an earlier config (EDS, simulation) go first.
            eng("exec", BRIDGE, "sh", "-c", "rm -rf %s/canworks %s/canworks.json" % (BRIDGE_CONF, BRIDGE_CONF),
                timeout=60)
        r = eng("cp", work + os.sep + ".", "%s:%s" % (BRIDGE, BRIDGE_CONF), timeout=120)
        if r.returncode != 0:
            raise LocalRuntimeError("%s could not copy the config into %s: %s"
                                    % (eng.name, BRIDGE, _last_line(r.stderr) or "no reason"))
    finally:
        shutil.rmtree(work, ignore_errors=True)
    since = str(int(clock()) - 1)
    r = eng("restart", BRIDGE, timeout=120)
    if r.returncode != 0:
        raise LocalRuntimeError("%s could not restart %s: %s" % (eng.name, BRIDGE, _last_line(r.stderr)))
    out("put the config on the local bridge; it restarts on it")
    deadline = clock() + timeout
    while True:
        r = eng("logs", "--since", since, BRIDGE, timeout=60)
        text = (r.stdout or "") + "\n" + (r.stderr or "")
        failed = [x.strip() for x in text.splitlines() if "canworks-bridge not started" in x]
        if failed:
            raise LocalRuntimeError("the local bridge did not start the config: %s" % failed[-1])
        if any("canworks-bridge: config " in x for x in text.splitlines()):
            out("ok: the local bridge runs the new config (every network simulated)")
            return
        if clock() > deadline:
            raise LocalRuntimeError("the local bridge did not start the config within %d s; see `%s logs`"
                                    % (timeout, PROG))
        sleep(1.0)


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
                                    "`canworks-local-runtime logs`" % (port, timeout))
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
            "password from `%s status --show-password`.\n"
            "Put the project's config on its bridge:   canworks-deploy --config canworks/canworks.json --bridge local\n"
            "Diagnostics:   canworks-diag --runtime local status   (configurator: host \"local\")\n"
            "Every network runs simulated here: no CAN interface is used."
            % (doc["port"], doc["user"], PROG))


def certificate_changed(port, saved, seen):
    return ("the local runtime's certificate changed (saved fingerprint %s, now %s): another program may be "
            "answering on port %s, so nothing was sent to it. Stop that program; if you recreated the container "
            "yourself, run `%s remove` and `%s start`, which pins the new certificate"
            % (saved, seen, port, PROG, PROG))


def _credentials(eng, image, port, diag_port, settings, out, volume=VOLUME, created=False):
    """After the runtime answers: first user, fingerprint and saved settings.
    Returns the settings, or raises when the credentials are lost. The saved
    fingerprint is replaced only when this command `created` the container;
    any other change stops here, before anything is sent."""
    fp = wait_ready(port, out=out)
    pinned = (settings or {}).get("fingerprint")
    changed = pinned and runtime.normalize_fingerprint(pinned) != runtime.normalize_fingerprint(fp)
    if changed and not created:
        raise LocalRuntimeError(certificate_changed(port, pinned, fp))
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
                                "(%s is missing). It cannot be recovered: run `canworks-local-runtime remove "
                                "--data` and `start` again for new credentials." % settings_path())
    if changed:
        out("note: the runtime's certificate changed; the new fingerprint is saved")
    try:
        client.login(settings["user"], settings["password"])
    except runtime.RuntimeError_ as e:
        raise LocalRuntimeError("the saved credentials do not log in (%s). Run `canworks-local-runtime remove "
                                "--data` and `start` again for new ones." % e)
    save_settings(doc)
    return doc


def _bridge_image(args, state):
    """The bridge image to run: --image, else the bridge container's (with a
    note when `update` would switch it), else the tools' version."""
    if args.image:
        if state and state[1] != args.image:
            raise LocalRuntimeError("the local bridge runs image %s, not %s: run `canworks-local-runtime update "
                                    "--image %s`" % (state[1], args.image, args.image))
        return args.image
    return state[1] if state else default_image()


def cmd_start(args, out):
    settings = load_settings()
    eng = _engine_for(args, settings)
    image = getattr(args, "runtime_image", None) or (settings or {}).get("runtime_image") or runtime_image()
    port = args.port or (settings or {}).get("port") or RUNTIME_PORT
    diag_port = args.diag_port or (settings or {}).get("diag_port") or DIAG_PORT
    volume = saved_volume(settings)
    state = container_state(eng)
    bstate = container_state(eng, BRIDGE)
    bridge_image = _bridge_image(args, bstate)
    if bstate and bstate[1] != default_image() and not args.image:
        out("note: the local bridge runs image %s; `canworks-local-runtime update` switches it to %s"
            % (bstate[1], default_image()))
    if state is None or bstate is None:
        for c in (BRIDGE, CONTAINER):
            eng("rm", "-f", c, timeout=60)  # a half of an earlier pair
        ensure_image(eng, image, out)
        ensure_image(eng, bridge_image, out)
        out("starting %s (%s) and %s (%s) with %s" % (CONTAINER, image, BRIDGE, bridge_image, eng.name))
        create(eng, image, port, diag_port, out, volume, bridge_image)
        created = state is None
    else:
        if args.port and settings and args.port != settings.get("port") or \
                args.diag_port and settings and args.diag_port != settings.get("diag_port"):
            raise LocalRuntimeError("the containers exist with other ports; run `canworks-local-runtime update` "
                                    "with --port/--diag-port to change them")
        image = state[1]
        if state[0] == "running" and bstate[0] == "running":
            out("the local runtime is already running")
        else:
            for name, st in ((CONTAINER, state), (BRIDGE, bstate)):
                if st[0] != "running":
                    r = eng("start", name, timeout=120)
                    if r.returncode != 0:
                        raise LocalRuntimeError("%s could not start %s: %s" % (eng.name, name, _last_line(r.stderr)))
                    out("started %s" % name)
        created = False
    doc = _credentials(eng, image, port, diag_port, settings, out, volume, created=created)
    doc["bridge_image"] = bridge_image
    doc["runtime_image"] = image
    save_settings(doc)
    out(_editor_text(doc))
    return 0


def cmd_stop(args, out):
    settings = load_settings()
    eng = _engine_for(args, settings)
    if container_state(eng) is None and container_state(eng, BRIDGE) is None:
        out("there is no local runtime container")
        return 0
    stopped = False
    for name in (BRIDGE, CONTAINER):
        state = container_state(eng, name)
        if state is None or state[0] != "running":
            continue
        r = eng("stop", name, timeout=120)
        if r.returncode != 0:
            raise LocalRuntimeError("%s could not stop %s: %s" % (eng.name, name, _last_line(r.stderr)))
        out("stopped %s" % name)
        stopped = True
    if not stopped:
        out("the local runtime is not running")
    return 0


def bridge_lines(log_text, limit=3):
    """The last canworks lines of the bridge's log."""
    lines = [x.strip() for x in (log_text or "").splitlines() if "[CANWORKS]" in x]
    return lines[-limit:]


def cmd_status(args, out):
    settings = load_settings()
    eng = _engine_for(args, settings)
    out("engine: %s" % eng.name)
    state = container_state(eng)
    bstate = container_state(eng, BRIDGE)
    if state is None and bstate is None:
        out("containers: none (run `%s start`)" % PROG)
        return 1
    for name, st in ((CONTAINER, state), (BRIDGE, bstate)):
        out("%s: %s" % (name, "%s, image %s" % st if st else "missing (run `%s start`)" % PROG))
    if not settings:
        out("credentials: not saved on this PC (%s)" % settings_path())
    else:
        out("runtime: https://localhost:%s, user %s%s" % (settings.get("port"), settings.get("user"),
                                                          ", password " + settings.get("password", "")
                                                          if args.show_password else ""))
        out("bridge diagnostics: localhost:%s" % settings.get("diag_port"))
    if state is None or state[0] != "running":
        return 1
    if settings:
        try:
            client = runtime.Client("127.0.0.1:%d" % settings["port"], fingerprint=settings.get("fingerprint"),
                                    timeout=5.0)
            client.login(settings["user"], settings["password"])
            out("PLC: %s" % client.plc_status())
        except (runtime.RuntimeError_, OSError, ssl.SSLError) as e:
            out("PLC: unknown (%s)" % e)
    if bstate is None:
        return 1
    r = eng("logs", "--tail", "400", BRIDGE, timeout=60)
    text = (r.stdout or "") + "\n" + (r.stderr or "")
    if any("waiting for a config" in x for x in text.splitlines()) and \
            not any("canworks-bridge: config " in x for x in text.splitlines()):
        out("bridge: waiting for a config (canworks-deploy --config ... --bridge local)")
    lines = bridge_lines(text)
    out("bridge log: %s" % ("\n  ".join([""] + lines) if lines else "nothing yet"))
    return 0 if bstate[0] == "running" else 1


def cmd_logs(args, out):
    eng = _engine_for(args, load_settings())
    name = CONTAINER if args.runtime else BRIDGE
    if container_state(eng, name) is None:
        out("there is no %s container" % name)
        return 1
    # Both streams in one, so `logs | grep` sees all.
    return eng(*(["logs"] + (["-f"] if args.follow else []) + [name]), capture=False, merge=True).returncode


def cmd_update(args, out):
    settings = load_settings()
    eng = _engine_for(args, settings)
    image = getattr(args, "runtime_image", None) or runtime_image()
    bridge_image = args.image or default_image()
    port = args.port or (settings or {}).get("port") or RUNTIME_PORT
    diag_port = args.diag_port or (settings or {}).get("diag_port") or DIAG_PORT
    for img in (image, bridge_image):
        try:
            pull(eng, img, out)
        except LocalRuntimeError:
            if not _has_image(eng, img):
                raise
            out("note: could not pull %s; using the copy on this PC" % img)
    volume = saved_volume(settings)
    cert_dir = tempfile.mkdtemp(prefix="canworks-local-cert-")
    try:
        cert = _save_cert(eng, cert_dir) if container_state(eng) is not None else None
        for name in (BRIDGE, CONTAINER):
            if container_state(eng, name) is not None:
                eng("stop", name, timeout=120)
                r = eng("rm", name, timeout=60)
                if r.returncode != 0:
                    raise LocalRuntimeError("%s could not remove the old container %s: %s"
                                            % (eng.name, name, _last_line(r.stderr)))
        out("starting %s (%s) and %s (%s) with %s on the same volumes" % (CONTAINER, image, BRIDGE, bridge_image,
                                                                          eng.name))
        create(eng, image, port, diag_port, out, volume, bridge_image, cert=cert)
    finally:
        shutil.rmtree(cert_dir, ignore_errors=True)
    doc = _credentials(eng, image, port, diag_port, settings, out, volume, created=True)
    doc["bridge_image"], doc["runtime_image"] = bridge_image, image
    save_settings(doc)
    out("The containers are new: upload the PLC program again (the editor's Build and Upload); the bridge kept its "
        "config.")
    out(_editor_text(doc))
    return 0


def cmd_remove(args, out):
    settings = load_settings()
    eng = _engine_for(args, settings)
    if container_state(eng) is None and container_state(eng, BRIDGE) is None:
        out("there is no local runtime container")
    for name in (BRIDGE, CONTAINER):
        if container_state(eng, name) is None:
            continue
        r = eng("rm", "-f", name, timeout=120)
        if r.returncode != 0:
            raise LocalRuntimeError("%s could not remove %s: %s" % (eng.name, name, _last_line(r.stderr)))
        out("removed %s" % name)
    if args.data:
        kept = []
        for volume in (saved_volume(settings), BRIDGE_VOLUME):
            r = eng("volume", "rm", volume, timeout=60)
            if r.returncode == 0:
                out("removed the volume %s" % volume)
            elif "no such volume" in (r.stderr or "").lower():
                out("no volume %s" % volume)
            else:
                # Typically "volume is in use" by a container of an older install.
                kept.append("%s could not remove the volume %s: %s" % (eng.name, volume, _last_line(r.stderr)))
        if kept:
            # The settings stay, so a second remove --data tries the same volume again.
            raise LocalRuntimeError("\n".join(kept))
        if delete_settings():
            out("removed %s" % settings_path())
    return 0


def parser():
    p = argparse.ArgumentParser(
        prog=PROG,
        description="Run OpenPLC Runtime v4 and canworks-bridge on this PC, every network simulated, in two "
                    "containers (Docker or Podman; Docker Desktop is not needed). See " + DOCS + ".")
    p.add_argument("--engine", choices=sorted(ENGINES),
                   help="the container engine (default: $%s, else the first that runs of docker, podman and, on "
                        "Windows, the two inside WSL)" % ENGINE_ENV)
    p.add_argument("--version", action="version", version="%(prog)s " + __version__)
    sub = p.add_subparsers(dest="command", metavar="COMMAND")
    sub.required = True

    def ports(sp):
        sp.add_argument("--image", help="the bridge image (default %s)" % default_image())
        sp.add_argument("--runtime-image", help="the runtime image (default %s, the pinned version)" % runtime_image())
        sp.add_argument("--port", type=int, help="the runtime's port on this PC (default %d)" % RUNTIME_PORT)
        sp.add_argument("--diag-port", type=int,
                        help="the bridge's diagnostics port (default %d; set it when the config's diagnostics "
                             "uses another)" % DIAG_PORT)

    ports(sub.add_parser("start", help="start the local runtime (creates it and its user the first time)"))
    sub.add_parser("stop", help="stop the local runtime and its bridge")
    st = sub.add_parser("status", help="show the containers, the runtime's PLC state and the bridge's")
    st.add_argument("--show-password", action="store_true", help="also print the saved password")
    lg = sub.add_parser("logs", help="print the bridge's log")
    lg.add_argument("--runtime", action="store_true", help="the runtime's log instead")
    lg.add_argument("-f", "--follow", action="store_true", help="keep following the log")
    ports(sub.add_parser("update", help="run the images for this version of the tools and the pinned runtime, "
                                        "keeping the data and the bridge's config"))
    rm = sub.add_parser("remove", help="delete both containers")
    rm.add_argument("--data", action="store_true", help="also delete both volumes and the saved credentials")
    return p


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
