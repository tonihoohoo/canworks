"""A strict CiA 306 check of the EDS and DCF files canworks writes itself
(the slave EDS generator, the DCF export). Lely's lint, which the bridge
runs, allow-lists keys but requires none and reads REAL values only as hex
bit patterns; this check asks for what CiA 306 lists and what other masters'
tools expect. It never runs on vendor files canworks only reads.

    findings = check(text)                 # [Finding(section, key, message)]
    findings = check(text, only=keep)      # keep(section, key) -> bool

Sections and keys compare case-insensitively, as CiA 306 says.
"""

import re

MAX_LINE = 255
MAX_SUPPORTED_OBJECTS = 0xFFFF  # checked before the list is walked
MAX_PRODUCT_NAME = 243
MAX_NODE_NAME = 246
MANDATORY = (0x1000, 0x1001, 0x1018)
LISTS = ("MandatoryObjects", "OptionalObjects", "ManufacturerObjects")
FILE_INFO = ("FileName", "FileVersion", "FileRevision", "EDSVersion", "Description", "CreationTime",
             "CreationDate", "CreatedBy")
DEVICE_INFO = ("VendorName", "VendorNumber", "ProductName", "ProductNumber", "RevisionNumber", "OrderCode",
               "BaudRate_10", "BaudRate_20", "BaudRate_50", "BaudRate_125", "BaudRate_250", "BaudRate_500",
               "BaudRate_800", "BaudRate_1000", "SimpleBootUpMaster", "SimpleBootUpSlave", "Granularity",
               "DynamicChannelsSupported", "GroupMessaging", "NrOfRXPDO", "NrOfTXPDO", "LSS_Supported")
DATES = ("CreationDate", "ModificationDate")
TIMES = ("CreationTime", "ModificationTime")
REALS = (0x0008, 0x0011)
VALUE_KEYS = ("DefaultValue", "ParameterValue", "LowLimit", "HighLimit")
# Standard objects canworks writes itself, with their CiA 301 default.
CIA301_DEFAULTS = {("1003sub0", "DefaultValue"): 0}

_DATE = re.compile(r"^(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])-\d{4}$")
_TIME = re.compile(r"^(0\d|1[0-2]):[0-5]\d(AM|PM)$")
_OBJECT = re.compile(r"^([0-9A-Fa-f]{4})$")
_SUB = re.compile(r"^([0-9A-Fa-f]{4})sub([0-9A-Fa-f]{1,2})$", re.I)


class Finding:
    def __init__(self, section, key, message):
        self.section, self.key, self.message = section, key, message

    def where(self):
        return "[%s]%s" % (self.section, " " + self.key if self.key else "")

    def __str__(self):
        return "%s: %s" % (self.where(), self.message)

    def __repr__(self):
        return "Finding(%r)" % str(self)


def parse(text):
    """{section (lower case): (name as written, {key (lower case): (name, value)})}
    and the text's lines."""
    sections = {}
    current = None
    lines = text.splitlines()
    for line in lines:
        s = line.strip()
        if not s or s.startswith(";"):
            continue
        if s.startswith("[") and s.endswith("]"):
            name = s[1:-1].strip()
            current = sections.setdefault(name.lower(), (name, {}))[1]
            continue
        if current is not None and "=" in s:
            k, v = s.split("=", 1)
            current[k.strip().lower()] = (k.strip(), v.strip())
    return sections, lines


def _int(value):
    try:
        return int(value, 0)
    except (TypeError, ValueError):
        return None


