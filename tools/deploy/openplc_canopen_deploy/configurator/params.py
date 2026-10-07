"""Device parameters in the configurator (canopen-device-parameters): the
object dictionary view, backup, compare, restore and store.

The long operations (read all, backup, compare, the restore plan and the
restore) run as background jobs in the server, so a page reload does not lose
a running restore and its hold release still runs. One job runs at a time; the
last few finished ones are kept for the page to pick up.
"""

import base64
import collections
import itertools
import os
import threading
import time

from .. import contract, dbcexport, diag
from .. import parameters as P

KEEP = 10  # finished jobs kept
MAX_KEYS = 64  # entries per direct read
WATCH_MAX = 32  # entries in a node's watch list
GROUPS = (("communication", 0x1000, 0x1FFF), ("manufacturer", 0x2000, 0x5FFF), ("profile", 0x6000, 0x9FFF))


class Refused(Exception):
    """A request the page made that cannot be done; status and message."""

    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


class Client:
    """The diag.Client methods parameters.py uses, each one call through the
    configurator's kept-open connection (so the page's status polling and a
    job share it, one request at a time)."""

    def __init__(self, conn, host, port, token, network=None):
        self.conn, self.key, self.network = conn, (host, port, token), network

    def _call(self, fn):
        return self.conn.call(*self.key, fn, self.network)

    def sdo_read(self, node, index, sub, timeout_ms=None):
        return self._call(lambda c: c.sdo_read(node, index, sub, timeout_ms))

    def sdo_write(self, node, index, sub, data, timeout_ms=None):
        return self._call(lambda c: c.sdo_write(node, index, sub, data, timeout_ms))

    def nmt(self, node, command):
        return self._call(lambda c: c.nmt(node, command))

    def status(self):
        return self._call(lambda c: c.status())

    @property
    def info(self):
        if self.conn.info is None:
            self._call(lambda c: None)
        return self.conn.info or {}


# -- jobs ----------------------------------------------------------------------------

class Job:
    def __init__(self, id, kind, node):
        self.id, self.kind, self.node = id, kind, node
        self.state = "running"  # running, done, failed, cancelled
        self.phase = "reading"
        self.done = self.total = 0
        self.result = self.error = None
        self.cancel = False
        self.started = time.time()
        self.plan = None  # a restore plan job's Plan, for the restore that follows it

    def progress(self, phase):
        def update(done, total):
            self.phase, self.done, self.total = phase, done, total
        return update

    def to_json(self):
        return {"id": self.id, "kind": self.kind, "node": self.node, "state": self.state, "phase": self.phase,
                "done": self.done, "total": self.total, "result": self.result, "error": self.error,
                "cancel_requested": self.cancel}


class Jobs:
    def __init__(self):
        self.lock = threading.Lock()
        self.jobs = collections.OrderedDict()
        self.ids = itertools.count(1)

    def start(self, kind, node, fn):
        """Runs fn(job) in a thread; its return value is the job's result."""
        with self.lock:
            busy = next((j for j in self.jobs.values() if j.state == "running"), None)
            if busy:
                raise Refused(409, "node %d: %s is still running; wait for it or cancel it" % (busy.node, busy.kind))
            job = Job(next(self.ids), kind, node)
            self.jobs[job.id] = job
            while len(self.jobs) > KEEP:
                self.jobs.popitem(last=False)

        def run():
            try:
                job.result = fn(job)
                job.state = "cancelled" if job.cancel else "done"
            except (diag.DiagError, P.ParameterError, Refused) as e:
                job.error, job.state = str(e), "failed"
            except Exception as e:  # pragma: no cover - shown in the page
                job.error, job.state = "%s: %s" % (type(e).__name__, e), "failed"

        threading.Thread(target=run, daemon=True, name="params-%s-%d" % (kind, job.id)).start()
        return job

    def get(self, job_id=None):
        with self.lock:
            if job_id is None:
                return next(reversed(self.jobs.values()), None)
            return self.jobs.get(job_id)

    def wait(self, job_id, timeout=10.0):
        """For tests: the job once it is no longer running."""
        end = time.monotonic() + timeout
        job = self.get(job_id)
        while job.state == "running" and time.monotonic() < end:
            time.sleep(0.02)
        return job


# -- the node's EDS ------------------------------------------------------------------

