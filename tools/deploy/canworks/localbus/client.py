"""LocalBus: the diagnostics operations served by a CAN adapter on this PC,
with diag.Client's interface (canopen-local-bus). Everything built on
diag.Client (the CLI, the configurator's online pages, device parameters,
traces) works on it unchanged.

Operations come from one table (OPS). An operation the table lacks answers
"not available on a local adapter". Raw frames (send_frame) send through
Core.transmit like every other operation; bit rate detection closes the
shared adapter, sweeps listen-only (sweep.py) and opens it again.
"""

import base64
import threading
import time

from .. import __version__
from .. import bitrate as bitrate_mod
from ..diag import DiagError, FORCE_NEEDED, LSS_BITRATES, LSS_KEYS, NMT_COMMANDS, PROTOCOL, hex_bytes, parse_hex, \
    abort_text
from . import adapter as adapter_mod
from . import core as core_mod
from . import lss as lss_mod
from . import pdo as pdo_mod
from . import sdo as sdo_mod
from . import sweep as sweep_mod

NMT_CODES = {"start": 0x01, "stop": 0x02, "preop": 0x80, "reset": 0x81, "reset-comm": 0x82}
SCAN_PARALLEL = 8
SCAN_PROBE_S = 0.1
SCAN_READ_S = 0.2
TRACE_MAX = 4000
CHANGES = ("sdo_write", "nmt", "lss_find", "lss_inquire", "lss_set_id", "lss_set_bitrate", "send_frame",
           "pdo_test_start", "pdo_test_set", "sync_start", "detect_bitrate_stop")
NOT_LOCAL = "not available on a local adapter"
# Raw frames, with the plugin's limits.
SEND_RATE = 50  # single frames per second per handle
PERIOD_MS = (10, 60000)
MAX_JOBS = 8  # cyclic jobs per adapter
JOB_LIMIT_S = 600.0
ENDED_KEEP_S = 60.0
OPERATIONAL_S = 30.0  # a node counts as OPERATIONAL this long after a heartbeat saying so
SWEEP_OPS = ("detect_bitrate", "detect_bitrate_status", "detect_bitrate_stop")
MAX_SWEEP_MS = 120000  # listening time per rate times rates times rounds, as the plugin


def _int(v, what, lo, hi):
    try:
        n = int(str(v), 0) if isinstance(v, str) else int(v)
    except (TypeError, ValueError):
        raise DiagError("refused", "field '%s' must be a number" % what)
    if isinstance(v, bool) or not lo <= n <= hi:
        raise DiagError("refused", "field '%s' must be %d-%d" % (what, lo, hi))
    return n


class _Shared:
    """Per adapter (Core) state the handles share: the scan and LSS jobs, and
    the cyclic raw frame jobs (each owned by the handle that started it)."""

    def __init__(self):
        self.lock = threading.Lock()
        self.scan = None  # {"running", "entries", "started", ...}
        self.lss_busy = False
        self.find = None
        self.jobs = []  # running cyclic jobs
        self.ended = []  # ended ones, kept ENDED_KEEP_S for send_frame_stop
        self.next_job = 1
        self.cond = threading.Condition(self.lock)
        self.sender = None  # the thread that sends the cyclic jobs


_shared = {}
_shared_lock = threading.Lock()


def _shared_of(core):
    with _shared_lock:
        return _shared.setdefault(id(core), _Shared())


