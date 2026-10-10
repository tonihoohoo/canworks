"""J1939-73 diagnostic messages (j1939-diagnostics spec): the codec the
trace, canworks-diag, the simulator and the configurator share.

A trouble code (DTC) on the wire is four bytes: the SPN's low 16 bits, then
its top 3 bits above the 5-bit FMI, then the conversion method bit (CM) above
the 7-bit occurrence count. The PLC gets one UDINT instead:

    value = SPN + FMI * 2**19 + OC * 2**24 + CM * 2**31

DM1 and DM2 are the lamp byte, the flash byte and the codes; a message with
no code carries one all-zero code (DM1 must still be 8 bytes). The byte
fixtures in test/fixtures/j1939-dm/cases.json pin this module and the
plugin's codec to the same bytes.
"""

PGN_DM1 = 0xFECA   # 65226 active codes
PGN_DM2 = 0xFECB   # 65227 previously active codes
PGN_DM3 = 0xFECC   # 65228 clear previously active codes (a Request)
PGN_DM11 = 0xFED3  # 65235 clear active codes (a Request)
PGN_DM13 = 0xDF00  # 57088 stop/start broadcast
PGN_DM22 = 0xC300  # 49920 clear one code
PGN_COMPONENT_ID = 0xFEEB  # 65249
PGN_SOFTWARE_ID = 0xFEDA   # 65242
PGN_ACK = 0xE800

# The PGNs canworks handles as diagnostic messages; a DBC import does not
# offer them as rx/tx entries.
DM_PGNS = {PGN_DM1: "DM1", PGN_DM2: "DM2", PGN_DM3: "DM3", PGN_DM11: "DM11", PGN_DM13: "DM13", PGN_DM22: "DM22"}
DM_TITLES = {
    "DM1": "active DTCs", "DM2": "previously active DTCs", "DM3": "clear previously active DTCs",
    "DM11": "clear active DTCs", "DM13": "stop/start broadcast", "DM22": "clear one DTC",
}

MAX_SPN = 0x7FFFF
SERVICE_TOOL_ADDRESS = 249  # off-board diagnostic-service tool #1

# Lamps in byte 1 (states) and byte 2 (flash), highest first: (key, label, shift).
LAMPS = (("mil", "MIL", 6), ("red", "red stop", 4), ("amber", "amber warning", 2), ("protect", "protect", 0))
LAMP_BITS = {key: 1 << shift for key, _, shift in LAMPS}  # the "on" (01) state
LAMP_STATE = {0: "off", 1: "on", 2: "reserved", 3: "n/a"}
FLASH_STATE = {0: "slow flash", 1: "fast flash", 2: "reserved", 3: ""}

# Failure mode identifiers (FMI 0..31), in our own words.
FMI_TEXT = (
    "above normal, most severe",          # 0
    "below normal, most severe",          # 1
    "erratic or incorrect data",          # 2
    "voltage above normal or shorted high",  # 3
    "voltage below normal or shorted low",   # 4
    "current below normal or open circuit",  # 5
    "current above normal or grounded circuit",  # 6
    "mechanical system not responding",   # 7
    "abnormal frequency, pulse width or period",  # 8
    "abnormal update rate",               # 9
    "abnormal rate of change",            # 10
    "root cause not known",               # 11
    "bad device or component",            # 12
    "out of calibration",                 # 13
    "special instructions",               # 14
    "above normal, least severe",         # 15
    "above normal, moderately severe",    # 16
    "below normal, least severe",         # 17
    "below normal, moderately severe",    # 18
    "received network data in error",     # 19
    "data drifted high",                  # 20
    "data drifted low",                   # 21
    "reserved",                           # 22
    "reserved",                           # 23
    "reserved",                           # 24
    "reserved",                           # 25
    "reserved",                           # 26
    "reserved",                           # 27
    "reserved",                           # 28
    "reserved",                           # 29
    "reserved",                           # 30
    "condition exists",                   # 31
)

