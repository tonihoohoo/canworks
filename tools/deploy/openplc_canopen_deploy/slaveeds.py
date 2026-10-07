"""The slave EDS generator (canopen-slave-eds): a CiA 306 EDS for OpenPLC as
a CANopen slave, from a short JSON description, for the plugin to run and
for the other master's configuration tool to import unchanged.

    {"device_name": "OpenPLC slave", "vendor_id": 0, "product_code": 1,
     "revision_number": null, "heartbeat_ms": 1000, "layout": "manufacturer",
     "objects": [{"name": "speed_setpoint", "type": "UNSIGNED16",
                  "direction": "from_master", "default": 0, "low": null, "high": null}]}

Layouts:

    manufacturer  objects the master writes (from_master) in ARRAYs from
                  0x2000, those it reads (to_master) from 0x2100: one ARRAY
                  per data type in the order the types first appear, sub-index
                  0 the count. AccessType rww and ro, PDOMapping=1.
    cia401        device type 401 (0x191, with the I/O bits of what is there)
                  and the generic I/O objects: digital inputs 0x6000 and
                  outputs 0x6200 (UNSIGNED8), analog inputs 0x6401 and
                  outputs 0x6411 (INTEGER16). CiA 401 "inputs" are what the
                  master reads (to_master).

The communication area has what a CiA 301 slave with store/restore,
configuration date, heartbeat, guarding, EMCY and LSS needs. Default PDOs
carry every object in object order, at most 8 bytes each: RPDOs the
from_master objects, TPDOs the to_master ones, with the CiA 301 default
COB-IDs for PDOs 1-4 (PDOs 5 and up start switched off: the master gives them
a COB-ID), transmission type 255 and mapping the master may change.

With a gateway config (canopen-gateway, D14) the generator adds a slave
object per route (up: to_master, down: from_master, with the type of the
route's field entry), the field node status ARRAYs and the SDO bridge record.

Unless the description sets revision_number, 0x1018:3 is the low 32 bits of
the SHA-256 of the canonical JSON of the layout, the objects and the gateway
objects, so a master that checks identity notices a changed dictionary. The
output is deterministic (no dates) and passes the plugin's EDS lint with
eds_lint "all"; generate() checks that before it returns.
"""

import hashlib
import json
import math
import os
import struct

from . import edslint
from .contract import DEFAULT_BRIDGE_INDEX, DEFAULT_STATUS_INDEX, MAX_STATUS_NETWORKS, _uint, networks, sdo_value
from .iec import CO_TYPES

LAYOUTS = ("manufacturer", "cia401")
DIRECTIONS = ("from_master", "to_master")
DEFAULT_NAME = "OpenPLC slave"
DEFAULT_HEARTBEAT_MS = 1000
FROM_MASTER_BASE, TO_MASTER_BASE = 0x2000, 0x2100
MAX_SUBS = 254
MAX_PDOS = 512
MIN_PDOS = 4  # the CiA 301 predefined connection set, so the master can remap
PDO_BITS = 64
# CiA 401 generic I/O: (type, direction) -> (index, ParameterName, device type bit).
CIA401 = {
    ("UNSIGNED8", "to_master"): (0x6000, "Read input 8-bit", 0x00010000),
    ("UNSIGNED8", "from_master"): (0x6200, "Write output 8-bit", 0x00020000),
    ("INTEGER16", "to_master"): (0x6401, "Read analog input 16-bit", 0x00040000),
    ("INTEGER16", "from_master"): (0x6411, "Write analog output 16-bit", 0x00080000),
}
CIA401_DEVICE_TYPE = 0x00000191
STRING = 0x0009  # VISIBLE_STRING
U8, U16, U32 = 0x0005, 0x0006, 0x0007
# The SDO bridge record (canopen-gateway, D13): (sub-index, name, type, access, PDO-mappable).
BRIDGE = ((1, "Network", U8, "rw", False), (2, "Node", U8, "rw", False), (3, "Index", U16, "rw", False),
          (4, "Subindex", U8, "rw", False), (5, "Value", U32, "rw", True), (6, "Length", U8, "rw", False),
          (7, "Command", U8, "rw", False), (8, "Status", U8, "ro", True), (9, "Abort code", U32, "ro", False))


