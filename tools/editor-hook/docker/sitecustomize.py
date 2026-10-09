"""Loads the CANopen editor hook in the OpenPLC runtime container.

scripts/install-stock.sh (Docker mode) installs this file as
<prefix>/lib/sitecustomize/sitecustomize.py and puts that directory on the
runtime container's PYTHONPATH (the bootloader's extraEnv), so every Python
in the container imports it at startup. It registers the hook, which only acts
when the runtime's webserver starts; elsewhere (plugin venvs, dcfgen) it is an
unused import hook. Any other sitecustomize on sys.path still runs.
"""

import importlib.machinery
import importlib.util
import os
import sys


def _chain():
    here = os.path.dirname(os.path.abspath(__file__))
    rest = [p for p in sys.path if os.path.abspath(p or os.curdir) != here]
    spec = importlib.machinery.PathFinder.find_spec("sitecustomize", rest)
    if spec is None or spec.loader is None:
        return
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)


def _load_hook():
    # <prefix>/lib/sitecustomize/ -> <prefix>/lib/python/ (the hook package)
    hook_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "python")
    if hook_dir not in sys.path:
        sys.path.append(hook_dir)
    try:
        import canworks_hook
    except ImportError:
        return
    canworks_hook.install(docker=True)


try:
    _chain()
except Exception as e:  # another sitecustomize failing must not stop Python
    sys.stderr.write("[canworks editor hook] WARNING: the other sitecustomize failed: %s\n" % e)
try:
    _load_hook()
except Exception as e:
    sys.stderr.write("[canworks editor hook] ERROR: not loaded: %s\n" % e)
