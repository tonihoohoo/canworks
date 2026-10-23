"""Node-RED flow of a bridge config (modbus-bridge-map "Node-RED flow") and
the Node-RED package it uses (nodered-blocks).

The flow is one tab with a "canworks bridge" config node of the
`node-red-canworks` package, which carries the config's layout (register map
rows, the bridge's blocks and mailboxes, networks), and a "canworks in" and
"canworks out" node. The package itself (nodered_package/) talks to
canworks-bridge over one Modbus TCP connection; `package_tgz` writes it as the
`.tgz` Node-RED installs, and `layout_js` its generated lib/layout.js.
"""

import gzip
import hashlib
import io
import json
import os
import tarfile

from . import __version__, contract, mailboxlayout, modbusmap

DEFAULT_POLL_MS = 10
MIN_POLL_MS = 10
DEFAULT_SDO_TIMEOUT_MS = 1000
PACKAGE = "node-red-canworks"
PACKAGE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "nodered_package")

REAL_TYPES = ("REAL32", "REAL64", "REAL", "LREAL")
SIGNED_PREFIXES = ("INTEGER", "SINT", "INT", "DINT", "LINT")


class FlowError(ValueError):
    """The config is not a bridge config, or the options are out of range."""


def _kind(t):
    if t in REAL_TYPES:
        return "real"
    if t.startswith(SIGNED_PREFIXES):
        return "signed"
    return "unsigned"