class DescriptionError(Exception):
    pass


# ---------------------------------------------------------------------------
# The description

def _number(value, type_name, what):
    """The EDS text of a value of `type_name` (REALs as Lely's hexadecimal
    bit pattern, so the plugin reads the file unchanged)."""
    if type_name in ("REAL32", "REAL64"):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise DescriptionError("%s must be a number" % what)
        if type_name == "REAL32":
            if abs(value) > 3.4028234663852886e38:
                raise DescriptionError("%s does not fit REAL32" % what)
            return "0x%08X" % struct.unpack("<I", struct.pack("<f", value))[0]
        return "0x%016X" % struct.unpack("<Q", struct.pack("<d", value))[0]
    if isinstance(value, bool):
        value = int(value)
    if isinstance(value, float) and value == math.floor(value):
        value = int(value)
    if not isinstance(value, int):
        raise DescriptionError("%s must be an integer" % what)
    _, problem = sdo_value(value, type_name)
    if problem:
        raise DescriptionError("%s %s %s" % (what, value, problem))
    return str(value)


def _numeric(text, type_name):
    """A value written by _number() as a number, to compare limits."""
    if type_name == "REAL32":
        return struct.unpack("<f", struct.pack("<I", int(text, 16)))[0]
    if type_name == "REAL64":
        return struct.unpack("<d", struct.pack("<Q", int(text, 16)))[0]
    return int(text)


def _uint_field(desc, key, default, high, what=None):
    value = desc.get(key, default)
    if value is None:
        return default
    n = _uint(value)
    if n is None or n > high:
        raise DescriptionError("%s must be 0-%d: %s" % (what or "'%s'" % key, high, json.dumps(value)))
    return n


def _text(value, what):
    if not isinstance(value, str) or not value.strip():
        raise DescriptionError("%s must be a non-empty string" % what)
    if any(ord(c) < 32 for c in value):
        raise DescriptionError("%s may not hold control characters" % what)
    return value.strip()


def check_description(desc):
    """The description with defaults filled in and values as EDS text:
    {device_name, vendor_name, vendor_id, product_code, revision_number
    (None: from the hash), heartbeat_ms, layout, objects: [{name, type,
    direction, default, low, high}]}. Raises DescriptionError naming the
    object and the field."""
    if not isinstance(desc, dict):
        raise DescriptionError("the description must be a JSON object")
    out = {"device_name": _text(desc.get("device_name", DEFAULT_NAME), "'device_name'"),
           "vendor_name": _text(desc.get("vendor_name", "OpenPLC"), "'vendor_name'"),
           "vendor_id": _uint_field(desc, "vendor_id", 0, 0xFFFFFFFF),
           "product_code": _uint_field(desc, "product_code", 0, 0xFFFFFFFF),
           "revision_number": (None if desc.get("revision_number") is None
                               else _uint_field(desc, "revision_number", 0, 0xFFFFFFFF)),
           "heartbeat_ms": _uint_field(desc, "heartbeat_ms", DEFAULT_HEARTBEAT_MS, 0xFFFF)}
    layout = desc.get("layout", "manufacturer")
    if layout not in LAYOUTS:
        raise DescriptionError("layout %s is not supported (supported: %s)" % (json.dumps(layout), ", ".join(LAYOUTS)))
    out["layout"] = layout
    objects = desc.get("objects", [])
    if not isinstance(objects, list):
        raise DescriptionError("'objects' must be a list")
    out["objects"] = []
    names = {}
    for i, o in enumerate(objects):
        out["objects"].append(check_object(o, i, layout, names))
    return out