class LocalBus:
    """One handle on a local adapter. `spec` is an adapter.Spec, `bitrate`
    in bit/s. `config` optionally names configured nodes: {node_id: {"name",
    "expect": {vendor_id, product_code, revision_number, serial_number}}}.
    `allow_changes` is the session switch; `force` is the session's --force: LSS
    while another master is active, and sdo_write, nmt and scan while a node
    is OPERATIONAL."""

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
        self.tokens, self.tokens_at = float(SEND_RATE), time.monotonic()  # single frame rate limit
        self.sweep = None  # the last bit rate sweep of this handle
        self.reopen_error = None  # the adapter could not be opened again after a sweep

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
        sweep, self.sweep = self.sweep, None
        if sweep is not None and sweep.running:
            sweep.stop()  # its on_end sees self.sweep gone and does not open the adapter again
        core, self.core = self.core, None
        if core is not None:
            _end_jobs(core, self, "client disconnected")
            pdo_mod.end_owner(core, self)
            if self.trace_after is not None:
                core.trace_remove()
            core_mod.release(core)
        self.trace_after = None
        self.reopen_error = None

    def request(self, op, timeout=None, **fields):
        fn = OPS.get(op)
        sweep = self.sweep
        if sweep is not None and (sweep.running or op == "detect_bitrate_status"):
            # The adapter is closed for the sweep: only the sweep and status answer.
            if op in SWEEP_OPS:
                return fn(self, fields)
            if op == "status":
                return _sweep_status(self)
            if fn is not None:
                raise DiagError("refused", "no bus")
        if self.core is None:
            raise DiagError("eof", self.reopen_error or "not connected to %s" % self.where)
        if self.core.error:
            raise DiagError("eof", self.core.error)
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

    def sdo_write(self, node, index, subindex, data, timeout_ms=1000, force=None):
        return self.request("sdo_write", node=node, index=index, subindex=subindex, data=hex_bytes(data),
                            timeout_ms=timeout_ms, **({"force": True} if force else {}))

    def nmt(self, node, command, force=None):
        return self.request("nmt", node=node, command=command, **({"force": True} if force else {}))

    def scan(self, start=True, force=None):
        if not start:
            return self.request("scan_status")
        return self.request("scan", **({"force": True} if force else {}))

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

    def send_frame(self, can_id, data=b"", ext=False, rtr=False, dlc=None, period_ms=None, count=None, force=False):
        fields = {"can_id": can_id, "ext": bool(ext), "rtr": bool(rtr)}
        if rtr:
            fields["dlc"] = dlc or 0
        elif data:
            fields["data"] = hex_bytes(data)
        if period_ms:
            fields["period_ms"] = period_ms
            if count:
                fields["count"] = count
        if force:
            fields["force"] = True
        return self.request("send_frame", **fields)

    def send_frame_stop(self, job=None):
        return self.request("send_frame_stop", **({} if job is None else {"job": job}))

    def detect_bitrate(self, rates=None, per_rate_ms=None, rounds=None, force=False, disturb_bus=False,
                       lone_device=False, probe=None):
        fields = {}
        if lone_device:
            fields["lone_device"] = True
        if probe:
            fields["probe"] = probe
        if rates:
            fields["rates"] = list(rates)
        if per_rate_ms:
            fields["per_rate_ms"] = per_rate_ms
        if rounds:
            fields["rounds"] = rounds
        if force:
            fields["force"] = True
        if disturb_bus:
            fields["disturb_bus"] = True
        return self.request("detect_bitrate", **fields)

    def detect_bitrate_status(self):
        return self.request("detect_bitrate_status")

    def detect_bitrate_stop(self):
        return self.request("detect_bitrate_stop")

    def pdo_test_start(self, node, layout, force=False):
        return self.request("pdo_test_start", node=node, layout=layout, **({"force": True} if force else {}))

    def pdo_test_status(self, node):
        return self.request("pdo_test_status", node=node)

    def pdo_test_set(self, node, rpdo, values, repeat_ms=None):
        fields = {"node": node, "rpdo": rpdo, "values": values}
        if repeat_ms is not None:
            fields["repeat_ms"] = repeat_ms
        return self.request("pdo_test_set", **fields)

    def pdo_test_stop(self, node=None):
        return self.request("pdo_test_stop", **({} if node is None else {"node": node}))

    def sync_start(self, period_ms, counter=0, cob_id=None, force=False):
        fields = {"period_ms": period_ms, "counter": counter}
        if cob_id is not None:
            fields["cob_id"] = cob_id
        if force:
            fields["force"] = True
        return self.request("sync_start", **fields)

    def sync_stop(self):
        return self.request("sync_stop")

    # -- helpers ------------------------------------------------------------------
    def _network(self):
        return {"name": self.network or "", "interface": str(self.spec), "bitrate": self.core.bitrate,
                "role": "local", "master_node_id": None}

    def _force(self, fields):
        return self.force or fields.get("force") is True

    def _check_master(self, fields):
        self.core.wait_listened()
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
    core.wait_listened()
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
            "other_master_seen": other, "nodes": nodes, "send_jobs": _job_list(core),
            "bitrate_sweep": {"running": False}}


