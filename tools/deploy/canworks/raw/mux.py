"""DBC-style multiplexed signals (spec can-multiplexed-signals), shared by
raw CAN messages and J1939: the `multiplexer` and `mux` fields of a signal,
their checks, which signals a frame carries (its page), the page list of a
send entry and which signals can share a frame. The plugin has the same
rules in plugin/src/can/mux.*; both are checked against the multiplexing
cases of test/fixtures/config/cases-raw.json and cases-j1939.json.

Signals are given as dicts with the config's keys (`name`, `start_bit`,
`length`, `byte_order`, `signed`, `multiplexer`, `mux`) plus `path`:

    layout = Layout.build(signals, errors, warnings)
    active, unknown, short, need = layout.evaluate(frame_data)
"""

from . import signals as sig

# At most this many pages for `all` and `rotate`.
MAX_PAGES = 64
PAGES = ("program", "all", "rotate")
_SATURATE = 1 << 40
_UINT32 = 0xFFFFFFFF


def _whole(v):
    return isinstance(v, int) and not isinstance(v, bool) and 0 <= v <= _UINT32


def merge(ranges):
    """Sorted, non-overlapping, non-adjacent (lo, hi) ranges."""
    out = []
    for lo, hi in sorted(ranges):
        if out and lo <= out[-1][1] + 1:
            out[-1] = (out[-1][0], max(out[-1][1], hi))
        else:
            out.append((lo, hi))
    return out


def parse_fields(s, path, errors):
    """(is_switch, mux) of signal dict `s` at `path`, where mux is None or
    {"on": name or None, "values": [(lo, hi)]}. Shape errors go to `errors`;
    names and value ranges are checked by Layout.build."""
    is_switch = False
    if "multiplexer" in s:
        if not isinstance(s["multiplexer"], bool):
            errors.append("%s.multiplexer: must be true or false" % path)
        else:
            is_switch = s["multiplexer"]
    if "mux" not in s:
        return is_switch, None
    mux, mp = s["mux"], path + ".mux"
    if not isinstance(mux, dict):
        errors.append("%s: must be an object with values (and on)" % mp)
        return is_switch, None
    ok = True
    for k in mux:
        if k not in ("on", "values"):
            errors.append("%s.%s: unknown field '%s'" % (mp, k, k))
            ok = False
    on = None
    if "on" in mux:
        if not isinstance(mux["on"], str) or not mux["on"]:
            errors.append("%s.on: must be a switch name" % mp)
            ok = False
        else:
            on = mux["on"]
    values = []
    vals = mux.get("values")
    if not isinstance(vals, list) or not vals:
        errors.append("%s.values: must be a list of switch values or [low, high] ranges" % mp)
        ok = False
    else:
        for k, v in enumerate(vals):
            vp = "%s.values[%d]" % (mp, k)
            if _whole(v):
                values.append((v, v))
            elif isinstance(v, list) and len(v) == 2 and _whole(v[0]) and _whole(v[1]):
                if v[0] > v[1]:
                    errors.append("%s: low %d is above high %d" % (vp, v[0], v[1]))
                    ok = False
                    continue
                values.append((v[0], v[1]))
            else:
                errors.append("%s: must be a whole number 0..4294967295 or [low, high]" % vp)
                ok = False
    if not ok:
        return is_switch, None
    return is_switch, {"on": on, "values": values}


def _label(s):
    return s.get("name") or s["path"]


def _intersects(a, b):
    return any(x[0] <= y[1] and y[0] <= x[1] for x in a for y in b)


