"""Triggers (canopen-bus-trace: "Triggers").

A trigger is a dict, the same in the configurator (JSON) and the CLI, which
writes it as text (parse()):

    {"conditions": [cond] or [a, b], "combine": "and" | "then",
     "window_ms": 100, "count": 1, "mode": "normal" | "single",
     "pre_s": 5, "post_s": 2, "autosave": {"format": "blf", "folder": "..."} or None}

Conditions ({"type": ...}):
    frame          id, mask (default all bits), data / data_mask (hex), dir (rx, tx, any)
    emcy           node (optional), code (optional)
    state          node, state (bootup, stopped, operational, preop, any): heartbeat or boot-up
    heartbeat_lost node (optional): the status bit of a configured node falls
    boot_error     node (optional): a configured node's boot error appears
    sdo_abort      node (optional)
    signal         key, op (>, <, =, !=, cross_up, cross_down, rising, falling), value
    bus            state (warning, passive, off): the bus state reaches it
    error_frame

"and": both conditions matched within window_ms of each other. "then": the
second matched within window_ms after the first (window_ms 0: any time after).
count N: fires on every Nth combined match.
"""

import re

COND_TYPES = ("frame", "emcy", "state", "heartbeat_lost", "boot_error", "sdo_abort", "signal", "bus", "error_frame")
SIGNAL_OPS = (">", "<", "=", "!=", "cross_up", "cross_down", "rising", "falling")
STATES = {"bootup": 0, "stopped": 4, "operational": 5, "preop": 127}
BUS_LEVELS = {"warning": 2, "passive": 3, "off": 4}
MAX_POST_S = 600


class TriggerError(ValueError):
    pass


def _int(v, what):
    if isinstance(v, bool):
        raise TriggerError("%s must be a number" % what)
    if isinstance(v, int):
        return v
    try:
        return int(str(v).strip(), 0)
    except (TypeError, ValueError):
        raise TriggerError("%s %r is not a number" % (what, v))


def _hex(text, what):
    digits = "".join(str(text or "").split()).replace(".", "")
    if len(digits) % 2:
        raise TriggerError("%s %r is not hexadecimal bytes" % (what, text))
    try:
        return bytes.fromhex(digits)
    except ValueError:
        raise TriggerError("%s %r is not hexadecimal bytes" % (what, text))


def check_condition(c):
    """A normalized copy of a condition; raises TriggerError."""
    if not isinstance(c, dict) or c.get("type") not in COND_TYPES:
        raise TriggerError("condition type must be one of %s" % ", ".join(COND_TYPES))
    t = c["type"]
    out = {"type": t}
    if "node" in c and c["node"] not in (None, ""):
        n = _int(c["node"], "node")
        if not 1 <= n <= 127:
            raise TriggerError("node must be 1-127")
        out["node"] = n
    if t == "frame":
        if c.get("id") in (None, ""):
            raise TriggerError("a frame condition needs an id")
        out["id"] = _int(c["id"], "id")
        out["mask"] = _int(c.get("mask", 0x1FFFFFFF) if c.get("mask") not in (None, "") else 0x1FFFFFFF, "mask")
        data = _hex(c.get("data", ""), "data")
        mask = _hex(c.get("data_mask", ""), "data_mask") if c.get("data_mask") else b"\xff" * len(data)
        if len(mask) != len(data):
            raise TriggerError("data and data_mask must have the same length")
        out["data"], out["data_mask"] = data.hex(), mask.hex()
        d = str(c.get("dir") or "any").lower()
        if d not in ("rx", "tx", "any"):
            raise TriggerError("dir must be rx, tx or any")
        out["dir"] = d
    elif t == "emcy":
        if c.get("code") not in (None, ""):
            out["code"] = _int(c["code"], "code")
    elif t == "state":
        s = str(c.get("state") or "any").lower().replace("-", "").replace("_", "")
        s = {"preoperational": "preop", "bootup": "bootup", "boot": "bootup"}.get(s, s)
        if s != "any" and s not in STATES:
            raise TriggerError("state must be bootup, stopped, operational, preop or any")
        out["state"] = s
    elif t == "signal":
        if not c.get("key"):
            raise TriggerError("a signal condition needs a signal")
        out["key"] = str(c["key"])
        op = str(c.get("op") or ">")
        if op == "==":
            op = "="
        if op not in SIGNAL_OPS:
            raise TriggerError("op must be one of %s" % ", ".join(SIGNAL_OPS))
        out["op"] = op
        if op not in ("rising", "falling"):
            try:
                out["value"] = float(c.get("value"))
            except (TypeError, ValueError):
                raise TriggerError("a signal condition with %s needs a number" % op)
    elif t == "bus":
        s = str(c.get("state") or "warning").lower().replace("error-", "").replace("bus-", "")
        if s not in BUS_LEVELS:
            raise TriggerError("bus state must be warning, passive or off")
        out["state"] = s
    return out


