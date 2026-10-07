"""LocalBus: the diagnostics operations served by a CAN adapter on this PC,
with diag.Client's interface (canopen-local-bus). Everything built on
diag.Client (the CLI, the configurator's online pages, device parameters,
traces) works on it unchanged.

Operations come from one table (OPS). An operation the table lacks answers
"not available on a local adapter". Later operations (raw frames, bit rate
detection) are added there and send through Core.transmit.
"""

import base64
import threading
import time

from .. import __version__
from ..diag import DiagError, LSS_BITRATES, LSS_KEYS, NMT_COMMANDS, PROTOCOL, hex_bytes, parse_hex, abort_text
from . import adapter as adapter_mod
from . import core as core_mod
from . import lss as lss_mod
from . import sdo as sdo_mod

NMT_CODES = {"start": 0x01, "stop": 0x02, "preop": 0x80, "reset": 0x81, "reset-comm": 0x82}
SCAN_PARALLEL = 8
SCAN_PROBE_S = 0.1
SCAN_READ_S = 0.2
TRACE_MAX = 4000
CHANGES = ("sdo_write", "nmt", "lss_find", "lss_inquire", "lss_set_id", "lss_set_bitrate")
NOT_LOCAL = "not available on a local adapter"


def _int(v, what, lo, hi):
    try:
        n = int(str(v), 0) if isinstance(v, str) else int(v)
    except (TypeError, ValueError):
        raise DiagError("refused", "field '%s' must be a number" % what)
    if isinstance(v, bool) or not lo <= n <= hi:
        raise DiagError("refused", "field '%s' must be %d-%d" % (what, lo, hi))
    return n


class _Shared:
    """Per adapter (Core) state the handles share: the scan and LSS jobs."""

    def __init__(self):
        self.lock = threading.Lock()
        self.scan = None  # {"running", "entries", "started", ...}
        self.lss_busy = False
        self.find = None


_shared = {}
_shared_lock = threading.Lock()


def _shared_of(core):
    with _shared_lock:
        return _shared.setdefault(id(core), _Shared())


