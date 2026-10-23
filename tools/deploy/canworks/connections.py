"""The connections of a Modbus bridge config (modbus-connections): the
programs and tools that use the bridge's registers, kept in
`bridge.connections` so they travel with the project. canworks-bridge does
not read them; bridgecheck checks them.

Each kind has its hookup: OpenPLC gets its editor files from Save in an
editor project (openplcmodbus), the others a Download, the same file as the
command line writes. A Download stores the map hash in `map_hash`, so the
page can say when a client's files no longer fit the map.
"""

import base64
import copy
import io
import re
import zipfile

from . import bridgecheck, contract, modbusmap, nodered, openplcmodbus, plcopen, plcopen_targets

KINDS = bridgecheck.CONNECTION_KINDS
TITLES = bridgecheck.CONNECTION_TITLES
# One line each on what the kind gets (Add connection).
GETS = {
    "openplc": "OpenPLC Runtime on the bridge's device: Save keeps the editor's remote device and the canworks "
               "programs in sync.",
    "trust": "A truST runtime: the canworks variables, copy programs and function blocks as PLCopen XML, with its "
             "Modbus driver settings.",
    "plc": "Another PLC that imports PLCopen XML or ST: the canworks variables, copy programs and client channels.",
    "nodered": "A Node-RED flow that reads and writes every value by name.",
    "hmi": "An HMI, SCADA or script: the register map as CSV, JSON or an ST variable list.",
}
MIME = {"csv": "text/csv", "json": "application/json", "st": "text/plain", "zip": "application/zip"}


class DownloadError(ValueError):
    """The file cannot be made; `problems` says why, one text each."""

    def __init__(self, message, problems=None):
        super().__init__(message)
        self.problems = list(problems) if problems else [message]


def map_hash_text(cfg):
    """The config's map hash as 0x1234abcd, or None when the map cannot be made."""
    try:
        return "0x%08x" % modbusmap.map_hash(cfg)
    except (modbusmap.MapError, AttributeError, KeyError, TypeError, ValueError):
        return None


def new(kind, cfg, name=None, address=None):
    """A new connection of `kind` with a free name and the kind's defaults."""
    if kind not in KINDS:
        raise ValueError("kind must be one of: " + ", ".join(KINDS))
    taken = {c.get("name") for c in bridgecheck.connections(cfg)}
    base = name or TITLES[kind].split(",")[0]
    name, n = base, 2
    while name in taken:
        name, n = "%s %d" % (base, n), n + 1
    out = {"kind": kind, "name": name}
    if kind == "openplc":
        out.update({"address": bridgecheck.OPENPLC_ADDRESS, "writes": True})
    else:
        out.update({"address": address or "", "writes": kind in ("trust", "plc")})
    if kind in ("trust", "plc"):
        out["format"] = "plcopen"
    elif kind == "hmi":
        out["format"] = "csv"
    return out


def sync_writers(cfg):
    """`bridge.writers` set to the addresses of the connections that write,
    when the config has connections (modbus-connections "Writers follow the
    connections"). In place."""
    if bridgecheck.connections(cfg):
        cfg["bridge"]["writers"] = bridgecheck.connection_writers(cfg)


def openplc_settings(cfg, conn):
    """What adding an OpenPLC connection sets on the bridge, in place
    (modbus-connections "OpenPLC connection bridge settings"): the PLC link,
    low word first, 127.0.0.1:1502 unless another connection is on the
    network, the watchdog when unset, the
    control block, SDO registers and mailboxes when absent (every canworks
    block then works) and a live list per named CANopen master network.
    Placed by the pack that follows."""
    b = cfg["bridge"]
    b["plc_link"] = True
    b["word_order"] = "low_first"
    # Loopback only while no other connection needs the network.
    others = [c for c in bridgecheck.connections(cfg) if c is not conn and c.get("kind") != "openplc"]
    if "listen" not in b or not any(isinstance(c.get("address"), str) and c["address"]
                                    and not plcopen_targets.is_loopback(c["address"]) for c in others):
        b["listen"] = bridgecheck.OPENPLC_LISTEN
    poll = conn.get("poll_ms") if isinstance(conn.get("poll_ms"), int) else bridgecheck.OPENPLC_POLL_MS
    b.setdefault("watchdog_ms", bridgecheck.openplc_watchdog(poll))
    b.setdefault("control_location", "%QB0")
    if "sdo_bridge_location" not in b:
        b["sdo_bridge_location"] = {"request": "%QB0", "response": "%IB0"}
        b["sdo_bridge_write"] = True
    b.setdefault("mailboxes", {"input_location": "%IB0", "output_location": "%QB0"})
    lists = b.get("live_lists") if isinstance(b.get("live_lists"), list) else []
    have = {e.get("network") for e in lists if isinstance(e, dict)}
    for n in contract.networks(cfg):
        if n["name"] and n["role"] == "master" and n["protocol"] == "canopen" and n["name"] not in have:
            lists.append({"network": n["name"], "location": "%IB0"})
    if lists:
        b["live_lists"] = lists


