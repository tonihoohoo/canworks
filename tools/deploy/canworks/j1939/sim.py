"""canworks-j1939-sim: one simulated J1939 ECU on a SocketCAN interface or a
USB CAN adapter (docs/j1939.md, "Simulator").

Built on can-j1939 (python package `j1939`: address claim, requests,
transport protocol BAM and RTS/CTS) over python-can, and on cantools for the
DBC. The simulator claims an address with its NAME, sends every DBC message
whose sender is the simulated node at its cycle time, answers requests for
those PGNs (and NACKs requests to its address for any other PGN), and
reports every received message the DBC defines, decoded. With --contend it
claims an address and keeps it: it never moves, so claim loss and defence of
another ECU (the PLC) can be tested. With trouble codes in the scenario
("dtcs") it plays a faulty ECU (J1939-73): DM1 every second and on change,
DM2 on request, DM3 and DM11 carried out and acknowledged (or refused with
--refuse-clear); every DM it receives is printed decoded.

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
DM1_PERIOD_S = 1.0  # DM1 every second, and on change at most once per second (J1939-73)
MAX_OC = 126  # the highest occurrence count (127: not available)

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
     "ComponentInfo": {"period_ms": 1000}},
   "dtcs": [{"spn": 520192, "fmi": 3, "lamps": ["amber"], "from_s": 5, "to_s": 20},
            {"spn": 520193, "fmi": 1, "lamps": ["red"], "flash": "fast", "from_s": 10}]}
  Messages are named as in the DBC and must be sent by --node. period_ms
  replaces the DBC cycle time (0: only on request). A signal is a constant,
  a ramp, a list of values each held step_s seconds, or a raw value; values
  are physical (scaled) and within the DBC range, raw values within the
  signal's bits (so "not available" can be sent). Signals not named ramp.
  dtcs: trouble codes, each active from from_s (default 0) to to_s seconds
  after start (default: to the end); lamps out of mil, red, amber, protect,
  flash slow or fast. With dtcs (even []) the simulator sends DM1 every
  second and on change, and answers Requests for DM1, DM2, DM3 and DM11. A
  scenario with only dtcs needs no --dbc or --node (give --address)."""

_SCENARIO_KEYS = ("ramp_period_s", "messages", "dtcs")
_MESSAGE_KEYS = ("period_ms", "signals")
_DTC_KEYS = ("spn", "fmi", "lamps", "flash", "from_s", "to_s")


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


class DtcPlan:
    """One scenario trouble code: active from `from_s` to `to_s` (None: to
    the end) seconds after start."""

    def __init__(self, spn, fmi, lamps=(), flash=None, from_s=0.0, to_s=None):
        self.spn, self.fmi, self.lamps, self.flash = spn, fmi, list(lamps), flash
        self.from_s, self.to_s = from_s, to_s

    def active(self, t):
        return t >= self.from_s and (self.to_s is None or t < self.to_s)


def _dtcs(value, where):
    from . import dm
    if not isinstance(value, list):
        raise SimError("%s: give a list of trouble codes" % where)
    out, seen = [], set()
    for i, c in enumerate(value):
        at = "%s[%d]" % (where, i)
        _keys(c, _DTC_KEYS, at)
        for key, top in (("spn", dm.MAX_SPN), ("fmi", 31)):
            v = c.get(key)
            if not isinstance(v, int) or isinstance(v, bool) or not 0 <= v <= top:
                raise SimError("%s.%s: give 0..%d" % (at, key, top))
        if (c["spn"], c["fmi"]) in seen:
            raise SimError("%s: SPN %d FMI %d is already in the list" % (at, c["spn"], c["fmi"]))
        seen.add((c["spn"], c["fmi"]))
        lamps = c.get("lamps", [])
        if not isinstance(lamps, list) or any(x not in dm.LAMP_BITS for x in lamps):
            raise SimError('%s.lamps: give a list out of "mil", "red", "amber" and "protect"' % at)
        flash = c.get("flash")
        if flash is not None and flash not in ("slow", "fast"):
            raise SimError('%s.flash: give "slow" or "fast"' % at)
        frm, to = c.get("from_s", 0), c.get("to_s")
        if not _number(frm) or frm < 0:
            raise SimError("%s.from_s: give seconds, 0 or more" % at)
        if to is not None and (not _number(to) or to <= frm):
            raise SimError("%s.to_s: give seconds after from_s" % at)
        out.append(DtcPlan(c["spn"], c["fmi"], lamps, flash, float(frm), None if to is None else float(to)))
    return out