def _sweep_status(c):
    """status while a bit rate sweep has the adapter: nothing heard, no jobs."""
    return {"local": True, "version": __version__, "uptime_s": None, "adapter": str(c.spec), "bitrate": c.bitrate,
            "network": c.network or "", "untested_adapter": adapter_mod.untested(c.spec),
            "allow_changes": c.allow_changes, "session": False, "bus": {"interface": str(c.spec), "state": None},
            "master": None, "other_master": False, "other_master_seen": None, "nodes": [], "send_jobs": [],
            "bitrate_sweep": {"running": True}}


def _emcy(c, f):
    node = _int(f.get("node"), "node", 1, 127)
    with c.core.lock:
        e = c.core.emcy.get(node)
        hist = list(e["history"]) if e else []
    return {"node_id": node, "emcy": hist}


def _running(c, node):
    """The label of `node` when it was heard OPERATIONAL lately, else ''."""
    now = time.monotonic()
    with c.core.lock:
        h = c.core.heard.get(node)
        on = bool(h and h["state"] == 5 and now - h["at"] <= OPERATIONAL_S)
    return _label(c, node) if on else ""


def _check_force(c, f, what, node=None):
    """The plugin's rule: changes to an OPERATIONAL node, and a scan while a
    node is OPERATIONAL, need force (--force, or force: true)."""
    if "force" in f and not isinstance(f["force"], bool):
        raise DiagError("refused", "field 'force' must be true or false")
    if c._force(f):
        return
    # The heartbeats heard while the adapter listens tell which node is
    # OPERATIONAL; the transmit would wait as long anyway.
    c.core.wait_listened()
    if node is not None:
        busy = _running(c, node)
    else:
        now = time.monotonic()
        with c.core.lock:
            heard = sorted(n for n, h in c.core.heard.items() if h["state"] == 5 and now - h["at"] <= OPERATIONAL_S)
        busy = _label(c, heard[0]) if heard else ""
    if busy:
        raise DiagError("refused", "%s is OPERATIONAL; %s; %s" % (busy, what, FORCE_NEEDED))


def _sdo(c, f, write):
    node = _int(f.get("node"), "node", 1, 127)
    if write:
        _check_force(c, f, "an SDO write changes it while the program drives it", node)
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
    if command != "start":
        _check_force(c, f, "an NMT command takes it out of the program's control", node)
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
        running = bool(sh.scan and sh.scan["running"])
    if start and not running:
        _check_force(c, f, "a scan sends SDO requests to every node ID")
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


# -- raw frames ------------------------------------------------------------------------


def _label(c, node):
    name = (c.config.get(node) or {}).get("name")
    return "node %d (%s)" % (node, name) if name else "node %d" % node


def cob_id_use(c, can_id, ext):
    """What `can_id` is on this bus, or '': the services every CANopen bus has
    (NMT, SYNC, TIME, LSS), and with a config the predefined EMCY, PDO, SDO
    and heartbeat COB-IDs of its nodes. Extended identifiers are never used."""
    if ext:
        return ""
    fixed = {core_mod.NMT_COB: "NMT", core_mod.SYNC_COB: "SYNC", core_mod.TIME_COB: "TIME",
             core_mod.LSS_RX_COB: "LSS", core_mod.LSS_TX_COB: "LSS"}
    if can_id in fixed:
        return fixed[can_id]
    for node in sorted(c.config):
        who = " of " + _label(c, node)
        if can_id == 0x80 + node:
            return "EMCY" + who
        for k in range(4):
            if can_id == 0x180 + 0x100 * k + node:
                return "TPDO%d%s (predefined)" % (k + 1, who)
            if can_id == 0x200 + 0x100 * k + node:
                return "RPDO%d%s (predefined)" % (k + 1, who)
        if can_id == 0x580 + node:
            return "the SDO response channel" + who
        if can_id == 0x600 + node:
            return "the SDO request channel" + who
        if can_id == 0x700 + node:
            return "the heartbeat" + who
    return ""


def _force_reason(c, can_id, ext):
    """Why a frame needs force, or '' (the plugin's guard, design D9)."""
    use = cob_id_use(c, can_id, ext)
    if use:
        return "0x%s is %s%s" % ("%08X" % can_id if ext else "%03X" % can_id, use,
                                 " on network " + c.network if c.network else "")
    c.core.wait_listened()
    other = c.core.other_master()
    if other:
        return "another master is active on this bus (%s, last at %s)" % (other["what"], other["last_at"])
    now = time.monotonic()
    with c.core.lock:
        running = sorted(n for n, h in c.core.heard.items() if h["state"] == 5 and now - h["at"] <= OPERATIONAL_S)
    if running:
        return "%s is OPERATIONAL" % _label(c, running[0])
    return ""


