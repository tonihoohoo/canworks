"""Trace files (canopen-bus-trace: "Save and open traces", "Export formats").

Writers: pcapng (native save, SocketCAN link type with our metadata),
candump log, Vector ASC, Vector BLF, PEAK TRC 2.1, CSV and signals CSV.
Readers: pcapng (and classic pcap) with SocketCAN link type, candump log,
Vector ASC. Standard library only; python-can and Wireshark open what this
writes (checked in tests/test_bustrace.py).

Gap records (capture restarted) are not frames: pcapng keeps them in its
metadata, the other formats leave them out.
"""

import datetime as dt
import io
import json
import os
import re
import struct
import tempfile
import zlib

from .. import __version__
from .model import EFF, ERR, ID_MASK, RTR, Frame, Trace

# extension -> (format id, label). Open: the formats read_file() reads.
FORMATS = {
    "pcapng": ("pcapng", "pcapng (Wireshark)"),
    "log": ("candump", "candump log (can-utils, SavvyCAN, python-can)"),
    "asc": ("asc", "Vector ASC (CANalyzer, CANoe)"),
    "blf": ("blf", "Vector BLF (CANalyzer, CANoe)"),
    "trc": ("trc", "PEAK TRC 2.1 (PCAN-View, PCAN-Explorer)"),
    "csv": ("csv", "CSV with decoded values"),
}
OPEN_FORMATS = ("pcapng", "pcap", "log", "asc")
META_VERSION = 1


class FormatError(Exception):
    pass


def format_of(path, fmt=None):
    """The format id for a path (by extension) or an explicit name."""
    if fmt:
        fmt = fmt.lower()
        for ext, (fid, _) in FORMATS.items():
            if fmt in (ext, fid):
                return fid
        raise FormatError("unknown trace format %r (known: %s)" % (fmt, ", ".join(sorted(FORMATS))))
    ext = os.path.splitext(path)[1].lower().lstrip(".")
    if ext in FORMATS:
        return FORMATS[ext][0]
    if ext == "pcap":
        return "pcapng"
    raise FormatError("cannot tell the trace format of %s from its extension (use .pcapng, .log, .asc, .blf, .trc "
                      "or .csv)" % os.path.basename(path))


def _frames(trace_or_frames):
    for f in trace_or_frames:
        if not f.gap:
            yield f


def _first_time(frames):
    for f in frames:
        return f.time_us
    return None


# ---------------------------------------------------------------------------
# candump log

def write_candump(trace, out, interface=None):
    iface = interface or (trace.meta.get("interface") if isinstance(trace, Trace) else None) or "can0"
    for f in _frames(trace):
        if f.err:
            cid = "%08X" % (f.can_id | ERR)
        else:
            cid = ("%08X" if f.ext else "%03X") % f.can_id
        if f.rtr:
            body = "R%X" % f.dlc if f.dlc else "R"  # can-utils: R and the DLC when not 0
        else:
            body = f.data.hex().upper()
        out.write("(%d.%06d) %s %s#%s %s\n" % (f.time_us // 1000000, f.time_us % 1000000, iface, cid, body,
                                               "T" if f.tx else "R"))


_CANDUMP = re.compile(r"^\((\d+)\.(\d+)\)\s+(\S+)\s+([0-9A-Fa-f]+)#(#?)([0-9A-Fa-f.R]*)\s*([TR])?\s*$")


def read_candump(text):
    t = Trace()
    iface = None
    for line in text.splitlines():
        m = _CANDUMP.match(line.strip())
        if not m:
            continue
        sec, frac, iface, cid, fd, body, direction = m.groups()
        if fd:
            continue  # CAN FD: not supported
        time_us = int(sec) * 1000000 + int((frac + "000000")[:6])
        raw = int(cid, 16)
        err = bool(raw & ERR) and len(cid) == 8
        ext = len(cid) == 8 and not err
        rtr = body.startswith("R")
        if rtr:
            dlc = int(body[1:]) if body[1:].isdigit() else 0
            data = b""
        else:
            data = bytes.fromhex(body.replace(".", ""))
            dlc = None
        t.append(Frame(time_us, raw & ID_MASK, data, ext=ext, rtr=rtr, err=err, tx=direction == "T", dlc=dlc))
    if iface:
        t.meta["interface"] = iface
    return t