def load_scenario(source, db, node):
    """A scenario (a file path or the parsed JSON) checked against the DBC:
    {"ramp_period_s": float or None, "messages": {name: {"period_ms": int or
    None, "signals": {signal name: source}}}, "dtcs": [DtcPlan] or None (no
    "dtcs" key)}. `db` and `node` may be None for a scenario without
    messages. Raises SimError."""
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
    dtcs = _dtcs(source["dtcs"], where + ": dtcs") if "dtcs" in source else None
    if db is None:
        if messages:
            raise SimError("%s: messages need --dbc and --node" % where)
        return {"ramp_period_s": ramp_period, "messages": {}, "dtcs": dtcs}
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
    return {"ramp_period_s": ramp_period, "messages": out, "dtcs": dtcs}


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


def mux_layout(message):
    """The mux.Layout of a cantools message (not multiplexed for a plain
    one, or one whose multiplexing the DBC does not say clearly)."""
    from ..raw import mux
    from ..raw.dbc import mux_fields
    fields, _ = mux_fields(message)
    defs = []
    for j, s in enumerate(message.signals):
        d = {"path": "signals[%d]" % j, "name": s.name, "start_bit": s.start, "length": s.length,
             "byte_order": "big" if s.byte_order == "big_endian" else "little", "signed": s.is_signed}
        d.update(fields.get(s.name, {}))
        defs.append(d)
    return mux.Layout.build(defs, [], [])


class Plan:
    """One message the simulator sends: identifier parts, period (None: only
    on request) and a value source per signal. A multiplexed message is sent
    as every page at each send (`mux` "all") or the next page (`mux`
    "rotate")."""

    def __init__(self, message, period_s, sources, mux="all"):
        from ..raw import mux as mux_mod
        self.message, self.period_s, self.sources = message, period_s, sources
        self.mux = mux
        self.layout = mux_layout(message)
        self.pages = []
        if self.layout.multiplexed:
            n = self.layout.page_count()
            if n > mux_mod.MAX_PAGES:
                raise SimError("%s has %d pages; the simulator sends at most %d" % (message.name, n,
                                                                                   mux_mod.MAX_PAGES))
            self.pages = self.layout.pages()
        self.next_page = 0
        fid = message.frame_id
        self.pgn = pgn_of(fid)
        self.priority = (fid >> 26) & 7
        self.dp, self.pf, self.ps = (fid >> 24) & 1, (fid >> 16) & 0xFF, (fid >> 8) & 0xFF
        self.next_due = None
        self.sent = 0
        self.pending = []  # pages of a cyclic send still to go (transport protocol busy)
        self.busy_noted = False

    @property
    def pdu1(self):
        return self.pf < 240

    def payload(self, t):
        raw = {name: src.raw(t) for name, src in self.sources.items()}
        return self.message.encode(raw, scaling=False, padding=True, strict=False)

    def page_payload(self, page, t):
        """The data of one page (values, active) of a multiplexed message:
        the page's switch values and its signals' sources; other bits 1."""
        from ..raw import signals as sig
        values, active = page
        data = bytearray(b"\xff" * self.message.length)
        for j, s in enumerate(self.message.signals):
            if not active[j]:
                continue
            v = values[j] if self.layout.is_switch[j] else self.sources[s.name].raw(t)
            sig.pack(data, s.start, s.length, int(v), s.byte_order == "big_endian")
        return bytes(data)

    def payloads(self, t):
        """The frames' data of one send: one, or for a multiplexed message
        every page ("all") or the next page ("rotate")."""
        if not self.pages:
            return [self.payload(t)]
        if self.mux == "rotate":
            page = self.pages[self.next_page % len(self.pages)]
            self.next_page = (self.next_page + 1) % len(self.pages)
            return [self.page_payload(page, t)]
        return [self.page_payload(page, t) for page in self.pages]

    def describe(self):
        when = "%d ms" % round(self.period_s * 1000) if self.period_s else "on request"
        if self.pages:
            when += ", %d pages%s" % (len(self.pages), " in turn" if self.mux == "rotate" else "")
        return "%s (PGN %d, %s)" % (self.message.name, self.pgn, when)


