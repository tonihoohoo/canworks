"""The open adapter shared by every LocalBus handle in this process: one
receive thread, one transmit path, what the bus showed (heartbeats, EMCY,
another master), and the trace ring.

The PC is a guest on the bus (canopen-local-bus): nothing is sent until an
operation asks, except the bit rate check's one probe on a silent bus
(check_bitrate); the first frame waits until the adapter has listened for
LISTEN_S, and nothing here ever sends SYNC, heartbeat, TIME or broadcast NMT.

Bus errors after the check (bus-off, error passive, or a run of error frames
with no valid frame) end the connection: `error` says why and the adapter is
closed.
"""

import collections
import queue
import threading
import time

from ..bustrace.model import Frame
from . import adapter as adapter_mod

LISTEN_S = 1.0  # listen before the first transmit
OTHER_MASTER_S = 30.0  # another master counts as active this long after its last frame
FOREIGN_SDO_S = 0.2  # wait this long after another client's SDO request to a node
TRACE_FRAMES = 65536
EMCY_HISTORY = 16
ECHO_S = 0.5  # an adapter that echoes its frames: no echo this long means it stopped sending
PROBE_S = 0.2  # the bit rate check waits this long after its probe for an echo or error frames
CHECK_SDO_S = 0.5  # ... and this long for the node's answer to its SDO read
ERROR_BURST = 10  # error frames within ERROR_WINDOW_S with no valid frame end the connection
ERROR_WINDOW_S = 1.0

# Error frame identifier bits (linux/can/error.h), as python-can gives them.
ERR_CRTL = 0x004
ERR_PROT = 0x008
ERR_ACK = 0x020
ERR_BUSOFF = 0x040
CRTL_PASSIVE = 0x10 | 0x20  # data[1]: RX or TX error passive

NMT_COB = 0x000
SYNC_COB = 0x080
TIME_COB = 0x100
LSS_TX_COB = 0x7E5  # master -> devices
LSS_RX_COB = 0x7E4  # devices -> master


def iso(t):
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(t)) + ".%03dZ" % int((t % 1) * 1000)


def _sleep_until(deadline):
    """Sleeps until time.monotonic() reaches `deadline`. One sleep is not
    enough on Windows: time.sleep is finer than the monotonic clock there
    (15.6 ms ticks), so it can end a tick before the deadline reads as past."""
    while True:
        wait = deadline - time.monotonic()
        if wait <= 0:
            return
        time.sleep(wait)


class BitrateRefused(adapter_mod.AdapterError):
    def __init__(self, message):
        super().__init__("bitrate", message)


