"""The configurator's Trace view on the server (canopen-configurator: "Trace
view"; canopen-bus-trace design D4).

One Workspace per project folder holds the trace the page shows: a live
recording (a bustrace Recorder with its own diagnostics connection) or an
opened file. The page asks for windows of decoded rows and decimated series
ranges, so a reload or a switch to another view keeps the trace.

Display filters (node, frame kind, identifier range, direction, text) never
change what is recorded; a FilterView keeps the matching frame numbers and
extends them as frames arrive.
"""

import base64
import io
import os
import threading
from array import array

from .. import contract, dbcexport, diag
from ..bustrace import explain as explain_mod
from ..bustrace import formats, sequences, triggers
from ..bustrace.decode import CONTEXT_KINDS, KINDS, Decoder, j1939_network
from ..bustrace.recorder import Recorder, Session
from ..bustrace.stats import KIND_CODE

MAX_ROWS = 1000
LOOKBACK = 4000  # frames searched back for SDO transfers when decoding a window
SPAN_CONTEXT = 50000  # above this, frames between filtered rows are not decoded for SDO context
MAX_VIEWS = 8
MAX_SEQUENCES = 2000  # conversations or boot stories sent to the page
CONTEXT = {KIND_CODE[k] for k in CONTEXT_KINDS}  # SDO transfers, J1939 transport sessions
GAP = KIND_CODE["gap"]
EXPORT_FORMATS = ("pcapng", "candump", "asc", "blf", "trc", "csv", "signals")
CONTENT_TYPES = {"csv": "text/csv", "signals": "text/csv"}


class Refused(Exception):
    def __init__(self, status, message, **extra):
        super().__init__(message)
        self.status, self.extra = status, extra


def _int(v, what, lo=None, hi=None):
    if isinstance(v, bool):
        raise Refused(400, "%s must be a number" % what)
    try:
        n = v if isinstance(v, int) else int(str(v).strip(), 0)
    except (TypeError, ValueError):
        raise Refused(400, "%s must be a number" % what)
    if (lo is not None and n < lo) or (hi is not None and n > hi):
        raise Refused(400, "%s must be %s-%s" % (what, lo, hi))
    return n


def _hex_id(v, what):
    """An identifier as the trace shows it: hex, with or without 0x (a JSON
    number is taken as it is)."""
    if isinstance(v, str):
        t = v.strip()
        t = t[2:] if t[:2].lower() == "0x" else t
        if not t or any(c not in "0123456789abcdefABCDEF" for c in t):
            raise Refused(400, "%s must be a hex identifier, e.g. 180 or 0x180" % what)
        v = int(t, 16)
    return _int(v, what, 0, 0x1FFFFFFF)


def _opt_id(v, what):
    return None if v in (None, "") else _hex_id(v, what)


def _opt_time(v, what):
    return None if v in (None, "") else _int(v, what)


def capture_filters(items):
    """[{"id", "mask"}] from the page -> [(id, mask)]; the plugin takes up to 16."""
    out = []
    for f in items or []:
        if not isinstance(f, dict):
            raise Refused(400, "a capture filter must be an object with id and mask")
        can_id = _hex_id(f.get("id"), "filter id")
        mask = _hex_id(f.get("mask") if f.get("mask") not in (None, "") else 0x1FFFFFFF, "filter mask")
        out.append((can_id, mask))
    if len(out) > 16:
        raise Refused(400, "at most 16 capture filters")
    return out


class DisplayFilter:
    def __init__(self, spec):
        spec = spec if isinstance(spec, dict) else {}
        nodes = spec.get("nodes") or []
        self.nodes = {_int(n, "node", 1, 127) for n in nodes} or None
        kinds = spec.get("kinds") or []
        bad = [k for k in kinds if k not in KIND_CODE]
        if bad:
            raise Refused(400, "unknown frame kind %s (known: %s)" % (bad[0], ", ".join(KINDS)))
        self.kinds = {KIND_CODE[k] for k in kinds} or None
        self.id_from = _opt_id(spec.get("id_from"), "ID from")
        self.id_to = _opt_id(spec.get("id_to"), "ID to")
        direction = spec.get("dir") or "any"
        if direction not in ("any", "rx", "tx"):
            raise Refused(400, "dir must be any, rx or tx")
        self.dir = direction
        self.text = str(spec.get("text") or "").strip().lower()
        self.key = (tuple(sorted(self.nodes or ())), tuple(sorted(self.kinds or ())), self.id_from, self.id_to,
                    self.dir, self.text)

    @property
    def empty(self):
        return not (self.nodes or self.kinds or self.id_from is not None or self.id_to is not None
                    or self.dir != "any" or self.text)


