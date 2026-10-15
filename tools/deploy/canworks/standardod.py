"""The standard object dictionary of a node that has no EDS: the CiA 301
communication objects, and the CiA 401 or CiA 402 standard objects when the
device's 0x1000 names that profile (canopen-configurator: Standard object
dictionary without an EDS).

The objects are a table here, written out as EDS text and read with the
EDS reader (eds.Eds), so the configurator's object dictionary view, its reads,
notes and edits work on them as on a device's EDS. The entries have no
default values: a standard gives none that every device keeps. Only 0x1000
carries the profile number as its default, which picks the built-in profile
notes (notes.profile); the configurator does not show it as a default.

The table lists RPDO and TPDO 1-4 unless more are asked for; read_all looks
for further PDOs on the device. An ARRAY or RECORD object lists every
sub-index the standard allows (CiA 401 arrays up to IO_MAX); the page shows those up to the value the
device gives in sub-index 0."""

from . import eds as eds_mod
from .diag import DiagError, abort_text

BOOLEAN, I8, I16, I32, U8, U16, U32, STRING, DOMAIN = 0x1, 0x2, 0x3, 0x4, 0x5, 0x6, 0x7, 0x9, 0xF
VAR, ARRAY, RECORD = 0x7, 0x8, 0x9

PROFILES = (401, 402)
PROFILE_NAMES = {301: "CiA 301 device", 401: "CiA 401 I/O device", 402: "CiA 402 drive",
                 404: "CiA 404 measuring device", 406: "CiA 406 encoder", 408: "CiA 408 hydraulic drive",
                 410: "CiA 410 inclinometer", 413: "CiA 413 truck gateway", 418: "CiA 418 battery module",
                 419: "CiA 419 battery charger", 443: "CiA 443 SIIS level-2 device", 447: "CiA 447 car add-on device"}
DEFAULT_PDOS = 4
MAX_PDOS = 512
MAX_MAPPED = 64
IO_MAX = 64  # CiA 401 blocks and channels listed: 512 digital, 64 analog

NO_OBJECT = 0x06020000
NO_SUB = 0x06090011
LACKING = (NO_OBJECT, NO_SUB)


def profile_name(n):
    return PROFILE_NAMES.get(n, "CiA %d device" % n) if n else "CiA 301 device"


def _var(index, name, dtype, access, pdo=False):
    return (index, name, VAR, [(0, name, dtype, access, pdo)])


def _array(index, name, count_name, count_access, entry, dtype, access, last, pdo=False, names=None):
    """An ARRAY: sub-index 0 the count, 1 to `last` entries named
    `entry N` (or by `names`, 1-based)."""
    subs = [(0, count_name, U8, count_access, False)]
    for s in range(1, last + 1):
        nm = names[s - 1] if names and s <= len(names) else "%s %d" % (entry, s)
        subs.append((s, nm, dtype, access, pdo))
    return (index, name, ARRAY, subs)


def _record(index, name, subs):
    return (index, name, RECORD, [(0, "Highest sub-index supported", U8, "ro", False)] + list(subs))


HIGHEST = "Highest sub-index supported"