def plans(db, node, scenario=None, ramp_period=DEFAULT_RAMP_S, mux="all"):
    """What `node` sends: a Plan per DBC message it is the sender of
    (multiplexed messages page by page, `mux` "all" or "rotate")."""
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
        out.append(Plan(m, period_ms / 1000.0 if period_ms else None, sources, mux))
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
# Trouble codes


class DmState:
    """The simulated ECU's trouble codes (j1939-diagnostics, as the plugin
    keeps its own): the active set from the scenario's DtcPlans, an
    occurrence count per code (up to MAX_OC, +1 on each activation) and the
    previously active codes (a code that goes inactive, with its count)."""

    def __init__(self, plans):
        self.plans = list(plans)
        self.active = []    # (spn, fmi) in scenario order
        self.oc = {}        # (spn, fmi) -> occurrence count
        self.previous = {}  # (spn, fmi) -> occurrence count, in the order they went inactive

    def update(self, t):
        """Takes the scenario's state at `t` s; True when the active set changed."""
        now = [(p.spn, p.fmi) for p in self.plans if p.active(t)]
        if now == self.active:
            return False
        for key in now:
            if key not in self.active:
                self.oc[key] = min(MAX_OC, self.oc.get(key, 0) + 1)
                self.previous.pop(key, None)
        for key in self.active:
            if key not in now:
                self.previous[key] = self.oc.get(key, 0)
        self.active = now
        return True

    def _plan(self, key):
        return next(p for p in self.plans if (p.spn, p.fmi) == key)

    def lamps(self):
        from . import dm
        active = [self._plan(k) for k in self.active]
        lamps = 0
        for p in active:
            lamps |= dm.lamp_byte(p.lamps)
        return lamps, dm.flash_byte([(p.lamps, p.flash) for p in active])

    def dm1(self):
        from . import dm
        lamps, flash = self.lamps()
        return dm.build_dm(lamps, flash, [dm.Dtc(k[0], k[1], self.oc.get(k, 0)) for k in self.active])

    def dm2(self):
        from . import dm
        lamps, flash = self.lamps()
        return dm.build_dm(lamps, flash, [dm.Dtc(k[0], k[1], oc) for k, oc in self.previous.items()])

    def clear(self, previous_only):
        """DM3 (previous_only): forget the previously active codes; DM11:
        also every occurrence count, the active codes start again at 1."""
        self.previous.clear()
        if not previous_only:
            self.oc = {k: 1 for k in self.active}


def dm_text(name, data, spn_names=None):
    """A received DM1/DM2 as one line ("lamps; codes"), or None when malformed."""
    from . import dm
    lst = dm.parse_dm(data)
    if lst is None:
        return None, None
    codes = "; ".join(c.text((spn_names or {}).get(c.spn)) for c in lst.dtcs) or "no codes"
    return lst, "%s; %s" % (lst.lamps_text(), codes)


# ---------------------------------------------------------------------------
# The simulator


