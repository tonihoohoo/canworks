#!/usr/bin/env python3
"""Writes the two made-up CiA 402 drive EDS files the tests use.

servo-drive.eds  A drive with writable PDO mapping, 0x1020 (configuration date
                 and time) and 0x1010:1 (save all parameters). Its 0x1018 has
                 no values, as on drives that report their identity from
                 firmware. Two limit-only lint findings outside the
                 communication objects: LowLimit=0xFFFF on INTEGER16 0x60C0
                 and LowLimit=0xFD on INTEGER8 0x60C2 sub 2.
fixed-drive.eds  A drive whose PDO mappings and COB-IDs are all read-only,
                 with node guarding and no heartbeat (no 0x1017). RPDO 2 maps
                 0x2301:1 (UNSIGNED8) and 0x2301:2 (INTEGER32). One
                 limit-only lint finding: HighLimit=0xFF on INTEGER8 0x6061.

Neither describes a real product; the vendor IDs are not ones CiA assigns.

    python3 test/fixtures/eds/drives/make_drives.py test/fixtures/eds/drives
"""

import os
import sys

U8, U16, U32, I8, I16, I32, VSTR = 0x0005, 0x0006, 0x0007, 0x0002, 0x0003, 0x0004, 0x0009


class Eds:
    def __init__(self):
        self.out = []

    def w(self, line=""):
        self.out.append(line)

    def var(self, section, name, dtype, access, default=None, pdo=0, low=None, high=None):
        self.w("[%s]" % section)
        self.w("ParameterName=%s" % name)
        self.w("ObjectType=0x7")
        self.w("DataType=0x%04X" % dtype)
        self.w("AccessType=%s" % access)
        if default is not None:
            self.w("DefaultValue=%s" % default)
        self.w("PDOMapping=%d" % pdo)
        if low is not None:
            self.w("LowLimit=%s" % low)
        if high is not None:
            self.w("HighLimit=%s" % high)
        self.w()

    def obj(self, index, name, otype, subs):
        """subs: list of (name, dtype, access, default, pdo, low, high) from sub 0."""
        self.w("[%04X]" % index)
        self.w("ParameterName=%s" % name)
        self.w("ObjectType=0x%X" % otype)
        self.w("SubNumber=%d" % len(subs))
        self.w()
        for i, s in enumerate(subs):
            self.var("%04Xsub%X" % (index, i), *s)

    def header(self, file_name, description, vendor, vendor_id, product, product_code, rx, tx):
        self.w("[FileInfo]")
        self.w("FileName=%s" % file_name)
        self.w("FileVersion=1")
        self.w("FileRevision=1")
        self.w("EDSVersion=4.0")
        self.w("Description=%s" % description)
        self.w("CreationTime=12:00PM")
        self.w("CreationDate=10-06-2026")
        self.w("CreatedBy=openplc-canopen")
        self.w("ModificationTime=12:00PM")
        self.w("ModificationDate=10-06-2026")
        self.w("ModifiedBy=openplc-canopen")
        self.w()
        self.w("[DeviceInfo]")
        self.w("VendorName=%s" % vendor)
        self.w("VendorNumber=0x%08X" % vendor_id)
        self.w("ProductName=%s" % product)
        self.w("ProductNumber=0x%08X" % product_code)
        self.w("RevisionNumber=0x00010000")
        self.w("OrderCode=%s" % product)
        for rate in (10, 20, 50, 125, 250, 500, 800, 1000):
            self.w("BaudRate_%d=1" % rate)
        self.w("SimpleBootUpMaster=0")
        self.w("SimpleBootUpSlave=1")
        self.w("Granularity=8")
        self.w("DynamicChannelsSupported=0")
        self.w("CompactPDO=0")
        self.w("GroupMessaging=0")
        self.w("NrOfRXPDO=%d" % rx)
        self.w("NrOfTXPDO=%d" % tx)
        self.w("LSS_Supported=1")
        self.w()
        self.w("[DummyUsage]")
        for i in range(1, 8):
            self.w("Dummy%04d=0" % i)
        self.w()
        self.w("[Comments]")
        self.w("Lines=1")
        self.w("Line1=Made-up test device, see test/fixtures/eds/drives/make_drives.py")
        self.w()

    def lists(self, mandatory, optional, manufacturer):
        for title, lst in (("MandatoryObjects", mandatory), ("OptionalObjects", optional),
                           ("ManufacturerObjects", manufacturer)):
            self.w("[%s]" % title)
            self.w("SupportedObjects=%d" % len(lst))
            for i, index in enumerate(lst):
                self.w("%d=0x%04X" % (i + 1, index))
            self.w()

    def text(self):
        return "\n".join(self.out).rstrip("\n") + "\n"


def pdo_comm(e, index, name, cob, access):
    e.obj(index, name, 0x9, [
        ("Highest sub-index supported", U8, "ro", "2"),
        ("COB-ID", U32, access, cob),
        ("Transmission type", U8, "rw", "0xFF"),
    ])