def resolve_signals(spec, signal_keys):
    """The trigger with each signal condition's name turned into a series key
    of the decoder: the full key ("valve_RPDO1.Output_1") or, when it names
    one signal only, the signal name alone. `signal_keys` is
    Decoder.signal_keys(). Raises TriggerError for a name the config does not
    decode, so the trigger cannot wait for a signal that never comes."""
    conds = [c for c in (spec or {}).get("conditions") or [] if c.get("type") == "signal"]
    if not conds:
        return spec
    keys = [k for k, _label, _node in signal_keys]
    if not keys:
        raise TriggerError("a signal condition needs the config's PDOs to decode (--config canworks.json)")
    for c in conds:
        name = c["key"]
        if name in keys:
            continue
        found = [k for k in keys if k.split(".", 1)[-1] == name]
        if len(found) == 1:
            c["key"] = found[0]
            continue
        shown = ", ".join(found or keys[:12]) + ("" if found or len(keys) <= 12 else ", ...")
        raise TriggerError("%s signal %r; %s: %s" % ("more than one" if found else "no", name,
                                                     "use one of" if found else "the config's signals are", shown))
    return spec


def check(spec):
    """A normalized copy of a trigger; raises TriggerError."""
    if not isinstance(spec, dict):
        raise TriggerError("a trigger must be an object")
    conds = spec.get("conditions") or []
    if not 1 <= len(conds) <= 2:
        raise TriggerError("a trigger has one or two conditions")
    out = {"conditions": [check_condition(c) for c in conds]}
    combine = str(spec.get("combine") or "and").lower()
    if combine not in ("and", "then"):
        raise TriggerError("combine must be and or then")
    out["combine"] = combine
    out["window_ms"] = max(0, _int(spec.get("window_ms", 100), "window_ms"))
    out["count"] = max(1, _int(spec.get("count", 1), "count"))
    mode = str(spec.get("mode") or "single").lower()
    if mode not in ("normal", "single"):
        raise TriggerError("mode must be normal or single")
    out["mode"] = mode
    try:
        out["pre_s"] = max(0.0, float(spec.get("pre_s", 5)))
        out["post_s"] = float(spec.get("post_s", 2))
    except (TypeError, ValueError):
        raise TriggerError("pre_s and post_s must be numbers")
    if not 0 <= out["post_s"] <= MAX_POST_S:
        raise TriggerError("post-trigger time must be 0-%d s" % MAX_POST_S)
    autosave = spec.get("autosave")
    if autosave:
        if not isinstance(autosave, dict) or not autosave.get("format"):
            raise TriggerError("autosave needs a format")
        out["autosave"] = {"format": str(autosave["format"]), "folder": autosave.get("folder") or ""}
    else:
        out["autosave"] = None
    return out