class LocalBus:
    """One handle on a local adapter. `spec` is an adapter.Spec, `bitrate`
    in bit/s. `config` optionally names configured nodes: {node_id: {"name",
    "expect": {vendor_id, product_code, revision_number, serial_number}}}.
    `allow_changes` is the session switch; `force` lets LSS run while another
    master is active."""

    def __init__(self, spec, bitrate, allow_changes=False, force=False, config=None, network=None,
                 timeout=5.0, listen_s=None):
        self.spec, self.bitrate = spec, bitrate
        self.allow_changes, self.force = bool(allow_changes), bool(force)
        self.config = dict(config or {})
        self.network = network
        self.timeout = timeout
        self.listen_s = listen_s
        self.core = None
        self.info = None
        self.trace_after = None
        self.trace_filters = []
        self.trace_errors = False

    # -- diag.Client's interface -------------------------------------------------
    @property
    def where(self):
        return "adapter %s" % self.spec

    @property
    def networks(self):
        return (self.info or {}).get("networks") or []

    def several(self):
        return False

    def connect(self):
        self.close()
        try:
            self.core = core_mod.acquire(self.spec, self.bitrate,
                                         core_mod.LISTEN_S if self.listen_s is None else self.listen_s)
        except adapter_mod.AdapterError as e:
            raise DiagError("usage" if e.kind == "usage" else e.kind, str(e))
        self.info = self.request("hello")
        return self.info

    def close(self):
        if self.core is not None:
            if self.trace_after is not None:
                self.core.trace_remove()
                self.trace_after = None
            core_mod.release(self.core)
        self.core = None

    def request(self, op, timeout=None, **fields):
        if self.core is None:
            raise DiagError("eof", "not connected to %s" % self.where)
        if self.core.error:
            raise DiagError("eof", self.core.error)
        fn = OPS.get(op)
        if fn is None:
            raise DiagError("refused", NOT_LOCAL)
        if op in CHANGES and not self.allow_changes:
            raise DiagError("refused", "changes not allowed (start with --allow-changes)")
        try:
            return fn(self, fields)
        except adapter_mod.AdapterError as e:
            raise DiagError("eof", str(e))

    # The same convenience methods as diag.Client.
    def status(self):
        return self.request("status")

    def emcy(self, node):
        return self.request("emcy", node=node)

    def sdo_read(self, node, index, subindex, timeout_ms=1000):
        return self.request("sdo_read", node=node, index=index, subindex=subindex, timeout_ms=timeout_ms)

    def sdo_write(self, node, index, subindex, data, timeout_ms=1000):
        return self.request("sdo_write", node=node, index=index, subindex=subindex, data=hex_bytes(data),
                            timeout_ms=timeout_ms)

    def nmt(self, node, command):
        return self.request("nmt", node=node, command=command)

    def scan(self, start=True):
        return self.request("scan" if start else "scan_status")

    def lss_find(self, start=True, vendor_id=None, product_code=None):
        fields = {}
        if start and vendor_id is not None and product_code is not None:
            fields = {"vendor_id": vendor_id, "product_code": product_code}
        return self.request("lss_find" if start else "lss_find_status", **fields)

    def lss_inquire(self, address):
        return self.request("lss_inquire", **dict(zip(LSS_KEYS, address)))

    def lss_set_id(self, address, node, store=False):
        return self.request("lss_set_id", node=node, store=bool(store), **dict(zip(LSS_KEYS, address)))

    def lss_set_bitrate(self, address, bitrate_kbit, store=False):
        return self.request("lss_set_bitrate", bitrate_kbit=bitrate_kbit, store=bool(store),
                            **dict(zip(LSS_KEYS, address)))

    def trace_start(self, filters=None, error_frames=False):
        fields = {"error_frames": bool(error_frames)}
        if filters:
            fields["filters"] = [{"id": i, "mask": m} for i, m in filters]
        return self.request("trace_start", **fields)

    def trace_fetch(self, after, max_frames=TRACE_MAX):
        return self.request("trace_fetch", after=after, max=max_frames)

    def trace_stop(self):
        return self.request("trace_stop")

    # -- helpers ------------------------------------------------------------------
    def _network(self):
        return {"name": self.network or "", "interface": str(self.spec), "bitrate": self.core.bitrate,
                "role": "local", "master_node_id": None}

    def _force(self, fields):
        return self.force or fields.get("force") is True

    def _check_master(self, fields):
        other = self.core.other_master()
        if other and not self._force(fields):
            raise DiagError("refused", "another master is active on this bus (%s, last at %s); --force runs LSS "
                                       "anyway" % (other["what"], other["last_at"]))


# ---------------------------------------------------------------------------
# The operations


def _hello(c, f):
    return {"protocol": PROTOCOL, "version": __version__, "allow_changes": c.allow_changes, "local": True,
            "adapter": str(c.spec), "bitrate": c.core.bitrate, "untested_adapter": adapter_mod.untested(c.spec),
            "master_node_id": None, "networks": [c._network()]}


def _status(c, f):
    core = c.core
    now = time.monotonic()
    with core.lock:
        heard = dict(core.heard)
        emcy = {n: dict(e) for n, e in core.emcy.items()}
    bus = {"interface": str(c.spec), "state": None}
    state = getattr(core.bus, "state", None)
    name = getattr(state, "name", None)
    if name:
        bus["adapter_state"] = name.lower()
    ids = sorted(set(heard) | set(emcy) | set(c.config))
    nodes = []
    for n in ids:
        h = heard.get(n)
        e = emcy.get(n) or {}
        code, reg = e.get("last", (0, 0))
        cfg = c.config.get(n) or {}
        nodes.append({"node_id": n, "name": cfg.get("name") or "", "configured": n in c.config,
                      "state": h["state"] if h else None,
                      "last_heard_s": round(now - h["at"], 1) if h else None,
                      "emcy": {"code": code, "error_register": reg, "count": e.get("count", 0)}})
    other = core.other_master()
    return {"local": True, "version": __version__, "uptime_s": round(now - core.started, 1),
            "adapter": str(c.spec), "bitrate": core.bitrate, "network": c.network or "",
            "untested_adapter": adapter_mod.untested(c.spec), "allow_changes": c.allow_changes,
            "session": True, "bus": bus, "master": None, "other_master": bool(other),
            "other_master_seen": other, "nodes": nodes}


