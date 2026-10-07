"""Bit-level explanation of one CAN frame (canopen-frame-explain; design D1).

    model = explain(frame, decoder, bitrate=500000, context=None)

The model has four layers, JSON-ready:

- "meaning", "about", "notes": one plain sentence, what the message type is
  for, and anything worth knowing about this frame;
- "identifier": every identifier bit with its weight, split into function
  code and node ID for CANopen identifiers;
- "fields": every data bit in exactly one field, in CANopen bit numbering
  (bit 0 is the least significant bit of byte 0). A field has "name",
  "start", "length", "value" (text), "text" (what it means), optionally
  "how" (how the value is put together), "bits" (names of single flags,
  lowest bit first), "object", "object_name", "type", "location",
  "variables" (PDOs), and "group": a number per explained field, or
  "unused" for unused, reserved and padding bits;
- "wire": the frame rebuilt on the wire (wire.py); None for error frames.

`context` is a decoder that has decoded the frames before this one (see
context_for): it gives SDO segments their transfer. The decoder itself is
not changed.
"""

import datetime

from .. import diag
from . import explain_texts as T
from .decode import Decoder, signal_value
from .wire import DEFAULT_BITRATE, wire

LOOKBACK = 4000  # frames decoded before a frame for its SDO context


def hexbytes(data):
    return " ".join("%02X" % b for b in data)


def _num(v, nbytes=None):
    if isinstance(v, float):
        return "%g" % v
    if nbytes:
        return "%d (0x%0*X)" % (v, nbytes * 2, v & ((1 << (nbytes * 8)) - 1))
    return str(v)


def le_how(data, start, length):
    """How a little-endian number is put together from the frame's bytes."""
    if start % 8 or length % 8:
        v = int.from_bytes(bytes(data).ljust(8, b"\0"), "little")
        raw = (v >> start) & ((1 << length) - 1)
        return "bits %d-%d of the frame = %s" % (start, start + length - 1, format(raw, "0%db" % length))
    a, n = start // 8, length // 8
    bs = bytes(data[a:a + n])
    if n == 1:
        return "byte %d = 0x%02X" % (a, bs[0] if bs else 0)
    return "bytes %d-%d = %s, low byte first, so read backwards: 0x%s" % (
        a, a + n - 1, hexbytes(bs), "".join("%02X" % b for b in reversed(bs)))


def obj_text(index, sub, name=None):
    t = "%04Xh:%02X" % (index, sub)
    return t + (" " + name if name else "")


