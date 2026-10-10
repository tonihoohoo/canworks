"""Raw messages in the bus trace (spec canopen-bus-trace, "Raw message
decoding"): which configured (or DBC) messages a frame matches, with its
signal values. A multiplexed message (can-multiplexed-signals) decodes only
the signals its frame carries, by the switches' values (mux.Layout, not
cantools, so a page the message does not describe is shown, not an
error)."""

from . import mux
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
        self._layouts = {}

    def layout(self, m):
        """The mux.Layout of a message (not multiplexed when its
        multiplexing does not check)."""
        key = id(m)
        if key not in self._layouts:
            sigs = [dict(s, path="signals[%d]" % j) for j, s in enumerate(m.get("signals") or [])
                    if isinstance(s, dict)]
            self._layouts[key] = (m, mux.Layout.build(sigs, [], []))
        return self._layouts[key][1]

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

    def decode_pages(self, can_id, extended, data, rtr=False):
        """For every matching message {"name", "page" ("Page=2", "" when not
        multiplexed or the switch is not in the frame), "unknown_page" (the
        switches select no page), "signals": [(signal name, raw, scaled or
        None, unit)] of the signals the frame carries, "active": their
        indexes in the message's signals, "switches": the indexes of its
        switches}."""
        out = []
        data = bytes(data)
        for _, m in self.matches(can_id, extended, rtr):
            lay = self.layout(m)
            active, unknown, short = None, False, False
            if lay.multiplexed:
                active, unknown, short, _ = lay.evaluate(data)
            values, shown = [], []
            for j, s in enumerate(m.get("signals") or []):
                if active is not None and not active[j]:
                    continue
                big = s.get("byte_order") == "big"
                if not sig.fits(s["start_bit"], s["length"], big, len(data)):
                    continue
                raw = sig.unpack(data, s["start_bit"], s["length"], big, bool(s.get("signed")))
                scaled = None
                if "scale" in s or "offset" in s:
                    scaled = raw * s.get("scale", 1) + s.get("offset", 0)
                values.append((s.get("name") or "s%d" % j, raw, scaled, s.get("unit") or ""))
                shown.append(j)
            out.append({"name": m.get("name") or "0x%X" % m["id"],
                        "page": "" if short or not lay.multiplexed else lay.page_label(data),
                        "unknown_page": bool(unknown), "signals": values, "active": shown,
                        "switches": [j for j, x in enumerate(lay.is_switch) if x]})
        return out

    def decode(self, can_id, extended, data, rtr=False):
        """[(message name, [(signal name, raw, scaled or None, unit)])] for
        every matching message, with the signals the frame carries."""
        return [(d["name"], d["signals"]) for d in self.decode_pages(can_id, extended, data, rtr)]

    def text(self, can_id, extended, data, rtr=False):
        """'Joystick X=-1 (-0.1 %)', 'Status [Page=2] Press=400 (400 kPa)',
        'Status [Page=7 unknown]', or '' when no message matches."""
        parts = []
        for d in self.decode_pages(can_id, extended, data, rtr):
            items = [d["name"]]
            if d["page"]:
                items.append("[%s%s]" % (d["page"], " unknown" if d["unknown_page"] else ""))
            for j, (sname, raw, scaled, unit) in zip(d["active"], d["signals"]):
                if d["page"] and j in d["switches"]:
                    continue  # named in the page
                item = "%s=%d" % (sname, raw)
                if scaled is not None or unit:
                    shown = "%g" % (scaled if scaled is not None else raw)
                    item += " (%s%s)" % (shown, " " + unit if unit else "")
                items.append(item)
            parts.append(" ".join(items))
        return "; ".join(parts)
