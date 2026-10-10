"""Online access for the configurator: the diagnostics token and runtime host
kept on this PC, the connection to the plugin's diagnostics channel, config
fingerprints, and EDS matching for scan results.

The token is never written to the project: canworks.json holds only its
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
SEND_IDLE_CLOSE_S = 10.0  # the Trace view polls its jobs every second; a closed page lets them end
DEPLOYED_EDS_DIR = "canworks/eds"  # bundle.EDS_DIR, and the editor hook's
DEPLOYED_FW_DIR = "canworks/fw"


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
    """SHA-256 values the runtime may report for this canworks.json: the file
    itself, and the conf/canworks.json the deploy tool and the editor hook
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
# Runtimes on the local network and remembered ones (remote link)


def remembered(host):
    """The remembered runtime (canworks.link.pc) a host text names, or None."""
    if not host or not isinstance(host, str):
        return None
    from ..link import pc as linkpc
    try:
        return linkpc.find(host)
    except Exception:  # a broken runtimes.json reads as nothing remembered
        return None


def remembered_view(host):
    """What the page shows of the remembered runtime `host` names: {name,
    link (has a link ID), paired, internet}, or None."""
    entry = remembered(host)
    if not entry:
        return None
    return {"name": entry["name"], "link": bool(entry.get("id")), "paired": bool(entry.get("paired")),
            "internet": bool(entry.get("internet"))}


def runtimes_list(wait=2.0):
    """The connect box's list: {discovered: [{name, address, addresses, id}]
    (runtimes that answer on the local network within `wait` seconds; the
    address to connect to, with the diagnostics port when it is not the
    default), remembered: [{name, hosts, paired, internet, link}],
    discovery: whether this PC can browse (zeroconf), link: whether the
    remote link works here (iroh)}."""
    from .. import link
    from ..link import discovery, pc as linkpc
    found = []
    try:
        browsed = discovery.browse(wait) if discovery.available() else []
    except Exception:  # an mDNS failure must not break the connect box
        browsed = []
    for r in browsed:
        addrs = list(r.get("addresses") or [])
        # IPv4 first: a scoped IPv6 link-local address is hard to type and to read.
        addrs.sort(key=lambda a: ":" in a)
        address = None
        if addrs:
            a = addrs[0]
            address = "[%s]" % a if ":" in a else a
            if r.get("diag") and r["diag"] != diag.DEFAULT_PORT:
                address += ":%d" % r["diag"]
            elif ":" in a:
                address += ":%d" % diag.DEFAULT_PORT  # "[v6]" alone is not a HOST
        found.append({"name": r.get("name") or "", "address": address, "addresses": addrs, "id": r.get("id")})
    try:
        items = linkpc.runtimes()
    except Exception:
        items = []
    mem = [{"name": r["name"], "hosts": list(r.get("hosts") or []), "paired": bool(r.get("paired")),
            "internet": bool(r.get("internet")), "link": bool(r.get("id"))} for r in items]
    mem.sort(key=lambda r: r["name"].lower())
    return {"discovered": found, "remembered": mem, "discovery": discovery.available(),
            "link": link.available()}


# ---------------------------------------------------------------------------
# Connection to the plugin


class AdapterTarget:
    """A CAN adapter on this PC as the online target (canopen-local-bus), in
    place of a runtime host: the adapter (TYPE:CHANNEL), the bit rate in
    bit/s, the session's allow-changes switch and the configured nodes
    ({node_id: {name, expect}}) for status and scan. Equal targets share the
    kept-open connection."""

    def __init__(self, adapter, bitrate, allow_changes=False, nodes=None, network=None):
        self.adapter, self.bitrate, self.allow_changes = adapter, bitrate, bool(allow_changes)
        self.nodes = nodes or {}
        self.network = network

    def _key(self):
        return (self.adapter, self.bitrate, self.allow_changes, self.network,
                json.dumps(self.nodes, sort_keys=True, default=str))

    def __eq__(self, other):
        return isinstance(other, AdapterTarget) and self._key() == other._key()

    def __hash__(self):
        return hash(self._key())

    def __str__(self):
        return "USB adapter %s" % self.adapter

    def client(self, timeout):
        from .. import localbus
        try:
            spec = localbus.parse(self.adapter)
        except localbus.AdapterError as e:
            raise diag.DiagError("usage", str(e))
        return localbus.LocalBus(spec, self.bitrate, allow_changes=self.allow_changes, config=self.nodes,
                                 network=self.network, timeout=timeout)


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
        self.notes_shown = set()  # ids of the pairing jobs whose line the page has had

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

    def link_info(self):
        """{path, rtt_ms, pairing_note} of the open connection: the path the
        automatic path choice took ("LAN", "internet direct", "internet
        relayed"; None for a USB adapter), the measured round trip in ms, and
        the background pairing's one line (see diag.Client.connect) once it
        finished, given once per pairing and only when the runtime is
        reachable from other networks (remote_link.internet)."""
        with self.lock:
            c, key = self.client, self.key
        if c is None or isinstance(key[0], AdapterTarget):
            return {"path": None, "rtt_ms": None, "pairing_note": None}
        out = {"path": getattr(c, "path", None), "rtt_ms": getattr(c, "rtt_ms", None), "pairing_note": None}
        job = getattr(c, "pairing", None)
        if not isinstance(job, dict) or id(job) in self.notes_shown:
            return out
        thread = job.get("thread")
        if thread is not None and thread.is_alive():
            return out
        self.notes_shown.add(id(job))
        entry = remembered(c.host)
        if job.get("note") and entry and entry.get("internet"):
            out["pairing_note"] = job["note"]
        return out

    def _open(self, key):
        if isinstance(key[0], AdapterTarget):
            c = key[0].client(self.timeout)
        else:
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