def check_object(o, i, layout, names):
    """One description object, checked as check_description() does."""
    if not isinstance(o, dict):
        raise DescriptionError("objects[%d] must be an object" % i)
    if "name" not in o:
        raise DescriptionError("objects[%d] has no 'name'" % i)
    name = _text(o["name"], "objects[%d]: 'name'" % i)
    what = "object '%s' (objects[%d])" % (name, i)
    if name.lower() in names:
        raise DescriptionError("%s: the name is also used by %s" % (what, names[name.lower()]))
    names[name.lower()] = "objects[%d]" % i
    if "type" not in o:
        raise DescriptionError("%s has no 'type' (supported: %s)" % (what, ", ".join(CO_TYPES)))
    type_name = o["type"]
    direction = o.get("direction")
    if direction not in DIRECTIONS:
        raise DescriptionError("%s: 'direction' must be from_master (the master writes it, a PLC input) or "
                               "to_master (the master reads it, a PLC output)" % what)
    if layout == "cia401" and (type_name, direction) not in CIA401:
        raise DescriptionError("%s: layout cia401 takes UNSIGNED8 (digital) and INTEGER16 (analog) objects, not %s"
                               % (what, json.dumps(type_name)))
    if type_name not in CO_TYPES:
        raise DescriptionError("%s: type %s is not supported (supported: %s)"
                               % (what, json.dumps(type_name), ", ".join(CO_TYPES)))
    out = {"name": name, "type": type_name, "direction": direction}
    for key in ("default", "low", "high"):
        value = o.get(key)
        out[key] = None if value is None else _number(value, type_name, "%s: '%s'" % (what, key))
    low = _numeric(out["low"], type_name) if out["low"] is not None else None
    high = _numeric(out["high"], type_name) if out["high"] is not None else None
    if low is not None and high is not None and low > high:
        raise DescriptionError("%s: 'low' is above 'high'" % what)
    if out["default"] is not None:
        d = _numeric(out["default"], type_name)
        if (low is not None and d < low) or (high is not None and d > high):
            raise DescriptionError("%s: 'default' is outside 'low' and 'high'" % what)
    return out


# ---------------------------------------------------------------------------
# The gateway's objects

def gateway_objects(cfg, names=()):
    """The objects a gateway config adds (canopen-gateway, D14): one per
    route, with its direction from the field entry (TPDO entry: to_master,
    RPDO entry: from_master) and the entry's type, named after the route.
    Returns (objects as check_object() gives them, status networks [names
    of the master networks, at most 4] or None, bridge index or None).
    Raises DescriptionError for a route whose field end is not a PDO entry
    of the config."""
    if not isinstance(cfg, dict) or not isinstance(cfg.get("gateway"), dict):
        raise DescriptionError("the config has no 'gateway' section")
    g = cfg["gateway"]
    nets = networks(cfg)
    by_name = {n["name"]: n for n in nets if n["name"]}
    taken = {n.lower(): "an object of the description" for n in names}
    objects = []
    for j, rt in enumerate(g.get("routes") or []):
        f = rt.get("field") if isinstance(rt, dict) else None
        if not isinstance(f, dict):
            raise DescriptionError("gateway: routes[%d] has no 'field'" % j)
        net = by_name.get(f.get("network"))
        if net is None or net["role"] != "master":
            raise DescriptionError("gateway: routes[%d]: no master network '%s' in the config" % (j, f.get("network")))
        node_id, index, sub = _uint(f.get("node")), _uint(f.get("index")), _uint(f.get("subindex", 0))
        node = next((n for n in net["nodes"] if isinstance(n, dict) and _uint(n.get("node_id")) == node_id), None)
        if node is None:
            raise DescriptionError("gateway: routes[%d]: network %s has no node %s" % (j, f.get("network"), node_id))
        found = None
        for key, direction in (("tx_pdos", "to_master"), ("rx_pdos", "from_master")):
            for p in node.get(key) or []:
                for e in p.get("entries") or []:
                    if found is None and _uint(e.get("index")) == index and _uint(e.get("subindex", 0)) == sub:
                        found = (direction, e.get("type"))
        if found is None:
            raise DescriptionError("gateway: routes[%d]: network %s node %d 0x%04X:%d is not an entry of the node's "
                                   "tx_pdos or rx_pdos" % (j, f.get("network"), node_id, index or 0, sub or 0))
        name = rt.get("name") if isinstance(rt.get("name"), str) and rt.get("name").strip() else "route%d" % (j + 1)
        try:
            objects.append(check_object({"name": name, "type": found[1], "direction": found[0]}, j, "manufacturer",
                                        taken))
        except DescriptionError as e:
            raise DescriptionError("gateway: routes[%d]: %s" % (j, str(e).replace("objects[%d]" % j, "route", 1)))
    status = None
    if isinstance(g.get("status"), dict):
        masters = [n["name"] for n in nets if n["role"] == "master"]
        if len(masters) > MAX_STATUS_NETWORKS:
            raise DescriptionError("gateway: 'status' covers at most %d field networks; the config has %d"
                                   % (MAX_STATUS_NETWORKS, len(masters)))
        status = (_uint(g["status"].get("index", DEFAULT_STATUS_INDEX)), masters)
    bridge = _uint(g.get("sdo_bridge_index", DEFAULT_BRIDGE_INDEX)) if g.get("sdo_bridge") is True else None
    return objects, status, bridge


