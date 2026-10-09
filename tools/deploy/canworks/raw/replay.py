"""Replay of a recorded trace onto a bus (spec canopen-online-diagnostics,
"Replay"): reading the file, the timing plan, batches for the plugin's
`replay` op and playing on a PC adapter through python-can."""

import os
import re
import time

from ..bustrace import formats
from ..bustrace.model import Frame

MAX_RATE = 1000       # frames per second, on the plugin and on an adapter
BATCH = 500           # frames per `replay` request


class ReplayError(ValueError):
    pass


def read_trc(text):
    """The data and remote frames of a PEAK .trc file (versions 1.x and 2.x)."""
    frames = []
    columns = None
    t0_ms = None
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith(";"):
            m = re.match(r";\$COLUMNS=(.*)", line)
            if m:
                columns = [c.strip() for c in m.group(1).split(",")]
            continue
        parts = line.split()
        try:
            if columns:
                f = _trc2(parts, columns)
            else:
                f = _trc1(parts)
        except (ValueError, IndexError):
            raise ReplayError("cannot read this .trc line: %s" % line[:80])
        if f is None:
            continue
        ms, can_id, ext, rtr, dlc, data = f
        if t0_ms is None:
            t0_ms = ms
        frames.append(Frame(round((ms - t0_ms) * 1000), can_id, data, ext=ext, rtr=rtr, dlc=dlc))
    return frames


def _trc2(parts, columns):
    get = {c: i for i, c in enumerate(columns)}
    typ = parts[get["T"]] if "T" in get else "DT"
    if typ not in ("DT", "RR", "FD", "FB", "FE", "BI", "RX", "TX"):
        return None  # error, event and status records
    if typ in ("FD", "FB", "FE", "BI"):
        raise ReplayError("CAN FD frames cannot be replayed (classic CAN only)")
    ms = float(parts[get["O"]])
    cid_text = parts[get["I"]]
    can_id = int(cid_text, 16)
    ext = len(cid_text) > 4 or can_id > 0x7FF
    dlc = int(parts[get["l"]] if "l" in get else parts[get["L"]])
    rtr = typ == "RR"
    start = get.get("D", len(parts))
    data = bytes(int(b, 16) for b in parts[start:start + (0 if rtr else dlc)])
    return ms, can_id, ext, rtr, dlc, data


def _trc1(parts):
    # "1)  1059.9  Rx  0300  8  00 00 ..." or "1)  1059.9  Rx  0300  1  RTR"
    if not parts[0].endswith(")"):
        return None
    ms = float(parts[1])
    cid_text = parts[3]
    can_id = int(cid_text, 16)
    dlc = int(parts[4])
    rtr = len(parts) > 5 and parts[5] == "RTR"
    data = b"" if rtr else bytes(int(b, 16) for b in parts[5:5 + dlc])
    return ms, can_id, len(cid_text) > 4, rtr, dlc, data


def load(path):
    """The frames of a recorded trace: .trc, .asc, candump log, pcapng or a
    canworks trace."""
    if os.path.splitext(path)[1].lower() == ".trc":
        with open(path, encoding="latin-1") as f:
            return read_trc(f.read())
    try:
        return list(formats.read_file(path))
    except formats.FormatError as e:
        raise ReplayError(str(e))


def plan(frames, rate=None):
    """[(offset_us from the first frame, frame)] of the frames to send: error
    frames and loss markers are left out. With `rate` (frames per second) the
    frames go out evenly at that rate instead of with their recorded spacing.
    A plan faster than MAX_RATE frames per second over any second is refused."""
    if rate is not None and not 0 < rate <= MAX_RATE:
        raise ReplayError("--rate must be above 0 and at most %d frames per second" % MAX_RATE)
    sendable = [f for f in frames if not f.err]
    if not sendable:
        raise ReplayError("the trace has no data or remote frames")
    out = []
    t0 = sendable[0].time_us
    for i, f in enumerate(sendable):
        off = round(i * 1e6 / rate) if rate else f.time_us - t0
        out.append((off, f))
    # Recorded traffic above the limit: say so instead of silently stretching it.
    lo = 0
    for hi in range(len(out)):
        while out[hi][0] - out[lo][0] >= 1000000:
            lo += 1
        if hi - lo + 1 > MAX_RATE:
            raise ReplayError("the trace has more than %d frames in one second (at %.3f s); replay it with --rate"
                              % (MAX_RATE, out[hi][0] / 1e6))
    return out


def frame_json(f):
    d = {"id": f.can_id, "dlc": f.dlc}
    if f.ext:
        d["extended"] = True
    if f.rtr:
        d["rtr"] = True
    else:
        d["data"] = f.data.hex()
    return d


def batches(p, size=BATCH):
    """The plan as `replay` request bodies: [{"frames": [{t_us, id, ...}]}],
    times relative to the start of the replay."""
    out = []
    for k in range(0, len(p), size):
        out.append({"frames": [dict(frame_json(f), t_us=off) for off, f in p[k:k + size]]})
    return out


def play_on_bus(bus, p, loop=False, stop=None, clock=time.monotonic, sleep=time.sleep):
    """Sends the plan on a python-can bus with its timing; `stop()` true ends
    it. Returns the number of frames sent."""
    import can
    sent = 0
    while True:
        start = clock()
        for off, f in p:
            if stop and stop():
                return sent
            wait = start + off / 1e6 - clock()
            if wait > 0:
                sleep(wait)
            bus.send(can.Message(arbitration_id=f.can_id, is_extended_id=f.ext, is_remote_frame=f.rtr,
                                 dlc=f.dlc, data=b"" if f.rtr else f.data))
            sent += 1
        if not loop:
            return sent
        # The next round keeps the recorded gap of one frame period.
        if len(p) > 1:
            sleep(max(0.0, (p[-1][0] - p[-2][0]) / 1e6))
