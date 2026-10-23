"""The PC tools' updater (pc-tools-self-update): installs a newer release in
place of the running one, after the configurator that started it has ended.

It runs outside the tools' environment, the one it replaces: the
configurator copies this file to a new temporary folder and starts it on the
base interpreter behind that environment (uv's own Python, which a tools
reinstall does not touch) with -I -S, so nothing of the tools is imported.
Standard library only, for the same reason.

Its one argument is the run file (update-run.json in the settings folder)
the configurator wrote; see configurator/update.py for its fields. The steps:
wait for the configurator to end; on Windows, check that no other process
runs a program file of the tools; read the installed version (when it is the
target or newer already, install nothing and start the configurator again);
download the new release's wheel and locked dependency versions; move the
tools' environment aside as the backup; install the downloaded wheel with
uv, with the one-line installers' arguments; on a failure put the backup
back, so no older release is needed; refresh the app shortcut (macOS and
Linux); write the result into the run file; start the configurator again
when asked to. Progress goes to update.log next to configurator.log, and to
the terminal for canworks-config --update.

It never downloads or runs an install script, and starts no shell.
"""

import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

# The arguments and the override the one-line installers use
# (scripts/install-pc.sh, install-pc.ps1): a test keeps the three the same.
UV_INSTALL = ["tool", "install", "--force", "--compile-bytecode"]
OVERRIDE = "pytest; sys_platform == 'never'"
SPEC = "canworks @ %s"
# A release's locked dependency versions (lock-dependency-versions), passed
# as --constraints; a release from before them has none (404).
CONSTRAINTS = "--constraints"

BACKUP = ".canworks-update-backup"  # the environment before the update, next to it in uv's tools folder
RENAME_WAIT_S = 5.0  # Windows: a virus scanner may hold a file of the environment for a moment
WAIT_PID_S = 30.0  # the configurator stops in about a second; then the update is given up
LOCK_WAIT_S = 10.0  # Windows: how long other processes get to let go of the tools' files
LOG_MAX = 1024 * 1024
WINDOWS = os.name == "nt"
NO_WINDOW = 0x08000000  # CREATE_NO_WINDOW: uv and the tools are console programs


class Run:
    def __init__(self, path, out=None):
        self.path = path
        with open(path, encoding="utf-8") as f:
            self.data = json.load(f)
        self.out = out
        self.log = None
        log = self.data.get("log")
        if log:
            try:
                os.makedirs(os.path.dirname(log), exist_ok=True)
                if os.path.getsize(log) >= LOG_MAX:
                    os.replace(log, log + ".1")
            except OSError:
                pass
            try:
                self.log = open(log, "a", encoding="utf-8")
            except OSError:
                self.log = None

    def say(self, text):
        line = "%s %s" % (time.strftime("%Y-%m-%d %H:%M:%S"), text)
        if self.log:
            self.log.write(line + "\n")
            self.log.flush()
        if self.out:
            print(text, file=self.out, flush=True)

    def finish(self, state, message, version):
        """Writes the result into the run file (the configurator shows it)."""
        self.data["result"] = {"state": state, "message": message, "version": version, "at": time.time()}
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=2)
        for _ in range(20):
            try:
                os.replace(tmp, self.path)
                break
            except PermissionError:
                time.sleep(0.05)
        self.say("result: %s: %s" % (state, message))


def pid_alive(pid):
    if WINDOWS:
        import ctypes
        k32 = ctypes.WinDLL("kernel32")
        k32.OpenProcess.restype = ctypes.c_void_p
        handle = k32.OpenProcess(0x00100000, False, int(pid))  # SYNCHRONIZE
        if not handle:
            return False
        try:
            return k32.WaitForSingleObject(ctypes.c_void_p(handle), 0) == 0x102  # WAIT_TIMEOUT: still running
        finally:
            k32.CloseHandle(ctypes.c_void_p(handle))
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    try:
        with open("/proc/%d/stat" % int(pid)) as f:
            return f.read().rsplit(")", 1)[1].split()[0] != "Z"  # ended, its parent has not asked yet
    except (OSError, IndexError):
        return True


