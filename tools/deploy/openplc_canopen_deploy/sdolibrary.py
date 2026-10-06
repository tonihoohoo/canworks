"""The openplc_canopen editor library: SDO function blocks for the PLC program
(spec canopen-plc-sdo).

The package carries the library as built from library/openplc_canopen
(library/build.sh); its version is set to this package's version when it is
written out. `install()` puts it where OpenPLC Editor's Library Manager puts
a library installed from a file: {userData}/libraries/<name>/<name>.stlib,
registered in {userData}/libraries/registry.json.
"""

import datetime
import json
import os
import sys

from . import __version__

NAME = "openplc_canopen"
FILE_NAME = NAME + ".stlib"
_PACKAGED = os.path.join(os.path.dirname(os.path.abspath(__file__)), "library", FILE_NAME)
# The editor's userData folder name (Electron app name of OpenPLC Editor).
EDITOR_APP = "open-plc-editor"


class LibraryError(Exception):
    pass


def archive():
    """The library archive (a dict), with this package's version."""
    try:
        with open(_PACKAGED, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        raise LibraryError("the packaged library %s cannot be read: %s" % (_PACKAGED, e))
    data["manifest"]["version"] = __version__
    return data


def archive_text():
    return json.dumps(archive(), indent=2) + "\n"


def block_names():
    return [fb["name"] for fb in archive()["manifest"]["functionBlocks"]]


def write(out_dir):
    """Writes openplc_canopen.stlib into out_dir; returns its path."""
    out_dir = os.path.abspath(os.path.expanduser(out_dir))
    if not os.path.isdir(out_dir):
        raise LibraryError("%s is not a folder" % out_dir)
    path = os.path.join(out_dir, FILE_NAME)
    _write(path, archive_text())
    return path


def editor_user_data(environ=None, platform=None, home=None):
    """The editor's userData folder on this computer (it need not exist);
    $OPENPLC_EDITOR_USER_DATA overrides it."""
    environ = os.environ if environ is None else environ
    if environ.get("OPENPLC_EDITOR_USER_DATA"):
        return environ["OPENPLC_EDITOR_USER_DATA"]
    platform = platform or sys.platform
    home = home or os.path.expanduser("~")
    if platform == "darwin":
        return os.path.join(home, "Library", "Application Support", EDITOR_APP)
    if platform.startswith("win"):
        return os.path.join(environ.get("APPDATA") or os.path.join(home, "AppData", "Roaming"), EDITOR_APP)
    return os.path.join(environ.get("XDG_CONFIG_HOME") or os.path.join(home, ".config"), EDITOR_APP)


def installed_version(user_data=None):
    """The version of the library installed in the editor, or None."""
    registry = os.path.join(user_data or editor_user_data(), "libraries", "registry.json")
    try:
        with open(registry, encoding="utf-8") as f:
            entry = json.load(f).get("libraries", {}).get(NAME)
    except (OSError, ValueError, AttributeError):
        return None
    if not isinstance(entry, dict) or not os.path.isfile(entry.get("stlibPath", "")):
        return None
    return entry.get("version")


def install(user_data=None):
    """Installs the library into the editor as its Library Manager does;
    returns the archive's path."""
    user_data = user_data or editor_user_data()
    if not os.path.isdir(user_data):
        raise LibraryError("%s does not exist: start OpenPLC Editor once, or install the library from a file with "
                           "the editor's Library Manager (openplc-canopen-deploy library --out DIR)" % user_data)
    libraries = os.path.join(user_data, "libraries")
    target_dir = os.path.join(libraries, NAME)
    os.makedirs(target_dir, exist_ok=True)
    path = os.path.join(target_dir, FILE_NAME)
    _write(path, archive_text())
    registry_path = os.path.join(libraries, "registry.json")
    registry = {"formatVersion": "1.0", "libraries": {}}
    if os.path.exists(registry_path):
        try:
            with open(registry_path, encoding="utf-8") as f:
                registry = json.load(f)
        except (OSError, ValueError) as e:
            raise LibraryError("%s cannot be read: %s" % (registry_path, e))
        if not isinstance(registry, dict) or not isinstance(registry.get("libraries"), dict):
            raise LibraryError("%s is not an editor library registry" % registry_path)
    registry["libraries"][NAME] = {
        "version": __version__,
        "installedAt": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
        "stlibPath": path,
        "origin": "stlib",
    }
    _write(registry_path, json.dumps(registry, indent=2))
    return path


def ensure_installed(user_data=None):
    """Installs the library into the editor when it is missing or older than
    these tools. Returns (ok, message); ok is False when it could not be
    installed, and the message then says how to install it."""
    have = installed_version(user_data)
    if have == __version__:
        return True, "%s %s is installed in the editor" % (NAME, have)
    try:
        path = install(user_data)
    except (LibraryError, OSError) as e:
        return False, ("the editor does not have the %s library and it was not installed: %s. Install it with "
                       "'openplc-canopen-deploy library --install', or write it with 'openplc-canopen-deploy library "
                       "--out DIR' and add it in the editor's Library Manager" % (NAME, e))
    return True, "installed %s %s into the editor (%s%s); restart OpenPLC Editor if it is open" % (
        NAME, __version__, path, "" if have is None else ", replacing %s" % have)


def enable_in_project(project_dir):
    """Enables the library in an editor project (project.json data.libraries),
    as the editor does when the user ticks it in the Library Manager."""
    path = os.path.join(project_dir, "project.json")
    with open(path, encoding="utf-8") as f:
        proj = json.load(f)
    data = proj.get("data") if isinstance(proj, dict) else None
    if not isinstance(data, dict):
        raise LibraryError("%s has no project data" % path)
    libs = data.get("libraries")
    if not isinstance(libs, list):
        libs = data["libraries"] = []
    libs[:] = [lib for lib in libs if not (isinstance(lib, dict) and lib.get("name") == NAME)]
    libs.append({"name": NAME, "version": __version__})
    _write(path, json.dumps(proj, indent=2))


def _write(path, text):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)
