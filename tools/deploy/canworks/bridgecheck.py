"""The checks of a bridge config (modbus-bridge): the top-level `bridge`
object and the byte rules of its locations, in the words of
plugin/src/can/config.cpp (parse_bridge, report_byte_overlaps).

A bridge config is byte-addressed: %IWn covers input bytes n and n+1, and
two locations clash when their bytes overlap, except bits of one byte with
different bit numbers. Word and larger locations start at an even byte.
"""

import ipaddress

from .iec import parse_location

# Bytes per location size letter.
SIZE_BYTES = {"X": 1, "B": 1, "W": 2, "D": 4, "L": 8}
# The bridge's own blocks.
STATUS_BYTES = 8
CONTROL_BYTES = 6
LIVE_LIST_BYTES = 16
SDO_BYTES = 14
# The largest byte address of a bridge config (+1), per direction.
IMAGE_BYTES = 8192

KEYS = ("listen", "unit_id", "word_order", "max_clients", "writers", "readers", "watchdog_ms", "on_client_loss",
        "status_location", "control_location", "live_lists", "sdo_bridge_location", "sdo_bridge_write")

NOT_BRIDGE_CONFIG = ("not a bridge config: canworks-bridge serves a version 2 config with a top-level 'bridge' "
                     "object")
PLUGIN_REFUSES = ("this is a Modbus bridge config (it has a 'bridge' object): run it with canworks-bridge, not the "
                  "OpenPLC plugin")


def is_bridge_config(cfg):
    return isinstance(cfg, dict) and "bridge" in cfg


def _uint(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, float) and value >= 0 and value == int(value):
        return int(value)
    if isinstance(value, str) and value and not value.startswith("-"):
        try:
            return int(value, 0)
        except ValueError:
            return None
    return None


def _get_uint(obj, key, where, maximum, err):
    if key not in obj:
        return None
    v = _uint(obj[key])
    if v is None:
        err(where, "field '%s' must be a non-negative integer" % key, [where + "." + key])
        return None
    if v > maximum:
        err(where, "field '%s' is out of range (max %d): %d" % (key, maximum, v), [where + "." + key])
        return None
    return v


def _valid_listen(text):
    v6 = text.startswith("[")
    colon = text.find("]:") if v6 else text.rfind(":")
    if colon < 0:
        return False
    host = text[1:colon] if v6 else text[:colon]
    port = text[colon + (2 if v6 else 1):]
    try:
        if v6:
            ipaddress.IPv6Address(host)
        else:
            ipaddress.IPv4Address(host)
    except ValueError:
        return False
    return port.isdigit() and 1 <= int(port) <= 65535


def _valid_address_or_prefix(text):
    if not isinstance(text, str):
        return False
    host, slash, bits = text.partition("/")
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return False
    if not slash:
        return True
    return bits.isdigit() and int(bits) <= addr.max_prefixlen


def _block(obj, key, where, area, nbytes, err):
    """A byte location of a bridge block in the right area; None if absent or wrong."""
    if key not in obj:
        return None
    text = obj[key]
    if not isinstance(text, str) or not text:
        err(where, "field '%s' must be a non-empty string" % key, [where + "." + key])
        return None
    loc = parse_location(text)
    if loc is None:
        return None  # the location syntax is reported by the schema
    if loc.size != "B" or loc.area != area:
        err(where, "%s must be %s byte location (%%%sB...) where its %d-byte block starts, not %s"
            % (key, "an input" if area == "I" else "an output", area, nbytes, loc), [where + "." + key])
        return None
    if loc.index + nbytes > IMAGE_BYTES:
        err(where, "%s %s: its %d-byte block ends outside the image (%d bytes)" % (key, loc, nbytes, IMAGE_BYTES),
            [where + "." + key])
        return None
    return loc


