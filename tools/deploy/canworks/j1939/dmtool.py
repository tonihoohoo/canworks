"""Trouble codes straight from a CAN adapter on this PC (`canworks-diag
--adapter ... dm`, j1939-pc-tools "Trouble codes from the command line").

Listing only listens: every DM1 for a while, nothing sent. Reading (DM2) and
clearing (DM3/DM11) need a source address: the tool claims one, by default
249 (off-board diagnostic-service tool), with a NAME of its own that is not
arbitrary address capable, keeps it (never moves) and refuses to send when
it cannot claim it. close() gives the address back with a Cannot Claim and
closes the adapter. Built on can-j1939 like canworks-j1939-sim, whose
address claim it reuses.

    tool = DmTool(bus)
    sources = tool.listen(1.5)        # [{"address", "lamps", "flash", "count", "dtcs", "age_ms", ...}]
    tool.claim()
    answer = tool.read(0)             # {"address", "lamps", "flash", "count", "dtcs"}
    tool.clear(0, previous=True)      # {"address", "result": "ack"}
    tool.close()
"""

import threading
import time

from . import dm
from . import sim

FUNCTION_SERVICE_TOOL = 129  # NAME function: off-board diagnostic-service tool
GLOBAL = 255
ACK_CONTROL = {0: "ack", 1: "nack", 2: "access denied", 3: "cannot respond"}


class DmToolError(Exception):
    """A read or clear that did not work: the message says why."""


def default_name(address=dm.SERVICE_TOOL_ADDRESS):
    """The tool's NAME: function 129, identity number 0x10000 + address,
    not arbitrary address capable."""
    return sim.make_name(None, {"function": FUNCTION_SERVICE_TOOL}, address)


