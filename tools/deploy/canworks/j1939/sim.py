"""canworks-j1939-sim: one simulated J1939 ECU on a SocketCAN interface or a
USB CAN adapter (docs/j1939.md, "Simulator").

Built on can-j1939 (python package `j1939`: address claim, requests,
transport protocol BAM and RTS/CTS) over python-can, and on cantools for the
DBC. The simulator claims an address with its NAME, sends every DBC message
whose sender is the simulated node at its cycle time, answers requests for
those PGNs (and NACKs requests to its address for any other PGN), and
reports every received message the DBC defines, decoded. With --contend it
claims an address and keeps it: it never moves, so claim loss and defence of
another ECU (the PLC) can be tested.

Adapters are opened by canworks.localbus.adapter, as the other PC tools do.

The ECU's address claim is reimplemented here on top of can-j1939's
ControllerApplication: its own one moves to the next address without a
range and never stops at 253.
"""

import argparse
import json
import math
import signal as signal_mod
import sys
import threading
import time

PROG = "canworks-j1939-sim"

GLOBAL = 255  # destination of a broadcast
NULL = 254  # source address of Cannot Claim
PGN_REQUEST = 59904
PGN_ACK = 59392
ACK_NACK = 1  # Acknowledgement control byte: negative
CLAIM_PF = 0xEE

DEFAULT_BITRATE = 250000
DEFAULT_RAMP_S = 10.0
DEFAULT_IDENTITY = 0x10000  # default NAME: identity number 0x10000 + address, all other fields 0
VETO_S = 0.25  # wait after a claim before sending (J1939-81), addresses 128..247
ARBITRARY_RANGE = (128, 247)  # where an arbitrary address capable simulator moves when it loses
TICK_S = 0.02  # claim and send scheduler resolution

NAME_FIELDS = (  # (option, j1939.Name keyword, bits)
    ("identity-number", "identity_number", 21),
    ("manufacturer-code", "manufacturer_code", 11),
    ("ecu-instance", "ecu_instance", 3),
    ("function-instance", "function_instance", 5),
    ("function", "function", 8),
    ("vehicle-system", "vehicle_system", 7),
    ("vehicle-system-instance", "vehicle_system_instance", 4),
    ("industry-group", "industry_group", 3),
)


class SimError(Exception):
    """A problem with the DBC, the scenario or the options: the message says what."""


# ---------------------------------------------------------------------------
# Identifiers, NAMEs and values


def _pythoncom_fix():
    """can-j1939 (2.0.12) ends its job thread on Windows with
    pythoncom.CoUnitialize(), a misspelling that raises at every stop."""
    if sys.platform != "win32":
        return
    try:
        import pythoncom
    except ImportError:
        return
    if not hasattr(pythoncom, "CoUnitialize") and hasattr(pythoncom, "CoUninitialize"):
        pythoncom.CoUnitialize = pythoncom.CoUninitialize


def pgn_of(frame_id):
    """The PGN of a 29-bit identifier: PS is part of it only for PDU2 (PF >= 240)."""
    dp, pf, ps = (frame_id >> 24) & 1, (frame_id >> 16) & 0xFF, (frame_id >> 8) & 0xFF
    return (dp << 16) | (pf << 8) | (ps if pf >= 240 else 0)


def name_text(value):
    return "0x%016X" % value


def make_name(value=None, fields=None, address=0):
    """A j1939.Name from a 64-bit value, or from NAME fields (identity number
    defaults to DEFAULT_IDENTITY + address, every other field to 0)."""
    import j1939
    if value is not None:
        return j1939.Name(value=value)
    kw = {"identity_number": DEFAULT_IDENTITY + address}
    kw.update(fields or {})
    return j1939.Name(**kw)


def raw_limits(signal):
    """The raw values a signal's bits can hold."""
    n = signal.length
    if signal.is_signed:
        return -(1 << (n - 1)), (1 << (n - 1)) - 1
    return 0, (1 << n) - 1


def valid_limits(signal):
    """The raw values below J1939's "error" and "not available" (all ones and
    all ones minus one; for 8 bits and more the whole top range from 0xFB...)."""
    lo, hi = raw_limits(signal)
    if signal.is_signed or signal.length == 1:
        return lo, hi
    if signal.length < 8:
        return 0, hi - 2
    return 0, (0xFB << (signal.length - 8)) - 1