def describe_condition(c):
    t = c["type"]
    node = " node %d" % c["node"] if "node" in c else ""
    if t == "frame":
        s = "frame 0x%X" % c["id"]
        if c["mask"] != 0x1FFFFFFF:
            s += "/0x%X" % c["mask"]
        if c["data"]:
            s += " data %s" % c["data"].upper()
            if c["data_mask"] != "ff" * (len(c["data"]) // 2):
                s += " mask %s" % c["data_mask"].upper()
        if c["dir"] != "any":
            s += " " + c["dir"].capitalize()
        return s
    if t == "emcy":
        return "EMCY" + (" from" + node if node else "") + (" code 0x%04X" % c["code"] if "code" in c else "")
    if t == "state":
        return "state%s %s" % (node, c["state"])
    if t == "signal":
        return "%s %s%s" % (c["key"], c["op"], "" if "value" not in c else " %g" % c["value"])
    if t == "bus":
        return "bus %s" % c["state"]
    return t.replace("_", " ") + node


def describe(spec):
    parts = [describe_condition(c) for c in spec["conditions"]]
    text = (" and " if spec["combine"] == "and" else " then ").join(parts)
    if spec["count"] > 1:
        text += ", every %d" % spec["count"]
    return text


# ---------------------------------------------------------------------------
# Text form (CLI)

_ALIASES = {"sdo-abort": "sdo_abort", "heartbeat-lost": "heartbeat_lost", "boot-error": "boot_error",
            "error-frame": "error_frame", "nmt": "state"}


def parse_condition(text):
    words = text.split()
    if not words:
        raise TriggerError("empty trigger condition")
    t = _ALIASES.get(words[0].lower(), words[0].lower())
    c = {"type": t}
    for w in words[1:]:
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_.]*)(!=|=|>|<)(.*)$", w)
        if not m:
            raise TriggerError("%r: write key=value (for example node=23)" % w)
        k, op, v = m.groups()
        if op == "=" and (k in ("key", "op", "value", "node") or t != "signal"):
            c[k] = v
        elif t == "signal":  # shortcut: signal NAME>3
            c["key"], c["op"], c["value"] = k, op, v
        else:
            raise TriggerError("%r: write key=value (for example node=23)" % w)
    return check_condition(c)


def parse(text, **options):
    """"emcy node=23", "frame id=0x197 data=10", "a && b", "a -> b". Options
    (mode, pre_s, post_s, count, window_ms, autosave) are added as given."""
    text = text.strip()
    if "->" in text:
        a, b = text.split("->", 1)
        conds, combine = [parse_condition(a), parse_condition(b)], "then"
    elif "&&" in text:
        a, b = text.split("&&", 1)
        conds, combine = [parse_condition(a), parse_condition(b)], "and"
    else:
        conds, combine = [parse_condition(text)], "and"
    spec = {"conditions": conds, "combine": combine}
    spec.update({k: v for k, v in options.items() if v is not None})
    return check(spec)


# ---------------------------------------------------------------------------
# Evaluation

