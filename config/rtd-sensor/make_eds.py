#!/usr/bin/env python3
"""Writes rtd8.eds, the device description of the simulated RTD module.

The module is made up for this repository: an 8-channel resistance temperature
input module following the CiA 404 measuring-device profile (analog inputs in
0x6110-0x7135), four TPDOs with writable mapping, no RPDOs, plus a few
manufacturer objects in 0x2000-0x2002. Its vendor ID is not one CiA assigns.

    python3 config/rtd-sensor/make_eds.py > config/rtd-sensor/rtd8.eds
"""

import sys

CHANNELS = 8
U8, U16, U32, I16, REAL32, VSTR = 0x0005, 0x0006, 0x0007, 0x0003, 0x0008, 0x0009

VENDOR_ID = 0x00F0F0F0
PRODUCT_CODE = 0x00000404
REVISION = 0x00010003

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


def channel_array(index, name, dtype, access, default, pdo=0, low=None, high=None):
    """One CiA 404 array, sub-entries named AI<channel>_<object name> (channel from 0)."""
    sub_name = name[3:].replace(" ", "_")
    subs = [("Number Of Entries", U8, "ro", CHANNELS)]
    subs += [("AI%d_%s" % (ch, sub_name), dtype, access, default, pdo, low, high) for ch in range(CHANNELS)]
    obj(index, name, 0x8, subs)


w("[FileInfo]")
w("FileName=rtd8.eds")
w("FileVersion=1")
w("FileRevision=1")
w("EDSVersion=4.0")
w("Description=Simulated 8-channel RTD input module (CiA 404) for openplc-canopen tests")
w("CreationTime=12:00PM")
w("CreationDate=10-06-2026")
w("CreatedBy=openplc-canopen")
w("ModificationTime=12:00PM")
w("ModificationDate=10-06-2026")
w("ModifiedBy=openplc-canopen")
w()
w("[DeviceInfo]")
w("VendorName=openplc-canopen test devices")
w("VendorNumber=0x%08X" % VENDOR_ID)
w("ProductName=RTD-8 temperature input module")
w("ProductNumber=0x%08X" % PRODUCT_CODE)
w("RevisionNumber=0x%08X" % REVISION)
w("OrderCode=RTD-8")
for rate in (10, 20, 50, 125, 250, 500, 800, 1000):
    w("BaudRate_%d=1" % rate)
w("SimpleBootUpMaster=0")
w("SimpleBootUpSlave=1")
w("Granularity=8")
w("DynamicChannelsSupported=0")
w("CompactPDO=0")
w("GroupMessaging=0")
w("NrOfRXPDO=0")
w("NrOfTXPDO=4")
w("LSS_Supported=1")
w()
w("[DummyUsage]")
for i in range(1, 8):
    w("Dummy%04d=%d" % (i, 1 if i >= 5 else 0))
w()
w("[Comments]")
w("Lines=2")
w("Line1=Simulated device, see config/rtd-sensor/README.md")
w("Line2=8 resistance temperature inputs, values in 0.1 degC")
w()

mandatory = [0x1000, 0x1001, 0x1018]
optional = [0x1003, 0x1005, 0x1007, 0x1008, 0x1009, 0x100A, 0x100C, 0x100D, 0x1010, 0x1011,
            0x1014, 0x1017, 0x1029, 0x1200, 0x1800, 0x1801, 0x1802, 0x1803,
            0x1A00, 0x1A01, 0x1A02, 0x1A03, 0x1F51,
            0x6110, 0x6112, 0x6126, 0x6127, 0x6131, 0x6132, 0x6150,
            0x7100, 0x7130, 0x7133, 0x7134, 0x7135]
manufacturer = [0x2000, 0x2001, 0x2002]

for title, lst in (("MandatoryObjects", mandatory), ("OptionalObjects", optional),
                   ("ManufacturerObjects", manufacturer)):
    w("[%s]" % title)
    w("SupportedObjects=%d" % len(lst))
    for i, index in enumerate(lst):
        w("%d=0x%04X" % (i + 1, index))
    w()

# Communication profile (CiA 301).
var("1000", "Device type", U32, "ro", 0x00040194)
var("1001", "Error register", U8, "ro", 0)
obj(0x1018, "Identity object", 0x9, [
    ("Highest sub-index supported", U8, "ro", 4),
    ("Vendor-ID", U32, "ro", "0x%08X" % VENDOR_ID),
    ("Product code", U32, "ro", "0x%08X" % PRODUCT_CODE),
    ("Revision number", U32, "ro", "0x%08X" % REVISION),
    ("Serial number", U32, "ro", None),
])
obj(0x1003, "Pre-defined error field", 0x8,
    [("Number of errors", U8, "rw", 0)] + [("Standard error field", U32, "ro", None)] * 10)
