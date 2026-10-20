"""canworks-config --create-shortcut / --remove-shortcut
(configurator-quit-and-background): an app shortcut that starts the
configurator with no terminal.

- Windows: "canworks configurator" in the Start menu and on the desktop
  (.lnk files written by PowerShell's WScript.Shell), running pythonw of the
  installed tools, which has no console window, with --from-shortcut: that
  process is the configurator (start.py), no second Python. Nothing of ours to sign.
- macOS: ~/Applications/canworks configurator.app, a script that starts the
  canworks-config launcher in the background and ends, so the app is not
  running and opening it again starts the script again (which hands over to
  the running configurator); made on the Mac, so Gatekeeper lets it run.
- Linux: canworks-configurator.desktop in the user's applications folder.

The shortcut runs what the install put on PATH (the uv tool's launcher or
its environment's pythonw), so an update keeps it working. Each file carries
a mark (the .lnk description, a plist key, X-Canworks=1), and
--remove-shortcut removes only marked files.
"""

import os
import plistlib
import shlex
import shutil
import stat
import subprocess
import sys

from .. import __version__

NAME = "canworks configurator"
MARK = "canworks configurator: CANopen and J1939 networks in the browser (canworks-config --create-shortcut)"
DESKTOP_FILE = "canworks-configurator.desktop"
ICONS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icons")
BUNDLE_ID = "org.canworks.configurator"
APP_EXE = "canworks-configurator"


class Refused(Exception):
    pass


def launcher():
    """The installed canworks-config command, or None."""
    found = shutil.which("canworks-config")
    if found:
        return os.path.abspath(found)
    here = os.path.dirname(sys.executable)
    for name in ("canworks-config", "canworks-config.exe"):
        if os.path.isfile(os.path.join(here, name)):
            return os.path.join(here, name)
    return None


def _need_launcher():
    exe = launcher()
    if not exe:
        raise Refused("canworks-config is not on PATH; install the PC tools first (docs/install-pc.md)")
    return exe


def _remove(path, removed):
    try:
        if os.path.isdir(path) and not os.path.islink(path):
            shutil.rmtree(path)
        else:
            os.remove(path)
    except FileNotFoundError:
        return
    removed.append(path)


# -- Linux ------------------------------------------------------------------

def linux_paths(env):
    data = env.get("XDG_DATA_HOME") or os.path.join(env.get("HOME") or os.path.expanduser("~"), ".local", "share")
    return (os.path.join(data, "applications", DESKTOP_FILE),
            os.path.join(data, "icons", "hicolor", "256x256", "apps", "canworks-configurator.png"))


def desktop_quote(arg):
    """An Exec= argument as the desktop entry spec quotes it."""
    if not any(c in arg for c in ' \t\n"\'\\><~|&;$*?#()`'):
        return arg
    return '"%s"' % "".join("\\" + c if c in '"`$\\' else c for c in arg)


def _ours_desktop(path):
    try:
        with open(path, encoding="utf-8") as f:
            return any(line.strip() == "X-Canworks=1" for line in f)
    except (OSError, UnicodeDecodeError):
        return False


def linux(remove, env, run):
    entry, icon = linux_paths(env)
    if remove:
        removed = []
        if _ours_desktop(entry):
            _remove(entry, removed)
            _remove(icon, removed)
    else:
        exe = _need_launcher()
        if os.path.exists(entry) and not _ours_desktop(entry):
            raise Refused("%s is there already and was not made by canworks-config" % entry)
        os.makedirs(os.path.dirname(entry), exist_ok=True)
        os.makedirs(os.path.dirname(icon), exist_ok=True)
        shutil.copyfile(os.path.join(ICONS, "logo-256.png"), icon)
        with open(entry, "w", encoding="utf-8") as f:
            f.write("[Desktop Entry]\nType=Application\nName=%s\n"
                    "Comment=Configure CANopen and J1939 networks in the browser\n"
                    "Exec=%s --from-shortcut\nIcon=%s\nTerminal=false\nCategories=Development;Engineering;\n"
                    "StartupNotify=false\nX-Canworks=1\n" % (NAME, desktop_quote(exe), icon))
        os.chmod(entry, 0o755)  # some desktops start only an executable entry
        removed = [entry]
    if shutil.which("update-desktop-database"):
        run(["update-desktop-database", os.path.dirname(entry)])
    return removed


# -- macOS ------------------------------------------------------------------

def macos_app(env):
    return os.path.join(env.get("HOME") or os.path.expanduser("~"), "Applications", NAME + ".app")


def _ours_app(app):
    try:
        with open(os.path.join(app, "Contents", "Info.plist"), "rb") as f:
            return plistlib.load(f).get("CanworksShortcut") is True
    except (OSError, ValueError, plistlib.InvalidFileException):
        return False