CIA301 = [
    _var(0x1000, "Device type", U32, "ro"),
    _var(0x1001, "Error register", U8, "ro", True),
    _var(0x1002, "Manufacturer status register", U32, "ro", True),
    _array(0x1003, "Pre-defined error field", "Number of errors", "rw", "Standard error field", U32, "ro", 254),
    _var(0x1005, "COB-ID SYNC message", U32, "rw"),
    _var(0x1006, "Communication cycle period", U32, "rw"),
    _var(0x1007, "Synchronous window length", U32, "rw"),
    _var(0x1008, "Manufacturer device name", STRING, "const"),
    _var(0x1009, "Manufacturer hardware version", STRING, "const"),
    _var(0x100A, "Manufacturer software version", STRING, "const"),
    _var(0x100C, "Guard time", U16, "rw"),
    _var(0x100D, "Life time factor", U8, "rw"),
    _array(0x1010, "Store parameters", HIGHEST, "ro", "Save manufacturer defined parameters", U32, "rw", 127,
           names=["Save all parameters", "Save communication parameters", "Save application parameters"]),
    _array(0x1011, "Restore default parameters", HIGHEST, "ro", "Restore manufacturer defined default parameters",
           U32, "rw", 127, names=["Restore all default parameters", "Restore communication default parameters",
                                  "Restore application default parameters"]),
    _var(0x1012, "COB-ID time stamp object", U32, "rw"),
    _var(0x1013, "High resolution time stamp", U32, "rw", True),
    _var(0x1014, "COB-ID EMCY", U32, "rw"),
    _var(0x1015, "Inhibit time EMCY", U16, "rw"),
    _array(0x1016, "Consumer heartbeat time", HIGHEST, "ro", "Consumer heartbeat time", U32, "rw", 127),
    _var(0x1017, "Producer heartbeat time", U16, "rw"),
    _record(0x1018, "Identity object", [(1, "Vendor-ID", U32, "ro", False), (2, "Product code", U32, "ro", False),
                                        (3, "Revision number", U32, "ro", False), (4, "Serial number", U32, "ro", False)]),
    _var(0x1019, "Synchronous counter overflow value", U8, "rw"),
    _array(0x1020, "Verify configuration", HIGHEST, "ro", "Verify configuration", U32, "rw", 2,
           names=["Configuration date", "Configuration time"]),
    _var(0x1021, "Store EDS", DOMAIN, "ro"),
    _var(0x1022, "Store format", U8, "ro"),
    _array(0x1028, "Emergency consumer object", HIGHEST, "ro", "Emergency consumer", U32, "rw", 127),
    _array(0x1029, "Error behavior object", HIGHEST, "ro", "Error class", U8, "rw", 254,
           names=["Communication error"]),
    _record(0x1200, "SDO server parameter", [(1, "COB-ID client to server", U32, "ro", False),
                                             (2, "COB-ID server to client", U32, "ro", False),
                                             (3, "Node-ID of the SDO client", U8, "rw", False)]),
]

CIA401 = [
    _array(0x6000, "Read input 8-bit", "Number of input 8-bit", "ro", "Read input block", U8, "ro", IO_MAX, True),
    _array(0x6002, "Polarity input 8-bit", "Number of input 8-bit", "ro", "Polarity input block", U8, "rw", IO_MAX),
    _array(0x6003, "Filter constant input 8-bit", "Number of input 8-bit", "ro", "Filter constant input block",
           U8, "rw", IO_MAX),
    _var(0x6005, "Global interrupt enable digital 8-bit", BOOLEAN, "rw"),
    _array(0x6006, "Interrupt mask any change 8-bit", "Number of input 8-bit", "ro", "Interrupt mask block",
           U8, "rw", IO_MAX),
    _array(0x6200, "Write output 8-bit", "Number of output 8-bit", "ro", "Write output block", U8, "rw", IO_MAX, True),
    _array(0x6202, "Change polarity output 8-bit", "Number of output 8-bit", "ro", "Change polarity output block",
           U8, "rw", IO_MAX),
    _array(0x6206, "Error mode output 8-bit", "Number of output 8-bit", "ro", "Error mode output block",
           U8, "rw", IO_MAX),
    _array(0x6207, "Error value output 8-bit", "Number of output 8-bit", "ro", "Error value output block",
           U8, "rw", IO_MAX),
    _array(0x6208, "Filter mask output 8-bit", "Number of output 8-bit", "ro", "Filter mask output block",
           U8, "rw", IO_MAX),
    _array(0x6401, "Read analog input 16-bit", "Number of analog input 16-bit", "ro", "Analog input",
           I16, "ro", IO_MAX, True),
    _array(0x6411, "Write analog output 16-bit", "Number of analog output 16-bit", "ro", "Analog output",
           I16, "rw", IO_MAX, True),
    _array(0x6421, "Analog input interrupt trigger selection", "Number of analog inputs", "ro",
           "Trigger selection analog input", U8, "rw", IO_MAX),
    _var(0x6423, "Analog input global interrupt enable", BOOLEAN, "rw"),
    _array(0x6424, "Analog input interrupt upper limit integer", "Number of analog inputs", "ro",
           "Upper limit analog input", I32, "rw", IO_MAX),
    _array(0x6425, "Analog input interrupt lower limit integer", "Number of analog inputs", "ro",
           "Lower limit analog input", I32, "rw", IO_MAX),
    _array(0x6426, "Analog input interrupt delta unsigned", "Number of analog inputs", "ro",
           "Delta analog input", U32, "rw", IO_MAX),
    _array(0x6443, "Analog output error mode", "Number of analog outputs", "ro", "Error mode analog output",
           U8, "rw", IO_MAX),
    _array(0x6444, "Analog output error value integer", "Number of analog outputs", "ro",
           "Error value analog output", I32, "rw", IO_MAX),
]