def _emcy(c, f):
    node = _int(f.get("node"), "node", 1, 127)
    with c.core.lock:
        e = c.core.emcy.get(node)
        hist = list(e["history"]) if e else []
    return {"node_id": node, "emcy": hist}


def _sdo(c, f, write):
    node = _int(f.get("node"), "node", 1, 127)
    index = _int(f.get("index"), "index", 0, 0xFFFF)
    sub = _int(f.get("subindex"), "subindex", 0, 0xFF)
    timeout_ms = _int(f.get("timeout_ms", 1000), "timeout_ms", 10, 10000)
    res = {"node": node, "index": index, "subindex": sub}
    try:
        if write:
            try:
                data = parse_hex(f.get("data") or "")
            except ValueError:
                raise DiagError("refused", "field 'data' must be hex bytes")
            if not data or len(data) > sdo_mod.MAX_BYTES:
                raise DiagError("refused", "field 'data' must be 1-%d bytes" % sdo_mod.MAX_BYTES)
            sdo_mod.download(c.core, node, index, sub, data, timeout_ms / 1000.0)
            res["success"] = True
        else:
            data = sdo_mod.upload(c.core, node, index, sub, timeout_ms / 1000.0)
            res.update(success=True, data=hex_bytes(data), size=len(data))
    except sdo_mod.SdoTimeout:
        res.update(success=False, error="timeout")
    except sdo_mod.SdoAbort as e:
        res.update(success=False, abort_code=e.code, abort_code_hex="0x%08X" % e.code,
                   error=str(e) if str(e) != "abort 0x%08X" % e.code else abort_text(e.code))
    return res


def _nmt(c, f):
    node = _int(f.get("node"), "node", 1, 127)
    command = f.get("command")
    if command not in NMT_CODES:
        raise DiagError("refused", "field 'command' must be one of " + ", ".join(NMT_COMMANDS))
    c.core.transmit(core_mod.NMT_COB, bytes([NMT_CODES[command], node]))
    return {"node": node, "command": command,
            "note": "sent once; no master holds the node in this state" if command in ("stop", "preop") else ""}


# -- scan ----------------------------------------------------------------------


def _scan_one(core, e):
    try:
        v = sdo_mod.upload(core, e["id"], 0x1018, 1, SCAN_PROBE_S)
    except (sdo_mod.SdoTimeout, sdo_mod.SdoAbort):
        e["done"] = True
        return
    e["answered"] = True
    e["values"]["vendor_id"] = int.from_bytes(v[:4].ljust(4, b"\0"), "little")
    for key, idx, sub in (("product_code", 0x1018, 2), ("revision_number", 0x1018, 3),
                          ("serial_number", 0x1018, 4), ("device_type", 0x1000, 0)):
        try:
            v = sdo_mod.upload(core, e["id"], idx, sub, SCAN_READ_S)
            e["values"][key] = int.from_bytes(v[:4].ljust(4, b"\0"), "little")
        except (sdo_mod.SdoTimeout, sdo_mod.SdoAbort):
            pass
    try:
        e["name"] = sdo_mod.upload(core, e["id"], 0x1008, 0, SCAN_READ_S).rstrip(b"\0").decode("latin-1")
    except (sdo_mod.SdoTimeout, sdo_mod.SdoAbort):
        pass
    e["done"] = True