def _take_token(c):
    now = time.monotonic()
    c.tokens = min(float(SEND_RATE), c.tokens + (now - c.tokens_at) * SEND_RATE)
    c.tokens_at = now
    if c.tokens < 1:
        return False
    c.tokens -= 1
    return True


def _frame(f):
    """The fields of send_frame, checked as the plugin checks them."""
    for key in ("ext", "rtr", "force"):
        if key in f and not isinstance(f[key], bool):
            raise DiagError("refused", "field '%s' must be true or false" % key)
    ext, rtr = f.get("ext") is True, f.get("rtr") is True
    can_id = _int(f.get("can_id"), "can_id", 0, 0x1FFFFFFF if ext else 0x7FF)
    data, dlc = b"", 0
    if rtr:
        if "data" in f:
            raise DiagError("refused", "a remote frame has no data (give 'dlc')")
        if "dlc" in f:
            dlc = _int(f.get("dlc"), "dlc", 0, 8)
    else:
        if "data" in f:
            try:
                if not isinstance(f["data"], str):
                    raise ValueError
                data = parse_hex(f["data"])
            except ValueError:
                raise DiagError("refused", "field 'data' must be hexadecimal bytes such as \"40 18 10 01\"")
        if len(data) > 8:
            raise DiagError("refused", "a CAN frame carries at most 8 data bytes")
        dlc = len(data)
    period, count = 0, None
    if "period_ms" in f:
        try:
            period = _int(f.get("period_ms"), "period_ms", 0, PERIOD_MS[1])
            if period and period < PERIOD_MS[0]:
                raise DiagError("refused", "")
        except DiagError:
            raise DiagError("refused", "field 'period_ms' must be 0 (one frame) or %d-%d" % PERIOD_MS)
    if "count" in f:
        if not period:
            raise DiagError("refused", "field 'count' needs 'period_ms'")
        count = _int(f.get("count"), "count", 1, 1000000)
    return {"id": can_id, "ext": ext, "rtr": rtr, "dlc": dlc, "data": data, "period_ms": period, "count": count}


def _transmit(core, fr):
    core.transmit(fr["id"], fr["data"], fr["ext"], fr["rtr"], fr["dlc"])


def _prune(sh, now):
    sh.ended = [j for j in sh.ended if now - j["ended"] < ENDED_KEEP_S]


def _end(sh, j, reason):
    """Under sh.lock: the job ends with `reason`."""
    if j in sh.jobs:
        sh.jobs.remove(j)
        j.update(reason=reason, ended=time.monotonic())
        if reason != "client disconnected":  # nobody can ask about a closed handle's jobs
            sh.ended.append(j)
        sh.cond.notify_all()


def _end_jobs(core, owner, reason):
    """Ends the cyclic jobs on `core` (of `owner`, or all)."""
    sh = _shared_of(core)
    with sh.lock:
        for j in list(sh.jobs):
            if owner is None or j["owner"] is owner:
                _end(sh, j, reason)
        if reason == "client disconnected":
            sh.ended = [j for j in sh.ended if j["owner"] is not owner]


def _job_list(core):
    sh = _shared_of(core)
    with sh.lock:
        return [{"job": j["job"], "id": j["frame"]["id"], "ext": j["frame"]["ext"], "period_ms": j["period_ms"],
                 "sent": j["sent"], "count": j["count"], "peer": j["peer"]} for j in sh.jobs]


def _send_jobs(core, sh):
    """The thread that sends the cyclic jobs of one adapter, each on its own
    monotonic deadline; it ends when no job is left."""
    while True:
        with sh.lock:
            if not sh.jobs:
                sh.sender = None
                return
            now = time.monotonic()
            due = [j for j in sh.jobs if j["next"] <= now]
            if not due:
                sh.cond.wait(min(j["next"] for j in sh.jobs) - now)
                continue
        for j in due:
            reason = None
            if now - j["started"] >= JOB_LIMIT_S:
                reason = "time limit"
            else:
                try:
                    _transmit(core, j["frame"])
                except adapter_mod.AdapterError as e:
                    reason = "cannot send: %s" % e
            with sh.lock:
                if j not in sh.jobs:
                    continue  # stopped meanwhile
                if reason is None:
                    j["sent"] += 1
                    if j["count"] and j["sent"] >= j["count"]:
                        reason = "count reached"
                if reason:
                    _end(sh, j, reason)
                    continue
                j["next"] += j["period_ms"] / 1000.0
                if j["next"] < now:  # behind by more than a period: no burst to catch up
                    j["next"] = now + j["period_ms"] / 1000.0


