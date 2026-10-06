"""EDS (CiA 306) reading and the checks the plugin runs at load.

Mirrors plugin/src/eds_check.cpp, message for message: the shared fixtures in
test/fixtures/ run through both. The plugin reads EDS files with Lely; this
module reads the parts the checks need (object list, DataType, AccessType,
PDOMapping) with configparser.
"""

import configparser

from .iec import CO_TYPES, CO_TYPE_BY_CODE

# AccessType -> (slave can send it in a TPDO, slave can receive it in an RPDO,
# writable over SDO). CiA 306; the same table as Lely's CO_ACCESS_* flags.
ACCESS = {
    "ro": (True, False, False),
    "wo": (False, True, True),
    "rw": (True, True, True),
    "rwr": (True, False, True),
    "rww": (False, True, True),
    "const": (True, False, False),
}


class EdsError(Exception):
    pass


def to_utf8(data):
    """(UTF-8 bytes, converted?) for an EDS file's bytes: UTF-8 as is, else
    CP1252, with the five bytes CP1252 leaves undefined read as Latin-1."""
    try:
        data.decode("utf-8")
        return data, False
    except UnicodeDecodeError:
        pass
    text = "".join(b.decode("cp1252") if b not in b"\x81\x8d\x8f\x90\x9d" else b.decode("latin-1")
                   for b in (data[i:i + 1] for i in range(len(data))))
    return text.encode("utf-8"), True


class SubObject:
    def __init__(self, data_type, access, pdo_mapping, name="", default="", parameter="", low_limit="",
                 high_limit=""):
        self.data_type = data_type
        self.access = access
        self.pdo_mapping = pdo_mapping
        self.name = name
        self.default = default
        self.parameter = parameter  # ParameterValue, if the file has one
        self.low_limit, self.high_limit = low_limit, high_limit  # LowLimit/HighLimit text, "" when absent

    def value(self, node_id):
        """The value the device starts with, as Lely reads it: ParameterValue,
        else DefaultValue, with $NODEID resolved ("$NODEID+0x180", and the
        "0x180+$NODEID" form some vendors write). None if not a number."""
        text = (self.parameter or self.default).strip()
        if not text:
            return None
        parts = [t.strip() for t in text.split("+")]
        total = 0
        for t in parts:
            if t.upper() == "$NODEID":
                total += node_id
                continue
            try:
                total += int(t, 0)
            except ValueError:
                return None
        return total

    @property
    def type_name(self):
        return CO_TYPE_BY_CODE.get(self.data_type)

    @property
    def directions(self):
        """The PDO directions the object can be mapped in: "input" (the slave
        sends it, TPDO) and/or "output" (the slave receives it, RPDO). Empty
        when it is not PDO-mappable or is const."""
        if not self.pdo_mapping or self.access == "const":
            return ()
        can_send, can_receive, _ = ACCESS[self.access]
        return tuple(d for d, ok in (("input", can_send), ("output", can_receive)) if ok)

    @property
    def writable(self):
        return ACCESS[self.access][2]


def _int(text, what):
    try:
        return int(str(text).strip(), 0)
    except ValueError:
        raise EdsError("%s is not a number: %r" % (what, text))