class Core:
    def __init__(self, opened, listen_s=LISTEN_S):
        self.opened = opened
        self.spec = opened.spec
        self.bus = opened.bus
        self.bitrate = opened.bitrate
        self.started = time.monotonic()
        self.started_wall = time.time()
        self.listen_s = listen_s
        self.listen_until = self.started + listen_s
        self.lock = threading.Lock()
        self.tx_lock = threading.Lock()
        self.waiters = collections.defaultdict(list)  # COB-ID -> [Queue]
        self.listeners = collections.defaultdict(list)  # COB-ID -> [fn(data, monotonic, wall)] (PDO test)
        self.heard = {}  # node -> {"state", "at", "at_wall"}
        self.emcy = {}  # node -> {"history": deque, "count"}
        self.other = None  # {"what", "first_at", "last", "last_at"}
        self.foreign_sdo = {}  # node -> monotonic time of another client's last SDO request
        self.ring = collections.deque(maxlen=TRACE_FRAMES)  # (seq, record bytes, raw id, error frame)
        self.seq = 0
        self.tracers = 0
        self.error = None  # why the receive thread ended
        self.users = 0
        self.echo_waiters = []  # [cob, data, Event] of frames sent and not echoed yet
        self.valid = 0  # valid frames received (not echoes)
        self.valid_at = None
        self.errors = collections.deque(maxlen=256)  # (monotonic time, identifier, data) of error frames
        self.error_frames = 0  # error frames received since opening
        self.checked = False  # the bit rate check passed: bus errors now end the connection
        self.bitrate_check = None
        self._closed = False
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._rx, name="canopen-localbus-rx", daemon=True)
        self._thread.start()

    # -- life -----------------------------------------------------------------
    def close(self):
        self._stop.set()
        if self._thread is not threading.current_thread():
            self._thread.join(timeout=2)
        self._close_adapter()

    def _close_adapter(self):
        with self.lock:
            if self._closed:
                return
            self._closed = True
        self.opened.close()

    def end(self, reason):
        """Ends the connection: every later request answers `reason`, and
        the adapter is closed."""
        if self.error is None:
            self.error = "connection ended: %s" % reason
        self._stop.set()
        for w in list(self.echo_waiters):
            w[2].set()
        self._close_adapter()

    @property
    def alive(self):
        return self._thread.is_alive() and self.error is None

    # -- receive --------------------------------------------------------------
    def _rx(self):
        while not self._stop.is_set():
            try:
                msg = self.bus.recv(0.1)
            except Exception as e:  # the adapter went away
                if not self._stop.is_set():
                    self.end("adapter %s stopped: %s" % (self.spec, e))
                return
            if msg is None:
                continue
            try:
                self._handle(msg)
            except Exception:  # never let one odd frame end the thread
                pass

    def _stamp(self, msg):
        t = getattr(msg, "timestamp", 0) or 0
        now = time.time()
        # Some adapters give time since their own start; the trace wants UTC.
        return t if abs(t - now) < 3600 else now

    def _record(self, msg, tx):
        if not self.tracers:
            return
        err = bool(getattr(msg, "is_error_frame", False))
        f = Frame(int(self._stamp(msg) * 1e6), msg.arbitration_id, bytes(msg.data or b""),
                  ext=bool(msg.is_extended_id), rtr=bool(msg.is_remote_frame), err=err, tx=tx,
                  dlc=msg.dlc)
        with self.lock:
            self.seq += 1
            self.ring.append((self.seq, f.pack(), msg.arbitration_id, err))

    def _echo(self, msg):
        """A frame this adapter sent, handed back (gs_usb): it is out on the
        bus. Never a received frame."""
        data = bytes(msg.data or b"")
        with self.lock:
            for w in self.echo_waiters:
                if w[0] == msg.arbitration_id and w[1] == data:
                    self.echo_waiters.remove(w)
                    w[2].set()
                    break
        self._record(msg, True)

    def _bus_error(self, msg):
        now = time.monotonic()
        data = bytes(msg.data or b"")
        with self.lock:
            self.errors.append((now, msg.arbitration_id, data))
            self.error_frames += 1
            recent = [e for e in self.errors if now - e[0] <= ERROR_WINDOW_S]
            valid_since = self.valid_at is not None and now - self.valid_at <= ERROR_WINDOW_S
        if not self.checked:
            return
        ident = msg.arbitration_id
        if ident & ERR_BUSOFF:
            self.end("the adapter went bus-off: the bit rate may be wrong, or the bus is not terminated")
        elif ident & ERR_CRTL and len(data) > 1 and data[1] & CRTL_PASSIVE:
            self.end("the adapter went error passive: the bit rate may be wrong, or no device acknowledges")
        elif len(recent) >= ERROR_BURST and not valid_since:
            self.end("%d error frames in %g s and no valid frame: the bus does not run at %d kbit/s, or the "
                     "wiring is wrong" % (len(recent), ERROR_WINDOW_S, self.bitrate // 1000))

    def _handle(self, msg):
        if self.opened.echoes and getattr(msg, "is_rx", True) is False:
            self._echo(msg)
            return
        self._record(msg, False)
        if msg.is_error_frame:
            self._bus_error(msg)
            return
        with self.lock:
            self.valid += 1
            self.valid_at = time.monotonic()
        if msg.is_extended_id or msg.is_remote_frame:
            return
        cob = msg.arbitration_id
        data = bytes(msg.data or b"")
        now, wall = time.monotonic(), time.time()
        for q in list(self.waiters.get(cob, ())):
            q.put(data)
        for fn in list(self.listeners.get(cob, ())):
            fn(data, now, wall)
        if cob == NMT_COB and len(data) >= 2:
            self._other_master("NMT command 0x%02X to %s" % (data[0], "all nodes" if data[1] == 0
                                                               else "node %d" % data[1]), now, wall)
        elif cob == SYNC_COB and len(data) <= 1:
            self._other_master("SYNC", now, wall)
        elif cob == TIME_COB and len(data) == 6:
            self._other_master("TIME", now, wall)
        elif 0x081 <= cob <= 0x0FF and len(data) == 8:
            node = cob - 0x080
            code = data[0] | data[1] << 8
            with self.lock:
                e = self.emcy.setdefault(node, {"history": collections.deque(maxlen=EMCY_HISTORY), "count": 0})
                e["history"].appendleft({"time": iso(wall), "code": code, "error_register": data[2],
                                         "manufacturer": " ".join("%02X" % b for b in data[3:8])})
                e["count"] += 1
                e["last"] = (code, data[2])
        elif 0x601 <= cob <= 0x67F:
            node = cob - 0x600
            with self.lock:
                self.foreign_sdo[node] = now
            self._other_master("SDO request to node %d" % node, now, wall)
        elif 0x701 <= cob <= 0x77F and len(data) >= 1:
            node = cob - 0x700
            with self.lock:
                self.heard[node] = {"state": data[0] & 0x7F, "at": now, "at_wall": wall}

    def _other_master(self, what, now, wall):
        with self.lock:
            if self.other is None or now - self.other["last"] > OTHER_MASTER_S:
                self.other = {"what": what, "first_at": iso(wall), "last": now, "last_at": iso(wall)}
            else:
                self.other.update(what=what, last=now, last_at=iso(wall))

    def other_master(self):
        """What another master sent recently (a dict), or None."""
        with self.lock:
            if self.other and time.monotonic() - self.other["last"] <= OTHER_MASTER_S:
                return {k: v for k, v in self.other.items() if k != "last"}
            return None

    # -- waiting for answers ---------------------------------------------------
    class _Expect:
        def __init__(self, core, cob):
            self.core, self.cob, self.q = core, cob, queue.Queue()

        def __enter__(self):
            # Frames heard while the adapter still listens are another client's
            # (no transmit before then): waiting first keeps them out of the queue.
            self.core.wait_listened()
            with self.core.lock:
                self.core.waiters[self.cob].append(self.q)
            return self

        def __exit__(self, *exc):
            with self.core.lock:
                self.core.waiters[self.cob].remove(self.q)

        def get(self, timeout):
            """The next frame's data on this COB-ID, or None after `timeout` s."""
            try:
                return self.q.get(timeout=max(0.0, timeout))
            except queue.Empty:
                return None

        def drain(self):
            while not self.q.empty():
                self.q.get_nowait()

    def listen(self, cob, fn):
        """Calls fn(data, monotonic time, wall time) for each frame on `cob`
        until unlisten(cob, fn); fn runs in the receive thread."""
        with self.lock:
            self.listeners[cob].append(fn)

    def unlisten(self, cob, fn):
        with self.lock:
            if fn in self.listeners.get(cob, ()):
                self.listeners[cob].remove(fn)

    def expect(self, cob):
        """with core.expect(0x585) as rx: ... rx.get(timeout)"""
        return Core._Expect(self, cob)

    # -- transmit ---------------------------------------------------------------
    def transmit(self, cob, data, ext=False, rtr=False, dlc=None):
        """The one transmit path: waits until the adapter has listened, sends,
        and records the frame (Tx) in the trace. A remote frame (rtr) has no
        data and `dlc`."""
        import can
        if self.error:
            raise adapter_mod.AdapterError("unreachable", self.error)
        self.wait_listened()
        if rtr:
            msg = can.Message(arbitration_id=cob, is_extended_id=bool(ext), is_remote_frame=True, dlc=dlc or 0)
        else:
            msg = can.Message(arbitration_id=cob, data=bytes(data), is_extended_id=bool(ext))
        self.send(msg)

    def send(self, msg, wait_echo=True):
        """Sends `msg` on the adapter. On an adapter that echoes its frames,
        waits for the echo (it is recorded in the trace then) and ends the
        connection when it does not come: the adapter stopped sending."""
        waiter = None
        if self.opened.echoes:
            waiter = [msg.arbitration_id, bytes(msg.data or b""), threading.Event()]
            with self.lock:
                self.echo_waiters.append(waiter)
        with self.tx_lock:
            try:
                self.bus.send(msg, timeout=0.5)
            except Exception as e:
                if waiter is not None:
                    with self.lock:
                        if waiter in self.echo_waiters:
                            self.echo_waiters.remove(waiter)
                if self.opened.echoes and self.checked:
                    self.end("adapter %s stopped sending: %s" % (self.spec, e))
                raise adapter_mod.AdapterError("unreachable", "adapter %s could not send: %s" % (self.spec, e))
        if waiter is None:
            msg.timestamp = time.time()
            self._record(msg, True)
            return True
        if not wait_echo:
            return waiter
        if not waiter[2].wait(ECHO_S) or self.error:
            with self.lock:
                if waiter in self.echo_waiters:
                    self.echo_waiters.remove(waiter)
            if self.error:
                raise adapter_mod.AdapterError("unreachable", self.error)
            if self.checked:
                self.end("adapter %s stopped sending (a frame it was given did not go out within %g s); unplug "
                         "it and plug it in again if it stays so" % (self.spec, ECHO_S))
            raise adapter_mod.AdapterError("unreachable", self.error or "adapter %s could not send" % self.spec)
        return True

    def wait_listened(self):
        """Until the adapter has listened LISTEN_S: what the bus shows (another
        master, heartbeats) is known only then."""
        _sleep_until(self.listen_until)

    def wait_foreign_sdo(self, node):
        """Let another client's SDO transfer to `node` end before ours starts."""
        self.wait_listened()
        with self.lock:
            t = self.foreign_sdo.get(node)
        if t is not None:
            _sleep_until(t + FOREIGN_SDO_S)

    # -- trace ------------------------------------------------------------------
    def trace_add(self):
        with self.lock:
            self.tracers += 1
            return self.seq

    def trace_remove(self):
        with self.lock:
            self.tracers = max(0, self.tracers - 1)

    def trace_read(self, after, limit, filters, error_frames):
        """Records after sequence number `after`: (records, next, more, lost)."""
        with self.lock:
            ring = list(self.ring)
        if not ring:
            return [], after, False, 0
        oldest = ring[0][0]
        lost = max(0, oldest - after - 1)
        out, nxt, more = [], after, False
        for seq, rec, raw, err in ring:
            if seq <= after:
                continue
            if len(out) >= limit:
                more = True
                break
            nxt = seq
            if err and not error_frames:
                continue
            if filters and not err and not any((raw & m) == (i & m) for i, m in filters):
                continue
            out.append(rec)
        return out, nxt, more, lost



# ---------------------------------------------------------------------------
# The bit rate check (canopen-local-bus, "Bit rate check on connect")

LSS_INQUIRE_NODE_ID = bytes([0x5E]) + bytes(7)  # answered only by a device in LSS configuration mode


def _errors_since(core, t0):
    with core.lock:
        return [e for e in core.errors if e[0] >= t0]


def _wrong(core, errors):
    """The refusal text for `errors` after the probe: acknowledge errors only
    (no device at this rate), or errors of a bus at another rate."""
    kbit = core.bitrate // 1000
    if errors and not all(e[1] & ERR_ACK and not (e[1] & ERR_PROT and len(e[2]) > 2 and e[2][2])
                          for e in errors):
        return "the bus does not run at %d kbit/s (error frames when the adapter sent its probe)" % kbit
    return ("no device acknowledged at %d kbit/s: the bit rate is wrong, or no device is powered and connected"
            % kbit)


def check_bitrate(core, check_node=None):
    """Checks that the bus runs at the core's bit rate; raises BitrateRefused
    when it does not. Listens LISTEN_S first (listen-only where the adapter
    can): valid frames and no more than 1 % error frames confirm the rate,
    error frames refuse it. On a silent bus one LSS "inquire node ID" frame is
    sent once (one-shot on gs_usb) and must get out with no error frame; an
    adapter that cannot tell (slcan) reads 0x1000 from `check_node` instead.
    Sets core.bitrate_check, leaves the adapter in normal mode, and from then
    on bus errors end the connection."""
    import can
    kbit = core.bitrate // 1000
    opened = core.opened
    core.wait_listened()
    with core.lock:
        valid, errors = core.valid, len(core.errors)
    how = None
    if errors and (not valid or errors * 100 > valid):
        raise BitrateRefused("the bus does not run at %d kbit/s (%d error frame%s and %d valid frame%s in %g s)"
                             % (kbit, errors, "" if errors == 1 else "s", valid, "" if valid == 1 else "s",
                                core.listen_s))
    if valid:
        how = "traffic"
        if opened.listen_only:
            opened.set_mode(listen_only=False)
    elif opened.confirm is None:
        if check_node is None:
            raise BitrateRefused(
                "nothing was heard at %d kbit/s, and adapter %s cannot tell whether a frame it sends is "
                "acknowledged: give the device's node ID to check the bit rate with one SDO read (--check-node N, "
                "or the node ID field in Bus and master)" % (kbit, core.spec))
        from . import sdo as sdo_mod
        if opened.listen_only:
            opened.set_mode(listen_only=False)
        t0 = time.monotonic()
        try:
            sdo_mod.upload(core, check_node, 0x1000, 0, CHECK_SDO_S)
        except sdo_mod.SdoAbort:
            pass  # an abort is an answer too
        except sdo_mod.SdoTimeout:
            errs = _errors_since(core, t0)
            if errs:
                raise BitrateRefused(_wrong(core, errs))
            raise BitrateRefused("node %d did not answer at %d kbit/s: the bit rate is wrong, or the device is not "
                                 "powered and connected" % (check_node, kbit))
        how = "node %d answered" % check_node
    else:
        opened.set_mode(listen_only=False, one_shot=True)
        t0 = time.monotonic()
        msg = can.Message(arbitration_id=LSS_TX_COB, data=LSS_INQUIRE_NODE_ID, is_extended_id=False)
        try:
            waiter = core.send(msg, wait_echo=False)
        except adapter_mod.AdapterError:
            raise BitrateRefused(_wrong(core, _errors_since(core, t0)))
        time.sleep(PROBE_S)
        errs = _errors_since(core, t0)
        echoed = waiter is True or (waiter[2].is_set() and not core.error)
        if errs or not echoed:
            raise BitrateRefused(_wrong(core, errs))
        opened.set_mode(listen_only=False)
        how = "probe acknowledged"
    core.bitrate_check = {"result": "confirmed", "how": how, "bitrate_kbit": kbit}
    with core.lock:
        core.errors.clear()
    core.checked = True

# ---------------------------------------------------------------------------
# One open adapter per spec in this process, shared by its handles.

_cores = {}
_cores_lock = threading.Lock()


def acquire(spec, bitrate, listen_s=LISTEN_S, check_node=None):
    """The process's Core for `spec`, opened at `bitrate` and its bit rate
    checked when it is not open yet. Raises AdapterError (busy when another
    tool has it, or when this process has it open at another bit rate;
    bitrate when the check refuses it)."""
    key = str(spec)
    with _cores_lock:
        core = _cores.get(key)
        if core is not None and not core.alive:
            core.close()
            del _cores[key]
            core = None
        if core is None:
            core = Core(adapter_mod.open(spec, bitrate, listen_only=True), listen_s)
            try:
                check_bitrate(core, check_node)
            except BaseException:
                core.close()
                raise
            _cores[key] = core
        elif spec.kind != "socketcan" and bitrate and core.bitrate != bitrate:
            raise adapter_mod.AdapterError("busy", "adapter %s is open at %d kbit/s here; close the other view "
                                                   "first" % (spec, core.bitrate // 1000))
        core.users += 1
        return core


def release(core):
    with _cores_lock:
        core.users -= 1
        if core.users <= 0:
            if _cores.get(str(core.spec)) is core:
                del _cores[str(core.spec)]
            core.close()