def context(session, body, node, library=""):
    """A parameters.NodeContext for a request: from the draft config the page
    sends when the node is in it (in the network the request names, with
    several), else from `eds_path` (an EDS file in the project's canopen
    folder or the EDS library, for a scanned node)."""
    cfg = body.get("config")
    network = None
    nodes = []
    if isinstance(cfg, dict):
        network = (body.get("network") or None) if contract.version_of(cfg) == 2 else None
        ctx = slave_context(session, cfg, network, node)
        if ctx is not None:
            return ctx
        try:
            nodes = contract.network_config(cfg, network)["nodes"] or []
        except ValueError:
            pass  # not in the draft: the scanned node's EDS below
    if nodes:
        for n in nodes:
            if not isinstance(n, dict) or not isinstance(n.get("eds"), str) or not n.get("eds"):
                continue
            try:
                nid = int(str(n.get("node_id")), 0)
            except ValueError:
                continue
            if nid == node:
                with session.lock:
                    eds_paths = session.eds_paths(cfg)
                    config_path = session.config_path
                try:
                    return P.node_context(node, config_path, cfg=cfg, eds_paths=eds_paths, network=network)
                except (OSError, P.ParameterError) as e:
                    raise Refused(422, str(e))
    path = body.get("eds_path")
    if isinstance(path, str) and path:
        with session.lock:
            canopen_dir = session.canopen_dir
            if not os.path.isabs(path):
                path = session.eds_path(path)
        real = os.path.realpath(path)
        roots = [os.path.realpath(r) for r in (canopen_dir, library) if r]
        if not any(real.startswith(r + os.sep) for r in roots) or not os.path.isfile(real):
            raise Refused(403, "only EDS files in the project's canopen folder or the EDS library can be used")
        try:
            ctx = P.node_context(node, eds_path=real)
        except (OSError, P.ParameterError) as e:
            raise Refused(422, str(e))
        ctx.eds_name = os.path.basename(real)
        return ctx
    raise Refused(422, "node %d has no EDS: add it to the configuration, or open it from the scan with its EDS" % node)


def slave_context(session, cfg, network, node):
    """The own device of a slave network as a NodeContext from the slave's
    EDS in the draft, with `slave` set to its bound objects; None when the
    request's network (or the config's only one) is not a slave network.
    The node ID is the runtime's: a slave that waits for LSS has none in the
    config."""
    nets = contract.networks(cfg)
    found = [n for n in nets if n["name"] == network] if network else nets if len(nets) == 1 else []
    if not found or found[0]["role"] != "slave":
        return None
    net = found[0]
    eds = net["slave"].get("eds")
    if not isinstance(eds, str) or not eds:
        raise Refused(422, "the slave network has no EDS yet: build or pick it on the network's page")
    with session.lock:
        path = session.eds_path(eds)
    try:
        ctx = P.node_context(node, eds_path=path)
    except (OSError, P.ParameterError) as e:
        raise Refused(422, str(e))
    ctx.eds_name = eds
    ctx.slave = slave_binds(cfg, net)
    return ctx


def slave_binds(cfg, net):
    """{(index, sub): {"iec_location", "name"} or {"route"}} of a slave
    network in the draft: its bound objects and, on a gateway's upper
    network, the slave ends of the routes."""
    out = {}
    for o in net["slave"].get("objects") or []:
        if not isinstance(o, dict):
            continue
        key = (_node_id(o.get("index")), _node_id(o.get("subindex", 0)))
        if None not in key:
            out[key] = {"iec_location": o.get("iec_location") or "", "name": o.get("name") or ""}
    g = cfg.get("gateway") if isinstance(cfg.get("gateway"), dict) else {}
    if g.get("upper") == net["name"]:
        for i, r in enumerate(g.get("routes") or []):
            end = r.get("slave") if isinstance(r, dict) else None
            if not isinstance(end, dict):
                continue
            key = (_node_id(end.get("index")), _node_id(end.get("subindex", 0)))
            if None not in key:
                out[key] = {"route": r.get("name") or "route %d" % (i + 1)}
    return out


def config_marks(ctx):
    """({(index, sub)}, {(index, sub): SDO variable}) of a configured node:
    what the configuration writes at boot and what SDO variables write.
    A draft that cannot be exported yet gives no marks and a note."""
    if not ctx.configured:
        return set(), {}, None
    try:
        writes, owned = ctx.config_refs()
    except Exception as e:  # dcfexport.ExportFailed and the draft's own problems
        return set(), {}, "boot writes not known: %s" % e
    return set(writes), owned, None


OBJECT_TYPES = {0x7: "VAR", 0x8: "ARRAY", 0x9: "RECORD"}


