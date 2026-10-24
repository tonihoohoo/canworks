"""The checks of a bridge config (modbus-bridge): the top-level `bridge`
object and the byte rules of its locations, in the words of
plugin/src/can/config.cpp (parse_bridge, report_byte_overlaps).

A bridge config is byte-addressed: %IWn covers input bytes n and n+1, and
two locations clash when their bytes overlap, except bits of one byte with
different bit numbers. Word and larger locations start at an even byte.
"""

import ipaddress

from . import mailboxlayout
from .iec import parse_location

# Bytes per location size letter.
SIZE_BYTES = {"X": 1, "B": 1, "W": 2, "D": 4, "L": 8}
# The bridge's own blocks.
STATUS_BYTES = 8
CONTROL_BYTES = 6
LIVE_LIST_BYTES = 16
SDO_BYTES = 14
# bridge.plc_link: the map hash at input bytes 0-3, the status block at input
# byte 4, the PLC link header at output bytes 0-5.
OPENPLC_HASH_BYTES = 4
OPENPLC_STATUS_BYTE = 4
OPENPLC_HEADER_BYTES = 6
# What adding an OpenPLC connection sets (modbus-connections "OpenPLC
# connection bridge settings").
OPENPLC_LISTEN = "127.0.0.1:1502"
OPENPLC_ADDRESS = "127.0.0.1"
OPENPLC_POLL_MS = 10
# The largest byte address of a bridge config (+1), per direction.
IMAGE_BYTES = 8192

KEYS = ("listen", "unit_id", "word_order", "max_clients", "max_clients_per_address", "writers", "readers", "watchdog_ms", "on_client_loss",
        "status_location", "control_location", "live_lists", "sdo_bridge_location", "sdo_bridge_write", "plc_link", "mailboxes",
        "connections")
OPENPLC_REMOVED = ("field 'openplc' was removed: OpenPLC is a connection on the Modbus bridge page; open the config in "
                   "the configurator and add it there")

# bridge.connections (modbus-connections): the configurator's clients. Each
# kind's own fields.
CONNECTION_KINDS = ("openplc", "trust", "plc", "nodered", "hmi")
CONNECTION_TITLES = {"openplc": "OpenPLC", "trust": "truST", "plc": "Other PLC", "nodered": "Node-RED",
                     "hmi": "HMI, SCADA or script"}
CONNECTION_COMMON = ("kind", "name", "address", "writes", "map_hash", "stale")
CONNECTION_FIELDS = {"openplc": ("poll_ms", "remote_device", "iec_base", "inputs_on_loss"),
                     "trust": ("format", "library", "bridge_host", "inputs_on_loss", "blocks"),
                     "plc": ("format", "library", "bridge_host", "inputs_on_loss", "blocks"),
                     "nodered": ("period_ms", "bridge_host", "blocks"),
                     "hmi": ("format",)}
CONNECTION_FORMATS = {"trust": ("plcopen",), "plc": ("plcopen", "st"), "hmi": ("csv", "json", "st")}
# The canworks blocks choice (mailboxes-on-demand): the parts of
# bridge.mailboxes a connection's program uses. truST moves one request each
# way, which holds one request mailbox and nothing more.
CONNECTION_BLOCKS = ("none", "sdo_send", "receive", "all")
CONNECTION_BLOCKS_TRUST = ("none", "sdo_send")
BLOCKS_TITLES = {"none": "None", "sdo_send": "SDO and send", "receive": "SDO, send and receive", "all": "All"}

# Every address may write: the explicit form `writers` needs for that.
ALL_WRITERS = ["0.0.0.0/0", "::/0"]
WRITERS_MISSING = ("missing required field 'writers': list the addresses that may write, or [\"0.0.0.0/0\", "
                   "\"::/0\"] to let every address write")


def is_bridge_config(cfg):
    return isinstance(cfg, dict) and "bridge" in cfg


def connections(cfg):
    """The well-formed entries of `bridge.connections` (dicts with a kind)."""
    b = cfg.get("bridge") if isinstance(cfg, dict) else None
    items = b.get("connections") if isinstance(b, dict) else None
    return [c for c in items if isinstance(c, dict) and isinstance(c.get("kind"), str)] if isinstance(items, list) else []


