"""What the trace view shows next to the frames (canopen-bus-trace:
"Trace statistics", "Graphs"): a per-frame kind/node index for display
filters, per-identifier counts and cycle times, frame rate and estimated bus
load per 100 ms, and the time series of decoded PDO signals and of the
status values the recorder polls.

Analysis.feed() takes frames in order, so the recorder updates it while
recording and an opened file is fed once.
"""

from array import array

from .decode import KINDS

BUCKET_US = 100_000
KIND_CODE = {k: i for i, k in enumerate(KINDS)}


def frame_bits(f):
    """Estimated bits on the wire: the frame, the 3-bit interframe space and
    half the worst-case stuff bits (an estimate, not a measurement)."""
    if f.gap:
        return 0
    if f.err:
        return 14 + 8 + 3  # error flag, delimiter, intermission
    n = 0 if f.rtr else len(f.data)
    if f.ext:
        base, stuffable = 67 + 8 * n, 54 + 8 * n
    else:
        base, stuffable = 47 + 8 * n, 34 + 8 * n
    return base + (stuffable - 1) // 4 // 2


class IdStats:
    __slots__ = ("can_id", "ext", "count", "first_us", "last_us", "min_us", "max_us", "sum_us", "data", "name",
                 "kind", "node", "tx")

    def __init__(self, f):
        self.can_id, self.ext = (-1, False) if f.err else (f.can_id, f.ext)
        self.count = 0
        self.first_us = self.last_us = f.time_us
        self.min_us = self.max_us = None
        self.sum_us = 0
        self.data = b""
        self.name = self.kind = ""
        self.node = None
        self.tx = False

    def add(self, f, d):
        if self.count:
            dt = f.time_us - self.last_us
            self.min_us = dt if self.min_us is None else min(self.min_us, dt)
            self.max_us = dt if self.max_us is None else max(self.max_us, dt)
            self.sum_us += dt
        self.count += 1
        self.last_us = f.time_us
        self.data = f.data
        self.tx = f.tx
        if d is None:
            return
        if d.kind == "tp":
            # A J1939 transport identifier is named after its message (TP.CM,
            # TP.DT), not after the step its last frame was (RTS, End of message ACK).
            base = d.name.split(" ", 1)[0]
            if not self.name.startswith(base):
                self.name = base
            self.kind, self.node = d.kind, d.node
        elif self.kind == "tp":
            # The message a TP.DT session carried, decoded on its last packet.
            self.name = "%s of %s" % (self.name.split(" ", 1)[0], d.name)
        else:
            self.name, self.kind, self.node = d.name, d.kind, d.node

    def as_dict(self):
        avg = self.sum_us / (self.count - 1) if self.count > 1 else None
        id_text = "error" if self.can_id < 0 else ("%08X" if self.ext else "%03X") % self.can_id
        return {"id": self.can_id, "id_text": id_text, "ext": self.ext,
                "count": self.count, "name": self.name, "kind": self.kind, "node": self.node,
                "dir": "Tx" if self.tx else "Rx", "data": " ".join("%02X" % b for b in self.data),
                "cycle_min_ms": None if self.min_us is None else self.min_us / 1000.0,
                "cycle_avg_ms": None if avg is None else avg / 1000.0,
                "cycle_max_ms": None if self.max_us is None else self.max_us / 1000.0,
                "last_us": self.last_us}


class Series:
    __slots__ = ("key", "label", "node", "kind", "times", "values")

    def __init__(self, key, label, node=None, kind="signal"):
        self.key, self.label, self.node, self.kind = key, label, node, kind
        self.times = array("q")
        self.values = array("d")

    def add(self, time_us, value):
        try:
            v = float(value)
        except (TypeError, ValueError):
            return
        self.times.append(int(time_us))
        self.values.append(v)

    def range(self, start_us=None, end_us=None, points=None):
        """[[t_us...], [v...]] in a time range, decimated to about `points`
        points by keeping each bucket's first, min and max (and last)."""
        import bisect
        a = 0 if start_us is None else bisect.bisect_left(self.times, start_us)
        b = len(self.times) if end_us is None else bisect.bisect_right(self.times, end_us)
        # One point before the range so a step line starts at its left edge.
        if a > 0:
            a -= 1
        ts, vs = self.times[a:b], self.values[a:b]
        n = len(ts)
        if not points or n <= points * 2:
            return [list(ts), list(vs)]
        step = n / float(points)
        out_t, out_v = [], []
        i = 0
        while i < n:
            j = min(n, int(i + step) or i + 1)
            if j <= i:
                j = i + 1
            seg = range(i, j)
            lo = min(seg, key=lambda k: vs[k])
            hi = max(seg, key=lambda k: vs[k])
            for k in sorted({i, lo, hi, j - 1}):
                out_t.append(ts[k])
                out_v.append(vs[k])
            i = j
        return [out_t, out_v]


