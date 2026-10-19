"""How canworks-config starts (configurator-quit-and-background): one
configurator per user, found through instance.json in the settings folder;
the start in the background with its output in a log file; and the start
address shown when no browser opened the page.

instance.json holds the running configurator's pid, port and a random secret,
readable only by the user. A second start asks that configurator for a new
start address (POST /api/instance/start with the secret in a header), opens
it and exits; a file whose configurator does not run or answer is ignored.
"""

import http.client
import json
import os
import subprocess
import sys
import threading
import time
import webbrowser

from ..userdirs import config_dir

INSTANCE = "instance.json"
LOG = "configurator.log"
LOG_MAX = 1024 * 1024  # bytes per log file; one older file (configurator.log.1) is kept
HEADER = "X-Canworks-Instance"
CHILD = "--child-background"
ASK_S = 2.0  # a configurator that does not answer in this time counts as gone
START_S = 10.0  # how long a background start waits for its configurator
NO_PAGE_S = 15.0  # after asking the browser: no page by then, the address is shown
TAKEN_OVER = 3  # the background configurator's exit code when another one started at the same moment
START_ENV = "CANWORKS_CONFIG_START"  # the starter's id for its background configurator: in its instance file
TITLE = "canworks configurator"
NO_BROWSER = "No browser opened. Open this address in a browser: %s"


def instance_path(name=INSTANCE):
    return os.path.join(config_dir(), name)


def log_path():
    return os.path.join(config_dir(), LOG)


def write_instance(path, port, secret):
    """Writes the instance file, readable only by this user; raises
    FileExistsError when another configurator has one (O_EXCL)."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump({"pid": os.getpid(), "port": port, "secret": secret, "start": os.environ.get(START_ENV)}, f)


def own_instance_name(new_instance):
    """The instance file a configurator writes: instance.json, or with
    --new-instance one only its starter knows (later starts do not find it)."""
    if not new_instance:
        return INSTANCE
    return "instance-%s.json" % (os.environ.get(START_ENV) or os.getpid())


def read_instance(path=None):
    try:
        with open(path or instance_path(), encoding="utf-8") as f:
            doc = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(doc, dict) or not all(isinstance(doc.get(k), t) for k, t in
                                            (("pid", int), ("port", int), ("secret", str))):
        return None
    return doc


def remove_instance(path, secret):
    """Removes the instance file when it is still this configurator's."""
    doc = read_instance(path)
    if doc is not None and doc["secret"] == secret:
        try:
            os.remove(path)
        except OSError:
            pass


