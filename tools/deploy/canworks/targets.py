"""Project targets (canopen-config-contract "Config target", "Settings the
target does not use"): which system runs a config, and one table of the
settings each target uses.

A config's target is OpenPLC through Modbus when it has a top-level `bridge`
object with an `openplc` object, the Modbus bridge when it has a `bridge`
without one, CODESYS when it has a top-level `codesys` object, else the
OpenPLC plugin. OpenPLC through Modbus runs the networks in canworks-bridge
(so it uses what the bridge uses) and has an editor project. The
table below drives the configurator page (what it hides), the check (a
warning for a set value its target does not use) and the CODESYS plan's
`not_carried` list, so the three say the same thing in the same words."""

import re

OPENPLC, BRIDGE, CODESYS, OPENPLC_MODBUS = "openplc", "bridge", "codesys", "openplc_modbus"
TARGETS = (OPENPLC, BRIDGE, CODESYS, OPENPLC_MODBUS)
LABELS = {OPENPLC: "the OpenPLC plugin", BRIDGE: "the Modbus bridge", CODESYS: "CODESYS",
          OPENPLC_MODBUS: "OpenPLC through Modbus"}
TITLES = {OPENPLC: "OpenPLC plugin", BRIDGE: "Modbus bridge", CODESYS: "CODESYS", OPENPLC_MODBUS: "OpenPLC"}
# Targets whose networks canworks-bridge runs.
BRIDGES = (BRIDGE, OPENPLC_MODBUS)
BOTH_MESSAGE = "a config targets one system: remove 'bridge' (Modbus bridge) or 'codesys' (CODESYS)"

_ALL = frozenset(TARGETS)
_RUNTIME = frozenset((OPENPLC, BRIDGE, OPENPLC_MODBUS))

_PLUGIN_STATUS = ("plugin status location for the PLC program; CODESYS has its own diagnostics (CANopen Manager "
                  "status, CiA 405 blocks)")
_NODE_STATUS = "plugin status location for the PLC program; use the device's diagnostics or the CiA 405 blocks in CODESYS"
_IDENTITY = "identity check: tick the device's startup checks in CODESYS"
_MASTER_IDENTITY = "the master's own identity"
_NMT_BEHAVIOUR = "set the manager's NMT error behaviour in CODESYS"
_ADAPTER = "CODESYS sets up its CAN interface itself, from the network number and bit rate"
_BIT_CHANNEL = "CODESYS assigns the I/O addresses itself; the bit's name names its channel"
_BIT_BRIDGE = "the bridge serves an entry's bits in the entry's own location"
_NO_SCAN = "the bridge has no PLC scan; its output watchdog is bridge.watchdog_ms"
_LOSS = "bridge.on_client_loss says what the nodes get when OpenPLC stops"
_AXIS_MODBUS = "the CiA 402 axis needs the OpenPLC plugin"

