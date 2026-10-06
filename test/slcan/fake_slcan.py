#!/usr/bin/env python3
"""A fake slcan adapter (CANable with slcan firmware) on a pseudo-terminal.

    fake_slcan.py <link-path> <can-interface>

Creates a pty, points <link-path> (a symlink) at its device, and plays the
adapter's firmware: it answers the Lawicel commands the kernel's slcan driver
sends (C close, Sn bit rate, O open) and, while the channel is open, bridges
CAN frames between the serial line and <can-interface> (a vcan where the
test's slave runs). Exiting closes the pty, which looks to the kernel like an
unplugged USB adapter.
"""

import os
import select
import signal
import socket
import struct
import sys
import time
import tty

CAN_FRAME = struct.Struct("=IB3x8s")
CAN_EFF_FLAG = 0x80000000
CAN_RTR_FLAG = 0x40000000
CAN_EFF_MASK = 0x1FFFFFFF


def encode(can_id, data):
    """A CAN frame as the adapter sends it to the host."""
    rtr = can_id & CAN_RTR_FLAG
    if can_id & CAN_EFF_FLAG:
        head = ("R" if rtr else "T") + "%08X" % (can_id & CAN_EFF_MASK)
    else:
        head = ("r" if rtr else "t") + "%03X" % (can_id & 0x7FF)
    return (head + "%d" % len(data) + ("" if rtr else data.hex().upper()) + "\r").encode()


def decode(line):
    """A frame command from the host as (can_id, data), or None."""
    kind = line[:1]
    ext = kind in "TR"
    n = 8 if ext else 3
    can_id = int(line[1:1 + n], 16) | (CAN_EFF_FLAG if ext else 0)
    dlc = int(line[1 + n])
    if kind in "rR":
        return can_id | CAN_RTR_FLAG, b"\0" * dlc
    return can_id, bytes.fromhex(line[2 + n:2 + n + 2 * dlc])


def main():
    link, iface = sys.argv[1], sys.argv[2]
    master, slave = os.openpty()
    tty.setraw(slave)
    name = os.ttyname(slave)
    os.close(slave)  # the plugin's open must be the only one, or closing it would not detach the driver
    tmp = link + ".new"
    if os.path.lexists(tmp):
        os.unlink(tmp)
    os.symlink(name, tmp)
    os.replace(tmp, link)
    print("fake slcan adapter on %s (%s), bridged to %s" % (link, name, iface), flush=True)

    can = socket.socket(socket.PF_CAN, socket.SOCK_RAW, socket.CAN_RAW)
    can.bind((iface,))
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))

    is_open = False
    buf = b""
    while True:
        r, _, _ = select.select([master, can], [], [], 0.5)
        if can in r:
            frame = can.recv(CAN_FRAME.size)
            can_id, dlc, data = CAN_FRAME.unpack(frame)
            if is_open:
                os.write(master, encode(can_id, data[:dlc]))
        if master in r:
            try:
                chunk = os.read(master, 4096)
            except OSError:  # EIO: nobody has the device open
                time.sleep(0.05)
                continue
            buf += chunk
            while b"\r" in buf:
                line, buf = buf.split(b"\r", 1)
                line = line.decode("ascii", "replace").strip()
                if not line:
                    continue
                cmd = line[0]
                if cmd in "tTrR":
                    if is_open:
                        can_id, data = decode(line)
                        can.send(CAN_FRAME.pack(can_id, len(data), data.ljust(8, b"\0")))
                        os.write(master, b"z\r" if cmd in "tr" else b"Z\r")
                    else:
                        os.write(master, b"\a")
                    continue
                if cmd == "O":
                    is_open = True
                elif cmd == "C":
                    is_open = False
                print("command %s" % line, flush=True)
                os.write(master, b"\r")


if __name__ == "__main__":
    main()
