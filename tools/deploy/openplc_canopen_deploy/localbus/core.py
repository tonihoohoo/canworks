"""The open adapter shared by every LocalBus handle in this process: one
receive thread, one transmit path, what the bus showed (heartbeats, EMCY,
another master), and the trace ring.

The PC is a guest on the bus (canopen-local-bus): nothing is sent until an
operation asks, the first frame waits until the adapter has listened for
LISTEN_S, and nothing here ever sends SYNC, heartbeat, TIME or broadcast NMT.
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

NMT_COB = 0x000
SYNC_COB = 0x080
TIME_COB = 0x100
LSS_TX_COB = 0x7E5  # master -> devices
LSS_RX_COB = 0x7E4  # devices -> master


def iso(t):
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(t)) + ".%03dZ" % int((t % 1) * 1000)


class Core:
    def __init__(self, opened, listen_s=LISTEN_S):
        self.opened = opened
        self.spec = opened.spec
        self.bus = opened.bus
        self.bitrate = opened.bitrate
        self.started = time.monotonic()
        self.started_wall = time.time()
        self.listen_until = self.started + listen_s
        self.lock = threading.Lock()
        self.tx_lock = threading.Lock()
        self.waiters = collections.defaultdict(list)  # COB-ID -> [Queue]
        self.heard = {}  # node -> {"state", "at", "at_wall"}
        self.emcy = {}  # node -> {"history": deque, "count"}
        self.other = None  # {"what", "first_at", "last", "last_at"}
        self.foreign_sdo = {}  # node -> monotonic time of another client's last SDO request
        self.ring = collections.deque(maxlen=TRACE_FRAMES)  # (seq, record bytes, raw id, error frame)
        self.seq = 0
        self.tracers = 0
        self.error = None  # why the receive thread ended
        self.users = 0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._rx, name="canopen-localbus-rx", daemon=True)
        self._thread.start()

    # -- life -----------------------------------------------------------------
    def close(self):
        self._stop.set()
        self._thread.join(timeout=2)
        self.opened.close()

    @property
    def alive(self):
        return self._thread.is_alive() and self.error is None

    # -- receive --------------------------------------------------------------
    def _rx(self):
        while not self._stop.is_set():
            try:
                msg = self.bus.recv(0.1)
            except Exception as e:  # the adapter went away
                self.error = "adapter %s stopped: %s" % (self.spec, e)
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

    def _handle(self, msg):
        self._record(msg, False)
        if msg.is_error_frame or msg.is_extended_id or msg.is_remote_frame:
            return
        cob = msg.arbitration_id
        data = bytes(msg.data or b"")
        now, wall = time.monotonic(), time.time()
        for q in list(self.waiters.get(cob, ())):
            q.put(data)
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

    def expect(self, cob):
        """with core.expect(0x585) as rx: ... rx.get(timeout)"""
        return Core._Expect(self, cob)

    # -- transmit ---------------------------------------------------------------
    def transmit(self, cob, data):
        """The one transmit path: waits until the adapter has listened, sends,
        and records the frame (Tx) in the trace."""
        import can
        if self.error:
            raise adapter_mod.AdapterError("unreachable", self.error)
        wait = self.listen_until - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        msg = can.Message(arbitration_id=cob, data=bytes(data), is_extended_id=False)
        with self.tx_lock:
            try:
                self.bus.send(msg, timeout=0.5)
            except Exception as e:
                raise adapter_mod.AdapterError("unreachable", "adapter %s could not send: %s" % (self.spec, e))
        msg.timestamp = time.time()
        self._record(msg, True)

    def wait_foreign_sdo(self, node):
        """Let another client's SDO transfer to `node` end before ours starts."""
        with self.lock:
            t = self.foreign_sdo.get(node)
        if t is not None:
            wait = t + FOREIGN_SDO_S - time.monotonic()
            if wait > 0:
                time.sleep(wait)

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
# One open adapter per spec in this process, shared by its handles.

_cores = {}
_cores_lock = threading.Lock()


def acquire(spec, bitrate, listen_s=LISTEN_S):
    """The process's Core for `spec`, opened at `bitrate` when it is not open
    yet. Raises AdapterError (busy when another tool has it, or when this
    process has it open at another bit rate)."""
    key = str(spec)
    with _cores_lock:
        core = _cores.get(key)
        if core is not None and not core.alive:
            core.close()
            del _cores[key]
            core = None
        if core is None:
            core = Core(adapter_mod.open(spec, bitrate), listen_s)
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
