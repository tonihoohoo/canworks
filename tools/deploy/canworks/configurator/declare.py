"""Located variable declarations for the editor, from a canworks config
(CANopen and J1939 networks)."""

import re

from .. import contract
from ..iec import parse_location
from ..iec import CO_TYPES, type_fits
from .layout import C_MACROS, MASTER_LOCATIONS, NODE_LOCATIONS, SDO_VARIABLE_LOCATIONS, SIZE_TYPES, SLAVE_LOCATIONS

IEC_TYPE = {
    "BOOLEAN": "BOOL",
    "INTEGER8": "SINT", "INTEGER16": "INT", "INTEGER32": "DINT", "INTEGER64": "LINT",
    "UNSIGNED8": "USINT", "UNSIGNED16": "UINT", "UNSIGNED32": "UDINT", "UNSIGNED64": "ULINT",
    "REAL32": "REAL", "REAL64": "LREAL",
}


def identifier(text):
    """An IEC 61131-3 identifier: letters, digits and single underscores,
    not starting with a digit."""
    s = re.sub(r"[^A-Za-z0-9_]+", "_", text or "")
    s = re.sub(r"_+", "_", s).strip("_")
    if not s:
        s = "v"
    if s[0].isdigit():
        s = "n" + s
    return s


# Descriptions of the master's and a node's diagnostic locations.
MASTER_TEXT = {
    "bus_state_location": "CAN bus state", "tx_error_count_location": "CAN TX error count",
    "rx_error_count_location": "CAN RX error count", "bus_off_count_location": "CAN bus-off count",
    "state_location": "CANopen master state",
}
NODE_TEXT = {
    "status_location": "operational", "state_location": "NMT state", "boot_error_location": "boot error",
    "emcy_code_location": "last EMCY code", "error_register_location": "error register",
    "nmt_command_location": "NMT command",
}
SDO_TEXT = {"trigger_location": "trigger", "status_location": "status", "abort_code_location": "abort code"}
SLAVE_TEXT = {"state_location": "own NMT state", "comm_ok_location": "communication OK",
              "sync_count_location": "SYNC count", "emcy_code_location": "EMCY code to send",
              "error_register_location": "error register to send"}
# A J1939 signal's IEC type by location size: (unsigned, signed).
J1939_TYPES = {"X": ("BOOL", "BOOL"), "B": ("USINT", "SINT"), "W": ("UINT", "INT"), "D": ("UDINT", "DINT"),
               "L": ("ULINT", "LINT")}
J1939_ECU_TEXT = {"state_location": ("ecu_state", "J1939 address claim state (0 claiming, 1 claimed, 2 cannot "
                                                  "claim, 3 no bus)"),
                  "address_location": ("ecu_address", "J1939 source address (254 while none is held)")}
# Order inside a node in a generated program: diagnostics, inputs, outputs, NMT command last.
SLAVE_RANK = 1 << 30
_RANK = {("diag", "I"): 0, ("pdo", "I"): 1, ("sdo", "I"): 2, ("pdo", "Q"): 3, ("sdo", "Q"): 4, ("nmt", "Q"): 5}


def comment_text(text):
    """One line that is safe inside (* ... *)."""
    text = re.sub(r"\s+", " ", str(text or "")).replace("(*", "( *").replace("*)", "* )")
    return text.strip()


def number_text(v):
    """A scale or offset as written in a comment: 1, 0.1, -40."""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return repr(v) if isinstance(v, float) else str(v)


def scaling_text(scale, offset, unit):
    """The comment of a J1939 signal's declaration: "x 0.1 + 0 bar"."""
    return ("x %s + %s %s" % (number_text(scale), number_text(offset), unit or "")).strip()