class Simulator:
    """One simulated ECU on an open python-can `bus`.

    report(event, text, **fields) gets every event: claims (own and seen),
    received messages the DBC defines ("rx"), requests answered and NACKed,
    received diagnostic messages ("dm") and clear requests ("dm_clear").

    `dtcs` (a list of DtcPlan, None: no trouble codes) makes it send DM1 and
    answer DM1/DM2/DM3/DM11 requests; `refuse_clear` answers DM3/DM11 with
    NACK.
    """

    def __init__(self, bus, address, name, db=None, plans=(), keep_address=False, report=None,
                 clock=time.monotonic, dtcs=None, refuse_clear=False):
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
        self._layouts = {}  # id(DBC message) -> mux.Layout
        self.dm = DmState(dtcs) if dtcs is not None else None
        self.refuse_clear = refuse_clear
        self.dm1_sent = 0
        self._dm_due = None  # the next periodic DM1
        self._dm_change = False  # a change not sent yet
        self._dm_change_at = None  # the last change-driven DM1
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
            if self.dm is not None and self.dm.update(now - self._t0):
                self._dm_change = True
            if not self.claimed:
                for p in self.plans:
                    p.next_due = None
                self._dm_due = None
                continue
            if self.dm is not None:
                self._dm_tick(now)
            for p in self.plans:
                if not p.period_s:
                    continue
                if p.next_due is None:
                    p.next_due = now
                # A message whose transfer cannot start yet (another BAM
                # from this address still running) goes on the next tick.
                if now >= p.next_due and self.send(p):
                    p.next_due += p.period_s
                    if p.next_due < now:
                        p.next_due = now + p.period_s  # late: no burst to catch up

    def _dm_tick(self, now):
        """DM1 every DM1_PERIOD_S, and once on a change but at most one
        change-driven DM1 per DM1_PERIOD_S."""
        if self._dm_change and (self._dm_change_at is None or now - self._dm_change_at >= DM1_PERIOD_S):
            if self.send_dm(1):  # else on a later tick: a transfer is still running
                self._dm_change, self._dm_change_at = False, now
                self._dm_due = now + DM1_PERIOD_S
        elif (self._dm_due is None or now >= self._dm_due) and self.send_dm(1):
            self._dm_due = now + DM1_PERIOD_S if self._dm_due is None or self._dm_due + DM1_PERIOD_S < now \
                else self._dm_due + DM1_PERIOD_S

    def send_dm(self, which):
        """Sends DM1 or DM2 (`which` 1 or 2) now; False when not sent."""
        from . import dm
        data = self.dm.dm1() if which == 1 else self.dm.dm2()
        pgn = dm.PGN_DM1 if which == 1 else dm.PGN_DM2
        try:
            ok = self.ca.send_pgn(0, pgn >> 8, pgn & 0xFF, 6, list(data))
        except RuntimeError:  # the address was lost meanwhile
            return False
        if ok is False:
            return False
        if which == 1:
            self.dm1_sent += 1
        return True

    def _send_ack(self, control, src, pgn):
        data = [control, 0xFF, 0xFF, 0xFF, src, pgn & 0xFF, (pgn >> 8) & 0xFF, (pgn >> 16) & 0xFF]
        try:
            self.ca.send_pgn(0, PGN_ACK >> 8, GLOBAL, 6, data)
        except RuntimeError:
            pass

    def _dm_request(self, src, dest, pgn):
        """A Request for DM1, DM2, DM3 or DM11 (to us or global)."""
        from . import dm
        name = dm.DM_PGNS[pgn]
        if pgn in (dm.PGN_DM1, dm.PGN_DM2):
            sent = self.send_dm(1 if pgn == dm.PGN_DM1 else 2)
            self._report("request", "Request for %s from %d: %s" % (name, src, "sent" if sent else "could not send"),
                         pgn=pgn, source=src, answered=bool(sent))
            return
        to_us = dest != GLOBAL
        if self.refuse_clear:
            if to_us:
                self._send_ack(ACK_NACK, src, pgn)
            self._report("dm_clear", "Request for %s (%s) from %d: refused%s" % (
                name, dm.DM_TITLES[name], src, ", NACK" if to_us else ""), dm=name, **{"from": src},
                result="nack", **({} if to_us else {"global": True}))
            return
        self.dm.clear(pgn == dm.PGN_DM3)
        if to_us:
            self._send_ack(0, src, pgn)
        self._report("dm_clear", "Request for %s (%s) from %d: done%s" % (
            name, dm.DM_TITLES[name], src, ", ACK" if to_us else " (global, no ACK)"), dm=name, **{"from": src},
            result="ack", **({} if to_us else {"global": True}))

    def send(self, plan, destination=None):
        """Sends `plan`'s message now (to `destination` for a PDU1 message,
        default its DBC destination). False when not (all) sent: one
        transport protocol transfer runs per address at a time (can-j1939),
        so a message longer than 8 bytes waits while another one is still
        going; the pages not sent stay pending for the next cyclic send."""
        if not self.claimed:
            return False
        ps = plan.ps if not plan.pdu1 or destination is None else destination
        cyclic = destination is None
        queue = (cyclic and plan.pending) or plan.payloads(self.clock() - self._t0)
        for i, data in enumerate(queue):
            try:
                ok = self.ca.send_pgn(plan.dp, plan.pf, ps, plan.priority, list(data))
            except RuntimeError:  # the address was lost meanwhile
                return False
            if ok is False:
                if cyclic:
                    plan.pending = queue[i:]
                if not plan.busy_noted:
                    plan.busy_noted = True
                    self._report("busy", "%s waits: another transport protocol transfer from this address is "
                                 "still running" % plan.message.name, pgn=plan.pgn)
                return False
            plan.sent += 1
        if cyclic:
            plan.pending = []
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
        from . import dm
        if pgn in (dm.PGN_DM1, dm.PGN_DM2):
            name = dm.DM_PGNS[pgn]
            lst, text = dm_text(name, data)
            if lst is None:
                self._report("dm", "%s from %d: malformed (%d bytes)" % (name, sa, len(data)), dm=name, source=sa,
                             data=bytes(data).hex())
            else:
                self._report("dm", "%s from %d: %s" % (name, sa, text), dm=name, source=sa, lamps=lst.lamps,
                             flash=lst.flash, dtcs=[c.as_dict() for c in lst.dtcs])
            return
        if pgn in (dm.PGN_DM13, dm.PGN_DM22):
            if pgn == dm.PGN_DM13:
                cmd = dm.parse_dm13(data)
                text = ", ".join("%s %s" % (k, v) for k, v in cmd.items() if not k.startswith("_")) or "no command"
            else:
                ctl, reason, code = dm.parse_dm22(data)
                text = "%s, SPN %d FMI %d%s" % (ctl, code.spn, code.fmi, ", " + reason if reason else "")
            name = dm.DM_PGNS[pgn]
            self._report("dm", "%s from %d: %s" % (name, sa, text), dm=name, source=sa, data=bytes(data).hex())
            return
        messages = self._rx.get(pgn)
        if not messages:
            return
        msg = next((m for m in messages if m.frame_id & 0xFF == sa), messages[0])
        self.received += 1
        layout = self._layouts.get(id(msg))
        if layout is None:
            layout = self._layouts[id(msg)] = mux_layout(msg)
        page = ""
        if layout.multiplexed:
            # Only the signals of the frame's page (cantools would refuse an
            # unknown page).
            from ..raw import signals as sig
            data = bytes(data)
            active, unknown, _, _ = layout.evaluate(data)
            page = layout.page_label(data)
            values = {}
            for j, s in enumerate(msg.signals):
                big = s.byte_order == "big_endian"
                if active[j] and sig.fits(s.start, s.length, big, len(data)):
                    raw = sig.unpack(data, s.start, s.length, big, s.is_signed)
                    values[s.name] = raw * s.scale + s.offset if (s.scale, s.offset) != (1, 0) else raw
            if page:
                page = "[%s%s] " % (page, " unknown" if unknown else "")
        else:
            try:
                values = msg.decode(bytes(data), decode_choices=False, allow_truncated=True)
            except Exception as e:  # cantools: wrong length, bad multiplexer, ...
                self._report("rx", "PGN %d from %d: cannot decode %s: %s" % (pgn, sa, msg.name, e), pgn=pgn,
                             source=sa, message=msg.name, data=bytes(data).hex(), error=str(e))
                return
        text = page + " ".join("%s=%s" % (k, fmt_value(v)) for k, v in values.items())
        self._report("rx", "PGN %d from %d: %s" % (pgn, sa, text), pgn=pgn, source=sa, message=msg.name,
                     signals=values, data=bytes(data).hex())

    def _on_request(self, src, dest, pgn):
        from . import dm
        if self.dm is not None and pgn in (dm.PGN_DM1, dm.PGN_DM2, dm.PGN_DM3, dm.PGN_DM11):
            self._dm_request(src, dest, pgn)
            return
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
the transport protocol: BAM when broadcast, RTS/CTS to one address. A
multiplexed message goes out as every one of its pages at each cycle, or
one page per cycle in turn with --mux rotate (requests likewise).
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

