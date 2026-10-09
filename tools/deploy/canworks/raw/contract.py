"""Checks of a network's `raw` object (spec can-raw-messages), with the same
messages as the plugin (plugin/src/can/raw/config.cpp). Both run
test/fixtures/config/cases-raw.json."""

from ..iec import parse_location
from . import signals as sig

STD_MAX = 0x7FF
EXT_MAX = 0x1FFFFFFF

_SIZE_WORD = {"X": "a bit (%IX/%QX)", "B": "a byte", "W": "a word", "D": "a double word", "L": "a long word"}
_TOOL_ONLY = ("scale", "offset", "unit", "minimum", "maximum", "comment")
_RX_FIELDS = ("name", "id", "extended", "mask", "rtr", "dlc", "timeout_ms", "status_location", "counter_location",
              "id_location", "dlc_location", "data_location", "signals")
_TX_FIELDS = ("name", "id", "extended", "rtr", "dlc", "fill", "period_ms", "on_change", "min_gap_ms",
              "override_protocol", "trigger_location", "enable_location", "data_location", "signals")
_SIGNAL_FIELDS = ("name", "start_bit", "length", "byte_order", "signed", "iec_location") + _TOOL_ONLY


def size_for_bits(bits):
    if bits == 1:
        return "X"
    if bits <= 8:
        return "B"
    if bits <= 16:
        return "W"
    if bits <= 32:
        return "D"
    return "L"


def hex_id(value):
    return "0x%X" % value


