"""Where the PC tools keep their per-user settings."""

import os
import sys


def config_dir():
    env = os.environ.get("OPENPLC_CANOPEN_CONFIG_DIR")
    if env:
        return env
    if sys.platform == "darwin":
        return os.path.expanduser("~/Library/Application Support/openplc-canopen")
    if os.name == "nt":
        return os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "openplc-canopen")
    return os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), "openplc-canopen")