def declarations(cfg, object_name, declared, slave_object=None):
    """[{name, location, type, path, declared_as, node, kind, description}]
    for every mapped entry,
    node diagnostic input and NMT command byte, SDO variable (value, trigger,
    status, abort code), and the master's diagnostic inputs. `object_name(node index, index, subindex)` gives the EDS
    ParameterName (or None); `declared` maps JSON paths to the name of a
    variable already declared at that location.

    With several networks (schema_version 2) every name starts with the
    network's name, every description names the network, paths start with
    networks[i]. and node indexes count the nodes of all networks in order.

    A slave network adds one variable per bound object and per status
    location (kind "slave", node None), always named after the network:
    `<network>_<name>`, the name from the binding's `name`, else the
    object's ParameterName, which `slave_object(eds value, index, subindex)`
    gives together with its CANopen type as (name, type), or None. The IEC
    type is the object's when it fits the location, else the location
    size's.

    A J1939 network adds one variable per signal (kind "j1939", node
    None), named `<network>_<signal>`, typed by its location size and
    `signed`, with `comment` holding its scale, offset and unit ("x 0.1 + 0
    bar"); one per ECU state and address location (`<network>_ecu_state`,
    `<network>_ecu_address`), per rx status location (`<network>_<message>_ok`,
    the message's name or PGN) and per signal valid location
    (`<network>_<signal>_valid`)."""
    out, names = [], set()

    def unique(base):
        name, n = base, 2
        while name.lower() in names or name.upper() in C_MACROS:
            name = "%s_%d" % (base, n)
            n += 1
        names.add(name.lower())
        return name

    def network(master, nodes, at, net, desc, first):
        for key, _, name, iec_type in MASTER_LOCATIONS:
            if parse_location(master.get(key)):
                path = at + "master." + key
                out.append({"name": unique(net + name), "location": master[key].strip(), "type": iec_type,
                            "path": path, "declared_as": declared.get(path), "node": None, "kind": "diag",
                            "description": desc + MASTER_TEXT[key]})

        for i, n in enumerate(nodes, first):
            prefix = net + identifier(n.get("name") or "node%s" % n.get("node_id"))
            who = desc + ("node %s (%s)" % (n.get("name"), n.get("node_id")) if n.get("name")
                          else "node %s" % n.get("node_id"))
            for key, _, suffix, iec_type in NODE_LOCATIONS:
                if parse_location(n.get(key)):
                    path = at + "nodes[%d].%s" % (i - first, key)
                    out.append({"name": unique("%s_%s" % (prefix, suffix)), "location": n[key].strip(),
                                "type": iec_type, "path": path, "declared_as": declared.get(path), "node": i,
                                "kind": "nmt" if key == "nmt_command_location" else "diag",
                                "description": "%s: %s" % (who, NODE_TEXT[key])})
            for j, p in enumerate(n.get("tx_pdos") or []):
                if parse_location(p.get("timeout_location")):
                    path = at + "nodes[%d].tx_pdos[%d].timeout_location" % (i - first, j)
                    number = p.get("number") or j + 1
                    out.append({"name": unique("%s_tpdo%s_timeout" % (prefix, number)),
                                "location": p["timeout_location"].strip(), "type": "BOOL", "path": path,
                                "declared_as": declared.get(path), "node": i, "kind": "diag",
                                "description": "%s: TPDO %s receive timeout" % (who, number)})
            for key in ("tx_pdos", "rx_pdos"):
                for j, p in enumerate(n.get(key) or []):
                    for k, e in enumerate(p.get("entries") or []):
                        if not parse_location(e.get("iec_location")) or e.get("type") not in IEC_TYPE:
                            continue
                        index = e["index"] if isinstance(e["index"], int) else int(str(e["index"]), 0)
                        sub = e.get("subindex", 0)
                        sub = sub if isinstance(sub, int) else int(str(sub), 0)
                        eds_name = object_name(i, index, sub)
                        label = eds_name or "x%04X_%d" % (index, sub)
                        path = at + "nodes[%d].%s[%d].entries[%d].iec_location" % (i - first, key, j, k)
                        pdo = "%s%s" % ("TPDO" if key == "tx_pdos" else "RPDO", p.get("number") or j + 1)
                        text = "%s %s 0x%04X:%d %s" % (who, pdo, index, sub, eds_name or "")
                        out.append({"name": unique("%s_%s" % (prefix, identifier(label))),
                                    "location": e["iec_location"].strip(), "type": IEC_TYPE[e["type"]],
                                    "path": path, "declared_as": declared.get(path), "node": i, "kind": "pdo",
                                    "description": text.strip()})
            for j, v in enumerate(n.get("sdo_variables") or []):
                if not parse_location(v.get("iec_location")) or v.get("type") not in IEC_TYPE:
                    continue
                try:
                    index = v["index"] if isinstance(v["index"], int) else int(str(v["index"]), 0)
                    sub = v.get("subindex", 0)
                    sub = sub if isinstance(sub, int) else int(str(sub), 0)
                except (KeyError, ValueError):
                    index = sub = None
                label = v.get("name")
                if not label:
                    if index is None:
                        continue
                    label = object_name(i, index, sub) or "x%04X_%d" % (index, sub)
                base = unique("%s_%s" % (prefix, identifier(label)))
                vp = at + "nodes[%d].sdo_variables[%d]" % (i - first, j)
                what = "%s SDO %s" % (who, v.get("direction") or "variable")
                if index is not None:
                    what += " 0x%04X:%d %s" % (index, sub, object_name(i, index, sub) or "")
                what = what.strip()
                out.append({"name": base, "location": v["iec_location"].strip(), "type": IEC_TYPE[v["type"]],
                            "path": vp + ".iec_location", "declared_as": declared.get(vp + ".iec_location"),
                            "node": i, "kind": "sdo", "description": what})
                for key, _, _, suffix, iec_type in SDO_VARIABLE_LOCATIONS:
                    if parse_location(v.get(key)):
                        path = "%s.%s" % (vp, key)
                        out.append({"name": unique("%s_%s" % (base, suffix)), "location": v[key].strip(),
                                    "type": iec_type, "path": path, "declared_as": declared.get(path), "node": i,
                                    "kind": "sdo", "description": "%s, %s" % (what, SDO_TEXT[key])})

    def slave_network(n):
        s = n["slave"]
        net = identifier(n["name"] or "slave")
        at = n["path"] + "." if n["path"] else ""
        who = "network %s: slave node %s" % (n["name"], s.get("node_id") if s.get("node_id") is not None else "(LSS)")
        objects = s.get("objects")
        for j, o in enumerate(objects if isinstance(objects, list) else []):
            loc = parse_location(o.get("iec_location") if isinstance(o, dict) else None)
            if not loc:
                continue
            try:
                index = o["index"] if isinstance(o["index"], int) else int(str(o["index"]), 0)
                sub = o.get("subindex", 0)
                sub = sub if isinstance(sub, int) else int(str(sub), 0)
            except (KeyError, ValueError):
                continue
            eds_name, co_type = (slave_object(s.get("eds"), index, sub) if slave_object else None) or (None, None)
            label = o.get("name") or eds_name or "x%04X_%d" % (index, sub)
            iec_type = IEC_TYPE[co_type] if co_type in CO_TYPES and type_fits(co_type, loc.size) \
                else SIZE_TYPES[loc.size]
            path = at + "slave.objects[%d].iec_location" % j
            text = "%s 0x%04X:%d %s, %s" % (who, index, sub, eds_name or "",
                                            "from the master" if loc.area == "I" else "to the master")
            out.append({"name": unique("%s_%s" % (net, identifier(label))), "location": o["iec_location"].strip(),
                        "type": iec_type, "path": path, "declared_as": declared.get(path), "node": None,
                        "kind": "slave", "description": re.sub(r"\s+", " ", text)})
        for key, _, _, suffix, iec_type in SLAVE_LOCATIONS:
            if parse_location(s.get(key)):
                path = at + "slave." + key
                out.append({"name": unique("%s_%s" % (net, suffix)), "location": s[key].strip(), "type": iec_type,
                            "path": path, "declared_as": declared.get(path), "node": None, "kind": "slave",
                            "description": "%s: %s" % (who, SLAVE_TEXT[key])})

    def j1939_network(n):
        j = n["j1939"]
        net = identifier(n["name"] or "j1939")
        at = n["path"] + "." if n["path"] else ""
        who = "network %s:" % n["name"]

        def add(name, location, iec_type, path, text, comment=None):
            d = {"name": unique(name), "location": location.strip(), "type": iec_type, "path": at + path,
                 "declared_as": declared.get(at + path), "node": None, "kind": "j1939", "description": text}
            if comment:
                d["comment"] = comment
            out.append(d)

        ecu = j.get("ecu") if isinstance(j.get("ecu"), dict) else {}
        for key, (suffix, text) in J1939_ECU_TEXT.items():
            if parse_location(ecu.get(key)):
                add("%s_%s" % (net, suffix), ecu[key], "USINT", "j1939.ecu." + key, "%s %s" % (who, text))
        for key in ("rx", "tx"):
            for i, m in enumerate(j.get(key) if isinstance(j.get(key), list) else []):
                if not isinstance(m, dict):
                    continue
                pgn = contract._uint(m.get("pgn"))
                msg = "PGN %s" % pgn + (" (%s)" % m["name"] if m.get("name") else "")
                mp = "j1939.%s[%d]" % (key, i)
                if key == "rx" and parse_location(m.get("status_location")):
                    add("%s_%s_ok" % (net, identifier(m.get("name") or "PGN%s" % pgn)), m["status_location"], "BOOL",
                        mp + ".status_location", "%s %s received in time" % (who, msg))
                for k, sg in enumerate(m.get("signals") if isinstance(m.get("signals"), list) else []):
                    loc = parse_location(sg.get("iec_location") if isinstance(sg, dict) else None)
                    if not loc or loc.size not in J1939_TYPES:
                        continue
                    sname = identifier(sg.get("name"))
                    comment = scaling_text(sg.get("scale", 1), sg.get("offset", 0), sg.get("unit", ""))
                    add("%s_%s" % (net, sname), sg["iec_location"], J1939_TYPES[loc.size][sg.get("signed") is True],
                        "%s.signals[%d].iec_location" % (mp, k),
                        "%s %s %s, %s" % (who, msg, sg.get("name"), comment), comment)
                    if key == "rx" and parse_location(sg.get("valid_location")):
                        add("%s_%s_valid" % (net, sname), sg["valid_location"], "BOOL",
                            "%s.signals[%d].valid_location" % (mp, k),
                            "%s %s %s valid (not 'not available' or 'error')" % (who, msg, sg.get("name")))

    nets = contract.networks(cfg) if isinstance(cfg, dict) else []
    base = 0
    for n in nets:
        if n["role"] == "slave":
            slave_network(n)
            continue
        if n["role"] == "j1939":
            j1939_network(n)
            continue
        several = len(nets) > 1 and n["name"]
        network(n["master"], [x for x in n["nodes"] if isinstance(x, dict)], n["path"] + "." if n["path"] else "",
                identifier(n["name"]) + "_" if several else "", "network %s: " % n["name"] if several else "", base)
        base += len([x for x in n["nodes"] if isinstance(x, dict)])
    return out