def pdo_map(e, index, name, entries, access, size=8):
    subs = [("Number of mapped objects", U8, access, str(len(entries)), 0, None if access == "ro" else "0",
             None if access == "ro" else str(size))]
    for k in range(size if access == "rw" else len(entries)):
        subs.append(("Mapped object %d" % (k + 1), U32, access, "0x%08X" % (entries[k] if k < len(entries) else 0)))
    e.obj(index, name, 0x9, subs)


def drive_402(e, signed_limit_quirks):
    """The CiA 402 objects both drives have."""
    e.var("6040", "Controlword", U16, "rww", "0x0000", pdo=1)
    e.var("6041", "Statusword", U16, "ro", "0x0000", pdo=1)
    e.var("6060", "Modes of operation", I8, "rw", "0", pdo=1)
    if signed_limit_quirks == "fixed":
        e.var("6061", "Modes of operation display", I8, "ro", "1", low="0x00", high="0xFF")
    else:
        e.var("6061", "Modes of operation display", I8, "ro", "0", pdo=1)
    e.var("6064", "Position actual value", I32, "ro", "0", pdo=1)
    e.var("606C", "Velocity actual value", I32, "ro", "0", pdo=1)
    e.var("607A", "Target position", I32, "rww", "0", pdo=1)
    e.var("60FF", "Target velocity", I32, "rww", "0", pdo=1)


def servo_drive():
    e = Eds()
    e.header("servo-drive.eds", "Made-up CiA 402 servo drive with writable PDO mapping (test fixture)",
             "openplc-canopen test devices", 0x00F0F0F1, "Servo drive SD-1", 0x00000402, 4, 4)
    params = list(range(0x2100, 0x2140))
    e.lists([0x1000, 0x1001, 0x1018],
            [0x1005, 0x1008, 0x100C, 0x100D, 0x1010, 0x1011, 0x1014, 0x1017, 0x1020, 0x1200]
            + list(range(0x1400, 0x1404)) + list(range(0x1600, 0x1604))
            + list(range(0x1800, 0x1804)) + list(range(0x1A00, 0x1A04))
            + [0x6040, 0x6041, 0x6060, 0x6061, 0x6064, 0x606C, 0x607A, 0x60C0, 0x60C2, 0x60FF],
            [0x2000] + params + [0x2212, 0x2213])
    e.var("1000", "Device type", U32, "ro", "0x00020192")
    e.var("1001", "Error register", U8, "ro", "0")
    e.var("1005", "COB-ID SYNC", U32, "rw", "0x00000080")
    e.var("1008", "Manufacturer device name", VSTR, "const", "SD-1")
    e.var("100C", "Guard time", U16, "rw", "0")
    e.var("100D", "Life time factor", U8, "rw", "0")
    e.obj(0x1010, "Store parameters", 0x8, [
        ("Highest sub-index supported", U8, "ro", "1"),
        ("Save all parameters", U32, "rw"),
    ])
    e.obj(0x1011, "Restore default parameters", 0x8, [
        ("Highest sub-index supported", U8, "ro", "1"),
        ("Restore all default parameters", U32, "rw"),
    ])
    e.var("1014", "COB-ID EMCY", U32, "rw", "$NODEID+0x80")
    e.var("1017", "Producer heartbeat time", U16, "rw", "0")
    # No values: the drive reports its identity from firmware.
    e.obj(0x1018, "Identity object", 0x9, [
        ("Highest sub-index supported", U8, "ro", "4"),
        ("Vendor-ID", U32, "ro"),
        ("Product code", U32, "ro"),
        ("Revision number", U32, "ro"),
        ("Serial number", U32, "ro"),
    ])
    e.obj(0x1020, "Verify configuration", 0x8, [
        ("Highest sub-index supported", U8, "ro", "2"),
        ("Configuration date", U32, "rw"),
        ("Configuration time", U32, "rw"),
    ])
    e.obj(0x1200, "SDO server parameter", 0x9, [
        ("Highest sub-index supported", U8, "ro", "2"),
        ("COB-ID client to server", U32, "ro", "$NODEID+0x600"),
        ("COB-ID server to client", U32, "ro", "$NODEID+0x580"),
    ])
    rx = [[0x60400010], [0x60400010, 0x60600008], [0x60400010, 0x607A0020], [0x60400010, 0x60FF0020]]
    tx = [[0x60410010], [0x60410010, 0x60610008], [0x60410010, 0x60640020], [0x60410010, 0x606C0020]]
    for n in range(4):
        pdo_comm(e, 0x1400 + n, "RPDO %d communication parameter" % (n + 1), "$NODEID+0x%X" % (0x200 + 0x100 * n), "rw")
    for n in range(4):
        pdo_map(e, 0x1600 + n, "RPDO %d mapping parameter" % (n + 1), rx[n], "rw")
    for n in range(4):
        pdo_comm(e, 0x1800 + n, "TPDO %d communication parameter" % (n + 1), "$NODEID+0x%X" % (0x180 + 0x100 * n), "rw")
    for n in range(4):
        pdo_map(e, 0x1A00 + n, "TPDO %d mapping parameter" % (n + 1), tx[n], "rw")
    e.var("2000", "Drive temperature", I16, "ro", "0")
    # A block of plain parameters, so the drive has well over 100 SDO objects.
    for i, index in enumerate(params):
        e.var("%04X" % index, "Tuning parameter %d" % (i + 1), U16, "rw", "0")
    e.obj(0x2212, "Encoder 2", 0x9, [
        ("Highest sub-index supported", U8, "ro", "1"),
        ("Encoder 2 pulse number", U32, "rw", None, 0, "16", "2500000"),
    ])
    e.obj(0x2213, "Sine encoder 2", 0x9, [
        ("Highest sub-index supported", U8, "ro", "1"),
        ("Sine encoder 2 resolution", U32, "rw", None, 0, "64", "10000000"),
    ])
    drive_402(e, "servo")
    # Limits written as unsigned hex on signed types (limit-only lint findings).
    e.var("60C0", "Interpolation sub mode select", I16, "rw", "0", low="0xFFFF", high="0")
    e.obj(0x60C2, "Interpolation time period", 0x9, [
        ("Highest sub-index supported", U8, "ro", "2"),
        ("Time period units", U8, "rw", "1"),
        ("Time index", I8, "rw", "-3", 0, "0xFD", "0"),
    ])
    return e.text()