# (key, targets that use it, {target that does not: why}, targets that
# refuse it). Keys are paths inside one network ("master.on_plc_stop",
# "nodes.tx_pdos.entries.iec_location": list indexes left out), "/key" for a
# top-level key, "key=value" for one value of a choice, and "ui:name" for
# parts of the page with no setting of their own. A refused value is an
# error elsewhere in the checks, so it is hidden on the page but gets no
# warning here.
ROWS = [
    ("/gateway", _RUNTIME, {CODESYS: "the gateway between networks stays with canworks"}, ()),
    ("/cia309", _RUNTIME, {CODESYS: "the CiA 309-3 gateway runs in the canworks plugin or bridge"}, ()),
    ("/diagnostics", _RUNTIME, {CODESYS: "the canworks diagnostics channel of the plugin or bridge"}, ()),
    ("raw", _RUNTIME, {CODESYS: "raw CAN messages stay with canworks"}, ()),
    ("codesys", frozenset((CODESYS,)), {OPENPLC: "CODESYS settings of the network",
                                        BRIDGE: "CODESYS settings of the network",
                                        OPENPLC_MODBUS: "CODESYS settings of the network"}, ()),
    ("adapter.type", _RUNTIME, {CODESYS: _ADAPTER}, ()),
    ("adapter.device", _RUNTIME, {CODESYS: _ADAPTER}, ()),
    ("adapter.serial_baudrate", _RUNTIME, {CODESYS: _ADAPTER}, ()),
    ("adapter.configure_link", _RUNTIME, {CODESYS: _ADAPTER}, ()),
    ("adapter.restart_ms", _RUNTIME, {CODESYS: _ADAPTER}, ()),
    ("adapter.simulate", _RUNTIME, {CODESYS: "simulated devices run in canworks, not in CODESYS"}, ()),
] + [("master." + k, _RUNTIME, {CODESYS: _PLUGIN_STATUS}, ()) for k in (
    "bus_state_location", "tx_error_count_location", "rx_error_count_location", "bus_off_count_location",
    "state_location")] + [
    ("master.on_plc_stop", frozenset((OPENPLC, BRIDGE)),
     {CODESYS: "CODESYS decides what the nodes get when the application stops", OPENPLC_MODBUS: _LOSS}, ()),
    ("master.scan_watchdog_ms", frozenset((OPENPLC,)), {BRIDGE: _NO_SCAN, CODESYS: "plugin scan watchdog",
                                                        OPENPLC_MODBUS: _NO_SCAN}, ()),
    ("master.sync_source=plc_cycle", frozenset((OPENPLC,)),
     {CODESYS: "SYNC from the PLC cycle: switch SYNC on in the manager and pick its bus cycle task in CODESYS"},
     (BRIDGE, OPENPLC_MODBUS)),
    ("master.sync_cycles", frozenset((OPENPLC,)),
     {CODESYS: "SYNC from the PLC cycle: pick the bus cycle task in CODESYS instead"}, (BRIDGE, OPENPLC_MODBUS)),
    ("master.eds_lint", _RUNTIME, {CODESYS: "dcfgen's EDS lint runs in the plugin; CODESYS reads the DCFs canworks "
                                            "checked"}, ()),
    ("master.diagnostics", _RUNTIME, {CODESYS: "the canworks diagnostics channel of the plugin or bridge"}, ()),
    ("master.cia309", _RUNTIME, {CODESYS: "the CiA 309-3 gateway runs in the canworks plugin or bridge"}, ()),
    ("master.heartbeat_multiplier", _RUNTIME, {CODESYS: "CODESYS sets the nodes' heartbeat consumer times itself"}, ()),
    ("master.error_behavior", _RUNTIME, {CODESYS: "master 0x1029: " + _NMT_BEHAVIOUR}, ()),
    ("master.reset_all_nodes", _RUNTIME, {CODESYS: _NMT_BEHAVIOUR}, ()),
    ("master.stop_all_nodes", _RUNTIME, {CODESYS: _NMT_BEHAVIOUR}, ()),
    ("master.boot_time_ms", _RUNTIME, {CODESYS: "master 0x1F89 boot time"}, ()),
    ("master.vendor_id", _RUNTIME, {CODESYS: _MASTER_IDENTITY}, ()),
    ("master.product_code", _RUNTIME, {CODESYS: _MASTER_IDENTITY}, ()),
    ("master.revision_number", _RUNTIME, {CODESYS: _MASTER_IDENTITY}, ()),
    ("master.serial_number", _RUNTIME, {CODESYS: _MASTER_IDENTITY}, ()),
    ("master.sync_counter_overflow", _RUNTIME, {CODESYS: "SYNC counter: set it on the manager's SYNC settings in "
                                                         "CODESYS"}, ()),
    ("master.emcy_inhibit_time_us", _RUNTIME, {CODESYS: "the master's own EMCY"}, ()),
] + [("nodes." + k, _RUNTIME, {CODESYS: _NODE_STATUS}, ()) for k in (
    "status_location", "state_location", "boot_error_location", "emcy_code_location", "error_register_location",
    "nmt_command_location")] + [
    ("nodes.sdo_variables", _RUNTIME, {CODESYS: "plugin SDO variables; use the CiA 405 SDO blocks in CODESYS"}, ()),
    ("nodes.heartbeat_timeout_ms", _RUNTIME, {CODESYS: "CODESYS supervises the node's heartbeat with its own "
                                                       "consumer time"}, ()),
    ("nodes.lss", _RUNTIME, {CODESYS: "LSS node ID assignment: use CODESYS's own LSS settings"}, ()),
    ("nodes.axis", frozenset((OPENPLC, BRIDGE)),
     {CODESYS: "canworks CiA 402 axis bridge: use SoftMotion or CiA 402 blocks in CODESYS",
      OPENPLC_MODBUS: _AXIS_MODBUS}, ()),
    ("nodes.config_check", _RUNTIME, {CODESYS: "configuration check: CODESYS downloads the configuration at every "
                                               "boot"}, ()),
    ("nodes.store_configuration", _RUNTIME, {CODESYS: "plugin store after the configuration check"}, ()),
    ("nodes.emcy_cob_id", _RUNTIME, {CODESYS: "where the plugin listens for EMCY"}, ()),
    ("nodes.revision_number", _RUNTIME, {CODESYS: _IDENTITY}, ()),
    ("nodes.serial_number", _RUNTIME, {CODESYS: _IDENTITY}, ()),
    ("nodes.retry_factor", _RUNTIME, {CODESYS: "node guarding retries"}, ()),
    ("nodes.simulate", _RUNTIME, {CODESYS: "simulated devices run in canworks, not in CODESYS"}, ()),
    ("nodes.tx_pdos.timeout_location", _RUNTIME, {CODESYS: "plugin receive timeout of a TPDO"}, ()),
    ("nodes.tx_pdos.timeout_ms", _RUNTIME, {CODESYS: "plugin receive timeout of a TPDO"}, ()),
    ("nodes.tx_pdos.on_timeout", _RUNTIME, {CODESYS: "plugin receive timeout of a TPDO"}, ()),
    ("nodes.tx_pdos.entries.iec_location", _RUNTIME,
     {CODESYS: "CODESYS assigns the I/O addresses itself; the entry's name names the channel"}, ()),
    ("nodes.rx_pdos.entries.iec_location", _RUNTIME,
     {CODESYS: "CODESYS assigns the I/O addresses itself; the entry's name names the channel"}, ()),
    ("nodes.tx_pdos.entries.bits.iec_location", frozenset((OPENPLC,)),
     {CODESYS: _BIT_CHANNEL, BRIDGE: _BIT_BRIDGE, OPENPLC_MODBUS: _BIT_BRIDGE}, ()),
    ("nodes.rx_pdos.entries.bits.iec_location", frozenset((OPENPLC,)),
     {CODESYS: _BIT_CHANNEL, BRIDGE: _BIT_BRIDGE, OPENPLC_MODBUS: _BIT_BRIDGE}, ()),
    ("j1939.scan_watchdog_ms", frozenset((OPENPLC,)), {BRIDGE: _NO_SCAN, OPENPLC_MODBUS: _NO_SCAN}, ()),
    ("raw.scan_watchdog_ms", frozenset((OPENPLC,)), {BRIDGE: _NO_SCAN, OPENPLC_MODBUS: _NO_SCAN}, ()),
    # Network kinds: CODESYS gets CANopen master networks only.
    ("role=slave", _RUNTIME, {CODESYS: "a slave network stays with canworks: give the other master the slave's EDS "
                                       "(canworks-deploy slave-eds)"}, ()),
    ("protocol=j1939", _RUNTIME, {CODESYS: "a J1939 network stays with canworks"}, ()),
    ("protocol=none", _RUNTIME, {CODESYS: "a plain CAN network stays with canworks"}, ()),
    # Parts of the page.
    ("ui:editor_project", frozenset((OPENPLC, OPENPLC_MODBUS)), {BRIDGE: "", CODESYS: ""}, ()),
    ("ui:runtime", _RUNTIME, {CODESYS: ""}, ()),
    ("ui:simulation", _RUNTIME, {CODESYS: ""}, ()),
    ("ui:declarations", frozenset((OPENPLC,)), {BRIDGE: "", CODESYS: "", OPENPLC_MODBUS: ""}, ()),
    ("ui:bridge", frozenset((BRIDGE, OPENPLC_MODBUS)), {OPENPLC: "", CODESYS: ""}, ()),
    ("ui:openplc_modbus", frozenset((OPENPLC_MODBUS,)), {OPENPLC: "", BRIDGE: "", CODESYS: ""}, ()),
    ("ui:codesys", frozenset((CODESYS,)), {OPENPLC: "", BRIDGE: "", OPENPLC_MODBUS: ""}, ()),
]

