#!/usr/bin/env python3
"""Writes servo402.eds, the made-up CiA 402 drive of the CiA 402 example.

A single-axis drive (device type 0x00020192: profile 402, servo drive) with
the objects the editor's PLCopen motion blocks use, writable PDO mapping on
four RPDOs and four TPDOs, a heartbeat producer, error code 0x603F, ramps
(0x6083, 0x6084), homing (0x6098, 0x6099, 0x609A), the following error window
(0x6065, 0x6066) and the interpolation time period 0x60C2 of the cyclic
synchronous modes. Modes (0x6502): profile position, profile velocity,
homing, cyclic synchronous position, velocity and torque. Its default
mapping is the one the profile-mode example config uses:

    RPDO 1  controlword 0x6040, modes of operation 0x6060
    RPDO 2  target position 0x607A, profile velocity 0x6081
    RPDO 3  target velocity 0x60FF
    RPDO 4  target torque 0x6071
    TPDO 1  statusword 0x6041, modes of operation display 0x6061
    TPDO 2  position actual value 0x6064
    TPDO 3  velocity actual value 0x606C
    TPDO 4  torque actual value 0x6077

It describes no real product; the vendor ID is not one CiA assigns. The
simulated drive of the tests (test/drive/) plays it.

    python3 config/cia402-drive/make_eds.py config/cia402-drive
"""

import os
import sys

U8, U16, U32, I8, I16, I32, VSTR = 0x0005, 0x0006, 0x0007, 0x0002, 0x0003, 0x0004, 0x0009

RX = [[0x60400010, 0x60600008], [0x607A0020, 0x60810020], [0x60FF0020], [0x60710010]]
TX = [[0x60410010, 0x60610008], [0x60640020], [0x606C0020], [0x60770010]]


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
        """subs: {sub-index: (name, dtype, access, default, pdo, low, high)}."""
        self.w("[%04X]" % index)
        self.w("ParameterName=%s" % name)
        self.w("ObjectType=0x%X" % otype)
        self.w("SubNumber=%d" % len(subs))
        self.w()
        for sub, s in sorted(subs.items()):
            self.var("%04Xsub%X" % (index, sub), *s)

    def text(self):
        return "\n".join(self.out).rstrip("\n") + "\n"