def openplc_connection(cfg):
    """The config's OpenPLC connection, or None."""
    return next((c for c in connections(cfg) if c["kind"] == "openplc"), None)


def is_openplc(cfg):
    """OpenPLC through its Modbus master: a bridge config with an OpenPLC connection."""
    return openplc_connection(cfg) is not None


def has_plc_link(cfg):
    """The PLC link header and map hash: `bridge.plc_link` true."""
    b = cfg.get("bridge") if isinstance(cfg, dict) else None
    return isinstance(b, dict) and b.get("plc_link") is True


def link_settings(cfg):
    """The effective settings the generated link code needs: openplc_settings
    with an OpenPLC connection, else the bridge's own (watchdog default 1000 ms)."""
    if is_openplc(cfg):
        return openplc_settings(cfg)
    b = cfg.get("bridge") or {}
    listen = b.get("listen") if isinstance(b.get("listen"), str) else ""
    wd = _uint(b.get("watchdog_ms"))
    return {"poll_ms": None, "remote_device": None, "iec_base": None, "listen": listen,
            "port": int(listen.rsplit(":", 1)[1]) if _valid_listen(listen) else 502,
            "watchdog_ms": 1000 if wd is None else wd}


def openplc_settings(cfg):
    """The OpenPLC connection's settings and the bridge's (defaults applied)."""
    b = cfg.get("bridge") or {}
    o = openplc_connection(cfg) or {}
    poll = _uint(o.get("poll_ms"))
    poll = OPENPLC_POLL_MS if poll is None else max(5, min(poll, 1000))
    listen = b.get("listen") if isinstance(b.get("listen"), str) else OPENPLC_LISTEN
    wd = _uint(b.get("watchdog_ms"))
    return {
        "poll_ms": poll,
        "remote_device": o.get("remote_device") if isinstance(o.get("remote_device"), str) else "canworks",
        "iec_base": _uint(o.get("iec_base")),
        "listen": listen,
        "port": int(listen.rsplit(":", 1)[1]) if _valid_listen(listen) else 1502,
        "watchdog_ms": 1000 if wd is None else wd,
    }


def openplc_watchdog(poll_ms):
    """The watchdog an OpenPLC connection sets when there is none: 5 polls, at least 50 ms."""
    return max(50, 5 * poll_ms)


def connection_writers(cfg):
    """The sorted addresses of the connections that write (bridge.writers
    follows them)."""
    return sorted({c["address"] for c in connections(cfg)
                   if c.get("writes") is True and isinstance(c.get("address"), str) and c["address"]},
                  key=_address_key)


def _address_key(text):
    try:
        a = ipaddress.ip_address(text)
        return (a.version, int(a), text)
    except ValueError:
        return (9, 0, text)


def _is_loopback(host):
    try:
        return ipaddress.ip_address(host.strip("[]")).is_loopback
    except ValueError:
        return host == "localhost"


def listen_host(listen):
    """The address part of a listen text, or None."""
    if not isinstance(listen, str) or not _valid_listen(listen):
        return None
    return listen[1:listen.find("]:")] if listen.startswith("[") else listen.rsplit(":", 1)[0]


def listen_all(listen):
    """`listen` on every address with the same port (Listen on all addresses)."""
    port = listen.rsplit(":", 1)[1] if isinstance(listen, str) and _valid_listen(listen) else "502"
    return "0.0.0.0:" + port


