"""J1939 decoding of trace frames (j1939-trace spec) for networks whose
config entry has "protocol": "j1939".

Extended frames split into priority, PGN, source and destination. Message
and signal names, scale, offset and unit come from the network's DBC
(`j1939.dbc`, relative to the config file, read with cantools), and for a
PGN the DBC lacks, from the config's rx/tx signals. Address Claimed, Cannot
Claim, Request, Acknowledgement and the transport protocol (TP.CM, TP.DT)
are decoded without a DBC. A BAM or RTS/CTS session is reassembled: the
row of its last TP.DT frame carries the whole message, the other frames stay
rows of their own as its parts. A multiplexed message (DBC `M`/`mN`/
`SG_MUL_VAL_`, or the config's `multiplexer`/`mux`) decodes only the
signals its frame carries and names the page ("[Page=2]").

    dec = J1939Decoder.from_network(net, config_path)   # net: a contract.networks() entry
    d = dec.decode(frame)   # Decoded: kind, node (source address), name, text, signals

decode() keeps the transport sessions in progress: feed it the frames in
order (reset() before a new pass), as for CANopen SDO transfers.
"""

import os
import struct

from ..raw import mux as raw_mux
from .decode import Decoded, Decoder

PGN_REQUEST = 0xEA00         # 59904
PGN_ACK = 0xE800             # 59392
PGN_TP_CM = 0xEC00           # 60416
PGN_TP_DT = 0xEB00           # 60160
PGN_ADDRESS_CLAIMED = 0xEE00  # 60928
NULL_ADDRESS = 254
GLOBAL = 255

KNOWN_PGNS = {PGN_REQUEST: "Request", PGN_ACK: "Acknowledgement", PGN_TP_CM: "TP.CM", PGN_TP_DT: "TP.DT",
              PGN_ADDRESS_CLAIMED: "Address Claimed"}
ACK_CONTROL = {0: "ACK", 1: "NACK", 2: "Access denied", 3: "Cannot respond"}
TP_CONTROL = {16: "RTS", 17: "CTS", 19: "End of message ACK", 32: "BAM", 255: "Abort"}
TP_ABORT_REASONS = {1: "already in a session", 2: "resources needed elsewhere", 3: "timeout",
                    4: "CTS while sending", 5: "retransmit limit reached", 6: "unexpected data packet",
                    7: "bad sequence number", 8: "duplicate sequence number", 9: "message too large"}

# The 64-bit NAME (J1939-81), lowest bit first: (key, label, start bit, length).
NAME_FIELDS = (
    ("identity_number", "Identity number", 0, 21),
    ("manufacturer_code", "Manufacturer code", 21, 11),
    ("ecu_instance", "ECU instance", 32, 3),
    ("function_instance", "Function instance", 35, 5),
    ("function", "Function", 40, 8),
    ("reserved", "Reserved", 48, 1),
    ("vehicle_system", "Vehicle system", 49, 7),
    ("vehicle_system_instance", "Vehicle system instance", 56, 4),
    ("industry_group", "Industry group", 60, 3),
    ("arbitrary_address_capable", "Arbitrary address capable", 63, 1),
)

ABOUT = {
    "claim": ("Address Claimed (PGN 60928) is how a J1939 ECU takes a source address: it sends its 64-bit NAME "
              "from the address it wants. When two ECUs want the same address, the lower NAME keeps it; the other "
              "moves to a free address if it is arbitrary address capable, or sends Cannot Claim from the null "
              "address 254 and goes silent."),
    "request": ("A Request (PGN 59904) asks one ECU, or all with destination 255, to send a parameter group now. "
                "Its three data bytes are the requested PGN, low byte first."),
    "ack": ("The Acknowledgement (PGN 59392) answers a request that is not answered with the data: NACK when the "
            "PGN is not supported, Access denied or Cannot respond. The requested PGN is in the last three bytes."),
    "tp": ("The transport protocol carries parameter groups of 9 to 1785 bytes in 7-byte packets. TP.CM (PGN "
           "60416) opens the session: a BAM announces a broadcast, an RTS asks the receiver, which paces the "
           "sender with CTS and confirms the end. TP.DT (PGN 60160) carries the packets, numbered from 1."),
    "pgn": ("A J1939 parameter group. The 29-bit identifier holds the priority, the PGN (what the message is) "
            "and the source address (who sent it); PDU1 groups (PDU format below 240) also name a destination. "
            "The signals' places, scale and unit come from the network's DBC."),
}