def pid_alive(pid):
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        k32 = ctypes.windll.kernel32
        handle = k32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        code = ctypes.c_ulong()
        try:
            return bool(k32.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == 259  # STILL_ACTIVE
        finally:
            k32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def running(path=None):
    """The instance file of a configurator that runs, or None."""
    doc = read_instance(path)
    return doc if doc is not None and pid_alive(doc["pid"]) else None


def ask(inst, route, body, timeout=ASK_S):
    """POST to a running configurator with its secret: (status, answer), or
    None when it does not answer."""
    c = http.client.HTTPConnection("127.0.0.1", inst["port"], timeout=timeout)
    try:
        c.request("POST", route, json.dumps(body), {"Host": "127.0.0.1:%d" % inst["port"], HEADER: inst["secret"],
                                                    "Content-Type": "application/json"})
        r = c.getresponse()
        data = json.loads(r.read().decode("utf-8") or "{}")
        return r.status, data if isinstance(data, dict) else {}
    except (OSError, ValueError, http.client.HTTPException):
        return None
    finally:
        c.close()


def foreground(args, env=None, platform=None):
    """Whether canworks-config stays in its terminal: asked for, with
    --no-browser or --keep-running, over SSH, and on Linux without a
    display, where the address it prints is the way in."""
    env = os.environ if env is None else env
    platform = platform or sys.platform
    if args.foreground or args.no_browser or args.keep_running:
        return True
    if env.get("SSH_CONNECTION"):
        return True
    return platform.startswith("linux") and not env.get("DISPLAY") and not env.get("WAYLAND_DISPLAY")


def in_terminal(out):
    try:
        return out is not None and out.isatty()
    except (AttributeError, ValueError):
        return False


# -- the log of a background configurator -------------------------------------

def rotate(path, limit=LOG_MAX):
    """Moves a log of `limit` bytes or more to path.1 (replacing it)."""
    try:
        if os.path.getsize(path) >= limit:
            os.replace(path, path + ".1")
    except OSError:
        pass


class Log:
    """sys.stdout and sys.stderr of a background configurator: the log file,
    moved to configurator.log.1 when it reaches `limit` bytes."""

    def __init__(self, path, limit=LOG_MAX):
        self.path, self.limit = path, limit
        self.lock = threading.Lock()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        rotate(path, limit)
        self.f = open(path, "a", encoding="utf-8", errors="replace")

    def write(self, text):
        with self.lock:
            if self.f.tell() + len(text) > self.limit and self.f.tell():
                self.f.close()
                rotate(self.path, 0)
                self.f = open(self.path, "a", encoding="utf-8", errors="replace")
            self.f.write(text)
            self.f.flush()
        return len(text)

    def flush(self):
        with self.lock:
            self.f.flush()

    def isatty(self):
        return False


def log_to_file(path=None):
    """The background configurator's output goes to the log. The file
    handles it got from its parent are let go, so the log can be moved on
    Windows. (In this order: without a console the log could get fd 1.)"""
    try:
        null = os.open(os.devnull, os.O_RDWR)
        for fd in (0, 1, 2):
            if fd != null:
                os.dup2(null, fd)
        if null > 2:
            os.close(null)
    except OSError:
        pass
    log = Log(path or log_path())
    sys.stdout = sys.stderr = log
    return log


def tail(path, start=0, lines=8):
    """The last lines written to the log since offset `start`."""
    try:
        with open(path, "rb") as f:
            f.seek(start)
            text = f.read().decode("utf-8", "replace")
    except OSError:
        return ""
    return "\n".join(text.strip().splitlines()[-lines:])


# -- starting in the background ----------------------------------------------

def child_command(argv, executable=None):
    """The command of the background configurator: this one's arguments
    and --child-background; on Windows with pythonw, which has no console."""
    exe = executable or sys.executable
    if os.name == "nt":
        w = os.path.join(os.path.dirname(exe), "pythonw.exe")
        if os.path.isfile(w):
            exe = w
    return [exe, "-m", "canworks.configurator.server"] + [a for a in argv if a != CHILD] + [CHILD]


def spawn(argv, log, start_id=None):
    """Starts the background configurator, detached from this terminal (a
    new session; on Windows no console), its output appended to `log`.
    `start_id` comes back in its instance file: on Windows the process
    started is a venv launcher whose pid is not the configurator's."""
    os.makedirs(os.path.dirname(log), exist_ok=True)
    rotate(log)
    kw = {"stdin": subprocess.DEVNULL, "stderr": subprocess.STDOUT, "close_fds": True,
          "env": dict(os.environ, **({START_ENV: start_id} if start_id else {}))}
    if os.name == "nt":
        kw["creationflags"] = (subprocess.DETACHED_PROCESS | subprocess.CREATE_NO_WINDOW
                               | subprocess.CREATE_NEW_PROCESS_GROUP)
    else:
        kw["start_new_session"] = True
    with open(log, "ab") as f:
        return subprocess.Popen(child_command(argv), stdout=f, **kw)


def background(argv, new_instance=False, out=None, wait_s=START_S, no_page_s=None):
    """canworks-config without --foreground: starts the configurator in the
    background, opens its page and returns 0; a configurator that could
    not start: its reason from the log, and 2."""
    out = out or sys.stdout
    log = log_path()
    try:
        start = os.path.getsize(log)
        if start >= LOG_MAX:
            start = 0  # spawn() moves it to configurator.log.1
    except OSError:
        start = 0
    start_id = os.urandom(8).hex()
    try:
        child = spawn(argv, log, start_id)
    except OSError as e:
        print("canworks-config: cannot start the configurator in the background: %s" % (e.strerror or e),
              file=sys.stderr)
        return 2
    path = instance_path("instance-%s.json" % start_id if new_instance else INSTANCE)
    deadline = time.monotonic() + wait_s
    while True:
        code = child.poll()
        if code == TAKEN_OVER:
            # Another canworks-config started at the same moment and won: its page.
            inst = running()
            done = hand_over(inst, None, out=out, no_page_s=no_page_s) if inst else None
            if done is not None:
                return done
        if code is not None:
            why = tail(log, start)
            print("canworks-config: the configurator did not start%s" % (":\n" + why if why else " (see %s)" % log),
                  file=sys.stderr)
            return code or 2
        inst = read_instance(path)
        if inst is not None and inst.get("start") == start_id:
            done = hand_over(inst, None, out=out, no_page_s=no_page_s)
            if done is not None:
                if done == 0:
                    print("The configurator runs in the background and stops when its last browser tab is closed "
                          "(log: %s)." % log, file=out, flush=True)
                return done
        if time.monotonic() > deadline:
            print("canworks-config: the configurator did not start within %d s (see %s)" % (wait_s, log),
                  file=sys.stderr)
            return 2
        time.sleep(0.1)


def hand_over(inst, path, browser=True, out=None, no_page_s=None):
    """Opens a page of the running configurator `inst` (with PATH: asks it
    to open that folder): 0, or 2 when it refused PATH; None when it did not
    answer (the instance file is stale)."""
    out = out or sys.stdout
    body = {"browser": browser}
    if path:
        body["path"] = os.path.abspath(path)
    r = ask(inst, "/api/instance/start", body)
    if r is None or r[0] == 403:
        return None
    status, data = r
    if status != 200 or not isinstance(data.get("url"), str):
        print("canworks-config: %s" % (data.get("error") or "the running configurator refused (%d)" % status),
              file=sys.stderr)
        return 2
    url = data["url"]
    if not browser:
        print("canworks configurator: %s" % url, file=out, flush=True)
        return 0
    webbrowser.open(url)
    if not wait_for_page(inst, url, NO_PAGE_S if no_page_s is None else no_page_s):
        print(NO_BROWSER % url, file=out, flush=True)
        if not in_terminal(out):
            message_window(url)
    return 0


def wait_for_page(inst, url, timeout):
    """Whether the browser opened `url` (its one-time code was used) within
    `timeout` seconds."""
    code = url.rsplit("code=", 1)[-1]
    deadline = time.monotonic() + timeout
    while True:
        r = ask(inst, "/api/instance/page", {"code": code})
        if r is None or (r[0] == 200 and r[1].get("opened")):
            return True  # opened, or the configurator has stopped: nothing to show
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.25)