class Sender:
    """Raw frames of the Trace view's Send panel, on a connection of their own:
    a cyclic job belongs to the connection that started it and ends when it
    closes, so the online view closing its connection must not stop them. A
    page that goes away without stopping its jobs stops polling, and the
    connection closes after SEND_IDLE_CLOSE_S, which ends them on the plugin.
    `jobs` are the cyclic jobs started here, by (network, job number)."""

    def __init__(self, idle=SEND_IDLE_CLOSE_S, timeout=3.0):
        self.connection = Connection(idle=idle, timeout=timeout)
        self.lock = threading.Lock()
        self.jobs = {}

    def send(self, where, network, frame, force=False):
        """frame: {can_id, ext, rtr, dlc, data (bytes), period_ms, count}.
        where: (host, port, token). Raises diag.DiagError."""
        res = self.connection.call(*where, lambda c: c.send_frame(
            frame["can_id"], frame.get("data") or b"", frame.get("ext"), frame.get("rtr"), frame.get("dlc"),
            frame.get("period_ms"), frame.get("count"), force), network)
        if res.get("job") is not None:
            with self.lock:
                self.jobs[(network, res["job"])] = {
                    "job": res["job"], "network": network, "id": frame["can_id"], "ext": bool(frame.get("ext")),
                    "rtr": bool(frame.get("rtr")), "dlc": frame.get("dlc"),
                    "data": diag.hex_bytes(frame.get("data") or b""), "period_ms": res.get("period_ms"),
                    "count": res.get("count"), "sent": 0}
        return res

    def stop(self, where, network=None, job=None):
        """Stops one job, or every job started here (on every network); the
        plugin's "stopped" entries. Nothing to stop opens no connection."""
        with self.lock:
            keys = [k for k in self.jobs if job is None or k == (network, job)]
        out = []
        for net in sorted({k[0] for k in keys}, key=str):
            if not self.connection.connected:
                break  # the connection, and with it the jobs, is gone
            mine = [k[1] for k in keys if k[0] == net]
            res = self.connection.call(*where, lambda c: c.send_frame_stop(job if job is not None else None), net)
            for s in res.get("stopped") or []:
                if s.get("job") in mine:
                    out.append(dict(s, network=net))
        with self.lock:
            for k in keys:
                self.jobs.pop(k, None)
        return out

    def poll(self, where):
        """The jobs started here with their sent counts from the plugin's
        status, and the ones that ended since the last poll (count reached,
        transmit error, time limit) with their reason."""
        with self.lock:
            jobs = dict(self.jobs)
        ended = []
        if not jobs:
            return {"jobs": [], "ended": []}
        if not self.connection.connected:
            # The connection closed (idle, or the runtime went away): its jobs ended with it.
            with self.lock:
                for k in jobs:
                    self.jobs.pop(k, None)
            return {"jobs": [], "ended": [dict(j, reason="connection closed") for j in jobs.values()]}
        for net in sorted({k[0] for k in jobs}, key=str):
            st = self.connection.call(*where, lambda c: c.status(), net)
            if "send_jobs" not in st:
                continue  # a plugin that does not list jobs: counts stay unknown
            live = {j.get("job"): j for j in st.get("send_jobs") or [] if not j.get("reason")}
            for (n, number), j in jobs.items():
                if n != net:
                    continue
                if number in live:
                    j["sent"] = live[number].get("sent", j["sent"])
                    continue
                res = self.connection.call(*where, lambda c: c.send_frame_stop(number), net)
                got = next((s for s in res.get("stopped") or [] if s.get("job") == number), {})
                ended.append(dict(j, sent=got.get("sent", j["sent"]), reason=got.get("reason") or "ended"))
                with self.lock:
                    self.jobs.pop((n, number), None)
        with self.lock:
            return {"jobs": [dict(j) for j in self.jobs.values()], "ended": ended}

    def close(self):
        """Closes the connection; the plugin ends its jobs."""
        self.connection.close()
        with self.lock:
            self.jobs.clear()


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
                    break  # canworks/ itself only
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
