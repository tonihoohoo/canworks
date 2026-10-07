"""A classic CAN frame rebuilt bit by bit as a correct controller sends it
(canopen-frame-explain: "Frame on the wire"; design D4).

SocketCAN delivers finished frames, so nothing here is measured: the bits
follow from the identifier, the flags and the data. Every bit names where
it comes from (`ref`), so a view can link it to the identifier and data
layers:

    sof, id.<n> (identifier bit n, 28..0), srr, ide, rtr, r1, r0, dlc.<n>,
    data.<byte>.<bit>, crc.<n>, stuff, crcdel, ack, ackdel, eof, ifs
"""

from .explain_texts import WIRE, WIRE_NOTE

CRC_POLY = 0x4599
DEFAULT_BITRATE = 500000


def crc15(bits):
    """The CAN CRC-15 over a sequence of 0/1 bits."""
    crc = 0
    for b in bits:
        nxt = b ^ ((crc >> 14) & 1)
        crc = (crc << 1) & 0x7FFF
        if nxt:
            crc ^= CRC_POLY
    return crc


def crc15_bytes(data):
    """CRC-15 over bytes, most significant bit first (the catalogue check
    value of b"123456789" is 0x059E)."""
    return crc15([(b >> i) & 1 for b in data for i in range(7, -1, -1)])


def _unstuffed(can_id, ext, rtr, dlc, data):
    """[(bit, field, ref)] from start of frame to the end of the data."""
    out = [(0, "sof", "sof")]
    if ext:
        for n in range(28, 17, -1):
            out.append(((can_id >> n) & 1, "id", "id.%d" % n))
        out.append((1, "srr", "srr"))
        out.append((1, "ide", "ide"))
        for n in range(17, -1, -1):
            out.append(((can_id >> n) & 1, "id", "id.%d" % n))
        out.append((1 if rtr else 0, "rtr", "rtr"))
        out.append((0, "r1", "r1"))
        out.append((0, "r0", "r0"))
    else:
        for n in range(10, -1, -1):
            out.append(((can_id >> n) & 1, "id", "id.%d" % n))
        out.append((1 if rtr else 0, "rtr", "rtr"))
        out.append((0, "ide", "ide"))
        out.append((0, "r0", "r0"))
    for n in range(3, -1, -1):
        out.append(((dlc >> n) & 1, "dlc", "dlc.%d" % n))
    if not rtr:
        for k, byte in enumerate(data):
            for n in range(7, -1, -1):
                out.append(((byte >> n) & 1, "data", "data.%d.%d" % (k, n)))
    return out


def wire(can_id, ext=False, rtr=False, data=b"", dlc=None, bitrate=None):
    """The frame's bits and figures as a JSON-ready dict."""
    data = bytes(data)
    dlc = len(data) if dlc is None else dlc
    if dlc > 8 or len(data) > 8:
        raise ValueError("only classic CAN frames with up to 8 data bytes are supported")
    raw = _unstuffed(can_id, ext, rtr, dlc, b"" if rtr else data)
    crc = crc15([b for b, _, _ in raw])
    raw += [((crc >> n) & 1, "crc", "crc.%d" % n) for n in range(14, -1, -1)]
    bits, run, last, stuffed = [], 0, None, 0
    for b, field, ref in raw:
        bits.append({"v": b, "field": field, "ref": ref})
        if b == last:
            run += 1
        else:
            run, last = 1, b
        if run == 5:
            s = 1 - b
            bits.append({"v": s, "field": "stuff", "ref": "stuff"})
            stuffed += 1
            run, last = 1, s
    tail = [(1, "crcdel"), (0, "ack"), (1, "ackdel")] + [(1, "eof")] * 7 + [(1, "ifs")] * 3
    bits += [{"v": v, "field": f, "ref": f} for v, f in tail]
    assumed = not bitrate
    rate = int(bitrate or DEFAULT_BITRATE)
    frame_bits = len(bits) - 3
    bit_us = 1e6 / rate
    for k, b in enumerate(bits):
        b["n"] = k
        b["level"] = "recessive" if b["v"] else "dominant"
    return {
        "bits": bits, "frame_bits": frame_bits, "stuff_bits": stuffed, "crc": crc, "crc_text": "0x%04X" % crc,
        "bitrate": rate, "bitrate_assumed": assumed, "bit_time_us": bit_us,
        "duration_us": frame_bits * bit_us, "with_intermission_us": len(bits) * bit_us,
        "data_share": round(100.0 * (0 if rtr else len(data)) * 8 / frame_bits, 1),
        "fields": {k: {"name": v[0], "text": v[1]} for k, v in WIRE.items()},
        "note": WIRE_NOTE,
    }


def unstuff(bits):
    """The bits without stuff bits (for checks)."""
    return [b["v"] for b in bits if b["field"] != "stuff"]
