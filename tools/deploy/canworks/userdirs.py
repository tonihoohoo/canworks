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


class FileLockedError(PermissionError):
    """Windows kept refusing to replace a file another program holds open."""

    def __init__(self, path):
        super().__init__(13, "%s is held open by another program (often antivirus or a sync client such as "
                             "OneDrive); try again" % path, path)

    def __str__(self):
        return self.strerror


def replace_file(tmp, path, deadline_s=5.0, in_place=False):
    """os.replace(tmp, path). On Windows, while another program (a virus
    scanner, the search indexer, OneDrive, a second configurator) holds
    `path` open, the rename is refused: it is tried again with growing waits
    for about `deadline_s`. Then, with `in_place`, the content is written over
    `path` directly (for a new project's own files, which nothing reads yet);
    else the temporary file is removed and FileLockedError is raised."""
    start = time.monotonic()
    wait = 0.02
    while True:
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if os.name != "nt":
                _remove(tmp)
                raise
            if time.monotonic() - start >= deadline_s:
                break
            time.sleep(wait)
            wait = min(wait * 2, 0.5)
    if in_place:
        try:
            with open(tmp, "rb") as src, open(path, "r+b") as dst:
                dst.write(src.read())
                dst.truncate()
            _remove(tmp)
            return
        except PermissionError:
            pass
    _remove(tmp)
    raise FileLockedError(path)


def _remove(path):
    try:
        os.remove(path)
    except OSError:
        pass