def check_bridge(cfg, nets, err, warn):
    """The `bridge` object. `nets` is contract.networks(cfg). Returns the
    bridge blocks as uses (loc, who, path, nbytes)."""
    b = cfg.get("bridge")
    w = "bridge"
    uses = []
    if not isinstance(b, dict):
        err("", "field 'bridge' must be an object", ["bridge"])
        return uses
    listen = b.get("listen")
    if "listen" not in b:
        err(w, "missing required field 'listen'", [w + ".listen"])
    elif not isinstance(listen, str) or not listen:
        err(w, "field 'listen' must be a non-empty string", [w + ".listen"])
    elif not _valid_listen(listen):
        err(w, "field 'listen' must be address:port with a numeric address, such as 0.0.0.0:502 or [::]:502, not "
               "\"%s\"" % listen, [w + ".listen"])
    _get_uint(b, "unit_id", w, 255, err)
    if "word_order" in b and b["word_order"] not in ("high_first", "low_first"):
        err(w, "field 'word_order' must be \"high_first\" or \"low_first\"", [w + ".word_order"])
    v = _get_uint(b, "max_clients", w, 64, err)
    if v is not None and v < 1:
        err(w, "field 'max_clients' must be 1-64", [w + ".max_clients"])
    for key in ("writers", "readers"):
        if key not in b:
            continue
        if not isinstance(b[key], list):
            err(w, "field '%s' must be a list of addresses or prefixes" % key, [w + "." + key])
            continue
        for i, a in enumerate(b[key]):
            if not _valid_address_or_prefix(a):
                err(w, "field '%s': %s is not an IPv4 or IPv6 address or prefix"
                    % (key, '"%s"' % a if isinstance(a, str) else "an entry"), ["%s.%s[%d]" % (w, key, i)])
    _get_uint(b, "watchdog_ms", w, 60000, err)
    if "on_client_loss" in b and b["on_client_loss"] not in ("stop", "zero", "hold"):
        err(w, "field 'on_client_loss' must be \"stop\", \"zero\" or \"hold\"", [w + ".on_client_loss"])
    loc = _block(b, "status_location", w, "I", STATUS_BYTES, err)
    if loc:
        uses.append((loc, "bridge status_location", w + ".status_location", STATUS_BYTES))
    loc = _block(b, "control_location", w, "Q", CONTROL_BYTES, err)
    if loc:
        uses.append((loc, "bridge control_location", w + ".control_location", CONTROL_BYTES))
    lists = b.get("live_lists")
    if "live_lists" in b and not isinstance(lists, list):
        err(w, "field 'live_lists' must be a list", [w + ".live_lists"])
    by_name = {n["name"]: n for n in nets if n["name"]}
    for i, entry in enumerate(lists if isinstance(lists, list) else []):
        lw = "%s.live_lists[%d]" % (w, i)
        if not isinstance(entry, dict):
            err(lw, "must be an object", [lw])
            continue
        ok = True
        name = entry.get("network")
        if "network" not in entry:
            err(lw, "missing required field 'network'", [lw + ".network"])
            ok = False
        elif not isinstance(name, str) or not name:
            err(lw, "field 'network' must be a non-empty string", [lw + ".network"])
            ok = False
        elif name not in by_name:
            err(lw, "network \"%s\" is not in the config" % name, [lw + ".network"])
            ok = False
        elif by_name[name]["role"] != "master":
            err(lw, "network \"%s\" is not a CANopen master network; a live list lists a master's nodes" % name,
                [lw + ".network"])
            ok = False
        if "location" not in entry:
            err(lw, "missing required field 'location'", [lw + ".location"])
            ok = False
        else:
            loc = _block(entry, "location", lw, "I", LIVE_LIST_BYTES, err)
            if loc is None:
                ok = False
        if ok:
            uses.append((loc, "bridge live list of " + name, lw + ".location", LIVE_LIST_BYTES))
    sdo = b.get("sdo_bridge_location")
    if "sdo_bridge_location" in b:
        sw = w + ".sdo_bridge_location"
        if not isinstance(sdo, dict):
            err(w, "field 'sdo_bridge_location' must be an object with 'request' and 'response'", [sw])
        else:
            for key in ("request", "response"):
                if key not in sdo:
                    err(sw, "missing required field '%s'" % key, [sw + "." + key])
            rq = _block(sdo, "request", sw, "Q", SDO_BYTES, err)
            rs = _block(sdo, "response", sw, "I", SDO_BYTES, err)
            if rq and rs:
                uses.append((rq, "bridge sdo_bridge_location.request", sw + ".request", SDO_BYTES))
                uses.append((rs, "bridge sdo_bridge_location.response", sw + ".response", SDO_BYTES))
    if "sdo_bridge_write" in b and not isinstance(b["sdo_bridge_write"], bool):
        err(w, "field 'sdo_bridge_write' must be true or false", [w + ".sdo_bridge_write"])
    elif b.get("sdo_bridge_write") is True and "sdo_bridge_location" not in b:
        warn(w, "'sdo_bridge_write' has no effect without 'sdo_bridge_location'", [w + ".sdo_bridge_write"])
    for n in nets:
        m = n.get("master") if n["role"] == "master" else None
        if isinstance(m, dict) and m.get("sync_source") == "plc_cycle":
            err("networks[%d]: master" % n["index"],
                "\"sync_source\": \"plc_cycle\" needs a PLC cycle, which the Modbus bridge does not have: use "
                "\"sync_period_us\" (timer SYNC)", ["networks[%d].master.sync_source" % n["index"]])
    return uses


def report_byte_overlaps(uses, where, err):
    """`uses`: (loc, who, path, nbytes or None). The plugin's
    report_byte_overlaps."""
    def count(u):
        return u[3] if u[3] else SIZE_BYTES[u[0].size]

    for u in uses:
        if not u[3] and u[0].size in "WDL" and u[0].index % 2:
            err(where, "%s %s must start at an even byte: word locations are whole Modbus registers" % (u[1], u[0]),
                [u[2]])
    for i, a in enumerate(uses):
        for b in uses[i + 1:]:
            if a[0].area != b[0].area:
                continue
            if a[0].size == "X" and b[0].size == "X":
                if a[0].index == b[0].index and a[0].bit == b[0].bit:
                    err(where, "%s and %s both map to %s" % (a[1], b[1], a[0]), [a[2], b[2]])
                continue
            lo = max(a[0].index, b[0].index)
            hi = min(a[0].index + count(a), b[0].index + count(b))
            if lo >= hi:
                continue
            err(where, "%s (%s) and %s (%s) overlap in %s byte%s %s"
                % (a[1], a[0], b[1], b[0], "input" if a[0].area == "I" else "output",
                   "s" if hi - lo > 1 else "", " and ".join(str(k) for k in range(lo, hi))), [a[2], b[2]])
