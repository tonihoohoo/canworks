"""Updates from inside the configurator (pc-tools-self-update): the check
for a newer release, whether this install can update itself, the guard, and
the hand-off to the updater (canworks/updater.py).

The check reads the tag GitHub's releases/latest address redirects to, as
the one-line installers do: no API and no token. It runs at most once per
CHECK_EVERY_S unless the user asks, in a thread, and its result is kept in
update.json in the settings folder with the version the user dismissed.

Only a uv tool install (uv's uv-receipt.toml in an environment under `uv
tool dir`), with uv found and its base interpreter there, updates itself;
outside that the page shows the one-line install command. The update: the
configurator writes update-run.json (user-readable only) and starts the
updater from a copy in a temporary folder on the base interpreter, detached,
then stops. The updater waits for it to end, installs, writes the result
into the run file and, for Update now, starts the configurator again with
--resume: on the same port with the same session token, so the open tab
reloads into the new version. Every start reads a finished run file, keeps
the result for the page and removes the file.
"""

import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request

from .. import __version__
from ..userdirs import config_dir, replace_file

DEFAULT_REPO = "https://github.com/tonihoohoo/canworks"
REPO_ENV = "CANWORKS_REPO"  # the same override as the install scripts' (tests)
OFF_ENV = "CANWORKS_NO_UPDATE_CHECK"
STATE = "update.json"
RUN = "update-run.json"
LOG = "update.log"
CHECK_EVERY_S = 24 * 3600
TIMEOUT_S = 10.0
RESUME_S = 120.0  # a run file older than this restarts on a new port and token
TAG = re.compile(r"^deploy-v(\d+\.\d+\.\d+)$")


def repo():
    return (os.environ.get(REPO_ENV) or DEFAULT_REPO).rstrip("/")


def version_key(v):
    """(major, minor, patch) of "1.2.3", or None."""
    m = re.match(r"^(\d+)\.(\d+)\.(\d+)$", v or "")
    return tuple(int(x) for x in m.groups()) if m else None


def is_newer(latest, running=__version__):
    a, b = version_key(latest), version_key(running)
    return bool(a and b and a > b)


def release_page(version):
    return "%s/releases/tag/deploy-v%s" % (repo(), version)


def wheel_url(version):
    return "%s/releases/download/deploy-v%s/canworks-%s-py3-none-any.whl" % (repo(), version, version)


def install_command(platform=None):
    """The one-line install command of the README for this system."""
    if (platform or sys.platform) == "win32":
        return ('$f = "$env:TEMP\\install-pc.ps1"; irm %s/releases/latest/download/install-pc.ps1 -OutFile $f; '
                'powershell -NoProfile -ExecutionPolicy RemoteSigned -File $f' % repo())
    return "curl -LsSf %s/releases/latest/download/install-pc.sh | sh" % repo()


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def latest_version(timeout=TIMEOUT_S):
    """The newest release's version from the releases/latest redirect.
    Follows the system's proxy settings (urllib). Raises OSError or
    ValueError."""
    opener = urllib.request.build_opener(_NoRedirect)
    req = urllib.request.Request(repo() + "/releases/latest", method="GET",
                                 headers={"User-Agent": "canworks-config/" + __version__})
    try:
        with opener.open(req, timeout=timeout) as r:
            raise ValueError("no redirect from %s (HTTP %d)" % (req.full_url, r.status))
    except urllib.error.HTTPError as e:
        location = e.headers.get("Location") if e.code in (301, 302, 303, 307, 308) else None
        if not location:
            raise ValueError("HTTP %d from %s" % (e.code, req.full_url))
    m = TAG.match(location.rstrip("/").rsplit("/", 1)[-1])
    if not m:
        raise ValueError("the newest release is not a PC tools release: %s" % location)
    return m.group(1)


# -- where this install came from ---------------------------------------------

def find_uv(env=None):
    """uv as the installers find it: PATH, then where its installer puts it."""
    env = os.environ if env is None else env
    found = shutil.which("uv", path=env.get("PATH"))
    if found:
        return os.path.abspath(found)
    home = os.path.expanduser("~")
    exe = "uv.exe" if os.name == "nt" else "uv"
    for d in (env.get("XDG_BIN_HOME"), os.path.join(home, ".local", "bin"), os.path.join(home, ".cargo", "bin")):
        if d and os.path.isfile(os.path.join(d, exe)):
            return os.path.join(d, exe)
    return None


