#!/usr/bin/env python3
"""Writes the PDO link fixture EDS files (canopen-pdo-links):

link-io.eds        a made-up analog I/O module: inputs 0x6401:1-2 (INTEGER16,
                   ro) in TPDO 1's default mapping, outputs 0x6411:1-2
                   (INTEGER16, rww), 0x2000 UNSIGNED16, 0x2001 UNSIGNED8 and
                   0x2003 UNSIGNED32 (rww) for consumers, 0x2002 INTEGER16 (ro,
                   mappable); RPDOs 1-4 and TPDOs 1-2 with writable
                   parameters, event-driven by default; two heartbeat consumer
                   entries (0x1016), error behaviour (0x1029), Dummy0002-0007.
link-io-small.eds  the same with one heartbeat consumer entry.

Run from this folder: python3 make_link_eds.py
"""

import os

HERE = os.path.dirname(os.path.abspath(__file__))


def var(index, name, dtype, access, default, mapping=0, sub=None):
    head = "[%X]" % index if sub is None else "[%Xsub%X]" % (index, sub)
    return ("%s\nParameterName=%s\nDataType=0x%04X\nAccessType=%s\nDefaultValue=%s\nPDOMapping=%d\n"
            % (head, name, dtype, access, default, mapping))


def record(index, name, subs, object_type=0x09):
    out = "[%X]\nSubNumber=%d\nParameterName=%s\nObjectType=0x%02X\n\n" % (index, len(subs), name, object_type)
    out += "\n".join(var(index, *s[1:], sub=s[0]) for s in subs)
    return out