class DmTool:
    """Diagnostic messages on an open python-can `bus`."""

    def __init__(self, bus, address=dm.SERVICE_TOOL_ADDRESS, name=None, clock=time.monotonic):
        import can
        import j1939
        from j1939.electronic_control_unit import MessageListener
        self.bus, self.clock = bus, clock
        self.name = name or default_name(address)
        self.events = []  # (event, text) of the claim
        self._lock = threading.Lock()
        self._send_lock = threading.Lock()
        self._sources = {}  # address -> {"list": DmList, "at": clock, "dm1_count": int, "count": int}
        self._waiting = None  # {"address", "pgn", "result"} of a pending read or clear
        self._claims = {}
        sim._pythoncom_fix()
        self.ecu = j1939.ElectronicControlUnit(send_message=self._send_frame, max_cmdt_packets=255)
        self.ca = sim._claim_class()(self.name, address, True, lambda: set(self._claims),
                                     lambda event, text, **f: self.events.append((event, text)), clock)
        self.ecu.add_ca(controller_application=self.ca)
        self.ecu.subscribe(self._on_message)
        self._notifier = can.Notifier(bus, [MessageListener(self.ecu)], timeout=0.1)
        self._claim_started = False

    # -- bus

    def _send_frame(self, can_id, extended_id, data, fd_format=False):
        import can
        msg = can.Message(arbitration_id=can_id, is_extended_id=extended_id, data=bytes(data))
        with self._send_lock:
            try:
                self.bus.send(msg)
            except can.CanError as e:
                self.events.append(("send_error", "cannot send on the bus: %s" % e))

    def _on_message(self, priority, pgn, sa, timestamp, data):
        data = bytes(data)
        if pgn in (dm.PGN_DM1, dm.PGN_DM2):
            lst = dm.parse_dm(data)
            if lst is None:
                return
            count = len(lst.dtcs)
            with self._lock:
                if pgn == dm.PGN_DM1:
                    s = self._sources.setdefault(sa, {"dm1_count": 0})
                    s.update({"list": lst, "at": self.clock(), "count": count})
                    s["dm1_count"] += 1
                w = self._waiting
                if w and w["pgn"] == pgn and w["address"] == sa and w["result"] is None:
                    w["result"] = {"address": sa, "lamps": lst.lamps, "flash": lst.flash, "count": count,
                                   "dtcs": [c.as_dict() for c in lst.dtcs]}
            return
        if pgn == sim.PGN_ACK and len(data) >= 8:
            acked = data[5] | data[6] << 8 | data[7] << 16
            with self._lock:
                w = self._waiting
                if w and w["address"] == sa and acked == w["pgn"] and data[4] == self.ca.device_address \
                        and w["result"] is None:
                    w["result"] = ACK_CONTROL.get(data[0], "control %d" % data[0])

    # -- listing

    def listen(self, seconds):
        """Listens `seconds` and returns every DM1 source seen, as the
        plugin's status "dm" "sources"."""
        end = self.clock() + seconds
        while self.clock() < end:
            time.sleep(min(0.05, max(0.0, end - self.clock())))
        return self.sources()

    def sources(self):
        now = self.clock()
        out = []
        with self._lock:
            for a in sorted(self._sources):
                s = self._sources[a]
                lst = s["list"]
                out.append({"address": a, "lamps": lst.lamps, "flash": lst.flash, "count": s["count"],
                            "truncated": 0, "dtcs": [c.as_dict() for c in lst.dtcs],
                            "age_ms": int((now - s["at"]) * 1000), "dm1_count": s["dm1_count"],
                            "old_spn_format": any(c.cm for c in lst.dtcs)})
        return out

    # -- the address

    def claim(self, timeout=1.0):
        """Claims the address and waits sim.VETO_S for a contender; raises
        DmToolError when it cannot hold it."""
        import j1939
        state = j1939.ControllerApplication.State
        self._claim_started = True
        deadline = self.clock() + timeout
        settled = None
        while self.clock() < deadline:
            self.ca.tick(self.clock())
            if self.ca.state == state.CANNOT_CLAIM:
                break
            if self.ca.state == state.NORMAL:
                settled = settled or self.clock() + sim.VETO_S
                if self.clock() >= settled:
                    return self.ca.device_address
            time.sleep(0.01)
        lost = [t for e, t in self.events if e == "cannot_claim"]
        raise DmToolError("cannot claim address %d for the service tool%s; nothing sent (give another one with "
                          "--source-address)" % (self.ca._device_address_preferred,
                                                  ": " + lost[-1] if lost else ""))

    def _check_claimed(self):
        import j1939
        if self.ca.state != j1939.ControllerApplication.State.NORMAL:
            raise DmToolError("lost the service tool's address; nothing sent")

    # -- read and clear

    def _wait(self, address, pgn, timeout_ms):
        w = {"address": address, "pgn": pgn, "result": None}
        with self._lock:
            self._waiting = w
        try:
            self._check_claimed()
            try:
                self.ca.send_request(0, pgn, address)
            except RuntimeError:
                raise DmToolError("lost the service tool's address; nothing sent")
            end = self.clock() + timeout_ms / 1000.0
            while self.clock() < end:
                with self._lock:
                    if w["result"] is not None:
                        return w["result"]
                time.sleep(0.01)
            raise DmToolError("no answer from %d within %d ms" % (address, timeout_ms))
        finally:
            with self._lock:
                self._waiting = None

    def read(self, address, timeout_ms=1000):
        """The previously active codes (DM2) of `address`."""
        res = self._wait(address, dm.PGN_DM2, timeout_ms)
        if isinstance(res, str):  # an Acknowledgement instead of the data
            raise DmToolError("NACK from %d" % address if res == "nack" else "%s from %d" % (res, address))
        return res

    def clear(self, address, previous, timeout_ms=1000):
        """DM3 (`previous`) or DM11 to `address`, or to every ECU (255:
        no acknowledgement comes, so it answers "sent")."""
        pgn = dm.PGN_DM3 if previous else dm.PGN_DM11
        if address == GLOBAL:
            self._check_claimed()
            try:
                self.ca.send_request(0, pgn, GLOBAL)
            except RuntimeError:
                raise DmToolError("lost the service tool's address; nothing sent")
            return {"address": GLOBAL, "result": "sent"}
        res = self._wait(address, pgn, timeout_ms)
        if res != "ack":
            raise DmToolError("NACK from %d" % address if res == "nack" else "%s from %d" % (res, address))
        return {"address": address, "result": "ack"}

    def close(self):
        """Gives the address back (Cannot Claim with the tool's NAME) when it
        was claimed, and stops listening; the caller closes the adapter."""
        import j1939
        try:
            if self._claim_started and self.ca.state == j1939.ControllerApplication.State.NORMAL:
                self.ca._send_address_claimed(sim.NULL)
                time.sleep(0.05)  # let the frame leave before the adapter closes
        finally:
            try:
                self._notifier.stop(1)
            except Exception:  # the bus already gone
                pass
            self.ecu.stop()