def _connections(b, w, err, warn, link):
    """Checks bridge.connections (modbus-connections "Connections in the config")."""
    if "connections" not in b:
        return
    items = b["connections"]
    if not isinstance(items, list):
        err(w, "field 'connections' must be a list", [w + ".connections"])
        return
    names = {}
    openplc = 0
    owner = None  # the OpenPLC connection's label
    users = []  # (index, label) of the connections with canworks blocks
    writers = []  # (index, label, kind) of the connections that write
    listen = listen_host(b.get("listen"))
    for i, c in enumerate(items):
        cw = "%s.connections[%d]" % (w, i)
        if not isinstance(c, dict):
            err(cw, "must be an object", [cw])
            continue
        kind = c.get("kind")
        if kind not in CONNECTION_KINDS:
            err(cw, "field 'kind' must be one of %s" % ", ".join('"%s"' % k for k in CONNECTION_KINDS), [cw + ".kind"])
            continue
        for key in c:
            if key not in CONNECTION_COMMON + CONNECTION_FIELDS[kind]:
                err(cw, "unknown field '%s' for a %s connection" % (key, CONNECTION_TITLES[kind]), [cw + "." + key])
        name = c.get("name")
        label = name if isinstance(name, str) and name else CONNECTION_TITLES[kind]
        if not isinstance(name, str) or not 1 <= len(name) <= 64:
            err(cw, "field 'name' must be 1-64 characters", [cw + ".name"])
        elif name in names:
            err(cw, "connection name \"%s\" is used twice (also connections[%d])" % (name, names[name]), [cw + ".name"])
        else:
            names[name] = i
        address = c.get("address")
        if "address" not in c:
            err(cw, "missing required field 'address' (the client's IP address)", [cw + ".address"])
        elif address == "":
            err(cw, "Give the address of %s: the IP address it connects from" % label, [cw + ".address"])
        elif not isinstance(address, str) or not _valid_address(address):
            err(cw, "field 'address' must be an IPv4 or IPv6 address, not %s" % _show(address), [cw + ".address"])
        elif listen and _is_loopback(listen) and not _is_loopback(address):
            err(cw, "%s connects from %s, but the bridge listens on %s only: listen on all addresses"
                % (label, address, b.get("listen")), [w + ".listen", cw + ".address"])
        if "writes" in c and not isinstance(c["writes"], bool):
            err(cw, "field 'writes' must be true or false", [cw + ".writes"])
        elif c.get("writes") is True:
            writers.append((i, label, kind))
        if "map_hash" in c and not (isinstance(c["map_hash"], str) and len(c["map_hash"]) == 10
                                    and c["map_hash"].startswith("0x")
                                    and all(ch in "0123456789abcdef" for ch in c["map_hash"][2:])):
            err(cw, "field 'map_hash' must look like 0x1234abcd", [cw + ".map_hash"])
        if kind in CONNECTION_FORMATS and "format" in c and c["format"] not in CONNECTION_FORMATS[kind]:
            err(cw, "field 'format' of a %s connection must be %s" % (
                CONNECTION_TITLES[kind], " or ".join('"%s"' % f for f in CONNECTION_FORMATS[kind])), [cw + ".format"])
        if "inputs_on_loss" in c and c["inputs_on_loss"] not in ("hold", "zero"):
            err(cw, "field 'inputs_on_loss' must be \"hold\" or \"zero\"", [cw + ".inputs_on_loss"])
        if "stale" in c and not isinstance(c["stale"], bool):
            err(cw, "field 'stale' must be true or false", [cw + ".stale"])
        if "library" in c and not isinstance(c["library"], bool):
            err(cw, "field 'library' must be true or false", [cw + ".library"])
        if "bridge_host" in c and not isinstance(c["bridge_host"], str):
            err(cw, "field 'bridge_host' must be a string", [cw + ".bridge_host"])
        v = _get_uint(c, "period_ms", cw, 60000, err)
        if v is not None and v < 10:
            err(cw, "field 'period_ms' must be 10-60000", [cw + ".period_ms"])
        if "blocks" in c:
            if c["blocks"] not in CONNECTION_BLOCKS:
                err(cw, "field 'blocks' must be %s" % ", ".join('"%s"' % k for k in CONNECTION_BLOCKS), [cw + ".blocks"])
            elif kind == "trust" and c["blocks"] not in CONNECTION_BLOCKS_TRUST:
                err(cw, "%s: truST moves one request each way, so only canworks blocks None or SDO and send fit"
                    % label, [cw + ".blocks"])
            elif kind == "nodered" and link and c["blocks"] != "none":
                err(cw, "%s: with the PLC link the flow is read-only, so its block nodes cannot use the mailboxes: "
                        "set canworks blocks to None" % label, [cw + ".blocks"])
            elif c["blocks"] != "none":
                users.append((i, label))
        if kind == "openplc":
            openplc += 1
            owner = label
            if openplc > 1:
                err(cw, "a config has one OpenPLC connection", [cw + ".kind"])
            v = _get_uint(c, "poll_ms", cw, 1000, err)
            if v is not None and v < 5:
                err(cw, "field 'poll_ms' must be 5-1000", [cw + ".poll_ms"])
            if "remote_device" in c:
                rd = c["remote_device"]
                if (not isinstance(rd, str) or not 1 <= len(rd) <= 64
                        or not all(ch.isascii() and (ch.isalnum() or ch in "_-") for ch in rd)):
                    err(cw, "field 'remote_device' must be 1-64 letters, digits, '_' or '-' (the editor's file name)",
                        [cw + ".remote_device"])
            _get_uint(c, "iec_base", cw, 65535, err)
            if isinstance(address, str) and _valid_address(address) and not _is_loopback(address):
                err(cw, "an OpenPLC connection's address is 127.0.0.1: OpenPLC runs on the bridge's device",
                    [cw + ".address"])
            if not link:
                err(w, "an OpenPLC connection needs 'plc_link' true: OpenPLC's program checks the map hash",
                    [w + ".plc_link"])
            if b.get("word_order") == "high_first":
                err(w, "field 'word_order' must be \"low_first\" with an OpenPLC connection: OpenPLC's Modbus master "
                       "reads 32- and 64-bit values lowest word first", [w + ".word_order"])
    # With the PLC link one PLC writes the whole output image and the header:
    # the OpenPLC connection, else the first truST or Other PLC that writes.
    # Every other writer gets the warning, whatever its kind.
    if link and writers:
        plc = [x for x in writers if x[2] == "openplc"] or [x for x in writers if x[2] in ("trust", "plc")]
        first = plc[0] if plc else None
        for i, label, kind in writers:
            if first is not None and i == first[0]:
                continue
            why = " (%s does)" % first[1] if first else ""
            warn("%s.connections[%d]" % (w, i), "%s writes, but with the PLC link only the PLC writes outputs and "
                 "mailboxes%s: untick Writes" % (label, why), ["%s.connections[%d].writes" % (w, i)])
    # One program owns the mailboxes (mailboxes-on-demand "One program owns
    # the mailboxes"): the request words, tickets and receivers assume one client.
    if owner is not None:
        for i, label in users:
            err("%s.connections[%d]" % (w, i), "%s has canworks blocks, but the OpenPLC program owns the mailboxes: "
                "only one program can use them, so set canworks blocks to None" % label,
                ["%s.connections[%d].blocks" % (w, i)])
    elif len(users) > 1:
        for i, label in users[1:]:
            err("%s.connections[%d]" % (w, i), "%s and %s both have canworks blocks: only one program can use the "
                "mailboxes, so set one of them to None" % (users[0][1], label), ["%s.connections[%d].blocks" % (w, i)])
    if items and isinstance(b.get("writers"), list):
        cfg = {"bridge": b}
        if sorted(b["writers"], key=_address_key) != connection_writers(cfg):
            warn(w, "'writers' (%s) differ from the connections that write (%s): use the connections' addresses"
                 % (", ".join(map(str, b["writers"])) or "none", ", ".join(connection_writers(cfg)) or "none"),
                 [w + ".writers"])