def wait_pid(pid, wait_s=None):
    deadline = time.monotonic() + (WAIT_PID_S if wait_s is None else wait_s)
    while pid_alive(pid):
        if time.monotonic() > deadline:
            return False
        time.sleep(0.1)
    return True


PROGRAM_FILES = (".exe", ".dll", ".pyd")


def file_in_use(env):
    """Windows: the first program file (.exe, .dll, .pyd) in the tools'
    environment that a running process has loaded, or None. Windows lets
    such a file (and its folder) be renamed while it runs, but not opened
    for writing or removed, which is what uv does to it."""
    for root, _dirs, files in os.walk(env):
        for name in files:
            if not name.lower().endswith(PROGRAM_FILES):
                continue
            path = os.path.join(root, name)
            try:
                with open(path, "r+b"):
                    pass
            except FileNotFoundError:
                continue
            except OSError:
                return path
    return None


def files_free(env, wait_s=LOCK_WAIT_S, run=None):
    """Windows: whether no process runs a program file of the tools'
    environment; tried again for wait_s (the venv launcher ends just after
    the interpreter it started)."""
    deadline = time.monotonic() + wait_s
    while True:
        held = file_in_use(env)
        if held is None:
            return True
        if time.monotonic() > deadline:
            if run:
                run.say("in use: %s" % held)
            return False
        time.sleep(0.5)


def run_quiet(cmd, timeout=60):
    kw = {"creationflags": NO_WINDOW} if WINDOWS else {}
    return subprocess.run(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          universal_newlines=True, timeout=timeout, **kw)


def installed_version(run):
    """The version the installed canworks-deploy says, or None."""
    try:
        r = run_quiet(run.data["check_cmd"])
    except (OSError, subprocess.SubprocessError):
        return None
    words = (r.stdout or "").split()
    return words[-1] if r.returncode == 0 and words else None


class DownloadError(Exception):
    pass


def fetch_constraints(run, url, path):
    """The release's constraints file at `url` into `path`: the path, or None
    when the release has none (404). Any other failure raises DownloadError."""
    if not url:
        return None
    try:
        with urllib.request.urlopen(url, timeout=60) as r, open(path, "wb") as f:
            f.write(r.read())
        return path
    except urllib.error.HTTPError as e:
        if e.code == 404:
            run.say("%s: none (this release does not lock its dependency versions)" % url)
            return None
        raise DownloadError("%s: HTTP %d" % (url, e.code))
    except (OSError, ValueError) as e:
        raise DownloadError("%s: %s" % (url, e))


def version_key(v):
    """(major, minor, patch) of "1.2.3", or None."""
    parts = (v or "").split(".")
    if len(parts) != 3 or not all(p.isdigit() for p in parts):
        return None
    return tuple(int(p) for p in parts)


def at_least(installed, target):
    a, b = version_key(installed), version_key(target)
    return bool(a and b and a >= b)


def download(url, folder):
    """The file at `url` into `folder` under its own name: the path. Raises
    DownloadError, naming the HTTP status when there is one."""
    path = os.path.join(folder, url.rstrip("/").rsplit("/", 1)[-1])
    try:
        with urllib.request.urlopen(url, timeout=120) as r, open(path, "wb") as f:
            shutil.copyfileobj(r, f)
        return path
    except urllib.error.HTTPError as e:
        raise DownloadError("HTTP %d" % e.code)
    except (OSError, ValueError) as e:
        raise DownloadError(str(getattr(e, "reason", None) or e))


def _rename(src, dst, wait_s=RENAME_WAIT_S):
    deadline = time.monotonic() + wait_s
    while True:
        try:
            os.rename(src, dst)
            return True
        except OSError:
            if time.monotonic() > deadline:
                return False
            time.sleep(0.25)


def _remove(path):
    shutil.rmtree(path, ignore_errors=True)
    if os.path.exists(path):  # Windows: a file let go a moment late
        time.sleep(1.0)
        shutil.rmtree(path, ignore_errors=True)
    return not os.path.exists(path)


def backup_path(env):
    return os.path.join(os.path.dirname(os.path.abspath(env)), BACKUP)


