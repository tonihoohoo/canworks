"""Trace records: the plugin's 24-byte TraceRecord (plugin/src/trace_capture.h),
kept packed so a trace of millions of frames stays small."""

import bisect
import struct
from array import array

RECORD = struct.Struct("<QIBB2x8s")  # time_us, can_id with flags, dlc, flags, data
RECORD_SIZE = RECORD.size  # 24

EFF = 0x80000000
RTR = 0x40000000
ERR = 0x20000000
ID_MASK = 0x1FFFFFFF

TX = 0x01   # sent from the PLC host
GAP = 0x02  # no frame: capture stopped and restarted here

DEFAULT_LIMIT = 2_000_000


class Frame:
    __slots__ = ("time_us", "raw_id", "dlc", "flags", "data")

    def __init__(self, time_us, can_id, data=b"", ext=False, rtr=False, err=False, tx=False, gap=False, dlc=None):
        self.time_us = int(time_us)
        raw = can_id & ID_MASK
        if ext:
            raw |= EFF
        if rtr:
            raw |= RTR
        if err:
            raw |= ERR
        self.raw_id = raw
        self.data = bytes(data)[:8]
        self.dlc = len(self.data) if dlc is None else min(int(dlc), 8)
        self.flags = (TX if tx else 0) | (GAP if gap else 0)

    @classmethod
    def unpack(cls, buf, offset=0):
        t, raw, dlc, flags, data = RECORD.unpack_from(buf, offset)
        f = cls.__new__(cls)
        f.time_us, f.raw_id, f.flags = t, raw, flags
        f.dlc = min(dlc, 8)
        f.data = b"" if raw & RTR else data[:f.dlc]
        return f

    def pack(self):
        return RECORD.pack(self.time_us, self.raw_id, self.dlc, self.flags, self.data.ljust(8, b"\0"))

    @property
    def can_id(self):
        return self.raw_id & ID_MASK

    @property
    def ext(self):
        return bool(self.raw_id & EFF)

    @property
    def rtr(self):
        return bool(self.raw_id & RTR)

    @property
    def err(self):
        return bool(self.raw_id & ERR)

    @property
    def tx(self):
        return bool(self.flags & TX)

    @property
    def gap(self):
        return bool(self.flags & GAP)

    @property
    def t(self):
        """UTC seconds."""
        return self.time_us / 1e6

    def id_text(self):
        return ("%08X" if self.ext else "%03X") % self.can_id

    def data_text(self):
        return " ".join("%02X" % b for b in self.data)

    def __eq__(self, other):
        return isinstance(other, Frame) and self.pack() == other.pack()

    def __repr__(self):
        if self.gap:
            return "Frame(gap at %d)" % self.time_us
        return "Frame(%d, %s%s%s, [%s]%s)" % (self.time_us, self.id_text(), " RTR" if self.rtr else "",
                                             " ERR" if self.err else "", self.data_text(), " Tx" if self.tx else "")


class Trace:
    """Frames in time order, packed, with markers and loss notes.

    markers: [{"time_us", "label", "kind"}]; lost: [(time_us, frames)].
    meta: interface, bitrate (bit/s), config_sha256, source, trigger, ...
    """

    def __init__(self, limit=DEFAULT_LIMIT):
        self.buf = bytearray()
        self.times = array("Q")  # time_us per frame, for time lookups
        self.limit = limit
        self.dropped = 0  # oldest frames dropped past the limit
        self.markers = []
        self.lost = []
        self.kernel_drops = 0
        self.meta = {}

    def __len__(self):
        return len(self.times)

    @property
    def start_us(self):
        return self.times[0] if self.times else None

    @property
    def end_us(self):
        return self.times[-1] if self.times else None

    def append(self, frame):
        self.append_packed(frame.pack())

    def append_packed(self, data):
        """Packed records (a multiple of 24 bytes)."""
        n = len(data) // RECORD_SIZE
        if not n:
            return
        self.buf += data[:n * RECORD_SIZE]
        self.times.extend(struct.unpack_from("<Q", data, i * RECORD_SIZE)[0] for i in range(n))
        if len(self.times) > self.limit:
            # Drop a tenth more than needed so the copy happens rarely.
            drop = len(self.times) - self.limit + self.limit // 10
            drop = min(drop, len(self.times))
            del self.buf[:drop * RECORD_SIZE]
            del self.times[:drop]
            self.dropped += drop

    def extend(self, frames):
        self.append_packed(b"".join(f.pack() for f in frames))

    def frame(self, i):
        return Frame.unpack(self.buf, i * RECORD_SIZE)

    def __getitem__(self, i):
        if isinstance(i, slice):
            return [self.frame(k) for k in range(*i.indices(len(self)))]
        if i < 0:
            i += len(self)
        if not 0 <= i < len(self):
            raise IndexError(i)
        return self.frame(i)

    def __iter__(self):
        for i in range(len(self)):
            yield self.frame(i)

    def index_at(self, time_us):
        """First frame at or after time_us."""
        return bisect.bisect_left(self.times, time_us)

    def range(self, start_us=None, end_us=None):
        """(first, end) frame indices for a time range (inclusive start, inclusive end)."""
        a = 0 if start_us is None else bisect.bisect_left(self.times, start_us)
        b = len(self) if end_us is None else bisect.bisect_right(self.times, end_us)
        return a, b

    def frames(self, start_us=None, end_us=None):
        a, b = self.range(start_us, end_us)
        for i in range(a, b):
            yield self.frame(i)

    def sub(self, start_us=None, end_us=None):
        """A new Trace with the frames, markers and loss notes of a time range."""
        a, b = self.range(start_us, end_us)
        t = Trace(limit=max(self.limit, b - a))
        t.buf = bytearray(self.buf[a * RECORD_SIZE:b * RECORD_SIZE])
        t.times = self.times[a:b]
        lo = start_us if start_us is not None else float("-inf")
        hi = end_us if end_us is not None else float("inf")
        t.markers = [dict(m) for m in self.markers if lo <= m["time_us"] <= hi]
        t.lost = [x for x in self.lost if lo <= x[0] <= hi]
        t.meta = dict(self.meta)
        return t

    def add_marker(self, time_us, label, kind="marker"):
        self.markers.append({"time_us": int(time_us), "label": str(label), "kind": kind})
        self.markers.sort(key=lambda m: m["time_us"])

    def clear(self):
        self.buf = bytearray()
        self.times = array("Q")
        self.markers = []
        self.lost = []
        self.dropped = 0
        self.kernel_drops = 0


def unpack_records(data):
    """Frames from packed records."""
    return [Frame.unpack(data, i * RECORD_SIZE) for i in range(len(data) // RECORD_SIZE)]