def _scan_run(core, job):
    queue_ = list(job["entries"])
    lock = threading.Lock()

    def worker():
        while True:
            with lock:
                if not queue_:
                    return
                e = queue_.pop(0)
            try:
                _scan_one(core, e)
            except Exception:
                e["done"] = True

    threads = [threading.Thread(target=worker, daemon=True) for _ in range(SCAN_PARALLEL)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    job["seconds"] = time.monotonic() - job["started"]
    job["finished_at"] = core_mod.iso(time.time())
    job["running"] = False


def _match(c, e):
    cfg = c.config.get(e["id"])
    if cfg is None:
        return "not configured", ""
    if not e.get("answered"):
        return "configured, no answer", ""
    expect = cfg.get("expect") or {}
    labels = (("vendor_id", "vendor ID"), ("product_code", "product code"), ("revision_number", "revision number"),
              ("serial_number", "serial number"))
    for key, label in labels:
        if expect.get(key) and key in e["values"] and e["values"][key] != expect[key]:
            return "configured, different device", "%s 0x%08X, expected 0x%08X" % (label, e["values"][key],
                                                                                    expect[key])
    return "configured", ""


def _scan(c, f, start=True):
    sh = _shared_of(c.core)
    with sh.lock:
        job = sh.scan
        if start and not (job and job["running"]):
            job = {"running": True, "started": time.monotonic(),
                   "entries": [{"id": n, "values": {}, "done": False} for n in range(1, 128)]}
            sh.scan = job
            threading.Thread(target=_scan_run, args=(c.core, job), daemon=True).start()
    res = {"running": bool(job and job["running"])}
    if not job:
        return dict(res, done=0, total=0)
    res["done"] = sum(1 for e in job["entries"] if e["done"])
    res["total"] = len(job["entries"])
    if not job["running"]:
        res.update(finished_at=job["finished_at"], seconds=job["seconds"],
                   note="devices in STOPPED do not answer SDO and are not found")
        nodes = []
        for e in job["entries"]:
            if not e.get("answered") and e["id"] not in c.config:
                continue
            o = {"node_id": e["id"]}
            o.update(e["values"])
            if "name" in e:
                o["device_name"] = e["name"]
            if e["id"] in c.config:
                o["name"] = c.config[e["id"]].get("name") or ""
            o["match"], differs = _match(c, e)
            if differs:
                o["differs"] = differs
            nodes.append(o)
        res["nodes"] = nodes
    return res


# -- LSS -------------------------------------------------------------------------


def _address(f):
    return tuple(_int(f.get(k), k, 0, 0xFFFFFFFF) for k in LSS_KEYS)


def _address_text(a):
    return "vendor 0x%08X, product 0x%08X, revision 0x%08X, serial 0x%08X" % tuple(a)


def _lss_begin(c, f):
    c._check_master(f)
    sh = _shared_of(c.core)
    with sh.lock:
        if sh.lss_busy:
            raise DiagError("refused", "LSS busy")
        sh.lss_busy = True
    return sh


def _lss_end(c, sh):
    try:
        lss_mod.switch_global(c.core, False)  # every device back to waiting
    finally:
        with sh.lock:
            sh.lss_busy = False


def _find_run(c, sh, job, vendor, product):
    try:
        addr = lss_mod.fastscan(c.core, vendor, product)
        if addr:
            job["device"] = dict(zip(LSS_KEYS, addr))
            try:
                job["device"]["node_id"] = lss_mod.inquire_node_id(c.core)
            except lss_mod.LssError:
                pass
            job["found"] = True
    except Exception as e:
        job["error"] = str(e)
    finally:
        job["seconds"] = time.monotonic() - job["started"]
        try:
            _lss_end(c, sh)
        except Exception:
            pass
        job["running"] = False


def _lss_find(c, f, start=True):
    sh = _shared_of(c.core)
    with sh.lock:
        job = sh.find
        running = bool(job and job["running"])
    if start and not running:
        vendor = product = None
        if f.get("vendor_id") is not None and f.get("product_code") is not None:
            vendor = _int(f.get("vendor_id"), "vendor_id", 0, 0xFFFFFFFF)
            product = _int(f.get("product_code"), "product_code", 0, 0xFFFFFFFF)
        _lss_begin(c, f)
        job = {"running": True, "started": time.monotonic(), "found": False}
        with sh.lock:
            sh.find = job
        threading.Thread(target=_find_run, args=(c, sh, job, vendor, product), daemon=True).start()
    res = {"running": bool(job and job["running"])}
    if job and job["running"]:
        res["seconds"] = time.monotonic() - job["started"]
    elif job:
        res.update(seconds=job["seconds"], found=job["found"])
        if job.get("error"):
            res["error"] = job["error"]
        if job.get("device"):
            res["device"] = dict(job["device"])
    return res


def _lss_addressed(c, f, op):
    address = _address(f)
    node = None
    if op == "lss_set_id":
        node = _int(f.get("node"), "node", 1, 127)
        with c.core.lock:
            heard = c.core.heard.get(node)
        if heard and not c._force(f):
            raise DiagError("refused", "node ID %d is in use: node %d was heard on the bus %.0f s ago "
                                       "(--force sets it anyway)" % (node, node, time.monotonic() - heard["at"]))
    if op == "lss_set_bitrate":
        kbit = f.get("bitrate_kbit")
        if kbit not in LSS_BITRATES:
            raise DiagError("refused", "field 'bitrate_kbit' must be one of " + ", ".join(map(str, LSS_BITRATES)))
    store = f.get("store") is True
    sh = _lss_begin(c, f)
    try:
        try:
            lss_mod.switch_selective(c.core, address)
        except lss_mod.LssError as e:
            if e.timed_out:
                raise DiagError("refused", "not found: no device with %s answered" % _address_text(address))
            raise DiagError("refused", "LSS switch selective failed: %s" % e)
        try:
            prev = lss_mod.inquire_node_id(c.core)
        except lss_mod.LssError as e:
            raise DiagError("refused", str(e))
        if op == "lss_inquire":
            return {"node_id": prev, "configured": prev != 0xFF}
        try:
            if op == "lss_set_id":
                lss_mod.configure_node_id(c.core, node)
                had = prev != 0xFF
                res = {"node_id": node, "previous_node_id": prev, "had_node_id": had,
                       "note": "the device had another node ID; the new one becomes active after its next "
                               "communication reset or power cycle" if had else
                               "the device had no node ID and starts with the new one now"}
            else:
                lss_mod.configure_bit_timing(c.core, kbit)
                res = {"bitrate_kbit": kbit,
                       "note": "the device uses the new bit rate after its next power cycle; change the "
                               "adapter's bit rate to match"}
        except lss_mod.LssError as e:
            raise DiagError("refused", str(e))
        if store:
            try:
                lss_mod.store(c.core)
            except lss_mod.LssError as e:
                raise DiagError("refused", "set, but %s" % e)
        res["stored"] = store
        return res
    finally:
        _lss_end(c, sh)


# -- trace ---------------------------------------------------------------------------


def _trace_start(c, f):
    filters = []
    for item in f.get("filters") or []:
        if not isinstance(item, dict):
            raise DiagError("refused", "field 'filters' must be a list of {id, mask}")
        filters.append((_int(item.get("id"), "id", 0, 0x1FFFFFFF), _int(item.get("mask", 0x1FFFFFFF), "mask", 0,
                                                                          0x1FFFFFFF)))
    if len(filters) > 16:
        raise DiagError("refused", "at most 16 filters")
    if c.trace_after is None:
        c.trace_after = c.core.trace_add()
    c.trace_filters, c.trace_errors = filters, f.get("error_frames") is True
    return {"next": c.trace_after, "buffer_frames": core_mod.TRACE_FRAMES, "record_size": 24,
            "network": c.network or "", "interface": str(c.spec), "bitrate": c.core.bitrate}


def _trace_fetch(c, f):
    if c.trace_after is None:
        raise DiagError("refused", "no trace running")
    after = _int(f.get("after", c.trace_after), "after", 0, 2 ** 63)
    limit = _int(f.get("max", 2000), "max", 1, TRACE_MAX)
    recs, nxt, more, lost = c.core.trace_read(after, limit, c.trace_filters, c.trace_errors)
    c.trace_after = nxt
    return {"count": len(recs), "next": nxt, "more": more, "lost": lost, "kernel_drops": 0, "session": True,
            "frames": base64.b64encode(b"".join(recs)).decode("ascii")}


def _trace_stop(c, f):
    if c.trace_after is not None:
        c.core.trace_remove()
        c.trace_after = None
    return {}


OPS = {
    "hello": _hello,
    "status": _status,
    "emcy": _emcy,
    "sdo_read": lambda c, f: _sdo(c, f, False),
    "sdo_write": lambda c, f: _sdo(c, f, True),
    "nmt": _nmt,
    "scan": lambda c, f: _scan(c, f, True),
    "scan_status": lambda c, f: _scan(c, f, False),
    "lss_find": lambda c, f: _lss_find(c, f, True),
    "lss_find_status": lambda c, f: _lss_find(c, f, False),
    "lss_inquire": lambda c, f: _lss_addressed(c, f, "lss_inquire"),
    "lss_set_id": lambda c, f: _lss_addressed(c, f, "lss_set_id"),
    "lss_set_bitrate": lambda c, f: _lss_addressed(c, f, "lss_set_bitrate"),
    "trace_start": _trace_start,
    "trace_fetch": _trace_fetch,
    "trace_stop": _trace_stop,
}