def servo402():
    e = Eds()
    w = e.w
    w("[FileInfo]")
    for line in ("FileName=servo402.eds", "FileVersion=1", "FileRevision=1", "EDSVersion=4.0",
                 "Description=Made-up CiA 402 servo drive for the canworks CiA 402 example",
                 "CreationTime=12:00PM", "CreationDate=10-06-2026", "CreatedBy=canworks",
                 "ModificationTime=12:00PM", "ModificationDate=10-06-2026", "ModifiedBy=canworks"):
        w(line)
    w()
    w("[DeviceInfo]")
    for line in ("VendorName=canworks example devices", "VendorNumber=0x00F0F402",
                 "ProductName=Example servo drive SD-402", "ProductNumber=0x00000402", "RevisionNumber=0x00010000",
                 "OrderCode=SD-402"):
        w(line)
    for rate in (10, 20, 50, 125, 250, 500, 800, 1000):
        w("BaudRate_%d=1" % rate)
    for line in ("SimpleBootUpMaster=0", "SimpleBootUpSlave=1", "Granularity=8", "DynamicChannelsSupported=0",
                 "CompactPDO=0", "GroupMessaging=0", "NrOfRXPDO=4", "NrOfTXPDO=4", "LSS_Supported=0"):
        w(line)
    w()
    w("[DummyUsage]")
    for i in range(1, 8):
        w("Dummy%04d=0" % i)
    w()
    w("[Comments]")
    w("Lines=1")
    w("Line1=Made-up example device, see config/cia402-drive/make_eds.py")
    w()
    drive = [0x603F, 0x6040, 0x6041, 0x6060, 0x6061, 0x6064, 0x6065, 0x6066, 0x606C, 0x6071, 0x6077, 0x607A,
             0x6081, 0x6083, 0x6084, 0x6098, 0x6099, 0x609A, 0x60C2, 0x60FF, 0x6502]
    optional = ([0x1005, 0x1008, 0x1014, 0x1017, 0x1200] + list(range(0x1400, 0x1404)) + list(range(0x1600, 0x1604))
                + list(range(0x1800, 0x1804)) + list(range(0x1A00, 0x1A04)) + drive)
    for title, lst in (("MandatoryObjects", [0x1000, 0x1001, 0x1018]), ("OptionalObjects", optional),
                       ("ManufacturerObjects", [])):
        w("[%s]" % title)
        w("SupportedObjects=%d" % len(lst))
        for i, index in enumerate(lst):
            w("%d=0x%04X" % (i + 1, index))
        w()

    e.var("1000", "Device type", U32, "ro", "0x00020192")
    e.var("1001", "Error register", U8, "ro", "0")
    e.var("1005", "COB-ID SYNC", U32, "rw", "0x00000080")
    e.var("1008", "Manufacturer device name", VSTR, "const", "SD-402")
    e.var("1014", "COB-ID EMCY", U32, "rw", "$NODEID+0x80")
    e.var("1017", "Producer heartbeat time", U16, "rw", "0")
    e.obj(0x1018, "Identity object", 0x9, {
        0: ("Highest sub-index supported", U8, "ro", "4"),
        1: ("Vendor-ID", U32, "ro", "0x00F0F402"),
        2: ("Product code", U32, "ro", "0x00000402"),
        3: ("Revision number", U32, "ro", "0x00010000"),
        4: ("Serial number", U32, "ro", "0"),
    })
    e.obj(0x1200, "SDO server parameter", 0x9, {
        0: ("Highest sub-index supported", U8, "ro", "2"),
        1: ("COB-ID client to server", U32, "ro", "$NODEID+0x600"),
        2: ("COB-ID server to client", U32, "ro", "$NODEID+0x580"),
    })
    for n in range(4):
        e.obj(0x1400 + n, "RPDO %d communication parameter" % (n + 1), 0x9, {
            0: ("Highest sub-index supported", U8, "ro", "2"),
            1: ("COB-ID", U32, "rw", "$NODEID+0x%X" % (0x200 + 0x100 * n)),
            2: ("Transmission type", U8, "rw", "0xFF"),
        })
    for n in range(4):
        subs = {0: ("Number of mapped objects", U8, "rw", str(len(RX[n])), 0, "0", "8")}
        for k in range(8):
            subs[k + 1] = ("Mapped object %d" % (k + 1), U32, "rw", "0x%08X" % (RX[n][k] if k < len(RX[n]) else 0))
        e.obj(0x1600 + n, "RPDO %d mapping parameter" % (n + 1), 0x9, subs)
    for n in range(4):
        e.obj(0x1800 + n, "TPDO %d communication parameter" % (n + 1), 0x9, {
            0: ("Highest sub-index supported", U8, "ro", "5"),
            1: ("COB-ID", U32, "rw", "$NODEID+0x%X" % (0x180 + 0x100 * n)),
            2: ("Transmission type", U8, "rw", "0xFF"),
            3: ("Inhibit time", U16, "rw", "0"),
            5: ("Event timer", U16, "rw", "50"),
        })
    for n in range(4):
        subs = {0: ("Number of mapped objects", U8, "rw", str(len(TX[n])), 0, "0", "8")}
        for k in range(8):
            subs[k + 1] = ("Mapped object %d" % (k + 1), U32, "rw", "0x%08X" % (TX[n][k] if k < len(TX[n]) else 0))
        e.obj(0x1A00 + n, "TPDO %d mapping parameter" % (n + 1), 0x9, subs)

    e.var("603F", "Error code", U16, "ro", "0x0000", pdo=1)
    e.var("6040", "Controlword", U16, "rww", "0x0000", pdo=1)
    e.var("6041", "Statusword", U16, "ro", "0x0000", pdo=1)
    e.var("6060", "Modes of operation", I8, "rww", "0", pdo=1)
    e.var("6061", "Modes of operation display", I8, "ro", "0", pdo=1)
    e.var("6064", "Position actual value", I32, "ro", "0", pdo=1)
    e.var("6065", "Following error window", U32, "rw", "10000")
    e.var("6066", "Following error time out", U16, "rw", "10")
    e.var("606C", "Velocity actual value", I32, "ro", "0", pdo=1)
    e.var("6071", "Target torque", I16, "rww", "0", pdo=1)
    e.var("6077", "Torque actual value", I16, "ro", "0", pdo=1)
    e.var("607A", "Target position", I32, "rww", "0", pdo=1)
    e.var("6081", "Profile velocity", U32, "rww", "1000", pdo=1)
    e.var("6083", "Profile acceleration", U32, "rw", "10000")
    e.var("6084", "Profile deceleration", U32, "rw", "10000")
    e.var("6098", "Homing method", I8, "rw", "35")
    e.obj(0x6099, "Homing speeds", 0x8, {
        0: ("Highest sub-index supported", U8, "ro", "2"),
        1: ("Speed during search for switch", U32, "rw", "500"),
        2: ("Speed during search for zero", U32, "rw", "100"),
    })
    e.var("609A", "Homing acceleration", U32, "rw", "10000")
    e.obj(0x60C2, "Interpolation time period", 0x9, {
        0: ("Highest sub-index supported", U8, "ro", "2"),
        1: ("Interpolation time period value", U8, "rw", "1"),
        2: ("Interpolation time index", I8, "rw", "-3", 0, "-128", "63"),
    })
    e.var("60FF", "Target velocity", I32, "rww", "0", pdo=1)
    # Profile position (bit 0), profile velocity (bit 2), homing (bit 5),
    # cyclic synchronous position, velocity and torque (bits 7, 8, 9).
    e.var("6502", "Supported drive modes", U32, "ro", "0x000003A5")
    return e.text()


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(out, "servo402.eds"), "w", newline="\n") as f:
        f.write(servo402())


if __name__ == "__main__":
    main()