# ---------------------------------------------------------------------------
# Vector ASC

def _asc_date(time_us):
    d = dt.datetime.fromtimestamp(time_us / 1e6, dt.timezone.utc)
    return d.strftime("%a %b %d %I:%M:%S.") + "%03d" % (d.microsecond // 1000) + d.strftime(" %p %Y")


def write_asc(trace, out, channel=1):
    frames = list(_frames(trace))
    t0 = frames[0].time_us if frames else (trace.start_us if isinstance(trace, Trace) and trace.start_us else 0)
    head = _asc_date(t0)
    out.write("date %s\nbase hex  timestamps absolute\ninternal events logged\n// version 9.0.0\n" % head)
    out.write("// openplc-canopen-diag %s\n" % __version__)
    out.write("Begin Triggerblock %s\n   0.000000 Start of measurement\n" % head)
    for f in frames:
        ts = (f.time_us - t0) / 1e6
        if f.err:
            out.write("%11.6f %d  ErrorFrame\n" % (ts, channel))
            continue
        cid = ("%Xx" % f.can_id) if f.ext else ("%X" % f.can_id)
        d = "Tx" if f.tx else "Rx"
        if f.rtr:
            out.write("%11.6f %d  %-15s %s   r %X\n" % (ts, channel, cid, d, f.dlc))
        else:
            out.write("%11.6f %d  %-15s %s   d %X %s\n" % (ts, channel, cid, d, f.dlc, f.data_text()))
    out.write("End TriggerBlock\n")


_ASC_DATE_FORMATS = ("%a %b %d %I:%M:%S.%f %p %Y", "%a %b %d %I:%M:%S %p %Y", "%a %b %d %H:%M:%S.%f %Y",
                     "%a %b %d %H:%M:%S %Y")
_ASC_FRAME = re.compile(r"^\s*(\d+\.\d+)\s+(\d+)\s+([0-9A-Fa-f]+)(x?)\s+(Rx|Tx)\s+([dr])\s*([0-9A-Fa-f]*)\s*(.*)$")
_ASC_ERROR = re.compile(r"^\s*(\d+\.\d+)\s+(\d+)\s+ErrorFrame")


def _parse_asc_date(text):
    text = re.sub(r"\s+", " ", text.strip())
    for fmt in _ASC_DATE_FORMATS:
        try:
            d = dt.datetime.strptime(text, fmt).replace(tzinfo=dt.timezone.utc)
            return int(d.timestamp() * 1e6)
        except ValueError:
            pass
    return 0


def read_asc(text):
    t = Trace()
    start = 0
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("date "):
            start = _parse_asc_date(s[5:])
            continue
        m = _ASC_ERROR.match(line)
        if m:
            t.append(Frame(start + int(round(float(m.group(1)) * 1e6)), 0, b"", err=True))
            continue
        m = _ASC_FRAME.match(line)
        if not m:
            continue
        ts, _ch, cid, x, direction, kind, dlc, rest = m.groups()
        dlc = int(dlc or "0", 16)
        if kind == "r":
            data, rtr = b"", True
        else:
            data, rtr = bytes(int(b, 16) for b in rest.split()[:dlc]), False
        t.append(Frame(start + int(round(float(ts) * 1e6)), int(cid, 16), data, ext=bool(x), rtr=rtr,
                       tx=direction == "Tx", dlc=dlc))
    return t


# ---------------------------------------------------------------------------
# PEAK TRC 2.1

def write_trc(trace, out):
    frames = list(_frames(trace))
    t0 = frames[0].time_us if frames else 0
    start = dt.datetime.fromtimestamp(t0 / 1e6, dt.timezone.utc)
    days = t0 / 1e6 / 86400.0 + 25569.0  # OLE automation date
    out.write(";$FILEVERSION=2.1\n;$STARTTIME=%.10f\n;$COLUMNS=N,O,T,I,d,l,D\n;\n" % days)
    out.write(";   Start time: %s.%03d.0\n" % (start.strftime("%d.%m.%Y %H:%M:%S"), start.microsecond // 1000))
    out.write(";   Generated by openplc-canopen-diag %s\n;\n" % __version__)
    for i, f in enumerate(frames, 1):
        ms = (f.time_us - t0) / 1000.0
        if f.err:
            out.write("%7d %13.3f ER %8s %s %d %s\n" % (i, ms, "-", "Rx", len(f.data), f.data_text()))
            continue
        cid = ("%08X" if f.ext else "%04X") % f.can_id
        typ = "RR" if f.rtr else "DT"
        out.write("%7d %13.3f %s %8s %s %d %s\n" % (i, ms, typ, cid, "Tx" if f.tx else "Rx", f.dlc,
                                                   "" if f.rtr else f.data_text()))


# ---------------------------------------------------------------------------
# Vector BLF

_BLF_OBJ = struct.Struct("<4sHHLL")
_BLF_OBJ_V1 = struct.Struct("<LHHQ")
_BLF_CAN = struct.Struct("<HBBL8s")
_BLF_ERR = struct.Struct("<HHLBBBxLLH2x8s")
_BLF_CONTAINER = struct.Struct("<H6xL4x")
_BLF_CONTAINER_MAX = 128 * 1024


def _systime(time_us):
    d = dt.datetime.fromtimestamp(time_us / 1e6, dt.timezone.utc)
    return struct.pack("<8H", d.year, d.month, (d.weekday() + 1) % 7, d.day, d.hour, d.minute, d.second,
                       d.microsecond // 1000)


def write_blf(trace, out):
    frames = list(_frames(trace))
    t0 = frames[0].time_us if frames else 0
    objs = []
    for f in frames:
        ts = (f.time_us - t0) * 1000  # nanoseconds (object flag 2)
        if f.err:
            body = _BLF_ERR.pack(1, 0, 0, 0, 0, f.dlc, 0, f.can_id, 0, f.data.ljust(8, b"\0"))
            otype = 73  # CAN_ERROR_EXT
        else:
            cid = f.can_id | (0x80000000 if f.ext else 0)
            flags = (1 if f.tx else 0) | (0x80 if f.rtr else 0)
            body = _BLF_CAN.pack(1, flags, f.dlc, cid, f.data.ljust(8, b"\0"))
            otype = 1  # CAN_MESSAGE
        hdr = _BLF_OBJ.pack(b"LOBJ", 32, 1, 32 + len(body), otype) + _BLF_OBJ_V1.pack(2, 0, 0, ts)
        objs.append(hdr + body)
    containers = []
    chunk, size = [], 0
    for o in objs + [None]:
        if o is None or size + len(o) > _BLF_CONTAINER_MAX:
            if chunk:
                raw = b"".join(chunk)
                packed = zlib.compress(raw, 6)
                c = _BLF_OBJ.pack(b"LOBJ", 16, 1, 16 + _BLF_CONTAINER.size + len(packed), 10)
                c += _BLF_CONTAINER.pack(2, len(raw)) + packed
                c += b"\0" * (len(c) % 4)
                containers.append(c)
            chunk, size = [], 0
            if o is None:
                break
        chunk.append(o)
        size += len(o)
    body = b"".join(containers)
    uncompressed = sum(len(o) for o in objs)
    head = struct.pack("<4sLBBBBBBBBQQLL", b"LOGG", 144, 5, 0, 0, 0, 2, 6, 8, 1, 144 + len(body), uncompressed,
                       len(objs), 0)
    head += _systime(t0) + _systime(frames[-1].time_us if frames else t0)
    out.write(head.ljust(144, b"\0") + body)


# ---------------------------------------------------------------------------
# pcapng (LINKTYPE_CAN_SOCKETCAN)

LINKTYPE_CAN_SOCKETCAN = 227


def _pad4(b):
    return b + b"\0" * (-len(b) % 4)


def _opt(code, value):
    return struct.pack("<HH", code, len(value)) + _pad4(value)


def _block(btype, body):
    n = 12 + len(body)
    return struct.pack("<II", btype, n) + body + struct.pack("<I", n)


def _meta_of(trace):
    meta = {"openplc_canopen_trace": META_VERSION, "tool": "openplc-canopen-diag %s" % __version__}
    if isinstance(trace, Trace):
        for k, v in trace.meta.items():
            if isinstance(v, (str, int, float, bool, list, dict)) or v is None:
                meta[k] = v
        meta["markers"] = trace.markers
        meta["lost"] = [[t, n] for t, n in trace.lost]
        meta["kernel_drops"] = trace.kernel_drops
        meta["gaps"] = [f.time_us for f in trace if f.gap]
    return meta


def write_pcapng(trace, out, interface=None):
    meta = _meta_of(trace)
    iface = interface or meta.get("interface") or "can0"
    shb_opts = (_opt(1, json.dumps(meta, separators=(",", ":")).encode("utf-8"))
                + _opt(4, ("openplc-canopen-diag %s" % __version__).encode()) + _opt(0, b""))
    out.write(_block(0x0A0D0D0A, struct.pack("<IHHq", 0x1A2B3C4D, 1, 0, -1) + shb_opts))
    idb_opts = _opt(2, iface.encode()) + _opt(9, b"\x06")
    if meta.get("bitrate"):
        idb_opts += _opt(8, struct.pack("<Q", int(meta["bitrate"])))  # if_speed
    out.write(_block(1, struct.pack("<HHI", LINKTYPE_CAN_SOCKETCAN, 0, 16) + idb_opts + _opt(0, b"")))
    for f in _frames(trace):
        cid = f.can_id | (EFF if f.ext else 0) | (RTR if f.rtr else 0) | (ERR if f.err else 0)
        pkt = struct.pack(">I", cid) + struct.pack("<BBBB", f.dlc, 0, 0, 0) + f.data.ljust(8, b"\0")
        us = f.time_us
        flags = _opt(2, struct.pack("<I", 2 if f.tx else 1)) + _opt(0, b"")  # epb_flags direction
        body = struct.pack("<IIIII", 0, us >> 32, us & 0xFFFFFFFF, len(pkt), len(pkt)) + _pad4(pkt) + flags
        out.write(_block(6, body))


def _socketcan_frame(pkt, time_us, tx, byteorder=">"):
    if len(pkt) < 8:
        return None
    raw = struct.unpack(byteorder + "I", pkt[:4])[0]
    dlc = min(pkt[4], 8)
    rtr = bool(raw & RTR)
    data = b"" if rtr else pkt[8:8 + dlc]
    return Frame(time_us, raw & ID_MASK, data, ext=bool(raw & EFF) and not raw & ERR, rtr=rtr, err=bool(raw & ERR),
                 tx=tx, dlc=dlc)


def _parse_options(buf, endian):
    opts = {}
    i = 0
    while i + 4 <= len(buf):
        code, length = struct.unpack_from(endian + "HH", buf, i)
        i += 4
        if code == 0:
            break
        opts.setdefault(code, buf[i:i + length])
        i += length + (-length % 4)
    return opts


def read_pcapng(data):
    if len(data) >= 4 and struct.unpack_from("<I", data)[0] in (0xA1B2C3D4, 0xA1B23C4D, 0xD4C3B2A1, 0x4D3CB2A1):
        return _read_pcap(data)
    t = Trace()
    i = 0
    endian = "<"
    ifaces = []  # (linktype, ticks per second)
    meta = None
    while i + 12 <= len(data):
        btype = struct.unpack_from(endian + "I", data, i)[0]
        if btype == 0x0A0D0D0A:
            bom = data[i + 8:i + 12]
            endian = "<" if bom == b"\x4d\x3c\x2b\x1a" else ">"
            ifaces = []
        blen = struct.unpack_from(endian + "I", data, i + 4)[0]
        if blen < 12 or i + blen > len(data):
            raise FormatError("damaged pcapng block at byte %d" % i)
        body = data[i + 8:i + blen - 4]
        if btype == 0x0A0D0D0A:
            opts = _parse_options(body[16:], endian)
            comment = opts.get(1)
            if comment:
                try:
                    m = json.loads(comment.decode("utf-8"))
                    if isinstance(m, dict) and m.get("openplc_canopen_trace"):
                        meta = m
                except ValueError:
                    pass
        elif btype == 1:
            linktype = struct.unpack_from(endian + "H", body, 0)[0]
            opts = _parse_options(body[8:], endian)
            res = opts.get(9, b"\x06")[0]
            tps = 2 ** (res & 0x7F) if res & 0x80 else 10 ** res
            ifaces.append((linktype, tps, (opts.get(2) or b"").decode("utf-8", "replace")))
        elif btype in (6, 3):
            if btype == 6:
                ifid, hi, lo, caplen = struct.unpack_from(endian + "IIII", body, 0)
                pkt = body[20:20 + caplen]
                opts = _parse_options(body[20 + caplen + (-caplen % 4):], endian)
                flags = struct.unpack_from(endian + "I", opts[2])[0] if 2 in opts else 0
                ticks = (hi << 32) | lo
            else:
                ifid, ticks, flags = 0, 0, 0
                pkt = body[4:]
            if ifid < len(ifaces) and ifaces[ifid][0] == LINKTYPE_CAN_SOCKETCAN:
                time_us = ticks * 1000000 // ifaces[ifid][1]
                f = _socketcan_frame(pkt, time_us, (flags & 3) == 2)
                if f:
                    t.append(f)
        i += blen
    if ifaces:
        t.meta["interface"] = ifaces[0][2] or None
    if meta:
        for k in ("network", "interface", "bitrate", "config_sha256", "source", "trigger", "started_utc", "runtime"):
            if meta.get(k) is not None:
                t.meta[k] = meta[k]
        for m in meta.get("markers") or []:
            if isinstance(m, dict) and "time_us" in m:
                t.add_marker(m["time_us"], m.get("label", ""), m.get("kind", "marker"))
        t.lost = [(int(a), int(b)) for a, b in meta.get("lost") or []]
        t.kernel_drops = int(meta.get("kernel_drops") or 0)
        gaps = sorted(int(g) for g in meta.get("gaps") or [])
        if gaps:
            frames = list(t) + [Frame(g, 0, gap=True) for g in gaps]
            frames.sort(key=lambda f: (f.time_us, not f.gap))
            t2 = Trace()
            t2.meta, t2.markers, t2.lost, t2.kernel_drops = t.meta, t.markers, t.lost, t.kernel_drops
            t2.extend(frames)
            t = t2
    return t


def _read_pcap(data):
    magic = struct.unpack_from("<I", data)[0]
    endian = "<" if magic in (0xA1B2C3D4, 0xA1B23C4D) else ">"
    nano = magic in (0xA1B23C4D, 0x4D3CB2A1)
    linktype = struct.unpack_from(endian + "I", data, 20)[0]
    if linktype != LINKTYPE_CAN_SOCKETCAN:
        raise FormatError("pcap link type %d is not SocketCAN (227)" % linktype)
    t = Trace()
    i = 24
    while i + 16 <= len(data):
        sec, frac, caplen, _ = struct.unpack_from(endian + "IIII", data, i)
        pkt = data[i + 16:i + 16 + caplen]
        f = _socketcan_frame(pkt, sec * 1000000 + (frac // 1000 if nano else frac), False)
        if f:
            t.append(f)
        i += 16 + caplen
    return t


# ---------------------------------------------------------------------------
# CSV

def _csv_cell(text):
    text = str(text)
    if any(c in text for c in ',"\n\r'):
        return '"%s"' % text.replace('"', '""')
    return text


def write_csv(trace, out, decoder=None):
    out.write("time_s,utc,dir,id,ext,rtr,err,dlc,data,kind,node,name,decoded\n")
    frames = list(_frames(trace))
    t0 = frames[0].time_us if frames else 0
    decoder = decoder.clone() if decoder else None
    for f in frames:
        d = decoder.decode(f) if decoder else None
        utc = dt.datetime.fromtimestamp(f.time_us / 1e6, dt.timezone.utc).isoformat(timespec="microseconds")
        cells = ["%.6f" % ((f.time_us - t0) / 1e6), utc, "Tx" if f.tx else "Rx", "0x%X" % f.can_id, int(f.ext),
                 int(f.rtr), int(f.err), f.dlc, f.data_text(),
                 d.kind if d else "", d.node if d and d.node else "", d.name if d else "", d.text if d else ""]
        out.write(",".join(_csv_cell(c) for c in cells) + "\n")


def write_signals_csv(series, out, t0_us=None):
    """series: [(name, [(time_us, value)])]. One row per time at which any
    series changes, holding every series' latest value."""
    names = [n for n, _ in series]
    events = []
    for k, (_, points) in enumerate(series):
        for t, v in points:
            events.append((t, k, v))
    events.sort(key=lambda e: (e[0], e[1]))
    if t0_us is None:
        t0_us = events[0][0] if events else 0
    out.write(",".join(["time_s", "utc"] + [_csv_cell(n) for n in names]) + "\n")
    current = [""] * len(names)
    i = 0
    while i < len(events):
        t = events[i][0]
        while i < len(events) and events[i][0] == t:
            current[events[i][1]] = events[i][2]
            i += 1
        utc = dt.datetime.fromtimestamp(t / 1e6, dt.timezone.utc).isoformat(timespec="microseconds")
        out.write(",".join(["%.6f" % ((t - t0_us) / 1e6), utc] + [_csv_cell(_num(v)) for v in current]) + "\n")


def _num(v):
    if isinstance(v, float):
        return repr(v) if v != int(v) or abs(v) >= 1e15 else str(int(v))
    return str(v)


# ---------------------------------------------------------------------------
# Files

def write(trace, out, fmt, decoder=None):
    """Writes `trace` (a Trace or frames) to a binary file object."""
    if fmt in ("pcapng", "blf"):
        (write_pcapng if fmt == "pcapng" else write_blf)(trace, out)
        return
    text = io.StringIO()
    if fmt == "candump":
        write_candump(trace, text)
    elif fmt == "asc":
        write_asc(trace, text)
    elif fmt == "trc":
        write_trc(trace, text)
    elif fmt == "csv":
        write_csv(trace, text, decoder)
    else:
        raise FormatError("unknown trace format %r" % fmt)
    newline = "\r\n" if fmt in ("asc", "trc") else "\n"
    out.write(text.getvalue().replace("\n", newline).encode("utf-8"))


def write_file(trace, path, fmt=None, decoder=None):
    """Writes through a temporary file and a rename; returns the format id."""
    fmt = format_of(path, fmt)
    folder = os.path.dirname(os.path.abspath(path))
    os.makedirs(folder, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=folder, prefix=".trace-", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as out:
            write(trace, out, fmt, decoder)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return fmt


def read(data, name=""):
    """A Trace from file contents (bytes); the format from the content, then
    the name."""
    if data[:4] in (b"\x0a\x0d\x0d\x0a", b"\xd4\xc3\xb2\xa1", b"\xa1\xb2\xc3\xd4", b"\x4d\x3c\xb2\xa1",
                    b"\xa1\xb2\x3c\x4d"):
        return read_pcapng(data)
    if data[:4] == b"LOGG":
        raise FormatError("BLF files cannot be opened; open a pcapng, candump log or ASC file")
    text = data.decode("utf-8", "replace")
    head = text[:4000]
    if re.search(r"^\(\d+\.\d+\)\s+\S+\s+[0-9A-Fa-f]+#", head, re.M):
        return read_candump(text)
    if re.search(r"^date ", head, re.M) or re.search(r"Begin Triggerblock", head, re.I):
        return read_asc(text)
    ext = os.path.splitext(name)[1].lower()
    if ext == ".log":
        return read_candump(text)
    if ext == ".asc":
        return read_asc(text)
    raise FormatError("%s is not a pcapng, candump log or Vector ASC trace" % (os.path.basename(name) or "the file"))


def read_file(path):
    with open(path, "rb") as f:
        t = read(f.read(), path)
    t.meta.setdefault("source", os.path.basename(path))
    return t