def _send_frame(c, f):
    fr = _frame(f)
    reason = _force_reason(c, fr["id"], fr["ext"])
    if reason and not c._force(f):
        raise DiagError("refused", "%s; %s" % (reason, FORCE_NEEDED))
    if not fr["period_ms"]:
        if not _take_token(c):
            raise DiagError("refused", "rate limit")
        try:
            _transmit(c.core, fr)
        except adapter_mod.AdapterError as e:
            raise DiagError("refused", "cannot send: %s" % e)
        return {"sent": True}
    sh = _shared_of(c.core)
    with sh.lock:
        if len(sh.jobs) >= MAX_JOBS:
            raise DiagError("refused", "too many jobs (at most %d per adapter)" % MAX_JOBS)
        now = time.monotonic()
        j = {"job": sh.next_job, "owner": c, "peer": "this PC", "frame": fr, "period_ms": fr["period_ms"],
             "count": fr["count"], "sent": 0, "started": now, "next": now, "forced": bool(reason)}
        sh.next_job += 1
        sh.jobs.append(j)
        if sh.sender is None:
            sh.sender = threading.Thread(target=_send_jobs, args=(c.core, sh), name="canopen-localbus-send",
                                         daemon=True)
            sh.sender.start()
        sh.cond.notify_all()
    return {"job": j["job"], "period_ms": j["period_ms"], "count": j["count"]}


def _send_frame_stop(c, f):
    job = _int(f.get("job"), "job", 1, 2 ** 53) if f.get("job") is not None else None
    sh = _shared_of(c.core)
    out = []
    with sh.lock:
        found = False
        for j in list(sh.jobs):
            if j["owner"] is c and (job is None or j["job"] == job):
                _end(sh, j, "stopped")
                found = True
        _prune(sh, time.monotonic())
        for j in list(sh.ended):
            if j["owner"] is c and (job is None or j["job"] == job):
                found = True
                out.append({"job": j["job"], "id": j["frame"]["id"], "period_ms": j["period_ms"], "sent": j["sent"],
                            "reason": j["reason"]})
                sh.ended.remove(j)
    if job is not None and not found:
        raise DiagError("refused", "no job %d of this connection" % job)
    return {"stopped": out}


# -- bit rate detection -------------------------------------------------------------------