CIA402 = [
    _var(0x603F, "Error code", U16, "ro", True),
    _var(0x6040, "Controlword", U16, "rw", True),
    _var(0x6041, "Statusword", U16, "ro", True),
    _var(0x605A, "Quick stop option code", I16, "rw"),
    _var(0x605B, "Shutdown option code", I16, "rw"),
    _var(0x605C, "Disable operation option code", I16, "rw"),
    _var(0x605D, "Halt option code", I16, "rw"),
    _var(0x605E, "Fault reaction option code", I16, "rw"),
    _var(0x6060, "Modes of operation", I8, "rw", True),
    _var(0x6061, "Modes of operation display", I8, "ro", True),
    _var(0x6062, "Position demand value", I32, "ro", True),
    _var(0x6063, "Position actual internal value", I32, "ro", True),
    _var(0x6064, "Position actual value", I32, "ro", True),
    _var(0x6065, "Following error window", U32, "rw"),
    _var(0x6066, "Following error time out", U16, "rw"),
    _var(0x6067, "Position window", U32, "rw"),
    _var(0x6068, "Position window time", U16, "rw"),
    _var(0x606B, "Velocity demand value", I32, "ro", True),
    _var(0x606C, "Velocity actual value", I32, "ro", True),
    _var(0x606D, "Velocity window", U16, "rw"),
    _var(0x606E, "Velocity window time", U16, "rw"),
    _var(0x6071, "Target torque", I16, "rw", True),
    _var(0x6072, "Max torque", U16, "rw", True),
    _var(0x6073, "Max current", U16, "rw"),
    _var(0x6074, "Torque demand", I16, "ro", True),
    _var(0x6075, "Motor rated current", U32, "rw"),
    _var(0x6076, "Motor rated torque", U32, "rw"),
    _var(0x6077, "Torque actual value", I16, "ro", True),
    _var(0x6078, "Current actual value", I16, "ro", True),
    _var(0x6079, "DC link circuit voltage", U32, "ro", True),
    _var(0x607A, "Target position", I32, "rw", True),
    _var(0x607C, "Home offset", I32, "rw"),
    _array(0x607D, "Software position limit", HIGHEST, "ro", "Position limit", I32, "rw", 2,
           names=["Min position limit", "Max position limit"]),
    _var(0x607E, "Polarity", U8, "rw"),
    _var(0x607F, "Max profile velocity", U32, "rw", True),
    _var(0x6080, "Max motor speed", U32, "rw"),
    _var(0x6081, "Profile velocity", U32, "rw", True),
    _var(0x6082, "End velocity", U32, "rw"),
    _var(0x6083, "Profile acceleration", U32, "rw", True),
    _var(0x6084, "Profile deceleration", U32, "rw", True),
    _var(0x6085, "Quick stop deceleration", U32, "rw"),
    _var(0x6086, "Motion profile type", I16, "rw"),
    _var(0x6087, "Torque slope", U32, "rw"),
    _var(0x6088, "Torque profile type", I16, "rw"),
    _var(0x6098, "Homing method", I8, "rw"),
    _array(0x6099, "Homing speeds", HIGHEST, "ro", "Homing speed", U32, "rw", 2,
           names=["Speed during search for switch", "Speed during search for zero"]),
    _var(0x609A, "Homing acceleration", U32, "rw"),
    _var(0x60B0, "Position offset", I32, "rw", True),
    _var(0x60B1, "Velocity offset", I32, "rw", True),
    _var(0x60B2, "Torque offset", I16, "rw", True),
    _record(0x60C2, "Interpolation time period", [(1, "Interpolation time period value", U8, "rw", False),
                                                  (2, "Interpolation time index", I8, "rw", False)]),
    _var(0x60F4, "Following error actual value", I32, "ro", True),
    _var(0x60FD, "Digital inputs", U32, "ro", True),
    _array(0x60FE, "Digital outputs", HIGHEST, "ro", "Digital outputs", U32, "rw", 2,
           names=["Physical outputs", "Bit mask"], pdo=True),
    _var(0x60FF, "Target velocity", I32, "rw", True),
    _var(0x6402, "Motor type", U16, "rw"),
    _var(0x6502, "Supported drive modes", U32, "ro"),
]