class Eds:
    """The object dictionary of an EDS file: {index: {subindex: SubObject}}."""

    def __init__(self, objects, names=None, object_types=None):
        self.objects = objects
        # The ParameterName of each record/array object (index: name); a VAR's
        # name is its sub-index 0's.
        self.names = names or {}
        # The ObjectType of each object (0x7 VAR, 0x8 ARRAY, 0x9 RECORD).
        self.object_types = object_types or {}

    def find(self, index, subindex):
        return self.objects.get(index, {}).get(subindex)

    def has(self, index):
        return index in self.objects

    def items(self):
        """(index, subindex, SubObject) for every subobject, in order."""
        for index in sorted(self.objects):
            for sub in sorted(self.objects[index]):
                yield index, sub, self.objects[index][sub]

    def mappable(self):
        """(index, subindex, SubObject) for every object a PDO can carry
        with a type the config supports."""
        return [(i, s, o) for i, s, o in self.items() if o.directions and o.type_name]

    def pdo_count(self, direction):
        """How many PDOs of a direction the EDS defines: TPDOs (input) are
        0x1800+n with mapping 0x1A00+n, RPDOs (output) 0x1400+n / 0x1600+n."""
        comm = 0x1800 if direction == "input" else 0x1400
        n = 0
        while n < 512 and self.has(comm + n) and self.has(comm + 0x200 + n):
            n += 1
        return n

    @classmethod
    def read(cls, path, text=None):
        """Reads an EDS file, or `text` (its prepared copy, edslint.prepare)
        in its place; `path` then only names it in messages."""
        parser = configparser.ConfigParser(strict=False, interpolation=None, comment_prefixes=(";", "#"))
        try:
            if text is None:
                with open(path, "rb") as f:
                    data = f.read()
                # UTF-8 (what the editor project route stores), else Latin-1 as most vendor EDS files are.
                try:
                    text = data.decode("utf-8")
                except UnicodeDecodeError:
                    text = data.decode("latin-1")
            parser.read_string(text, path)
        except configparser.Error as e:
            raise EdsError(str(e).splitlines()[0])
        sections = {name.lower(): parser[name] for name in parser.sections()}

        def sub_from(section, where, name=None):
            if "datatype" not in section:
                raise EdsError("[%s] has no DataType" % where)
            access = section.get("accesstype", "").strip().lower()
            if access not in ACCESS:
                raise EdsError("[%s] has an invalid AccessType %r" % (where, access))
            return SubObject(_int(section["datatype"], "[%s] DataType" % where), access,
                             _int(section.get("pdomapping", "0"), "[%s] PDOMapping" % where) != 0,
                             name if name is not None else section.get("parametername", "").strip(),
                             section.get("defaultvalue", "").strip(), section.get("parametervalue", "").strip(),
                             section.get("lowlimit", "").strip(), section.get("highlimit", "").strip())

        objects, names, object_types = {}, {}, {}
        for list_name in ("mandatoryobjects", "optionalobjects", "manufacturerobjects"):
            listing = sections.get(list_name)
            if listing is None:
                continue
            count = _int(listing.get("supportedobjects", "0"), "[%s] SupportedObjects" % list_name)
            for i in range(1, count + 1):
                if str(i) not in listing:
                    raise EdsError("[%s] lists %d objects but has no entry %d" % (list_name, count, i))
                index = _int(listing[str(i)], "[%s] %d" % (list_name, i))
                name = "%x" % index
                section = sections.get(name) or sections.get("%04x" % index)
                if section is None:
                    raise EdsError("object 0x%04X is listed in [%s] but has no section" % (index, list_name))
                object_type = _int(section.get("objecttype", "0x7"), "[%04X] ObjectType" % index)
                subs = {}
                object_types[index] = object_type
                if object_type != 0x7:
                    names[index] = section.get("parametername", "").strip()
                if object_type == 0x7:
                    subs[0] = sub_from(section, "%04X" % index)
                elif "compactsubobj" in section and _int(section["compactsubobj"], "CompactSubObj"):
                    n = _int(section["compactsubobj"], "[%04X] CompactSubObj" % index)
                    subs[0] = SubObject(0x0005, "ro", False)
                    base_name = section.get("parametername", "").strip()
                    for sub in range(1, n + 1):
                        subs[sub] = sub_from(section, "%04X" % index, "%s%d" % (base_name, sub))
                else:
                    for sub in range(0, 256):
                        s = sections.get("%xsub%x" % (index, sub)) or sections.get("%04xsub%x" % (index, sub))
                        if s is not None:
                            subs[sub] = sub_from(s, "%04Xsub%X" % (index, sub))
                objects[index] = subs
        if 0x1000 not in objects or 0x1018 not in objects:
            raise EdsError("mandatory objects 0x1000/0x1018 missing (not a CiA 306 EDS)")
        return cls(objects, names, object_types)

    def object_name(self, index, subindex):
        """The sub-object's name in the object dictionary: a VAR's
        ParameterName, or for a record/array sub-object the parent's
        ParameterName and the sub-object's own (`parent`, `sub`); `parent` is
        "" for a VAR. ("", "") when the sub-object is not in the EDS."""
        sub = self.find(index, subindex)
        if sub is None:
            return "", ""
        return self.names.get(index, ""), sub.name