# -- the address, when no browser opened and there is no terminal ------------

def _which(name):
    import shutil
    return shutil.which(name)


def message_window(url, run=None, platform=None):
    """Shows the start address in a window the user can copy it from:
    a Windows message box (Ctrl+C copies its text), a macOS dialog with the
    address in a field, zenity or kdialog on Linux, else a notification.
    Returns how it was shown, or None."""
    run = run or (lambda cmd: subprocess.run(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                             stderr=subprocess.DEVNULL, timeout=3600))
    platform = platform or sys.platform
    text = "canworks configurator runs, but no browser opened. Open this address in a browser:"
    try:
        if platform == "win32":
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, "%s\n\n%s\n\nCtrl+C copies this message." % (text, url), TITLE,
                                             0x40 | 0x10000)  # MB_ICONINFORMATION | MB_SETFOREGROUND
            return "messagebox"
        if platform == "darwin":
            run(["osascript", "-e", 'display dialog "%s" default answer "%s" with title "%s" buttons {"OK"} '
                 'default button "OK"' % (text, url, TITLE)])
            return "osascript"
        if _which("zenity"):
            run(["zenity", "--entry", "--title", TITLE, "--text", text, "--entry-text", url])
            return "zenity"
        if _which("kdialog"):
            run(["kdialog", "--title", TITLE, "--inputbox", text, url])
            return "kdialog"
        if _which("notify-send"):
            run(["notify-send", TITLE, "%s %s" % (text, url)])
            return "notify-send"
    except (OSError, subprocess.SubprocessError, AttributeError):
        pass
    return None