def add(cfg, conn):
    """`cfg` (a copy) with `conn` added: an OpenPLC connection also sets
    the bridge for it; writers follow; the locations are repacked when the
    bridge settings changed. Raises ValueError or modbusmap.MapError."""
    if not modbusmap.is_bridge_config(cfg):
        raise ValueError("not a Modbus bridge config: it has no \"bridge\" object")
    if not isinstance(conn, dict) or conn.get("kind") not in KINDS:
        raise ValueError("a connection needs a kind: " + ", ".join(KINDS))
    out = copy.deepcopy(cfg)
    b = out["bridge"]
    if conn["kind"] == "openplc" and bridgecheck.is_openplc(out):
        raise ValueError("the config already has an OpenPLC connection")
    conn = dict(conn)
    if conn["kind"] == "openplc":
        # The removed `bridge.openplc` gives way to the connection, which keeps its settings.
        old = b.pop("openplc", None)
        for f in bridgecheck.CONNECTION_FIELDS["openplc"]:
            if isinstance(old, dict) and f in old:
                conn.setdefault(f, old[f])
    items = b.get("connections") if isinstance(b.get("connections"), list) else []
    b["connections"] = items + [conn]
    sync_writers(out)
    if conn["kind"] == "openplc":
        openplc_settings(out, conn)
        out = modbusmap.pack(out)
    return out


def file_stem(config_name, conn):
    """`<config name>-<connection name>`, each with only letters, digits, '_', '-' and '.'."""
    safe = lambda s: re.sub(r"[^A-Za-z0-9_.-]+", "-", str(s)).strip("-")
    return "%s-%s" % (safe(config_name or "") or "canworks", safe(conn.get("name") or conn.get("kind")) or conn["kind"])


def bridge_host(cfg, conn):
    """The bridge address the client uses: its `bridge_host`, else
    `listen`'s address when that is neither a wildcard nor loopback, else
    loopback for a client on the bridge's own device; None when unknown."""
    host = conn.get("bridge_host")
    if isinstance(host, str) and host.strip():
        return host.strip()
    listen = bridgecheck.listen_host((cfg.get("bridge") or {}).get("listen"))
    if listen and listen not in ("0.0.0.0", "::") and not plcopen_targets.is_loopback(listen):
        return listen
    address = conn.get("address")
    if isinstance(address, str) and plcopen_targets.is_loopback(address):
        return "127.0.0.1"
    return None


def download(cfg, conn, decls, config_name):
    """(file name, content type, bytes, notes) of the connection's Download,
    the same file as the command line's export. Raises DownloadError."""
    kind = conn.get("kind")
    stem = file_stem(config_name, conn)
    try:
        if kind == "nodered":
            period = conn.get("period_ms")
            host = conn.get("bridge_host") or None
            # Without Writes, or next to a PLC that owns the writes, the flow only reads.
            nodes, notes, _ = nodered.flow(cfg, stem, host=host, poll_ms=period if isinstance(period, int) else None,
                                           readonly=nodered.read_only(cfg) or conn.get("writes") is not True)
            return stem + ".json", MIME["json"], nodered.to_json(nodes).encode("utf-8"), notes
        fmt = conn.get("format") or ("plcopen" if kind in ("trust", "plc") else "csv")
        if kind in ("trust", "plc") and fmt == "plcopen":
            target = "trust" if kind == "trust" else "generic"
            files = plcopen_targets.files(cfg, decls, target, host=bridge_host(cfg, conn),
                                          library=conn.get("library") is not False, on_loss=_on_loss(conn))
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
                for n in sorted(files):
                    z.writestr(n, files[n].encode("utf-8"))
            return stem + ".zip", MIME["zip"], buf.getvalue(), []
        if fmt not in ("csv", "json", "st"):
            raise DownloadError("format %r is not one of csv, json and st" % fmt)
        rows = modbusmap.register_map(cfg)
        if fmt == "st" and modbusmap.has_plc_link(cfg):
            text = openplcmodbus.other_plc_st(cfg, decls, on_loss=_on_loss(conn))
        else:
            text = modbusmap.to_csv(rows) if fmt == "csv" else modbusmap.to_json(cfg, rows) if fmt == "json" \
                else modbusmap.to_st(cfg, rows)
        return "%s.%s" % (stem, fmt), MIME[fmt], text.encode("utf-8"), []
    except modbusmap.MapError as e:
        raise DownloadError(str(e), e.problems)
    except (nodered.FlowError, plcopen_targets.ExportError, plcopen.PlcopenError, openplcmodbus.OpenplcError) as e:
        raise DownloadError(str(e))


