"""Online access for the configurator: the diagnostics token and runtime host
kept on this PC, the connection to the plugin's diagnostics channel, config
fingerprints, and EDS matching for scan results.

The token is never written to the project: canopen.json holds only its
SCRAM verifier (master.diagnostics.token_verifier). The plain token and the runtime
host live in online.json in the configurator's settings folder, per project
folder.
"""

import hashlib
import json
import os
import threading
import time

from .. import contract, diag
from .. import eds as eds_mod

SETTINGS = "online.json"
IDLE_CLOSE_S = 30.0
DEPLOYED_EDS_DIR = "canopen/eds"  # bundle.EDS_DIR, and the editor hook's
DEPLOYED_FW_DIR = "canopen/fw"


# ---------------------------------------------------------------------------
# Settings on this PC


class Settings:
    # One lock for every instance: the server makes a Settings per request, and
    # two requests at once (the host field's change event and the Connect click)
    # used to write the same temporary file, so one of them failed.
    lock = threading.Lock()

    def __init__(self, folder):
        self.path = os.path.join(folder, SETTINGS)

    def load(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _store(self, data):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = "%s.%d.%d.tmp" % (self.path, os.getpid(), threading.get_ident())
        # The file holds access tokens: readable by this user only.
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, self.path)

    def project(self, folder):
        p = (self.load().get("projects") or {}).get(folder)
        return dict(p) if isinstance(p, dict) else {}

    def update_project(self, folder, **values):
        with self.lock:
            data = self.load()
            projects = data.setdefault("projects", {})
            p = projects.setdefault(folder, {})
            for k, v in values.items():
                if v is None:
                    p.pop(k, None)
                else:
                    p[k] = v
            self._store(data)
            return dict(p)

    @property
    def eds_library(self):
        v = self.load().get("eds_library")
        return v if isinstance(v, str) else ""

    def set_eds_library(self, path):
        with self.lock:
            data = self.load()
            data["eds_library"] = path or ""
            self._store(data)


# ---------------------------------------------------------------------------
# Fingerprints


def fingerprints(config_path):
    """SHA-256 values the runtime may report for this canopen.json: the file
    itself, and the conf/canopen.json the deploy tool and the editor hook
    write from it (EDS and program paths rewritten, indent 2). Empty when the
    file does not exist or cannot be read."""
    try:
        with open(config_path, "rb") as f:
            raw = f.read()
    except OSError:
        return set()
    out = {hashlib.sha256(raw).hexdigest()}
    try:
        cfg = json.loads(raw.decode("utf-8"))
        for n in contract.all_nodes(cfg):
            if isinstance(n.get("eds"), str):
                n["eds"] = "%s/%s" % (DEPLOYED_EDS_DIR, os.path.basename(n["eds"].replace("\\", "/")))
            if n.get("software_file"):
                n["software_file"] = "%s/%s" % (DEPLOYED_FW_DIR,
                                                os.path.basename(str(n["software_file"]).replace("\\", "/")))
        out.add(hashlib.sha256((json.dumps(cfg, indent=2) + "\n").encode("utf-8")).hexdigest())
    except (ValueError, AttributeError, TypeError):
        pass
    return out


# ---------------------------------------------------------------------------
# Connection to the plugin


class Connection:
    """One diagnostics connection, opened on the first request and closed
    after IDLE_CLOSE_S without one (or by close())."""

    def __init__(self, idle=IDLE_CLOSE_S, timeout=3.0):
        self.idle, self.timeout = idle, timeout
        self.lock = threading.Lock()
        self.client = None
        self.key = None
        self.last = 0.0
        self.timer = None

    def call(self, host, port, token, fn, network=None):
        """fn(client) on a connected client whose requests go to `network`
        (when the plugin runs several); a lost connection is reopened once.
        Raises diag.DiagError."""
        with self.lock:
            key = (host, port, token)
            if self.client is None or self.key != key:
                self._close()
                self._open(key)
            try:
                self.client.network = network
                result = fn(self.client)
            except diag.DiagError as e:
                if e.kind not in ("eof", "timeout"):
                    raise
                self._close()
                self._open(key)
                self.client.network = network
                result = fn(self.client)
            self.last = time.monotonic()
            self._arm()
            return result

    @property
    def info(self):
        return self.client.info if self.client else None

    def _open(self, key):
        c = diag.Client(key[0], key[1], key[2], self.timeout)
        c.connect()
        self.client, self.key = c, key

    def _arm(self):
        if self.timer:
            self.timer.cancel()
        self.timer = threading.Timer(self.idle, self._idle)
        self.timer.daemon = True
        self.timer.start()

    def _idle(self):
        with self.lock:
            if time.monotonic() - self.last >= self.idle - 0.05:
                self._close()

    def _close(self):
        if self.client:
            self.client.close()
        self.client = self.key = None

    def close(self):
        with self.lock:
            if self.timer:
                self.timer.cancel()
                self.timer = None
            self._close()

    @property
    def connected(self):
        return self.client is not None


# ---------------------------------------------------------------------------
# EDS matching for scan results


class EdsIndex:
    """[DeviceInfo] of the EDS files in some folders, cached by mtime."""

    def __init__(self):
        self.cache = {}

    def files(self, folders):
        out = []
        for where, folder in folders:
            if not folder or not os.path.isdir(folder):
                continue
            for root, dirs, names in os.walk(folder):
                dirs[:] = [d for d in dirs if not d.startswith(".")]
                for name in sorted(names):
                    if name.lower().endswith(".eds"):
                        out.append((where, os.path.join(root, name)))
                if where == "project":
                    break  # canopen/ itself only
        return out

    def info(self, path):
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            return None
        hit = self.cache.get(path)
        if hit and hit[0] == mtime:
            return hit[1]
        info = eds_mod.device_info(path)
        self.cache[path] = (mtime, info)
        return info

    def matches(self, folders, vendor_id, product_code, revision=None):
        """EDS files whose VendorNumber and ProductNumber match, an exact
        RevisionNumber first, then project files before library files."""
        if vendor_id is None or product_code is None:
            return []
        found = []
        for where, path in self.files(folders):
            info = self.info(path)
            if not info or info["vendor_id"] != vendor_id or info["product_code"] != product_code:
                continue
            exact = revision is not None and info["revision_number"] == revision
            found.append({"path": path, "name": os.path.basename(path), "where": where,
                          "revision_number": info["revision_number"], "revision_match": exact,
                          "vendor_name": info["vendor_name"], "product_name": info["product_name"]})
        found.sort(key=lambda m: (not m["revision_match"], m["where"] != "project", m["name"].lower()))
        return found


def expected_identity(node, eds_path):
    """What the config expects of a node: vendor and product from its EDS,
    revision and serial number from the node's identity check fields."""
    out = {}
    info = eds_mod.device_info(eds_path) if eds_path else None
    if info:
        out["vendor_id"], out["product_code"] = info["vendor_id"], info["product_code"]
    for key in ("revision_number", "serial_number"):
        v = node.get(key)
        if isinstance(v, str):
            try:
                v = int(v, 0)
            except ValueError:
                v = None
        if isinstance(v, int) and v:
            out[key] = v
    return out