class FilterView:
    """The absolute frame numbers (trace.dropped + index) that pass a filter."""

    def __init__(self, flt, decoder):
        self.flt = flt
        self.seqs = array("Q")
        self.upto = 0
        self.decoder = decoder.clone() if flt.text else None

    def update(self, session):
        t, a, flt = session.trace, session.analysis, self.flt
        base = t.dropped
        if self.seqs and self.seqs[0] < base:
            k = _bisect(self.seqs, base)
            del self.seqs[:k]
        start, end = max(self.upto, base), base + len(t)
        kinds, nodes = a.kinds, a.nodes
        for seq in range(start, end):
            i = seq - base
            kind = kinds[i]
            if kind == GAP:
                if flt.kinds is None or GAP in flt.kinds:
                    self.seqs.append(seq)
                continue
            ok = (flt.kinds is None or kind in flt.kinds) and (flt.nodes is None or nodes[i] in flt.nodes)
            f = None
            if ok and (flt.id_from is not None or flt.id_to is not None or flt.dir != "any"):
                f = t.frame(i)
                if f.err and (flt.id_from is not None or flt.id_to is not None):
                    ok = False
                elif flt.id_from is not None and f.can_id < flt.id_from:
                    ok = False
                elif flt.id_to is not None and f.can_id > flt.id_to:
                    ok = False
                elif flt.dir != "any" and f.tx != (flt.dir == "tx"):
                    ok = False
            if self.decoder is not None and (ok or kind in CONTEXT):
                f = f or t.frame(i)
                d = self.decoder.decode(f)
                if ok:
                    hay = " ".join((f.id_text(), f.data_text(), d.name, d.text)).lower()
                    ok = flt.text in hay
            if ok:
                self.seqs.append(seq)
        self.upto = end


def _bisect(seq, value, key=None):
    lo, hi = 0, len(seq)
    while lo < hi:
        mid = (lo + hi) // 2
        if (key(seq[mid]) if key else seq[mid]) < value:
            lo = mid + 1
        else:
            hi = mid
    return lo