def _pdo_pair(n, tx):
    """(communication object, mapping object) of RPDO or TPDO n (1-based)."""
    kind = "TPDO" if tx else "RPDO"
    comm = [(1, "COB-ID used by " + kind, U32, "rw", False), (2, "Transmission type", U8, "rw", False),
            (3, "Inhibit time", U16, "rw", False), (5, "Event timer", U16, "rw", False)]
    if tx:
        comm.append((6, "SYNC start value", U8, "rw", False))
    base = 0x1800 if tx else 0x1400
    return (_record(base + n - 1, "%s %d communication parameter" % (kind, n), comm),
            _array(base + 0x200 + n - 1, "%s %d mapping parameter" % (kind, n), "Number of mapped objects", "rw",
                   "Mapped object", U32, "rw", MAX_MAPPED))


def pdo_objects(rpdos, tpdos):
    """The PDO communication and mapping objects of RPDO 1-rpdos and TPDO 1-tpdos."""
    out = []
    for count, tx in ((rpdos, False), (tpdos, True)):
        for n in range(1, count + 1):
            out.extend(_pdo_pair(n, tx))
    return out


def device_profile(device_type):
    """The profile number of a 0x1000 value (its low 16 bits), or None."""
    return device_type & 0xFFFF if isinstance(device_type, int) and device_type >= 0 else None


def objects(device_type=None, rpdos=DEFAULT_PDOS, tpdos=DEFAULT_PDOS):
    p = device_profile(device_type)
    table = CIA301 + pdo_objects(rpdos, tpdos)
    if p == 401:
        table = table + CIA401
    elif p == 402:
        table = table + CIA402
    return sorted(table, key=lambda o: o[0])


def text(device_type=None, rpdos=DEFAULT_PDOS, tpdos=DEFAULT_PDOS):
    """The standard dictionary as EDS text."""
    p = device_profile(device_type)
    title = "Standard CiA 301 objects" + (" and CiA %d" % p if p in PROFILES else "")
    table = objects(device_type, rpdos, tpdos)
    mandatory = [o for o in table if o[0] in (0x1000, 0x1001, 0x1018)]
    optional = [o for o in table if o not in mandatory]
    lines = ["[FileInfo]", "FileName=standard.eds", "FileVersion=1", "Description=" + title, "",
             "[DeviceInfo]", "VendorName=", "ProductName=" + title, "", ""]
    for section, listed in (("MandatoryObjects", mandatory), ("OptionalObjects", optional)):
        lines.append("[%s]" % section)
        lines.append("SupportedObjects=%d" % len(listed))
        lines += ["%d=0x%04X" % (k + 1, o[0]) for k, o in enumerate(listed)]
        lines.append("")
    for index, name, otype, subs in table:
        lines.append("[%04X]" % index)
        lines.append("ParameterName=" + name)
        lines.append("ObjectType=0x%X" % otype)
        if otype == VAR:
            _, _, dtype, access, pdo = subs[0]
            lines += ["DataType=0x%04X" % dtype, "AccessType=" + access, "PDOMapping=%d" % pdo]
            if index == 0x1000 and p:
                lines.append("DefaultValue=0x%08X" % p)
            lines.append("")
            continue
        lines.append("SubNumber=%d" % len(subs))
        lines.append("")
        for sub, sname, dtype, access, pdo in subs:
            lines += ["[%04Xsub%X]" % (index, sub), "ParameterName=" + sname, "ObjectType=0x7",
                      "DataType=0x%04X" % dtype, "AccessType=" + access, "PDOMapping=%d" % pdo, ""]
    return "\n".join(lines)