_BY_KEY = {r[0]: r for r in ROWS}

# The page's name for each setting of the table, for the list of settings
# the target does not use (canopen-configurator "Settings the target does
# not use on the page").
_LOCATION_LABELS = {"bus_state_location": "Bus state", "tx_error_count_location": "TX errors",
                    "rx_error_count_location": "RX errors", "bus_off_count_location": "Bus-off count",
                    "state_location": "Master state"}
_NODE_LABELS = {"status_location": "Status bit", "state_location": "State byte", "boot_error_location": "Boot error byte",
                "emcy_code_location": "EMCY code", "error_register_location": "Error register",
                "nmt_command_location": "NMT command"}
FIELD_LABELS = dict(
    [("/gateway", "Gateway"), ("/cia309", "CiA 309-3 gateway"), ("/diagnostics", "Online access"),
     ("raw", "CAN messages"), ("codesys", "CODESYS settings"), ("adapter.type", "Type"),
     ("adapter.device", "Interface"), ("adapter.serial_baudrate", "Serial speed"),
     ("adapter.configure_link", "Sets up the link"), ("adapter.restart_ms", "Bus-off restart (ms)"),
     ("adapter.simulate", "Simulated network"), ("master.on_plc_stop", "When the PLC stops"),
     ("master.scan_watchdog_ms", "Scan watchdog (ms)"), ("master.sync_source=plc_cycle", "SYNC from the PLC cycle"),
     ("master.sync_cycles", "SYNC every n PLC cycles"), ("master.eds_lint", "EDS lint"),
     ("master.diagnostics", "Online access"), ("master.cia309", "CiA 309-3 gateway"),
     ("master.heartbeat_multiplier", "Heartbeat multiplier"), ("master.error_behavior", "Error behaviour (0x1029)"),
     ("master.reset_all_nodes", "Reset all nodes on error"), ("master.stop_all_nodes", "Stop all nodes on error"),
     ("master.boot_time_ms", "Boot time (ms)"), ("master.vendor_id", "Master vendor ID"),
     ("master.product_code", "Master product code"), ("master.revision_number", "Master revision number"),
     ("master.serial_number", "Master serial number"), ("master.sync_counter_overflow", "SYNC counter overflow"),
     ("master.emcy_inhibit_time_us", "Master EMCY inhibit time"),
     ("nodes.sdo_variables", "SDO variables"), ("nodes.heartbeat_timeout_ms", "Heartbeat timeout (ms)"),
     ("nodes.lss", "LSS"), ("nodes.axis", "CiA 402 axis"), ("nodes.config_check", "Skip download when unchanged"),
     ("nodes.store_configuration", "Save configuration on the device"), ("nodes.emcy_cob_id", "EMCY COB-ID"),
     ("nodes.revision_number", "Revision number"), ("nodes.serial_number", "Serial number"),
     ("nodes.retry_factor", "Guarding retries"), ("nodes.simulate", "Simulated device"),
     ("nodes.tx_pdos.timeout_location", "Timeout bit"), ("nodes.tx_pdos.timeout_ms", "Receive timeout (ms)"),
     ("nodes.tx_pdos.on_timeout", "On timeout"),
     ("nodes.tx_pdos.entries.iec_location", "PLC location"), ("nodes.rx_pdos.entries.iec_location", "PLC location"),
     ("nodes.tx_pdos.entries.bits.iec_location", "Bit location"), ("nodes.rx_pdos.entries.bits.iec_location", "Bit location"),
     ("j1939.scan_watchdog_ms", "Scan watchdog (ms)"), ("raw.scan_watchdog_ms", "Scan watchdog (ms)"),
     ("role=slave", "Slave network"), ("protocol=j1939", "J1939 network"), ("protocol=none", "Plain CAN network")]
    + [("master." + k, v) for k, v in _LOCATION_LABELS.items()]
    + [("nodes." + k, v) for k, v in _NODE_LABELS.items()])


