"""The newest canworks release, found as the install scripts find it: GitHub
redirects releases/latest to releases/tag/deploy-v<version> (no API token)."""

import os
import re
import threading
import time
import urllib.error
import urllib.request

from .ssh import SshError, quote

REPO = "https://github.com/tonihoohoo/canworks"
CACHE_S = 600.0
_TAG = re.compile(r"/releases/tag/deploy-v(\d+\.\d+\.\d+)$")
_cache = {"at": 0.0, "version": None}
_lock = threading.Lock()


def _url():
    return os.environ.get("CANWORKS_RELEASES_URL") or REPO + "/releases/latest"


def from_url(url):
    m = _TAG.search((url or "").strip())
    return m.group(1) if m else None


def latest(refresh=False, timeout=8.0):
    """The newest release's version from this PC, or None (kept 10 minutes)."""
    with _lock:
        if not refresh and _cache["version"] and time.monotonic() - _cache["at"] < CACHE_S:
            return _cache["version"]
    try:
        req = urllib.request.Request(_url(), method="HEAD", headers={"User-Agent": "canworks-config"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            version = from_url(r.geturl())
    except (OSError, urllib.error.URLError, ValueError):
        version = None
    if version:
        with _lock:
            _cache.update(at=time.monotonic(), version=version)
    return version


def latest_on_device(conn):
    """The same lookup from the device (a PC without internet access)."""
    try:
        status, out, _ = conn.run("curl -fsSL -o /dev/null -w '%%{url_effective}' %s" % quote(_url()), timeout=20.0)
    except SshError:
        return None
    return from_url(out) if status == 0 else None


ADAPTER_SCRIPT = "install-adapter.sh"
MAX_ADAPTER_FILE = 8 << 20  # the file is about 1 MB; anything far larger is not it


def adapter_file_name(version):
    return "canworks-adapter-%s.pyz" % version


def _download_url():
    return os.environ.get("CANWORKS_RELEASES_DOWNLOAD") or REPO + "/releases/download"


def adapter_files(version, cache_dir, timeout=30.0):
    """[install-adapter.sh, canworks-adapter-<version>.pyz] of release
    `version` downloaded on this PC into cache_dir/<version>/ (kept there,
    so a second device needs no download), or None when this PC cannot get
    them (add-adapter-server-file: the job then downloads on the device)."""
    folder = os.path.join(cache_dir, version)
    names = (ADAPTER_SCRIPT, adapter_file_name(version))
    paths = [os.path.join(folder, n) for n in names]
    if all(os.path.isfile(p) for p in paths):
        return paths
    try:
        os.makedirs(folder, exist_ok=True)
        for name, path in zip(names, paths):
            if os.path.isfile(path):
                continue
            url = "%s/deploy-v%s/%s" % (_download_url(), version, name)
            req = urllib.request.Request(url, headers={"User-Agent": "canworks-config"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = r.read(MAX_ADAPTER_FILE + 1)
            if not data or len(data) > MAX_ADAPTER_FILE:
                return None
            tmp = path + ".part"
            with open(tmp, "wb") as f:
                f.write(data)
            os.replace(tmp, path)
    except (OSError, urllib.error.URLError, ValueError):
        return None
    return paths
