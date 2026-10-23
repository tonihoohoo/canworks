"""Replay of a recorded trace onto a bus (spec canopen-online-diagnostics,
"Replay"): reading the file, the timing plan, batches for the bridge's
`replay` op and playing on a PC adapter through python-can."""

import os
import re
import time

from ..bustrace import formats
from ..bustrace.model import Frame

MAX_RATE = 1000       # frames per second, on the bridge and on an adapter
BATCH = 500           # frames per `replay` request
MAX_FRAMES = 200000   # frames of one replay through the bridge


class ReplayError(ValueError):
    pass


TRC_VERSIONS = ("1.0", "1.1", "2.0", "2.1")
# Version 2.0 has no $COLUMNS line: its fixed layout.
TRC2_COLUMNS = ["N", "O", "T", "I", "d", "l", "D"]


def read_trc(text):
    """The data and remote frames of a PEAK .trc file, versions 1.0, 1.1, 2.0
    and 2.1; the layout follows ;$FILEVERSION (a file without one is 1.0 or
    1.1, told by its Rx/Tx column). Other versions, lines it cannot read and
    lines whose data bytes do not match their DLC are refused."""
    frames = []
    version = None
    columns = None
    t0_ms = None
    for n, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        if line.startswith(";"):
            m = re.match(r";\$FILEVERSION=(\S+)", line)
            if m:
                version = m.group(1)
                if version not in TRC_VERSIONS:
                    raise ReplayError("PEAK .trc version %s cannot be replayed (versions %s)"
                                      % (version, ", ".join(TRC_VERSIONS)))
            m = re.match(r";\$COLUMNS=(.*)", line)
            if m:
                columns = [c.strip() for c in m.group(1).split(",")]
            continue
        parts = line.split()
        try:
            if columns or (version or "").startswith("2."):
                f = _trc2(parts, columns or TRC2_COLUMNS)
            else:
                f = _trc1(parts, version)
        except (ValueError, IndexError, KeyError) as e:
            raise ReplayError("cannot read .trc line %d (%s): %s" % (n, e, line[:80]))
        if f is None:
            continue
        ms, can_id, ext, rtr, dlc, data = f
        if t0_ms is None:
            t0_ms = ms
        frames.append(Frame(round((ms - t0_ms) * 1000), can_id, data, ext=ext, rtr=rtr, dlc=dlc))
    return frames


def _data(parts, rtr, dlc):
    if not 0 <= dlc <= 8:
        raise ValueError("DLC %d" % dlc)
    if rtr:
        return b""
    if len(parts) != dlc:
        raise ValueError("%d data bytes for DLC %d" % (len(parts), dlc))
    return bytes(int(b, 16) for b in parts)


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
    return ms, can_id, ext, rtr, dlc, _data(parts[start:], rtr, dlc)


def _trc1(parts, version):
    # 1.1: "1)  1059.9  Rx  0300  8  00 00 ..." or "1)  1059.9  Rx  0300  1  RTR";
    # 1.0: "1)  1059  0300  8  00 00 ..." (no direction column).
    if not parts[0].endswith(")"):
        return None
    has_dir = parts[2] in ("Rx", "Tx")
    if version == "1.1" and not has_dir:
        if parts[2] in ("Warng", "Error"):
            return None  # bus state records
        raise ValueError("no Rx/Tx column in a version 1.1 line")
    if version == "1.0" and has_dir:
        raise ValueError("an Rx/Tx column in a version 1.0 line")
    k = 3 if has_dir else 2
    ms = float(parts[1])
    cid_text = parts[k]
    can_id = int(cid_text, 16)
    dlc = int(parts[k + 1])
    rtr = parts[k + 2:] == ["RTR"]
    return ms, can_id, len(cid_text) > 4, rtr, dlc, _data(parts[k + 2:], rtr, dlc)


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


def plan(frames, rate=None, loop=False):
    """[(offset_us from the first frame, frame)] of the frames to send: error
    frames and loss markers are left out. With `rate` (frames per second) the
    frames go out evenly at that rate instead of with their recorded spacing.
    A plan faster than MAX_RATE frames per second over any second is refused;
    with `loop` the check covers the plan repeated (as `play` repeats it), and
    a plan shorter than 1 s needs `rate`."""
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
    if loop and not rate and out[-1][0] < 1000000:
        raise ReplayError("the trace is shorter than 1 s; --loop needs --rate for it")
    # Recorded traffic above the limit: say so instead of silently stretching it.
    # Looping, two passes cover every second (a looped plan lasts 1 s or more,
    # or goes out evenly at `rate`).
    check = out
    if loop:
        period = out[-1][0] + loop_gap_us(out, rate)
        check = out + [(off + period, f) for off, f in out]
    lo = 0
    for hi in range(len(check)):
        while check[hi][0] - check[lo][0] >= 1000000:
            lo += 1
        if hi - lo + 1 > MAX_RATE:
            raise ReplayError("the trace has more than %d frames in one second (at %.3f s%s); replay it with --rate"
                              % (MAX_RATE, check[hi][0] / 1e6, ", looping" if loop else ""))
    return out


def loop_gap_us(p, rate=None):
    """The wait between two loops of the plan: one frame period (the recorded
    gap of the last two frames, or 1/rate), at least 1 ms."""
    if rate:
        gap = 1e6 / rate
    elif len(p) > 1:
        gap = p[-1][0] - p[-2][0]
    else:
        gap = 0
    return max(1000, round(gap))


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


def play_on_bus(bus, p, loop=False, stop=None, clock=time.monotonic, sleep=time.sleep, gap_us=None):
    """Sends the plan on a python-can bus with its timing; `stop()` true ends
    it. Returns the number of frames sent."""
    import can

    def send(f):
        bus.send(can.Message(arbitration_id=f.can_id, is_extended_id=f.ext, is_remote_frame=f.rtr,
                             dlc=f.dlc, data=b"" if f.rtr else f.data))

    return play(send, p, loop, stop, clock, sleep, gap_us)


def play(send, p, loop=False, stop=None, clock=time.monotonic, sleep=time.sleep, gap_us=None):
    """Calls send(frame) for each frame of the plan with its timing; `stop()`
    true ends it. With `loop` the plan starts again `gap_us` (default
    loop_gap_us) after its last frame, and the frames sent since the first
    loop never run ahead of MAX_RATE per second (one second of burst).
    Returns the number of frames sent."""
    sent = 0
    gap = (loop_gap_us(p) if gap_us is None else max(1000, gap_us)) / 1e6
    first = start = clock()
    while True:
        for off, f in p:
            if stop and stop():
                return sent
            wait = start + off / 1e6 - clock()
            if loop:
                wait = max(wait, first + (sent + 1 - MAX_RATE) / MAX_RATE - clock())
            if wait > 0:
                sleep(wait)
            send(f)
            sent += 1
        if not loop:
            return sent
        # The next round keeps one frame period after the last frame, and does
        # not catch up when this one ran late.
        start = max(start + p[-1][0] / 1e6 + gap, clock())
