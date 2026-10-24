"""Recording a trace from the bridge's diagnostics channel
(canopen-bus-trace: "Record a trace on the PC", "Triggers").

A Session is a trace with its decoder and analysis (frames, kind/node index,
statistics, series); an opened file is a Session too. A Recorder fills a
Session from its own diagnostics connection in a background thread: it
fetches every 100 ms (at once again while the bridge has more), polls status
every 500 ms for the status series and status triggers, evaluates the
trigger, places markers and auto-saves.

Times: frames carry the PLC's kernel clock. Status answers are stamped with
this PC's clock moved by the smallest (PC time - newest frame time) seen,
which puts them on the frames' time axis to within the network delay.
"""

import base64
import os
import threading
import time

from .. import diag
from . import formats, triggers
from .model import RECORD_SIZE, Frame, Trace, unpack_records
from .modbus import Record as ModbusRecord
from .stats import Analysis

FETCH_INTERVAL = 0.1
STATUS_INTERVAL = 0.5
RECONNECT_INTERVAL = 1.0
LOST_AFTER_S = 10.0  # a runtime that answers no reconnect for this long ends the recording
TOO_OLD = "the bridge is too old for traces; update it (install-bridge.sh)"
MODBUS_HOLD_US = 500_000  # Modbus records wait this long for CAN frames of their time
NOT_A_BRIDGE = "Modbus requests: the runtime is not a bridge, so only CAN frames are recorded"
MODBUS_TOO_OLD = "Modbus requests: the bridge is too old for a Modbus trace; update it (install-bridge.sh)"


class Session:
    def __init__(self, decoder, bitrate=None, limit=None, trace=None):
        self.lock = threading.RLock()
        self.decoder = decoder
        self.trace = trace if trace is not None else (Trace(limit) if limit else Trace())
        if trace is None and bitrate:
            self.trace.meta["bitrate"] = bitrate
        self.analysis = Analysis(decoder, bitrate or self.trace.meta.get("bitrate"))
        if trace is not None and len(trace):
            for f in trace:
                self.analysis.feed(f)

    def feed_packed(self, data, on_decoded=None):
        """Appends packed records; returns the new frames."""
        frames = unpack_records(data)
        with self.lock:
            before = self.trace.dropped
            self.trace.append_packed(data[:len(frames) * RECORD_SIZE])
            for f in frames:
                self.analysis.feed(f, on_decoded)
            dropped = self.trace.dropped - before
            if dropped:
                self.analysis.drop_front(dropped)
        return frames

    def feed(self, frames, on_decoded=None):
        return self.feed_packed(b"".join(f.pack() for f in frames), on_decoded)

    def feed_modbus(self, records):
        """Appends Modbus records (time order) after the frames: a record
        older than the newest frame keeps its own time but takes its place
        after it."""
        with self.lock:
            t = self.trace
            for r in records:
                end = t.end_us
                before = t.dropped
                t.append_modbus(r, end if end is not None and r.time_us < end else None)
                self.analysis.feed(t.frame(len(t) - 1))
                dropped = t.dropped - before
                if dropped:
                    self.analysis.drop_front(dropped)