def fixed_drive():
    e = Eds()
    e.header("fixed-drive.eds", "Made-up CiA 402 drive with fixed PDO mapping (test fixture)",
             "openplc-canopen test devices", 0x00F0F0F2, "Fixed drive FD-1", 0x00000403, 3, 3)
    e.lists([0x1000, 0x1001, 0x1018],
            [0x1005, 0x1008, 0x100C, 0x100D, 0x1010, 0x1011, 0x1014, 0x1200, 0x1400, 0x1401, 0x1402,
             0x1600, 0x1601, 0x1602, 0x1800, 0x1801, 0x1802, 0x1A00, 0x1A01, 0x1A02,
             0x6040, 0x6041, 0x6060, 0x6061, 0x6064, 0x606C, 0x607A, 0x60FF],
            [0x2301])
    e.var("1000", "Device type", U32, "ro", "0x00020192")
    e.var("1001", "Error register", U8, "ro", "0")
    e.var("1005", "COB-ID SYNC", U32, "rw", "0x00000080")
    e.var("1008", "Manufacturer device name", VSTR, "const", "FD-1")
    e.var("100C", "Guard time", U16, "rw", "0", low="0", high="0xFFFF")
    e.var("100D", "Life time factor", U8, "rw", "0", low="0", high="0xFF")
    e.obj(0x1010, "Store parameters", 0x8, [
        ("Highest sub-index supported", U8, "ro", "1"),
        ("Save all parameters", U32, "rw"),
    ])
    e.obj(0x1011, "Restore default parameters", 0x8, [
        ("Highest sub-index supported", U8, "ro", "1"),
        ("Restore all default parameters", U32, "rw"),
    ])
    e.var("1014", "COB-ID EMCY", U32, "rw", "$NODEID+0x80")
    e.obj(0x1018, "Identity object", 0x9, [
        ("Highest sub-index supported", U8, "ro", "4"),
        ("Vendor-ID", U32, "ro", "0x00F0F0F2"),
        ("Product code", U32, "ro", "0x00000403"),
        ("Revision number", U32, "ro", "0x00010000"),
        ("Serial number", U32, "ro"),
    ])
    e.obj(0x1200, "SDO server parameter", 0x9, [
        ("Highest sub-index supported", U8, "ro", "2"),
        ("COB-ID client to server", U32, "ro", "$NODEID+0x600"),
        ("COB-ID server to client", U32, "ro", "$NODEID+0x580"),
    ])
    rx = [[0x60400010], [0x23010108, 0x23010220], [0x60400010, 0x607A0020]]
    tx = [[0x60410010], [0x60410010, 0x60640020], [0x60410010, 0x606C0020]]
    for n in range(3):
        pdo_comm(e, 0x1400 + n, "RPDO %d communication parameter" % (n + 1), "$NODEID+0x%X" % (0x200 + 0x100 * n), "ro")
    for n in range(3):
        pdo_map(e, 0x1600 + n, "RPDO %d mapping parameter" % (n + 1), rx[n], "ro")
    for n in range(3):
        pdo_comm(e, 0x1800 + n, "TPDO %d communication parameter" % (n + 1), "$NODEID+0x%X" % (0x180 + 0x100 * n), "ro")
    for n in range(3):
        pdo_map(e, 0x1A00 + n, "TPDO %d mapping parameter" % (n + 1), tx[n], "ro")
    e.obj(0x2301, "Command", 0x9, [
        ("Highest sub-index supported", U8, "ro", "2"),
        ("Command number", U8, "rw", "0x00", 1, "0x00", "0xFF"),
        ("Command argument", I32, "rww", "0", 1, "-2147483648", "2147483647"),
    ])
    drive_402(e, "fixed")
    return e.text()


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.abspath(__file__))
    for name, text in (("servo-drive.eds", servo_drive()), ("fixed-drive.eds", fixed_drive())):
        with open(os.path.join(out, name), "w", newline="\n") as f:
            f.write(text)


if __name__ == "__main__":
    main()