# ---------------------------------------------------------------------------
# The dictionary

class Var:
    """One sub-object (or a VAR)."""

    def __init__(self, name, data_type, access, default="", pdo=False, low=None, high=None):
        self.name, self.data_type, self.access, self.default = name, data_type, access, default
        self.pdo, self.low, self.high = pdo, low, high


class Obj:
    """One object: a VAR (subs is a Var) or an ARRAY/RECORD ({sub: Var})."""

    def __init__(self, index, name, var=None, subs=None, object_type=0x7):
        self.index, self.name, self.var, self.subs, self.object_type = index, name, var, subs, object_type


def _array(index, name, data_type, entries, access, sub0_access="ro", object_type=0x8, pdo=False, default="0"):
    """An ARRAY (or RECORD) whose sub-index 0 is the count and the others
    one each of `entries` (names, or (name, type, access, default, pdo))."""
    subs = {0: Var("Highest sub-index supported", U8, sub0_access, str(len(entries)))}
    for k, e in enumerate(entries, 1):
        if isinstance(e, tuple):
            subs[k] = Var(e[0], e[1], e[2], e[3], e[4])
        else:
            subs[k] = Var(e, data_type, access, default, pdo)
    return Obj(index, name, subs=subs, object_type=object_type)


def _type_code(type_name):
    return CO_TYPES[type_name][0]


def _layout(objects, layout):
    """[(object index, sub-index)] of each object, and the ARRAYs that hold
    them: [Obj]."""
    places, arrays = [None] * len(objects), []
    if layout == "cia401":
        groups = {}
        for i, o in enumerate(objects):
            groups.setdefault((o["type"], o["direction"]), []).append(i)
        for key in sorted(groups, key=lambda k: CIA401[k][0]):
            index, name, _ = CIA401[key]
            members = groups[key]
            if len(members) > MAX_SUBS:
                raise DescriptionError("layout cia401 holds at most %d %s objects %s the master; there are %d"
                                       % (MAX_SUBS, key[0], "from" if key[1] == "from_master" else "to", len(members)))
            arrays.append(_values(index, name, [objects[i] for i in members]))
            for k, i in enumerate(members, 1):
                places[i] = (index, k)
        return places, arrays
    for direction, base in (("from_master", FROM_MASTER_BASE), ("to_master", TO_MASTER_BASE)):
        groups = []  # [type, [object positions]] in order of first appearance, at most MAX_SUBS each
        for i, o in enumerate(objects):
            if o["direction"] != direction:
                continue
            group = next((g for g in groups if g[0] == o["type"] and len(g[1]) < MAX_SUBS), None)
            if group is None:
                group = [o["type"], []]
                groups.append(group)
            group[1].append(i)
        if len(groups) > 0x100:
            raise DescriptionError("too many objects %s the master" % ("from" if direction == "from_master" else "to"))
        for n, (type_name, members) in enumerate(groups):
            index = base + n
            arrays.append(_values(index, "%s %s master" % (type_name, "from" if direction == "from_master" else "to"),
                                  [objects[i] for i in members]))
            for k, i in enumerate(members, 1):
                places[i] = (index, k)
    return places, arrays