class Layout:
    """The multiplexing of one message."""

    def __init__(self, signals):
        n = len(signals)
        self.signals = signals
        self.parent = [-1] * n
        self.is_switch = [False] * n
        self.ranges = [[] for _ in range(n)]
        self.order = list(range(n))

    @property
    def multiplexed(self):
        return any(self.is_switch)

    @classmethod
    def build(cls, signals, errors, warnings, specs=None):
        """Checks the multiplexing of `signals` and returns the Layout (not
        multiplexed when there were errors). Each signal dict needs `path`
        and the config's keys; `multiplexer`/`mux` shape errors are reported
        here too (parse_fields), unless the caller parsed them already and
        gives `specs`: [(is_switch, mux, had shape errors)] per signal."""
        lay = cls(signals)
        before = len(errors)
        bad = False
        if specs is None:
            specs = [parse_fields(s, s["path"], errors) for s in signals]
        else:
            bad = any(x[2] for x in specs)
        switches = []
        for i, s in enumerate(signals):
            if not specs[i][0]:
                continue
            switches.append(i)
            if s.get("signed"):
                errors.append("%s: switch %s must be unsigned" % (s["path"], _label(s)))
            length = s.get("length") or 1
            if length > 32:
                errors.append("%s: switch %s has %d bits; a switch has at most 32" % (s["path"], _label(s), length))
            if s.get("name") and any(signals[j].get("name") == s["name"] for j in switches[:-1]):
                errors.append("%s: another switch is also named '%s'" % (s["path"], s["name"]))
        names = ", ".join(_label(signals[j]) for j in switches)
        for i, s in enumerate(signals):
            mux = specs[i][1]
            if mux is None:
                continue
            mp = s["path"] + ".mux"
            if not switches:
                errors.append("%s: the message has no switch (multiplexer: true)" % mp)
                continue
            if mux["on"] is None:
                if len(switches) > 1:
                    errors.append("%s.on: missing; the message has several switches (%s)" % (mp, names))
                    continue
                p = switches[0]
            else:
                p = next((j for j in switches if signals[j].get("name") == mux["on"]), -1)
                if p < 0:
                    errors.append("%s.on: no switch named '%s' in this message" % (mp, mux["on"]))
                    continue
            if p == i:
                errors.append("%s.on: a switch cannot depend on itself" % mp)
                continue
            plen = signals[p].get("length") or 1
            top = _UINT32 if plen >= 32 else (1 << plen) - 1
            ok = True
            for k, (lo, hi) in enumerate(mux["values"]):
                if hi > top:
                    errors.append("%s.values[%d]: %d is outside switch %s (0..%d)"
                                  % (mp, k, lo if lo > top else hi, _label(signals[p]), top))
                    ok = False
            if not ok:
                continue
            lay.parent[i] = p
            lay.ranges[i] = merge(mux["values"])
        reported = set()
        for i in switches:
            if i in reported:
                continue
            chain, x = [i], lay.parent[i]
            while x >= 0 and x not in chain:
                chain.append(x)
                x = lay.parent[x]
            if x < 0:
                continue
            text, y = _label(signals[x]), x
            while True:
                reported.add(y)
                y = lay.parent[y]
                text += " -> " + _label(signals[y])
                if y == x:
                    break
            errors.append("%s: switch cycle %s" % (signals[x]["path"], text))
        if len(errors) != before or bad:
            return cls(signals)
        for i in switches:
            lay.is_switch[i] = True
            if i not in lay.parent:
                warnings.append("%s: switch %s has no signal that depends on it" % (signals[i]["path"], _label(signals[i])))

        def depth(i):
            d, x = 0, lay.parent[i]
            while x >= 0:
                d, x = d + 1, lay.parent[x]
            return d
        lay.order = sorted(range(len(signals)), key=depth)
        return lay

    def _bits(self, i):
        s = self.signals[i]
        return s["start_bit"], s.get("length") or 1, s.get("byte_order") == "big"

    def in_values(self, i, v):
        return any(lo <= v <= hi for lo, hi in self.ranges[i])

    def can_share(self, a, b):
        """True when both signals can be in one frame."""
        x = a
        while self.parent[x] >= 0:
            y = b
            while self.parent[y] >= 0:
                if self.parent[x] == self.parent[y] and not _intersects(self.ranges[x], self.ranges[y]):
                    return False
                y = self.parent[y]
            x = self.parent[x]
        return True

    def activity(self, values):
        """(active list, unknown) for switch `values` (a dict or list indexed
        by signal)."""
        active = [False] * len(self.signals)
        for i in self.order:
            p = self.parent[i]
            active[i] = p < 0 or (active[p] and self.in_values(i, values[p]))
        unknown = False
        for s, sw in enumerate(self.is_switch):
            if sw and active[s]:
                deps = [j for j, p in enumerate(self.parent) if p == s]
                if deps and not any(active[j] for j in deps):
                    unknown = True
        return active, unknown

    def evaluate(self, data):
        """(active, unknown, short, need) for a received frame's data bytes."""
        data = bytes(data)
        values = [0] * len(self.signals)
        active = [False] * len(self.signals)
        for i in self.order:
            p = self.parent[i]
            active[i] = p < 0 or (active[p] and self.in_values(i, values[p]))
            if active[i] and self.is_switch[i]:
                start, length, big = self._bits(i)
                if not sig.fits(start, length, big, len(data)):
                    return active, False, True, sig.last_byte(start, length, big) + 1
                values[i] = sig.unpack(data, start, length, big)
        active, unknown = self.activity(values)
        need = 0
        for i, a in enumerate(active):
            if a:
                need = max(need, sig.last_byte(*self._bits(i)) + 1)
        return active, unknown, False, need

    def switch_values(self, data):
        """{signal index: value} of the switches active in a frame."""
        active, _, short, _ = self.evaluate(data)
        if short:
            return {}
        return {i: sig.unpack(bytes(data), *self._bits(i)) for i, sw in enumerate(self.is_switch) if sw and active[i]}

    def _candidates(self, s):
        out = []
        for j, p in enumerate(self.parent):
            if p == s:
                out.extend(self.ranges[j])
        return merge(out)

    def _count(self, s):
        cand = self._candidates(s)
        if not cand:
            return 1
        children = [j for j, p in enumerate(self.parent) if p == s and self.is_switch[j]]
        points = set()
        for lo, hi in cand:
            points.update((lo, hi + 1))
        for c in children:
            for lo, hi in self.ranges[c]:
                points.update((lo, hi + 1))
        points = sorted(points)
        total = 0
        for a, b in zip(points, points[1:]):
            if not any(lo <= a <= hi for lo, hi in cand):
                continue
            mult = 1
            for c in children:
                if self.in_values(c, a):
                    mult = min(mult * self._count(c), _SATURATE)
            total = min(total + (b - a) * mult, _SATURATE)
        return total

    def page_count(self):
        """Pages of `all` and `rotate` (saturates at 2**40)."""
        n = 1
        for s, sw in enumerate(self.is_switch):
            if sw and self.parent[s] < 0:
                n = min(n * self._count(s), _SATURATE)
        return n

    def pages(self):
        """[(values, active)] in send order; values maps every signal index to
        its switch value (0 for others). Only when page_count() <= MAX_PAGES."""
        out = []
        n = len(self.signals)

        def walk(pending, values):
            if not pending:
                active, _ = self.activity(values)
                out.append((list(values), active))
                return
            s, rest = pending[0], pending[1:]
            cand = self._candidates(s)
            if not cand:
                values[s] = 0
                walk(rest, values)
                return
            for lo, hi in cand:
                for v in range(lo, hi + 1):
                    values[s] = v
                    nxt = rest + [c for c in range(n) if self.is_switch[c] and self.parent[c] == s
                                  and self.in_values(c, v)]
                    walk(nxt, values)
            values[s] = 0

        walk([s for s in range(n) if self.is_switch[s] and self.parent[s] < 0], [0] * n)
        return out

    def page_label(self, data):
        """'Page=2' or 'Page=2 Sub=1' for a frame ('' when not multiplexed)."""
        vals = self.switch_values(data)
        return " ".join("%s=%d" % (self.signals[i].get("name") or "switch", v) for i, v in sorted(vals.items(),
                        key=lambda kv: self.order.index(kv[0])))


def page_text(s, signals):
    """'page Page=1' or 'page Page=1-2,5-9' for a config signal dict with
    `mux` among the message's `signals` (`on` defaults to the one switch);
    '' for others. For declaration comments."""
    mux = s.get("mux") if isinstance(s, dict) else None
    if not isinstance(mux, dict) or not isinstance(mux.get("values"), list):
        return ""
    on = mux.get("on")
    if not on:
        names = [x.get("name") for x in signals if isinstance(x, dict) and x.get("multiplexer") is True]
        on = names[0] if len(names) == 1 else "switch"
    parts = []
    for v in mux["values"]:
        if isinstance(v, list) and len(v) == 2:
            parts.append("%s-%s" % (v[0], v[1]) if v[0] != v[1] else str(v[0]))
        else:
            parts.append(str(v))
    return "page %s=%s" % (on, ",".join(parts))
