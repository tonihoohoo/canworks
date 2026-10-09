"""Located variable declarations for a network's raw messages (spec
canopen-editor-project, "Declarations for raw messages")."""

from ..iec import parse_location
from .contract import hex_id

_RX_KEYS = (("status_location", "status", "BOOL", "received in time"),
            ("counter_location", "counter", "UINT", "frames received"),
            ("id_location", "id", "UDINT", "last identifier"),
            ("dlc_location", "dlc", "USINT", "last DLC"),
            ("data_location", "data", "LWORD", "last data bytes"))
_TX_KEYS = (("trigger_location", "trigger", "BOOL", "send on a rising edge"),
            ("enable_location", "enable", "BOOL", "sending enabled"),
            ("data_location", "data", "LWORD", "data bytes"))
_SIGNED = {"X": "BOOL", "B": "SINT", "W": "INT", "D": "DINT", "L": "LINT"}
_UNSIGNED = {"X": "BOOL", "B": "USINT", "W": "UINT", "D": "UDINT", "L": "ULINT"}


def _num(v):
    return ("%g" % v) if isinstance(v, float) else str(v)


def signal_text(s):
    """'scale 0.1, offset 0, unit %' when the signal has any of them."""
    if not any(k in s for k in ("scale", "offset", "unit")):
        return ""
    parts = ["scale %s" % _num(s.get("scale", 1)), "offset %s" % _num(s.get("offset", 0))]
    if s.get("unit"):
        parts.append("unit %s" % s["unit"])
    return ", ".join(parts)


def declarations(raw, at, net, desc, unique, identifier, declared):
    """[{name, location, type, path, declared_as, node, kind, description}]
    for every location of `raw` (the object at JSON path `at` + "raw"). `net`
    prefixes names ("" or "<network>_"), `desc` descriptions; `unique(name)`
    makes a name unique, `identifier(text)` makes one valid, `declared` maps
    paths to names already declared."""
    out = []
    if not isinstance(raw, dict):
        return out
    for kind, keys, area in (("rx", _RX_KEYS, "I"), ("tx", _TX_KEYS, "Q")):
        for k, m in enumerate(raw.get(kind) or []):
            base = "%sraw.%s[%d]" % (at, kind, k)
            label = m.get("name") or "msg_%s" % hex_id(m.get("id", 0))[2:]
            prefix = net + identifier(label)
            who = "%sraw message %s (%s, %s)" % (desc, m.get("name") or hex_id(m.get("id", 0)),
                                                 hex_id(m.get("id", 0)), "received" if kind == "rx" else "sent")
            for key, suffix, iec_type, text in keys:
                loc = parse_location(m.get(key))
                if not loc:
                    continue
                path = "%s.%s" % (base, key)
                out.append({"name": unique("%s_%s" % (prefix, suffix)), "location": m[key].strip(), "type": iec_type,
                            "path": path, "declared_as": declared.get(path), "node": None, "kind": "raw",
                            "description": "%s: %s" % (who, text)})
            for j, s in enumerate(m.get("signals") or []):
                loc = parse_location(s.get("iec_location"))
                if not loc:
                    continue
                path = "%s.signals[%d].iec_location" % (base, j)
                types = _SIGNED if s.get("signed") else _UNSIGNED
                extra = signal_text(s)
                text = "%s: signal %s" % (who, s.get("name") or j) + ("; " + extra if extra else "")
                out.append({"name": unique("%s_%s" % (prefix, identifier(s.get("name") or "s%d" % j))),
                            "location": s["iec_location"].strip(), "type": types[loc.size], "path": path,
                            "declared_as": declared.get(path), "node": None, "kind": "raw",
                            "description": text})
    return out