def _values(index, name, members):
    subs = {0: Var("Highest sub-index supported", U8, "ro", str(len(members)))}
    for k, o in enumerate(members, 1):
        subs[k] = Var(o["name"], _type_code(o["type"]), "rww" if o["direction"] == "from_master" else "ro",
                      o["default"] if o["default"] is not None else _zero(o["type"]), True, o["low"], o["high"])
    return Obj(index, name, subs=subs, object_type=0x8)


def _zero(type_name):
    return "0x00000000" if type_name == "REAL32" else ("0x0000000000000000" if type_name == "REAL64" else "0")


def _pack(items):
    """Default PDO mappings of one direction: items [(index, sub, bits)]
    packed in order, at most 64 bits a PDO. Returns [[(index, sub, bits)]]."""
    pdos = []
    for item in items:
        if not pdos or sum(b for _, _, b in pdos[-1]) + item[2] > PDO_BITS:
            pdos.append([])
        pdos[-1].append(item)
    if len(pdos) > MAX_PDOS:
        raise DescriptionError("the objects need %d PDOs of one direction; a device has at most %d"
                               % (len(pdos), MAX_PDOS))
    return pdos


def _pdo_objects(pdos, tx):
    """The communication and mapping objects of one direction: at least
    MIN_PDOS PDOs, those beyond the used ones switched off and empty."""
    out = []
    count = max(MIN_PDOS, len(pdos))
    kind = "TPDO" if tx else "RPDO"
    for n in range(count):
        mapped = pdos[n] if n < len(pdos) else []
        if n < 4:
            cob = "$NODEID+0x%X" % ((0x180 if tx else 0x200) + 0x100 * n)
            if not mapped:
                cob = "$NODEID+0x%X" % (0x80000000 + (0x180 if tx else 0x200) + 0x100 * n)
        else:
            cob = "0x80000000"  # no CiA 301 default: the master gives it a COB-ID
        subs = {0: Var("Highest sub-index supported", U8, "ro", "6" if tx else "5"),
                1: Var("COB-ID used by %s" % kind, U32, "rw", cob),
                2: Var("Transmission type", U8, "rw", "255")}
        if tx:
            subs[3] = Var("Inhibit time", U16, "rw", "0")
            subs[5] = Var("Event timer", U16, "rw", "0")
            subs[6] = Var("SYNC start value", U8, "rw", "0")
        else:
            subs[5] = Var("Event timer", U16, "rw", "0")
        base = 0x1800 if tx else 0x1400
        out.append(Obj(base + n, "%s communication parameter %d" % (kind, n + 1), subs=subs, object_type=0x9))
        entries = max(8, len(mapped))
        msubs = {0: Var("Number of mapped objects", U8, "rw", str(len(mapped)))}
        for k in range(1, entries + 1):
            value = "0x%08X" % ((mapped[k - 1][0] << 16) | (mapped[k - 1][1] << 8) | mapped[k - 1][2]) \
                if k <= len(mapped) else "0x00000000"
            msubs[k] = Var("Mapped object %d" % k, U32, "rw", value)
        out.append(Obj(base + 0x200 + n, "%s mapping parameter %d" % (kind, n + 1), subs=msubs, object_type=0x9))
    return out


