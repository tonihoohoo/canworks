#!/usr/bin/env python3
"""Writes dio16.eds, the device description of the example's I/O module.

DIO-16 is made up for this repository: a compact I/O module following the
CiA 401 generic I/O profile with 16 digital inputs and outputs (two bytes
each), two analogue inputs and outputs, two RPDOs and two TPDOs with writable
mapping that is blank by default (the master writes it), store and restore (0x1010, 0x1011), an EMCY producer, the
configuration date and time (0x1020), a TIME consumer entry (0x1012) and LSS.
Two manufacturer objects give the guide something to read and write over SDO.
Its vendor ID is not one CiA assigns.

    python3 examples/virtual-plant/make_dio16_eds.py > examples/virtual-plant/canopen/dio16.eds
"""

U8, U16, U32, I16, BOOL, VSTR = 0x0005, 0x0006, 0x0007, 0x0003, 0x0001, 0x0009

VENDOR_ID = 0x00F0F0F0
PRODUCT_CODE = 0x00000401
REVISION = 0x00010000

out = []


def w(line=""):
    out.append(line)


def fmt(v):
    return v if isinstance(v, str) else "0x%X" % v if v >= 0 else str(v)


def var(section, name, dtype, access, default=None, pdo=0, low=None, high=None):
    w("[%s]" % section)
    w("ParameterName=%s" % name)
    w("ObjectType=0x7")
    w("DataType=0x%04X" % dtype)
    w("AccessType=%s" % access)
    if default is not None:
        w("DefaultValue=%s" % fmt(default))
    w("PDOMapping=%d" % pdo)
    if low is not None:
        w("LowLimit=%s" % fmt(low))
    if high is not None:
        w("HighLimit=%s" % fmt(high))
    w()


def obj(index, name, otype, subs, numbers=None):
    """subs: list of (name, dtype, access, default, pdo, low, high); sub 0 first.
    numbers: the sub-indices when they are not 0, 1, 2, ..."""
    w("[%04X]" % index)
    w("ParameterName=%s" % name)
    w("ObjectType=0x%X" % otype)
    w("SubNumber=%d" % len(subs))
    w()
    for i, s in zip(numbers or range(len(subs)), subs):
        var("%04Xsub%X" % (index, i), *s)


def array(index, name, entry, dtype, access, default, count=2, pdo=0):
    subs = [("Number of entries", U8, "ro", count)]
    subs += [("%s %d" % (entry, k + 1), dtype, access, default, pdo) for k in range(count)]
    obj(index, name, 0x8, subs)


w("[FileInfo]")
w("FileName=dio16.eds")
w("FileVersion=1")
w("FileRevision=1")
w("EDSVersion=4.0")
w("Description=Made-up 16-channel digital and 2-channel analogue I/O module (CiA 401) for the openplc-canopen example")
w("CreationTime=12:00PM")
w("CreationDate=10-07-2026")
w("CreatedBy=openplc-canopen")
w("ModificationTime=12:00PM")
w("ModificationDate=10-07-2026")
w("ModifiedBy=openplc-canopen")
w()
w("[DeviceInfo]")
w("VendorName=openplc-canopen test devices")
w("VendorNumber=0x%08X" % VENDOR_ID)
w("ProductName=DIO-16 I/O module")
w("ProductNumber=0x%08X" % PRODUCT_CODE)
w("RevisionNumber=0x%08X" % REVISION)
w("OrderCode=DIO-16")
for rate in (10, 20, 50, 125, 250, 500, 800, 1000):
    w("BaudRate_%d=1" % rate)
w("SimpleBootUpMaster=0")
w("SimpleBootUpSlave=1")
w("Granularity=8")
w("DynamicChannelsSupported=0")
w("CompactPDO=0")
w("GroupMessaging=0")
w("NrOfRXPDO=2")
w("NrOfTXPDO=2")
w("LSS_Supported=1")
w()
w("[DummyUsage]")
for i in range(1, 8):
    w("Dummy%04d=%d" % (i, 1 if i >= 5 else 0))
w()
w("[Comments]")
w("Lines=2")
w("Line1=Made-up device for examples/virtual-plant, see its README.md")
w("Line2=16 DI, 16 DO, 2 AI, 2 AO; simulated, outputs loop back to inputs")
w()

mandatory = [0x1000, 0x1001, 0x1018]
optional = [0x1003, 0x1005, 0x1008, 0x1009, 0x100A, 0x100C, 0x100D, 0x1010, 0x1011, 0x1012,
            0x1014, 0x1016, 0x1017, 0x1020, 0x1029, 0x1200, 0x1400, 0x1401, 0x1600, 0x1601,
            0x1800, 0x1801, 0x1A00, 0x1A01,
            0x6000, 0x6200, 0x6401, 0x6411, 0x6423]
manufacturer = [0x2000, 0x2001]

for title, lst in (("MandatoryObjects", mandatory), ("OptionalObjects", optional),
                   ("ManufacturerObjects", manufacturer)):
    w("[%s]" % title)
    w("SupportedObjects=%d" % len(lst))
    for i, index in enumerate(lst):
        w("%d=0x%04X" % (i + 1, index))
    w()

