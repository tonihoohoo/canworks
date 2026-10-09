"""Raw messages in the bus trace (spec canopen-bus-trace, "Raw message
decoding"): which configured (or DBC) messages a frame matches, with its
signal values."""

from . import signals as sig

STD_MAX = 0x7FF
EXT_MAX = 0x1FFFFFFF


class RawDecoder:
    """Matches frames against the `rx` and `tx` entries of a `raw` object (or
    messages from dbc.read_dbc(), which have the same fields)."""

    def __init__(self, raw=None, messages=None):
        self.entries = []
        for kind in ("rx", "tx"):
            for m in (raw or {}).get(kind) or []:
                self.entries.append((kind, m))
        for m in messages or []:
            self.entries.append(("dbc", m))

    def matches(self, can_id, extended, rtr=False):
        out = []
        for kind, m in self.entries:
            if bool(m.get("extended")) != bool(extended) or bool(m.get("rtr")) != bool(rtr):
                continue
            top = EXT_MAX if extended else STD_MAX
            mask = m.get("mask", top) if kind == "rx" else top
            if (can_id & mask) == (m["id"] & mask):
                out.append((kind, m))
        return out

    def decode(self, can_id, extended, data, rtr=False):
        """[(message name, [(signal name, raw, scaled or None, unit)])] for
        every matching message."""
        out = []
        for _, m in self.matches(can_id, extended, rtr):
            values = []
            for j, s in enumerate(m.get("signals") or []):
                big = s.get("byte_order") == "big"
                if not sig.fits(s["start_bit"], s["length"], big, len(data)):
                    continue
                raw = sig.unpack(bytes(data), s["start_bit"], s["length"], big, bool(s.get("signed")))
                scaled = None
                if "scale" in s or "offset" in s:
                    scaled = raw * s.get("scale", 1) + s.get("offset", 0)
                values.append((s.get("name") or "s%d" % j, raw, scaled, s.get("unit") or ""))
            out.append((m.get("name") or "0x%X" % m["id"], values))
        return out

    def text(self, can_id, extended, data, rtr=False):
        """'Joystick X=-1 (-0.1 %)', or '' when no message matches."""
        parts = []
        for name, values in self.decode(can_id, extended, data, rtr):
            items = []
            for sname, raw, scaled, unit in values:
                item = "%s=%d" % (sname, raw)
                if scaled is not None or unit:
                    shown = "%g" % (scaled if scaled is not None else raw)
                    item += " (%s%s)" % (shown, " " + unit if unit else "")
                items.append(item)
            parts.append(" ".join([name] + items))
        return "; ".join(parts)