class Fields:
    """Collects the fields of a frame's data and fills the gaps."""

    def __init__(self, data):
        self.data = bytes(data)
        self.items = []

    def bits(self, start, length):
        v = int.from_bytes(self.data.ljust(8, b"\0"), "little")
        return (v >> start) & ((1 << length) - 1)

    def byte(self, k):
        return self.data[k] if k < len(self.data) else 0

    def add(self, name, start, length, value, text, unused=False, **extra):
        if start >= len(self.data) * 8:
            return None
        length = min(length, len(self.data) * 8 - start)
        f = {"name": name, "start": start, "length": length, "value": value, "text": text,
             "group": "unused" if unused else None}
        f.update({k: v for k, v in extra.items() if v is not None})
        self.items.append(f)
        return f

    def unused(self, start, length, name="Not used", text="Not used, sent as 0."):
        aligned = not start % 8 and not length % 8
        return self.add(name, start, length, hexbytes(self.data[start // 8:(start + length) // 8])
                        if aligned else format(self.bits(start, length), "0%db" % length), text, unused=True)

    def done(self, gap_name="Not used", gap_text="Not used."):
        total = len(self.data) * 8
        owner = [None] * total
        for f in self.items:
            for b in range(f["start"], f["start"] + f["length"]):
                if b < total and owner[b] is None:
                    owner[b] = f
        b = 0
        while b < total:
            if owner[b] is None:
                e = b
                while e < total and owner[e] is None and (e == b or e % 8):
                    e += 1
                f = {"name": gap_name, "start": b, "length": e - b, "group": "unused", "text": gap_text,
                     "value": format(self.bits(b, e - b), "0%db" % (e - b))}
                self.items.append(f)
                for k in range(b, e):
                    owner[k] = f
                b = e
            else:
                b += 1
        # byte by byte, and inside a byte from the most significant bit, as the grid shows them
        self.items.sort(key=lambda f: (f["start"] // 8, -(f["start"] % 8 + min(f["length"], 8))))
        g = 0
        for f in self.items:
            if f["group"] is None:
                f["group"] = g
                g += 1
        return self.items


def context_for(trace, index, decoder):
    """A clone of `decoder` that has decoded the SDO frames before frame
    `index` of `trace` (up to LOOKBACK frames back)."""
    ctx = decoder.clone()
    for j in range(max(0, index - LOOKBACK), index):
        f = trace.frame(j)
        if not f.gap and not f.err and not f.ext and 0x581 <= f.can_id <= 0x67F:
            ctx.decode(f)
    return ctx


# -- identifier ---------------------------------------------------------------

def _function(cid):
    for lo, hi, short, kind, what, sender in T.FUNCTIONS:
        if lo <= cid <= hi:
            return short, kind, what, sender
    return None


def _pdo_number(name):
    """("TPDO", 3) from a DBC message name such as node5_TPDO3."""
    tail = name.rsplit("_", 1)[-1]
    for kind in ("TPDO", "RPDO"):
        if tail.startswith(kind) and tail[4:].isdigit():
            return kind, int(tail[4:])
    return None, None


def identifier_layer(f, dec):
    cid = f.can_id
    width = 29 if f.ext else 11
    out = {"width": width, "value": cid, "text_id": f.id_text(), "bits": [], "function_code": None, "node": None,
           "message": None, "what": None, "sender": None, "math": None, "configured": False,
           "priority": T.ARBITRATION}
    split = not f.ext
    for n in range(width - 1, -1, -1):
        part = "id" if not split else ("function" if n >= 7 else "node")
        out["bits"].append({"n": n, "v": (cid >> n) & 1, "part": part, "weight": 1 << n})
    if f.ext:
        out["what"] = "extended identifier, outside the CANopen predefined set"
        return out
    fc, nid = cid >> 7, cid & 0x7F
    out["function_code"], out["node"] = fc, nid
    out["math"] = "0x%03X = %d × 0x80 + %d" % (cid, fc, nid)
    p = dec.pdos.get(cid)
    if p is not None:
        kind, num = _pdo_number(p.name)
        out["message"] = "%s%d" % (kind, num) if kind else p.name
        out["what"] = "process data the node %s" % ("transmits" if p.tx else "receives")
        out["sender"] = "the node" if p.tx else "the PLC"
        out["node_label"] = dec.node_label(p.node) if p.node is not None else None
        if kind and num <= 4 and p.node is not None:
            default = (0x180 if kind == "TPDO" else 0x200) + 0x100 * (num - 1) + p.node
            out["configured"] = default != cid
        else:
            out["configured"] = True
        if out["configured"]:
            out["math"] = None
            out["configured_text"] = ("0x%03X is set in the configuration for %s of %s, so the function code and "
                                      "node ID split does not apply." % (cid, out["message"], out["node_label"]))
        return out
    if cid == dec.time_cob and cid != 0x100:
        out.update(message="TIME", what="time stamp", sender="the TIME producer", configured=True, math=None,
                   configured_text="0x%03X is the configured TIME identifier." % cid)
        return out
    fn = _function(cid)
    if fn is None:
        out["what"] = "not a CANopen predefined identifier"
        out["math"] = None
        return out
    short, kind, what, sender = fn
    out.update(message=short, what=what, sender=sender)
    if kind == "lss":
        out["function_code"] = out["node"] = None
        out["math"] = None
        for b in out["bits"]:
            b["part"] = "id"
    elif kind in ("nmt", "sync", "time"):
        out["node"] = None
        out["math"] = "0x%03X: function code %d, no node ID" % (cid, fc)
    else:
        out["node_label"] = dec.node_label(nid)
    return out


# -- data layers per protocol --------------------------------------------------

def _nmt(F, dec):
    cmd, target = F.byte(0), F.byte(1)
    name, effect = T.NMT_COMMANDS.get(cmd, ("unknown command", "not a CiA 301 NMT command"))
    F.add("Command", 0, 8, "0x%02X = %s" % (cmd, name), "Command specifier: 01h start, 02h stop, 80h enter "
          "pre-operational, 81h reset node, 82h reset communication. This one: %s." % effect)
    who = "all nodes" if target == 0 else dec.node_label(target)
    F.add("Target node", 8, 8, "%d = %s" % (target, who), "The node the command is for; 0 means every node.")
    return "The PLC tells %s: %s (%s)." % (who, name, effect)


def _sync(F, f):
    if f.data:
        F.add("SYNC counter", 0, 8, str(F.byte(0)), "Optional counter (1 up to the overflow value of object 1019h), "
              "so a node can act only on every n-th SYNC.")
        return "SYNC tick number %d from the PLC." % F.byte(0)
    return "SYNC tick from the PLC."


def _time(F):
    ms = F.bits(0, 28)
    days = F.bits(32, 16)
    when = datetime.datetime(1984, 1, 1) + datetime.timedelta(days=days, milliseconds=ms)
    F.add("Milliseconds after midnight", 0, 28, "%d = %s" % (ms, when.strftime("%H:%M:%S.") + "%03d" % (ms % 1000)),
          "28 bits, little-endian.", how=le_how(F.data, 0, 32) + ", lower 28 bits")
    F.add("Reserved", 28, 4, format(F.bits(28, 4), "04b"), "Reserved, 0.", unused=True)
    F.add("Days since 1984-01-01", 32, 16, "%d = %s" % (days, when.strftime("%Y-%m-%d")), "16 bits, little-endian.",
          how=le_how(F.data, 32, 16))
    return "Time stamp: %s." % (when.strftime("%Y-%m-%d %H:%M:%S.") + "%03d" % (ms % 1000))


def _emcy(F, dec, nid):
    who = dec.node_label(nid)
    code = F.bits(0, 16)
    cls = diag.emcy_class(code)
    F.add("Error code", 0, 16, "0x%04X (%s)" % (code, cls),
          "CiA 301 emergency error code. The first hex digit gives the class (here: %s); the device manual or "
          "device profile gives the rest." % cls, how=le_how(F.data, 0, 16))
    reg = F.byte(2)
    names = [n for k, n in enumerate(T.ERROR_REGISTER) if reg >> k & 1]
    F.add("Error register (1001h)", 16, 8, "0x%02X%s" % (reg, " = " + ", ".join(names) if names else ""),
          "A copy of the node's error register at the time of the emergency; each bit flags one kind of error.",
          bits=[{"name": n} for n in T.ERROR_REGISTER])
    if len(F.data) > 3:
        F.add("Manufacturer data", 24, (len(F.data) - 3) * 8, hexbytes(F.data[3:]),
              "Free for the device maker: the device manual says what it means.")
    if code == 0:
        return "%s: all errors are gone (error reset)." % who.capitalize()
    return "%s reports error 0x%04X (%s)." % (who.capitalize(), code, cls)


def _heartbeat(F, f, dec, nid):
    who = dec.node_label(nid)
    if f.rtr:
        return "The PLC asks %s for its state (node guarding remote request)." % who
    st = F.byte(0) & 0x7F
    tog = F.byte(0) >> 7
    name, what = T.NMT_STATES.get(st, ("unknown state", "not a CiA 301 NMT state"))
    F.add("NMT state", 0, 7, "%d = %s" % (st, name), "0 boot-up, 4 STOPPED, 5 OPERATIONAL, 127 PRE-OPERATIONAL. "
          "This one: %s." % what)
    F.add("Toggle bit", 7, 1, str(tog), "Used only by node guarding, where it flips on every answer; always 0 in a "
          "heartbeat.")
    if st == 0:
        return "%s has booted and waits to be configured." % who.capitalize()
    if tog:
        return "%s answers node guarding: %s (toggle 1)." % (who.capitalize(), name)
    return "%s is %s." % (who.capitalize(), name)


def _value(dec, nid, index, sub, data):
    t = dec.object_type(nid, index, sub)
    if t:
        return diag.decode(t, data)["text"], t
    if 0 < len(data) <= 4:
        return _num(int.from_bytes(data, "little"), len(data)), None
    return hexbytes(data) or "(empty)", None


def _obj_name(dec, nid, index, sub):
    eds = dec.eds.get(nid)
    if eds is None:
        return None
    parent, name = eds.object_name(index, sub)
    if parent and name and name != parent:
        return "%s / %s" % (parent, name)
    return name or parent or None


def _mux(F, dec, nid):
    index, sub = F.bits(8, 16), F.byte(3)
    name = _obj_name(dec, nid, index, sub)
    F.add("Index", 8, 16, "0x%04X" % index, T.SDO_BITS["index"], how=le_how(F.data, 8, 16))
    F.add("Subindex", 24, 8, "0x%02X%s" % (sub, " = " + name if name else ""), T.SDO_BITS["sub"])
    return index, sub, obj_text(index, sub, name)


def _cs_field(F, server, cs):
    table = T.SDO_SERVER if server else T.SDO_CLIENT
    name, what = table.get(cs, ("unknown", "not a CiA 301 command specifier"))
    F.add("Server command specifier" if server else "Client command specifier", 5, 3, "%d = %s" % (cs, name),
          T.SDO_BITS["scs" if server else "ccs"] + " This one: %s." % what)
    return name


def _sdo(F, f, dec, nid, server, ctx):
    d = F.data
    who = dec.node_label(nid)
    notes = []
    if not d:
        return "An empty SDO frame (malformed).", notes
    cmd, cs = d[0], d[0] >> 5
    state = ctx.sdo_state if ctx is not None else {}
    blk = state.get((nid, "b"))
    seg = state.get((nid, "x"))
    if blk and blk["phase"] == "data" and server == (blk["dir"] == "read") and cmd != 0x80:
        seqno, last = cmd & 0x7F, cmd >> 7
        F.add("c: last segment", 7, 1, str(last), T.SDO_BITS["c_block"])
        F.add("Sequence number", 0, 7, str(seqno), T.SDO_BITS["seqno"])
        F.add("Segment data", 8, 56, hexbytes(d[1:]), "7 bytes of the value.")
        what = "write" if blk["dir"] == "write" else "read"
        return ("Block segment %d of the %s of %s, %s%s." % (
            seqno, what, obj_text(*blk["mux"], _obj_name(dec, nid, *blk["mux"])), who,
            ", the last one" if last else "")), notes
    _cs_field(F, server, cs)
    if cs == 4:
        F.unused(0, 5)
        index, sub, ot = _mux(F, dec, nid)
        code = F.bits(32, 32)
        F.add("Abort code", 32, 32, "0x%08X = %s" % (code, diag.abort_text(code)), T.SDO_BITS["abort"],
              how=le_how(d, 32, 32))
        if server:
            return "%s refuses the transfer of %s: %s." % (who.capitalize(), ot, diag.abort_text(code)), notes
        return "The PLC aborts the transfer of %s with %s: %s." % (ot, who, diag.abort_text(code)), notes
    initiate = (not server and cs == 1) or (server and cs == 2)
    if initiate:
        n, e, s = (cmd >> 2) & 3, (cmd >> 1) & 1, cmd & 1
        F.unused(4, 1)
        F.add("n: bytes without data", 2, 2, "%d%s" % (n, " (%d data bytes)" % (4 - n) if e and s else " (not used)"),
              T.SDO_BITS["n_init"])
        F.add("e: expedited", 1, 1, str(e), T.SDO_BITS["e"])
        F.add("s: size indicated", 0, 1, str(s), T.SDO_BITS["s"])
        index, sub, ot = _mux(F, dec, nid)
        if e:
            size = 4 - n if s else 4
            data = d[4:4 + size]
            text, t = _value(dec, nid, index, sub, data)
            F.add("Data", 32, size * 8, text, "The value itself%s, little-endian." % (" as %s" % t if t else ""),
                  how=le_how(d, 32, size * 8), type=t)
            if size < 4:
                F.unused(32 + size * 8, (4 - size) * 8, "Padding", "No data: the n bits say these bytes are empty.")
            if server:
                return "%s answers %s = %s." % (who.capitalize(), ot, text), notes
            return "The PLC writes %s to %s of %s." % (text, ot, who), notes
        if s:
            size = F.bits(32, 32)
            F.add("Size", 32, 32, "%d bytes" % size, T.SDO_BITS["size"], how=le_how(d, 32, 32))
        else:
            F.unused(32, 32, "Reserved", "Reserved: the size is not given.")
            size = None
        if server:
            return "%s answers %s: %s follow in segments." % (
                who.capitalize(), ot, "%d bytes" % size if size is not None else "the data"), notes
        return "The PLC starts writing %s to %s of %s in segments." % (
            "%d bytes" % size if size is not None else "data", ot, who), notes
    if (not server and cs == 2) or (server and cs == 3):
        F.unused(0, 5)
        index, sub, ot = _mux(F, dec, nid)
        F.unused(32, 32, "Reserved", "Reserved, 0.")
        if server:
            if seg and seg["dir"] == "write" and not seg["data"]:
                return "%s accepts the segmented write to %s; the segments follow." % (who.capitalize(), ot), notes
            return "%s confirms the write to %s." % (who.capitalize(), ot), notes
        return "The PLC reads %s from %s." % (ot, who), notes
    if (not server and cs == 0) or (server and cs == 0):
        t, n, c = (cmd >> 4) & 1, (cmd >> 1) & 7, cmd & 1
        F.add("t: toggle", 4, 1, str(t), T.SDO_BITS["t"])
        F.add("n: bytes without data", 1, 3, "%d (%d data bytes)" % (n, 7 - n), T.SDO_BITS["n_seg"])
        F.add("c: last segment", 0, 1, str(c), T.SDO_BITS["c"])
        F.add("Segment data", 8, (7 - n) * 8, hexbytes(d[1:8 - n]), T.SDO_BITS["seg_data"])
        if n:
            F.unused(8 + (7 - n) * 8, n * 8, "Padding", "No data: the n bits say these bytes are empty.")
        want = "write" if not server else "read"
        if seg and seg["dir"] == want:
            k = len(seg["data"]) // 7 + 1
            if (k - 1) % 2 != t:
                notes.append("The toggle bit should be %d for segment %d: the server would abort with 05030000h "
                             "(toggle bit not alternated)." % ((k - 1) % 2, k))
            ot = obj_text(*seg["mux"], _obj_name(dec, nid, *seg["mux"]))
            total = ""
            if c:
                data = bytes(seg["data"]) + d[1:8 - n]
                text, _ = _value(dec, nid, seg["mux"][0], seg["mux"][1], data)
                total = " It completes the value: %s." % text
            return "Segment %d of the %s of %s, %s%s.%s" % (
                k, want, ot, who, ", the last one" if c else "", total), notes
        notes.append("Which transfer this segment belongs to is known only from the frames before it.")
        return "An SDO %s segment %s %s%s." % (want, "from" if server else "to", who, ", the last one" if c else ""), notes
    if (not server and cs == 3) or (server and cs == 1):
        t = (cmd >> 4) & 1
        F.add("t: toggle", 4, 1, str(t), T.SDO_BITS["t"])
        F.unused(0, 4)
        F.unused(8, 56, "Reserved", "Reserved, 0.")
        want = "read" if not server else "write"
        if seg and seg["dir"] == want:
            ot = obj_text(*seg["mux"], _obj_name(dec, nid, *seg["mux"]))
            if server:
                k = max(1, (len(seg["data"]) + 6) // 7)
                return "%s confirms segment %d of the write of %s." % (who.capitalize(), k, ot), notes
            k = len(seg["data"]) // 7 + 1
            return "The PLC asks %s for segment %d of %s." % (who, k, ot), notes
        if server:
            return "%s confirms a download segment." % who.capitalize(), notes
        return "The PLC asks %s for the next upload segment." % who, notes
    return _sdo_block_cmd(F, dec, nid, server, cs, cmd, who, blk), notes


def _sdo_block_cmd(F, dec, nid, server, cs, cmd, who, blk):
    d = F.data
    ot = obj_text(*blk["mux"], _obj_name(dec, nid, *blk["mux"])) if blk else "the object"
    if not server and cs == 6:  # block download
        if cmd & 1 == 0:
            F.unused(3, 2)
            F.add("cc: CRC support", 2, 1, str(cmd >> 2 & 1), T.SDO_BITS["cc"])
            F.add("s: size indicated", 1, 1, str(cmd >> 1 & 1), T.SDO_BITS["s"])
            F.add("Subcommand", 0, 1, "0 = initiate", T.SDO_BITS["sub_cmd"])
            index, sub, ot = _mux(F, dec, nid)
            if cmd >> 1 & 1:
                F.add("Size", 32, 32, "%d bytes" % F.bits(32, 32), T.SDO_BITS["size"], how=le_how(d, 32, 32))
            return "The PLC starts a block write of %s to %s." % (ot, who)
        F.add("n: bytes without data", 2, 3, str(cmd >> 2 & 7), T.SDO_BITS["n_block"])
        F.unused(1, 1)
        F.add("Subcommand", 0, 1, "1 = end", T.SDO_BITS["sub_cmd"])
        F.add("CRC", 8, 16, "0x%04X" % F.bits(8, 16), T.SDO_BITS["crc"], how=le_how(d, 8, 16))
        F.unused(24, 40, "Reserved", "Reserved, 0.")
        return "The PLC ends the block write of %s." % ot
    if not server and cs == 5:  # block upload commands
        sc = cmd & 3
        if sc == 0:
            F.unused(3, 2)
            F.add("cc: CRC support", 2, 1, str(cmd >> 2 & 1), T.SDO_BITS["cc"])
            F.add("Subcommand", 0, 2, "0 = initiate", T.SDO_BITS["sub_cmd"])
            index, sub, ot = _mux(F, dec, nid)
            F.add("Block size", 32, 8, str(F.byte(4)), T.SDO_BITS["blksize"])
            F.add("Protocol switch threshold", 40, 8, str(F.byte(5)), T.SDO_BITS["pst"])
            F.unused(48, 16, "Reserved", "Reserved, 0.")
            return "The PLC starts a block read of %s from %s." % (ot, who)
        F.unused(2, 3)
        F.add("Subcommand", 0, 2, {3: "3 = start", 2: "2 = block received", 1: "1 = end"}[sc], T.SDO_BITS["sub_cmd"])
        if sc == 2:
            F.add("Acknowledged sequence", 8, 8, str(F.byte(1)), T.SDO_BITS["ackseq"])
            F.add("Block size", 16, 8, str(F.byte(2)), T.SDO_BITS["blksize"])
            F.unused(24, 40, "Reserved", "Reserved, 0.")
            return "The PLC confirms %d segments of the block read of %s." % (F.byte(1), ot)
        F.unused(8, 56, "Reserved", "Reserved, 0.")
        return ("The PLC tells %s to start sending the blocks of %s." % (who, ot) if sc == 3
                else "The PLC confirms the end of the block read of %s." % ot)
    if server and cs == 5:  # block download answers
        sc = cmd & 3
        if sc == 0:
            F.unused(3, 2)
            F.add("sc: CRC support", 2, 1, str(cmd >> 2 & 1), T.SDO_BITS["sc"])
            F.add("Subcommand", 0, 2, "0 = initiate", T.SDO_BITS["sub_cmd"])
            index, sub, ot = _mux(F, dec, nid)
            F.add("Block size", 32, 8, str(F.byte(4)), T.SDO_BITS["blksize"])
            F.unused(40, 24, "Reserved", "Reserved, 0.")
            return "%s accepts the block write of %s, %d segments per block." % (who.capitalize(), ot, F.byte(4))
        F.unused(2, 3)
        F.add("Subcommand", 0, 2, {2: "2 = block received", 1: "1 = end"}.get(sc, str(sc)), T.SDO_BITS["sub_cmd"])
        if sc == 2:
            F.add("Acknowledged sequence", 8, 8, str(F.byte(1)), T.SDO_BITS["ackseq"])
            F.add("Block size", 16, 8, str(F.byte(2)), T.SDO_BITS["blksize"])
            F.unused(24, 40, "Reserved", "Reserved, 0.")
            return "%s confirms %d segments of the block write of %s." % (who.capitalize(), F.byte(1), ot)
        F.unused(8, 56, "Reserved", "Reserved, 0.")
        return "%s confirms the end of the block write of %s." % (who.capitalize(), ot)
    if server and cs == 6:  # block upload answers
        if cmd & 1 == 0:
            F.unused(3, 2)
            F.add("sc: CRC support", 2, 1, str(cmd >> 2 & 1), T.SDO_BITS["sc"])
            F.add("s: size indicated", 1, 1, str(cmd >> 1 & 1), T.SDO_BITS["s"])
            F.add("Subcommand", 0, 1, "0 = initiate", T.SDO_BITS["sub_cmd"])
            index, sub, ot = _mux(F, dec, nid)
            if cmd >> 1 & 1:
                F.add("Size", 32, 32, "%d bytes" % F.bits(32, 32), T.SDO_BITS["size"], how=le_how(d, 32, 32))
            return "%s answers the block read of %s." % (who.capitalize(), ot)
        F.add("n: bytes without data", 2, 3, str(cmd >> 2 & 7), T.SDO_BITS["n_block"])
        F.unused(1, 1)
        F.add("Subcommand", 0, 1, "1 = end", T.SDO_BITS["sub_cmd"])
        F.add("CRC", 8, 16, "0x%04X" % F.bits(8, 16), T.SDO_BITS["crc"], how=le_how(d, 8, 16))
        F.unused(24, 40, "Reserved", "Reserved, 0.")
        return "%s ends the block read of %s." % (who.capitalize(), ot)
    F.unused(0, 5)
    return "An SDO frame with an unknown command byte 0x%02X." % cmd


def _pdo(F, f, dec, p):
    who = dec.node_label(p.node) if p.node is not None else "a node"
    kind, num = _pdo_number(p.name)
    label = "%s%d" % (kind, num) if kind else p.name
    notes = []
    if f.rtr:
        return "The PLC asks %s to send %s (remote request)." % (who, label), notes
    total = len(F.data) * 8
    shown = []
    for (key, name, start, length, signed, fk, tname), info in zip(p.signals, p.info):
        if start + length > total:
            notes.append("The frame is shorter than the mapping: %s (bits %d-%d) is missing." % (
                name, start, start + length - 1))
            continue
        v = signal_value(F.data, start, length, signed, fk)
        nbytes = length // 8 if not length % 8 and not fk else None
        value = _num(v, nbytes) if not isinstance(v, float) else _num(v)
        if tname == "BOOLEAN" and length == 1:
            value = "TRUE" if v else "FALSE"
        idx, sub = info.get("index"), info.get("subindex")
        oname = _obj_name(dec, p.node, idx, sub) if idx is not None else None
        loc = info.get("location")
        variables = info.get("variables") or []
        if info.get("used"):
            where = "In the PLC program: %s%s." % (loc, " (%s)" % ", ".join(variables) if variables else "")
        elif p.tx:
            where = "No PLC address uses it."
        else:
            where = "No PLC address writes it: the master sends 0."
        text = "Mapped object %s (%s), bits %d-%d of the PDO. %s" % (
            obj_text(idx, sub, oname) if idx is not None else name, tname or "unknown type", start,
            start + length - 1, where)
        F.add(variables[0] if variables else (oname or name), start, length, value, text,
              how=le_how(F.data, start, length) if length > 8 or start % 8 else None,
              object=obj_text(idx, sub) if idx is not None else None, object_name=oname, type=tname,
              location=loc, variables=variables or None, signal=name)
        shown.append("%s = %s" % (variables[0] if variables else (loc or name), value.split(" ")[0]))
    plen = (p.length or 0) * 8
    meaning = "%s %s %s" % ("%s sends" % who.capitalize() if p.tx else "The PLC sends", label,
                            "" if p.tx else "to %s" % who)
    meaning = " ".join(meaning.split())
    if shown:
        meaning += ": " + ", ".join(shown[:4]) + (", ..." if len(shown) > 4 else "")
    F.done_gap = ("Dummy or unused", "Bits in the PDO that the mapping fills with a dummy entry or does not use."
                  if plen else "Not in the mapping.")
    if plen and plen < total:
        F.unused(plen, total - plen, "Not in the mapping", "The frame is longer than the mapping says; these bytes "
                 "carry nothing.")
    return meaning + ".", notes


def _lss(F, request):
    cs = F.byte(0)
    name = T.LSS_COMMANDS.get(cs, "unknown command")
    F.add("Command specifier", 0, 8, "0x%02X = %s" % (cs, name), "LSS command (CiA 305).")
    who = "The PLC (LSS master)" if request else "The device"
    detail = ""
    if cs == 0x04 and request:
        mode = F.byte(1)
        F.add("Mode", 8, 8, "%d = %s" % (mode, "configuration" if mode else "waiting"),
              "0: back to waiting, 1: every device goes to the configuration state.")
        detail = " to the %s state" % ("configuration" if mode else "waiting")
    elif cs == 0x11:
        if request:
            F.add("Node-ID", 8, 8, str(F.byte(1)), "The node-ID to give the device in the configuration state.")
            detail = " %d" % F.byte(1)
        else:
            F.add("Error code", 8, 8, str(F.byte(1)), "0: done, 1: node-ID out of range, 255: manufacturer error.")
            detail = ": %s" % ("done" if F.byte(1) == 0 else "error %d" % F.byte(1))
    elif cs == 0x13:
        if request:
            F.add("Table selector", 8, 8, str(F.byte(1)), "0: the CiA 305 standard bit timing table.")
            F.add("Table index", 16, 8, "%d = %s" % (F.byte(2), T.LSS_BIT_RATES.get(F.byte(2), "?")),
                  "Index into the bit timing table.")
            detail = " %s" % T.LSS_BIT_RATES.get(F.byte(2), "?")
        else:
            F.add("Error code", 8, 8, str(F.byte(1)), "0: done, 1: bit rate not supported.")
    elif cs == 0x15:
        F.add("Switch delay", 8, 16, "%d ms" % F.bits(8, 16), "Wait this long before and after switching the bit "
              "rate.", how=le_how(F.data, 8, 16))
    elif cs == 0x17 and not request:
        F.add("Error code", 8, 8, str(F.byte(1)), "0: stored, 1: storing not supported, 2: storage access error.")
    elif cs in (0x40, 0x41, 0x42, 0x43, 0x46, 0x47, 0x48, 0x49, 0x4A, 0x4B) or (
            cs in (0x5A, 0x5B, 0x5C, 0x5D) and not request):
        v = F.bits(8, 32)
        F.add("Value", 8, 32, "0x%08X" % v, "The identity value of this command, little-endian.",
              how=le_how(F.data, 8, 32))
        detail = " 0x%08X" % v
    elif cs == 0x5E and not request:
        F.add("Node-ID", 8, 8, str(F.byte(1)), "The device's node-ID.")
        detail = " = %d" % F.byte(1)
    elif cs == 0x51 and request:
        F.add("ID number", 8, 32, "0x%08X" % F.bits(8, 32), "The identity bits compared so far.",
              how=le_how(F.data, 8, 32))
        F.add("Bit checked", 40, 8, str(F.byte(5)), "Which bit is checked now (128 = reset the scan).")
        F.add("LSS sub", 48, 8, str(F.byte(6)), "Which identity part (0 vendor, 1 product, 2 revision, 3 serial).")
        F.add("LSS next", 56, 8, str(F.byte(7)), "Which part comes next.")
    return "%s: %s%s." % (who, name, detail)


def _error_frame(F, f):
    cls = f.can_id
    names = [n for k, n in enumerate(T.ERROR_CLASSES) if cls >> k & 1]
    F.add("Lost arbitration at bit", 0, 8, str(F.byte(0)) if cls & 0x002 else "-", "With the lost arbitration class: "
          "the bit at which this node lost.")
    F.add("Controller state", 8, 8, "0x%02X" % F.byte(1), "Controller problem details.",
          bits=[{"name": n} for n in T.ERROR_CTRL])
    F.add("Protocol error type", 16, 8, "0x%02X" % F.byte(2), "Protocol violation details.",
          bits=[{"name": n} for n in T.ERROR_PROT_TYPE])
    F.add("Protocol error location", 24, 8, "0x%02X = %s" % (F.byte(3), T.ERROR_PROT_LOCATION.get(F.byte(3), "unspecified")),
          "Where in the frame the protocol error was seen.")
    F.add("Transceiver status", 32, 8, "0x%02X = %s" % (F.byte(4), T.ERROR_TRANSCEIVER.get(F.byte(4), "unspecified")),
          "Wiring problems the transceiver reports, if it can.")
    F.add("Controller specific", 40, 8, "0x%02X" % F.byte(5), "Free for the controller driver.")
    F.add("TX error counter", 48, 8, str(F.byte(6)), "Transmit error counter (error passive above 127, bus-off at 256).")
    F.add("RX error counter", 56, 8, str(F.byte(7)), "Receive error counter (error passive above 127).")
    return "The CAN controller reports: %s." % (", ".join(names) or "an error"), {
        "bits": [{"n": k, "name": n, "set": bool(cls >> k & 1)} for k, n in enumerate(T.ERROR_CLASSES)]}


# -- the whole explanation -----------------------------------------------------

def frame_dict(f):
    return {"id": f.can_id, "id_text": f.id_text(), "ext": f.ext, "rtr": f.rtr, "err": f.err, "dlc": f.dlc,
            "data": f.data_text(), "tx": f.tx, "time_us": f.time_us, "candump": candump_text(f)}


def candump_text(f):
    if f.rtr:
        return "%s#R%s" % (f.id_text(), f.dlc if f.dlc else "")
    return "%s#%s" % (f.id_text(), "".join("%02X" % b for b in f.data))


def explain(f, decoder=None, bitrate=None, context=None):
    dec = decoder or Decoder()
    if len(f.data) > 8 or f.dlc > 8:
        raise ValueError("only classic CAN frames with up to 8 data bytes are supported")
    F = Fields(b"" if f.rtr else f.data)
    notes = []
    out = {"frame": frame_dict(f), "kind": "other", "title": "", "notes": notes, "identifier": None,
           "error_classes": None}
    if f.err:
        meaning, classes = _error_frame(F, f)
        out.update(kind="error", title="Error frame", meaning=meaning, about=T.ABOUT["error"],
                   error_classes=classes, fields=F.done(), wire=None)
        return out
    ident = identifier_layer(f, dec)
    out["identifier"] = ident
    cid, d = f.can_id, f.data
    kind = "other"
    if f.ext:
        kind = "ext"
        meaning = "A frame with the extended identifier 0x%08X and %s; not a CANopen frame." % (cid, _bytes(len(d)))
        if d:
            F.add("Data", 0, len(d) * 8, hexbytes(d), "Data of another protocol; its meaning is not known here.")
    elif cid in dec.pdos:
        kind = "pdo"
        meaning, more = _pdo(F, f, dec, dec.pdos[cid])
        notes += more
    elif cid == 0x000:
        kind = "nmt"
        meaning = _nmt(F, dec)
    elif cid == dec.sync_cob:
        kind = "sync"
        meaning = _sync(F, f)
    elif cid == dec.time_cob:
        kind = "time"
        meaning = _time(F)
    elif 0x081 <= cid <= 0x0FF:
        kind = "emcy"
        meaning = _emcy(F, dec, cid - 0x80)
    elif 0x701 <= cid <= 0x77F:
        kind = "heartbeat"
        meaning = _heartbeat(F, f, dec, cid - 0x700)
        if f.rtr or (d and d[0] & 0x80):
            out["about"] = T.ABOUT["guarding"]
    elif 0x581 <= cid <= 0x5FF or 0x601 <= cid <= 0x67F:
        kind = "sdo"
        if f.rtr:
            meaning = "A remote request on an SDO identifier (not used by CANopen)."
        else:
            meaning, more = _sdo(F, f, dec, cid & 0x7F, cid < 0x600, context)
            notes += more
    elif cid in (0x7E4, 0x7E5):
        kind = "lss"
        meaning = _lss(F, cid == 0x7E5)
    else:
        fn = _function(cid)
        if fn and fn[1] == "pdo":
            kind = "pdo"
            nid = cid & 0x7F
            if f.rtr:
                meaning = "A remote request for %s of %s." % (fn[0], dec.node_label(nid))
            else:
                meaning = "%s of %s; it is not in the configuration, so its mapping is unknown." % (
                    fn[0], dec.node_label(nid))
                if d:
                    F.add("Process data", 0, len(d) * 8, hexbytes(d), "Without the PDO mapping only the bytes can "
                          "be shown.")
        else:
            meaning = "Frame 0x%03X with %s; nothing in CANopen or the configuration says what it is." % (
                cid, _bytes(len(d)))
            if d:
                F.add("Data", 0, len(d) * 8, hexbytes(d), "Unknown data.")
    gap = getattr(F, "done_gap", ("Not used", "Not used."))
    out["kind"] = kind
    out["title"] = _title(kind, ident, dec)
    out["meaning"] = meaning
    out.setdefault("about", T.ABOUT.get(kind, T.ABOUT["other"]))
    if f.rtr and kind not in ("heartbeat",):
        notes.append("A remote request carries no data: the RTR bit asks the owner of the identifier to send it.")
    out["fields"] = F.done(*gap)
    out["wire"] = wire(cid, f.ext, f.rtr, b"" if f.rtr else d, f.dlc, bitrate)
    return out


def _bytes(n):
    return "1 data byte" if n == 1 else "%d data bytes" % n


def _title(kind, ident, dec):
    if kind == "ext":
        return "Extended frame"
    msg = ident.get("message") or "Unknown frame"
    label = ident.get("node_label")
    return "%s of %s" % (msg, label) if label and kind not in ("nmt", "sync", "time", "lss") else msg


# -- one bit of a PDO layout (canopen-network-docs: "Bit explanations in PDO layouts") --

def pdo_bit_text(pb, entry, kind="TPDO"):
    """What bit `pb` of a PDO is, from a layout entry ({bit, length, index,
    subindex, name, type, location, variables, used, dummy}) or None."""
    where = "Bit %d (byte %d, bit %d of the byte)" % (pb, pb // 8, pb % 8)
    if entry is None:
        return "%s: not mapped, sent as 0." % where
    k = pb - entry["bit"]
    obj = "%04Xh:%02X" % (entry["index"], entry["subindex"])
    if entry.get("dummy"):
        return "%s: dummy entry %s (%s), a gap the receiver skips." % (where, obj, entry.get("type") or "")
    part = "%s %s%s" % (obj, entry.get("name") or "", " (%s)" % entry["type"] if entry.get("type") else "")
    if entry["length"] > 1:
        part += ", bit %d of %d (weight %d)" % (k, entry["length"], 1 << k)
    loc = entry.get("location")
    if entry.get("used") and loc:
        plc = loc if entry["length"] == 1 else "bit %d of %s" % (k, loc)
        if entry.get("variables"):
            plc += " (%s)" % ", ".join(entry["variables"])
        part += ". PLC: " + plc
    else:
        part += ". Not used by the PLC" + ("" if kind == "TPDO" else ", sent as 0")
    return "%s: %s." % (where, part)


# -- parsing frames -------------------------------------------------------------

def parse_frame(text):
    """A Frame from candump syntax: 123#11223344, 123#R, 123#R4,
    18FF0017#0102 (8 hex digits: extended)."""
    from .model import Frame
    t = (text or "").strip().replace(" ", "")
    if "#" not in t:
        raise ValueError("write a frame as ID#DATA, e.g. 185#2500EA00 or 705#R")
    ident, data = t.split("#", 1)
    if ident.lower().startswith("0x"):
        ident = ident[2:]
    if not ident or any(c not in "0123456789abcdefABCDEF" for c in ident):
        raise ValueError("%r: the identifier must be hexadecimal" % ident)
    ext = len(ident) == 8
    if len(ident) > 8:
        raise ValueError("%r: the identifier has too many digits" % ident)
    can_id = int(ident, 16)
    if not ext and can_id > 0x7FF:
        raise ValueError("0x%X is more than 11 bits: write extended identifiers with 8 digits" % can_id)
    if can_id > 0x1FFFFFFF:
        raise ValueError("0x%X is more than 29 bits" % can_id)
    if data[:1] in ("R", "r"):
        rest = data[1:]
        dlc = int(rest) if rest.isdigit() else 0
        if dlc > 8:
            raise ValueError("a remote request asks for at most 8 bytes")
        return Frame(0, can_id, b"", ext=ext, rtr=True, dlc=dlc)
    data = data.replace(".", "")
    if any(c not in "0123456789abcdefABCDEF" for c in data):
        raise ValueError("%r: the data must be hexadecimal bytes" % data)
    if len(data) % 2:
        raise ValueError("the data needs whole bytes: an even number of hex digits")
    raw = bytes.fromhex(data)
    if len(raw) > 8:
        raise ValueError("only classic CAN frames with up to 8 data bytes are supported (this one has %d)" % len(raw))
    return Frame(0, can_id, raw, ext=ext)


def bitrate_of(cfg, network=None):
    """The configured bit rate of a network, or None."""
    from .. import contract
    try:
        c = contract.network_config(cfg, network) if cfg else None
    except (ValueError, KeyError, TypeError):
        return None
    if not c:
        return None
    a = c.get("adapter") or {}
    v = a.get("bitrate", c.get("bitrate"))
    try:
        return int(v) if v else None
    except (TypeError, ValueError):
        return None


# -- text output (openplc-canopen-diag explain) -----------------------------------

LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"


def format_text(m, width=100):
    L = []
    fr = m["frame"]
    L.append("%s  [%d]  %s" % (fr["id_text"], fr["dlc"], "remote request" if fr["rtr"] else (fr["data"] or "(no data)")))
    L.append("")
    L.append(m["title"])
    L.append("  " + m["meaning"])
    L.append("")
    L.append("What it is")
    L += _wrap(m["about"], width, "  ")
    ident = m["identifier"]
    if ident:
        L.append("")
        L.append("Identifier (%d bits, most significant first)" % ident["width"])
        bits = ident["bits"]
        if ident["width"] == 11 and ident["function_code"] is not None and ident["node"] is None:
            L.append("  function code %s = %d" % ("".join(str(b["v"]) for b in bits[:4]), ident["function_code"]))
        elif ident["width"] == 11 and ident["function_code"] is not None:
            fc = "".join(str(b["v"]) for b in bits[:4])
            nd = "".join(str(b["v"]) for b in bits[4:])
            L.append("  function code %s = %d   node ID %s = %d" % (fc, ident["function_code"], nd, ident["node"]))
        else:
            L.append("  " + "".join(str(b["v"]) for b in bits))
        if ident.get("math"):
            L.append("  " + ident["math"])
        if ident.get("configured_text"):
            L.append("  " + ident["configured_text"])
        if ident.get("message"):
            L.append("  %s: %s%s" % (ident["message"], ident["what"],
                                      ", " + ident["node_label"] if ident.get("node_label") else ""))
        elif ident.get("what"):
            L.append("  " + ident["what"])
    if m.get("error_classes"):
        L.append("")
        L.append("Error class (identifier bits)")
        for b in m["error_classes"]["bits"]:
            L.append("  bit %d %s %s" % (b["n"], "1" if b["set"] else "0", b["name"]))
    fields = m["fields"]
    if fields:
        L.append("")
        L.append("Data bits (each row one byte, bit 7 first; letters mark the fields below)")
        letter = {}
        k = 0
        for f in fields:
            if f["group"] == "unused":
                letter[id(f)] = "."
            else:
                letter[id(f)] = LETTERS[k % len(LETTERS)]
                k += 1
        owner = {}
        for f in fields:
            for b in range(f["start"], f["start"] + f["length"]):
                owner[b] = f
        data = bytes.fromhex(fr["data"].replace(" ", "")) if fr["data"] else b""
        L.append("          b7 b6 b5 b4 b3 b2 b1 b0")
        for byte in range(len(data)):
            vals = " ".join(" %d" % (data[byte] >> n & 1) for n in range(7, -1, -1))
            marks = " ".join(" " + letter[id(owner[byte * 8 + n])] for n in range(7, -1, -1))
            L.append("  byte %d  %s   0x%02X" % (byte, vals, data[byte]))
            L.append("          %s" % marks)
        L.append("")
        for f in fields:
            rng = "bit %d" % f["start"] if f["length"] == 1 else "bits %d-%d" % (f["start"], f["start"] + f["length"] - 1)
            L.append("  %s %s (%s): %s" % (letter[id(f)], f["name"], rng, f["value"]))
            if f.get("how"):
                L.append("      " + f["how"])
            L += _wrap(f["text"], width, "      ")
            for k, b in enumerate(f.get("bits") or []):
                if k < f["length"]:
                    val = int.from_bytes(data.ljust(8, b"\0"), "little") >> (f["start"] + k) & 1
                    L.append("      bit %d = %d %s" % (k, val, b["name"]))
    if m["notes"]:
        L.append("")
        for n in m["notes"]:
            L += _wrap("Note: " + n, width, "  ")
    w = m["wire"]
    if w:
        L.append("")
        L.append("On the wire at %d kbit/s%s" % (w["bitrate"] // 1000, " (assumed)" if w["bitrate_assumed"] else ""))
        L.append("  %d bits + 3 intermission, %d stuff bits, CRC %s, %.1f us on the bus, %.0f %% data" % (
            w["frame_bits"], w["stuff_bits"], w["crc_text"], w["duration_us"], w["data_share"]))
        groups = []
        cur, last = [], None
        for b in w["bits"]:
            name = b["field"] if b["field"] != "stuff" else last
            if name != last and cur:
                groups.append((last, "".join(cur)))
                cur = []
            cur.append("[%d]" % b["v"] if b["field"] == "stuff" else str(b["v"]))
            last = name
        if cur:
            groups.append((last, "".join(cur)))
        line = "  "
        for name, bits in groups:
            piece = "%s:%s " % (w["fields"][name]["name"] if name in w["fields"] else name, bits)
            if len(line) + len(piece) > width:
                L.append(line.rstrip())
                line = "  "
            line += piece
        L.append(line.rstrip())
        L.append("  [x] = stuff bit")
        L += _wrap(w["note"], width, "  ")
    return "\n".join(L) + "\n"


def _wrap(text, width, indent):
    import textwrap
    return textwrap.wrap(text, width, initial_indent=indent, subsequent_indent=indent) or [indent.rstrip()]