def eds(name, heartbeat_entries):
    objects = []
    optional = []

    def add(index, text):
        optional.append(index)
        objects.append(text)

    add(0x1014, var(0x1014, "COB-ID EMCY", 0x0007, "rw", "$NODEID+0x80"))
    add(0x1016, record(0x1016, "Consumer heartbeat time",
                       [(0, "Highest sub-index supported", 0x0005, "const", heartbeat_entries)] +
                       [(k, "Consumer heartbeat time %d" % k, 0x0007, "rw", "0x00000000")
                        for k in range(1, heartbeat_entries + 1)], 0x08))
    add(0x1017, var(0x1017, "Producer heartbeat time", 0x0006, "rw", 0))
    for n in range(4):
        add(0x1400 + n, record(0x1400 + n, "RPDO communication parameter", [
            (0, "Highest sub-index supported", 0x0005, "const", 5),
            (1, "COB-ID used by RPDO", 0x0007, "rw", "$NODEID+0x%X" % (0x200 + 0x100 * n)),
            (2, "Transmission type", 0x0005, "rw", "0xFF"),
            (3, "Inhibit time", 0x0006, "rw", 0),
            (5, "Event timer", 0x0006, "rw", 0)]))
    for n in range(4):
        default = ["0x64110110", "0x64110210"] if n == 0 else []
        add(0x1600 + n, record(0x1600 + n, "RPDO mapping parameter",
                               [(0, "Number of mapped application objects in PDO", 0x0005, "rw", len(default))] +
                               [(k, "Application object %d" % k, 0x0007, "rw",
                                 default[k - 1] if k <= len(default) else "0x00000000") for k in range(1, 5)]))
    for n in range(2):
        add(0x1800 + n, record(0x1800 + n, "TPDO communication parameter", [
            (0, "Highest sub-index supported", 0x0005, "const", 5),
            (1, "COB-ID used by TPDO", 0x0007, "rw", "$NODEID+0x%X" % (0x180 + 0x100 * n)),
            (2, "Transmission type", 0x0005, "rw", "0xFF"),
            (3, "Inhibit time", 0x0006, "rw", 0),
            (5, "Event timer", 0x0006, "rw", 0)]))
    for n in range(2):
        default = ["0x64010110", "0x64010210"] if n == 0 else ["0x20020010"]
        add(0x1A00 + n, record(0x1A00 + n, "TPDO mapping parameter",
                               [(0, "Number of mapped application objects in PDO", 0x0005, "rw", len(default))] +
                               [(k, "Application object %d" % k, 0x0007, "rw",
                                 default[k - 1] if k <= len(default) else "0x00000000") for k in range(1, 5)]))
    add(0x1029, record(0x1029, "Error behavior", [
        (0, "Highest sub-index supported", 0x0005, "const", 1),
        (1, "Communication error", 0x0005, "rw", 0)], 0x08))
    add(0x2000, var(0x2000, "Setpoint UNSIGNED16", 0x0006, "rww", 0, 1))
    add(0x2001, var(0x2001, "Setpoint UNSIGNED8", 0x0005, "rww", 0, 1))
    add(0x2002, var(0x2002, "Status INTEGER16", 0x0003, "ro", 0, 1))
    add(0x2003, var(0x2003, "Setpoint UNSIGNED32", 0x0007, "rww", 0, 1))
    add(0x6401, record(0x6401, "Read analog input 16-bit", [
        (0, "Highest sub-index supported", 0x0005, "const", 2),
        (1, "Analog input 1", 0x0003, "ro", 0, 1),
        (2, "Analog input 2", 0x0003, "ro", 0, 1)], 0x08))
    add(0x6411, record(0x6411, "Write analog output 16-bit", [
        (0, "Highest sub-index supported", 0x0005, "const", 2),
        (1, "Analog output 1", 0x0003, "rww", 0, 1),
        (2, "Analog output 2", 0x0003, "rww", 0, 1)], 0x08))
    pairs = sorted(zip(optional, objects))
    optional = [i for i, _ in pairs]
    objects = [o for _, o in pairs]
    mandatory = [0x1000, 0x1001, 0x1018]
    head = """; PDO link fixture (canopen-pdo-links), written by make_link_eds.py: a made-up
; analog I/O module. Do not edit; change make_link_eds.py and run it again.

[FileInfo]
FileName=%s
FileVersion=1
FileRevision=0
EDSVersion=4.0
Description=Made-up analog I/O module for PDO link tests
CreationTime=12:00PM
CreationDate=10-10-2026
CreatedBy=canworks
ModificationTime=12:00PM
ModificationDate=10-10-2026
ModifiedBy=canworks

[DeviceInfo]
VendorName=canworks test fixtures
VendorNumber=0x00000000
ProductName=link-io
ProductNumber=0x00000000
RevisionNumber=0x00000000
OrderCode=
BaudRate_10=1
BaudRate_20=1
BaudRate_50=1
BaudRate_125=1
BaudRate_250=1
BaudRate_500=1
BaudRate_800=1
BaudRate_1000=1
SimpleBootUpMaster=0
SimpleBootUpSlave=1
Granularity=8
DynamicChannelsSupported=0
GroupMessaging=0
NrOfRxPDO=4
NrOfTxPDO=2
LSS_Supported=0

[DummyUsage]
Dummy0001=0
Dummy0002=1
Dummy0003=1
Dummy0004=1
Dummy0005=1
Dummy0006=1
Dummy0007=1

[Comments]
Lines=0

""" % name
    out = head
    out += "[MandatoryObjects]\nSupportedObjects=%d\n" % len(mandatory)
    out += "".join("%d=0x%04X\n" % (i + 1, x) for i, x in enumerate(mandatory)) + "\n"
    out += var(0x1000, "Device type", 0x0007, "ro", "0x00000000") + "\n"
    out += var(0x1001, "Error register", 0x0005, "ro", "0x00", 1) + "\n"
    out += record(0x1018, "Identity object", [
        (0, "Highest sub-index supported", 0x0005, "const", 4),
        (1, "Vendor-ID", 0x0007, "ro", "0x00000000"),
        (2, "Product code", 0x0007, "ro", "0x00000000"),
        (3, "Revision number", 0x0007, "ro", "0x00000000"),
        (4, "Serial number", 0x0007, "ro", "0x00000000")]) + "\n"
    maker = [i for i in optional if 0x2000 <= i <= 0x5FFF]
    optional = [i for i in optional if i not in maker]
    out += "[OptionalObjects]\nSupportedObjects=%d\n" % len(optional)
    out += "".join("%d=0x%04X\n" % (i + 1, x) for i, x in enumerate(optional)) + "\n"
    out += "\n".join(o for i, o in pairs if i not in maker)
    out += "\n[ManufacturerObjects]\nSupportedObjects=%d\n" % len(maker)
    out += "".join("%d=0x%04X\n" % (i + 1, x) for i, x in enumerate(maker)) + "\n"
    out += "\n".join(o for i, o in pairs if i in maker)
    return out


def main():
    for name, entries in (("link-io.eds", 2), ("link-io-small.eds", 1)):
        with open(os.path.join(HERE, name), "w", encoding="utf-8", newline="\n") as f:
            f.write(eds(name, entries))


if __name__ == "__main__":
    main()