def _is_uint(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and v >= 0 and float(v) == int(v)


class _Obj:
    def __init__(self, obj, path, errors, warnings, fields):
        self.obj, self.path, self.errors, self.warnings, self.fields = obj, path, errors, warnings, fields

    def finish(self):
        for key in self.obj:
            if key not in self.fields:
                self.warnings.append("%s.%s: unknown field '%s' is ignored" % (self.path, key, key))

    def uint(self, key, lo, hi, required=False):
        if key not in self.obj:
            if required:
                self.errors.append("%s.%s: missing" % (self.path, key))
            return None
        v = self.obj[key]
        if not _is_uint(v) or v < lo or v > hi:
            self.errors.append("%s.%s: must be a whole number %d..%d" % (self.path, key, lo, hi))
            return None
        return int(v)

    def flag(self, key):
        if key not in self.obj:
            return None
        v = self.obj[key]
        if not isinstance(v, bool):
            self.errors.append("%s.%s: must be true or false" % (self.path, key))
            return None
        return v

    def text(self, key):
        if key not in self.obj:
            return None
        v = self.obj[key]
        if not isinstance(v, str):
            self.errors.append("%s.%s: must be a string" % (self.path, key))
            return None
        return v

    def location(self, key, area, size):
        t = self.text(key)
        if t is None:
            return None
        loc = parse_location(t)
        where = "%s.%s" % (self.path, key)
        if loc is None or loc.area == "M":
            self.errors.append("%s: '%s' is not a located address" % (where, t))
            return None
        if loc.area != area:
            self.errors.append("%s: %s must be %s" % (where, key, "an input (%I)" if area == "I" else "an output (%Q)"))
            return None
        if loc.size != size:
            self.errors.append("%s: %s must be a %%%s%s location" % (where, key, area, size))
            return None
        return loc

    def ident(self):
        ext = self.flag("extended") or False
        top = EXT_MAX if ext else STD_MAX
        if "id" not in self.obj:
            self.errors.append("%s.id: missing" % self.path)
            return None, ext
        v = self.obj["id"]
        if not _is_uint(v) or v > top:
            self.errors.append("%s.id: must be 0..%s %s" % (
                self.path, hex_id(top),
                "(29-bit identifier)" if ext else "(11-bit identifier; set extended for 29 bits)"))
            return None, ext
        return int(v), ext


def _signals(lst, path, area, frame_bytes, dlc_given, errors, warnings):
    out = []
    if lst is None:
        return out
    if not isinstance(lst, list):
        errors.append("%s: must be a list" % path)
        return out
    used = 0
    for k, s in enumerate(lst):
        p = "%s[%d]" % (path, k)
        if not isinstance(s, dict):
            errors.append("%s: must be an object" % p)
            continue
        o = _Obj(s, p, errors, warnings, _SIGNAL_FIELDS)
        before = len(errors)
        name = o.text("name") or ""
        start = o.uint("start_bit", 0, 63, required=True)
        length = o.uint("length", 1, 64, required=True)
        order = o.text("byte_order") or "little"
        if order not in ("little", "big"):
            errors.append('%s.byte_order: must be "little" or "big"' % p)
        big = order == "big"
        signed = o.flag("signed") or False
        label = name or p
        t = o.text("iec_location")
        loc = None
        if t is None:
            if "iec_location" not in s:
                errors.append("%s.iec_location: missing" % p)
        else:
            loc = parse_location(t)
            where = "%s.iec_location" % p
            want = size_for_bits(length or 1)
            if loc is None or loc.area == "M":
                errors.append("%s: '%s' is not a located address" % (where, t))
            elif loc.area != area:
                errors.append("%s: a %s signal needs %s" % (
                    where, "received" if area == "I" else "sent", "an input (%I)" if area == "I" else "an output (%Q)"))
            elif loc.size != want:
                errors.append("%s: signal %s of %d bits needs %s" % (where, label, length, _SIZE_WORD[want]))
        o.finish()
        if len(errors) == before:
            if not sig.fits(start, length, big, frame_bytes):
                errors.append("%s: signal %s reaches past %s" % (
                    p, label, "the message's dlc (%d bytes)" % frame_bytes if dlc_given else "8 bytes"))
            else:
                mine = 0
                for pos in sig.bit_positions(start, length, big):
                    mine |= 1 << pos
                if mine & used:
                    warnings.append("%s: signal %s overlaps another signal" % (p, label))
                used |= mine
        out.append(dict(name=name, start_bit=start, length=length, big_endian=big, signed=signed, location=loc))
    return out


def check_raw(raw, path, listen_only=False, protocol_use=None):
    """Checks `raw` at `path`. Returns (errors, warnings, overrides), each a
    list of messages; `protocol_use(id, extended)` names what the network's
    protocol uses an identifier for, or returns ""."""
    errors, warnings, overrides = [], [], []
    if raw is None:
        return errors, warnings, overrides
    if not isinstance(raw, dict):
        return ["%s: must be an object" % path], warnings, overrides
    top = _Obj(raw, path, errors, warnings, ("dbc", "program_override_protocol", "rx", "tx"))
    top.text("dbc")
    top.flag("program_override_protocol")
    rx = raw.get("rx")
    if rx is not None and not isinstance(rx, list):
        errors.append("%s.rx: must be a list" % path)
        rx = []
    for k, e in enumerate(rx or []):
        p = "%s.rx[%d]" % (path, k)
        if not isinstance(e, dict):
            errors.append("%s: must be an object" % p)
            continue
        o = _Obj(e, p, errors, warnings, _RX_FIELDS)
        o.text("name")
        _, ext = o.ident()
        o.uint("mask", 0, EXT_MAX if ext else STD_MAX)
        rtr = o.flag("rtr") or False
        dlc = o.uint("dlc", 0, 8)
        o.uint("timeout_ms", 0, 600000)
        o.location("status_location", "I", "X")
        o.location("counter_location", "I", "W")
        o.location("id_location", "I", "D")
        o.location("dlc_location", "I", "B")
        o.location("data_location", "I", "L")
        sigs = _signals(e.get("signals"), p + ".signals", "I", 8 if dlc is None else dlc, dlc is not None, errors,
                        warnings)
        if rtr and sigs:
            errors.append("%s.signals: a remote frame carries no data" % p)
        o.finish()
    tx = raw.get("tx")
    if tx is not None and not isinstance(tx, list):
        errors.append("%s.tx: must be a list" % path)
        tx = []
    if listen_only and tx:
        errors.append("%s.tx: a listen-only network cannot send" % path)
    sent = []
    for k, e in enumerate(tx or []):
        p = "%s.tx[%d]" % (path, k)
        if not isinstance(e, dict):
            errors.append("%s: must be an object" % p)
            continue
        o = _Obj(e, p, errors, warnings, _TX_FIELDS)
        name = o.text("name") or ""
        ident, ext = o.ident()
        rtr = o.flag("rtr") or False
        dlc = o.uint("dlc", 0, 8)
        o.uint("fill", 0, 255)
        period = o.uint("period_ms", 1, 60000)
        on_change = o.flag("on_change") or False
        o.uint("min_gap_ms", 0, 60000)
        override = o.flag("override_protocol") or False
        trigger = o.location("trigger_location", "Q", "X")
        o.location("enable_location", "Q", "X")
        data = o.location("data_location", "Q", "L")
        sigs = _signals(e.get("signals"), p + ".signals", "Q", 8 if dlc is None else dlc, dlc is not None, errors,
                        warnings)
        if rtr and (sigs or data is not None):
            errors.append("%s: a remote frame carries no data (no signals or data_location)" % p)
        if not period and not on_change and trigger is None:
            errors.append("%s: needs period_ms, on_change or trigger_location to be sent" % p)
        o.finish()
        if ident is not None:
            sent.append((p, ident, ext, name, override))
    top.finish()
    for i, (p, ident, ext, _, _) in enumerate(sent):
        for q, other, oext, _, _ in sent[:i]:
            if ident == other and ext == oext:
                errors.append("%s: identifier %s is also sent by %s" % (p, hex_id(ident), q))
                break
    if protocol_use:
        for p, ident, ext, name, override in sent:
            what = protocol_use(ident, ext)
            if not what:
                continue
            if override:
                overrides.append("raw message %s (%s) overrides %s" % (name or hex_id(ident), hex_id(ident), what))
            else:
                errors.append("%s: %s is %s; set override_protocol to send it as a raw message" % (p, hex_id(ident), what))
    return errors, warnings, overrides


def tx_dlc(entry):
    """The DLC a `tx` entry sends: its `dlc`, or the smallest that holds every
    signal (at least 1; 8 with data_location; 0 for a remote frame)."""
    if "dlc" in entry:
        return entry["dlc"]
    if entry.get("rtr"):
        return 0
    need = 8 if entry.get("data_location") else 1
    for s in entry.get("signals", []):
        need = max(need, sig.last_byte(s["start_bit"], s["length"], s.get("byte_order") == "big") + 1)
    return need


def locations(raw, path):
    """(location text, config path) of every PLC location in `raw`."""
    out = []
    for kind, keys in (("rx", ("status_location", "counter_location", "id_location", "dlc_location", "data_location")),
                       ("tx", ("trigger_location", "enable_location", "data_location"))):
        for k, e in enumerate((raw or {}).get(kind) or []):
            p = "%s.%s[%d]" % (path, kind, k)
            for key in keys:
                if key in e:
                    out.append((e[key], "%s.%s" % (p, key)))
            for j, s in enumerate(e.get("signals") or []):
                if "iec_location" in s:
                    out.append((s["iec_location"], "%s.signals[%d].iec_location" % (p, j)))
    return out