def identity_hash(layout, objects, gateway=None):
    """The revision number derived from the content: the low 32 bits of the
    SHA-256 of the canonical JSON of the layout, the objects and the gateway
    objects."""
    doc = {"layout": layout, "objects": objects}
    if gateway:
        doc["gateway"] = gateway
    digest = hashlib.sha256(json.dumps(doc, sort_keys=True, separators=(",", ":")).encode("utf-8")).digest()
    return int.from_bytes(digest[-4:], "big")


def generate(desc, gateway=None, file_name="openplc-slave.eds"):
    """(EDS text, info) for a description (check_description()) and,
    optionally, a gateway config. info: {revision_number, layout, objects:
    [{name, type, direction, index, subindex}] (the description's, then the
    routes'), routes: [{index, subindex}] (the slave end of each route, in
    route order), pdos: {"rx": n, "tx": n}}. The text passes the plugin's
    EDS lint with eds_lint "all". Raises DescriptionError."""
    d = check_description(desc)
    objects = list(d["objects"])
    status = bridge = None
    route_objects = []
    if gateway is not None:
        route_objects, status, bridge = gateway_objects(gateway, [o["name"] for o in objects])
    if d["layout"] == "manufacturer":
        places, arrays = _layout(objects + route_objects, "manufacturer")
    else:
        places, arrays = _layout(objects, "cia401")
        if route_objects:
            more, extra = _layout(route_objects, "manufacturer")
            places, arrays = places + more, arrays + extra
    all_objects = objects + route_objects
    gw_doc = None
    extra_objs = []
    status_tx = []
    if status is not None:
        base_index, masters = status
        for k, net in enumerate(masters):
            extra_objs.append(_array(base_index + k, "Field node states %s" % net, U8,
                                     ["Node %d state" % n for n in range(1, 128)], "ro", pdo=True))
            bits = _array(base_index + 0x10 + k, "Operational nodes %s" % net, U32,
                          ["Nodes %d-%d" % (32 * q, 32 * q + 31) for q in range(4)], "ro", pdo=True)
            extra_objs.append(bits)
            status_tx += [(base_index + 0x10 + k, q, 32) for q in range(1, 5)]
    if bridge is not None:
        extra_objs.append(_array(bridge, "SDO bridge", U8, [(n, t, a, "0", p) for _, n, t, a, p in BRIDGE], "rw",
                                 object_type=0x9))
    if gateway is not None:
        gw_doc = {"routes": [dict(o, index=places[len(objects) + j][0], subindex=places[len(objects) + j][1])
                             for j, o in enumerate(route_objects)],
                  "status": [status[0], status[1]] if status else None, "sdo_bridge": bridge}
    used = {a.index for a in arrays}
    for o in extra_objs:
        if o.index in used or not 0x2000 <= o.index <= 0x5FFF:
            raise DescriptionError("gateway object 0x%04X collides with another object or is outside 0x2000-0x5FFF"
                                   % o.index)
        used.add(o.index)
    revision = d["revision_number"]
    if revision is None:
        revision = identity_hash(d["layout"], objects, gw_doc)

    rx = _pack([(places[i][0], places[i][1], CO_TYPES[o["type"]][1])
                for i, o in enumerate(all_objects) if o["direction"] == "from_master"])
    tx = _pack([(places[i][0], places[i][1], CO_TYPES[o["type"]][1])
                for i, o in enumerate(all_objects) if o["direction"] == "to_master"] + status_tx)

    device_type = 0
    if d["layout"] == "cia401":
        device_type = CIA401_DEVICE_TYPE
        for o in objects:
            device_type |= CIA401[(o["type"], o["direction"])][2]
    comm = [
        Obj(0x1000, "Device type", Var("Device type", U32, "ro", "0x%08X" % device_type)),
        Obj(0x1001, "Error register", Var("Error register", U8, "ro", "0", True)),
        _array(0x1003, "Pre-defined error field", U32, ["Standard error field %d" % k for k in range(1, 9)], "ro",
               sub0_access="rw"),
        Obj(0x1005, "COB-ID SYNC", Var("COB-ID SYNC", U32, "rw", "0x00000080")),
        Obj(0x1008, "Manufacturer device name", Var("Manufacturer device name", STRING, "const", d["device_name"])),
        Obj(0x100C, "Guard time", Var("Guard time", U16, "rw", "0")),
        Obj(0x100D, "Life time factor", Var("Life time factor", U8, "rw", "0")),
        _array(0x1010, "Store parameters", U32, ["Save all parameters", "Save communication parameters",
                                                 "Save application parameters", "Save manufacturer parameters"],
               "rw", default="1"),
        _array(0x1011, "Restore default parameters", U32, ["Restore all default parameters",
                                                           "Restore communication default parameters",
                                                           "Restore application default parameters",
                                                           "Restore manufacturer default parameters"], "rw", default="1"),
        Obj(0x1014, "COB-ID EMCY", Var("COB-ID EMCY", U32, "rw", "$NODEID+0x80")),
        Obj(0x1015, "Inhibit time EMCY", Var("Inhibit time EMCY", U16, "rw", "0")),
        _array(0x1016, "Consumer heartbeat time", U32, ["Consumer heartbeat time %d" % k for k in range(1, 5)], "rw"),
        Obj(0x1017, "Producer heartbeat time", Var("Producer heartbeat time", U16, "rw", str(d["heartbeat_ms"]))),
        _array(0x1018, "Identity object", U32, [("Vendor-ID", U32, "ro", "0x%08X" % d["vendor_id"], False),
                                                ("Product code", U32, "ro", "0x%08X" % d["product_code"], False),
                                                ("Revision number", U32, "ro", "0x%08X" % revision, False),
                                                ("Serial number", U32, "ro", "0x00000000", False)], "ro",
               object_type=0x9),
        _array(0x1020, "Verify configuration", U32, ["Configuration date", "Configuration time"], "rw"),
        _array(0x1029, "Error behavior", U8, ["Communication error"], "rw"),
        _array(0x1200, "SDO server parameter", U32, [("COB-ID client to server", U32, "ro", "$NODEID+0x600", False),
                                                     ("COB-ID server to client", U32, "ro", "$NODEID+0x580", False)],
               "ro", object_type=0x9),
    ]
    comm += _pdo_objects(rx, False) + _pdo_objects(tx, True)
    dictionary = sorted(comm + arrays + extra_objs, key=lambda o: o.index)
    text = _write(d, dictionary, revision, file_name, len(rx), len(tx), any(o["type"] == "BOOLEAN"
                                                                            for o in all_objects))
    # The plugin runs this file with eds_lint "all" if the user asks: it must pass.
    _, corrections, lint = edslint.check(text.encode("utf-8"))
    problems = [c.text for c in corrections] + ([lint.read_error] if lint.read_error else []) + \
        ["%s: %s" % (f.where(), f.message) for f in lint.failing("all")]
    if problems:  # pragma: no cover - a generator bug
        raise DescriptionError("the generated EDS fails the plugin's lint: " + "; ".join(problems))
    info = {"revision_number": revision, "layout": d["layout"], "device_name": d["device_name"],
            "objects": [dict(name=o["name"], type=o["type"], direction=o["direction"], index=places[i][0],
                             subindex=places[i][1]) for i, o in enumerate(all_objects)],
            "routes": [{"index": places[len(objects) + j][0], "subindex": places[len(objects) + j][1]}
                       for j in range(len(route_objects))],
            "pdos": {"rx": len(rx), "tx": len(tx)}}
    return text, info