def target(cfg):
    """The config's target: "openplc_modbus", "bridge", "codesys" or
    "openplc". A config with both markers counts as the bridge; the check
    reports it."""
    if not isinstance(cfg, dict):
        return OPENPLC
    if isinstance(cfg.get("bridge"), dict):
        return OPENPLC_MODBUS if isinstance(cfg["bridge"].get("openplc"), dict) else BRIDGE
    if isinstance(cfg.get("codesys"), dict):
        return CODESYS
    return OPENPLC


def uses(key, tgt):
    """Whether target `tgt` uses the table's `key` (a key not in the table is
    used by every target)."""
    row = _BY_KEY.get(key)
    return row is None or tgt in row[1]


def reason(key, tgt):
    row = _BY_KEY.get(key)
    return row[2].get(tgt, "") if row else ""


def table():
    """The table for the configurator page: [{key, targets, refused, reasons, label}]."""
    return [{"key": k, "targets": sorted(t), "refused": list(ref), "reasons": dict(why), "label": FIELD_LABELS.get(k, "")}
            for k, t, why, ref in ROWS]


def _set(value):
    return value not in (None, False, [], {}, "")


def _walk(obj, parts, at):
    """(path, value) for every value at `parts` below `obj`, list indexes
    filled in."""
    if not parts:
        yield at, obj
        return
    if not isinstance(obj, dict) or parts[0] not in obj:
        return
    value, path = obj[parts[0]], (at + "." if at else "") + parts[0]
    if isinstance(value, list) and len(parts) > 1:
        for i, item in enumerate(value):
            yield from _walk(item, parts[1:], "%s[%d]" % (path, i))
    else:
        yield from _walk(value, parts[1:], path)