With "dtcs" in the scenario (see below) the simulator is a faulty ECU: it
sends DM1 (PGN 65226) every second and on change, answers Requests for DM1
and DM2, and carries out Requests for DM3 and DM11 to its address with an
ACK (global ones without), or NACKs them with --refuse-clear. Every DM1,
DM2, DM13 and DM22 it receives is printed decoded ("DM1 from 128: amber
warning on; SPN 520192 FMI 3 (...) OC 1"); --log adds {"event": "dm", "dm",
"source", "lamps", "flash", "dtcs"} and {"event": "dm_clear", "dm", "from",
"result"} lines.

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
    p.add_argument("--scenario", metavar="FILE", help="signal values and periods, trouble codes (JSON, see below)")
    p.add_argument("--refuse-clear", action="store_true", help="answer Requests for DM3 and DM11 with NACK and "
                   "keep the codes")
    p.add_argument("--mux", choices=("all", "rotate"), default="all",
                   help="multiplexed messages: every page at each cycle (all, default) or the next page (rotate)")
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
    """(db, plans, address, name, dtcs) from the parsed options; dtcs is the
    scenario's list of DtcPlan, None without "dtcs". Raises SimError."""
    fields = _name_fields(args)
    if args.name_value is not None and fields:
        raise SimError("give --name-value or the NAME field options, not both")
    if args.contend is not None:
        if args.address is not None:
            raise SimError("give --contend ADDRESS or --address, not both")
        if args.name_value is None:
            raise SimError("--contend needs --name-value: the NAME to claim the address with")
    elif not args.node and not (args.scenario and args.address is not None):
        raise SimError("give --node: the DBC node to simulate" if not args.scenario
                       else "give --node, or --address for a scenario with only trouble codes")
    if args.node and not args.dbc:
        raise SimError("--node needs --dbc")
    if args.scenario and not args.node and args.contend is not None:
        raise SimError("--scenario needs --node")
    db = load_dbc(args.dbc) if args.dbc else None
    sends, dtcs = [], None
    if args.node:
        node_messages(db, args.node)  # checks the node
        scenario = load_scenario(args.scenario, db, args.node) if args.scenario else None
        sends = plans(db, args.node, scenario, args.ramp_period, args.mux)
        dtcs = scenario["dtcs"] if scenario else None
    elif args.scenario:
        dtcs = load_scenario(args.scenario, None, None)["dtcs"]
    if args.refuse_clear and dtcs is None:
        raise SimError("--refuse-clear needs a scenario with dtcs")
    address = args.contend if args.contend is not None else args.address
    if address is None:
        address = default_address(db, args.node)
    return db, sends, address, make_name(args.name_value, fields, address), dtcs


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
        db, sends, address, name, dtcs = setup(args)
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
    sim = Simulator(opened.bus, address, name, db, sends, keep_address=args.contend is not None, report=out,
                    dtcs=dtcs, refuse_clear=args.refuse_clear)
    done = threading.Event()
    previous = signal_mod.signal(signal_mod.SIGTERM, lambda *a: done.set()) \
        if threading.current_thread() is threading.main_thread() else None
    who = args.node or ("contender" if args.contend is not None else "ECU")
    print("%s on %s: address %d, NAME %s%s" % (who, spec, address, name_text(name.value), "; keeps the address"
                                                 if args.contend is not None else ""), flush=True)
    for p in sends:
        print("  sends %s" % p.describe(), flush=True)
    if dtcs is not None:
        print("  sends DM1 every second and on change, %d trouble code%s in the scenario%s" % (
            len(dtcs), "" if len(dtcs) == 1 else "s", "; refuses clears" if args.refuse_clear else ""), flush=True)
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
        print("Stopped: sent %d messages%s, received %d the DBC defines" % (
            sum(p.sent for p in sends), " and %d DM1" % sim.dm1_sent if dtcs is not None else "", sim.received),
            flush=True)
        out.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