def base_python(platform=None):
    """The interpreter behind the tools' environment (pythonw on Windows), or None."""
    base = getattr(sys, "_base_executable", None) or sys.executable
    if (platform or sys.platform) == "win32":
        w = os.path.join(os.path.dirname(base), "pythonw.exe")
        if os.path.isfile(w):
            return w
    return base if base and os.path.isfile(base) else None


def _same(a, b):
    return os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(b))


def _uv_dir(uv, *args):
    kw = {"creationflags": 0x08000000} if os.name == "nt" else {}  # CREATE_NO_WINDOW
    r = subprocess.run([uv, "tool", "dir"] + list(args), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                       stderr=subprocess.DEVNULL, universal_newlines=True, timeout=20, **kw)
    out = (r.stdout or "").strip()
    return out if r.returncode == 0 and out else None


def receipt_python(prefix):
    """The Python the tools were installed for (the receipt's request), else this one's major.minor."""
    try:
        import tomllib
        with open(os.path.join(prefix, "uv-receipt.toml"), "rb") as f:
            python = (tomllib.load(f).get("tool") or {}).get("python")
        if isinstance(python, str) and python:
            return python
    except (OSError, ValueError, ImportError):
        pass
    return "%d.%d" % sys.version_info[:2]


def install_info(prefix=None, platform=None, env=None, uv_dir=_uv_dir):
    """How this install can update: {"kind": "uv-tool" | "sandboxed" |
    "other", "why", and for uv-tool: "uv", "python", "base", "env", "bin"}."""
    prefix = os.path.abspath(prefix or sys.prefix)
    platform = platform or sys.platform
    env = os.environ if env is None else env
    if platform == "win32" and env.get("LOCALAPPDATA"):
        packages = os.path.join(env["LOCALAPPDATA"], "Packages") + os.sep
        if os.path.normcase(prefix).startswith(os.path.normcase(packages)):
            return {"kind": "sandboxed",
                    "why": "these tools were installed inside another app's private folder (%s)" % prefix}
    if not os.path.isfile(os.path.join(prefix, "uv-receipt.toml")):
        return {"kind": "other", "why": "these tools were not installed with the one-line installer (uv tool)"}
    uv = find_uv(env)
    if not uv:
        return {"kind": "other", "why": "uv, which installed these tools, was not found"}
    base = base_python(platform)
    if not base:
        return {"kind": "other", "why": "the Python these tools run on was not found"}
    try:
        tools, bin_dir = uv_dir(uv), uv_dir(uv, "--bin")
    except (OSError, subprocess.SubprocessError):
        tools = bin_dir = None
    if not tools or not bin_dir or not _same(os.path.dirname(prefix), tools):
        return {"kind": "other", "why": "these tools are not in uv's tools folder"}
    return {"kind": "uv-tool", "why": None, "uv": uv, "python": receipt_python(prefix), "base": base,
            "env": prefix, "bin": bin_dir}


# -- the check, and its state in update.json ------------------------------------

def _read_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_json(path, data, private=False):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    if private:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        f = os.fdopen(fd, "w", encoding="utf-8")
    else:
        f = open(tmp, "w", encoding="utf-8")
    with f:
        json.dump(data, f, indent=2)
    replace_file(tmp, path)


def check_off(ui_on=True, env=None):
    """Why the automatic check is off, or None."""
    env = os.environ if env is None else env
    if env.get(OFF_ENV, "").strip() not in ("", "0"):
        return "env"
    return None if ui_on else "setting"