def device_info(path):
    """The [DeviceInfo] identity of an EDS file: {vendor_id, product_code,
    revision_number (each an int or None), vendor_name, product_name,
    lss_supported (LSS_Supported is set and not 0)}, or
    None when the file cannot be read as an INI file. Reads only that section,
    so it is cheap enough to run over an EDS library folder."""
    parser = configparser.ConfigParser(strict=False, interpolation=None, comment_prefixes=(";", "#"))
    try:
        with open(path, "rb") as f:
            data = f.read()
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            text = data.decode("latin-1")
        parser.read_string(text, path)
    except (OSError, configparser.Error):
        return None
    section = next((parser[s] for s in parser.sections() if s.lower() == "deviceinfo"), None)
    if section is None:
        return None

    def number(key):
        text = section.get(key, "").strip()
        try:
            return int(text, 16) if text.lower().startswith("0x") else int(text, 10)
        except ValueError:
            return None

    return {"vendor_id": number("vendornumber"), "product_code": number("productnumber"),
            "revision_number": number("revisionnumber"), "vendor_name": section.get("vendorname", "").strip(),
            "product_name": section.get("productname", "").strip(), "lss_supported": bool(number("lss_supported"))}


def transmission_needs_sync(t):
    """Transmission types that only act on SYNC (CiA 301): 0-240 synchronous, 252 synchronous RTR."""
    return t <= 240 or t == 252


def sync_needed_message(transmission, from_eds):
    return ("transmission type %d%s needs SYNC, but the master produces none; set master.sync_period_us, "
            "\"sync_source\": \"plc_cycle\" or \"transmission\": 254 or 255"
            % (transmission, " (from the EDS)" if from_eds else ""))


def data_type_name(code):
    name = CO_TYPE_BY_CODE.get(code)
    return name if name else "0x%04X" % code


def _where(node_id, index, subindex):
    return "node %d, index 0x%04X, subindex %d" % (node_id, index, subindex)


def _check_type(where, sub, type_name, report):
    want = CO_TYPES[type_name][0]
    if sub.data_type != want:
        report("%s: configured type %s does not match the EDS data type %s"
                      % (where, type_name, data_type_name(sub.data_type)))


# Communication sub-indices of a PDO: (sub-index, JSON field). The plugin
# writes these from the PDO settings (cob_id is resolved by the caller).
COMM_FIELDS = ((1, "cob_id"), (2, "transmission"), (3, "inhibit_time_us"), (5, "event_timer_ms"), (6, "sync_start"))


def _comm_value(pdo, field):
    v = pdo.get(field)
    if v is None:
        return None
    return v // 100 if field == "inhibit_time_us" else v