def pdo_marks(ctx):
    """{(index, sub): [PDO marks]} of a configured node from its PDOs in the
    draft config; {} for a scanned node or a draft whose PDOs cannot be read
    yet (the page's own checks report those)."""
    if not ctx.configured:
        return {}
    node = next((n for n in ctx.cfg.get("nodes") or [] if isinstance(n, dict)
                 and str(n.get("node_id")) and _node_id(n.get("node_id")) == ctx.node_id), None)
    if node is None:
        return {}
    try:
        return dbcexport.pdo_marks(node, ctx.eds)
    except Exception:  # an unfinished draft: no marks rather than no tab
        return {}


def _node_id(v):
    try:
        return int(str(v), 0)
    except ValueError:
        return None


def entries_json(ctx):
    """The node's EDS entries for the object dictionary view, grouped."""
    boot, owned, note = config_marks(ctx)
    defaults = P.reference_from_eds(ctx.eds, ctx.node_id)
    pdo = pdo_marks(ctx)
    binds = getattr(ctx, "slave", None)
    out = []
    for e in P.entries(ctx.eds):
        d = e.to_json(ctx.node_id)
        d["object_type"] = OBJECT_TYPES.get(ctx.eds.object_types.get(e.index, 0x7), "VAR")
        if e.key in pdo:
            d["pdo"] = pdo[e.key]
        d["group"] = next((g for g, lo, hi in GROUPS if lo <= e.index <= hi), "other")
        d["readable"] = e.access in P.READABLE and e.data_type != P.DOMAIN
        d["writable"] = e.access in P.WRITABLE or e.access == "wo"
        d["object"] = ctx.eds.names.get(e.index, "")
        d["default_data"] = defaults[e.key].hex(" ").upper() if e.key in defaults else None
        if e.key in boot:
            d["config"] = True
        if e.key in owned:
            d["sdo_variable"] = owned[e.key] or True
        if binds and e.key in binds:
            d["slave_bind"] = binds[e.key]
        out.append(d)
    return {"node": ctx.node_id, "eds": ctx.eds_name, "configured": ctx.configured, "slave": binds is not None,
            "has_store": ctx.eds.has(0x1010), "store_subindices": [s for s in range(1, 128)
                                                                    if ctx.eds.find(0x1010, s) is not None],
            "entries": out, "note": note}


def keys_arg(body):
    keys = body.get("keys")
    if not isinstance(keys, list) or not keys or len(keys) > MAX_KEYS:
        raise Refused(400, "keys must be a list of 1-%d [index, subindex] pairs" % MAX_KEYS)
    out = []
    for k in keys:
        try:
            index, sub = int(str(k[0]), 0), int(str(k[1]), 0)
        except (TypeError, ValueError, IndexError, KeyError):
            raise Refused(400, "keys must be [index, subindex] pairs")
        if not (0 <= index <= 0xFFFF and 0 <= sub <= 0xFF):
            raise Refused(400, "index must be 0x0000-0xFFFF and subindex 0-255")
        out.append((index, sub))
    return out


def file_arg(body, node):
    data = body.get("file")
    if not isinstance(data, str) or not data:
        raise Refused(400, "choose a backup file")
    try:
        raw = base64.b64decode(data, validate=True)
    except ValueError:
        raise Refused(400, "file must be base64")
    try:
        return P.read_backup(raw, body.get("file_name") or "backup.dcf", node)
    except P.ParameterError as e:
        raise Refused(422, str(e))


# -- the operations --------------------------------------------------------------------