# ---------------------------------------------------------------------------
# The file

def _write(d, dictionary, revision, file_name, n_rx, n_tx, booleans):
    lines = []

    def section(name, *entries):
        lines.append("[%s]" % name)
        lines.extend("%s=%s" % kv for kv in entries if kv[1] is not None)
        lines.append("")

    section("FileInfo", ("FileName", file_name), ("FileVersion", "1"), ("FileRevision", "0"), ("EDSVersion", "4.0"),
            ("Description", "%s, an OpenPLC controller as a CANopen slave" % d["device_name"]),
            ("CreatedBy", "openplc-canopen-deploy slave-eds"))
    rates = [("BaudRate_%d" % r, "1") for r in (10, 20, 50, 125, 250, 500, 800, 1000)]
    section("DeviceInfo", ("VendorName", d["vendor_name"]), ("VendorNumber", "0x%08X" % d["vendor_id"]),
            ("ProductName", d["device_name"]), ("ProductNumber", "0x%08X" % d["product_code"]),
            ("RevisionNumber", "0x%08X" % revision), *rates, ("SimpleBootUpMaster", "0"),
            ("SimpleBootUpSlave", "1"), ("Granularity", "1" if booleans else "8"), ("DynamicChannelsSupported", "0"),
            ("GroupMessaging", "0"), ("NrOfRxPDO", str(max(MIN_PDOS, n_rx))), ("NrOfTxPDO", str(max(MIN_PDOS, n_tx))),
            ("LSS_Supported", "1"), ("CompactPDO", "0"))
    comments = ["Generated by openplc-canopen-deploy slave-eds (layout %s). The OpenPLC CANopen plugin runs this" % d[
        "layout"], "file unchanged; import the same file into the master's configuration tool.",
                "PDOs 5 and up start switched off (COB-ID bit 31): the master gives them a COB-ID."]
    section("Comments", ("Lines", str(len(comments))), *[("Line%d" % (k + 1), c) for k, c in enumerate(comments)])
    mandatory = [o for o in dictionary if o.index in (0x1000, 0x1001, 0x1018)]
    optional = [o for o in dictionary if o not in mandatory and not 0x2000 <= o.index <= 0x5FFF]
    manufacturer = [o for o in dictionary if 0x2000 <= o.index <= 0x5FFF]
    for listing, objs in (("MandatoryObjects", mandatory), ("OptionalObjects", optional),
                          ("ManufacturerObjects", manufacturer)):
        section(listing, ("SupportedObjects", str(len(objs))),
                *[(str(k), "0x%04X" % o.index) for k, o in enumerate(objs, 1)])
        for o in objs:
            if o.var is not None:
                section("%04X" % o.index, *_var_entries(o.name, o.var))
                continue
            section("%04X" % o.index, ("ParameterName", o.name), ("ObjectType", "0x%X" % o.object_type),
                    ("SubNumber", str(len(o.subs))))
            for sub in sorted(o.subs):
                section("%04Xsub%X" % (o.index, sub), *_var_entries(o.subs[sub].name, o.subs[sub]))
    return "\r\n".join(lines)