# Communication profile (CiA 301).
var("1000", "Device type", U32, "ro", 0x000F0191)  # CiA 401: DI, DO, AI, AO
var("1001", "Error register", U8, "ro", 0)
obj(0x1018, "Identity object", 0x9, [
    ("Highest sub-index supported", U8, "ro", 4),
    ("Vendor-ID", U32, "ro", "0x%08X" % VENDOR_ID),
    ("Product code", U32, "ro", "0x%08X" % PRODUCT_CODE),
    ("Revision number", U32, "ro", "0x%08X" % REVISION),
    ("Serial number", U32, "ro", None),
])
obj(0x1003, "Pre-defined error field", 0x8,
    [("Number of errors", U8, "rw", 0)] + [("Standard error field", U32, "ro", None)] * 8)
var("1005", "COB-ID SYNC", U32, "rw", 0x80)
var("1008", "Manufacturer device name", VSTR, "const", "DIO-16")
var("1009", "Manufacturer hardware version", VSTR, "const", "1.0")
var("100A", "Manufacturer software version", VSTR, "const", "1.0")
var("100C", "Guard time", U16, "rw", 0)
var("100D", "Life time factor", U8, "rw", 0)
obj(0x1010, "Store parameters", 0x8, [
    ("Highest sub-index supported", U8, "ro", 3),
    ("Save all parameters", U32, "rw", None),
    ("Save communication parameters", U32, "rw", None),
    ("Save application parameters", U32, "rw", None),
])
obj(0x1011, "Restore default parameters", 0x8, [
    ("Highest sub-index supported", U8, "ro", 3),
    ("Restore all default parameters", U32, "rw", None),
    ("Restore communication default parameters", U32, "rw", None),
    ("Restore application default parameters", U32, "rw", None),
])
var("1012", "COB-ID time stamp object", U32, "rw", 0x100)
var("1014", "COB-ID EMCY", U32, "rw", "$NODEID+0x80")
obj(0x1016, "Consumer heartbeat time", 0x8, [
    ("Highest sub-index supported", U8, "ro", 1),
    ("Consumer heartbeat time", U32, "rw", 0),
])
var("1017", "Producer heartbeat time", U16, "rw", 0)
obj(0x1020, "Verify configuration", 0x8, [
    ("Highest sub-index supported", U8, "ro", 2),
    ("Configuration date", U32, "rw", 0),
    ("Configuration time", U32, "rw", 0),
])
obj(0x1029, "Error behavior", 0x8, [
    ("Highest sub-index supported", U8, "const", 1),
    ("Communication error", U8, "rw", 0),
])
obj(0x1200, "SDO server parameter", 0x9, [
    ("Highest sub-index supported", U8, "const", 2),
    ("COB-ID client to server", U32, "ro", "$NODEID+0x600"),
    ("COB-ID server to client", U32, "ro", "$NODEID+0x580"),
])
# Two RPDOs and two TPDOs with the CiA default COB-IDs and no mapped
# objects: like a module whose mapping was never configured, it sends and
# takes nothing until the master writes a mapping.
for n, cob in enumerate((0x200, 0x300)):
    obj(0x1400 + n, "RPDO %d communication parameter" % (n + 1), 0x9, [
        ("Highest sub-index supported", U8, "const", 2),
        ("COB-ID used by RPDO", U32, "rw", "$NODEID+0x%X" % cob),
        ("Transmission type", U8, "rw", 0xFF),
    ])
    subs = [("Number of mapped objects", U8, "rw", 0)]
    subs += [("Mapped object %d" % (k + 1), U32, "rw", 0) for k in range(8)]
    obj(0x1600 + n, "RPDO %d mapping parameter" % (n + 1), 0x9, subs)
for n, cob in enumerate((0x180, 0x280)):
    obj(0x1800 + n, "TPDO %d communication parameter" % (n + 1), 0x9, [
        ("Highest sub-index supported", U8, "const", 5),
        ("COB-ID used by TPDO", U32, "rw", "$NODEID+0x%X" % cob),
        ("Transmission type", U8, "rw", 0xFF),
        ("Inhibit time", U16, "rw", 100),
        ("Event timer", U16, "rw", 0),
    ], numbers=[0, 1, 2, 3, 5])  # sub 4 is reserved
    subs = [("Number of mapped objects", U8, "rw", 0)]
    subs += [("Mapped object %d" % (k + 1), U32, "rw", 0) for k in range(8)]
    obj(0x1A00 + n, "TPDO %d mapping parameter" % (n + 1), 0x9, subs)

# Manufacturer objects.
var("2000", "Input filter time", U16, "rw", 5, low=0, high=1000)
var("2001", "Operating hours", U32, "ro", 1200)

# Device profile (CiA 401).
array(0x6000, "Read input 8-bit", "Read input 8-bit", U8, "ro", 0, pdo=1)
array(0x6200, "Write output 8-bit", "Write output 8-bit", U8, "rww", 0, pdo=1)
array(0x6401, "Read analogue input 16-bit", "Read analogue input", I16, "ro", "0", pdo=1)
array(0x6411, "Write analogue output 16-bit", "Write analogue output", I16, "rww", "0", pdo=1)
var("6423", "Analogue input global interrupt enable", BOOL, "rw", 0)

print("\n".join(out))