def _check_comm(label, kind, eds, eds_name, node_id, comm, pdo, report):
    """Each PDO communication field set in the config needs its sub-index in
    the EDS, writable unless the EDS value already matches."""
    for sub_index, field in COMM_FIELDS:
        value = _comm_value(pdo, field)
        if value is None:
            continue
        head = "%s: %s %d: '%s' needs object 0x%04X subindex %d" % (label, kind, pdo["number"], field, comm, sub_index)
        sub = eds.find(comm, sub_index)
        if sub is None:
            report("%s, which %s does not define" % (head, eds_name), field)
            continue
        if ACCESS[sub.access][2]:
            continue
        have = sub.value(node_id)
        if have is not None:
            if field == "cob_id":
                if (have & 0x7FF) == value and not have & 0x80000000:
                    continue
                have &= 0x7FF
            elif have == value:
                continue
        if have is None:
            tail = ""
        elif field == "cob_id":
            tail = " (EDS value 0x%03X, config 0x%03X)" % (have, value)
        else:
            tail = " (EDS value %d)" % have
        report("%s, but its AccessType in %s is %s%s; leave the field out or set it to the EDS value"
               % (head, eds_name, sub.access, tail), field)
    cob = eds.find(comm, 1)
    default = pdo.get("default_cob_id")
    if pdo.get("cob_id") is None and default is not None and cob is not None and not cob.writable:
        # Left out, the plugin still writes the CiA 301 default COB-ID, which
        # a node with a fixed COB-ID only takes when it is the same.
        have = cob.value(node_id)
        if have is not None and ((have & 0x7FF) != default or have & 0x80000000):
            report("%s: %s %d: %s fixes the COB-ID at 0x%03X%s (0x%04X subindex 1 is %s), but the plugin uses the "
                   "CiA 301 default 0x%03X; set 'cob_id' to the EDS value"
                   % (label, kind, pdo["number"], eds_name, have & 0x7FF,
                      " with the PDO switched off" if have & 0x80000000 else "", comm, cob.access, default), "cob_id")
    if pdo.get("sync_start") is not None and pdo.get("transmission") is None:
        tt = eds.find(comm, 2)
        t = tt.value(node_id) if tt is not None else None
        if t is not None and not 1 <= t <= 240:
            report("%s: %s %d: 'sync_start' needs a synchronous transmission type (1-240), but the EDS gives %d"
                   % (label, kind, pdo["number"], t), "sync_start")


def mapping_info(eds, map_index):
    """The PDO mapping object as the EDS defines it, like the plugin's
    eds_mapping(): dict with writable, fixed_sub, fixed_access, has_default,
    missing_sub and defaults (one 0xIIIISSLL value per mapped object)."""
    m = {"writable": True, "fixed_sub": 0, "fixed_access": "", "has_default": True, "missing_sub": 0,
         "defaults": []}
    sub0 = eds.find(map_index, 0)
    if sub0 is None:
        m["has_default"] = False
        return m
    if not sub0.writable:
        m["writable"], m["fixed_access"] = False, sub0.access
    count = (sub0.value(0) or 0) if sub0.data_type == 0x0005 else 0
    if count == 0 or count > 64:
        m["has_default"] = False
    for k in range(1, min(count, 64) + 1):
        sub = eds.find(map_index, k)
        v = (sub.value(0) or 0) if sub is not None and sub.data_type == 0x0007 else 0
        if not v:
            if m["has_default"]:
                m["missing_sub"] = k
            m["has_default"] = False
        else:
            m["defaults"].append(v)
        if sub is not None and m["writable"] and not sub.writable:
            m["writable"], m["fixed_sub"], m["fixed_access"] = False, k, sub.access
    return m


def uses_device_mapping(pdo, info):
    """Whether the PDO keeps the device's mapping: "device", or left out on a
    mapping the EDS makes read-only."""
    mode = pdo.get("mapping")
    return mode == "device" or (mode is None and not info["writable"])


def mapping_list(defaults):
    return ", ".join("0x%04X:%d (%d bit)" % (v >> 16, (v >> 8) & 0xFF, v & 0xFF) for v in defaults)


