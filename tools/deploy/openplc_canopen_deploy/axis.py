"""CiA 402 drives used as PLCopen axes (a node's `axis` object).

The motion blocks are the stock editor's built-in PLCopen SoftMotion library
(AXIS_REF_SM3, MC_Power, MC_MoveVelocity, ...). Its generic CiA 402 bridge
SM_Drive_GenericDS402 copies the drive's PDO values into the axis once per
scan. This module finds the standard objects in a node's PDO mapping, checks
them against the bridge's pins, and writes the declarations and the bridge
call a program needs. The plugin does nothing different for an axis.
"""

from .configurator.declare import comment_text, identifier

AXIS_TYPE = "AXIS_REF_SM3"
BRIDGE_TYPE = "SM_Drive_GenericDS402"
BODY_HEAD = "(* CiA 402 axes from canopen/canopen.json: keep these lines first *)"

# index: (bridge pin, PDO list, CANopen type, IEC type, name)
OBJECTS = {
    0x6040: ("wControlWord", "rx_pdos", "UNSIGNED16", "UINT", "controlword"),
    0x6060: ("siModes", "rx_pdos", "INTEGER8", "SINT", "modes of operation"),
    0x607A: ("diTargetPosition", "rx_pdos", "INTEGER32", "DINT", "target position"),
    0x6081: ("udiProfileVelocity", "rx_pdos", "UNSIGNED32", "UDINT", "profile velocity"),
    0x60FF: ("diTargetVelocity", "rx_pdos", "INTEGER32", "DINT", "target velocity"),
    0x6071: ("iTargetTorque", "rx_pdos", "INTEGER16", "INT", "target torque"),
    0x6041: ("wStatusWord", "tx_pdos", "UNSIGNED16", "UINT", "statusword"),
    0x6061: ("siModesDisplay", "tx_pdos", "INTEGER8", "SINT", "modes of operation display"),
    0x6064: ("diActualPosition", "tx_pdos", "INTEGER32", "DINT", "position actual value"),
    0x606C: ("diActualVelocity", "tx_pdos", "INTEGER32", "DINT", "velocity actual value"),
    0x6077: ("iActualTorque", "tx_pdos", "INTEGER16", "INT", "torque actual value"),
}
# The bridge's pin order: inputs, then outputs.
PIN_ORDER = [0x6041, 0x6061, 0x6064, 0x606C, 0x6077, 0x6040, 0x6060, 0x607A, 0x6081, 0x60FF, 0x6071]
TARGETS = (0x607A, 0x6081, 0x60FF)
SET_POINTS = (0x607A, 0x60FF, 0x6071)  # the cyclic modes' set-points (CSP, CSV, CST)
SCALING = (("scale_numerator", "iRatioTechUnitsNum", "DINT", 1),
           ("scale_denominator", "dwRatioTechUnitsDenom", "DWORD", 1),
           ("scale_factor", "fScalefactor", "LREAL", 1.0))
PROFILE = 402