def _on_loss(conn):
    return conn["inputs_on_loss"] if conn.get("inputs_on_loss") in openplcmodbus.ON_LOSS else "hold"


def encode(data):
    return base64.b64encode(data).decode("ascii")


def state(cfg, conn, current=None):
    """"up_to_date", "out_of_date" or "not_downloaded" of a file
    connection; None for OpenPLC (its editor files have their own check)."""
    if conn.get("kind") == "openplc":
        return None
    if not conn.get("map_hash"):
        return "not_downloaded"
    if conn.get("stale") is True:
        return "out_of_date"
    current = current or map_hash_text(cfg)
    return "up_to_date" if current is None or conn["map_hash"] == current else "out_of_date"


# The blocks an OpenPLC program loses when the mailboxes are trimmed for truST.
OPENPLC_TRIM_LOSES = "CAN_RECEIVE, J1939_RECEIVE, CO_RECV_EMCY, CAN_SEND_CYCLIC, CAN_BUS_INFO and J1939_ECU_INFO"

# The PLCopen export each PLC connection's Download makes.
DOWNLOAD_TARGETS = {"trust": "trust", "plc": "generic"}


def download_problems(cfg):
    """Warnings for each reason a truST or Other PLC connection's Download
    would be refused (modbus-connections "Connections that cannot be
    downloaded"): the export's own texts, pointing at the field to change.
    One warning per text, for the first connection of the kind."""
    out = []
    b = cfg.get("bridge") if isinstance(cfg, dict) else None
    items = b.get("connections") if isinstance(b, dict) else None
    seen = set()
    for i, c in enumerate(items if isinstance(items, list) else []):
        if not isinstance(c, dict) or c.get("kind") not in DOWNLOAD_TARGETS or c["kind"] in seen:
            continue
        seen.add(c["kind"])
        path = "bridge.connections[%d]" % i
        label = c.get("name") or TITLES[c["kind"]]
        try:
            texts = plcopen_targets.check(cfg, DOWNLOAD_TARGETS[c["kind"]])
        except (AttributeError, KeyError, TypeError, ValueError, modbusmap.MapError):
            continue  # the config's own check says what is wrong
        for text in texts:
            if "trim the mailboxes" in text and any(isinstance(x, dict) and x.get("kind") == "openplc" for x in items):
                text += ("; the OpenPLC program shares these mailboxes, so its " + OPENPLC_TRIM_LOSES
                         + " blocks stop working too")
            paths = (["bridge.watchdog_ms", path] if '"watchdog_ms"' in text
                     else ["bridge.mailboxes", path] if "trim the mailboxes" in text else [path])
            out.append({"level": "warning", "paths": paths, "message": "%s: Download refused: %s" % (label, text)})
    return out


def problems(cfg):
    """Problems-pane warnings of the connections: one per out-of-date
    download, a PLCopen or ST connection with no bridge address, and each
    reason a PLC connection's Download would be refused."""
    out = download_problems(cfg)
    current = map_hash_text(cfg)
    b = cfg.get("bridge") if isinstance(cfg, dict) else None
    items = b.get("connections") if isinstance(b, dict) else None
    for i, c in enumerate(items if isinstance(items, list) else []):
        if not isinstance(c, dict) or c.get("kind") not in KINDS:
            continue
        path = "bridge.connections[%d]" % i
        label = c.get("name") or TITLES[c["kind"]]
        if state(cfg, c, current) == "out_of_date" and c.get("stale") is True and c["map_hash"] == current:
            out.append({"level": "warning", "paths": [path], "message": (
                "%s: its downloaded file was made with other settings: Download again" % label)})
        elif state(cfg, c, current) == "out_of_date":
            out.append({"level": "warning", "paths": [path], "message": (
                "%s: its downloaded file was made for another map (%s, now %s): Download again"
                % (label, c["map_hash"], current))})
        if c["kind"] in ("trust", "plc") and not bridge_host(cfg, c):
            out.append({"level": "warning", "paths": [path + ".bridge_host"], "message": (
                "%s: the PLC needs the bridge's address: give it in the connection's settings" % label)})
    return out