var("1005", "COB-ID SYNC", U32, "rw", 0x80)
var("1007", "Synchronous window length", U32, "rw", 0)
var("1008", "Manufacturer device name", VSTR, "const", "RTD-8")
var("1009", "Manufacturer hardware version", VSTR, "const", "1.0")
var("100A", "Manufacturer software version", VSTR, "const", "1.0")
var("100C", "Guard time", U16, "rw", 0)
var("100D", "Life time factor", U8, "rw", 0)
obj(0x1010, "Store parameters", 0x8, [
    ("Highest sub-index supported", U8, "ro", 1),
    ("Save all parameters", U32, "rw", None),
])
obj(0x1011, "Restore default parameters", 0x8, [
    ("Highest sub-index supported", U8, "ro", 1),
    ("Restore all default parameters", U32, "rw", None),
])
var("1014", "COB-ID EMCY", U32, "rw", "$NODEID+0x80")
var("1017", "Producer heartbeat time", U16, "rw", 0)
obj(0x1029, "Error behavior", 0x8, [
    ("Highest sub-index supported", U8, "const", 1),
    ("Communication error", U8, "rw", 0),
])
obj(0x1200, "SDO server parameter", 0x9, [
    ("Highest sub-index supported", U8, "const", 2),
    ("COB-ID client to server", U32, "ro", "$NODEID+0x600"),
    ("COB-ID server to client", U32, "ro", "$NODEID+0x580"),
])
for n in range(4):
    obj(0x1800 + n, "TPDO %d communication parameter" % (n + 1), 0x9, [
        ("Highest sub-index supported", U8, "const", 5),
        ("COB-ID used by TPDO", U32, "rw", "$NODEID+0x%X" % (0x180 + 0x100 * n)),
        ("Transmission type", U8, "rw", 0xFF),
        ("Inhibit time", U16, "rw", 500),
        ("Event timer", U16, "rw", 0),
    ], numbers=[0, 1, 2, 3, 5])  # sub 4 is reserved
for n in range(4):
    subs = [("Number of mapped objects", U8, "rw", 4)]
    for k in range(4):
        ch = 2 * n + k // 2 + 1
        if k % 2 == 0:
            subs.append(("Mapped object %d" % (k + 1), U32, "rw", 0x71300010 | (ch << 8)))
        else:
            subs.append(("Mapped object %d" % (k + 1), U32, "rw", 0x61500008 | (ch << 8)))
    subs += [("Mapped object %d" % (k + 1), U32, "rw", 0) for k in range(4, 8)]
    obj(0x1A00 + n, "TPDO %d mapping parameter" % (n + 1), 0x9, subs)
obj(0x1F51, "Program control", 0x8, [
    ("Highest sub-index supported", U8, "ro", 1),
    ("Program 1", U8, "rw", None),
])

# Device profile (CiA 404 analog inputs).
channel_array(0x6110, "AI Sensor Type", U16, "rw", 30, low=30, high=33)
channel_array(0x6112, "AI Operation Mode", U8, "rw", 0, low=0, high=1)
channel_array(0x6126, "AI Scaling Factor", REAL32, "rw", "1")
channel_array(0x6127, "AI Scaling Offset", REAL32, "rw", "0")
channel_array(0x6131, "AI Physical Unit PV", U32, "rw", 0x002D0000)
channel_array(0x6132, "AI Decimal Digits PV", U8, "rw", 1, low=0, high=1)
channel_array(0x6150, "AI Status", U8, "ro", 0, pdo=1)
channel_array(0x7100, "AI Input FV", I16, "ro", "0", pdo=1)
channel_array(0x7130, "AI Input PV", I16, "ro", "0", pdo=1)
channel_array(0x7133, "AI Interrupt Delta Input PV", I16, "rw", "10")
channel_array(0x7134, "AI Interrupt Lower Limit Input PV", I16, "rw", "-200", low="-200", high="600")
channel_array(0x7135, "AI Interrupt Upper Limit Input PV", I16, "rw", "600", low="-200", high="600")

# Manufacturer objects.
obj(0x2000, "Boot options", 0x9, [
    ("Highest sub-index supported", U8, "ro", 2),
    ("Start without master", U8, "rw", 0),
    ("Start delay ms", U16, "rw", 500),
])
obj(0x2001, "Device monitor", 0x8, [
    ("Highest sub-index supported", U8, "ro", 2),
    ("Board temperature", I16, "ro", None),
    ("Supply voltage", I16, "ro", None),
])
obj(0x2002, "Power fail options", 0x9, [
    ("Highest sub-index supported", U8, "ro", 1),
    ("Power fail EMCY enable", U8, "rw", 1),
])

sys.stdout.write("\n".join(out).rstrip("\n") + "\n")