def to_raw(signal, value):
    return int(round((value - (signal.offset or 0)) / (signal.scale or 1)))


def ramp_limits(signal):
    """Raw ramp ends: the DBC's [minimum|maximum] inside the J1939 valid range."""
    lo, hi = valid_limits(signal)
    if signal.minimum is not None and signal.maximum is not None and signal.scale:
        a = (signal.minimum - (signal.offset or 0)) / signal.scale
        b = (signal.maximum - (signal.offset or 0)) / signal.scale
        lo = max(lo, int(math.ceil(min(a, b) - 1e-9)))
        hi = min(hi, int(math.floor(max(a, b) + 1e-9)))
    return lo, max(lo, hi)


def fmt_value(v):
    if isinstance(v, float):
        if v == int(v) and abs(v) < 1e15:
            return str(int(v))
        return ("%.6f" % v).rstrip("0").rstrip(".")
    return str(v)


# ---------------------------------------------------------------------------
# Signal values: ramp, constant, list


class Ramp:
    """From `lo` to `hi` (raw) over `period` seconds, then from `lo` again."""

    def __init__(self, lo, hi, period):
        self.lo, self.hi, self.period = lo, hi, period

    def raw(self, t):
        frac = (t % self.period) / self.period
        return self.lo + int(round((self.hi - self.lo) * frac))


class Constant:
    def __init__(self, raw):
        self.value = raw

    def raw(self, t):
        return self.value