_cache = {}


def read(device_type=None, rpdos=DEFAULT_PDOS, tpdos=DEFAULT_PDOS):
    """(Eds, text) of the standard dictionary, cached."""
    p = device_profile(device_type)
    key = (p if p in PROFILES else None, rpdos, tpdos)
    if key not in _cache:
        t = text(device_type if p in PROFILES else None, rpdos, tpdos)
        _cache[key] = (eds_mod.Eds.read("standard.eds", t), t)
    return _cache[key]


def read_all(client, node, eds, progress=None, cancel=None, timeout_ms=1000):
    """Reads the standard dictionary of a device: sub-index 0 of each object
    first, then its sub-indices up to that count; an object the device lacks
    is not read further. Then looks for RPDOs and TPDOs from 5 on until the
    first the device lacks. Returns (Reading, rpdos, tpdos) with the PDO
    counts the device has (at least 4 each, as listed)."""
    from .parameters import Reading, SILENT_LIMIT, TIMEOUT_ABORT, READABLE
    r = Reading(node)
    by_index = {}
    for index, sub, o in eds.items():
        by_index.setdefault(index, []).append((sub, o))
    r.total = len(by_index)
    silent = [0]

    def one(index, sub):
        """True when read; False when refused (r.failed); None when the read stopped."""
        if cancel and cancel():
            r.cancelled = True
            return None
        try:
            res = client.sdo_read(node, index, sub, timeout_ms)
        except DiagError as e:
            if e.kind != "refused" or "more than" not in str(e):
                raise
            r.failed[(index, sub)] = (None, str(e))
            return False
        if res.get("success"):
            r.values[(index, sub)] = bytes.fromhex(res.get("data") or "")
            silent[0] = 0
            return True
        code = res.get("abort_code")
        r.failed[(index, sub)] = (code, abort_text(code) if code not in (None, TIMEOUT_ABORT) else
                                  ("timeout" if code == TIMEOUT_ABORT else res.get("error") or "failed"))
        silent[0] = silent[0] + 1 if code in (None, TIMEOUT_ABORT) else 0
        if silent[0] >= SILENT_LIMIT:
            r.stopped = ("node %d does not answer SDO (%d timeouts in a row); it may be STOPPED or not on the bus"
                         % (node, SILENT_LIMIT))
            return None
        return False

    def read_object(index, otype, subs):
        """subs: [(sub, access, data type)]. False when the device lacks the
        object, None when the read stopped."""
        subs = [(s, a, t) for s, a, t in subs if a in READABLE and t != DOMAIN]
        if not subs:
            return True
        first = one(index, subs[0][0])
        if first is None:
            return None
        if first is False and r.failed[(index, subs[0][0])][0] == NO_OBJECT:
            return False
        last = 255
        if otype in (ARRAY, RECORD) and subs[0][0] == 0 and first:
            last = r.values[(index, 0)][0] if r.values[(index, 0)] else 0
        for s, _, _ in subs[1:]:
            if s > last:
                break
            if one(index, s) is None:
                return None
        return True

    done = 0
    for index in sorted(by_index):
        subs = [(s, o.access, o.data_type) for s, o in by_index[index]]
        if read_object(index, eds.object_types.get(index, VAR), subs) is None:
            return r, DEFAULT_PDOS, DEFAULT_PDOS
        done += 1
        if progress:
            progress(done, r.total)
    counts = []
    for tx in (False, True):
        n = DEFAULT_PDOS
        while n < MAX_PDOS:
            comm, mapping = _pdo_pair(n + 1, tx)
            res = read_object(comm[0], comm[2], [(s, a, t) for s, _, t, a, _ in comm[3]])
            if res is None:
                return r, DEFAULT_PDOS, DEFAULT_PDOS
            if res is False:
                break
            if read_object(mapping[0], mapping[2], [(s, a, t) for s, _, t, a, _ in mapping[3]]) is None:
                return r, DEFAULT_PDOS, DEFAULT_PDOS
            n += 1
        counts.append(n)
    return r, counts[0], counts[1]
