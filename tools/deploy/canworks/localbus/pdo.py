"""The PDO test and SYNC on a local adapter (canopen-local-bus, "PDO test on
a local adapter"): TPDO values received and decoded, RPDO values set by the
user and sent, and SYNC only while the user runs it.

Per adapter one thread (Tester) sends SYNC and RPDOs on their deadlines
through Core.transmit, the one transmit path. Tests and the SYNC producer
belong to the handle that started them and end when it closes, on stop, or
when another master appears on the bus (unless they were forced).
"""

import collections
import threading
import time

from .. import pdotest
from ..diag import DiagError, FORCE_NEEDED, hex_bytes
from . import core as core_mod

SYNC_PERIOD_MS = (1, 10000)
REPEAT_MS = (10, 60000)
PERIODS_KEPT = 20


def _int(v, what, lo, hi):
    try:
        n = int(str(v), 0) if isinstance(v, str) else int(v)
    except (TypeError, ValueError):
        raise DiagError("refused", "field '%s' must be a number" % what)
    if isinstance(v, bool) or not lo <= n <= hi:
        raise DiagError("refused", "field '%s' must be %d-%d" % (what, lo, hi))
    return n


def _pdos(items, what):
    if not isinstance(items, list):
        raise DiagError("refused", "field 'layout.%s' must be a list" % what)
    out = []
    for p in items:
        if not isinstance(p, dict):
            raise DiagError("refused", "field 'layout.%s' must be a list of PDOs" % what)
        entries = []
        for e in p.get("entries") or []:
            if not isinstance(e, dict):
                raise DiagError("refused", "PDO entries must be objects")
            entries.append({"index": _int(e.get("index"), "index", 0, 0xFFFF),
                            "subindex": _int(e.get("subindex"), "subindex", 0, 0xFF),
                            "bits": _int(e.get("bits"), "bits", 1, 64), "type": e.get("type"),
                            "name": str(e.get("name") or "")})
            if not entries[-1]["name"]:
                entries[-1]["name"] = pdotest.entry_key(entries[-1])
        if sum(e["bits"] for e in entries) > 64:
            raise DiagError("refused", "a PDO carries at most 64 bits")
        n = _int(p.get("number"), "number", 1, 512)
        out.append({"number": n, "name": str(p.get("name") or "%s%d" % (what[0].upper() + "PDO", n)),
                    "cob_id": _int(p.get("cob_id"), "cob_id", 1, 0x7FF),
                    "transmission": _int(p.get("transmission", 255), "transmission", 0, 255),
                    "event_timer_ms": _int(p.get("event_timer_ms", 0), "event_timer_ms", 0, 0xFFFF),
                    "entries": entries})
    return out


class Test:
    """One node's PDO test of one handle."""

    def __init__(self, owner, node, tpdos, rpdos, forced):
        self.owner, self.node, self.forced = owner, node, forced
        self.tpdos = {p["cob_id"]: dict(p, count=0, last=None, last_wall=None, data=None,
                                        periods=collections.deque(maxlen=PERIODS_KEPT)) for p in tpdos}
        self.rpdos = {p["number"]: dict(p, values={}, sent=0, repeat_ms=0, next=None, pending=False,
                                        last_sent=None) for p in rpdos}
        self.started = time.time()
        self.ended = None  # why it ended
        self.listeners = {}  # COB-ID -> the receive thread's callback


class _State:
    """Per adapter: the PDO tests, the SYNC producer and the thread."""

    def __init__(self):
        self.lock = threading.Lock()
        self.cond = threading.Condition(self.lock)
        self.tests = {}  # (id(owner), node) -> Test
        self.sync = None  # {"owner", "period_ms", "counter", "cob_id", "sent", "next", "value", "forced"}
        self.thread = None
        self.ended = []  # ended tests and syncs of the last minute: {"owner", "what", "reason", "at"}


_states = {}
_states_lock = threading.Lock()


def _state(core):
    with _states_lock:
        return _states.setdefault(id(core), _State())


def _remember(st, owner, what, reason):
    now = time.monotonic()
    st.ended = [e for e in st.ended if now - e["at"] < 60] + [{"owner": owner, "what": what, "reason": reason,
                                                                  "at": now}]


def _end_test(core, st, key, reason):
    t = st.tests.pop(key, None)
    if t is None:
        return
    t.ended = reason
    for cob, fn in t.listeners.items():
        core.unlisten(cob, fn)
    _remember(st, t.owner, "PDO test of node %d" % t.node, reason)
    st.cond.notify_all()


def _end_sync(st, reason):
    if st.sync is not None:
        _remember(st, st.sync["owner"], "SYNC", reason)
        st.sync = None
        st.cond.notify_all()


def end_owner(core, owner, reason="client disconnected"):
    """Ends a handle's tests and SYNC (on close)."""
    st = _state(core)
    with st.lock:
        for key in [k for k, t in st.tests.items() if t.owner is owner]:
            _end_test(core, st, key, reason)
        if st.sync is not None and st.sync["owner"] is owner:
            _end_sync(st, reason)
        st.ended = [e for e in st.ended if e["owner"] is not owner]