def _int(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    try:
        return int(str(value), 0)
    except ValueError:
        return None


def is_axis(node):
    return isinstance(node, dict) and isinstance(node.get("axis"), dict)


def axis_name(node):
    """The axis is named after the node, as the configurator names its variables."""
    return identifier(node.get("name") or "node%s" % node.get("node_id"))


def bridge_name(node):
    return axis_name(node) + "_bridge"


def label(node):
    return "node %s" % node.get("node_id") + (" (%s)" % node["name"] if node.get("name") else "")


def mapped(node, i):
    """{index: [(PDO list, pdo index, entry index, entry)]} of the standard
    objects mapped at sub-index 0 in the node's PDOs, in either direction."""
    out = {}
    for key in ("tx_pdos", "rx_pdos"):
        for j, p in enumerate(node.get(key) or []):
            for k, e in enumerate(p.get("entries") or []):
                index, sub = _int(e.get("index")), _int(e.get("subindex", 0))
                if index in OBJECTS and sub == 0:
                    out.setdefault(index, []).append((key, j, k, e))
    return out


def check(cfg, err, warn):
    """The axis checks of a schema-valid config. err/warn(where, message, paths)."""
    for i, n in enumerate(cfg.get("nodes", [])):
        if not is_axis(n):
            continue
        w = "nodes[%d]" % i
        who = label(n)
        if not n.get("status_location"):
            err(w, "%s: a CiA 402 axis needs 'status_location': the axis goes into error stop when the drive is lost"
                % who, [w + ".status_location", w + ".axis"])
        found = mapped(n, i)
        for index in PIN_ORDER:
            pin, key, co_type, iec, name = OBJECTS[index]
            kind = "RPDO" if key == "rx_pdos" else "TPDO"
            hits = found.get(index, [])
            for pkey, j, k, e in hits:
                at = "%s.%s[%d].entries[%d]" % (w, pkey, j, k)
                if pkey != key:
                    err(w, "%s: CiA 402 axis: 0x%04X (%s) must be mapped in %s, not %s"
                        % (who, index, name, "a TPDO" if kind == "TPDO" else "an RPDO",
                           "a TPDO" if pkey == "tx_pdos" else "an RPDO"), [at])
                elif e.get("type") != co_type:
                    err(w, "%s: CiA 402 axis: 0x%04X (%s) needs type %s (%s), not %s"
                        % (who, index, name, co_type, iec, e.get("type")), [at + ".type"])
            if len(hits) > 1:
                err(w, "%s: CiA 402 axis: 0x%04X (%s) is mapped %d times; map it once"
                    % (who, index, name, len(hits)), ["%s.%s[%d].entries[%d]" % (w, h[0], h[1], h[2]) for h in hits])
            if index in (0x6040, 0x6041) and not any(h[0] == key and h[3].get("iec_location") for h in hits):
                err(w, "%s: a CiA 402 axis needs the %s 0x%04X in a%s %s with a location"
                    % (who, name, index, "n" if kind == "RPDO" else "", kind), [w + "." + key, w + ".axis"])
        if is_cyclic(n):
            _check_cyclic(cfg, n, w, who, found, err)
        if 0x6060 not in found:
            for index in TARGETS:
                if index in found:
                    warn(w, "%s: CiA 402 axis: 0x%04X (%s) is mapped without 0x6060 (modes of operation); the motion "
                            "blocks set the mode themselves, so the drive stays in the mode it starts in"
                         % (who, index, OBJECTS[index][4]), [w + ".axis"])
                    break


def is_cyclic(node):
    return is_axis(node) and node["axis"].get("cyclic") is True


def interpolation_code(period_us):
    """(value, exponent) for 0x60C2 sub 1 and sub 2: the largest exponent of
    -3 to -6 that gives the period exactly with a value of 1-255; None when
    there is none (plugin: interpolation_code)."""
    p = _int(period_us)
    if p is None or p <= 0:
        return None
    for exponent, unit in ((-3, 1000), (-4, 100), (-5, 10), (-6, 1)):
        if p % unit == 0 and 1 <= p // unit <= 255:
            return p // unit, exponent
    return None


def _check_cyclic(cfg, n, w, who, found, err):
    master = cfg.get("master") or {}
    if master.get("sync_source") != "plc_cycle":
        err(w, "%s: a cyclic CiA 402 axis needs SYNC from the PLC cycle (\"sync_source\": \"plc_cycle\"): with the "
               "master's timer, scan and SYNC drift and a set-point is applied twice or skipped" % who,
            [w + ".axis.cyclic", "master.sync_source"])
    elif (_int(master.get("sync_cycles", 1)) or 1) != 1:
        err(w, "%s: a cyclic CiA 402 axis needs one SYNC every PLC cycle ('sync_cycles' 1, not %s): the drive would "
               "not see every set-point" % (who, master.get("sync_cycles")), [w + ".axis.cyclic", "master.sync_cycles"])
    if not any(h[0] == "rx_pdos" for h in found.get(0x6060, [])):
        err(w, "%s: a cyclic CiA 402 axis needs 0x6060 (modes of operation) in an RPDO: the cyclic blocks select the "
               "mode" % who, [w + ".rx_pdos", w + ".axis.cyclic"])
    if not any(h[0] == "rx_pdos" for i in SET_POINTS for h in found.get(i, [])):
        err(w, "%s: a cyclic CiA 402 axis needs a set-point in an RPDO: 0x607A (CSP), 0x60FF (CSV) or 0x6071 (CST)"
            % who, [w + ".rx_pdos", w + ".axis.cyclic"])
    period = n["axis"].get("interpolation_period_us")
    if period is not None and interpolation_code(period) is None:
        err(w, "%s: 'interpolation_period_us' %s cannot be written to 0x60C2: it must be 1-255 times 1 ms, 100 us, "
               "10 us or 1 us" % (who, period), [w + ".axis.interpolation_period_us"])


def _transmission(pdo, eds, comm, node_id):
    if pdo.get("transmission") is not None:
        return _int(pdo["transmission"])
    o = eds.find(comm, 2)
    try:
        return o.value(node_id) if o is not None else None
    except Exception:
        return None


def cyclic_eds_check(cfg_node, node, eds):
    """The EDS-dependent checks of a cyclic axis: (errors, warnings), each a
    list of (message, path within the node). `node` is the contract's parsed
    node (integer numbers, PDO numbers)."""
    errors, warnings = [], []
    if not is_cyclic(cfg_node) or eds is None:
        return errors, warnings
    who = label(cfg_node)
    node_id = node["node_id"]
    for key, comm_base, watch in (("rx_pdos", 0x1400, (0x6040, 0x6060) + SET_POINTS),
                                  ("tx_pdos", 0x1800, (0x6064, 0x606C))):
        for j, pdo in enumerate(node.get(key, [])):
            hit = [e["index"] for e in pdo["entries"] if e["index"] in watch and e["subindex"] == 0]
            if not hit:
                continue
            t = _transmission(pdo, eds, comm_base + pdo["number"] - 1, node_id)
            if t is None or t <= 240:
                continue
            objects = ", ".join("0x%04X" % i for i in hit)
            if key == "rx_pdos":
                errors.append(("%s: RPDO %d (%s) has transmission type %d; a cyclic CiA 402 axis needs it synchronous "
                               "(0-240) so the drive applies the set-points on SYNC" % (who, pdo["number"], objects, t),
                               ".rx_pdos[%d].transmission" % j))
            else:
                warnings.append(("%s: TPDO %d (%s) has transmission type %d; with a cyclic axis a synchronous type "
                                 "gives the program feedback sampled on SYNC" % (who, pdo["number"], objects, t),
                                 ".tx_pdos[%d].transmission" % j))
    if not eds.has(0x60C2):
        warnings.append(("%s: its EDS has no 0x60C2 (interpolation time period); set the drive's cycle time some other "
                         "way" % who, ".axis.cyclic"))
    if not eds.has(0x6065):
        warnings.append(("%s: its EDS has no 0x6065 (following error window), so the config cannot set it; check "
                         "that the drive's own window suits the cyclic set-points (docs/cia402.md)" % who,
                         ".axis.cyclic"))
    o = eds.find(0x6502, 0)
    try:
        modes = o.value(node_id) if o is not None else None
    except Exception:
        modes = None
    if isinstance(modes, int):
        found = mapped(cfg_node, 0)
        for index, mode, name in ((0x607A, 8, "cyclic synchronous position"), (0x60FF, 9, "cyclic synchronous velocity"),
                                  (0x6071, 10, "cyclic synchronous torque")):
            if any(h[0] == "rx_pdos" for h in found.get(index, [])) and not (modes >> (mode - 1)) & 1:
                warnings.append(("%s: 0x%04X is mapped, but the EDS's 0x6502 (supported drive modes, 0x%08X) does not "
                                 "list %s (mode %d)" % (who, index, modes, name, mode), ".axis.cyclic"))
    return errors, warnings


def device_type_warning(node, eds):
    """The warning for an axis node whose EDS does not report profile 402, or None."""
    if not is_axis(node) or eds is None:
        return None
    o = eds.find(0x1000, 0)
    value = None
    if o is not None:
        try:
            value = o.value(_int(node.get("node_id")) or 0)
        except Exception:  # an unreadable default is the EDS lint's business
            value = None
    if isinstance(value, int) and value & 0xFFFF == PROFILE:
        return None
    shown = "0x%08X" % value if isinstance(value, int) else "no value"
    return ("%s: CiA 402 axis: its EDS device type (0x1000) is %s, not device profile 402; check that this is a "
            "CiA 402 drive" % (label(node), shown))


def _literal(type_name, value):
    if type_name == "LREAL":
        text = repr(float(value))
        return "LREAL#" + (text if "." in text or "e" in text else text + ".0")
    return "%s#%d" % (type_name, int(value))


def glue(cfg, decls, cycle_s=0.02):
    """(declarations, body lines) for every axis node, in config order.

    `decls` are the program's located variable declarations
    (configurator.declare), whose names the bridge call uses. Declarations
    are {name, type, node, kind: "axis", description} without a location.
    With several networks (as in declare) names start with the network's
    name, paths with networks[i]. and `node` counts the nodes of all
    networks. A cyclic axis also gets its fCycleTime, `cycle_s` (the
    task interval in seconds)."""
    from . import contract  # contract imports this module
    by_path = {d["path"]: d["name"] for d in decls}
    out, body = [], []
    nets = contract.networks(cfg) if isinstance(cfg, dict) else []
    first = 0
    for net in nets:
        nodes = [x for x in net["nodes"] if isinstance(x, dict)]
        several = len(nets) > 1 and net["name"]
        at = net["path"] + "." if net["path"] else ""
        prefix = identifier(net["name"]) + "_" if several else ""
        desc = "network %s: " % net["name"] if several else ""
        for i, n in enumerate(nodes):
            if is_axis(n):
                _axis_glue(n, first + i, at + "nodes[%d]" % i, prefix, desc, by_path, out, body, cycle_s)
        first += len(nodes)
    return out, body


def _axis_glue(n, flat, w, prefix, desc, by_path, out, body, cycle_s):
    name, bridge = prefix + axis_name(n), prefix + bridge_name(n)
    who = desc + ("node %s (%s)" % (n.get("name"), n.get("node_id")) if n.get("name")
                  else "node %s" % n.get("node_id"))
    out.append({"name": name, "type": AXIS_TYPE, "location": None, "node": flat, "kind": "axis",
                "path": w + ".axis", "declared_as": None,
                "description": "%s: CiA 402 axis" % who})
    out.append({"name": bridge, "type": BRIDGE_TYPE, "location": None, "node": flat, "kind": "axis",
                "path": w + ".axis.bridge", "declared_as": None,
                "description": "%s: drive bridge of axis %s" % (who, name)})
    if not body:
        body.append(BODY_HEAD)
    a = n["axis"]
    for field, member, type_name, default in SCALING:
        body.append("%s.%s := %s;" % (name, member, _literal(type_name, a.get(field, default))))
    if is_cyclic(n):
        body.append("%s.fCycleTime := %s; (* the task interval: change it with the interval *)"
                    % (name, _literal("LREAL", round(cycle_s, 9))))
    binds = ["Axis := %s" % name]
    found = mapped(n, 0)
    status = by_path.get(w + ".status_location")
    outputs = []
    for index in PIN_ORDER:
        pin, key, _, _, _ = OBJECTS[index]
        for pkey, j, k, e in found.get(index, []):
            var = by_path.get("%s.%s[%d].entries[%d].iec_location" % (w, pkey, j, k))
            if var and pkey == key:
                (binds if key == "tx_pdos" else outputs).append(
                    ("%s := %s" if key == "tx_pdos" else "%s => %s") % (pin, var))
                break
    binds.append("bOnline := %s" % (status or "TRUE"))
    binds += outputs
    body.append("%s(%s);" % (bridge, (",\n" + " " * (len(bridge) + 1)).join(binds)))


def text_block(cfg, decls, cycle_s=0.02):
    """The axis declarations and bridge lines as text to paste into an
    existing program, or "" when the config has no axis."""
    axes, body = glue(cfg, decls, cycle_s)
    if not axes:
        return ""
    width = max(len(d["name"]) for d in axes)
    lines = ["VAR"]
    lines += ["  %s : %s; (* %s *)" % (d["name"].ljust(width), d["type"], comment_text(d["description"])) for d in axes]
    lines += ["END_VAR", "", "(* First lines of the program body: *)"] + body
    return "\n".join(lines) + "\n"