def leftover_backup(run, env):
    """A backup an earlier update left (it stopped halfway): put back when
    the environment is missing, else removed."""
    backup = backup_path(env)
    if not os.path.isdir(backup):
        return
    if os.path.isdir(env):
        run.say("removing the backup an earlier update left: %s" % backup)
        _remove(backup)
    elif _rename(backup, env):
        run.say("put back the environment an earlier update left as its backup")


def move_aside(run, env):
    """The environment moved to the backup folder: its path, or None when it
    could not be moved (the install then runs in place, without a backup)."""
    backup = backup_path(env)
    if not os.path.isdir(env):
        return None
    if _rename(env, backup):
        run.say("backup: %s" % backup)
        return backup
    run.say("could not move %s aside; installing in place, without a backup" % env)
    return None


def restore(run, env, backup):
    """The backup back in place of what uv left: whether it worked."""
    if os.path.exists(env) and not _remove(env):
        run.say("could not remove what the failed install left in %s" % env)
        return False
    if _rename(backup, env):
        run.say("put the backup back")
        return True
    run.say("could not put the backup back: %s is still there" % backup)
    return False


def uv_install(run, wheel, overrides, constraints=None):
    cmd = [run.data["uv"]] + UV_INSTALL + ["--python", run.data["python"], "--overrides", overrides]
    if constraints:
        cmd += [CONSTRAINTS, constraints]
    cmd.append(SPEC % wheel)
    run.say("running: %s" % " ".join(cmd))
    kw = {"creationflags": NO_WINDOW} if WINDOWS else {}
    # The user's environment: proxy settings and UV_SYSTEM_CERTS apply.
    p = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         universal_newlines=True, **kw)
    tail = []
    with p.stdout:
        lines = list(_lines(p.stdout, run))
    for text in lines:
        tail = (tail + [text])[-4:]
    p.wait()
    return p.returncode, tail


def _lines(stream, run):
    """uv's output lines, logged; yields the meaningful text of each (no
    box drawing, no warnings)."""
    for line in stream:
        line = line.rstrip()
        run.say("  uv: " + line)
        text = line.strip().lstrip("×│├╰─▶ ").strip()
        if text and not text.startswith("warning:"):
            yield text


def start_detached(cmd):
    kw = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL, "close_fds": True}
    if WINDOWS:
        flags = 0x00000008 | NO_WINDOW | 0x00000200  # DETACHED_PROCESS, CREATE_NEW_PROCESS_GROUP
        try:
            return subprocess.Popen(cmd, creationflags=flags | 0x01000000, **kw)  # CREATE_BREAKAWAY_FROM_JOB
        except OSError:
            return subprocess.Popen(cmd, creationflags=flags, **kw)
    return subprocess.Popen(cmd, start_new_session=True, **kw)


def message_window(text, title="canworks configurator"):
    """The last resort: a system message the user sees without a page."""
    try:
        if WINDOWS:
            import ctypes
            ctypes.WinDLL("user32").MessageBoxW(None, text, title, 0x30 | 0x10000)  # MB_ICONWARNING | MB_SETFOREGROUND
        elif sys.platform == "darwin":
            subprocess.run(["osascript", "-e", "on run argv", "-e",
                            "display dialog (item 1 of argv) with title (item 2 of argv) buttons {\"OK\"}",
                            "-e", "end run", text, title], timeout=3600)
        else:
            for cmd in (["zenity", "--warning", "--title", title, "--text", text],
                        ["kdialog", "--title", title, "--sorry", text], ["notify-send", title, text]):
                try:
                    subprocess.run(cmd, timeout=3600)
                    return
                except OSError:
                    continue
    except (OSError, subprocess.SubprocessError, AttributeError):
        pass