class Updates:
    """The configurator's update state: the check, the user's choices, the
    last update's result and an update chosen for when it stops."""

    def __init__(self, folder=None, fetch=latest_version, info=install_info, clock=time.time):
        self.folder = folder or config_dir()
        self.fetch, self.info_fn, self.clock = fetch, info, clock
        self.lock = threading.Lock()
        self.checking = False
        self.error = None
        self.result = None  # the last update's result, from its run file
        self.on_quit = None  # a version to install when the configurator stops
        self.boot = secrets.token_hex(8)  # a new value at every start: the updating page waits for it
        self._info = None

    @property
    def state_path(self):
        return os.path.join(self.folder, STATE)

    @property
    def run_path(self):
        return os.path.join(self.folder, RUN)

    def state(self):
        return _read_json(self.state_path)

    def install(self):
        with self.lock:
            if self._info is None:
                self._info = self.info_fn()
            return self._info

    def due(self, now=None):
        checked = self.state().get("checked_at")
        now = self.clock() if now is None else now
        return not isinstance(checked, (int, float)) or not 0 <= now - checked < CHECK_EVERY_S

    def check(self):
        """One check now (in the caller's thread); the newest version, or None."""
        with self.lock:
            if self.checking:
                return None
            self.checking = True
        try:
            latest = self.fetch()
        except (OSError, ValueError) as e:
            with self.lock:
                self.error = str(getattr(e, "reason", None) or e)
            print("canworks-config: update check failed: %s" % self.error, flush=True)
            st = self.state()
            st["checked_at"] = self.clock()  # tried: not again for a day, unless asked
            _write_json(self.state_path, st)
            return None
        finally:
            with self.lock:
                self.checking = False
        with self.lock:
            self.error = None
        st = self.state()
        st.update(checked_at=self.clock(), latest=latest)
        _write_json(self.state_path, st)
        return latest

    def check_in_background(self, force=False, ui_on=True):
        if not force and (check_off(ui_on) or not self.due()):
            return False
        threading.Thread(target=self.check, daemon=True, name="update-check").start()
        return True

    def dismiss(self, version):
        if version_key(version) is None:
            raise ValueError("version must look like 1.2.3")
        st = self.state()
        st["dismissed"] = version
        _write_json(self.state_path, st)

    def view(self, ui_on=True):
        """What the page shows."""
        st = self.state()
        latest = st.get("latest") if version_key(st.get("latest")) else None
        info = self.install()
        newer = is_newer(latest)
        return {"version": __version__, "latest": latest, "newer": newer,
                "dismissed": newer and st.get("dismissed") == latest,
                "checked_at": st.get("checked_at") if isinstance(st.get("checked_at"), (int, float)) else None,
                "checking": self.checking, "error": self.error, "off": check_off(ui_on),
                "kind": info["kind"], "why": info.get("why"), "command": install_command(),
                "release_url": release_page(latest) if newer else None, "result": self.result,
                "on_quit": self.on_quit, "boot": self.boot, "log": os.path.join(self.folder, LOG)}

    # -- the hand-off ----------------------------------------------------------
    def take_result(self, resume_path=None):
        """At start: a finished run file's result (and, for --resume, its
        port and token when they are fresh). Removes a finished file."""
        path = resume_path or self.run_path
        data = _read_json(path)
        if not data or not isinstance(data.get("result"), dict):
            return None
        self.result = dict(data["result"], to=data.get("to"), **{"from": data.get("from")})
        try:
            os.remove(path)
        except OSError:
            pass
        fresh = isinstance(data["result"].get("at"), (int, float)) and 0 <= self.clock() - data["result"]["at"] < RESUME_S
        if resume_path and fresh and isinstance(data.get("port"), int) and isinstance(data.get("token"), str):
            return {"port": data["port"], "token": data["token"]}
        return None

    def run_file(self, target, pid, port, token, restart, info=None):
        """The run file's fields for the updater (canworks/updater.py)."""
        info = info or self.install()
        if info["kind"] != "uv-tool":
            raise ValueError(info.get("why") or "this install cannot update itself")
        if version_key(target) is None:
            raise ValueError("no newer version to install")
        win = sys.platform == "win32"
        exe = (lambda name: os.path.join(info["bin"], name + (".exe" if win else "")))
        if win:
            restart_cmd = [os.path.join(info["env"], "Scripts", "pythonw.exe"), "-m", "canworks.configurator.start",
                           "--from-shortcut"]
            shortcut_cmd, shortcut_paths = None, []
        else:
            from . import shortcut
            restart_cmd = [exe("canworks-config"), "--from-shortcut"]
            shortcut_cmd = [exe("canworks-config"), "--create-shortcut"]
            shortcut_paths = [shortcut.macos_app(os.environ)] if sys.platform == "darwin" \
                else [shortcut.linux_paths(os.environ)[0]]
        return {"from": __version__, "to": target, "wheel": wheel_url(target), "old_wheel": wheel_url(__version__),
                "uv": info["uv"], "python": info["python"], "env": info["env"], "bin": info["bin"],
                "pid": pid, "port": port, "token": token, "restart": bool(restart),
                "restart_cmd": restart_cmd, "check_cmd": [exe("canworks-deploy"), "--version"],
                "shortcut_cmd": shortcut_cmd, "shortcut_paths": shortcut_paths,
                "install_command": install_command(), "log": os.path.join(self.folder, LOG), "result": None,
                "started_at": self.clock()}

    def start_updater(self, data, wait=False, out=None):
        """Writes the run file and starts the updater on the base
        interpreter from a copy of updater.py in a new temporary folder:
        detached (the configurator stops next), or, with wait, in this
        terminal (canworks-config --update on macOS and Linux)."""
        if os.path.exists(self.run_path) and not _read_json(self.run_path).get("result"):
            started = _read_json(self.run_path).get("started_at")
            if isinstance(started, (int, float)) and 0 <= self.clock() - started < 600:
                raise ValueError("an update is running already (%s)" % os.path.join(self.folder, LOG))
        _write_json(self.run_path, data, private=True)
        here = tempfile.mkdtemp(prefix="canworks-updater-")
        script = os.path.join(here, "updater.py")
        shutil.copyfile(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "updater.py"),
                        script)
        base = self.install()["base"]
        if wait:
            cmd = [base, "-I", "-S", script, self.run_path, "--print"]
            return subprocess.run(cmd, stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT).returncode
        cmd = [base, "-I", "-S", script, self.run_path]
        kw = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL,
              "close_fds": True}
        if os.name == "nt":
            flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
            try:
                subprocess.Popen(cmd, creationflags=flags | subprocess.CREATE_BREAKAWAY_FROM_JOB, **kw)
            except OSError:
                subprocess.Popen(cmd, creationflags=flags, **kw)
        else:
            subprocess.Popen(cmd, start_new_session=True, **kw)
        print("canworks-config: updating to %s (log: %s)" % (data["to"], data["log"]), flush=True)
        return None