class Workspace:
    def __init__(self, folder, limit=None):
        self.folder = folder
        self.lock = threading.RLock()
        self.limit = limit
        self.session = Session(Decoder(), limit=limit)
        self.recorder = None
        self.source = None  # None, "live" or the opened file's name
        self.network = None  # the network recorded or decoded, with several
        self.trigger = None  # the checked trigger spec for the next start
        self.filters, self.error_frames = [], False
        self.warnings = []
        self.generation = 0
        self.views = {}
        self.seq_cache = {}

    def _replace(self, session, source, warnings):
        self.session, self.source, self.warnings = session, source, list(warnings)
        self.views = {}
        self.seq_cache = {}
        self.generation += 1

    # -- recording ----------------------------------------------------------
    def start(self, connect, decoder, filters, error_frames, trigger, autosave_dir, name_prefix, network=None):
        with self.lock:
            if self.recorder and self.recorder.running:
                raise Refused(409, "a trace is already recording")
            self.filters, self.error_frames, self.network = filters, error_frames, network
            if trigger is not None:
                self.trigger = trigger or None
            self._replace(Session(decoder, limit=self.limit), "live", decoder.warnings)
            self.recorder = Recorder(connect, self.session, filters, error_frames, self.trigger,
                                     autosave_dir=autosave_dir, name_prefix=name_prefix)
            self.recorder.start()

    def stop(self):
        with self.lock:
            rec = self.recorder
        if rec:
            rec.stop()

    def clear(self):
        with self.lock:
            rec = self.recorder
            if rec and rec.running:
                with self.session.lock:
                    self.session.trace.clear()
                    self.session.analysis.__init__(self.session.decoder, self.session.analysis.bitrate)
                self.views = {}
                self.generation += 1
                return
            self.recorder = None
            self._replace(Session(Decoder(), limit=self.limit), None, [])

    def recording(self):
        with self.lock:
            return bool(self.recorder and self.recorder.running)

    def set_trigger(self, spec):
        with self.lock:
            self.trigger = spec
            rec = self.recorder
            if rec and rec.running:
                rec.engine = triggers.Engine(spec) if spec else None
                rec.stop_at_us = None
                rec.pending_saves = []

    def open(self, trace, name, decoder, network=None):
        with self.lock:
            if self.recorder and self.recorder.running:
                raise Refused(409, "stop the recording before opening a file")
        session = Session(decoder, trace=trace)  # decodes every frame: the page keeps polling meanwhile
        with self.lock:
            if self.recorder and self.recorder.running:
                raise Refused(409, "stop the recording before opening a file")
            self.recorder = None
            self.network = network
            self._replace(session, name, decoder.warnings)

    # -- what the page reads ------------------------------------------------
    def state(self):
        with self.lock:
            s, rec = self.session, self.recorder
            info = rec.info() if rec else None
        with s.lock:
            t = s.trace
            out = {"source": self.source, "network": self.network, "generation": self.generation, "frames": len(t),
                   "dropped": t.dropped, "limit": t.limit, "start_us": t.start_us, "end_us": t.end_us,
                   "markers": list(t.markers), "meta": {k: v for k, v in t.meta.items() if isinstance(v, (str, int))},
                   "summary": s.analysis.summary(sum(n for _, n in t.lost), t.kernel_drops),
                   "series": s.analysis.series_list(), "warnings": self.warnings,
                   "filters": [{"id": i, "mask": m} for i, m in self.filters], "error_frames": self.error_frames,
                   "trigger": self.trigger, "trigger_text": triggers.describe(self.trigger) if self.trigger else ""}
        out["recording"] = info or {"state": "idle", "message": "", "running": False, "saved": [], "hits": []}
        return out

    def _view(self, flt):
        if flt.empty:
            return None
        v = self.views.get(flt.key)
        if v is None:
            if len(self.views) >= MAX_VIEWS:
                self.views.pop(next(iter(self.views)))
            v = self.views[flt.key] = FilterView(flt, self.session.decoder)
        v.update(self.session)
        return v

    def rows(self, offset=0, count=200, flt=None, at_us=None):
        """A window of decoded rows. With at_us: the window around the first
        row at or after that time, and `focus` names that row's position."""
        flt = flt or DisplayFilter({})
        count = max(1, min(MAX_ROWS, count))
        with self.lock:
            s = self.session
            generation = self.generation
        with s.lock:
            t, a = s.trace, s.analysis
            base = t.dropped
            view = self._view(flt)
            total = len(view.seqs) if view else len(t)
            focus = None
            if at_us is not None:
                if view:
                    focus = _bisect(view.seqs, at_us, key=lambda q: t.times[q - base])
                else:
                    focus = t.index_at(at_us)
                focus = min(focus, max(0, total - 1))
                offset = max(0, focus - count // 2)
            offset = max(0, min(offset, max(0, total - count)))
            positions = range(offset, min(total, offset + count))
            idx = [view.seqs[p] - base for p in positions] if view else list(positions)
            rows = []
            if idx:
                dec = s.decoder.clone()
                first, last = idx[0], idx[-1]
                for j in range(max(0, first - LOOKBACK), first):
                    if a.kinds[j] in CONTEXT:
                        dec.decode(t.frame(j))
                wanted = set(idx)
                between = range(first, last + 1) if last - first <= SPAN_CONTEXT else idx
                for j in between:
                    if j in wanted:
                        f = t.frame(j)
                        d = dec.decode(f)
                        rows.append(_row(f, d, j + base, positions[len(rows)]))
                    elif a.kinds[j] in CONTEXT:
                        dec.decode(t.frame(j))
            return {"generation": generation, "total": total, "offset": offset, "focus": focus, "rows": rows,
                    "start_us": t.start_us}

    def ids(self):
        with self.session.lock:
            return {"ids": self.session.analysis.id_table()}

    def series(self, keys, start_us=None, end_us=None, points=None):
        out = {}
        with self.session.lock:
            a = self.session.analysis
            for k in keys:
                if k in ("bus.rate", "bus.load"):
                    ts, rate, load = a.rate_series(start_us, end_us)
                    out[k] = [ts, rate if k == "bus.rate" else load]
                    continue
                sr = a.series.get(k)
                if sr is not None:
                    out[k] = sr.range(start_us, end_us, points)
            return {"series": out, "start_us": self.session.trace.start_us, "end_us": self.session.trace.end_us}

    # -- explanations and sequences (canopen-bus-trace: "Frame inspector on
    # traces", "SDO conversations", "SYNC cycle view", "Boot story") ---------
    def explain(self, seq, bitrate=None, fallback=None):
        """The layers of frame `seq` (absolute), decoded with the SDO frames
        before it as context. The bit rate: the one chosen, else the
        trace's, else `fallback` (the configuration's)."""
        with self.lock:
            s = self.session
        with s.lock:
            t = s.trace
            i = seq - t.dropped
            if not 0 <= i < len(t):
                raise Refused(404, "frame %d is not in the trace (any more)" % seq)
            f = t.frame(i)
            if f.gap:
                raise Refused(422, "this row marks lost frames; it is not a frame")
            rate = bitrate or s.analysis.bitrate or fallback or None
            m = explain_mod.explain(f, s.decoder, rate, explain_mod.context_for(t, i, s.decoder))
        m.update(seq=seq, t_us=f.time_us, dir="Tx" if f.tx else "Rx")
        return m

    def _cached(self, s, name, make):
        t = s.trace
        key = (self.generation, len(t), t.dropped)
        if self.seq_cache.get("key") != key:
            self.seq_cache = {"key": key}
        if name not in self.seq_cache:
            self.seq_cache[name] = make()
        return self.seq_cache[name]

    def sequence(self, kind, n=None, node=None, expected=None, at=None, limit=MAX_SEQUENCES):
        """SDO conversations, boot stories or one SYNC period of the trace.
        With `at` (a frame number): the conversation, boot or SYNC period
        that holds that frame is `selected` (or `n`)."""
        with self.lock:
            s = self.session
        with s.lock:
            t, a, dec = s.trace, s.analysis, s.decoder
            base = t.dropped

            def convs():
                return self._cached(s, "sdo", lambda: sequences.sdo_conversations(t, a.kinds, dec, base=base))

            if kind == "sdo":
                lst = [c for c in convs() if node is None or c["node"] == node]
                sel = sequences.conversation_at(lst, at) if at is not None else None
                shown = lst[-limit:]
                if sel is not None and sel not in shown:
                    shown = [sel] + shown
                return {"kind": "sdo", "total": len(lst), "conversations": shown,
                        "nodes": sorted({c["node"] for c in convs()}), "selected": sel["seq"] if sel else None}
            if kind == "boot":
                lst = sequences.boot_stories(t, a.kinds, dec, expected, base, convs())
                lst = [b for b in lst if node is None or b["node"] == node]
                sel = next((b for b in lst if at is not None and b["seq"] <= at <= b["end_seq"]
                            and any(st["seq"] == at for st in b["steps"])), None) if at is not None else None
                return {"kind": "boot", "total": len(lst), "stories": lst[-limit:], "compared": expected is not None,
                        "selected": sel["seq"] if sel else None}
            if kind == "sync":
                cycles = self._cached(s, "sync", lambda: sequences.sync_cycles(t, a.kinds, dec, base))
                if not cycles:
                    return {"kind": "sync", "count": 0, "cycle": None, "slowest": None, "late": []}
                slow = sequences.slowest_cycle(cycles)
                if at is not None:
                    n = max(0, _bisect(cycles, at + 1, key=lambda c: c["seq"]) - 1)
                if n == "slowest":
                    n = slow["n"] if slow else 0
                n = 0 if n is None else n
                periods = [c["period_us"] for c in cycles if c["period_us"] is not None]
                return {"kind": "sync", "count": len(cycles), "slowest": slow["n"] if slow else None,
                        "slowest_us": slow["last_sync_pdo_us"] if slow else None,
                        "late": [c["n"] for c in cycles if c["late"]][:1000],
                        "period_min_us": min(periods) if periods else None,
                        "period_max_us": max(periods) if periods else None,
                        "cycle": sequences.sync_cycle(t, a.kinds, dec, n, base)}
        raise Refused(400, "kind must be sdo, boot or sync")

    def part(self, start_us=None, end_us=None):
        with self.session.lock:
            t = self.session.trace
            if not len(t):
                raise Refused(409, "the trace is empty")
            return t.sub(start_us, end_us), self.session.decoder

    def signals_csv(self, keys, start_us=None, end_us=None):
        with self.session.lock:
            a = self.session.analysis
            chosen = []
            for k in keys or []:
                sr = a.series.get(k)
                if sr is None:
                    continue
                ts, vs = sr.range(start_us, end_us)
                if start_us is not None and ts and ts[0] < start_us:
                    ts, vs = ts[1:], vs[1:]
                chosen.append((sr.label, list(zip(ts, vs))))
            t0 = self.session.trace.start_us
        if not chosen:
            raise Refused(400, "choose the series to export")
        out = io.StringIO()
        formats.write_signals_csv(chosen, out, t0)
        return out.getvalue().replace("\n", "\r\n").encode("utf-8")


def _row(f, d, seq, pos):
    return {"pos": pos, "seq": seq, "t_us": f.time_us, "dir": "Tx" if f.tx else "Rx", "id": f.id_text(),
            "ext": f.ext, "rtr": f.rtr, "err": f.err, "gap": f.gap, "dlc": f.dlc,
            "data": "" if f.gap or f.rtr else f.data_text(), "kind": d.kind, "node": d.node, "name": d.name,
            "text": d.text}


class Traces:
    """The workspaces of the server, by project folder."""

    def __init__(self, limit=None):
        self.lock = threading.Lock()
        self.limit = limit
        self.spaces = {}

    def get(self, folder):
        with self.lock:
            ws = self.spaces.get(folder)
            if ws is None:
                ws = self.spaces[folder] = Workspace(folder, self.limit)
            return ws

    def stop_all(self):
        with self.lock:
            spaces = list(self.spaces.values())
        for ws in spaces:
            ws.stop()


def decoder_for(cfg, config_path, eds_paths, names, network=None):
    """A decoder with the nodes of one network: the one `network` names in
    a version 2 config, or the only one (without it, a config with several
    decodes without nodes and says so in the warnings). A J1939 network
    decodes as J1939 (bustrace/j1939.py)."""
    if isinstance(cfg, dict) and j1939_network(cfg, network) is not None:
        return Decoder.from_config(cfg, config_path, network=network)
    if not isinstance(cfg, dict) or not contract.all_nodes(cfg):
        return Decoder()
    if contract.version_of(cfg) == 1:
        network = None
    return Decoder.from_config(cfg, config_path, eds_paths=eds_paths, names=names, network=network)


def check_trigger(spec):
    if not spec:
        return None
    try:
        return triggers.check(spec)
    except triggers.TriggerError as e:
        raise Refused(422, str(e))


def check_folder(folder, canopen_dir, exists=True):
    """An auto-save or save folder: absolute, existing (unless `exists` is
    false: the default traces folder is made on the first save), and never
    the project's canworks folder."""
    given = folder
    folder = os.path.expanduser(folder)
    if not os.path.isabs(folder):
        raise Refused(422, "the folder %s is not a full path; give one such as %s" % (
            given, os.path.join(os.path.expanduser("~"), "traces")))
    folder = os.path.abspath(folder)
    real, cdir = os.path.realpath(folder), os.path.realpath(canopen_dir)
    if real == cdir or real.startswith(cdir + os.sep):
        raise Refused(422, "traces are not saved in the project's canworks folder (it travels with the PLC "
                           "program); choose another folder")
    if exists and not os.path.isdir(folder):
        raise Refused(422, "the folder %s does not exist" % folder)
    return folder


def encode_export(ws, fmt, start_us, end_us, keys, base_name):
    if fmt not in EXPORT_FORMATS:
        raise Refused(400, "format must be one of " + ", ".join(EXPORT_FORMATS))
    if fmt == "signals":
        data = ws.signals_csv(keys, start_us, end_us)
        name = base_name + "-signals.csv"
    else:
        part, decoder = ws.part(start_us, end_us)
        buf = io.BytesIO()
        formats.write(part, buf, fmt, decoder if fmt == "csv" else None)
        data = buf.getvalue()
        ext = next(e for e, (fid, _) in formats.FORMATS.items() if fid == fmt)
        name = "%s.%s" % (base_name, ext)
    return {"name": name, "content_type": CONTENT_TYPES.get(fmt, "application/octet-stream"),
            "size": len(data), "data": base64.b64encode(data).decode("ascii")}


def connector(hostname, port, token, timeout=3.0, network=None):
    """`hostname` may be an online.AdapterTarget: the trace then records a USB
    adapter on this PC."""
    def connect():
        if hasattr(hostname, "client"):
            c = hostname.client(timeout)
        else:
            c = diag.Client(hostname, port, token, timeout, network=network)
        c.connect()
        return c
    return connect


def plc_names(session):
    return dbcexport.plc_names(session.uses) if session.mode == "project" else None
