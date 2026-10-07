"""Bit rate detection on a CAN adapter on this PC (canopen-local-bus): the
adapter listens at each CiA 301 bit rate in listen-only mode and counts the
valid frames, error frames and identifiers it receives. Listen-only: the
adapter sends nothing, not even an acknowledge, so this needs neither
allow-changes nor force. The verdict is bitrate.decide, the plugin's rules.

A Sweep needs the adapter to itself: LocalBus closes its shared adapter
first and opens it again at its own bit rate afterwards (`on_end`); the
configurator's connection dialog runs one with nothing open.
"""

import threading
import time

from .. import bitrate as bitrate_mod
from . import adapter as adapter_mod

IDS_KEPT = 16
EFF_FLAG = 0x80000000  # extended identifiers in `ids`, as the plugin lists them


def _iso(t):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))


class Sweep:
    def __init__(self, spec, rates=None, per_rate_ms=1000, rounds=1, configured_kbit=None, opener=None):
        self.spec = spec
        rates = list(rates or bitrate_mod.RATES)
        # Rates the adapter cannot be set to are left out and named in the
        # result, not tried and failed.
        self.skipped = adapter_mod.unsupported_rates(spec, rates)
        self.rates = [k for k in rates if k not in self.skipped]
        self.per_rate_s = per_rate_ms / 1000.0
        self.rounds = max(1, rounds or 1)
        self.configured_kbit = configured_kbit
        self.opener = opener or adapter_mod.open
        self.results = [{"bitrate_kbit": k, "frames": 0, "error_frames": 0, "ids": []} for k in self.rates]
        self.lock = threading.Lock()
        self.running = False
        self.rate_kbit, self.round, self.done = None, 0, 0
        self.total = len(self.rates) * self.rounds
        self.decided = None
        self.error = None
        self.finished_at = None
        self._stop = threading.Event()
        self._opened = None
        self._restore = None  # sets a SocketCAN link back as it was before the first rate
        self._thread = None

    # -- life -------------------------------------------------------------------
    def start(self, on_end=None):
        """Opens the adapter listen-only at the first rate, so what keeps the
        sweep from starting (adapter in use, no listen-only mode, missing
        permission) raises AdapterError here, then listens in a thread.
        `on_end()` runs when the adapter is closed again, before the result
        shows; it returns '' or what failed."""
        if not self.rates:
            raise adapter_mod.AdapterError("usage", "adapter %s cannot be set to %s kbit/s" % (
                self.spec, ", ".join(str(k) for k in self.skipped)))
        self._open(self.rates[0], first=True)
        self.running = True
        self._thread = threading.Thread(target=self._run, args=(on_end,), name="canopen-localbus-sweep",
                                        daemon=True)
        self._thread.start()

    def stop(self, wait=True):
        self._stop.set()
        if wait and self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join(timeout=5)

    def _open(self, kbit, first=False):
        if self._opened is not None and self._opened.retune(kbit * 1000):
            return
        if self._opened is not None:
            self._opened.close(restore=False)  # the link is set back once, at the end
            self._opened = None
        opened = self.opener(self.spec, kbit * 1000, listen_only=True)
        if first:
            self._restore = opened.restore
        opened.restore = None
        self._opened = opened

    def _listen(self, row):
        bus = self._opened.bus
        end = time.monotonic() + self.per_rate_s
        while not self._stop.is_set():
            left = end - time.monotonic()
            if left <= 0:
                return
            try:
                msg = bus.recv(min(0.1, left))
            except Exception as e:  # the adapter went away
                raise adapter_mod.AdapterError("unreachable", "adapter %s stopped: %s" % (self.spec, e))
            if msg is None:
                continue
            with self.lock:
                if getattr(msg, "is_error_frame", False):
                    row["error_frames"] += 1
                    continue
                row["frames"] += 1
                ident = msg.arbitration_id | (EFF_FLAG if msg.is_extended_id else 0)
                if len(row["ids"]) < IDS_KEPT and ident not in row["ids"]:
                    row["ids"].append(ident)

    def _run(self, on_end):
        error = None
        try:
            for rnd in range(1, self.rounds + 1):
                for i, kbit in enumerate(self.rates):
                    if self._stop.is_set():
                        break
                    with self.lock:
                        self.rate_kbit, self.round = kbit, rnd
                    if rnd > 1 or i:
                        self._open(kbit)
                    self._listen(self.results[i])
                    if self._stop.is_set():
                        break
                    with self.lock:
                        self.done += 1
                if self._stop.is_set():
                    error = "stopped"
                    break
                # A clear answer ends the sweep early.
                if bitrate_mod.decide(self.results)["verdict"] == "detected":
                    break
        except adapter_mod.AdapterError as e:
            error = str(e)
        except Exception as e:  # never leave the adapter open
            error = "the sweep failed: %s" % (e or e.__class__.__name__)
        finally:
            notes = []
            if self._opened is not None:
                self._opened.close(restore=False)
                self._opened = None
            if self._restore is not None:
                notes.append(self._restore())
            if on_end is not None:
                try:
                    notes.append(on_end())
                except Exception as e:
                    notes.append(str(e))
            with self.lock:
                self.decided = {"verdict": "failed", "bitrate_kbit": None, "candidates": []} if error else \
                    bitrate_mod.decide(self.results)
                notes = [n for n in notes if n]
                self.error = "; ".join(([error] if error else []) + notes) or None
                self.rate_kbit = None
                self.done = self.total
                self.finished_at = _iso(time.time())
                self.running = False

    # -- the answer of detect_bitrate and detect_bitrate_status ---------------------
    def status(self):
        with self.lock:
            res = {"running": self.running, "configured_kbit": self.configured_kbit,
                   "rate_kbit": self.rate_kbit if self.running else None, "round": self.round,
                   "done": self.done, "total": self.total,
                   "results": [dict(r, ids=list(r["ids"])) for r in self.results]}
            if self.skipped:
                res["skipped_kbit"] = list(self.skipped)
            if self.running:
                res["verdict"] = None
                return res
            d = self.decided
            res.update(verdict=d["verdict"], bitrate_kbit=d["bitrate_kbit"], candidates=list(d["candidates"]),
                       finished_at=self.finished_at)
            if d["verdict"] == "detected":
                res["matches_config"] = d["bitrate_kbit"] == self.configured_kbit
            if self.error:
                res["error"] = self.error
            return res


def idle_status(configured_kbit):
    """detect_bitrate_status before any sweep."""
    return {"running": False, "configured_kbit": configured_kbit, "verdict": None}