def _var_entries(name, v):
    return [("ParameterName", name), ("ObjectType", "0x7"), ("DataType", "0x%04X" % v.data_type),
            ("AccessType", v.access), ("DefaultValue", v.default), ("LowLimit", v.low), ("HighLimit", v.high),
            ("PDOMapping", "1" if v.pdo else "0")]


def write(text, path):
    """Writes the EDS through a temporary file and a rename; returns the path."""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        f.write(text)
    os.replace(tmp, path)
    return path


def load_json(path, what):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except OSError as e:
        raise DescriptionError("cannot read %s %s: %s" % (what, path, e.strerror or e))
    except ValueError as e:
        raise DescriptionError("%s %s is not valid JSON (%s)" % (what, path, e))


def update_routes(cfg, info):
    """Writes the slave end of each route (info["routes"]) into the gateway
    config's routes, in place; returns how many changed."""
    changed = 0
    for rt, place in zip(cfg["gateway"].get("routes") or [], info["routes"]):
        want = {"index": "0x%04X" % place["index"], "subindex": place["subindex"]}
        have = rt.get("slave") if isinstance(rt.get("slave"), dict) else {}
        if _uint(have.get("index")) != place["index"] or _uint(have.get("subindex", 0)) != place["subindex"]:
            changed += 1
        rt["slave"] = want
    return changed