class Analysis:
    def __init__(self, decoder, bitrate=None):
        self.decoder = decoder
        self.bitrate = bitrate or 0
        self.kinds = bytearray()   # per frame: KIND_CODE
        self.nodes = bytearray()   # per frame: node id or 0
        self.ids = {}              # (can_id, ext) -> IdStats
        self.buckets = {}          # bucket index -> [frames, bits]
        self.series = {}           # key -> Series
        self.frames = 0
        self.error_frames = 0
        self.first_us = None
        self.last_us = None
        for key, label, node in decoder.signal_keys():
            self.series[key] = Series(key, label, node, "signal")
        decoder.reset()

    def ensure_series(self, key, label, node=None, kind="status"):
        s = self.series.get(key)
        if s is None:
            s = self.series[key] = Series(key, label, node, kind)
        return s

    def feed(self, f, on_decoded=None):
        d = self.decoder.decode(f)
        self.kinds.append(KIND_CODE[d.kind])
        self.nodes.append(d.node if isinstance(d.node, int) and 0 <= d.node < 256 else 0)
        if f.gap:
            return d
        self.frames += 1
        if f.err:
            self.error_frames += 1
        if self.first_us is None:
            self.first_us = f.time_us
        self.last_us = f.time_us
        key = (-1, False) if f.err else (f.can_id, f.ext)
        st = self.ids.get(key)
        if st is None:
            st = self.ids[key] = IdStats(f)
        st.add(f, d)
        b = self.buckets.setdefault(f.time_us // BUCKET_US, [0, 0])
        b[0] += 1
        b[1] += frame_bits(f)
        for skey, value in d.signals:
            s = self.series.get(skey)
            if s is None and skey.startswith("emcy."):
                s = self.ensure_series(skey, "EMCY code node %s" % skey[5:], int(skey[5:]), "event")
            elif s is None and skey.startswith("sdo_abort."):
                s = self.ensure_series(skey, "SDO abort node %s" % skey[10:], int(skey[10:]), "event")
            if s is not None:
                s.add(f.time_us, value)
        if on_decoded:
            on_decoded(f, d)
        return d

    def drop_front(self, n):
        """The trace dropped its n oldest frames."""
        del self.kinds[:n]
        del self.nodes[:n]

    # -- views --------------------------------------------------------------
    def rate_series(self, start_us=None, end_us=None):
        """[[bucket start us], [frames/s], [load %]]."""
        keys = sorted(self.buckets)
        if start_us is not None:
            keys = [k for k in keys if (k + 1) * BUCKET_US > start_us]
        if end_us is not None:
            keys = [k for k in keys if k * BUCKET_US <= end_us]
        if not keys:
            return [[], [], []]
        ts, rate, load = [], [], []
        k = keys[0]
        last = keys[-1]
        while k <= last:
            frames, bits = self.buckets.get(k, (0, 0))
            ts.append(k * BUCKET_US)
            rate.append(frames * 1e6 / BUCKET_US)
            load.append(100.0 * bits * 1e6 / BUCKET_US / self.bitrate if self.bitrate else 0.0)
            k += 1
        return [ts, rate, load]

    def summary(self, lost=0, kernel_drops=0, window_s=1.0):
        """Totals and the rate and load over the last `window_s`."""
        rate = load = 0.0
        if self.last_us is not None:
            end = self.last_us // BUCKET_US
            n = max(1, int(window_s * 1e6 / BUCKET_US))
            frames = bits = 0
            for k in range(end - n + 1, end + 1):
                b = self.buckets.get(k)
                if b:
                    frames += b[0]
                    bits += b[1]
            rate = frames / (n * BUCKET_US / 1e6)
            load = 100.0 * bits / (n * BUCKET_US / 1e6) / self.bitrate if self.bitrate else None
        return {"frames": self.frames, "error_frames": self.error_frames, "lost": lost, "kernel_drops": kernel_drops,
                "rate": rate, "load": load, "bitrate": self.bitrate or None,
                "first_us": self.first_us, "last_us": self.last_us}

    def id_table(self):
        return [s.as_dict() for s in sorted(self.ids.values(), key=lambda s: (s.can_id < 0, s.ext, s.can_id))]

    def series_list(self):
        return [{"key": s.key, "label": s.label, "node": s.node, "kind": s.kind, "points": len(s.times)}
                for s in self.series.values()]