def handle(route, body, session, conn, jobs, client, node, library, host):
    """The /api/online/ parameter routes. `client` is a Client; `node` the
    checked node ID (None for /job)."""
    path = route[1].rsplit("/", 1)[-1]
    if path == "job":
        job = jobs.get(body.get("id") if isinstance(body.get("id"), int) else None)
        if job is None:
            if body.get("id") is not None:
                raise Refused(404, "no such job")
            return {"job": None}
        if body.get("cancel") and job.state == "running":
            job.cancel = True
        return {"job": job.to_json()}

    ctx = context(session, body, node, library)
    if getattr(ctx, "slave", None) is not None and path not in ("od_entries", "od_read"):
        raise Refused(409, "%s needs a master network: a slave network reads and writes only its own dictionary"
                      % path.replace("_", " "))
    if path == "od_entries":
        return entries_json(ctx)
    if path == "od_read":
        if body.get("all"):
            return {"job": jobs.start("read", node, lambda job: P.read_all(
                client, node, ctx.eds, job.progress("reading"), lambda: job.cancel).to_json(P.entries(ctx.eds)))
                .to_json()}
        keys = keys_arg(body)
        timeout = body.get("timeout_ms") if isinstance(body.get("timeout_ms"), int) else P.READ_TIMEOUT_MS
        reading = P.read_entries(client, node, keys, timeout_ms=timeout)
        return reading.to_json(P.entries(ctx.eds))
    if path == "backup":
        def backup(job):
            boot = None
            for nd in client.status().get("nodes") or []:
                if nd.get("node_id") == node and not nd.get("booted"):
                    boot = "not booted"
            reading = P.read_all(client, node, ctx.eds, job.progress("reading"), lambda: job.cancel)
            if job.cancel:
                return None
            text, name = P.build_backup(ctx.eds_text, ctx.eds, ctx.eds_name, reading, ctx.bitrate_kbit, ctx.name,
                                        host, boot_state=boot)
            return {"name": name, "data": base64.b64encode(text.encode("utf-8")).decode("ascii"),
                    "read": len(reading.values), "failed": len(reading.failed), "stopped": reading.stopped,
                    "boot_state": boot, "lint": P.lint_backup(text, ctx.eds_text, node)}
        return {"job": jobs.start("backup", node, backup).to_json()}
    if path == "compare":
        ref_kind = body.get("reference")
        if ref_kind == "file":
            reference, only = file_arg(body, node).values, False
        elif ref_kind == "config":
            if not ctx.configured:
                raise Refused(422, "node %d is not in the configuration" % node)
            try:
                reference, _ = ctx.config_refs()
            except Exception as e:
                raise Refused(422, "the configuration's boot writes are not known: %s" % e)
            only = True
        elif ref_kind == "eds":
            reference, only = P.reference_from_eds(ctx.eds, node), False
        else:
            raise Refused(400, "reference must be file, config or eds")
        include_ro = body.get("read_only") is True

        def compare(job):
            keys = P.compare_keys(ctx.eds, reference, include_ro, only)
            reading = P.read_entries(client, node, keys, job.progress("reading"), lambda: job.cancel)
            rows = P.compare(ctx.eds, reading, reference, include_ro, only)
            return {"rows": rows, "summary": P.summary(rows), "stopped": reading.stopped,
                    "reference": ref_kind}
        return {"job": jobs.start("compare", node, compare).to_json()}
    if path == "restore_plan":
        backup = file_arg(body, node)
        include_comm = body.get("include_comm") is True
        boot, owned, note = config_marks(ctx)
        config = {k: b"" for k in boot}

        def plan(job):
            keys = P.plan_keys(backup, ctx.eds, include_comm, config, owned)
            live = P.read_entries(client, node, keys, job.progress("reading"), lambda: job.cancel)
            if live.stopped:
                raise P.ParameterError(live.stopped)
            if job.cancel:
                return None
            job.plan = P.restore_plan(backup, ctx.eds, live, include_comm, config, owned)
            res = job.plan.to_json()
            res.update(configured=ctx.configured, include_comm=include_comm, note=note,
                       allow_changes=bool(client.info.get("allow_changes")))
            return res
        return {"job": jobs.start("restore_plan", node, plan).to_json()}
    if path == "restore":
        planned = jobs.get(body.get("plan") if isinstance(body.get("plan"), int) else -1)
        if planned is None or planned.kind != "restore_plan" or planned.plan is None or planned.node != node:
            raise Refused(409, "make the restore preview for node %d again" % node)
        if not client.info.get("allow_changes"):
            raise Refused(422, "changes not allowed")
        plan = planned.plan
        if plan.refused:
            if body.get("ignore_identity") is not True:
                raise Refused(422, "restore refused: %s" % plan.refused)
            plan.refused = None
        planned.plan = None  # one restore per preview
        hold = body.get("hold") is True
        return {"job": jobs.start("restore", node, lambda job: P.restore(
            client, node, plan, hold, job.progress("writing"), lambda: job.cancel)).to_json()}
    if path == "store":
        if not client.info.get("allow_changes"):
            raise Refused(422, "changes not allowed")
        sub = body.get("subindex", 1)
        if isinstance(sub, bool) or not isinstance(sub, int) or not 1 <= sub <= 127:
            raise Refused(400, "subindex must be 1-127")
        try:
            return P.store(client, node, ctx.eds, sub)
        except P.ParameterError as e:
            raise Refused(422, str(e))
    raise Refused(404, "no such API: %s %s" % route)


ROUTES = tuple(("POST", "/api/online/" + p) for p in
               ("od_entries", "od_read", "backup", "compare", "restore_plan", "restore", "store", "job"))