def _guard(c, f, what):
    c.core.wait_listened()
    other = c.core.other_master()
    forced = c._force(f)
    if other and not forced:
        raise DiagError("refused", "another master is active on this bus (%s, last at %s): %s from this PC would "
                                   "fight it; %s" % (other["what"], other["last_at"], what, FORCE_NEEDED))
    return forced


def _thread(core, st):
    """Sends SYNC and the RPDOs on their deadlines; ends tests and SYNC when
    another master appears; ends itself when nothing is left."""
    while True:
        sends = []
        with st.lock:
            if not st.tests and st.sync is None:
                st.thread = None
                return
            now = time.monotonic()
            other = core.other_master()
            if other:
                why = "another master appeared on the bus (%s)" % other["what"]
                for key in [k for k, t in st.tests.items() if not t.forced]:
                    _end_test(core, st, key, why)
                if st.sync is not None and not st.sync["forced"]:
                    _end_sync(st, why)
            sync = st.sync
            if sync is not None and sync["next"] <= now:
                data = b""
                if sync["counter"]:
                    sync["value"] = sync["value"] % sync["counter"] + 1
                    data = bytes([sync["value"]])
                sends.append(("sync", sync["cob_id"], data, None))
                sync["next"] += sync["period_ms"] / 1000.0
                if sync["next"] < now:
                    sync["next"] = now + sync["period_ms"] / 1000.0
                for t in st.tests.values():
                    for r in t.rpdos.values():
                        if not pdotest.is_event(r["transmission"]) and r["values"]:
                            sends.append(("rpdo", r["cob_id"], pdotest.pack(r["entries"], r["values"]), r))
            for t in st.tests.values():
                for r in t.rpdos.values():
                    if not pdotest.is_event(r["transmission"]):
                        continue
                    due = r["pending"] or (r["next"] is not None and r["next"] <= now)
                    if due and r["values"]:
                        sends.append(("rpdo", r["cob_id"], pdotest.pack(r["entries"], r["values"]), r))
                        r["pending"] = False
                        r["next"] = now + r["repeat_ms"] / 1000.0 if r["repeat_ms"] else None
            deadlines = [x for x in [sync["next"] if sync is not None else None] +
                         [r["next"] for t in st.tests.values() for r in t.rpdos.values()] if x is not None]
        for kind, cob, data, r in sends:
            try:
                core.transmit(cob, data)
            except Exception as e:
                with st.lock:
                    if kind == "sync":
                        _end_sync(st, "cannot send: %s" % e)
                    else:
                        for key in [k for k, t in st.tests.items() if r in t.rpdos.values()]:
                            _end_test(core, st, key, "cannot send: %s" % e)
                continue
            with st.lock:
                if kind == "sync" and st.sync is not None:
                    st.sync["sent"] += 1
                elif r is not None:
                    r["sent"] += 1
                    r["last_sent"] = time.time()
        with st.lock:
            if not st.tests and st.sync is None:
                continue
            pending = any(r["pending"] for t in st.tests.values() for r in t.rpdos.values())
            if not pending:
                wait = min([d - time.monotonic() for d in deadlines] + [0.1])
                if wait > 0:
                    st.cond.wait(wait)


def _wake(core, st):
    """Under st.lock: starts the thread or wakes it."""
    if st.thread is None:
        st.thread = threading.Thread(target=_thread, args=(core, st), name="canopen-localbus-pdo", daemon=True)
        st.thread.start()
    st.cond.notify_all()


# -- the operations -----------------------------------------------------------------------

def start(c, f):
    node = _int(f.get("node"), "node", 1, 127)
    lay = f.get("layout")
    if not isinstance(lay, dict):
        raise DiagError("refused", "field 'layout' must be {tpdos, rpdos}")
    tpdos, rpdos = _pdos(lay.get("tpdos") or [], "tpdos"), _pdos(lay.get("rpdos") or [], "rpdos")
    forced = _guard(c, f, "a PDO test")
    core, st = c.core, _state(c.core)
    t = Test(c, node, tpdos, rpdos, forced)
    for cob, p in t.tpdos.items():
        def on(data, now, wall, p=p):
            with st.lock:
                if p["last"] is not None:
                    p["periods"].append((now - p["last"]) * 1000.0)
                p.update(count=p["count"] + 1, last=now, last_wall=wall, data=bytes(data))
        t.listeners[cob] = on
    with st.lock:
        _end_test(core, st, (id(c), node), "replaced")
        st.tests[(id(c), node)] = t
        for cob, fn in t.listeners.items():
            core.listen(cob, fn)
        _wake(core, st)
    return status(c, {"node": node})