def _number(v):
    if v in ("", None):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _spec_row(r):
    """The fields of a map row the JavaScript side needs."""
    out = {"n": r["name"], "b": r["byte"], "k": _kind(r["type"])}
    if r["table"] in ("discrete input", "coil"):
        out["bit"] = r["address"] - r["byte"] * 8
        out["k"] = "bit"
        out["size"] = 1
        out["regs"] = [r["byte"] // 2, r["byte"] // 2]
    else:
        size = 1 if r.get("byte_in_register") else r["count"] * 2
        out["size"] = size
        out["regs"] = [r["address"], r["address"] + r["count"] - 1]
        if size >= 4:
            out["lo"] = r["word_order"] == "low_first"
    scale, offset = _number(r["scale"]), _number(r["offset"])
    if scale is not None and scale != 1:
        out["s"] = scale
    if offset:
        out["o"] = offset
    if r["unit"]:
        out["u"] = r["unit"]
    return out


def _parse_host(text):
    """(host, port) of "host", "host:port" or "[v6]:port"; port None when
    not given."""
    text = text.strip()
    if text.startswith("["):
        host, _, rest = text[1:].partition("]")
        port = rest[1:] if rest.startswith(":") else ""
    elif text.count(":") == 1:
        host, port = text.split(":")
    else:
        host, port = text, ""
    if port:
        try:
            port = int(port)
        except ValueError:
            raise FlowError("bad port in %r" % text)
        if not 0 < port < 65536:
            raise FlowError("bad port in %r" % text)
    return host, port or None


def options(cfg, host=None, poll_ms=None, readonly=False):
    """(host, port, poll_ms, notes) for the flow: the bridge's listen address
    (127.0.0.1 for an all-addresses listen) unless `host` says otherwise, and
    the poll period kept between MIN_POLL_MS and a third of watchdog_ms."""
    b = cfg["bridge"]
    lhost, lport = _parse_host(b.get("listen", "0.0.0.0:502"))
    notes = []
    if lhost in ("0.0.0.0", "::", ""):
        lhost = "127.0.0.1"
    port = lport or 502
    if host:
        h, p = _parse_host(host)
        lhost, port = h or lhost, p or port
    watchdog = b.get("watchdog_ms", 1000)
    poll = DEFAULT_POLL_MS if poll_ms is None else poll_ms
    if not isinstance(poll, int) or isinstance(poll, bool):
        raise FlowError("the poll period must be a whole number of milliseconds")
    top = watchdog // 3 if watchdog else None
    want = poll
    if poll < MIN_POLL_MS:
        poll = MIN_POLL_MS
    if top is not None and poll > top:
        poll = max(MIN_POLL_MS, top)
    if poll != want:
        notes.append("poll period %d ms instead of %d ms (kept between %d ms and a third of the bridge's "
                      "watchdog_ms)" % (poll, want, MIN_POLL_MS))
    writers = b.get("writers", [])
    if readonly:
        pass
    elif not writers:
        notes.append("the bridge's 'writers' is empty, so it refuses the flow's writes; add Node-RED's address")
    elif lhost in ("127.0.0.1", "::1", "localhost") and not any(
            w.startswith("127.") or w in ("::1", "::1/128", "0.0.0.0/0", "::/0") for w in writers):
        notes.append("the flow connects over loopback but the bridge's 'writers' (%s) has no loopback address; "
                     "add \"127.0.0.1\" so its writes are accepted" % ", ".join(writers))
    return lhost, port, poll, notes


def read_only(cfg):
    """True when a PLC program owns the bridge's writes (the PLC link), so
    the flow only reads."""
    return modbusmap.has_plc_link(cfg)


def layout(cfg, rows, readonly=None):
    """The layout the "canworks bridge" config node carries: everything the
    package needs to know about this config's registers."""
    b = cfg["bridge"]
    nets = contract.networks(cfg)
    by_name = {r["name"]: r for r in rows}
    data = [r for r in rows if r["type"] != "BLOCK"]
    # Status, state and timeout inputs read 0 while the bridge is lost
    # (modbus-connections "PLC inputs while the bridge is lost").
    status = {it.name for it in modbusmap.collect(cfg) if it.kind == "status" and it.direction == "input"}
    in_regs = out_regs = 0
    for r in rows:
        end = (r["byte"] // 2 + 1) if r["table"] in ("discrete input", "coil") else r["address"] + r["count"]
        if r["direction"] == "input":
            in_regs = max(in_regs, end)
        else:
            out_regs = max(out_regs, end)
    channels = modbusmap.suggest_channels(rows)

    def block(name):
        r = by_name.get(name)
        return r["byte"] if r else None

    live = []
    for r in rows:
        if r["name"].startswith("bridge.live_list."):
            net = next((n for n in nets if n["name"] == r["network"]), None)
            ids = sorted(n["node_id"] for n in (net["nodes"] if net else []) if isinstance(n, dict)
                         and isinstance(n.get("node_id"), int))
            live.append({"net": r["network"], "b": r["byte"], "nodes": ids})
    sdo_timeout = max([n["master"].get("sdo_timeout_ms", DEFAULT_SDO_TIMEOUT_MS)
                       for n in nets if n["role"] == "master"] or [DEFAULT_SDO_TIMEOUT_MS])
    networks = []
    for n in nets:
        kinds = ["can"]
        if n["role"] == "master":
            kinds.append("canopen")
        if n["protocol"] == "j1939":
            kinds.append("j1939")
        networks.append({"index": n["index"], "name": n["name"] or str(n["index"]), "kinds": kinds})
    mailboxes = None
    if isinstance(b.get("mailboxes"), dict):
        s = mailboxlayout.settings(b["mailboxes"], len(nets))
        mailboxes = {
            "requests": [{"req": block("bridge.mailbox.%d.request" % m), "resp": block("bridge.mailbox.%d.response" % m)}
                         for m in range(s["requests"])],
            "receive": ({"block": block("bridge.mailbox.receive.0"), "blocks": s["receive_blocks"],
                         "ack": block("bridge.mailbox.receive_ack")}
                        if s["receive"] else None),
            "info": [{"net": n["index"], "name": n["name"] or str(n["index"]), "j1939": n["protocol"] == "j1939",
                      "b": block("bridge.mailbox.network_info.%d" % i)}
                     for i, n in enumerate(nets[:s["info_networks"]])],
            "cyclic": ({"table": block("bridge.mailbox.cyclic_jobs"), "keepalive": block("bridge.mailbox.keepalives"),
                        "jobs": s["cyclic_jobs"]} if s["cyclic_jobs"] else None),
        }
    ro = read_only(cfg) if readonly is None else readonly
    return {
        "version": __version__,
        "unit": b.get("unit_id", 1),
        "mapHash": modbusmap.map_hash(cfg),
        "readOnly": ro,
        "inBytes": in_regs * 2,
        "outBytes": out_regs * 2,
        "inputs": [dict(_spec_row(r), **({"z": True} if r["name"] in status else {}))
                   for r in data if r["direction"] == "input"],
        "outputs": [] if ro else [_spec_row(r) for r in data if r["direction"] == "output"],
        "read": [[s, c] for f, s, c, d in channels if d == "input"],
        "write": [] if ro else [[s, c] for f, s, c, d in channels if d == "output"],
        "status": block("bridge.status"),
        "control": block("bridge.control"),
        "sdoReq": block("bridge.sdo_bridge.request"),
        "sdoResp": block("bridge.sdo_bridge.response"),
        "live": live,
        "networks": networks,
        "sdoTimeoutMs": sdo_timeout,
        "watchdogMs": b.get("watchdog_ms", 1000),
        "mailboxes": mailboxes,
    }


# -- the flow ----------------------------------------------------------------

def flow(cfg, name="canworks", host=None, poll_ms=None, readonly=None):
    """(nodes, notes, layout): the Node-RED flow of a bridge config as a list
    of node objects (one tab, the "canworks bridge" config node, canworks in
    and out), and notes for the user. Raises FlowError for a config that is
    not a bridge config or whose map breaks the byte rules."""
    if not modbusmap.is_bridge_config(cfg):
        raise FlowError("not a bridge config: a Node-RED flow needs a top-level \"bridge\" object "
                        "(docs/node-red.md)")
    try:
        rows = modbusmap.register_map(cfg)
    except modbusmap.MapError as e:
        raise FlowError(str(e))
    ro = read_only(cfg) if readonly is None else readonly
    h, port, poll, notes = options(cfg, host, poll_ms, ro)
    lay = layout(cfg, rows, ro)
    if not ro and lay["control"] is not None and lay["status"] is None:
        notes.append("the config has a control block but no status block (status_location), so the nmt node "
                     "cannot see the bridge's answer and ends with ERROR_ID 22; add a status block")

    def nid(key):
        return hashlib.sha1(("canworks-node-red:%s:%s" % (name, key)).encode("utf-8")).hexdigest()[:16]

    tab, bridge = nid("tab"), nid("bridge")
    why = (" It only reads: the bridge's writes belong to the PLC program." if read_only(cfg) else
           " It only reads." if ro else "")
    nodes = [{
        "id": tab, "type": "tab", "label": "canworks %s" % name, "disabled": False,
        "info": ("canworks Modbus bridge at %s:%d, generated by canworks %s.%s\n\n"
                 "Needs the node-red-canworks package of the same version (Manage palette > Install > upload, "
                 "or npm install node-red-canworks-%s.tgz). Use canworks nodes on any tab with the bridge node "
                 "\"canworks %s\". Export again after changing the config." % (h, port, __version__, why, __version__, name)),
    }, {
        "id": bridge, "type": "canworks-bridge", "name": "canworks %s" % name, "host": h, "port": port,
        "unit": lay["unit"], "period": poll, "readOnly": ro, "layout": json.dumps(lay, sort_keys=True),
    }, {
        "id": nid("comment"), "type": "comment", "z": tab, "name": "canworks %s: wire canworks nodes here or on any tab" % name,
        "info": "Values: canworks in (msg.topic = name, msg.payload = value)%s. Blocks: canworks nmt, sdo, emcy, "
                "can send, can cyclic, can receive, j1939 send, request, receive, dm and find ecu. See docs/node-red.md."
                % ("" if ro else "; canworks out sets an output with {topic, payload}"),
        "x": 250, "y": 40, "wires": [],
    }, {
        "id": nid("in"), "type": "canworks-in", "z": tab, "name": "", "bridge": bridge, "filter": "",
        "x": 130, "y": 100, "wires": [[]],
    }]
    if not ro:
        nodes.append({"id": nid("out"), "type": "canworks-out", "z": tab, "name": "", "bridge": bridge,
                      "x": 130, "y": 160, "wires": []})
    return nodes, notes, lay


def block_parts(lay):
    """What the flow's block nodes can use, in words."""
    if lay["readOnly"]:
        return "none (read-only flow)"
    parts = []
    if lay["control"] is not None and lay["status"] is not None:
        parts.append("NMT (control and status blocks)")
    if lay["sdoReq"] is not None:
        parts.append("short SDO (SDO registers)")
    mb = lay["mailboxes"]
    if mb:
        n = len(mb["requests"])
        if n:
            parts.append("%d request mailbox%s (long SDO, CAN, J1939)" % (n, "" if n == 1 else "es"))
        if mb["receive"]:
            parts.append("receive mailbox (CAN, J1939, EMCY receivers)")
        if mb["cyclic"]:
            parts.append("%d cyclic jobs" % mb["cyclic"]["jobs"])
    return ", ".join(parts) if parts else "none: the config has no control block, SDO registers or mailboxes"


def export(cfg, path, name=None, host=None, poll_ms=None, readonly=None):
    """Writes the flow to `path`; returns (number of inputs, number of outputs, notes, layout)."""
    stem = os.path.splitext(os.path.basename(path))[0]
    for suffix in ("_node-red", "-node-red"):
        if stem.endswith(suffix) and len(stem) > len(suffix):
            stem = stem[:-len(suffix)]
    stem = name or stem or "canworks"
    nodes, notes, lay = flow(cfg, stem, host, poll_ms, readonly)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(to_json(nodes))
    return len(lay["inputs"]), len(lay["outputs"]), notes, lay


def to_json(nodes):
    return json.dumps(nodes, indent=2) + "\n"


# -- the package -----------------------------------------------------------------

# The ERROR_IDs of the block families (docs/plc-library.md, raw-can.md,
# j1939.md), for node status and msg.canworks.text. "all" holds the IDs
# every family shares.
ERROR_TEXTS = {
    "all": {"8": "cancelled: the link stopped, the network restarted or the bridge restarted",
            "20": "the bridge is not reachable",
            "22": "the config has no part of the bridge this node needs"},
    "sdo": {"1": "the node aborted the transfer", "2": "no answer within the timeout",
            "3": "the node is not available", "4": "the network is not running or not a CANopen master network",
            "5": "too many SDO transfers or NMT commands wait", "6": "an input is out of range",
            "7": "the reply does not fit", "21": "SDO writes are not allowed by the config (sdo_bridge_write)"},
    "can": {"1": "the network is not running", "2": "no such network", "3": "an input is invalid",
            "4": "the identifier belongs to the network's protocol", "5": "no free receiver, cyclic job or queue space",
            "6": "not confirmed on the bus within the timeout", "7": "the bus is off or the interface is down",
            "9": "the network is listen-only"},
    "j1939": {"1": "the network is not running", "2": "no such network", "3": "an input is invalid",
              "4": "the network sends that PGN itself", "5": "another DM2 read or clear for that address is pending",
              "6": "no answer, or not sent, within the timeout", "7": "the bus is off or the interface is down",
              "9": "no free job or receiver", "10": "not a J1939 network", "11": "the network holds no address",
              "12": "the destination refused (NACK)", "13": "no DM1 from that source yet",
              "14": "the transfer was aborted"},
}
CONTROL_RESULTS = ["ok", "unknown command", "bad network", "bad node", "not a CANopen master network",
                   "refused (bus down or too many commands wait)", "not run: the bridge restarted"]


def layout_js():
    """The text of the package's lib/layout.js."""
    lay = mailboxlayout.client_layout()
    lay["errorTexts"] = ERROR_TEXTS
    lay["controlResults"] = CONTROL_RESULTS
    return ("// layout.js - GENERATED by `python -m canworks.nodered layout` from the PC tools'\n"
            "// mailbox layout (canworks/mailboxlayout.py) and block ERROR_IDs. Do not edit.\n"
            "\"use strict\";\n\nmodule.exports = %s;\n" % json.dumps(lay, indent=2, sort_keys=True))


def package_files():
    """[(path in the package, bytes)] of the package, sorted, with
    package.json's version set to the tools' version."""
    out = []
    for root, dirs, files in os.walk(PACKAGE_DIR):
        dirs[:] = sorted(d for d in dirs if d not in ("test", "node_modules", "__pycache__"))
        for f in sorted(files):
            full = os.path.join(root, f)
            rel = os.path.relpath(full, PACKAGE_DIR).replace(os.sep, "/")
            with open(full, "rb") as fh:
                data = fh.read()
            if rel == "package.json":
                pkg = json.loads(data.decode("utf-8"))
                pkg["version"] = __version__
                data = (json.dumps(pkg, indent=2) + "\n").encode("utf-8")
            out.append((rel, data))
    return sorted(out)


def package_tgz():
    """The package as the .tgz `npm pack` would write (entries under
    package/), the same bytes for the same tools version."""
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w", format=tarfile.USTAR_FORMAT) as tar:
        for rel, data in package_files():
            info = tarfile.TarInfo("package/" + rel)
            info.size = len(data)
            info.mtime = 499162500  # what npm pack writes: 1985-10-26
            info.mode = 0o644
            info.uname = info.gname = ""
            tar.addfile(info, io.BytesIO(data))
    out = io.BytesIO()
    with gzip.GzipFile(fileobj=out, mode="wb", mtime=0, filename="") as gz:
        gz.write(raw.getvalue())
    return out.getvalue()


def package_name():
    return "%s-%s.tgz" % (PACKAGE, __version__)


def export_package(path):
    """Writes the package .tgz to `path` (a directory: its usual file name in it)."""
    if os.path.isdir(path):
        path = os.path.join(path, package_name())
    with open(path, "wb") as f:
        f.write(package_tgz())
    return path


def main(argv=None):
    import sys
    args = sys.argv[1:] if argv is None else argv
    if args == ["layout"]:
        target = os.path.join(PACKAGE_DIR, "lib", "layout.js")
        with open(target, "w", encoding="utf-8", newline="\n") as f:
            f.write(layout_js())
        print(target)
        return 0
    print("usage: python -m canworks.nodered layout")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