def _check_mapping(label, kind, eds, eds_name, node_id, pdo, map_index, report, warn):
    """The plugin's check_mapping(): the mapping mode against the EDS, and
    a device-mapped PDO's entries against its default mapping."""
    if not eds.has(map_index):
        return
    m = mapping_info(eds, map_index)
    head = "%s: %s %d" % (label, kind, pdo["number"])
    if pdo.get("mapping") == "config" and not m["writable"]:
        report('%s: \'mapping\' is "config", but %s fixes the mapping (0x%04X subindex %d is %s); leave '
               '\'mapping\' out or set it to "device"' % (head, eds_name, map_index, m["fixed_sub"], m["fixed_access"]),
               ".mapping")
        return
    if not uses_device_mapping(pdo, m):
        return
    if not m["has_default"]:
        report("%s uses the device mapping, but %s gives no default mapping (0x%04X subindex %d has no "
               "DefaultValue, or 0)" % (head, eds_name, map_index, m["missing_sub"]), "")
        return
    used = [False] * len(m["defaults"])
    for k, e in enumerate(pdo["entries"]):
        found = False
        for i, v in enumerate(m["defaults"]):
            if v >> 16 != e["index"] or (v >> 8) & 0xFF != e["subindex"]:
                continue
            found = used[i] = True
            bits = CO_TYPES[e["type"]][1]
            if v & 0xFF != bits:
                report("%s: configured type %s (%d bit) does not match the %d bit the default mapping of %s %d "
                       "gives it" % (_where(node_id, e["index"], e["subindex"]), e["type"], bits, v & 0xFF, kind,
                                     pdo["number"]), ".entries[%d].type" % k)
        if not found:
            report("%s: not in the default mapping of %s %d in %s (%s); a PDO with the device mapping can only use "
                   "these objects" % (_where(node_id, e["index"], e["subindex"]), kind, pdo["number"], eds_name,
                                      mapping_list(m["defaults"])), ".entries[%d]" % k)
    if kind == "RPDO":
        unnamed = ["0x%04X:%d" % (v >> 16, (v >> 8) & 0xFF) for i, v in enumerate(m["defaults"])
                   if not used[i] and v >> 16 >= 0x0008]
        if unnamed:
            warn("%s uses the device mapping; objects not in 'entries' are sent as 0: %s" % (head, ", ".join(unnamed)))