def split_id(can_id):
    """The fields of a 29-bit J1939 identifier."""
    cid = can_id & 0x1FFFFFFF
    pf, ps = (cid >> 16) & 0xFF, (cid >> 8) & 0xFF
    pdu1 = pf < 240
    reserved, dp = (cid >> 25) & 1, (cid >> 24) & 1
    return {"priority": cid >> 26, "reserved": reserved, "dp": dp, "pf": pf, "ps": ps, "source": cid & 0xFF,
            "pdu1": pdu1, "destination": ps if pdu1 else None, "group_extension": None if pdu1 else ps,
            "pgn": (reserved << 17) | (dp << 16) | (pf << 8) | (0 if pdu1 else ps)}


def name_fields(value):
    """[(key, label, value)] of a 64-bit NAME."""
    return [(k, label, (value >> start) & ((1 << length) - 1)) for k, label, start, length in NAME_FIELDS]


def name_text(value):
    """A NAME as hex with its fields in words."""
    parts = []
    for k, label, v in name_fields(value):
        if k == "reserved":
            continue
        if k == "arbitrary_address_capable":
            v = "yes" if v else "no"
        parts.append("%s %s" % (label.lower().replace("ecu", "ECU"), v))
    return "NAME 0x%016X (%s)" % (value, ", ".join(parts))


def address_text(a):
    return "global (255)" if a == GLOBAL else "null address 254" if a == NULL_ADDRESS else str(a)


def _uint_le(data, start, length):
    return (int.from_bytes(bytes(data), "little") >> start) & ((1 << length) - 1)