def macos(remove, env, run):
    app = macos_app(env)
    removed = []
    if remove:
        if _ours_app(app):
            _remove(app, removed)
        return removed
    exe = _need_launcher()
    if os.path.exists(app):
        if not _ours_app(app):
            raise Refused("%s is there already and was not made by canworks-config" % app)
        shutil.rmtree(app)
    contents = os.path.join(app, "Contents")
    for d in ("MacOS", "Resources"):
        os.makedirs(os.path.join(contents, d))
    with open(os.path.join(contents, "Info.plist"), "wb") as f:
        plistlib.dump({"CFBundleName": NAME, "CFBundleDisplayName": NAME, "CFBundleIdentifier": BUNDLE_ID,
                       "CFBundleExecutable": APP_EXE, "CFBundleIconFile": "logo", "CFBundlePackageType": "APPL",
                       "CFBundleShortVersionString": __version__, "CFBundleInfoDictionaryVersion": "6.0",
                       "CanworksShortcut": True}, f)
    script = os.path.join(contents, "MacOS", APP_EXE)
    with open(script, "w", encoding="utf-8") as f:
        # Not exec: the configurator would be the app, and opening the app
        # again would only bring it to the front, with no new tab.
        f.write(MAC_SCRIPT % shlex.quote(exe))
    os.chmod(script, os.stat(script).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    shutil.copyfile(os.path.join(ICONS, "logo.icns"), os.path.join(contents, "Resources", "logo.icns"))
    return [app]


# macOS stops what the app started when the script ends (SIGINT, then
# SIGTERM): ignored here and for the first seconds in the configurator
# (server.APP_TEARDOWN_S).
MAC_SCRIPT = "#!/bin/sh\ntrap '' INT TERM\n%s --from-shortcut </dev/null >/dev/null 2>&1 &\n"


# -- Windows ----------------------------------------------------------------

# The .lnk files through WScript.Shell; the values come in environment
# variables, so nothing needs quoting. Prints each path it wrote or removed.
PS_COMMON = r"""
$ErrorActionPreference = 'Stop'
$shell = New-Object -ComObject WScript.Shell
$desk = if ($env:CANWORKS_SHORTCUT_DESKTOP) { $env:CANWORKS_SHORTCUT_DESKTOP } else { [Environment]::GetFolderPath('Desktop') }
$paths = @($env:CANWORKS_LNK_START, (Join-Path $desk ($env:CANWORKS_LNK_NAME + '.lnk')))
"""
PS_CREATE = PS_COMMON + r"""
foreach ($p in $paths) {
    if ((Test-Path -LiteralPath $p) -and ($shell.CreateShortcut($p).Description -ne $env:CANWORKS_LNK_MARK)) {
        throw "$p is there already and was not made by canworks-config"
    }
}
foreach ($p in $paths) {
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $p) | Out-Null
    $l = $shell.CreateShortcut($p)
    $l.TargetPath = $env:CANWORKS_LNK_TARGET
    $l.Arguments = $env:CANWORKS_LNK_ARGS
    $l.WorkingDirectory = $env:CANWORKS_LNK_DIR
    $l.IconLocation = $env:CANWORKS_LNK_ICON + ',0'
    $l.Description = $env:CANWORKS_LNK_MARK
    $l.Save()
    Write-Output $p
}
"""
PS_REMOVE = PS_COMMON + r"""
foreach ($p in $paths) {
    if ((Test-Path -LiteralPath $p) -and ($shell.CreateShortcut($p).Description -eq $env:CANWORKS_LNK_MARK)) {
        Remove-Item -LiteralPath $p
        Write-Output $p
    }
}
"""


def pythonw():
    """pythonw.exe of the tools' environment (no console window), else python."""
    w = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    return w if os.path.isfile(w) else sys.executable


def windows(remove, env, run):
    appdata = env.get("APPDATA") or os.path.join(env.get("USERPROFILE") or os.path.expanduser("~"),
                                                 "AppData", "Roaming")
    values = {"CANWORKS_LNK_START": os.path.join(appdata, "Microsoft", "Windows", "Start Menu", "Programs",
                                                 NAME + ".lnk"),
              "CANWORKS_LNK_NAME": NAME, "CANWORKS_LNK_MARK": MARK, "CANWORKS_LNK_TARGET": pythonw(),
              "CANWORKS_LNK_ARGS": "-m canworks.configurator.start --from-shortcut",
              "CANWORKS_LNK_DIR": env.get("USERPROFILE") or os.path.expanduser("~"),
              "CANWORKS_LNK_ICON": os.path.join(ICONS, "logo.ico")}
    # -Command text: the execution policy is for script files, so no Bypass.
    r = run(["powershell", "-NoProfile", "-NonInteractive", "-Command",
             PS_REMOVE if remove else PS_CREATE], env=dict(env, **values))
    if r.returncode != 0:
        raise Refused((r.stderr or r.stdout or "PowerShell failed").strip().splitlines()[-1])
    return [line.strip() for line in r.stdout.splitlines() if line.strip()]


def _run(cmd, env=None):
    return subprocess.run(cmd, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          universal_newlines=True, timeout=120)


def main(remove=False, platform=None, env=None, run=None, out=None):
    """Adds (or removes) the shortcut; 0, or 2 with the reason."""
    platform = platform or sys.platform
    env = dict(os.environ) if env is None else env
    run = run or _run
    out = out or sys.stdout
    try:
        if platform == "win32":
            paths = windows(remove, env, run)
        elif platform == "darwin":
            paths = macos(remove, env, run)
        else:
            paths = linux(remove, env, run)
    except (OSError, subprocess.SubprocessError, Refused) as e:
        print("canworks-config: could not %s the shortcut: %s" % ("remove" if remove else "add",
                                                                  getattr(e, "strerror", None) or e), file=sys.stderr)
        return 2
    if remove:
        print("Removed the canworks configurator shortcut: %s" % ", ".join(paths) if paths
              else "No canworks configurator shortcut to remove.", file=out)
    else:
        print("Added the canworks configurator shortcut: %s" % ", ".join(paths), file=out)
    return 0