DM13_CODES = {0: "stop", 1: "start", 2: "reserved", 3: "no action"}
# Byte and shift of each link's 2-bit command in DM13 bytes 1-3.
DM13_LINKS = (("current data link", 0, 6), ("J1587", 0, 4), ("J1922", 0, 2), ("J1939 network 1", 0, 0),
              ("J1939 network 2", 1, 6), ("ISO 9141", 1, 4), ("J1850", 1, 2), ("other", 1, 0),
              ("J1939 network 3", 2, 6), ("proprietary network 1", 2, 4), ("proprietary network 2", 2, 2),
              ("J1939 network 4", 2, 0))
DM22_CONTROL = {0x01: "clear previously active DTC", 0x02: "ACK clear previously active DTC",
                0x03: "NACK clear previously active DTC", 0x11: "clear active DTC", 0x12: "ACK clear active DTC",
                0x13: "NACK clear active DTC"}
DM22_NACK = {0: "general", 1: "access denied", 2: "unknown DTC", 3: "DTC no longer previously active",
             4: "DTC no longer active"}


def fmi_text(fmi):
    return FMI_TEXT[fmi] if 0 <= fmi < len(FMI_TEXT) else "?"


class Dtc:
    """One trouble code."""

    __slots__ = ("spn", "fmi", "oc", "cm")

    def __init__(self, spn, fmi, oc=0, cm=False):
        self.spn, self.fmi, self.oc, self.cm = spn, fmi, oc, bool(cm)

    def __eq__(self, other):
        return isinstance(other, Dtc) and (self.spn, self.fmi, self.oc, self.cm) == \
            (other.spn, other.fmi, other.oc, other.cm)

    def __repr__(self):
        return "Dtc(%d, %d, %d%s)" % (self.spn, self.fmi, self.oc, ", cm=True" if self.cm else "")

    @property
    def value(self):
        """The PLC's UDINT."""
        return to_value(self.spn, self.fmi, self.oc, self.cm)

    def to_bytes(self):
        return bytes((self.spn & 0xFF, (self.spn >> 8) & 0xFF, ((self.spn >> 11) & 0xE0) | (self.fmi & 0x1F),
                      (0x80 if self.cm else 0) | (self.oc & 0x7F)))

    @classmethod
    def from_bytes(cls, b):
        return cls(b[0] | b[1] << 8 | (b[2] & 0xE0) << 11, b[2] & 0x1F, b[3] & 0x7F, bool(b[3] & 0x80))

    def is_zero(self):
        return self.spn == 0 and self.fmi == 0 and self.oc == 0 and not self.cm

    def text(self, spn_name=None):
        t = "SPN %d%s FMI %d (%s) OC %d" % (self.spn, " %s" % spn_name if spn_name else "", self.fmi,
                                            fmi_text(self.fmi), self.oc)
        return t + (" [older SPN format]" if self.cm else "")

    def as_dict(self):
        return {"spn": self.spn, "fmi": self.fmi, "oc": self.oc, "cm": self.cm}


def to_value(spn, fmi, oc=0, cm=False):
    return (spn & MAX_SPN) | (fmi & 0x1F) << 19 | (oc & 0x7F) << 24 | (0x80000000 if cm else 0)


def from_value(value):
    return Dtc(value & MAX_SPN, (value >> 19) & 0x1F, (value >> 24) & 0x7F, bool(value & 0x80000000))


class DmList:
    """A parsed DM1 or DM2: lamps and flash bytes and the codes (the all-zero
    "no code" left out)."""

    def __init__(self, lamps=0, flash=0xFF, dtcs=()):
        self.lamps, self.flash, self.dtcs = lamps, flash, list(dtcs)

    def lamp_states(self):
        """{key: (state 0..3, flash 0..3)}."""
        return {key: ((self.lamps >> s) & 3, (self.flash >> s) & 3) for key, _, s in LAMPS}

    def lamps_text(self):
        if self.lamps == 0xFF:
            return "lamps n/a"
        parts = []
        for key, label, shift in LAMPS:
            st, fl = (self.lamps >> shift) & 3, (self.flash >> shift) & 3
            if st == 1:
                parts.append("%s on%s" % (label, ", " + FLASH_STATE[fl] if FLASH_STATE[fl] else ""))
            elif st == 2:
                parts.append("%s reserved" % label)
        return ", ".join(parts) if parts else "lamps off"


