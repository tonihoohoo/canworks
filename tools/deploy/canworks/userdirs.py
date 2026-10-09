"""Where the PC tools keep their per-user settings."""

import os
import sys


def config_dir():
    env = os.environ.get("CANWORKS_CONFIG_DIR")
    if env:
        return env
    if sys.platform == "darwin":
        return os.path.expanduser("~/Library/Application Support/canworks")
    if os.name == "nt":
        return os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "canworks")
    return os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), "canworks")