def _network_entries(cfg):
    """(prefix, network JSON) per network: "" for a version 1 file."""
    nets = cfg.get("networks")
    if isinstance(nets, list):
        return [("networks[%d]" % i, n) for i, n in enumerate(nets) if isinstance(n, dict)]
    return [("", cfg)]


def unused(cfg, tgt=None):
    """[(path, key, reason)] for every set value of `cfg` that its target (or
    `tgt`) does not use, in config order. Refused values are left out: the
    checks report them as errors."""
    tgt = tgt or target(cfg)
    out = []
    if not isinstance(cfg, dict):
        return out
    for key, users, why, refused in ROWS:
        if tgt in users or tgt in refused or key.startswith("ui:"):
            continue
        if key.startswith("/"):
            if _set(cfg.get(key[1:])):
                out.append((key[1:], key, why.get(tgt, "")))
            continue
        for prefix, net in _network_entries(cfg):
            if "=" in key:
                field, value = key.split("=", 1)
                parts = field.split(".")
                for path, v in _walk(net, parts, prefix):
                    if v == value:
                        out.append((path, key, why.get(tgt, "")))
                continue
            for path, v in _walk(net, key.split("."), prefix):
                if _set(v):
                    out.append((path, key, why.get(tgt, "")))
    order = {p: i for i, p in enumerate(_paths_in_order(cfg))}
    out.sort(key=lambda u: order.get(u[0], len(order)))
    return out


def _paths_in_order(cfg, at=""):
    yield at
    if isinstance(cfg, dict):
        for k, v in cfg.items():
            yield from _paths_in_order(v, (at + "." if at else "") + k)
    elif isinstance(cfg, list):
        for i, v in enumerate(cfg):
            yield from _paths_in_order(v, "%s[%d]" % (at, i))


NETWORK_KINDS = ("role=slave", "protocol=j1939", "protocol=none")


def removable(key):
    """Whether an unused value can simply be removed: not a network kind
    (removing `role` would turn a slave network into a master)."""
    return key not in NETWORK_KINDS


def message(path, key, why, tgt):
    """The check's warning for one unused value."""
    field = path.rsplit(".", 1)[-1]
    if "=" in key:
        field = "%s: %s" % (key.split("=")[0].rsplit(".", 1)[-1], key.split("=", 1)[1])
    if key in NETWORK_KINDS:
        return "not used by %s: %s" % (LABELS[tgt], why)
    return "'%s' is not used by %s%s" % (field, LABELS[tgt], ": " + why if why else "")


def remove(cfg, paths):
    """Removes the values at `paths` (as unused() gives them) from `cfg` in
    place. A `key=value` path removes the key."""
    # Only object keys go, never list items, so the order does not matter.
    for path in set(paths):
        parts = [int(x) if x.isdigit() else x for x in re.split(r"[\.\[\]]+", path) if x]
        obj = cfg
        for p in parts[:-1]:
            try:
                obj = obj[p]
            except (KeyError, IndexError, TypeError):
                obj = None
                break
        if isinstance(obj, dict):
            obj.pop(parts[-1], None)
