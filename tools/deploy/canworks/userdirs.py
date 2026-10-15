"""Where the PC tools keep their per-user settings."""

import os
import sys
import time


def config_dir():
    env = os.environ.get("CANWORKS_CONFIG_DIR")
    if env:
        return env
    if sys.platform == "darwin":
        return os.path.expanduser("~/Library/Application Support/canworks")
    if os.name == "nt":
        return os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "canworks")
    return os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), "canworks")


def replace_file(tmp, path, tries=20, wait_s=0.05):
    """os.replace(tmp, path), tried again for about a second while Windows
    refuses it because another process (a second configurator, a virus
    scanner) has `path` open; the temporary file is removed when it still
    fails."""
    for attempt in range(tries):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if os.name != "nt" or attempt == tries - 1:
                try:
                    os.remove(tmp)
                except OSError:
                    pass
                raise
            time.sleep(wait_s)
