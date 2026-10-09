"""Recording a trace from the plugin's diagnostics channel
(canopen-bus-trace: "Record a trace on the PC", "Triggers").

A Session is a trace with its decoder and analysis (frames, kind/node index,
statistics, series); an opened file is a Session too. A Recorder fills a
Session from its own diagnostics connection in a background thread: it
fetches every 100 ms (at once again while the plugin has more), polls status
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
from .stats import Analysis

FETCH_INTERVAL = 0.1
STATUS_INTERVAL = 0.5
RECONNECT_INTERVAL = 1.0
TOO_OLD = ("the CANopen plugin on the runtime is too old for traces; update it (install-stock.sh) and upload "
           "again")


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


class Recorder:
    """state: idle, connecting, recording, no_bus, reconnecting, stopped, error."""

    def __init__(self, connect, session, filters=None, error_frames=False, trigger=None, autosave_dir=None,
                 name_prefix="canworks", fetch_interval=FETCH_INTERVAL, status_interval=STATUS_INTERVAL,
                 on_stop=None):
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
        self.state = "idle"
        self.message = ""
        self.saved = []  # auto-saved file paths
        self.status = None  # the latest status answer
        self.offset_us = None  # PC clock - PLC clock (smallest seen)
        self.stop_at_us = None  # single mode: stop when frames reach this time
        self.pending_saves = []  # [(hit_us, until_us)]
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
               "lost": sum(n for _, n in t.lost), "kernel_drops": t.kernel_drops}
        return out

    # -- the loop -------------------------------------------------------------
    def _run(self):
        client = None
        next_seq = 0
        last_status = 0.0
        try:
            while not self._stop.is_set():
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
                        if e.kind == "refused" and "no bus" in str(e):
                            self.state, self.message = "no_bus", "no CANopen session on the runtime (waiting)"
                        else:
                            self.state = "reconnecting" if len(self.session.trace) else "connecting"
                            self.message = str(e)
                        self._stop.wait(RECONNECT_INTERVAL)
                        continue
                    with self.session.lock:
                        meta = self.session.trace.meta
                        # The network the trace records (a plugin with
                        # several networks names it; an older one does not).
                        if r.get("network"):
                            meta.setdefault("network", r["network"])
                        meta.setdefault("interface", r.get("interface"))
                        if r.get("bitrate"):
                            meta["bitrate"] = r["bitrate"]
                            self.session.analysis.bitrate = r["bitrate"]
                        if len(self.session.trace):
                            # Reconnected: whatever happened meanwhile is not in the trace.
                            self.session.feed([Frame(int(time.time() * 1e6) - (self.offset_us or 0), 0, gap=True)])
                    next_seq = int(r.get("next") or 0)
                    self.state, self.message = "recording", ""
                try:
                    more = self._fetch(client, next_seq)
                    next_seq = more[0]
                    now = time.monotonic()
                    if now - last_status >= self.status_interval:
                        last_status = now
                        self._poll_status(client)
                except diag.DiagError as e:
                    client.close()
                    client = None
                    self.state, self.message = "reconnecting", str(e)
                    continue
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
                    client.trace_stop()
                except diag.DiagError:
                    pass
                client.close()
            self._autosave_due(force=True)
            if self.state != "error":
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