class Steps:
    """Each raw value for `step` seconds; then from the first again, or the
    last one held when not `repeat`."""

    def __init__(self, values, step, repeat=True):
        self.values, self.step, self.repeat = values, step, repeat

    def raw(self, t):
        i = int(t // self.step)
        return self.values[i % len(self.values)] if self.repeat else self.values[min(i, len(self.values) - 1)]


# ---------------------------------------------------------------------------
# Scenario file

SCENARIO_HELP = """\
scenario file (--scenario), JSON:
  {"ramp_period_s": 10,
   "messages": {
     "Pressures": {"period_ms": 50,
                   "signals": {"Pressure": 12.5,
                               "Temp": {"ramp": [-20, 80], "period_s": 5},
                               "Level": {"values": [10, 50, 90], "step_s": 1, "repeat": true},
                               "PumpOn": {"raw": 3}}},
     "ComponentInfo": {"period_ms": 1000}}}
  Messages are named as in the DBC and must be sent by --node. period_ms
  replaces the DBC cycle time (0: only on request). A signal is a constant,
  a ramp, a list of values each held step_s seconds, or a raw value; values
  are physical (scaled) and within the DBC range, raw values within the
  signal's bits (so "not available" can be sent). Signals not named ramp."""

_SCENARIO_KEYS = ("ramp_period_s", "messages")
_MESSAGE_KEYS = ("period_ms", "signals")


def _number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _physical(signal, value, where):
    if not _number(value):
        raise SimError("%s: %r is not a number" % (where, value))
    eps = abs(signal.scale or 1) / 2
    if signal.minimum is not None and value < signal.minimum - eps:
        raise SimError("%s: %s is below %s's minimum %s" % (where, fmt_value(value), signal.name,
                                                          fmt_value(signal.minimum)))
    if signal.maximum is not None and value > signal.maximum + eps:
        raise SimError("%s: %s is above %s's maximum %s" % (where, fmt_value(value), signal.name,
                                                          fmt_value(signal.maximum)))
    return _raw(signal, to_raw(signal, value), where)


def _raw(signal, raw, where):
    if not isinstance(raw, int) or isinstance(raw, bool):
        raise SimError("%s: raw value %r is not an integer" % (where, raw))
    lo, hi = raw_limits(signal)
    if not lo <= raw <= hi:
        raise SimError("%s: raw value %d does not fit %s's %d bits (%d..%d)" % (where, raw, signal.name,
                                                                                 signal.length, lo, hi))
    return raw


def _positive(v, where):
    if not _number(v) or v <= 0:
        raise SimError("%s: give a number of seconds above 0" % where)
    return float(v)


def _keys(obj, allowed, where, unknown="unknown key %r"):
    if not isinstance(obj, dict):
        raise SimError("%s: expected an object" % where)
    extra = sorted(k for k in obj if k not in allowed)
    if extra:
        raise SimError("%s: %s (allowed: %s)" % (where, unknown % extra[0], ", ".join(allowed)))


def _source(signal, spec, where, ramp_period):
    if _number(spec):
        return Constant(_physical(signal, spec, where))
    if not isinstance(spec, dict):
        raise SimError("%s: give a number, or an object with ramp, values or raw" % where)
    kinds = [k for k in ("ramp", "values", "raw") if k in spec]
    if len(kinds) != 1:
        raise SimError("%s: give exactly one of ramp, values or raw" % where)
    kind = kinds[0]
    if kind == "raw":
        _keys(spec, ("raw",), where)
        return Constant(_raw(signal, spec["raw"], where + ".raw"))
    if kind == "ramp":
        _keys(spec, ("ramp", "period_s"), where)
        ends = spec["ramp"]
        if not isinstance(ends, list) or len(ends) != 2:
            raise SimError("%s.ramp: give [from, to]" % where)
        lo, hi = (_physical(signal, v, "%s.ramp[%d]" % (where, i)) for i, v in enumerate(ends))
        period = _positive(spec["period_s"], where + ".period_s") if "period_s" in spec else ramp_period
        return Ramp(lo, hi, period)
    _keys(spec, ("values", "step_s", "repeat"), where)
    values = spec["values"]
    if not isinstance(values, list) or not values:
        raise SimError("%s.values: give a list of at least one value" % where)
    raws = [_physical(signal, v, "%s.values[%d]" % (where, i)) for i, v in enumerate(values)]
    step = _positive(spec.get("step_s", 1), where + ".step_s")
    repeat = spec.get("repeat", True)
    if not isinstance(repeat, bool):
        raise SimError("%s.repeat: give true or false" % where)
    return Steps(raws, step, repeat)


def load_scenario(source, db, node):
    """A scenario (a file path or the parsed JSON) checked against the DBC:
    {"ramp_period_s": float or None, "messages": {name: {"period_ms": int or
    None, "signals": {signal name: source}}}}. Raises SimError."""
    where = "scenario"
    if isinstance(source, str):
        where = source
        try:
            with open(source, encoding="utf-8") as f:
                source = json.load(f)
        except OSError as e:
            raise SimError("cannot read scenario %s: %s" % (where, e.strerror or e))
        except ValueError as e:
            raise SimError("%s: not valid JSON: %s" % (where, e))
    _keys(source, _SCENARIO_KEYS, where)
    ramp_period = None
    if "ramp_period_s" in source:
        ramp_period = _positive(source["ramp_period_s"], where + ": ramp_period_s")
    messages = source.get("messages", {})
    for name in messages if isinstance(messages, dict) else ():
        msg = next((m for m in db.messages if m.name == name), None)
        if msg is not None and node not in msg.senders:
            raise SimError("%s: messages.%s: sent by %s in the DBC, not by %s" % (
                where, name, ", ".join(msg.senders) or "no node", node))
    _keys(messages, [m.name for m in db.messages if node in m.senders], where + ": messages",
          "no message %r in the DBC")
    out = {}
    for name, spec in messages.items():
        at = "%s: messages.%s" % (where, name)
        msg = db.get_message_by_name(name)
        _keys(spec, _MESSAGE_KEYS, at)
        period = spec.get("period_ms")
        if period is not None and (not isinstance(period, int) or isinstance(period, bool) or period < 0):
            raise SimError("%s.period_ms: give milliseconds, 0 or more (0: only on request)" % at)
        signals = spec.get("signals", {})
        _keys(signals, [s.name for s in msg.signals], at + ".signals", "no signal %r in " + name)
        out[name] = {"period_ms": period, "signals": {
            s: (at + ".signals." + s, v) for s, v in signals.items()}}
    # Sources are built once the ramp period is known (plans()).
    return {"ramp_period_s": ramp_period, "messages": out}


# ---------------------------------------------------------------------------
# DBC


def load_dbc(path):
    try:
        import cantools
    except ImportError:
        raise SimError("cantools is not installed; reinstall the PC tools")
    try:
        return cantools.database.load_file(path)
    except OSError as e:
        raise SimError("cannot read DBC %s: %s" % (path, e.strerror or e))
    except Exception as e:  # cantools raises its own parse errors
        raise SimError("cannot read DBC %s: %s" % (path, e))


def node_messages(db, node):
    names = [n.name for n in db.nodes]
    if node not in names:
        raise SimError("node %s is not in the DBC (its nodes: %s)" % (node, ", ".join(names) or "none"))
    return [m for m in db.messages if node in m.senders and m.is_extended_frame]


def default_address(db, node):
    """The source address of the node's messages in the DBC, when they agree."""
    addresses = sorted({m.frame_id & 0xFF for m in node_messages(db, node)})
    if len(addresses) != 1 or addresses[0] > 253:
        raise SimError("give --address: %s's messages in the DBC have %s" % (
            node, "source addresses " + ", ".join(map(str, addresses)) if addresses else "no source address"))
    return addresses[0]


class Plan:
    """One message the simulator sends: identifier parts, period (None: only
    on request) and a value source per signal."""

    def __init__(self, message, period_s, sources):
        self.message, self.period_s, self.sources = message, period_s, sources
        fid = message.frame_id
        self.pgn = pgn_of(fid)
        self.priority = (fid >> 26) & 7
        self.dp, self.pf, self.ps = (fid >> 24) & 1, (fid >> 16) & 0xFF, (fid >> 8) & 0xFF
        self.next_due = None
        self.sent = 0
        self.busy_noted = False

    @property
    def pdu1(self):
        return self.pf < 240

    def payload(self, t):
        raw = {name: src.raw(t) for name, src in self.sources.items()}
        return self.message.encode(raw, scaling=False, padding=True, strict=False)

    def describe(self):
        when = "%d ms" % round(self.period_s * 1000) if self.period_s else "on request"
        return "%s (PGN %d, %s)" % (self.message.name, self.pgn, when)


def plans(db, node, scenario=None, ramp_period=DEFAULT_RAMP_S):
    """What `node` sends: a Plan per DBC message it is the sender of."""
    scenario = scenario or {"ramp_period_s": None, "messages": {}}
    ramp_period = scenario["ramp_period_s"] or ramp_period
    out = []
    for m in node_messages(db, node):
        spec = scenario["messages"].get(m.name, {"period_ms": None, "signals": {}})
        period_ms = spec["period_ms"] if spec["period_ms"] is not None else (m.cycle_time or 0)
        sources = {}
        for s in m.signals:
            if s.name in spec["signals"]:
                where, value = spec["signals"][s.name]
                sources[s.name] = _source(s, value, where, ramp_period)
            else:
                sources[s.name] = Ramp(*ramp_limits(s), period=ramp_period)
        out.append(Plan(m, period_ms / 1000.0 if period_ms else None, sources))
    return out


# ---------------------------------------------------------------------------
# Address claim


def _claim_class():
    import j1939

    State = j1939.ControllerApplication.State

    class Claim(j1939.ControllerApplication):
        """can-j1939's controller application with this simulator's claim:
        claim, wait VETO_S (addresses 128..247), defend against a higher
        NAME; on a lower one move to the next free address in
        ARBITRARY_RANGE when the NAME is arbitrary address capable and the
        address is not kept, else send Cannot Claim and go silent. Driven
        by tick() from the simulator's thread, not by can-j1939's timer."""

        def __init__(self, name, address, keep, taken, report, clock):
            super().__init__(name, address)
            self._keep, self._taken, self._report, self._clock = keep, taken, report, clock
            self._veto_until = None
            self._lock = threading.RLock()

        def start(self):
            pass  # tick() claims

        def tick(self, now):
            with self._lock:
                if self._device_address_state == State.NONE:
                    self._claim(self._device_address_preferred, now)
                elif self._device_address_state == State.WAIT_VETO and now >= self._veto_until:
                    self._device_address = self._device_address_announced
                    self._device_address_state = State.NORMAL
                    self._report("claimed", "Claimed address %d with NAME %s" % (
                        self._device_address, name_text(self._name.value)), address=self._device_address)

        def _claim(self, address, now):
            self._device_address_announced = address
            self._device_address_state = State.WAIT_VETO
            wait = VETO_S if ARBITRARY_RANGE[0] <= address <= ARBITRARY_RANGE[1] else 0.0
            self._veto_until = now + wait
            self._send_address_claimed(address)

        def _process_addressclaim(self, mid, data, timestamp):
            if len(data) < 8:
                return
            with self._lock:
                state = self._device_address_state
                if state == State.NORMAL:
                    mine = self._device_address
                elif state == State.WAIT_VETO:
                    mine = self._device_address_announced
                else:
                    return
                if mid.source_address != mine:
                    return
                other = int.from_bytes(bytes(data[:8]), "little")
                if other == self._name.value:
                    return
                if self._name.value < other:
                    self._send_address_claimed(mine)
                    self._report("defended", "Defended address %d against NAME %s" % (mine, name_text(other)),
                                 address=mine, contender=name_text(other))
                    return
                nxt = None
                if not self._keep and self._name.arbitrary_address_capable:
                    taken = self._taken()
                    lo, hi = ARBITRARY_RANGE
                    for a in list(range(mine + 1, hi + 1)) + list(range(lo, mine)):
                        if lo <= a <= hi and a not in taken:
                            nxt = a
                            break
                self._device_address = j1939.ParameterGroupNumber.Address.NULL
                if nxt is None:
                    self._device_address_state = State.CANNOT_CLAIM
                    self._send_address_claimed(NULL)
                    self._report("cannot_claim", "Cannot claim: lost address %d to NAME %s; sending nothing"
                                 % (mine, name_text(other)), address=mine, contender=name_text(other))
                    return
                self._report("lost", "Lost address %d to NAME %s; claiming %d" % (mine, name_text(other), nxt),
                             address=mine, contender=name_text(other), next=nxt)
                self._claim(nxt, self._clock())

    return Claim


# ---------------------------------------------------------------------------
# The simulator


class Simulator:
    """One simulated ECU on an open python-can `bus`.

    report(event, text, **fields) gets every event: claims (own and seen),
    received messages the DBC defines ("rx"), requests answered and NACKed.
    """

    def __init__(self, bus, address, name, db=None, plans=(), keep_address=False, report=None,
                 clock=time.monotonic):
        import can
        import j1939
        from j1939.electronic_control_unit import MessageListener
        self.bus, self.db, self.plans = bus, db, list(plans)
        self.name = name
        self.report = report or (lambda event, text, **fields: print(text, flush=True))
        self.clock = clock
        self._send_lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None
        self._t0 = None
        self.claims = {}  # address -> NAME value, from the claims seen on the bus
        self.received = 0
        self.send_errors = 0
        self._by_pgn = {p.pgn: p for p in self.plans}
        self._rx = {}  # PGN -> DBC messages
        for m in (db.messages if db else ()):
            if m.is_extended_frame:
                self._rx.setdefault(pgn_of(m.frame_id), []).append(m)

        _pythoncom_fix()
        self.ecu = j1939.ElectronicControlUnit(send_message=self._send_frame, max_cmdt_packets=255)
        self.ca = _claim_class()(name, address, keep_address, lambda: set(self.claims), self._report, clock)
        self.ecu.add_ca(controller_application=self.ca)
        self.ca.subscribe(self._on_message)
        self.ca.subscribe_request(self._on_request)

        sim = self

        class Watch(can.Listener):
            def on_message_received(self, msg):
                sim._watch(msg)

        self._notifier = can.Notifier(bus, [MessageListener(self.ecu), Watch()], timeout=0.1)

    # -- state

    @property
    def claimed(self):
        import j1939
        return self.ca.state == j1939.ControllerApplication.State.NORMAL

    @property
    def address(self):
        return self.ca.device_address if self.claimed else None

    def wait_claimed(self, timeout):
        deadline = time.monotonic() + timeout
        while not self.claimed and time.monotonic() < deadline:
            time.sleep(0.01)
        return self.claimed

    # -- running

    def start(self):
        self._t0 = self.clock()
        self._thread = threading.Thread(target=self._run, name="j1939-sim", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(2)
        try:
            self._notifier.stop(1)
        except Exception:  # the bus already gone
            pass
        self.ecu.stop()

    def _run(self):
        while not self._stop.wait(TICK_S):
            now = self.clock()
            self.ca.tick(now)
            if not self.claimed:
                for p in self.plans:
                    p.next_due = None
                continue
            for p in self.plans:
                if not p.period_s:
                    continue
                if p.next_due is None:
                    p.next_due = now
                if now >= p.next_due:
                    self.send(p)
                    p.next_due += p.period_s
                    if p.next_due < now:
                        p.next_due = now + p.period_s  # late: no burst to catch up

    def send(self, plan, destination=None):
        """Sends `plan`'s message now (to `destination` for a PDU1 message,
        default its DBC destination). False when not sent."""
        if not self.claimed:
            return False
        data = list(plan.payload(self.clock() - self._t0))
        ps = plan.ps if not plan.pdu1 or destination is None else destination
        try:
            ok = self.ca.send_pgn(plan.dp, plan.pf, ps, plan.priority, data)
        except RuntimeError:  # the address was lost meanwhile
            return False
        if ok is False:
            if not plan.busy_noted:
                plan.busy_noted = True
                self._report("busy", "%s not sent: its previous transport protocol transfer is still running"
                             % plan.message.name, pgn=plan.pgn)
            return False
        plan.sent += 1
        return True

    # -- bus

    def _send_frame(self, can_id, extended_id, data, fd_format=False):
        import can
        msg = can.Message(arbitration_id=can_id, is_extended_id=extended_id, data=bytes(data))
        try:
            with self._send_lock:
                self.bus.send(msg)
        except can.CanError as e:
            self.send_errors += 1
            if self.send_errors == 1:
                self._report("send_error", "Cannot send on the bus: %s" % e)

    def _report(self, event, text, **fields):
        try:
            self.report(event, text, **fields)
        except Exception:  # a broken report must not stop the bus threads
            pass

    def _watch(self, msg):
        """Address claims of the other ECUs (can-j1939 does not pass them on)."""
        fid = msg.arbitration_id
        if not msg.is_extended_id or msg.is_error_frame or (fid >> 16) & 0xFF != CLAIM_PF or len(msg.data) < 8:
            return
        sa, name = fid & 0xFF, int.from_bytes(bytes(msg.data[:8]), "little")
        if sa == NULL:
            for a, n in list(self.claims.items()):
                if n == name:
                    del self.claims[a]
            self._report("claim_seen", "Cannot Claim from NAME %s" % name_text(name), address=None,
                         name=name_text(name))
            return
        for a, n in list(self.claims.items()):
            if n == name and a != sa:
                del self.claims[a]  # moved
        self.claims[sa] = name
        self._report("claim_seen", "Address claim from %d: NAME %s" % (sa, name_text(name)), address=sa,
                     name=name_text(name))

    def _on_message(self, priority, pgn, sa, timestamp, data):
        messages = self._rx.get(pgn)
        if not messages:
            return
        msg = next((m for m in messages if m.frame_id & 0xFF == sa), messages[0])
        self.received += 1
        try:
            values = msg.decode(bytes(data), decode_choices=False, allow_truncated=True)
        except Exception as e:  # cantools: wrong length, bad multiplexer, ...
            self._report("rx", "PGN %d from %d: cannot decode %s: %s" % (pgn, sa, msg.name, e), pgn=pgn, source=sa,
                         message=msg.name, data=bytes(data).hex(), error=str(e))
            return
        text = " ".join("%s=%s" % (k, fmt_value(v)) for k, v in values.items())
        self._report("rx", "PGN %d from %d: %s" % (pgn, sa, text), pgn=pgn, source=sa, message=msg.name,
                     signals=values, data=bytes(data).hex())

    def _on_request(self, src, dest, pgn):
        plan = self._by_pgn.get(pgn)
        if plan is not None:
            to = GLOBAL if dest == GLOBAL else src
            sent = self.send(plan, destination=to)
            self._report("request", "Request for PGN %d from %d: %s %s" % (
                pgn, src, "sent" if sent else "could not send", plan.message.name), pgn=pgn, source=src,
                answered=bool(sent))
            return
        if dest == GLOBAL:
            return  # a global request for a PGN we do not send gets no answer
        data = [ACK_NACK, 0xFF, 0xFF, 0xFF, src, pgn & 0xFF, (pgn >> 8) & 0xFF, (pgn >> 16) & 0xFF]
        try:
            self.ca.send_pgn(0, PGN_ACK >> 8, GLOBAL, 6, data)
        except RuntimeError:
            return
        self._report("request", "Request for PGN %d from %d: not sent here, NACK" % (pgn, src), pgn=pgn, source=src,
                     answered=False)


# ---------------------------------------------------------------------------
# Command line

EPILOG = """\
examples:
  %(prog)s --dbc machine.dbc --node Engine --interface vcan0 --address 0
  %(prog)s --dbc machine.dbc --node Engine --adapter slcan:/dev/tty.usbmodem1 --bitrate 250000
  %(prog)s --dbc machine.dbc --node PLC --interface vcan0 --log plc.jsonl --duration 10
  %(prog)s --contend 128 --name-value 0x100 --interface vcan0

The simulator claims its address, then sends every DBC message whose sender
is --node at its GenMsgCycleTime (messages without one only on request).
Signal values ramp from the DBC minimum to the maximum over --ramp-period
seconds and start again, kept below J1939's "error" and "not available"
values, unless a scenario says otherwise. Messages over 8 bytes go through
the transport protocol: BAM when broadcast, RTS/CTS to one address.
Requests (PGN 59904) for those PGNs, to its address or global, are answered;
requests to its address for any other PGN get a NACK.

Every received message the DBC defines is printed decoded, e.g.
"PGN 65281 from 128: Setpoint=500 Run=1"; with --log also written to FILE as
one JSON object per line ({"event": "rx", "pgn", "source", "message",
"signals", ...}), together with the claims and requests.

NAME: --name-value N (64-bit, 0x... allowed), or the NAME field options.
Default: not arbitrary address capable, identity number 0x10000 + the
address, every other field 0 (NAME value 0x10000 + address). A simulator
that loses its address moves to the next free one in 128..247 when its NAME
is arbitrary address capable, else it sends Cannot Claim and goes silent.

--contend ADDRESS --name-value N claims ADDRESS with that NAME and keeps it
(never moves; Cannot Claim when it loses), for claim tests: with a NAME
lower than the PLC's the PLC must move. --dbc and --node are optional then.

Stops on Ctrl-C, SIGTERM or after --duration seconds.

""" + SCENARIO_HELP


def _address(text):
    try:
        v = int(text, 0)
    except ValueError:
        raise argparse.ArgumentTypeError("%r is not an address" % text)
    if not 0 <= v <= 253:
        raise argparse.ArgumentTypeError("address %d: give 0..253" % v)
    return v


def _name_value(text):
    try:
        v = int(text, 0)
    except ValueError:
        raise argparse.ArgumentTypeError("%r is not a 64-bit NAME" % text)
    if not 0 < v < 1 << 64:
        raise argparse.ArgumentTypeError("NAME %s: give 1..0xFFFFFFFFFFFFFFFF" % text)
    return v


def _field(bits):
    def parse(text):
        try:
            v = int(text, 0)
        except ValueError:
            raise argparse.ArgumentTypeError("%r is not a number" % text)
        if not 0 <= v < 1 << bits:
            raise argparse.ArgumentTypeError("%d does not fit %d bits" % (v, bits))
        return v
    return parse


def _seconds(text):
    try:
        v = float(text)
    except ValueError:
        raise argparse.ArgumentTypeError("%r is not a number of seconds" % text)
    if v <= 0:
        raise argparse.ArgumentTypeError("give seconds above 0")
    return v


def parser():
    p = argparse.ArgumentParser(prog=PROG, description="Simulates one J1939 ECU from a DBC file on a SocketCAN "
                                "interface or a USB CAN adapter.", epilog=EPILOG,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dbc", metavar="FILE", help="the DBC file (J1939 messages, 29-bit identifiers)")
    p.add_argument("--node", metavar="NAME", help="the DBC node to simulate (sender of the messages it sends)")
    bus = p.add_mutually_exclusive_group(required=True)
    bus.add_argument("--interface", metavar="IFACE", help="a SocketCAN interface: vcan0, can0")
    bus.add_argument("--adapter", metavar="TYPE:CHANNEL", help="a USB adapter: slcan:PORT (slcan:COM5, "
                     "slcan:/dev/tty.usbmodem1), gs_usb:N, socketcan:can0")
    p.add_argument("--bitrate", type=int, default=DEFAULT_BITRATE, help="bit/s (default %(default)s)")
    p.add_argument("--address", type=_address, help="source address to claim (default: the source address of "
                   "the node's messages in the DBC)")
    p.add_argument("--contend", type=_address, metavar="ADDRESS", help="claim ADDRESS with --name-value and keep "
                   "it (contention tests)")
    p.add_argument("--name-value", type=_name_value, metavar="N", help="the 64-bit NAME")
    for opt, _key, bits in NAME_FIELDS:
        p.add_argument("--" + opt, type=_field(bits), metavar="N", help="NAME field (%d bits)" % bits)
    p.add_argument("--arbitrary-address-capable", action="store_true", help="NAME field: may move to another "
                   "address when it loses its claim")
    p.add_argument("--scenario", metavar="FILE", help="signal values and periods (JSON, see below)")
    p.add_argument("--ramp-period", type=_seconds, default=DEFAULT_RAMP_S, metavar="S",
                   help="seconds of one ramp from minimum to maximum (default %(default)s)")
    p.add_argument("--log", metavar="FILE", help="also write every event as a JSON line to FILE")
    p.add_argument("--duration", type=_seconds, metavar="S", help="stop after S seconds")
    return p


def _name_fields(args):
    fields = {key: getattr(args, opt.replace("-", "_")) for opt, key, _bits in NAME_FIELDS
              if getattr(args, opt.replace("-", "_")) is not None}
    if args.arbitrary_address_capable:
        fields["arbitrary_address_capable"] = 1
    return fields


def setup(args):
    """(db, plans, address, name) from the parsed options. Raises SimError."""
    fields = _name_fields(args)
    if args.name_value is not None and fields:
        raise SimError("give --name-value or the NAME field options, not both")
    if args.contend is not None:
        if args.address is not None:
            raise SimError("give --contend ADDRESS or --address, not both")
        if args.name_value is None:
            raise SimError("--contend needs --name-value: the NAME to claim the address with")
    elif not args.node:
        raise SimError("give --node: the DBC node to simulate")
    if args.node and not args.dbc:
        raise SimError("--node needs --dbc")
    if args.scenario and not args.node:
        raise SimError("--scenario needs --node")
    db = load_dbc(args.dbc) if args.dbc else None
    sends = []
    if args.node:
        node_messages(db, args.node)  # checks the node
        scenario = load_scenario(args.scenario, db, args.node) if args.scenario else None
        sends = plans(db, args.node, scenario, args.ramp_period)
    address = args.contend if args.contend is not None else args.address
    if address is None:
        address = default_address(db, args.node)
    return db, sends, address, make_name(args.name_value, fields, address)


class _Output:
    """A readable line on stdout per event; with a log file also a JSON line."""

    def __init__(self, path=None):
        self._lock = threading.Lock()
        self._log = open(path, "a", encoding="utf-8") if path else None

    def __call__(self, event, text, **fields):
        with self._lock:
            print(text, flush=True)
            if self._log:
                record = {"time": round(time.time(), 3), "event": event}
                record.update(fields)
                self._log.write(json.dumps(record, default=str) + "\n")
                self._log.flush()

    def close(self):
        if self._log:
            self._log.close()


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        db, sends, address, name = setup(args)
    except SimError as e:
        print("%s: %s" % (PROG, e), file=sys.stderr)
        return 2
    except ValueError as e:  # j1939.Name
        print("%s: NAME: %s" % (PROG, e), file=sys.stderr)
        return 2

    from ..localbus import adapter
    try:
        spec = adapter.parse("socketcan:" + args.interface if args.interface else args.adapter)
        opened = adapter.open(spec, args.bitrate, shared=True)
    except adapter.AdapterError as e:
        print("%s: %s" % (PROG, e), file=sys.stderr)
        return 2 if e.kind == "usage" else 1

    try:
        out = _Output(args.log)
    except OSError as e:
        opened.close()
        print("%s: cannot write log %s: %s" % (PROG, args.log, e.strerror or e), file=sys.stderr)
        return 2
    sim = Simulator(opened.bus, address, name, db, sends, keep_address=args.contend is not None, report=out)
    done = threading.Event()
    previous = signal_mod.signal(signal_mod.SIGTERM, lambda *a: done.set()) \
        if threading.current_thread() is threading.main_thread() else None
    who = args.node or "contender"
    print("%s on %s: address %d, NAME %s%s" % (who, spec, address, name_text(name.value), "; keeps the address"
                                                 if args.contend is not None else ""), flush=True)
    for p in sends:
        print("  sends %s" % p.describe(), flush=True)
    sim.start()
    end = time.monotonic() + args.duration if args.duration else None
    try:
        # Short waits: a wait without timeout misses Ctrl-C on Windows.
        while not done.wait(0.2 if end is None else max(0.0, min(0.2, end - time.monotonic()))):
            if end is not None and time.monotonic() >= end:
                break
    except KeyboardInterrupt:
        pass
    finally:
        sim.stop()
        opened.close()
        if previous is not None:
            signal_mod.signal(signal_mod.SIGTERM, previous)
        print("Stopped: sent %d messages, received %d the DBC defines" % (
            sum(p.sent for p in sends), sim.received), flush=True)
        out.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
