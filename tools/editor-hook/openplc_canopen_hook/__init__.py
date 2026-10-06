"""CANopen editor hook for a stock OpenPLC Runtime v4.

Loaded into the runtime's webserver by openplc_canopen_hook.pth (installed by
scripts/install-stock.sh). When the runtime imports
webserver.plcapp_management, install() wraps its update_plugin_configurations
so that, before the runtime decides which plugins to enable, a CANopen config
carried in the upload's project snapshot is put into the upload's conf/
directory (snapshot.materialize). The runtime then enables the plugin by its
own rules and writes plugins.conf itself, once, in its own order.

This module only uses the standard library: it is imported into the runtime's
webserver. The checks (the deploy tool's contract checks, which need
jsonschema) run in a child process with the CANopen install's own Python
(<prefix>/venv, where scripts/install-stock.sh installs the deploy tool and
this package), so nothing is added to the runtime's environment.

If the runtime no longer has what the hook relies on, nothing is patched and
one error is logged; the runtime then behaves exactly as without the hook.
"""

import functools
import importlib.abc
import importlib.machinery
import inspect
import json
import os
import subprocess
import sys

from . import docker_mode

TARGET = "webserver.plcapp_management"
APP = "webserver.app"
FUNCTION = "update_plugin_configurations"
PREFIX = "[openplc-canopen editor hook] "
TIMEOUT_S = 120

# <prefix>/lib/python/openplc_canopen_hook/__init__.py -> <prefix>/venv/bin/python
_INSTALL_PREFIX = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))


def install_prefix():
    # OPENPLC_CANOPEN_PREFIX is for tests.
    return os.environ.get("OPENPLC_CANOPEN_PREFIX") or _INSTALL_PREFIX


def helper_python():
    return os.environ.get("OPENPLC_CANOPEN_PYTHON") or os.path.join(_INSTALL_PREFIX, "venv", "bin", "python")

_state = {"installed": False, "patched": False, "reported": False, "docker": False, "started": False}

# The runtime's own relative paths; its working directory is the runtime root.
PLUGINS_CONF = "plugins.conf"
PLUGINS_DEFAULT_CONF = "plugins_default.conf"


def running_version():
    return os.environ.get("RUNTIME_VERSION", "").strip()


def _log(level, text):
    sys.stderr.write("%s%s: %s\n" % (PREFIX, level, text))
    sys.stderr.flush()


def _self_check(module):
    """Returns (staged blob path getter, None) or (None, reason)."""
    fn = getattr(module, FUNCTION, None)
    if not callable(fn):
        return None, "%s.%s is missing" % (TARGET, FUNCTION)
    try:
        params = list(inspect.signature(fn).parameters)
    except (TypeError, ValueError):
        params = []
    if not params or params[0] != "generated_dir":
        return None, "%s.%s no longer takes generated_dir" % (TARGET, FUNCTION)
    snap = sys.modules.get("webserver.project_snapshot") or getattr(module, "project_snapshot", None)
    if snap is None or not hasattr(snap, "_STAGED_BLOB"):
        return None, "webserver.project_snapshot has no staged snapshot (_STAGED_BLOB)"
    if not hasattr(module, "build_state") or not hasattr(module.build_state, "log"):
        return None, "%s.build_state.log is missing" % TARGET
    if not os.access(helper_python(), os.X_OK):
        return None, "%s not found (re-run scripts/install-stock.sh)" % helper_python()
    return (lambda: str(snap._STAGED_BLOB)), None