def update(run):
    """The steps; returns the exit code (0: the target version, or a newer
    one, is installed)."""
    d = run.data
    old, new = d["from"], d["to"]
    run.say("updating canworks %s to %s" % (old, new))
    if d.get("pid") and not wait_pid(d["pid"]):
        run.finish("failed", "The configurator did not stop, so nothing was installed.", old)
        return 1  # it still runs: nothing to start

    if WINDOWS and d.get("pid"):
        time.sleep(1.0)  # the venv launcher (or uv's command shim) ends just after the interpreter
    if WINDOWS and not files_free(d["env"], run=run):
        run.finish("locked", "Another canworks program still runs from this install (canworks-diag, a simulator, "
                   "another configurator window): close it and press Update again. Nothing was changed.", old)
        restart(run)
        return 1

    leftover_backup(run, d["env"])
    now = installed_version(run)
    if now and at_least(now, new):
        # Installed by other means since the configurator started (the one-line installer).
        run.finish("already", "Already on %s." % now, now)
        restart(run)
        return 0
    old = now or old

    work = tempfile.mkdtemp(prefix="canworks-update-")
    overrides = os.path.join(work, "overrides.txt")
    with open(overrides, "w", encoding="ascii") as f:
        f.write(OVERRIDE + "\n")
    try:
        try:
            wheel = download(d["wheel"], work)
            new_c = fetch_constraints(run, d.get("constraints"), os.path.join(work, "constraints.txt"))
        except DownloadError as e:
            run.say("could not download the update: %s" % e)
            run.finish("failed", "The update to %s could not be downloaded (%s). Nothing was changed. If the release "
                       "is brand new, try again in a few minutes." % (new, e), old)
            restart(run)
            return 1
        backup = move_aside(run, d["env"])
        code, tail = uv_install(run, pathlib.Path(wheel).resolve().as_uri(), overrides, new_c)
        now = installed_version(run)
        if code == 0 and now == new:
            if backup:
                _remove(backup)
            refresh_shortcut(run)
            run.finish("ok", "Updated to %s." % new, new)
            restart(run)
            return 0
        why = " ".join(" ".join(tail).split())[-300:] if tail else "uv exited with %d" % code
        if backup:
            run.say("the install failed: putting %s back" % old)
            restore(run, d["env"], backup)
            now = installed_version(run)
        if now:
            hint = " If it needs a newer uv or another Python, run the install command once." if code else ""
            run.finish("failed", "The update to %s failed: %s. Still on %s.%s" % (new, why, now, hint), now)
            restart(run)
            return 1
        msg = ("The canworks PC tools update to %s failed and the tools no longer start. "
               "Run the install command once:\n\n%s" % (new, d.get("install_command") or "see docs/install-pc.md"))
        run.finish("broken", msg, None)
        message_window(msg)
        return 2
    finally:
        shutil.rmtree(work, ignore_errors=True)


def refresh_shortcut(run):
    """macOS and Linux: the app shortcut again (the macOS app names the
    version), only where there is one. The Windows shortcut points at paths
    a reinstall keeps, and writing it needs PowerShell."""
    cmd = run.data.get("shortcut_cmd")
    if not cmd or not any(os.path.exists(p) for p in run.data.get("shortcut_paths") or []):
        return
    try:
        r = run_quiet(cmd)
        run.say("shortcut: %s" % (r.stdout or "").strip())
    except (OSError, subprocess.SubprocessError) as e:
        run.say("could not refresh the shortcut: %s" % e)


def restart(run):
    cmd = run.data.get("restart_cmd")
    if not run.data.get("restart") or not cmd:
        return
    try:
        start_detached(cmd + ["--resume", run.path])
        run.say("started the configurator again")
    except OSError as e:
        run.say("could not start the configurator again: %s" % e)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) not in (1, 2) or (len(argv) == 2 and argv[1] != "--print"):
        print("usage: updater.py RUN_FILE [--print]", file=sys.stderr)
        return 2
    run = Run(argv[0], out=sys.stdout if len(argv) == 2 else None)
    try:
        return update(run)
    except Exception as e:  # the result must say something
        run.say("unexpected error: %r" % (e,))
        try:
            run.finish("failed", "The update stopped with an unexpected error: %s (update.log)." % e, None)
        except OSError:
            pass
        restart(run)
        return 2
    finally:
        if run.log:
            run.log.close()
        here = os.path.dirname(os.path.abspath(__file__))
        if os.path.basename(here).startswith("canworks-updater-"):
            # The copy the configurator made: gone with its folder.
            try:
                os.remove(os.path.abspath(__file__))
                os.rmdir(here)
            except OSError:
                pass


if __name__ == "__main__":
    sys.exit(main())