def guard(server):
    """Why the configurator cannot stop for an update now: a list of
    sentences, empty when it can."""
    why = []
    now = time.monotonic()
    with server.page_lock:
        if any(p["unsaved"] for p in server._live(now)):
            why.append("there are unsaved changes")
    if server.connection.connected:
        why.append("an online connection is open (runtime or USB adapter)")
    if server.sim_connection.connected:
        why.append("the simulator runs")
    if server.sender.jobs:
        why.append("frames are being sent")
    with server.traces.lock:
        spaces = list(server.traces.spaces.values())
    if any(getattr(ws, "recorder", None) is not None for ws in spaces):
        why.append("a trace records")
    with server.jobs.lock:
        if any(j.state == "running" for j in server.jobs.jobs.values()):
            why.append("a job runs on the bus")
    if server.devices.running:
        why.append("a device install job runs")
    return why


def cli(yes=False, out=None, ask=input):
    """canworks-config --update: 0 when the newest version is installed at
    the end (or, on Windows and with a running configurator, the update has
    started), else non-zero."""
    from . import launch
    out = out or sys.stdout
    try:
        latest = latest_version()
    except (OSError, ValueError) as e:
        print("canworks-config: could not find the newest release: %s" % (getattr(e, "reason", None) or e),
              file=sys.stderr)
        return 2
    print("Installed: %s. Newest release: %s." % (__version__, latest), file=out, flush=True)  # before the updater's lines
    if not is_newer(latest):
        print("The newest version is installed.", file=out)
        return 0
    u = Updates()
    info = u.install()
    if info["kind"] != "uv-tool":
        print("This copy cannot update itself: %s. Run the install command instead:\n  %s"
              % (info["why"], install_command()), file=out)
        return 2
    if not yes:
        if not sys.stdin.isatty():
            print("canworks-config: add --yes to update without asking", file=sys.stderr)
            return 2
        if ask("Update to %s now? [y/N] " % latest).strip().lower() not in ("y", "yes"):
            return 1
    inst = launch.running()
    if inst is not None:
        r = launch.ask(inst, "/api/instance/update", {"go": True, "version": latest}, timeout=30)
        if r is None:
            print("canworks-config: the running configurator did not answer", file=sys.stderr)
            return 2
        status, data = r
        if status != 200:
            print("canworks-config: %s" % (data.get("error") or "the configurator refused (%d)" % status),
                  file=sys.stderr)
            return 2
        print("The running configurator updates to %s and starts again; its open tab comes back by itself "
              "(log: %s)." % (latest, os.path.join(u.folder, LOG)), file=out)
        return 0
    data = u.run_file(latest, None, None, None, restart=False, info=info)
    if os.name == "nt":
        # This command's own files are in use while it runs: the updater waits for it to end.
        data["pid"] = os.getpid()
        u.start_updater(data)
        print("The update runs in the background now and takes about a minute; %s shows its progress. "
              "Run canworks-config --update again to check." % data["log"], file=out)
        return 0
    code = u.start_updater(data, wait=True, out=out)
    u.take_result()
    return code