class Sig:
    """One signal of a message layout, from the DBC or the config."""
    __slots__ = ("name", "start", "length", "big", "signed", "scale", "offset", "unit", "is_float", "choices",
                 "multiplexer", "mux")

    def __init__(self, name, start, length, big=False, signed=False, scale=1, offset=0, unit="", is_float=False,
                 choices=None, multiplexer=False, mux=None):
        self.name, self.start, self.length, self.big, self.signed = name, start, length, big, signed
        self.scale, self.offset, self.unit, self.is_float = scale, offset, unit or "", is_float
        self.choices = choices or {}
        # Multiplexing in the config's form: a switch, and {"on", "values"}.
        self.multiplexer, self.mux = multiplexer, mux

    def raw(self, data):
        """The raw value, or None when the data is too short."""
        n = len(data) * 8
        if self.big:
            # DBC big byte order: start is the most significant bit, in the
            # DBC's sawtooth numbering.
            msb = (self.start // 8) * 8 + (7 - self.start % 8)
            if msb + self.length > n:
                return None
            raw = (int.from_bytes(bytes(data), "big") >> (n - msb - self.length)) & ((1 << self.length) - 1)
        else:
            if self.start + self.length > n:
                return None
            raw = _uint_le(data, self.start, self.length)
        if self.is_float and self.length == 32:
            return struct.unpack("<f", raw.to_bytes(4, "little"))[0]
        if self.is_float and self.length == 64:
            return struct.unpack("<d", raw.to_bytes(8, "little"))[0]
        if self.signed and raw & (1 << (self.length - 1)):
            raw -= 1 << self.length
        return raw

    def special(self, raw):
        """"not available" or "error" for the J1939 reserved values of an
        unsigned signal (all ones, all ones but the lowest bit; for 16 bits
        and more the top byte 0xFF or 0xFE), else None."""
        if self.signed or self.is_float or self.length < 2 or isinstance(raw, float):
            return None
        if self.length < 16:
            top = (1 << self.length) - 1
            return "not available" if raw == top else "error" if raw == top - 1 else None
        hi = raw >> ((self.length // 8 - 1) * 8) if self.length % 8 == 0 else None
        return "not available" if hi == 0xFF else "error" if hi == 0xFE else None

    def physical(self, raw):
        v = raw * self.scale + self.offset
        if isinstance(v, float) and v.is_integer() and not self.is_float and isinstance(self.scale, int) \
                and isinstance(self.offset, int):
            v = int(v)
        return v

    def text(self, raw):
        sp = self.special(raw)
        if sp:
            return "%s=%s" % (self.name, sp)
        v = self.physical(raw)
        out = "%s=%s%s" % (self.name, "%g" % v if isinstance(v, float) else v, " " + self.unit if self.unit else "")
        if raw in self.choices:
            out += " (%s)" % self.choices[raw]
        return out


class Msg:
    __slots__ = ("name", "pgn", "length", "signals", "sender", "source", "comment", "_layout")

    def __init__(self, name, pgn, length, signals, sender=None, source=None, comment=""):
        self.name, self.pgn, self.length, self.signals = name, pgn, length, signals
        self.sender, self.source, self.comment = sender, source, comment or ""
        self._layout = None

    @property
    def layout(self):
        """The mux.Layout of the signals (not multiplexed when the
        multiplexing does not check)."""
        if self._layout is None:
            defs = []
            for j, sg in enumerate(self.signals):
                d = {"path": "signals[%d]" % j, "name": sg.name, "start_bit": sg.start, "length": sg.length,
                     "byte_order": "big" if sg.big else "little", "signed": sg.signed}
                if sg.multiplexer:
                    d["multiplexer"] = True
                if sg.mux is not None:
                    d["mux"] = sg.mux
                defs.append(d)
            self._layout = raw_mux.Layout.build(defs, [], [])
        return self._layout

    def page(self, data):
        """(active flags or None when not multiplexed, unknown page, page
        label such as "Page=2" or "")."""
        lay = self.layout
        if not lay.multiplexed:
            return None, False, ""
        active, unknown, short, _ = lay.evaluate(bytes(data))
        return active, unknown, "" if short else lay.page_label(bytes(data))


def load_dbc(path):
    """{(pgn, source): Msg} from a DBC's extended messages (source None for
    the first message of a PGN, which stands for every source). Raises
    OSError or ValueError (also when cantools is not installed)."""
    try:
        import cantools
    except ImportError:
        raise ValueError("cantools is not installed; reinstall the PC tools")
    try:
        db = cantools.database.load_file(path, database_format="dbc", strict=False)
    except OSError:
        raise
    except Exception as e:  # noqa: BLE001 - cantools raises its own parse errors
        raise ValueError(str(e).splitlines()[0] if str(e) else type(e).__name__)
    from ..raw.dbc import mux_fields
    out = {}
    for m in db.messages:
        if not m.is_extended_frame:
            continue
        s = split_id(m.frame_id)
        sigs = []
        fields, _ = mux_fields(m)
        for sg in m.signals:
            choices = {int(k): str(v) for k, v in (sg.choices or {}).items()}
            f = fields.get(sg.name, {})
            sigs.append(Sig(sg.name, sg.start, sg.length, sg.byte_order == "big_endian", sg.is_signed,
                            sg.scale, sg.offset, sg.unit, sg.is_float, choices, f.get("multiplexer", False),
                            f.get("mux")))
        msg = Msg(m.name, s["pgn"], m.length, sigs, (m.senders or [None])[0], s["source"], m.comment)
        out.setdefault((s["pgn"], None), msg)
        out[(s["pgn"], s["source"])] = msg
    return out


def _config_msg(entry, direction):
    sigs = []
    for sg in entry.get("signals") or []:
        if not isinstance(sg, dict) or not isinstance(sg.get("start_bit"), int) or not isinstance(sg.get("length"), int):
            continue
        sigs.append(Sig(str(sg.get("name") or "signal"), sg["start_bit"], sg["length"], sg.get("byte_order") == "big",
                        bool(sg.get("signed")), sg.get("scale", 1), sg.get("offset", 0), sg.get("unit") or "",
                        multiplexer=sg.get("multiplexer") is True,
                        mux=sg.get("mux") if isinstance(sg.get("mux"), dict) else None))
    pgn = entry.get("pgn")
    name = entry.get("name") or "PGN%d" % pgn
    length = entry.get("length") or max([8] + [(s.start + s.length + 7) // 8 for s in sigs if not s.big])
    return Msg(str(name), pgn, length, sigs, direction)


class J1939Decoder(Decoder):
    """Decodes the frames of one J1939 network. It is a Decoder, so the code
    written for CANopen traces finds the attributes it reads (no PDOs, no
    EDS files); `protocol` tells the two apart."""

    protocol = "j1939"

    def __init__(self):
        self.messages = {}       # (pgn, source or None) -> Msg
        self.address_names = {}  # source address -> a name from the DBC or the config
        self.own_address = None
        super().__init__()

    @classmethod
    def from_network(cls, net, config_path):
        """A decoder for a contract.networks() entry of a J1939 network.
        Problems (no DBC, a DBC that does not read) go to `warnings`; the
        frames still decode without names."""
        d = cls()
        j = net["json"].get("j1939") if isinstance(net["json"].get("j1939"), dict) else {}
        ecu = j.get("ecu") if isinstance(j.get("ecu"), dict) else {}
        if isinstance(ecu.get("address"), int):
            d.own_address = ecu["address"]
            d.address_names[ecu["address"]] = "PLC"
        rx = [e for e in j.get("rx") or [] if isinstance(e, dict) and isinstance(e.get("pgn"), int)]
        tx = [e for e in j.get("tx") or [] if isinstance(e, dict) and isinstance(e.get("pgn"), int)]
        dbc = j.get("dbc")
        if isinstance(dbc, str) and dbc:
            if config_path is None:
                d.warnings.append("decoding without the DBC %s: the configuration has not been saved to a file" % dbc)
            else:
                path = os.path.join(os.path.dirname(os.path.abspath(config_path)), dbc)
                try:
                    d.messages = load_dbc(path)
                except (OSError, ValueError) as e:
                    d.warnings.append("decoding without the DBC %s: %s" % (dbc, getattr(e, "strerror", None) or e))
        # The config's own signals for PGNs the DBC does not have.
        for e, direction in [(e, "PLC") for e in tx] + [(e, None) for e in rx]:
            if (e["pgn"], None) not in d.messages:
                d.messages[(e["pgn"], None)] = _config_msg(e, direction)
        # Names for addresses: the DBC sender of a PGN the config takes from
        # one source, or sends itself.
        for e in rx:
            m = d.messages.get((e["pgn"], None))
            if isinstance(e.get("source"), int) and m is not None and m.sender:
                d.address_names.setdefault(e["source"], m.sender)
        return d

    def reset(self):
        super().reset()
        self.tp = {}  # (sender, destination or 255) -> session in progress

    # -- helpers --------------------------------------------------------------
    def node_label(self, a):
        name = self.address_names.get(a)
        return "%s (%s)" % (address_text(a), name) if name else address_text(a)

    def message(self, pgn, source=None):
        return self.messages.get((pgn, source)) or self.messages.get((pgn, None))

    def pgn_label(self, pgn, source=None):
        m = self.message(pgn, source)
        name = m.name if m else KNOWN_PGNS.get(pgn)
        return "PGN %d (%s)" % (pgn, name) if name else "PGN %d (0x%04X)" % (pgn, pgn)

    def signal_keys(self):
        out, seen = [], set()
        for _key, m in sorted(self.messages.items(), key=lambda kv: (kv[0][0], kv[0][1] is not None, kv[0][1] or 0)):
            if id(m) in seen:
                continue
            seen.add(id(m))
            for s in m.signals:
                out.append(("%s.%s" % (m.name, s.name), "%s %s" % (m.name, s.name), None))
        return out

    def _values(self, m, data):
        """(texts, [(series key, value)]) of a message's signals; for a
        multiplexed message the page first ("[Page=2]", "[Page=7 unknown]")
        and only the signals the frame carries (switches in the series
        only)."""
        texts, sigs = [], []
        active, unknown, page = m.page(data)
        if page:
            texts.append("[%s%s]" % (page, " unknown" if unknown else ""))
        for j, s in enumerate(m.signals):
            if active is not None and not active[j]:
                continue
            raw = s.raw(data)
            if page and s.multiplexer and raw is not None:
                sigs.append(("%s.%s" % (m.name, s.name), s.physical(raw)))
                continue
            if raw is None:
                texts.append("%s=?" % s.name)
                continue
            texts.append(s.text(raw))
            if not s.special(raw):
                sigs.append(("%s.%s" % (m.name, s.name), s.physical(raw)))
        return texts, sigs

    def _route(self, s):
        src = "from %s" % self.node_label(s["source"])
        return src + (" to %s" % self.node_label(s["destination"]) if s["pdu1"] else "")

    # -- decoding -------------------------------------------------------------
    def decode(self, f):
        if f.gap or f.err:
            return super().decode(f)
        r = self.decode_raw(f)
        if r is not None:
            return r
        if not f.ext:
            return Decoded("other", None, "", "11-bit frame on a J1939 network")
        s = split_id(f.can_id)
        pgn, sa, d = s["pgn"], s["source"], f.data
        if f.rtr:
            return Decoded("pgn", sa, "Remote request", "%s %s" % (self.pgn_label(pgn, sa), self._route(s)))
        if pgn == PGN_ADDRESS_CLAIMED:
            return self._claim(s, d)
        if pgn == PGN_REQUEST:
            if len(d) < 3:
                return Decoded("request", sa, "Request", "malformed (%d bytes) %s" % (len(d), self._route(s)))
            want = _uint_le(d, 0, 24)
            return Decoded("request", sa, "Request", "for %s %s" % (self.pgn_label(want), self._route(s)))
        if pgn == PGN_ACK:
            return self._ack(s, d)
        if pgn == PGN_TP_CM:
            return self._tp_cm(s, d)
        if pgn == PGN_TP_DT:
            return self._tp_dt(s, d)
        return self._data(pgn, sa, s["destination"], d, s["priority"])

    def _claim(self, s, d):
        sa = s["source"]
        if len(d) < 8:
            return Decoded("claim", sa, "Address Claimed", "malformed (%d bytes)" % len(d))
        name = int.from_bytes(d[:8], "little")
        if sa == NULL_ADDRESS:
            return Decoded("claim", sa, "Cannot Claim", "no address for %s" % name_text(name))
        return Decoded("claim", sa, "Address Claimed", "address %s claimed by %s" % (
            self.node_label(sa), name_text(name)))

    def _ack(self, s, d):
        sa = s["source"]
        if len(d) < 8:
            return Decoded("ack", sa, "Acknowledgement", "malformed (%d bytes)" % len(d))
        what = ACK_CONTROL.get(d[0], "control %d" % d[0])
        pgn = _uint_le(d, 40, 24)
        return Decoded("ack", sa, what, "%s for %s, to %s, from %s" % (
            what, self.pgn_label(pgn), self.node_label(d[4]), self.node_label(sa)))

    def _tp_cm(self, s, d):
        sa, da = s["source"], s["destination"]
        if len(d) < 8:
            return Decoded("tp", sa, "TP.CM", "malformed (%d bytes)" % len(d))
        ctl = d[0]
        pgn = _uint_le(d, 40, 24)
        what = TP_CONTROL.get(ctl, "control %d" % ctl)
        label = self.pgn_label(pgn, sa)
        if ctl in (16, 32):
            size, packets = _uint_le(d, 8, 16), d[3]
            self.tp[(sa, da)] = {"pgn": pgn, "size": size, "packets": packets, "parts": {},
                                 "how": "BAM" if ctl == 32 else "RTS/CTS"}
            text = "%s for %s: %d bytes in %d packets, %s" % (what, label, size, packets, self._route(s))
            if ctl == 16:
                text += ", up to %d packets per CTS" % d[4] if d[4] != 0xFF else ", no limit per CTS"
            return Decoded("tp", sa, "TP.CM " + what, text)
        if ctl == 17:
            return Decoded("tp", sa, "TP.CM CTS", "CTS for %s: send %d packets from packet %d, %s" % (
                label, d[1], d[2], self._route(s)))
        if ctl == 19:
            return Decoded("tp", sa, "TP.CM End of message ACK", "%s received: %d bytes in %d packets, %s" % (
                label, _uint_le(d, 8, 16), d[3], self._route(s)))
        if ctl == 255:
            self.tp.pop((sa, da), None)
            self.tp.pop((da, sa), None)
            return Decoded("tp", sa, "TP.CM Abort", "abort %s: %s, %s" % (
                label, TP_ABORT_REASONS.get(d[1], "reason %d" % d[1]), self._route(s)))
        return Decoded("tp", sa, "TP.CM", "%s %s, %s" % (what, label, self._route(s)))

    def _tp_dt(self, s, d):
        sa, da = s["source"], s["destination"]
        st = self.tp.get((sa, da))
        seq = d[0] if d else 0
        if st is None:
            return Decoded("tp", sa, "TP.DT", "packet %d without a session, %s" % (seq, self._route(s)))
        st["parts"][seq] = bytes(d[1:8]).ljust(7, b"\xff")
        part = "packet %d/%d of %s (%s)" % (seq, st["packets"], self.pgn_label(st["pgn"], sa), st["how"])
        if len(st["parts"]) < st["packets"] or not all(k in st["parts"] for k in range(1, st["packets"] + 1)):
            return Decoded("tp", sa, "TP.DT", "%s, %s" % (part, self._route(s)))
        del self.tp[(sa, da)]
        data = b"".join(st["parts"][k] for k in range(1, st["packets"] + 1))[:st["size"]]
        return self._data(st["pgn"], sa, None if da == GLOBAL else da, data, via="%d bytes by %s in %d packets; "
                          "this row is its last TP.DT, packet %d" % (len(data), st["how"], st["packets"], seq))

    def _data(self, pgn, sa, da, d, priority=None, via=None):
        m = self.message(pgn, sa)
        head = "PGN %d from %s" % (pgn, self.node_label(sa)) + (" to %s" % self.node_label(da) if da is not None else "")
        if priority is not None:
            head = "priority %d, %s" % (priority, head)
        if via:
            head += " (%s)" % via
        if m is None:
            name = KNOWN_PGNS.get(pgn) or "PGN %d" % pgn
            return Decoded("pgn", sa, name, "%s: %s" % (head, " ".join("%02X" % b for b in d) or "no data"))
        texts, sigs = self._values(m, d)
        if texts and texts[0].startswith("["):
            texts = [texts[0] + (" " + ", ".join(texts[1:]) if texts[1:] else "")]
        text = "%s: %s" % (head, ", ".join(texts) if texts else "no signals")
        if via:
            text += "; data " + " ".join("%02X" % b for b in d)
        return Decoded("pgn", sa, m.name, text, sigs)


# -- the frame explanation (explain.py) -------------------------------------------

def identifier_layer(f, dec):
    """The identifier layer of a 29-bit frame on a J1939 network: every bit
    with its part (priority, reserved, dp, pf, ps, source) and the PGN."""
    s = split_id(f.can_id)
    parts = ((28, 26, "priority"), (25, 25, "reserved"), (24, 24, "dp"), (23, 16, "pf"), (15, 8, "ps"),
             (7, 0, "source"))
    bits = []
    for n in range(28, -1, -1):
        part = next(p for hi, lo, p in parts if lo <= n <= hi)
        bits.append({"n": n, "v": (f.can_id >> n) & 1, "part": part, "weight": 1 << n})
    m = dec.message(s["pgn"], s["source"])
    name = m.name if m else KNOWN_PGNS.get(s["pgn"])
    ps = ("destination %s" % address_text(s["ps"])) if s["pdu1"] else "group extension 0x%02X" % s["ps"]
    math = "PGN 0x%04X = %d: %s%sPF 0x%02X%s" % (
        s["pgn"], s["pgn"], "reserved 1, " if s["reserved"] else "", "data page 1, " if s["dp"] else "", s["pf"],
        " below 240, so PDU1: PS is the destination and not part of the PGN" if s["pdu1"]
        else " from 240 up, so PDU2: PS (group extension 0x%02X) is part of the PGN" % s["ps"])
    return {"width": 29, "value": f.can_id, "text_id": f.id_text(), "bits": bits, "function_code": None,
            "node": None, "message": name, "what": "J1939 parameter group %d (0x%04X)" % (s["pgn"], s["pgn"]),
            "sender": dec.node_label(s["source"]), "math": math, "configured": False,
            "priority": ("The lower the identifier, the higher its priority: the 3 priority bits come first, so "
                         "priority 0 wins arbitration over 7."),
            "j1939": dict(s, ps_text=ps, source_label=dec.node_label(s["source"]),
                          destination_label=dec.node_label(s["ps"]) if s["pdu1"] else None)}


def _pgn_field(F, start, dec, what):
    pgn = F.bits(start, 24)
    F.add(what, start, 24, "%d (0x%05X)" % (pgn, pgn), "%s, three bytes, low byte first." % dec.pgn_label(pgn),
          how=_le_how(F.data, start, 24))
    return pgn


def _le_how(data, start, length):
    from .explain import le_how
    return le_how(data, start, length)


def explain_data(F, f, dec, context=None):
    """Fills the data fields of a 29-bit frame on a J1939 network; returns
    (kind, title, meaning, notes)."""
    s = split_id(f.can_id)
    pgn, sa, d = s["pgn"], s["source"], f.data
    who = dec.node_label(sa)
    notes = []
    if f.rtr:
        return "pgn", "Remote request from %s" % who, ("A remote request for %s; J1939 asks with a Request "
                                                       "(PGN 59904) instead." % dec.pgn_label(pgn, sa)), notes
    if pgn == PGN_ADDRESS_CLAIMED and len(d) == 8:
        name = int.from_bytes(d, "little")
        for k, label, start, length in NAME_FIELDS:
            v = (name >> start) & ((1 << length) - 1)
            if k == "reserved":
                F.unused(start, length, "Reserved", "Reserved, 0.")
                continue
            F.add(label, start, length, ("yes" if v else "no") if k == "arbitrary_address_capable" else str(v),
                  "NAME bits %d-%d." % (start, start + length - 1) if length > 1 else "NAME bit %d." % start)
        if sa == NULL_ADDRESS:
            return "claim", "Cannot Claim", ("The ECU with NAME 0x%016X found no free address and sends from the null "
                                             "address 254: it stays silent." % name), notes
        return "claim", "Address Claimed from %d" % sa, ("The ECU with NAME 0x%016X claims address %s." % (
            name, who)), notes
    if pgn == PGN_REQUEST and len(d) >= 3:
        want = _pgn_field(F, 0, dec, "Requested PGN")
        return "request", "Request from %s" % who, "%s asks %s to send %s." % (
            who, "every ECU" if s["ps"] == GLOBAL else dec.node_label(s["ps"]), dec.pgn_label(want)), notes
    if pgn == PGN_ACK and len(d) == 8:
        what = ACK_CONTROL.get(d[0], "control %d" % d[0])
        F.add("Control byte", 0, 8, "%d = %s" % (d[0], what), "0 ACK, 1 NACK, 2 access denied, 3 cannot respond.")
        F.add("Group function", 8, 8, str(d[1]), "The group function value, for proprietary and group function PGNs.")
        F.unused(16, 16, "Reserved", "Reserved, sent as FF.")
        F.add("Address acknowledged", 32, 8, str(d[4]), "The address of the ECU whose request this answers.")
        want = _pgn_field(F, 40, dec, "PGN")
        return "ack", "%s from %s" % (what, who), "%s answers %s's request for %s with %s." % (
            who, dec.node_label(d[4]), dec.pgn_label(want), what), notes
    if pgn == PGN_TP_CM and len(d) == 8:
        ctl = d[0]
        what = TP_CONTROL.get(ctl, "control %d" % ctl)
        F.add("Control byte", 0, 8, "%d = %s" % (ctl, what), "16 RTS, 17 CTS, 19 end of message ACK, 32 BAM, "
              "255 abort.")
        if ctl in (16, 19, 32):
            F.add("Message size", 8, 16, "%d bytes" % _uint_le(d, 8, 16), "The size of the whole message.",
                  how=_le_how(d, 8, 16))
            F.add("Packets", 24, 8, str(d[3]), "The number of TP.DT packets.")
            if ctl == 16:
                F.add("Packets per CTS", 32, 8, str(d[4]), "The most packets the sender sends per CTS (255: no "
                      "limit).")
            else:
                F.unused(32, 8, "Reserved", "Reserved, sent as FF.")
        elif ctl == 17:
            F.add("Packets to send", 8, 8, str(d[1]), "How many packets the sender may send now.")
            F.add("Next packet", 16, 8, str(d[2]), "The number of the next packet to send.")
            F.unused(24, 16, "Reserved", "Reserved, sent as FF.")
        elif ctl == 255:
            F.add("Abort reason", 8, 8, "%d = %s" % (d[1], TP_ABORT_REASONS.get(d[1], "?")), "Why the session ends.")
            F.unused(16, 24, "Reserved", "Reserved, sent as FF.")
        want = _pgn_field(F, 40, dec, "PGN of the message")
        if ctl == 32:
            meaning = "%s announces a broadcast of %s: %d bytes in %d TP.DT packets." % (
                who, dec.pgn_label(want, sa), _uint_le(d, 8, 16), d[3])
        elif ctl == 16:
            meaning = "%s asks %s to take %s: %d bytes in %d packets." % (
                who, dec.node_label(s["ps"]), dec.pgn_label(want, sa), _uint_le(d, 8, 16), d[3])
        elif ctl == 17:
            meaning = "%s lets %s send %d packets of %s from packet %d." % (
                who, dec.node_label(s["ps"]), d[1], dec.pgn_label(want), d[2])
        elif ctl == 19:
            meaning = "%s confirms it received all of %s." % (who, dec.pgn_label(want))
        else:
            meaning = "%s ends the transfer of %s: %s." % (who, dec.pgn_label(want), TP_ABORT_REASONS.get(d[1], "?"))
        return "tp", "TP.CM %s from %s" % (what, who), meaning, notes
    if pgn == PGN_TP_DT and d:
        F.add("Sequence number", 0, 8, str(d[0]), "The packet number, from 1.")
        st = getattr(context, "tp", {}).get((sa, s["ps"])) if context is not None else None
        if st:
            a = (d[0] - 1) * 7
            F.add("Data", 8, (len(d) - 1) * 8, " ".join("%02X" % b for b in d[1:]),
                  "Bytes %d-%d of %s." % (a, min(a + 6, st["size"] - 1), dec.pgn_label(st["pgn"], sa)))
            meaning = "Packet %d of %d of %s from %s (%s)." % (d[0], st["packets"], dec.pgn_label(st["pgn"], sa), who,
                                                               st["how"])
        else:
            F.add("Data", 8, (len(d) - 1) * 8, " ".join("%02X" % b for b in d[1:]), "Seven bytes of the message.")
            meaning = "Packet %d of a transport session from %s; its TP.CM is not before it." % (d[0], who)
        return "tp", "TP.DT from %s" % who, meaning, notes
    m = dec.message(pgn, sa)
    route = "from %s" % who + (" to %s" % dec.node_label(s["ps"]) if s["pdu1"] else "")
    if m is None:
        if d:
            F.add("Data", 0, len(d) * 8, " ".join("%02X" % b for b in d), "Neither the DBC nor the configuration "
                  "describes this PGN.")
        return "pgn", "PGN %d from %s" % (pgn, who), "%s %s, priority %d; nothing names this PGN." % (
            dec.pgn_label(pgn), route, s["priority"]), notes
    texts = []
    active, unknown, page = m.page(d)
    if page:
        route += ", page %s%s" % (page, " (no signal is on this page)" if unknown else "")
    for j, sg in enumerate(m.signals):
        if active is not None and not active[j]:
            continue  # not in this frame's page
        raw = sg.raw(d)
        if raw is None:
            continue
        texts.append(sg.text(raw))
        if sg.big:
            notes.append("%s is in big byte order: its bits are not marked in the grid." % sg.name)
            continue
        text = "Raw %s%s." % (raw, ", scale %g, offset %g" % (sg.scale, sg.offset) if (sg.scale, sg.offset) != (1, 0)
                              else "")
        sp = sg.special(raw)
        if sp:
            text += " The value means %s." % sp
        F.add(sg.name, sg.start, sg.length, sg.text(raw).split("=", 1)[1], text, how=_le_how(d, sg.start, sg.length))
    meaning = "%s (PGN %d) %s: %s." % (m.name, pgn, route, ", ".join(texts) or "no signals")
    if m.length > 8:
        notes.append("%s has %d bytes: it travels by the transport protocol (TP.CM and TP.DT)." % (m.name, m.length))
    F.done_gap = ("Not used", "Not used by a signal; J1939 sends unused bits as 1.")
    return "pgn", "%s from %s" % (m.name, who), meaning, notes


def is_context(f):
    """A frame decoding needs before a later one: TP.CM and TP.DT."""
    return f.ext and not f.err and not f.gap and (f.can_id >> 16) & 0xFF in (0xEC, 0xEB)