def check(text, only=None, defaults=True):
    """The findings in an EDS or DCF text; with `only`, those for which
    only(section, key) is true (section and key as CiA 306 names them).
    `defaults` checks the CiA 301 defaults of the standard objects canworks
    writes itself (off for a DCF, whose objects come from a vendor EDS)."""
    sections, lines = parse(text)
    out = []

    def add(section, key, message):
        if only is None or only(section, key):
            out.append(Finding(section, key, message))

    def get(section, key):
        return sections.get(section.lower(), (None, {}))[1].get(key.lower(), (None, None))[1]

    # Text: printable ASCII, lines of at most 255 characters (CiA 306 3.1).
    current = None
    for line in lines:
        s = line.strip()
        if s.startswith("[") and s.endswith("]"):
            current = s[1:-1].strip()
        key = s.split("=", 1)[0].strip() if "=" in s and not s.startswith(";") else None
        if any(not (32 <= ord(c) < 127 or c == "\t") for c in line):
            add(current or "", key, "only printable ASCII is allowed (CiA 306)")
        if len(line) > MAX_LINE:
            add(current or "", key, "line is %d characters, CiA 306 allows %d" % (len(line), MAX_LINE))

    # [FileInfo] and [DeviceInfo] keys (CiA 306 4.3, 4.4).
    for section, keys in (("FileInfo", FILE_INFO), ("DeviceInfo", DEVICE_INFO)):
        if section.lower() not in sections:
            add(section, None, "section missing (CiA 306)")
            continue
        for k in keys:
            if get(section, k) in (None, ""):
                add(section, k, "missing (CiA 306)")
    for k in DATES:
        v = get("FileInfo", k)
        if v and not _DATE.match(v):
            add("FileInfo", k, "%r is not a CiA 306 date (mm-dd-yyyy)" % v)
    for k in TIMES:
        v = get("FileInfo", k)
        if v and not _TIME.match(v):
            add("FileInfo", k, "%r is not a CiA 306 time (hh:mm followed by AM or PM)" % v)
    name = get("DeviceInfo", "ProductName")
    if name and len(name) > MAX_PRODUCT_NAME:
        add("DeviceInfo", "ProductName", "is %d characters, CiA 306 allows %d" % (len(name), MAX_PRODUCT_NAME))
    name = get("DeviceComissioning", "NodeName")
    if name is not None and len(name) > MAX_NODE_NAME:
        add("DeviceComissioning", "NodeName", "is %d characters, CiA 306 allows %d" % (len(name), MAX_NODE_NAME))

    # Object lists (CiA 306 4.5): counts, numbering, order, sections.
    listed = set()
    for lst in LISTS:
        if lst.lower() not in sections:
            if lst == "MandatoryObjects":
                add(lst, None, "section missing (CiA 306)")
            continue
        count = _int(get(lst, "SupportedObjects"))
        if count is None:
            add(lst, "SupportedObjects", "missing or not a number")
            continue
        if count > MAX_SUPPORTED_OBJECTS:
            add(lst, "SupportedObjects", "%d is above %d, more objects than an object dictionary holds"
                % (count, MAX_SUPPORTED_OBJECTS))
            continue
        indices = []
        for n in range(1, count + 1):
            v = _int(get(lst, str(n)))
            if v is None:
                add(lst, str(n), "missing: SupportedObjects is %d" % count)
                continue
            indices.append(v)
            if "%04x" % v not in sections:
                add(lst, str(n), "object 0x%04X has no section" % v)
        extra = [k for k in sections[lst.lower()][1] if k.isdigit() and int(k) > count]
        for k in extra:
            add(lst, k, "entry beyond SupportedObjects=%d" % count)
        if indices != sorted(indices):
            add(lst, None, "objects are not in ascending order")
        if lst == "MandatoryObjects" and sorted(indices) != list(MANDATORY):
            add(lst, None, "must list exactly 0x1000, 0x1001 and 0x1018 (CiA 306)")
        listed.update(indices)
    for sec, (written, _) in sections.items():
        m = _OBJECT.match(sec)
        if m and int(m.group(1), 16) not in listed:
            add(written, None, "object is in no object list")

    # Values: REALs in decimal, standard defaults.
    for sec, (written, keys) in sections.items():
        m = _OBJECT.match(sec) or _SUB.match(sec)
        if not m:
            continue
        data_type = _int(keys.get("datatype", (None, None))[1])
        if data_type in REALS:
            for k in VALUE_KEYS:
                v = keys.get(k.lower(), (None, None))[1]
                if v and v.lower().startswith(("0x", "-0x", "+0x")):
                    add(written, k, "REAL value %s is a hex bit pattern; CiA 306 writes REALs as decimal numbers"
                        % v)
    for (sec, k), want in CIA301_DEFAULTS.items() if defaults else ():
        v = get(sec, k)
        if v is not None and _int(v) != want:
            add(sections[sec.lower()][0], k, "is %s; CiA 301 gives %d" % (v, want))
    return out