def _valid_address(text):
    try:
        ipaddress.ip_address(text)
        return True
    except ValueError:
        return False


def _show(value):
    return '"%s"' % value if isinstance(value, str) else "a %s" % type(value).__name__


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
    if loc.index + SIZE_BYTES[loc.size] > IMAGE_BYTES:
        err(where, "%s %s lies outside the runtime I/O image (index must be below %d)" % (key, loc, IMAGE_BYTES),
            [where + "." + key])
        return None
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
    if "openplc" in b:
        err(w, OPENPLC_REMOVED, [w + ".openplc"])
    link = False
    if "plc_link" in b:
        if not isinstance(b["plc_link"], bool):
            err(w, "field 'plc_link' must be true or false", [w + ".plc_link"])
        else:
            link = b["plc_link"]
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
    v = _get_uint(b, "max_clients_per_address", w, 64, err)
    if v is not None and v < 1:
        err(w, "field 'max_clients_per_address' must be 1-64", [w + ".max_clients_per_address"])
    if "writers" not in b:
        err(w, WRITERS_MISSING, [w + ".writers"])
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
    if "on_client_loss" in b and b["on_client_loss"] not in ("stop", "zero", "hold", "preop"):
        err(w, "field 'on_client_loss' must be \"stop\", \"zero\", \"hold\" or \"preop\"", [w + ".on_client_loss"])
    loc = _block(b, "status_location", w, "I", STATUS_BYTES, err)
    if link:
        if loc and loc.index != OPENPLC_STATUS_BYTE:
            err(w, "field 'status_location' must be %IB4 with 'plc_link' (input bytes 0-3 hold the map hash), or "
                   "left out", [w + ".status_location"])
        loc = parse_location("%IB4")
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
    uses.extend(_mailboxes(b, w, len(nets), err))
    _connections(b, w, err, warn, link)
    if link:
        where = w + ".plc_link"
        uses.append((parse_location("%IB0"), "bridge map hash (PLC link)", where, OPENPLC_HASH_BYTES))
        uses.append((parse_location("%QB0"), "the PLC link header (output bytes 0-5)", where, OPENPLC_HEADER_BYTES))
    return uses