class Recorder:
    """state: idle, connecting, recording, no_bus, reconnecting, stopped,
    ended (the connection ended; the frames are kept), error.

    ended: () -> a reason when the page's connection ended (Disconnect, an
    adapter's bus-off), else None. offset_us: the clock offset of the
    recording this one continues, so its gap lands on the same time axis."""

    def __init__(self, connect, session, filters=None, error_frames=False, trigger=None, autosave_dir=None,
                 name_prefix="canworks", fetch_interval=FETCH_INTERVAL, status_interval=STATUS_INTERVAL,
                 on_stop=None, ended=None, offset_us=None, lost_after=LOST_AFTER_S, modbus=None):
        self.connect = connect  # () -> a connected diag.Client
        self.session = session
        self.filters = list(filters or [])
        self.error_frames = error_frames
        self.engine = triggers.Engine(trigger) if trigger else None
        self.autosave_dir = autosave_dir
        self.name_prefix = name_prefix
        self.fetch_interval = fetch_interval
        self.status_interval = status_interval
        self.on_stop = on_stop
        self.ended = ended
        self.lost_after = lost_after
        # Modbus requests (canopen-configurator "Modbus requests in the
        # Trace view"): {"changes_only", "clients"} or None.
        self.modbus = modbus
        self.modbus_note = ""
        self._mb_pending = []
        self._can_pending = []
        self._mb_active = False
        self.state = "idle"
        self.message = ""
        self.saved = []  # auto-saved file paths
        self.status = None  # the latest status answer
        self.offset_us = offset_us  # PC clock - PLC clock (smallest seen)
        self.stop_at_us = None  # single mode: stop when frames reach this time
        self.pending_saves = []  # [(hit_us, until_us)]
        self.trimmed = 0  # single mode: frames outside the pre/post window, removed at the stop
        self._stop = threading.Event()
        self._thread = None
        self._lost_total = 0

    # -- control ------------------------------------------------------------
    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self.state = "connecting"
        self._thread = threading.Thread(target=self._run, name="canopen-trace", daemon=True)
        self._thread.start()

    def stop(self, wait=True):
        self._stop.set()
        if wait and self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=5)

    @property
    def running(self):
        return bool(self._thread and self._thread.is_alive())

    def wait(self, timeout=None):
        if self._thread:
            self._thread.join(timeout)

    def info(self):
        t = self.session.trace
        out = {"state": self.state, "message": self.message, "running": self.running,
               "saved": list(self.saved), "hits": list(self.engine.hits) if self.engine else [],
               "trigger": triggers.describe(self.engine.spec) if self.engine else None,
               "lost": sum(n for _, n in t.lost), "kernel_drops": t.kernel_drops, "trimmed": self.trimmed,
               "modbus": bool(self.modbus), "modbus_note": self.modbus_note}
        return out

    # -- the loop -------------------------------------------------------------
    def _end(self, reason):
        """The connection ended: the frames stay, a marker says why."""
        now_us = int(time.time() * 1e6) - (self.offset_us or 0)
        with self.session.lock:
            at = max(now_us, self.session.analysis.last_us or 0)
            self.session.trace.add_marker(at, "connection ended: %s" % reason, "end")
        self.state, self.message = "ended", "connection ended: %s" % reason

    def _run(self):
        client = None
        next_seq = 0
        mb_seq = None  # the Modbus trace's cursor; None: no Modbus trace
        last_status = 0.0
        last_ok = time.monotonic()
        try:
            while not self._stop.is_set():
                reason = self.ended() if self.ended else None
                if reason:
                    self._end(reason)
                    break
                if client is None:
                    try:
                        client = self.connect()
                        r = client.trace_start(self.filters, self.error_frames)
                    except diag.DiagError as e:
                        if client is not None:
                            client.close()
                        client = None
                        if e.kind == "refused" and "unknown op" in str(e):
                            self.state = "error"
                            self.message = TOO_OLD
                            return
                        if e.kind in ("token", "protocol"):
                            self.state, self.message = "error", str(e)
                            return
                        if str(e).startswith("connection ended"):
                            self._end(str(e)[len("connection ended"):].lstrip(": ") or "closed")
                            break
                        if time.monotonic() - last_ok > self.lost_after:
                            self._end("not answering for %d s" % self.lost_after)
                            break
                        if e.kind == "refused" and "no bus" in str(e):
                            self.state, self.message = "no_bus", "no CANopen session on the runtime (waiting)"
                        else:
                            self.state = "reconnecting" if len(self.session.trace) else "connecting"
                            self.message = str(e)
                        self._stop.wait(RECONNECT_INTERVAL)
                        continue
                    with self.session.lock:
                        meta = self.session.trace.meta
                        # The network the trace records (a bridge with
                        # several networks names it; an older one does not).
                        if r.get("network"):
                            meta.setdefault("network", r["network"])
                        meta.setdefault("interface", r.get("interface"))
                        if r.get("bitrate"):
                            meta["bitrate"] = r["bitrate"]
                            self.session.analysis.bitrate = r["bitrate"]
                        if len(self.session.trace):
                            # Reconnected, or a recording continued: whatever
                            # happened meanwhile is not in the trace.
                            at = int(time.time() * 1e6) - (self.offset_us or 0)
                            last = self.session.analysis.last_us
                            self.session.feed([Frame(at, 0, gap=True)])
                            if last is not None and at - last >= 1_000_000:
                                self.session.trace.add_marker(at, "gap of %.1f s" % ((at - last) / 1e6), "gap")
                    next_seq = int(r.get("next") or 0)
                    mb_seq = self._modbus_start(client)
                    self.state, self.message = "recording", ""
                try:
                    more = self._fetch(client, next_seq)
                    next_seq = more[0]
                    if mb_seq is not None:
                        mb_seq, mb_more = self._fetch_modbus(client, mb_seq)
                        more = (more[0], more[1] or mb_more)
                    now = time.monotonic()
                    if now - last_status >= self.status_interval:
                        last_status = now
                        self._poll_status(client)
                except diag.DiagError as e:
                    client.close()
                    client = None
                    mb_seq = None
                    self._flush_modbus(None)
                    self._mb_active = False
                    if str(e).startswith("connection ended"):
                        self._end(str(e)[len("connection ended"):].lstrip(": ") or "closed")
                        break
                    self.state, self.message = "reconnecting", str(e)
                    continue
                last_ok = time.monotonic()
                self._autosave_due()
                if self.stop_at_us is not None and (self.session.analysis.last_us or 0) >= self.stop_at_us:
                    self.message = "stopped by the trigger"
                    break
                if self.stop_at_us is not None and self.offset_us is not None and \
                        time.time() * 1e6 - self.offset_us >= self.stop_at_us + 1e6:
                    self.message = "stopped by the trigger"
                    break
                if not more[1]:
                    self._stop.wait(self.fetch_interval)
        except Exception as e:  # keep the recorded frames; say what broke
            self.state, self.message = "error", "recording stopped: %s" % e
        finally:
            if client is not None:
                try:
                    if mb_seq is not None:
                        mb_seq = self._fetch_modbus(client, mb_seq, flush=True)[0]
                        client.modbus_trace_stop()
                    client.trace_stop()
                except diag.DiagError:
                    pass
                client.close()
            self._flush_modbus(None)
            self._autosave_due(force=True)
            if self.stop_at_us is not None:
                self._keep_window()
            if self.state not in ("error", "ended"):
                self.state = "stopped"
            if self.on_stop:
                self.on_stop(self)

    def _fetch(self, client, after):
        r = client.trace_fetch(after, 4000)
        data = base64.b64decode(r.get("frames") or "")
        lost = int(r.get("lost") or 0)
        trace = self.session.trace
        if lost:
            first_us = Frame.unpack(data, 0).time_us if len(data) >= RECORD_SIZE else int(time.time() * 1e6)
            with self.session.lock:
                trace.lost.append((first_us, lost))
                trace.add_marker(first_us, "%d frames lost" % lost, "lost")
        trace.kernel_drops = int(r.get("kernel_drops") or 0)
        if data:
            if self._mb_active:
                # With a Modbus trace the frames wait too, so both go in by time.
                self._can_pending += unpack_records(data)
            else:
                self.session.feed_packed(data, self._on_frame if self.engine else None)
            newest = Frame.unpack(data, len(data) - RECORD_SIZE).time_us
            off = int(time.time() * 1e6) - newest
            if self.offset_us is None or off < self.offset_us:
                self.offset_us = off
        if not r.get("session", True):
            self.state, self.message = "no_bus", "no CANopen session on the runtime (interface down?)"
        elif self.state == "no_bus":
            self.state, self.message = "recording", ""
        return int(r.get("next", after)), bool(r.get("more"))

    # -- Modbus ---------------------------------------------------------------
    def _modbus_start(self, client):
        """Starts the Modbus trace next to the CAN one; the cursor, or None
        (not asked for, or not a bridge: noted, CAN goes on)."""
        if not self.modbus:
            return None
        try:
            r = client.modbus_trace_start(self.modbus.get("changes_only", True), self.modbus.get("clients"))
        except diag.DiagError as e:
            if e.kind != "refused":
                raise
            self.modbus_note = MODBUS_TOO_OLD if "unknown op" in str(e) else \
                NOT_A_BRIDGE if "not a bridge" in str(e) else "Modbus requests: %s" % e
            return None
        with self.session.lock:
            meta = self.session.trace.meta
            meta["modbus"] = True
            for k, key in (("map_hash", "bridge_map_hash"), ("port", "modbus_port")):
                if r.get(k) is not None:
                    meta[key] = r[k]
            if len(self.session.trace.modbus):
                at = int(time.time() * 1e6) - (self.offset_us or 0)
                self.session.trace.add_marker(at, "Modbus trace restarted (requests may be missing)", "gap")
        self.modbus_note = ""
        self._mb_active = True
        return int(r.get("next") or 0)

    def _fetch_modbus(self, client, after, flush=False):
        r = client.modbus_trace_fetch(after, 4000)
        recs = ModbusRecord.unpack_all(base64.b64decode(r.get("records") or ""))
        lost = int(r.get("lost") or 0)
        if lost:
            at = recs[0].time_us if recs else int(time.time() * 1e6) - (self.offset_us or 0)
            with self.session.lock:
                self.session.trace.add_marker(at, "%d Modbus requests lost" % lost, "lost")
        self._mb_pending += recs
        if recs:
            off = int(time.time() * 1e6) - recs[-1].time_us
            if self.offset_us is None or off < self.offset_us:
                self.offset_us = off
        self._flush_modbus(None if flush else int(time.time() * 1e6) - (self.offset_us or 0) - MODBUS_HOLD_US)
        return int(r.get("next", after)), bool(r.get("more"))

    def _flush_modbus(self, upto_us):
        """Puts the waiting frames and Modbus records up to a time into the
        trace, in time order (all of them with None): records and frames of
        the same moment come in different fetches."""
        if not self._mb_pending and not self._can_pending:
            return
        if upto_us is None:
            mb, self._mb_pending = self._mb_pending, []
            can, self._can_pending = self._can_pending, []
        else:
            mb = [x for x in self._mb_pending if x.time_us <= upto_us]
            self._mb_pending = [x for x in self._mb_pending if x.time_us > upto_us]
            can = [f for f in self._can_pending if f.time_us <= upto_us]
            self._can_pending = [f for f in self._can_pending if f.time_us > upto_us]
        mb.sort(key=lambda x: x.time_us)
        on = self._on_frame if self.engine else None
        i = 0
        for rec in mb:
            j = i
            while j < len(can) and can[j].time_us <= rec.time_us:
                j += 1
            if j > i:
                self.session.feed(can[i:j], on)
                i = j
            self.session.feed_modbus([rec])
        if i < len(can):
            self.session.feed(can[i:], on)

    def _poll_status(self, client):
        st = client.status()
        self.status = st
        now_us = int(time.time() * 1e6) - (self.offset_us or 0)
        a = self.session.analysis
        with self.session.lock:
            bus = st.get("bus") or {}
            for key, label in (("state", "bus state"), ("tx_errors", "TX error counter"),
                               ("rx_errors", "RX error counter")):
                if key in bus:
                    a.ensure_series("bus.%s" % key, label, None, "status").add(now_us, bus[key])
            for n in st.get("nodes") or []:
                nid = n.get("node_id")
                name = n.get("name") or "node%s" % nid
                a.ensure_series("state.%s" % nid, "%s NMT state" % name, nid, "status").add(now_us, n.get("state", 0))
                a.ensure_series("status.%s" % nid, "%s status bit" % name, nid, "status").add(
                    now_us, 1 if n.get("status") else 0)
                for v in n.get("sdo_variables") or []:
                    try:
                        value = float(v.get("raw"))
                    except (TypeError, ValueError):
                        continue
                    a.ensure_series("sdovar.%s.%04X:%d" % (nid, v.get("index", 0), v.get("subindex", 0)),
                                    "%s %s" % (name, v.get("name")),
                                    nid, "status").add(now_us, value)
        if self.engine and self.engine.status(now_us, st):
            self._hit(now_us)

    # -- triggers -------------------------------------------------------------
    def _on_frame(self, f, d):
        if self.engine.frame(f, d):
            self._hit(f.time_us)

    def _hit(self, time_us):
        spec = self.engine.spec
        trace = self.session.trace
        with self.session.lock:
            trace.add_marker(time_us, "trigger: %s" % triggers.describe(spec), "trigger")
            trace.meta["trigger"] = triggers.describe(spec)
        post_us = int(spec["post_s"] * 1e6)
        if spec["autosave"]:
            self.pending_saves.append((time_us, time_us + post_us))
        if spec["mode"] == "single" and self.stop_at_us is None:
            self.stop_at_us = time_us + post_us

    def _keep_window(self):
        """Single mode: the trace keeps only the pre/post window around the
        hit; the analysis is built again from it, the polled status series
        keep their points in the window."""
        spec = self.engine.spec
        lo = self.stop_at_us - int(spec["post_s"] * 1e6) - int(spec["pre_s"] * 1e6)
        s = self.session
        with s.lock:
            old = s.trace
            part = old.sub(lo, self.stop_at_us)
            if len(part) == len(old):
                return
            part.limit, part.kernel_drops, part.dropped = old.limit, old.kernel_drops, old.dropped
            analysis = Analysis(s.decoder, s.analysis.bitrate)
            for f in part:
                analysis.feed(f)
            for key, sr in s.analysis.series.items():
                if sr.kind == "status":
                    ts, vs = sr.range(lo, self.stop_at_us)
                    kept = analysis.ensure_series(key, sr.label, sr.node, "status")
                    for t, v in zip(ts, vs):
                        if t >= lo:
                            kept.add(t, v)
            self.trimmed = len(old) - len(part)
            s.trace, s.analysis = part, analysis

    def _autosave_due(self, force=False):
        if not self.engine or not self.engine.spec["autosave"]:
            return
        spec = self.engine.spec
        last = self.session.analysis.last_us or 0
        keep = []
        for hit, until in self.pending_saves:
            if last >= until or force:
                self._save_window(hit, spec)
            else:
                keep.append((hit, until))
        self.pending_saves = keep

    def _save_window(self, hit, spec):
        a = spec["autosave"]
        fmt = formats.format_of("x." + a["format"], a["format"])
        ext = next(e for e, (fid, _) in formats.FORMATS.items() if fid == fmt)
        folder = a.get("folder") or self.autosave_dir or "."
        pre, post = int(spec["pre_s"] * 1e6), int(spec["post_s"] * 1e6)
        with self.session.lock:
            part = self.session.trace.sub(hit - pre, hit + post)
        path = os.path.join(folder, triggers.autosave_name(self.name_prefix, hit, ext))
        try:
            formats.write_file(part, path, fmt, self.session.decoder if fmt == "csv" else None)
            self.saved.append(path)
        except OSError as e:
            self.message = "auto-save to %s failed: %s" % (folder, e.strerror or e)