def run_materialize(snapshot_zip, conf_dir):
    """snapshot.materialize() in the helper Python. Returns [(level, text)]."""
    if os.path.exists(os.path.join(conf_dir, "canopen.json")):
        # The deployed config wins (snapshot.materialize says the same).
        return [("INFO", "CANopen: the upload carries conf/canopen.json; the project snapshot is not used")]
    if not os.path.isfile(snapshot_zip):
        return []
    p = subprocess.run([helper_python(), "-m", "openplc_canopen_hook.snapshot", snapshot_zip, conf_dir],
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=TIMEOUT_S)
    try:
        out = json.loads(p.stdout.decode("utf-8"))
        return [(str(level), str(text)) for level, text in out["messages"]]
    except (ValueError, KeyError, TypeError):
        err = p.stderr.decode("utf-8", "replace").strip().splitlines()
        raise RuntimeError("the check exited with %d%s" % (p.returncode, ": " + err[-1] if err else ""))


def patch(module):
    """Wraps module.update_plugin_configurations. Returns True when patched."""
    staged, problem = _self_check(module)
    if problem:
        _log("ERROR", "inactive, CANopen stays off on editor uploads: " + problem)
        return False
    original = getattr(module, FUNCTION)
    if getattr(original, "_openplc_canopen_hook", False):
        return True

    @functools.wraps(original)
    def update_plugin_configurations(generated_dir="core/generated", *args, **kwargs):
        try:
            for level, text in run_materialize(staged(), os.path.join(generated_dir, "conf")):
                module.build_state.log("[%s] %s\n" % (level, text))
        except Exception as e:  # never let the hook break an upload
            module.build_state.log("[WARNING] CANopen: editor hook failed, project config not used: %s\n" % e)
        result = original(generated_dir, *args, **kwargs)
        if _state["docker"]:
            try:
                for level, text in docker_mode.after_upload(install_prefix(), PLUGINS_CONF, running_version()):
                    module.build_state.log("[%s] %s\n" % (level, text))
            except Exception as e:
                module.build_state.log("[WARNING] CANopen: could not record the canopen line: %s\n" % e)
        return result

    update_plugin_configurations._openplc_canopen_hook = True
    setattr(module, FUNCTION, update_plugin_configurations)
    _log("INFO", "active: CANopen configs in editor projects are applied on upload")
    return True


class _Loader(importlib.abc.Loader):
    def __init__(self, inner, after):
        self.inner, self.after = inner, after

    def create_module(self, spec):
        return self.inner.create_module(spec)

    def __getattr__(self, name):  # get_code, get_source, ... from the real loader
        return getattr(self.inner, name)

    def exec_module(self, module):
        self.inner.exec_module(module)
        self.after(module)


class _Finder(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path, target=None):
        if name == APP:
            if _state["docker"] and not _state["started"]:
                _state["started"] = True
                at_webserver_start()
            # `python -m webserver.app` (start_openplc.sh) runs the app
            # through runpy; leave it alone and only check, before it starts,
            # that the module the hook patches is still there.
            if not _state["reported"] and importlib.machinery.PathFinder.find_spec(TARGET, path) is None:
                _log("ERROR", "inactive, CANopen stays off on editor uploads: %s not found" % TARGET)
                _state["reported"] = True
            return None
        if name != TARGET:
            return None
        spec = importlib.machinery.PathFinder.find_spec(name, path)
        if spec is None or spec.loader is None:
            return None
        spec.loader = _Loader(spec.loader, self._after_target)
        return spec

    @staticmethod
    def _after_target(module):
        _state["patched"] = patch(module)
        _state["reported"] = True


def at_webserver_start():
    """Docker mode: restores the canopen line before the runtime reads plugins.conf."""
    try:
        for level, text in docker_mode.at_start(install_prefix(), PLUGINS_CONF, PLUGINS_DEFAULT_CONF,
                                                running_version()):
            _log(level, text)
    except Exception as e:  # never stop the webserver from starting
        _log("ERROR", "could not restore the canopen line in plugins.conf: %s" % e)


def install(docker=False):
    """Registers the import hook (idempotent). Called from the .pth file, or
    with docker=True from the sitecustomize the Docker-mode install puts on
    the runtime container's PYTHONPATH."""
    if docker:
        _state["docker"] = True
    if _state["installed"]:
        return
    _state["installed"] = True
    sys.meta_path.insert(0, _Finder())