def check_node(node, eds, errors, paths=None, warnings=None):
    """Runs the plugin's EDS checks for one node (a parsed config node: dict
    with integer node_id, index and subindex values). Appends messages, and
    to `paths` (when given) each message's field path within the node
    (".tx_pdos[0].entries[1]", ".sdo[2]", or "" for the whole node).
    Warnings go to `warnings` as (message, path) pairs."""
    paths = paths if paths is not None else []
    warnings = warnings if warnings is not None else []

    def add(msg, where_in_node):
        errors.append(msg)
        paths.append(where_in_node)

    node_id = node["node_id"]
    eds_name = node["eds"]
    label = "node %d" % node_id + (" (%s)" % node["name"] if node.get("name") else "")
    for key, kind, comm_base in (("tx_pdos", "TPDO", 0x1800), ("rx_pdos", "RPDO", 0x1400)):
        is_tx = key == "tx_pdos"
        for j, pdo in enumerate(node.get(key, [])):
            comm = comm_base + pdo["number"] - 1
            if not eds.has(comm) or not eds.has(comm + 0x200):
                add("%s: %s %d does not exist in %s (no object 0x%04X/0x%04X)"
                              % (label, kind, pdo["number"], eds_name, comm, comm + 0x200), ".%s[%d]" % (key, j))
            elif eds.has(comm):
                _check_comm(label, kind, eds, eds_name, node_id, comm, pdo,
                            lambda m, f, j=j, key=key: add(m, ".%s[%d].%s" % (key, j, f)))
                # Without SYNC, a PDO left at a synchronous EDS transmission
                # type would never move; nothing picks another type for it.
                tt = eds.find(comm, 2) if node.get("no_sync") and pdo.get("transmission") is None else None
                t = tt.value(node_id) if tt is not None else None
                if t is not None and transmission_needs_sync(t):
                    add("%s: %s %d: %s" % (label, kind, pdo["number"], sync_needed_message(t, True)),
                        ".%s[%d].transmission" % (key, j))
            _check_mapping(label, kind, eds, eds_name, node_id, pdo, comm + 0x200,
                           lambda m, f, j=j, key=key: add(m, ".%s[%d]%s" % (key, j, f)),
                           lambda m, j=j, key=key: warnings.append((m, ".%s[%d]" % (key, j))))
            for k, e in enumerate(pdo["entries"]):
                at = ".%s[%d].entries[%d]" % (key, j, k)
                where = _where(node_id, e["index"], e["subindex"])
                sub = eds.find(e["index"], e["subindex"])
                if sub is None:
                    add("%s: object is not defined in %s" % (where, eds_name), at)
                    continue
                if not sub.pdo_mapping:
                    add("%s: object is not PDO-mappable in %s" % (where, eds_name), at)
                    continue
                can_send, can_receive, _ = ACCESS[sub.access]
                if is_tx and not can_send:
                    add("%s: tx_pdos entry needs an object the slave can send (AccessType ro, rw, rwr or "
                                  "const), but its AccessType is %s" % (where, sub.access), at)
                if not is_tx and not can_receive:
                    add("%s: rx_pdos entry needs an object the slave can receive (AccessType wo, rw or "
                                  "rww), but its AccessType is %s" % (where, sub.access), at)
                _check_type(where, sub, e["type"], lambda m: add(m, at + ".type"))
    for j, v in enumerate(node.get("sdo_variables", [])):
        at = ".sdo_variables[%d]" % j
        where = _where(node_id, v["index"], v["subindex"])
        sub = eds.find(v["index"], v["subindex"])
        if sub is None:
            add("%s: object is not defined in %s" % (where, eds_name), at)
            continue
        if v["direction"] == "read" and sub.access == "wo":
            add("%s: SDO variable to read needs a readable object (AccessType ro, rw, rwr, rww or const), but its "
                "AccessType is %s" % (where, sub.access), at)
        if v["direction"] == "write" and not ACCESS[sub.access][2]:
            add("%s: SDO variable to write needs a writable object (AccessType wo, rw, rwr or rww), but its "
                "AccessType is %s" % (where, sub.access), at)
        _check_type(where, sub, v["type"], lambda m: add(m, at + ".type"))
    # config_check writes the configuration date and time (0x1020 sub 1, 2),
    # store_configuration the "save" signature to 0x1010.
    needs = [(0x1020, 1, "config_check"), (0x1020, 2, "config_check")] if node.get("config_check") else []
    if node.get("store_configuration"):
        needs.append((0x1010, node["store_configuration"], "store_configuration"))
    for index, subindex, field in needs:
        where = _where(node_id, index, subindex)
        sub = eds.find(index, subindex)
        if sub is None:
            add("%s: %s needs this object, but it is not defined in %s" % (where, field, eds_name), "." + field)
            continue
        if not ACCESS[sub.access][2]:
            add("%s: %s needs a writable object (AccessType wo, rw, rwr or rww), but its AccessType is %s"
                % (where, field, sub.access), "." + field)
        _check_type(where, sub, "UNSIGNED32", lambda m, field=field: add(m, "." + field))
    for j, s in enumerate(node.get("sdo", [])):
        at = ".sdo[%d]" % j
        where = _where(node_id, s["index"], s["subindex"])
        sub = eds.find(s["index"], s["subindex"])
        if sub is None:
            add("%s: object is not defined in %s" % (where, eds_name), at)
            continue
        if not ACCESS[sub.access][2]:
            add("%s: startup SDO needs a writable object (AccessType wo, rw, rwr or rww), but its "
                          "AccessType is %s" % (where, sub.access), at)
        _check_type(where, sub, s["type"], lambda m: add(m, at + ".type"))
