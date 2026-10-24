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
        "connections", "safe_values")
OPENPLC_REMOVED = ("field 'openplc' was removed: OpenPLC is a connection on the Modbus bridge page; open the config in "
                   "the configurator and add it there")

# bridge.connections (modbus-connections): the configurator's clients. Each
# kind's own fields.
CONNECTION_KINDS = ("openplc", "plc", "nodered", "hmi")
CONNECTION_TITLES = {"openplc": "OpenPLC", "plc": "Other PLC", "nodered": "Node-RED",
                     "hmi": "HMI, SCADA or script"}
CONNECTION_COMMON = ("kind", "name", "address", "writes", "map_hash", "stale")
CONNECTION_FIELDS = {"openplc": ("poll_ms", "mailbox_poll_ms", "remote_device", "iec_base", "inputs_on_loss"),
                     "plc": ("format", "library", "bridge_host", "inputs_on_loss", "blocks"),
                     "nodered": ("period_ms", "bridge_host", "blocks"),
                     "hmi": ("format",)}
CONNECTION_FORMATS = {"plc": ("plcopen", "st"), "hmi": ("csv", "json", "st")}
# The canworks blocks choice (mailboxes-on-demand): the parts of
# bridge.mailboxes a connection's program uses.
# OpenPLC polls the mailbox blocks in groups of their own every
# mailbox_poll_ms, a multiple of poll_ms (the master runs on the greatest
# common divisor of the cycle times). 250 ms keeps four writes within the
# bridge's 1 s acknowledgement and keepalive limits.
MAILBOX_POLL_DEFAULT_MS = 50
MAILBOX_POLL_MAX_MS = 250
CONNECTION_BLOCKS = ("none", "sdo_send", "receive", "all")
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
    return {"poll_ms": None, "mailbox_poll_ms": None, "remote_device": None, "iec_base": None, "listen": listen,
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
    mpoll = _uint(o.get("mailbox_poll_ms"))
    if mpoll is None or mpoll < poll or mpoll % poll or mpoll > MAILBOX_POLL_MAX_MS:
        mpoll = default_mailbox_poll(poll)
    return {
        "poll_ms": poll,
        "mailbox_poll_ms": mpoll,
        "remote_device": o.get("remote_device") if isinstance(o.get("remote_device"), str) else "canworks",
        "iec_base": _uint(o.get("iec_base")),
        "listen": listen,
        "port": int(listen.rsplit(":", 1)[1]) if _valid_listen(listen) else 1502,
        "watchdog_ms": 1000 if wd is None else wd,
    }


def default_mailbox_poll(poll_ms):
    """The mailbox poll of an OpenPLC connection without one: the smallest
    multiple of the poll that is at least 50 ms (mailbox-poll)."""
    return max(poll_ms, -(-MAILBOX_POLL_DEFAULT_MS // poll_ms) * poll_ms)


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
            mp = _get_uint(c, "mailbox_poll_ms", cw, 65535, err)
            if mp is not None:
                p = v if v is not None and v >= 5 else OPENPLC_POLL_MS
                if mp < p or mp % p or mp > MAILBOX_POLL_MAX_MS:
                    err(cw, "field 'mailbox_poll_ms' must be a multiple of the poll (%d ms) and at most %d ms: %d"
                        % (p, MAILBOX_POLL_MAX_MS, mp), [cw + ".mailbox_poll_ms"])
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
    # the OpenPLC connection, else the first Other PLC that writes.
    # Every other writer gets the warning, whatever its kind.
    if link and writers:
        plc = [x for x in writers if x[2] == "openplc"] or [x for x in writers if x[2] == "plc"]
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
    if "on_client_loss" in b and b["on_client_loss"] not in ("stop", "zero", "hold", "preop", "safe"):
        err(w, "field 'on_client_loss' must be \"stop\", \"zero\", \"hold\", \"preop\" or \"safe\"",
            [w + ".on_client_loss"])
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
    # RX_OPEN and CYCLIC_SET go through a request mailbox (parse_mailboxes).
    full = dict(mailboxlayout.DEFAULTS, **counts)
    if not full["requests"] and (full["receive"] or full["cyclic_jobs"]):
        err(mw, "field 'requests' is 0, but opening a receiver or a cyclic job needs a request mailbox: set "
                "'requests' to at least 1, or turn 'receive' off and 'cyclic_jobs' to 0", [mw + ".requests"])
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


# ---- bridge.safe_values (modbus-bridge "Safe values"), as parse_safe_values
# in config.cpp ----

SAFE_UNUSED = "'safe_values' are used only with \"on_client_loss\": \"safe\"; they are not used now"
_SIGNED_TYPES = ("INTEGER8", "INTEGER16", "INTEGER32", "INTEGER64")


def _co_target(loc, type_name, who):
    from .iec import CO_TYPES
    if loc.size == "X" or type_name == "BOOLEAN":
        return {"loc": loc, "kind": "bit", "who": who}
    if type_name in ("REAL32", "REAL64"):
        return {"loc": loc, "kind": type_name.lower(), "who": who}
    bits = CO_TYPES[type_name][1] if type_name in CO_TYPES else SIZE_BYTES[loc.size] * 8
    return {"loc": loc, "kind": "int", "bits": bits, "signed": type_name in _SIGNED_TYPES, "who": who}


def _signal_target(loc, length, signed, who):
    return {"loc": loc, "kind": "bit" if loc.size == "X" else "int", "bits": length, "signed": signed, "who": who}


def _refused(loc, who, what, nbytes=None):
    return {"loc": loc, "kind": "refused", "who": who, "refuse": what, "nbytes": nbytes}


def safe_targets(cfg, nets, blocks=()):
    """Every output location of the config with what it takes as a safe
    value, in the bridge's words. `blocks` are the bridge's own uses."""
    out = []

    def loc_of(text):
        loc = parse_location(text) if isinstance(text, str) else None
        return loc if loc is not None and loc.area == "Q" else None

    def uint(v, default=0):
        # Numbers, or hex and decimal strings ("0x6200") as the config writes indices.
        if isinstance(v, str):
            try:
                v = int(v, 0)
            except ValueError:
                return default
        return v if isinstance(v, int) and not isinstance(v, bool) and v >= 0 else default

    for n in nets:
        p = "networks[%d]" % n["index"] + (" (%s)" % n["name"] if n["name"] else "") + " "
        raw = (n.get("json") or {}).get("raw")
        for k, m in enumerate((raw or {}).get("tx") or [] if isinstance(raw, dict) else []):
            if not isinstance(m, dict):
                continue
            at = "%s.raw.tx[%d]" % (n["path"], k)
            for key, what in (("trigger_location", "a raw message's trigger bit"),
                              ("enable_location", "a raw message's enable bit")):
                loc = loc_of(m.get(key))
                if loc:
                    out.append(_refused(loc, "%s.%s" % (at, key), what))
            loc = loc_of(m.get("data_location"))
            if loc:
                out.append(_signal_target(loc, SIZE_BYTES[loc.size] * 8, False, at + ".data_location"))
            for j, s in enumerate(m.get("signals") or []):
                loc = loc_of(s.get("iec_location")) if isinstance(s, dict) else None
                if loc:
                    out.append(_signal_target(loc, uint(s.get("length"), 1), s.get("signed") is True,
                                              "%s.signals[%d] (%s)" % (at, j, s.get("name"))))
        if n["role"] == "plain":
            continue
        if n["role"] == "j1939":
            j = n.get("j1939") or {}
            for t in j.get("tx") if isinstance(j.get("tx"), list) else []:
                for s in (t.get("signals") or []) if isinstance(t, dict) else []:
                    loc = loc_of(s.get("iec_location")) if isinstance(s, dict) else None
                    if loc:
                        out.append(_signal_target(loc, uint(s.get("length"), 1), s.get("signed") is True,
                                                  "%sPGN %s signal %s" % (p, uint(t.get("pgn")), s.get("name"))))
            d = j.get("diagnostics") if isinstance(j.get("diagnostics"), dict) else {}
            for c in d.get("dtcs") if isinstance(d.get("dtcs"), list) else []:
                loc = loc_of(c.get("active_location")) if isinstance(c, dict) else None
                if loc:
                    out.append({"loc": loc, "kind": "bit", "who": "%sdiagnostics SPN %s FMI %s active_location"
                                % (p, uint(c.get("spn")), uint(c.get("fmi")))})
            continue
        if n["role"] == "slave":
            for o in (n.get("slave") or {}).get("objects") or []:
                loc = loc_of(o.get("iec_location")) if isinstance(o, dict) else None
                if loc:
                    label = "object 0x%04X:%d" % (uint(o.get("index")), uint(o.get("subindex")))
                    if o.get("name"):
                        label += " (%s)" % o["name"]
                    out.append(_co_target(loc, o.get("type"), p + "slave " + label))
            continue
        for k, node in enumerate(n["nodes"]):
            if not isinstance(node, dict):
                continue
            label = p + "node %s" % uint(node.get("node_id")) + (" (%s)" % node["name"] if node.get("name") else "")
            loc = loc_of(node.get("nmt_command_location"))
            if loc:
                out.append(_refused(loc, label + " nmt_command_location", "an NMT command byte"))
            for v in node.get("sdo_variables") or []:
                if not isinstance(v, dict):
                    continue
                who = "%s SDO variable 0x%04X:%d" % (label, uint(v.get("index")), uint(v.get("subindex")))
                if v.get("name"):
                    who += " (%s)" % v["name"]
                loc = loc_of(v.get("iec_location"))
                if loc:
                    out.append(_refused(loc, who, "an SDO variable"))
                loc = loc_of(v.get("trigger_location"))
                if loc:
                    out.append(_refused(loc, who + " trigger_location", "an SDO variable's trigger bit"))
            for j, pdo in enumerate(node.get("rx_pdos") or []):
                if not isinstance(pdo, dict):
                    continue
                number = uint(pdo.get("number"), j + 1)
                for e in pdo.get("entries") or []:
                    loc = loc_of(e.get("iec_location")) if isinstance(e, dict) else None
                    if loc:
                        g = _co_target(loc, e.get("type"), "%s RPDO %d object 0x%04X:%d" % (
                            label, number, uint(e.get("index")), uint(e.get("subindex"))))
                        # Where the configurator finds the EDS limits.
                        g["ref"] = {"network": n["index"], "node": k, "index": uint(e.get("index")),
                                    "subindex": uint(e.get("subindex"))}
                        out.append(g)
    for loc, who, _, nbytes in blocks:
        if loc is not None and loc.area == "Q":
            out.append(_refused(loc, who, "the bridge's own block", nbytes))
    return out


def _int_range(g):
    nb = min(g.get("bits") or 64, 64)
    if g.get("signed"):
        return -(1 << (nb - 1)), (1 << (nb - 1)) - 1
    return 0, (1 << nb) - 1


def safe_table(cfg, nets):
    """The outputs that take a safe value, for the configurator's Safe
    values table: {location: {who, kind ("bit", "int", "real32",
    "real64"), range [low, high] of an integer, ref of an RPDO entry}}.
    A location bound twice (a signal and its message's data) keeps the
    first binding, as the check reads it."""
    out = {}
    for g in safe_targets(cfg, nets):
        if g["kind"] == "refused":
            continue
        loc = g["loc"]
        key = "%%Q%s%d%s" % (loc.size, loc.index, ".%d" % loc.bit if loc.size == "X" else "")
        if key in out:
            continue
        row = {"who": g["who"], "kind": "bit" if loc.size == "X" else g["kind"]}
        if row["kind"] == "int":
            row["range"] = list(_int_range(g))
        if g.get("ref"):
            row["ref"] = g["ref"]
        out[key] = row
    return out


def _target_bytes(g):
    if g["kind"] == "refused" and g.get("nbytes"):
        return g["nbytes"]
    return SIZE_BYTES[g["loc"].size]


def check_safe_values(cfg, nets, blocks, err, warn):
    """bridge.safe_values against the output bindings. Returns {location
    text: value} of the accepted ones (the map's safe value column)."""
    b = cfg.get("bridge") if isinstance(cfg.get("bridge"), dict) else {}
    if "safe_values" not in b:
        return {}
    sv = b["safe_values"]
    w = "bridge.safe_values"
    if not isinstance(sv, dict):
        err("bridge", "field 'safe_values' must be an object from %Q locations to values", ["bridge.safe_values"])
        return {}
    targets = safe_targets(cfg, nets, blocks)
    accepted = {}
    for key, value in sv.items():
        at = [w + "." + key]
        loc = parse_location(key)
        if loc is None:
            err(w, '"%s" is not a location' % key, at)
            continue
        if loc.area != "Q":
            err(w, "%s is an input location; safe values are for outputs (%%Q)" % key, at)
            continue
        exact = around = None
        for g in targets:
            gl = g["loc"]
            n = _target_bytes(g)
            same = gl.index == loc.index and gl.size == loc.size and (loc.size != "X" or gl.bit == loc.bit)
            if same and g["kind"] != "refused":
                exact = g
            elif gl.index <= loc.index < gl.index + n and gl.size != "X":
                around = g
            elif same:
                around = g
        if exact is None and around is not None and around["kind"] == "refused":
            err(w, "%s is %s (%s): safe values cannot be set on %s" % (key, around["refuse"], around["who"],
                                                                        around["refuse"]), at)
            continue
        if exact is None and not (loc.size == "X" and around is not None and around["kind"] != "bit"):
            err(w, "%s has no output bound to it; safe values go on RPDO entries and J1939 or raw transmit signals"
                % key, at)
            continue
        g = exact or around
        if loc.size == "X":
            if isinstance(value, bool) or value in (0, 1) and isinstance(value, (int, float)):
                accepted[key] = bool(value)
            else:
                err(w, "%s (%s) is a bit: its safe value must be true, false, 0 or 1" % (key, g["who"]), at)
            continue
        if g["kind"] == "bit":
            err(w, "%s (%s) is a bit: name it as a bit location" % (key, g["who"]), at)
            continue
        if g["kind"] in ("real32", "real64"):
            import math
            import struct
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                err(w, "%s (%s) is a REAL: its safe value must be a finite number" % (key, g["who"]), at)
                continue
            if g["kind"] == "real32":
                try:
                    struct.pack(">f", value)
                except OverflowError:
                    err(w, "%s (%s): %f does not fit a REAL32" % (key, g["who"], value), at)
                    continue
            accepted[key] = value
            continue
        lo, hi = _int_range(g)
        rng = "%d-%d" % (lo, hi)
        num = None
        if isinstance(value, bool):
            num = None
        elif isinstance(value, int):
            num = value if abs(value) <= 2 ** 53 else None
        elif isinstance(value, float):
            num = int(value) if value == int(value) and abs(value) <= 2 ** 53 else None
        elif isinstance(value, str) and (value.isdigit() or value[:1] == "-" and value[1:].isdigit()):
            num = int(value)
        if num is None:
            err(w, "%s (%s) is an integer: its safe value must be a whole number (a decimal string beyond 2^53), "
                   "in %s" % (key, g["who"], rng), at)
            continue
        fits = lo <= num <= hi
        if not fits:
            err(w, "%s (%s): %d is out of range %s" % (key, g["who"], num, rng), at)
            continue
        accepted[key] = num
    if accepted and b.get("on_client_loss") != "safe":
        warn("bridge", SAFE_UNUSED, ["bridge.safe_values"])
    return accepted
