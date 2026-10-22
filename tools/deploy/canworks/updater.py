"""The PC tools' updater (pc-tools-self-update): installs a newer release in
place of the running one, after the configurator that started it has ended.

It runs outside the tools' environment, the one it replaces: the
configurator copies this file to a new temporary folder and starts it on the
base interpreter behind that environment (uv's own Python, which a tools
reinstall does not touch) with -I -S, so nothing of the tools is imported.
Standard library only, for the same reason.

Its one argument is the run file (update-run.json in the settings folder)
the configurator wrote; see configurator/update.py for its fields. The steps:
wait for the configurator to end; on Windows, check that nothing else uses
the tools' files; install the new wheel with uv, with the one-line
installers' arguments; on a failure that changed the install, install the
old version again; refresh the app shortcut (macOS and Linux); write the
result into the run file; start the configurator again when asked to.
Progress goes to update.log next to configurator.log, and to the terminal
for canworks-config --update.

It never downloads or runs an install script, and starts no shell.
"""

import json
import os
import subprocess
import sys
import tempfile
import time

# The arguments and the override the one-line installers use
# (scripts/install-pc.sh, install-pc.ps1): a test keeps the three the same.
UV_INSTALL = ["tool", "install", "--force", "--compile-bytecode"]
OVERRIDE = "pytest; sys_platform == 'never'"
SPEC = "canworks @ %s"

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


def files_free(env, wait_s=LOCK_WAIT_S):
    """Windows: whether no process uses a file in the tools' environment.
    Windows refuses to rename a folder while a file in it is open (a
    running program, a loaded module), so the folder is renamed and at once
    renamed back; tried again for wait_s (the venv launcher ends just after
    the interpreter it started)."""
    aside = env + ".update-check"
    deadline = time.monotonic() + wait_s
    while True:
        try:
            os.rename(env, aside)
        except FileNotFoundError:
            return True  # nothing installed there: nothing in use either
        except OSError:
            if time.monotonic() > deadline:
                return False
            time.sleep(0.5)
            continue
        for _ in range(100):
            try:
                os.rename(aside, env)
                return True
            except OSError:
                time.sleep(0.1)
        raise OSError("could not rename %s back to %s" % (aside, env))


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


def uv_install(run, wheel, overrides):
    cmd = [run.data["uv"]] + UV_INSTALL + ["--python", run.data["python"], "--overrides", overrides, SPEC % wheel]
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
    """The steps; returns the exit code (0: the new version is installed)."""
    d = run.data
    old, new = d["from"], d["to"]
    run.say("updating canworks %s to %s" % (old, new))
    if d.get("pid") and not wait_pid(d["pid"]):
        run.finish("failed", "The configurator did not stop, so nothing was installed.", old)
        return 1  # it still runs: nothing to start

    if WINDOWS and d.get("pid"):
        time.sleep(1.0)  # the venv launcher (or uv's command shim) ends just after the interpreter
    if WINDOWS and not files_free(d["env"]):
        run.finish("locked", "Another canworks program still runs from this install (canworks-diag, a simulator, "
                   "another configurator window): close it and press Update again. Nothing was changed.", old)
        restart(run)
        return 1

    work = tempfile.mkdtemp(prefix="canworks-update-")
    overrides = os.path.join(work, "overrides.txt")
    with open(overrides, "w", encoding="ascii") as f:
        f.write(OVERRIDE + "\n")
    try:
        code, tail = uv_install(run, d["wheel"], overrides)
        now = installed_version(run)
        if code == 0 and now == new:
            refresh_shortcut(run)
            run.finish("ok", "Updated to %s." % new, new)
            restart(run)
            return 0
        why = " ".join(" ".join(tail).split())[-300:] if tail else "uv exited with %d" % code
        if now == old:
            hint = " If it needs a newer uv or another Python, run the install command once." if code else ""
            run.finish("failed", "The update to %s failed: %s. Still on %s.%s" % (new, why, old, hint), old)
            restart(run)
            return 1
        run.say("the install changed but is not %s (%s): installing %s again" % (new, now, old))
        code2, _ = uv_install(run, d["old_wheel"], overrides)
        if code2 == 0 and installed_version(run) == old:
            run.finish("rolled-back", "The update to %s failed: %s. %s was installed again." % (new, why, old), old)
            restart(run)
            return 1
        msg = ("The canworks PC tools update to %s failed and the old version could not be installed again. "
               "Run the install command once:\n\n%s" % (new, d.get("install_command") or "see docs/install-pc.md"))
        run.finish("broken", msg, None)
        message_window(msg)
        return 2
    finally:
        try:
            os.remove(overrides)
            os.rmdir(work)
        except OSError:
            pass


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