def program_order(decls):
    """The declarations in a generated program's order: master diagnostics,
    then node by node in config order with diagnostics, inputs (PDO, then
    SDO), outputs (PDO, then SDO) and the NMT command byte last, then the
    slave networks' inputs and outputs, then the J1939 networks'."""
    def key(d):
        area = d["location"].strip()[1:2].upper()
        if d.get("kind") == "slave":
            return SLAVE_RANK, 0 if area == "I" else 1  # after every node, inputs first
        if d.get("kind") == "j1939":
            return SLAVE_RANK + 1, 0 if area == "I" else 1
        node = -1 if d.get("node") is None else d["node"]
        return node, _RANK.get((d.get("kind"), area), 0 if area == "I" else 4)
    return sorted(decls, key=key)


def editor_block(decls, indent="  "):
    """A VAR block in the editor's own form (`name : TYPE AT loc; (* text *)`,
    `name : TYPE;` for a declaration without a location), indented as the
    editor writes a program's variables."""
    lines = [indent + "VAR"]
    if decls:
        width = max(len(d["name"]) for d in decls)
        for d in decls:
            if d.get("location"):
                line = "%s  %s : %s AT %s;" % (indent, d["name"].ljust(width), d["type"], d["location"])
            else:  # a plain variable (a CiA 402 axis and its bridge)
                line = "%s  %s : %s;" % (indent, d["name"].ljust(width), d["type"])
            text = comment_text(d.get("description"))
            if text:
                line += " (* %s *)" % text
            lines.append(line)
    lines.append(indent + "END_VAR")
    return "\n".join(lines)


def st_block(decls):
    """A VAR ... END_VAR block of the declarations not yet in the project,
    with a J1939 signal's scaling in a comment."""
    rows = [d for d in decls if not d["declared_as"]]
    if not rows:
        return ""
    width = max(len(d["name"]) for d in rows)
    lines = ["VAR"]
    lines += ["  %s AT %s : %s;%s" % (d["name"].ljust(width), d["location"], d["type"],
                                       " (* %s *)" % comment_text(d["comment"]) if d.get("comment") else "")
              for d in rows]
    lines.append("END_VAR")
    return "\n".join(lines) + "\n"