def _mailboxes(b, w, networks, err):
    """bridge.mailboxes: its blocks as uses, in the order of the bridge's
    own list (parse_mailboxes and bridge_uses in config.cpp)."""
    if "mailboxes" not in b:
        return []
    o = b["mailboxes"]
    mw = w + ".mailboxes"
    if not isinstance(o, dict):
        err(w, "field 'mailboxes' must be an object", [mw])
        return []
    counts = {}
    for key, maximum in (("requests", mailboxlayout.MAX_REQUESTS), ("cyclic_jobs", mailboxlayout.MAX_CYCLIC_JOBS)):
        v = _get_uint(o, key, mw, maximum, err)
        if v is not None:
            counts[key] = v
    v = _get_uint(o, "receive_blocks", mw, 2 ** 32 - 1, err)
    if v is not None:
        if 1 <= v <= mailboxlayout.MAX_RECEIVE_BLOCKS:
            counts["receive_blocks"] = v
        else:
            err(mw, "field 'receive_blocks' must be 1 or 2: %d" % v, [mw + ".receive_blocks"])
    for key in ("receive", "network_info"):
        if key not in o:
            continue
        if isinstance(o[key], bool):
            counts[key] = o[key]
        else:
            err(mw, "field '%s' must be true or false" % key, [mw + "." + key])
    for key in ("input_location", "output_location"):
        if key not in o:
            err(mw, "missing required field '%s' (where the mailbox area starts; Pack for Modbus in the configurator "
                    "sets it)" % key, [mw + "." + key])
    ins, outs = mailboxlayout.area_bytes(counts, networks)
    base = {"I": _block(o, "input_location", mw, "I", ins, err),
            "Q": _block(o, "output_location", mw, "Q", max(1, outs), err)}
    for area, key in (("I", "input_location"), ("Q", "output_location")):
        if base[area] and base[area].index % 2:
            err(mw, "%s: a mailbox area starts at an even byte (a register)" % base[area], [mw + "." + key])
    if not (base["I"] and base["Q"]):
        return []
    uses = []
    for area, offset, nbytes, _, who in mailboxlayout.blocks(counts, networks):
        key = "input_location" if area == "I" else "output_location"
        loc = parse_location("%%%sB%d" % (area, base[area].index + offset))
        uses.append((loc, who, mw + "." + key, nbytes))
    return uses


def report_byte_overlaps(uses, where, err):
    """`uses`: (loc, who, path, nbytes or None). The bridge's
    report_byte_overlaps."""
    def count(u):
        return u[3] if u[3] else SIZE_BYTES[u[0].size]

    # A location past the image is its own error (contract._check_image).
    uses = [u for u in uses if u[0].index + count(u) <= IMAGE_BYTES]
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