class _Cond:
    def __init__(self, c):
        self.c = c
        self.prev = {}  # signal key -> last value; node -> last status
        if c["type"] == "frame":
            self.data = bytes.fromhex(c["data"])
            self.dmask = bytes.fromhex(c["data_mask"])

    def frame(self, f, d):
        c, t = self.c, self.c["type"]
        node = c.get("node")
        if t == "frame":
            if f.gap or f.err or (f.can_id ^ c["id"]) & c["mask"] & 0x1FFFFFFF:
                return False
            if c["dir"] == "rx" and f.tx or c["dir"] == "tx" and not f.tx:
                return False
            if self.data:
                if len(f.data) < len(self.data):
                    return False
                return all((a & m) == (b & m) for a, b, m in zip(f.data, self.data, self.dmask))
            return True
        if t == "error_frame":
            return f.err
        if d is None:
            return False
        if node is not None and d.node != node and t in ("emcy", "state", "sdo_abort"):
            return False
        if t == "emcy":
            if d.kind != "emcy" or len(f.data) < 2:
                return False
            code = int.from_bytes(f.data[:2], "little")
            return code != 0 and ("code" not in c or code == c["code"])
        if t == "state":
            if d.kind != "heartbeat" or f.rtr or not f.data:
                return False
            state = f.data[0] & 0x7F
            key = d.node
            changed = self.prev.get(key) != state
            self.prev[key] = state
            want = c["state"]
            if want == "any":
                return changed
            return state == STATES[want] and (changed or want == "bootup")
        if t == "sdo_abort":
            return d.kind == "sdo" and bool(f.data) and f.data[0] >> 5 == 4
        if t == "signal":
            for key, v in d.signals:
                if key == c["key"]:
                    return self._signal(v)
        return False

    def _signal(self, v):
        c = self.c
        op = c["op"]
        prev = self.prev.get("v")
        self.prev["v"] = v
        x = c.get("value")
        if op == ">":
            return v > x
        if op == "<":
            return v < x
        if op == "=":
            return v == x
        if op == "!=":
            return v != x
        if prev is None:
            return False
        if op == "cross_up":
            return prev <= x < v
        if op == "cross_down":
            return prev >= x > v
        if op == "rising":
            return not prev and bool(v)
        if op == "falling":
            return bool(prev) and not v
        return False

    def status(self, st):
        """A status answer: node status bits, boot errors, bus state."""
        c, t = self.c, self.c["type"]
        hit = False
        if t == "heartbeat_lost":
            for n in st.get("nodes") or []:
                nid = n.get("node_id")
                if c.get("node") not in (None, nid):
                    continue
                now = bool(n.get("status"))
                if self.prev.get(nid) is True and not now:
                    hit = True
                self.prev[nid] = now
        elif t == "boot_error":
            for n in st.get("nodes") or []:
                nid = n.get("node_id")
                if c.get("node") not in (None, nid):
                    continue
                err = n.get("boot_error") or None
                if err and self.prev.get(nid) != err:
                    hit = True
                self.prev[nid] = err
        elif t == "bus":
            level = (st.get("bus") or {}).get("state") or 0
            was = self.prev.get("bus", 0)
            want = BUS_LEVELS[c["state"]]
            hit = was < want <= level
            self.prev["bus"] = level
        return hit


class Engine:
    """Feeds frames and status answers; hit(time_us) -> True when the
    trigger fires."""

    def __init__(self, spec):
        self.spec = check(spec)
        self.conds = [_Cond(c) for c in self.spec["conditions"]]
        self.last = [None] * len(self.conds)  # last match time per condition
        self.matches = 0
        self.hits = []

    def _matched(self, k, time_us):
        self.last[k] = time_us
        spec = self.spec
        if len(self.conds) == 1:
            ok = True
        else:
            other = self.last[1 - k]
            window = spec["window_ms"] * 1000
            if other is None:
                ok = False
            elif spec["combine"] == "and":
                ok = abs(time_us - other) <= window
            else:  # then: the second after the first
                ok = k == 1 and self.last[0] is not None and (window == 0 or time_us - self.last[0] <= window)
        if not ok:
            return False
        if len(self.conds) == 2:
            self.last = [None, None]
        self.matches += 1
        if self.matches % spec["count"]:
            return False
        self.hits.append(time_us)
        return True

    def frame(self, f, d):
        fired = False
        for k, c in enumerate(self.conds):
            if c.c["type"] in ("heartbeat_lost", "boot_error", "bus"):
                continue
            if c.frame(f, d):
                fired = self._matched(k, f.time_us) or fired
        return fired

    def status(self, time_us, st):
        fired = False
        for k, c in enumerate(self.conds):
            if c.c["type"] in ("heartbeat_lost", "boot_error", "bus") and c.status(st):
                fired = self._matched(k, time_us) or fired
        return fired


def autosave_name(prefix, time_us, fmt_ext):
    import datetime as dt
    d = dt.datetime.fromtimestamp(time_us / 1e6, dt.timezone.utc)
    return "%s-trace-%s.%s" % (prefix or "canworks", d.strftime("%Y%m%dT%H%M%S.") + "%03dZ" % (d.microsecond // 1000),
                               fmt_ext)
