"""Fake CANopen devices on python-can's virtual bus, for the local bus
backend's tests: an SDO server (expedited and segmented), heartbeat, EMCY,
NMT and an LSS slave with fastscan."""

import struct
import threading
import time

import can


class FakeDevice:
    """One device. `node` may be None (no node ID, waits for LSS).
    `od` maps (index, sub) -> bytes; read-only entries are in `ro`."""

    def __init__(self, channel, node, od=None, identity=(0x360, 0x1, 0x2, 0x1234), name="fake device",
                 device_type=0x00020191, heartbeat_s=None, ro=(), lss=True, nmt_state=127, nvm=False, pdo=False):
        self.channel, self.node = channel, node
        self.identity = identity
        self.od = {(0x1018, 1): struct.pack("<I", identity[0]), (0x1018, 2): struct.pack("<I", identity[1]),
                   (0x1018, 3): struct.pack("<I", identity[2]), (0x1018, 4): struct.pack("<I", identity[3]),
                   (0x1000, 0): struct.pack("<I", device_type), (0x1008, 0): name.encode("latin-1"),
                   (0x1010, 1): struct.pack("<I", 1)}
        self.od.update(od or {})
        # With `nvm` the device keeps what "save" (0x1010) stored over a reset
        # and power cycle, and "load" (0x1011) brings back these values.
        self.nvm = nvm
        # With `pdo` the device runs its PDOs from its object dictionary while
        # OPERATIONAL: TPDOs on each SYNC (or, event-driven, every 50 ms),
        # RPDOs written into the mapped entries.
        self.pdo = pdo
        self.syncs = 0
        self._last_event = 0.0
        self.factory = dict(self.od)
        self.saved = None
        self.loaded = False
        self.ro = set(ro) | {(0x1018, 1), (0x1018, 2), (0x1018, 3), (0x1018, 4), (0x1000, 0), (0x1008, 0)}
        self.heartbeat_s = heartbeat_s
        self.lss = lss
        self.state = nmt_state
        self.nmt_log = []
        self.lss_log = []
        self.stored = []
        self.pending_node = None
        self.bit_timing = None
        self.received = []  # every frame this device saw
        self._lss_state = "waiting"
        self._lss_sel = []
        self._fs_pos = 0
        self._seg = None
        self._stop = threading.Event()
        self.bus = can.Bus(interface="virtual", channel=channel, receive_own_messages=False)
        self._t = threading.Thread(target=self._run, daemon=True)
        self._t.start()

    def close(self):
        self._stop.set()
        self._t.join(2)
        self.bus.shutdown()

    def send(self, cob, data):
        self.bus.send(can.Message(arbitration_id=cob, data=bytes(data), is_extended_id=False))

    def emcy(self, code, register=1, msef=b"\0" * 5):
        self.send(0x80 + self.node, struct.pack("<HB", code, register) + bytes(msef))

    def _run(self):
        last_hb = 0.0
        while not self._stop.is_set():
            msg = self.bus.recv(0.02)
            now = time.monotonic()
            if self.heartbeat_s and self.node and now - last_hb >= self.heartbeat_s:
                last_hb = now
                self.send(0x700 + self.node, bytes([self.state]))
            if self.pdo and self.state == 5 and now - self._last_event >= 0.05:
                self._last_event = now
                self._tpdos(event=True)
            if msg is None:
                continue
            self.received.append(msg)
            if self.pdo and self.state == 5 and self._pdo(msg):
                continue
            cob, data = msg.arbitration_id, bytes(msg.data).ljust(8, b"\0")
            if cob == 0 and (data[1] in (0, self.node)) and self.node:
                self.nmt_log.append(data[0])
                self.state = {1: 5, 2: 4, 0x80: 127}.get(data[0], self.state)
                if data[0] in (0x81, 0x82):
                    if data[0] == 0x81 and self.nvm:
                        self._reload()
                    self.state = 127
                    self.send(0x700 + self.node, b"\0")
            elif self.node and cob == 0x600 + self.node and self.state != 4:
                self._sdo(data)
            elif cob == 0x7E5 and self.lss:
                self._lss(data)

    # -- PDOs ------------------------------------------------------------------------
    def _u(self, key):
        v = self.od.get(key)
        return int.from_bytes(v, "little") if v is not None else None

    def _mapped(self, mapping):
        out = []
        for k in range(1, (self._u((mapping, 0)) or 0) + 1):
            v = self._u((mapping, k)) or 0
            out.append(((v >> 16, (v >> 8) & 0xFF), v & 0xFF))
        return out

    def _tpdos(self, event):
        for n in range(4):
            cob = self._u((0x1800 + n, 1))
            trans = self._u((0x1800 + n, 2))
            if cob is None or cob & 0x80000000 or trans is None or (trans >= 254) != event:
                continue
            v, pos = 0, 0
            for key, bits in self._mapped(0x1A00 + n):
                v |= (int.from_bytes(self.od.get(key, b""), "little") & ((1 << bits) - 1)) << pos
                pos += bits
            self.send(cob & 0x7FF, v.to_bytes((pos + 7) // 8, "little"))

    def _pdo(self, msg):
        cob, data = msg.arbitration_id, bytes(msg.data)
        if cob == 0x80:
            self.syncs += 1
            self._tpdos(event=False)
            return True
        for n in range(4):
            rc = self._u((0x1400 + n, 1))
            if rc is None or rc & 0x80000000 or rc & 0x7FF != cob:
                continue
            v, pos = int.from_bytes(data, "little"), 0
            for key, bits in self._mapped(0x1600 + n):
                part = (v >> pos) & ((1 << bits) - 1)
                pos += bits
                self.od[key] = part.to_bytes((bits + 7) // 8, "little")
            return True
        return False

    # -- SDO server ---------------------------------------------------------------
    def _abort(self, idx, sub, code):
        self.send(0x580 + self.node, struct.pack("<BHBI", 0x80, idx, sub, code))

    def _sdo(self, d):
        ccs = d[0] >> 5
        if d[0] == 0x80:
            self._seg = None
            return
        if ccs == 2:  # upload initiate
            idx, sub = struct.unpack_from("<HB", d, 1)
            if (idx, sub) not in self.od:
                return self._abort(idx, sub, 0x06020000)
            v = self.od[(idx, sub)]
            if len(v) <= 4:
                self.send(0x580 + self.node, struct.pack("<BHB", 0x43 | (4 - len(v)) << 2, idx, sub) + v.ljust(4, b"\0"))
            else:
                self._seg = {"dir": "up", "idx": idx, "sub": sub, "data": v, "pos": 0, "t": 0}
                self.send(0x580 + self.node, struct.pack("<BHBI", 0x41, idx, sub, len(v)))
        elif ccs == 3 and self._seg and self._seg["dir"] == "up":
            s = self._seg
            t = (d[0] >> 4) & 1
            if t != s["t"]:
                return self._abort(s["idx"], s["sub"], 0x05030000)
            chunk = s["data"][s["pos"]:s["pos"] + 7]
            s["pos"] += len(chunk)
            last = s["pos"] >= len(s["data"])
            self.send(0x580 + self.node, bytes([t << 4 | (7 - len(chunk)) << 1 | int(last)]) + chunk.ljust(7, b"\0"))
            s["t"] ^= 1
            if last:
                self._seg = None
        elif ccs == 1:  # download initiate
            idx, sub = struct.unpack_from("<HB", d, 1)
            if (idx, sub) in self.ro:
                return self._abort(idx, sub, 0x06010002)
            if (idx, sub) not in self.od:
                return self._abort(idx, sub, 0x06020000)
            if d[0] & 0x02:
                n = (d[0] >> 2) & 3 if d[0] & 1 else 0
                self._write(idx, sub, bytes(d[4:8 - n]))
            else:
                self._seg = {"dir": "down", "idx": idx, "sub": sub, "data": b"", "t": 0}
            self.send(0x580 + self.node, struct.pack("<BHB4x", 0x60, idx, sub))
        elif ccs == 0 and self._seg and self._seg["dir"] == "down":
            s = self._seg
            t = (d[0] >> 4) & 1
            n = (d[0] >> 1) & 7
            s["data"] += bytes(d[1:8 - n])
            self.send(0x580 + self.node, bytes([0x20 | t << 4]) + bytes(7))
            if d[0] & 1:
                self._write(s["idx"], s["sub"], s["data"])
                self._seg = None

    def _write(self, idx, sub, value):
        if idx == 0x1010:
            self.stored.append(sub)
            if self.nvm and value == b"save":
                self.saved = dict(self.od)
                self.loaded = False
        if idx == 0x1011 and self.nvm and value == b"load":
            self.loaded = True
        self.od[(idx, sub)] = value

    def _reload(self):
        """What a reset node or power cycle starts with: the stored values,
        or the defaults after "load"."""
        if self.loaded:
            self.saved, self.loaded = None, False
        self.od = dict(self.saved or self.factory)

    def power_cycle(self):
        self._reload()
        self.state = 127
        if self.node:
            self.send(0x700 + self.node, b"\0")

    # -- LSS slave ------------------------------------------------------------------
    def _lss(self, d):
        cs = d[0]
        self.lss_log.append(cs)
        val = struct.unpack_from("<I", d, 1)[0]
        if cs == 0x04:
            self._lss_state = "config" if d[1] == 1 else "waiting"
            self._lss_sel = []
        elif 0x40 <= cs <= 0x43:
            if cs == 0x40:
                self._lss_sel = []
            if len(self._lss_sel) == cs - 0x40 and val == self.identity[cs - 0x40]:
                self._lss_sel.append(val)
                if cs == 0x43:
                    self._lss_state = "config"
                    self.send(0x7E4, bytes([0x44]))
            else:
                self._lss_sel = []
        elif cs == 0x51:
            if self.node and self.node != 0xFF:
                return  # only devices without a node ID take part
            bit, sub, nxt = d[5], d[6], d[7]
            if bit == 0x80:
                self._fs_pos = 0
                self.send(0x7E4, bytes([0x4F]))
                return
            if sub != self._fs_pos:
                return
            if ((self.identity[sub] ^ val) >> bit) == 0:
                self.send(0x7E4, bytes([0x4F]))
                if bit == 0 and nxt != sub:
                    self._fs_pos = nxt
                    if sub == 3:
                        self._lss_state = "config"  # all four parts matched
        elif self._lss_state != "config":
            return
        elif cs == 0x5E:
            self.send(0x7E4, bytes([0x5E, self.node if self.node else 0xFF]))
        elif cs == 0x11:
            if 1 <= d[1] <= 127:
                self.pending_node = d[1]
                if not self.node:
                    self.node = d[1]
                self.send(0x7E4, bytes([0x11, 0, 0]))
            else:
                self.send(0x7E4, bytes([0x11, 1, 0]))
        elif cs == 0x13:
            self.bit_timing = d[2]
            self.send(0x7E4, bytes([0x13, 0, 0]))
        elif cs == 0x17:
            self.stored.append("lss")
            self.send(0x7E4, bytes([0x17, 0, 0]))


class Peer:
    """Another node on the bus that sends raw frames (another master)."""

    def __init__(self, channel):
        self.bus = can.Bus(interface="virtual", channel=channel, receive_own_messages=False)

    def send(self, cob, data):
        self.bus.send(can.Message(arbitration_id=cob, data=bytes(data), is_extended_id=False))

    def close(self):
        self.bus.shutdown()