def _detect(c, f):
    if c.sweep is not None and c.sweep.running:
        return c.sweep.status()  # the running sweep's progress
    for key in ("force", "disturb_bus"):
        if key in f and not isinstance(f[key], bool):
            raise DiagError("refused", "field '%s' must be true or false" % key)
    rates = f.get("rates")
    if rates is not None:
        if not isinstance(rates, list) or not rates or any(
                isinstance(r, bool) or r not in bitrate_mod.RATES for r in rates):
            raise DiagError("refused", "field 'rates' takes %s" % ", ".join(str(r) for r in bitrate_mod.RATES))
        rates = list(dict.fromkeys(rates))
    try:
        per_rate_ms = _int(f.get("per_rate_ms", 1000), "per_rate_ms", 100, 10000)
    except DiagError:
        raise DiagError("refused", "field 'per_rate_ms' must be 100-10000")
    rounds = _int(f.get("rounds", 1), "rounds", 1, 20)
    total_ms = per_rate_ms * len(rates or bitrate_mod.RATES) * rounds
    if total_ms > MAX_SWEEP_MS:
        raise DiagError("refused", "the sweep would listen %d s; per_rate_ms times rates times rounds may be at most "
                                   "%d s" % (total_ms // 1000, MAX_SWEEP_MS // 1000))
    lone, probe = _lone_fields(c, f)
    if not lone and c.spec.kind not in adapter_mod.LISTEN_ONLY:
        # Refused before the adapter is closed for the sweep: closing and
        # reopening a gs_usb adapter at once can leave it deaf on macOS.
        raise DiagError("refused", "%s (%s adapters; slcan, PCAN and SocketCAN have one); with only one device "
                                   "on the bus, use the lone-device sweep" % (adapter_mod.NO_LISTEN_ONLY, c.spec.kind))
    # Listen-only sends nothing, so neither allow-changes nor force; but the
    # adapter is closed for it, so no other view may be using it.
    core = c.core
    try:
        core_mod.take_alone(core, lambda: (_end_jobs(core, None, "bit rate detection"),
                                           pdo_mod.end_owner(core, c, "bit rate detection")))
    except adapter_mod.AdapterError as e:
        raise DiagError("refused", str(e))
    c.reopen_error = None
    tracing = c.trace_after is not None
    c.core, c.trace_after = None, None
    sweep = sweep_mod.Sweep(c.spec, rates, per_rate_ms, rounds, configured_kbit=core.bitrate // 1000,
                            disturb_bus=f.get("disturb_bus") is True, lone_device=lone, probe=probe)

    def reopen():
        if c.sweep is not sweep:
            return ""  # the handle was closed meanwhile
        try:
            c.core = core_mod.acquire(c.spec, c.bitrate, core_mod.LISTEN_S if c.listen_s is None else c.listen_s)
        except adapter_mod.AdapterError as e:
            c.reopen_error = "adapter %s could not be opened again after bit rate detection: %s" % (c.spec, e)
            return c.reopen_error
        if tracing:
            c.trace_after = c.core.trace_add()
        return ""

    c.sweep = sweep
    try:
        sweep.start(on_end=reopen)
    except adapter_mod.AdapterError as e:
        reopen()
        c.sweep = None
        raise DiagError("refused", str(e))
    return sweep.status()


def _lone_fields(c, f):
    """(lone_device, probe) of a detect_bitrate request, after the lone-device
    sweep's guards: it joins the bus at every rate, so it needs allow-changes
    and a bus where only the one device was heard."""
    if "lone_device" in f and not isinstance(f["lone_device"], bool):
        raise DiagError("refused", "field 'lone_device' must be true or false")
    lone = f.get("lone_device") is True
    probe = f.get("probe")
    if probe is not None:
        if not lone:
            raise DiagError("refused", "field 'probe' needs 'lone_device'")
        if isinstance(probe, dict) and set(probe) == {"sdo"}:
            probe = {"sdo": _int(probe.get("sdo"), "probe.sdo", 1, 127)}
        elif probe != "lss":
            raise DiagError("refused", "field 'probe' must be \"lss\" or {\"sdo\": NODE}")
    if not lone:
        return False, None
    if not c.allow_changes:
        raise DiagError("refused", "changes not allowed (the lone-device sweep joins the bus at every rate; start "
                                   "with --allow-changes)")
    c.core.wait_listened()
    other = c.core.other_master()
    if other:
        raise DiagError("refused", "another master is active on this bus (%s, last at %s): the lone-device sweep "
                                   "is for a bench with one device" % (other["what"], other["last_at"]))
    now = time.monotonic()
    with c.core.lock:
        heard = sorted(n for n, h in c.core.heard.items() if now - h["at"] <= OPERATIONAL_S)
    if len(heard) > 1:
        raise DiagError("refused", "more than one node is on the bus (heard nodes %s in the last %d s): the "
                                   "lone-device sweep is for a bench with one device"
                                   % (", ".join(str(n) for n in heard), OPERATIONAL_S))
    return True, probe


def _detect_stop(c, f):
    if c.sweep is None or not c.sweep.running:
        raise DiagError("refused", "no bit rate detection is running on %s" % c.where)
    c.sweep.stop()
    return c.sweep.status()


def _detect_status(c, f):
    if c.sweep is None:
        return sweep_mod.idle_status(c.bitrate // 1000)
    return c.sweep.status()


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
    "send_frame": _send_frame,
    "send_frame_stop": _send_frame_stop,
    "detect_bitrate": _detect,
    "detect_bitrate_status": _detect_status,
    "detect_bitrate_stop": _detect_stop,
    "pdo_test_start": pdo_mod.start,
    "pdo_test_status": pdo_mod.status,
    "pdo_test_set": pdo_mod.set_values,
    "pdo_test_stop": pdo_mod.stop,
    "sync_start": pdo_mod.sync_start,
    "sync_stop": pdo_mod.sync_stop,
}