def parse_dm(data):
    """DM1/DM2 payload -> DmList, or None when shorter than 6 bytes."""
    data = bytes(data)
    if len(data) < 6:
        return None
    out = DmList(data[0], data[1])
    for k in range(2, len(data) - 3, 4):
        d = Dtc.from_bytes(data[k:k + 4])
        if d.is_zero():
            continue
        # Unused bytes of a short single-code message are 0xFF.
        if data[k:k + 4] == b"\xff\xff\xff\xff":
            continue
        out.dtcs.append(d)
    return out


def build_dm(lamps, flash, dtcs):
    """DM1/DM2 payload: at least 8 bytes; with no code one all-zero code and
    two 0xFF bytes."""
    body = bytes((lamps & 0xFF, flash & 0xFF))
    if not dtcs:
        return body + b"\x00\x00\x00\x00\xff\xff"
    body += b"".join(d.to_bytes() for d in dtcs)
    return body + b"\xff" * (8 - len(body)) if len(body) < 8 else body


def lamp_byte(keys):
    """The "on" state of each named lamp ("mil", "red", "amber", "protect")."""
    v = 0
    for k in keys:
        v |= LAMP_BITS[k]
    return v


def flash_byte(codes):
    """Flash byte for active codes [(lamp keys, "slow"|"fast"|None)]: every
    lamp no flash (11) unless an active code lights it with a flash; fast wins."""
    out = 0xFF
    for keys, flash in codes:
        if flash is None:
            continue
        for k in keys:
            shift = dict((key, s) for key, _, s in LAMPS)[k]
            cur = (out >> shift) & 3
            new = 1 if flash == "fast" else 0
            if cur == 3 or (cur == 0 and new == 1):
                out = (out & ~(3 << shift)) | (new << shift)
    return out


def parse_dm13(data):
    """{link label: "stop"|"start"|...} for the links not "no action", plus
    "_byte4" and "_duration_s"."""
    data = bytes(data) + b"\xff" * 8
    out = {}
    for label, byte, shift in DM13_LINKS:
        code = (data[byte] >> shift) & 3
        if code != 3:
            out[label] = DM13_CODES[code]
    out["_byte4"] = data[3]
    dur = data[4] | data[5] << 8
    out["_duration_s"] = None if dur == 0xFFFF else dur
    return out


def dm13_command(data):
    """What DM13 tells the current data link: "stop", "start" or None."""
    code = (bytes(data)[0] >> 6) & 3 if data else 3
    return {0: "stop", 1: "start"}.get(code)


def parse_dm22(data):
    """(control text, NACK reason text or None, Dtc without OC)."""
    data = bytes(data) + b"\xff" * 8
    ctl = data[0]
    reason = DM22_NACK.get(data[1], "0x%02X" % data[1]) if ctl in (0x03, 0x13) else None
    d = Dtc.from_bytes(data[5:8] + b"\x00")
    return DM22_CONTROL.get(ctl, "control 0x%02X" % ctl), reason, d


def parse_id_text(data, pgn=PGN_COMPONENT_ID):
    """Component ID (make*model*serial*unit*) or Software ID (a field count,
    then the `*`-delimited versions): the ASCII fields."""
    data = bytes(data)
    if pgn == PGN_SOFTWARE_ID and data:
        data = data[1:]
    text = data.decode("latin-1").rstrip("\xff\x00")
    fields = text.split("*")
    if fields and fields[-1] == "":
        fields.pop()
    return fields
