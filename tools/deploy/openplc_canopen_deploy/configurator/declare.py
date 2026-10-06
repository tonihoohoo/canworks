"""Located variable declarations for the editor, from a CANopen config."""

import re

from ..iec import parse_location
from .layout import MASTER_LOCATIONS, NODE_LOCATIONS, SDO_VARIABLE_LOCATIONS

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
# Order inside a node in a generated program: diagnostics, inputs, outputs, NMT command last.
_RANK = {("diag", "I"): 0, ("pdo", "I"): 1, ("sdo", "I"): 2, ("pdo", "Q"): 3, ("sdo", "Q"): 4, ("nmt", "Q"): 5}


def comment_text(text):
    """One line that is safe inside (* ... *)."""
    text = re.sub(r"\s+", " ", str(text or "")).replace("(*", "( *").replace("*)", "* )")
    return text.strip()


def declarations(cfg, object_name, declared):
    """[{name, location, type, path, declared_as, node, kind, description}]
    for every mapped entry,
    node diagnostic input and NMT command byte, SDO variable (value, trigger,
    status, abort code), and the master's diagnostic inputs. `object_name(node index, index, subindex)` gives the EDS
    ParameterName (or None); `declared` maps JSON paths to the name of a
    variable already declared at that location."""
    out, names = [], set()

    def unique(base):
        name, n = base, 2
        while name.lower() in names:
            name = "%s_%d" % (base, n)
            n += 1
        names.add(name.lower())
        return name

    master = cfg.get("master") or {}
    for key, _, name, iec_type in MASTER_LOCATIONS:
        if parse_location(master.get(key)):
            path = "master." + key
            out.append({"name": unique(name), "location": master[key].strip(), "type": iec_type,
                        "path": path, "declared_as": declared.get(path), "node": None, "kind": "diag",
                        "description": MASTER_TEXT[key]})

    for i, n in enumerate(cfg.get("nodes", [])):
        prefix = identifier(n.get("name") or "node%s" % n.get("node_id"))
        who = "node %s (%s)" % (n.get("name"), n.get("node_id")) if n.get("name") else "node %s" % n.get("node_id")
        for key, _, suffix, iec_type in NODE_LOCATIONS:
            if parse_location(n.get(key)):
                path = "nodes[%d].%s" % (i, key)
                out.append({"name": unique("%s_%s" % (prefix, suffix)), "location": n[key].strip(), "type": iec_type,
                            "path": path, "declared_as": declared.get(path), "node": i,
                            "kind": "nmt" if key == "nmt_command_location" else "diag",
                            "description": "%s: %s" % (who, NODE_TEXT[key])})
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
                    path = "nodes[%d].%s[%d].entries[%d].iec_location" % (i, key, j, k)
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
            vp = "nodes[%d].sdo_variables[%d]" % (i, j)
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
    return out


def program_order(decls):
    """The declarations in a generated program's order: master diagnostics,
    then node by node in config order with diagnostics, inputs (PDO, then
    SDO), outputs (PDO, then SDO) and the NMT command byte last."""
    def key(d):
        area = d["location"].strip()[1:2].upper()
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
    """A VAR ... END_VAR block of the declarations not yet in the project."""
    rows = [d for d in decls if not d["declared_as"]]
    if not rows:
        return ""
    width = max(len(d["name"]) for d in rows)
    lines = ["VAR"]
    lines += ["  %s AT %s : %s;" % (d["name"].ljust(width), d["location"], d["type"]) for d in rows]
    lines.append("END_VAR")
    return "\n".join(lines) + "\n"