def _pdo_json(p, tx, now):
    d = {"number": p["number"], "name": p["name"], "cob_id": p["cob_id"], "transmission": p["transmission"],
         "event": pdotest.is_event(p["transmission"])}
    if tx:
        periods = list(p["periods"])
        d.update(count=p["count"], last_ms_ago=round((now - p["last"]) * 1000.0) if p["last"] is not None else None,
                 last_at=core_mod.iso(p["last_wall"]) if p["last_wall"] else None,
                 period_ms=round(sum(periods) / len(periods), 1) if periods else None,
                 data=hex_bytes(p["data"]) if p["data"] is not None else None,
                 values=pdotest.unpack(p["entries"], p["data"]) if p["data"] is not None else
                 [{"name": e["name"], "key": pdotest.entry_key(e), "value": None, "raw": None}
                  for e in p["entries"]])
    else:
        d.update(sent=p["sent"], repeat_ms=p["repeat_ms"],
                 last_sent_at=core_mod.iso(p["last_sent"]) if p["last_sent"] else None,
                 data=hex_bytes(pdotest.pack(p["entries"], p["values"])) if p["values"] else None,
                 values=[{"name": e["name"], "key": pdotest.entry_key(e), "type": e.get("type"), "bits": e["bits"],
                          "value": pdotest.unpack([e], p["values"][pdotest.entry_key(e)])[0]["value"]
                          if pdotest.entry_key(e) in p["values"] else None} for e in p["entries"]])
        if not d["event"]:
            d["note"] = "sent after each SYNC this PC sends"
    return d


def _sync_json(c, st):
    s = st.sync
    if s is None:
        return {"running": False}
    return {"running": True, "mine": s["owner"] is c, "period_ms": s["period_ms"], "counter": s["counter"],
            "cob_id": s["cob_id"], "sent": s["sent"]}


def status(c, f):
    node = _int(f.get("node"), "node", 1, 127)
    st = _state(c.core)
    now = time.monotonic()
    with st.lock:
        t = st.tests.get((id(c), node))
        ended = [e for e in st.ended if e["owner"] is c and e["what"] == "PDO test of node %d" % node]
        if t is None:
            res = {"node": node, "running": False, "sync": _sync_json(c, st)}
            if ended:
                res["ended"] = ended[-1]["reason"]
            return res
        return {"node": node, "running": True, "forced": t.forced,
                "tpdos": [_pdo_json(p, True, now) for p in t.tpdos.values()],
                "rpdos": [_pdo_json(p, False, now) for p in t.rpdos.values()], "sync": _sync_json(c, st)}


def set_values(c, f):
    node = _int(f.get("node"), "node", 1, 127)
    number = _int(f.get("rpdo"), "rpdo", 1, 512)
    values = f.get("values")
    if not isinstance(values, dict) or not values:
        raise DiagError("refused", "field 'values' must be {entry: value}")
    st = _state(c.core)
    with st.lock:
        t = st.tests.get((id(c), node))
        if t is None:
            raise DiagError("refused", "no PDO test of node %d runs on this connection" % node)
        r = t.rpdos.get(number)
        if r is None:
            raise DiagError("refused", "node %d has no RPDO%d in the test (%s)" % (
                node, number, ", ".join(p["name"] for p in t.rpdos.values()) or "no RPDO"))
        new = dict(r["values"])
        for key, text in values.items():
            try:
                _, e = pdotest.find_entry([r], str(key))
                new[pdotest.entry_key(e)] = pdotest.encode_value(e, text)
            except ValueError as e:
                raise DiagError("refused", str(e))
        if "repeat_ms" in f:
            rep = _int(f.get("repeat_ms"), "repeat_ms", 0, REPEAT_MS[1])
            if rep and rep < REPEAT_MS[0]:
                raise DiagError("refused", "field 'repeat_ms' must be 0 or %d-%d" % REPEAT_MS)
            r["repeat_ms"] = rep
        r["values"] = new
        if pdotest.is_event(r["transmission"]):
            r["pending"] = True
        _wake(c.core, st)
        now = time.monotonic()
        return _pdo_json(r, False, now)


def stop(c, f):
    node = _int(f.get("node"), "node", 1, 127) if f.get("node") is not None else None
    st = _state(c.core)
    with st.lock:
        keys = [k for k, t in st.tests.items() if t.owner is c and (node is None or t.node == node)]
        for k in keys:
            _end_test(c.core, st, k, "stopped")
    return {"stopped": len(keys)}


def sync_start(c, f):
    period = _int(f.get("period_ms"), "period_ms", *SYNC_PERIOD_MS)
    counter = _int(f.get("counter", 0), "counter", 0, 240)
    if counter == 1:
        raise DiagError("refused", "field 'counter' must be 0 (none) or 2-240")
    cob = _int(f.get("cob_id", core_mod.SYNC_COB), "cob_id", 1, 0x7FF)
    forced = _guard(c, f, "SYNC")
    st = _state(c.core)
    with st.lock:
        if st.sync is not None and st.sync["owner"] is not c:
            raise DiagError("refused", "another connection of this tool already sends SYNC on this adapter")
        st.sync = {"owner": c, "period_ms": period, "counter": counter, "cob_id": cob, "sent": 0,
                   "next": time.monotonic(), "value": 0, "forced": forced}
        _wake(c.core, st)
        return _sync_json(c, st)


def sync_stop(c, f):
    st = _state(c.core)
    with st.lock:
        if st.sync is not None and st.sync["owner"] is c:
            sent = st.sync["sent"]
            _end_sync(st, "stopped")
            return {"stopped": True, "sent": sent}
    return {"stopped": False}
