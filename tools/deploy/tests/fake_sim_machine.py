"""A stand-in for the simulator's machine model (plugin/src/canopen/sim/sim_machine.cpp):
FakeMachine is built from a machine file and gives `sim_machine` answers
shaped as the simulator's, with the gantry running a pick-and-place cycle
over time. For the configurator's server and page tests; FakeSim answers
sim_machine from one (fake_sim.py).

    m = FakeMachine(machine_file_dict)   # or FakeMachine.example()
    m.snapshot(1.25)                     # the answer at 1.25 s simulator time
    m.fault("z", {"jam": True})          # z stops where it is, its state "fault"
    m.clear("z", "jam")

The cycle (period_s, default 8 s): from home over the belt's end, down,
close, up, over the pallet's next slot, down, open, up, back home. Each move
eases in and out, so positions are smooth in time. The next part rides the
belt to the end stop while the gantry places the last one. A jam stops the
whole cycle until it is cleared (the PLC would stop too), and the cycle
then goes on from where it stopped. Faults and clears act at the time of
the last snapshot unless given one."""

import json
import math
import os

from canworks import simmachine as machine_mod

STATUS_ENABLED = 0x0237
STATUS_FAULT = 0x0218
# The cycle's moves as (start, end) fractions of the period.
_TO_PICK = (0.0, 0.19)
_DOWN_PICK = (0.19, 0.275)
_CLOSE = 0.275
_UP_PICK = (0.30, 0.39)
_TO_SLOT = (0.39, 0.60)
_DOWN_SLOT = (0.60, 0.69)
_OPEN = 0.69
_UP_SLOT = (0.715, 0.80)
_HOME = (0.80, 1.0)


class FakeMachineError(Exception):
    """A fault or clear the simulator refuses; the message is its own."""


def _ease(t, span):
    a, b = span
    x = min(1.0, max(0.0, (t - a) / (b - a)))
    return x * x * (3 - 2 * x)


def _r(v, step):
    return round(round(v / step) * step, 6)


class FakeMachine:
    @classmethod
    def example(cls, **kw):
        """The gantry-cell example's machine (examples/gantry-cell)."""
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "examples", "gantry-cell",
                            "canworks", "machine.json")
        with open(path, encoding="utf-8") as f:
            return cls(json.load(f), **kw)

    def __init__(self, machine, network="motion", period_s=8.0):
        self.m = machine
        self.network = network
        self.period = float(period_s)
        self.joints = machine.get("joints") or {}
        self.tool = machine.get("tool") if isinstance(machine.get("tool"), dict) else None
        self.kinds = machine.get("parts") or {}
        self.conveyors = machine.get("conveyors") or []
        self.sensors = machine.get("sensors") or []
        self.fixtures = machine.get("fixtures") or []
        self.seq = 0
        self.last_t = 0.0
        self.jams = {}       # joint -> machine time it stopped at
        self.stuck = {}      # sensor -> "on" / "off"
        self.feeder = {}     # conveyor -> "stop" / "empty"
        self.misaligned = {}  # conveyor -> mm
        self.slipped = {}    # cycle -> (x, y) where its part fell
        self.paused = 0.0    # seconds the cycle stood still for jams
        self.pause_from = None
        self._geometry()

    # -- geometry -----------------------------------------------------------
    def _geometry(self):
        t = self.tool or {}
        self.offset = list(t.get("offset", [0, 0, 300]))
        self.open_mm = t.get("open_mm", 96)
        self.stroke_s = t.get("stroke_ms", 120) / 1000.0
        self.axis = 0 if t.get("axis", "x") == "x" else 1
        conv = self.conveyors[0] if self.conveyors else None
        kind_name = ((conv or {}).get("feed") or {}).get("part") or next(iter(self.kinds), None)
        self.kind = kind_name
        self.size = list((self.kinds.get(kind_name) or {}).get("size", [80, 60, 50]))
        if conv:
            fx, fy = conv["from"]
            tx, ty = conv["to"]
            self.along = 0 if abs(fy - ty) < 1e-6 else 1
            a = self.along
            d = 1 if (conv["to"][a] - conv["from"][a]) > 0 else -1
            half = self.size[a] / 2.0
            self.belt_start = list(conv["from"])
            self.belt_start[a] += d * half
            self.pick = list(conv["to"])
            self.pick[a] -= d * half
            self.belt_dir = d
            self.belt_len = abs(self.pick[a] - self.belt_start[a])
            self.belt_top = conv.get("height", 60)
            self.speed = conv.get("speed_mm_s", 100)
        else:
            self.along, self.belt_dir, self.belt_len, self.speed = 0, 1, 0.0, 100
            self.pick = [self.offset[0], self.offset[1]]
            self.belt_start = list(self.pick)
            self.belt_top = 0
        fix = self.fixtures[0] if self.fixtures else None
        if fix:
            s = fix["slots"]
            self.slots = [(s["origin"][0] + i * s["pitch"][0], s["origin"][1] + j * s["pitch"][1])
                          for j in range(int(s["count"][1])) for i in range(int(s["count"][0]))]
            self.fix_top = fix.get("height", 40)
        else:
            self.slots = [(self.pick[0], self.pick[1])]
            self.fix_top = 0

    def _clamp(self, name, v):
        j = self.joints.get(name)
        if not j:
            return 0.0
        lo, hi = j["travel"]
        return min(hi, max(lo, v))

    def _jx(self, x):
        return self._clamp("x", x - self.offset[0])

    def _jy(self, y):
        return self._clamp("y", y - self.offset[1])

    def _jz(self, height):
        j = self.joints.get("z") or {}
        return self._clamp("z", (self.offset[2] - height) if j.get("down") else (height - self.offset[2]))

    def _home(self, name):
        j = self.joints.get(name)
        return j["travel"][0] if j else 0.0

    # -- time ---------------------------------------------------------------
    def _machine_time(self, t):
        """Seconds of cycle that ran by simulator time t (jams stop it)."""
        if self.pause_from is not None:
            return max(0.0, self.pause_from - self.paused)
        return max(0.0, t - self.paused)

    def _cycle(self, mt):
        n = int(mt // self.period)
        return n, (mt - n * self.period) / self.period

    def _pose(self, mt):
        """Joint positions {name: mm} at machine time mt."""
        n, c = self._cycle(mt)
        slot = self.slots[n % len(self.slots)]
        hx, hy, hz = self._home("x"), self._home("y"), self._home("z")
        px, py = self._jx(self.pick[0]), self._jy(self.pick[1])
        sx, sy = self._jx(slot[0]), self._jy(slot[1])
        pz, sz = self._jz(self.belt_top + 5), self._jz(self.fix_top + 5)
        if c < _TO_SLOT[0]:
            e = _ease(c, _TO_PICK)
            x, y = hx + (px - hx) * e, hy + (py - hy) * e
            z = hz + (pz - hz) * (_ease(c, _DOWN_PICK) - _ease(c, _UP_PICK))
        elif c < _HOME[0]:
            e = _ease(c, _TO_SLOT)
            x, y = px + (sx - px) * e, py + (sy - py) * e
            z = hz + (sz - hz) * (_ease(c, _DOWN_SLOT) - _ease(c, _UP_SLOT))
        else:
            e = _ease(c, _HOME)
            x, y, z = sx + (hx - sx) * e, sy + (hy - sy) * e, hz
        return {"x": x, "y": y, "z": z}

    def _tool_point(self, pose):
        z = self.joints.get("z") or {}
        return [self.offset[0] + pose["x"], self.offset[1] + pose["y"],
                self.offset[2] + (-pose["z"] if z.get("down") else pose["z"])]

    # -- faults ---------------------------------------------------------------
    def fault(self, element, fault, t_seconds=None):
        """As sim_fault with "machine": FakeMachineError with the simulator's
        message when it refuses."""
        problem = machine_mod.fault_problem(fault) or machine_mod.fault_element_problem(self.m, element, fault)
        if problem:
            raise FakeMachineError("fault: " + problem)
        t = self.last_t if t_seconds is None else t_seconds
        (k, v), = fault.items()
        if k == "jam":
            if self.pause_from is None:
                self.pause_from = t
            self.jams.setdefault(element, t)
        elif k == "stuck":
            self.stuck[element] = v
        elif k == "feeder":
            self.feeder[element] = v
        elif k == "misaligned_mm":
            self.misaligned[element] = v
        elif k == "slip":
            mt = self._machine_time(t)
            n, c = self._cycle(mt)
            if _CLOSE <= c < _OPEN and n not in self.slipped:
                tp = self._tool_point(self._pose(mt))
                self.slipped[n] = (tp[0], tp[1])

    def clear(self, element, name, t_seconds=None):
        """As sim_clear with "machine"."""
        problem = machine_mod.clear_element_problem(self.m, element, name)
        if problem:
            raise FakeMachineError(problem)
        t = self.last_t if t_seconds is None else t_seconds
        every = element in ("all", "")
        if name in ("jam", "all"):
            for j in list(self.jams):
                if every or j == element:
                    del self.jams[j]
            if not self.jams and self.pause_from is not None:
                self.paused += max(0.0, t - self.pause_from)
                self.pause_from = None
        if name in ("stuck", "all"):
            for s in list(self.stuck):
                if every or s == element:
                    del self.stuck[s]
        for faults, kind in ((self.feeder, "feeder"), (self.misaligned, "misaligned_mm")):
            if name in (kind, "all"):
                for c in list(faults):
                    if every or c == element:
                        del faults[c]

    def faults(self):
        """The active faults as sim_status and sim_machine list them."""
        out = [{"machine": j, "fault": {"jam": True}} for j in machine_mod.JOINTS if j in self.jams]
        out += [{"machine": s["name"], "fault": {"stuck": self.stuck[s["name"]]}}
                for s in self.sensors if s["name"] in self.stuck]
        for c in self.conveyors:
            if c["name"] in self.feeder:
                out.append({"machine": c["name"], "fault": {"feeder": self.feeder[c["name"]]}})
            if c["name"] in self.misaligned:
                out.append({"machine": c["name"], "fault": {"misaligned_mm": self.misaligned[c["name"]]}})
        return out

    # -- the answer -----------------------------------------------------------
    def _parts(self, mt, tool_point):
        """(parts list, holding id or None, counters)."""
        n, c = self._cycle(mt)
        parts = []
        holding = None
        a, o = self.along, 1 - self.along
        part_top_z = self.belt_top

        def part(pid, x, y, bottom, state):
            parts.append({"id": pid, "kind": self.kind, "position": [_r(x, 0.1), _r(y, 0.1), _r(bottom, 0.1)],
                          "yaw": 0, "state": state})

        # Earlier cycles' parts on the pallet (this pallet only) and on the table.
        per = len(self.slots)
        first = n - n % per
        placed_before = sum(1 for k in range(n) if k not in self.slipped)
        for k in range(first, n):
            if k not in self.slipped:
                sx, sy = self.slots[k % per]
                part(k + 1, sx, sy, self.fix_top, "placed")
        for k, (x, y) in sorted(self.slipped.items()):
            if k < n or (k == n and c >= _CLOSE):
                part(k + 1, x, y, 0, "table")
        # This cycle's part: on the belt at the end stop, held, then placed.
        picked = n
        if c < _CLOSE:
            lat = self.misaligned.get(self.conveyors[0]["name"], 0) if self.conveyors else 0
            pos = list(self.pick)
            pos[o] += lat
            part(n + 1, pos[0], pos[1], part_top_z, "belt")
        elif n not in self.slipped:
            picked = n + 1
            if c < _OPEN:
                held_bottom = tool_point[2] - 5
                part(n + 1, tool_point[0], tool_point[1], held_bottom, "held")
                if c >= _CLOSE + self.stroke_s / self.period:
                    holding = n + 1
            else:
                sx, sy = self.slots[n % per]
                part(n + 1, sx, sy, self.fix_top, "placed")
        else:
            picked = n + 1
        # The next part rides the belt once this one is lifted off.
        fed = n + 1
        stopped = bool(self.conveyors) and self.conveyors[0]["name"] in self.feeder
        if c >= _UP_PICK[0] and self.conveyors and not stopped:
            s = min(self.belt_len, self.speed * (c - _UP_PICK[0]) * self.period)
            pos = list(self.belt_start)
            pos[a] += self.belt_dir * s
            part(n + 2, pos[0], pos[1], part_top_z, "belt")
            fed = n + 2
        placed = placed_before + (1 if c >= _OPEN and n not in self.slipped else 0)
        counters = {"fed": fed, "picked": picked, "placed": placed, "misplaced": 0,
                    "dropped": sum(1 for k in self.slipped if k < n or (k == n and c >= _CLOSE)),
                    "pallets": (n + (1 if c >= _OPEN else 0)) // per}
        return parts, holding, counters

    def _sensor_on(self, s, parts, tool_point):
        if s["name"] in self.stuck:
            return self.stuck[s["name"]] == "on"
        lo = [s["at"][k] - s["size"][k] / 2.0 for k in range(3)]
        hi = [s["at"][k] + s["size"][k] / 2.0 for k in range(3)]
        if s.get("detects", "part") == "tool":
            return all(lo[k] <= tool_point[k] <= hi[k] for k in range(3))
        for p in parts:
            x, y, b = p["position"]
            plo = [x - self.size[0] / 2.0, y - self.size[1] / 2.0, b]
            phi = [x + self.size[0] / 2.0, y + self.size[1] / 2.0, b + self.size[2]]
            if all(min(hi[k], phi[k]) - max(lo[k], plo[k]) > 0 for k in range(3)):
                return True
        return False

    def snapshot(self, t_seconds):
        """The sim_machine answer at simulator time t_seconds."""
        self.last_t = t_seconds
        self.seq += 1
        mt = self._machine_time(t_seconds)
        pose = self._pose(mt)
        before = self._pose(max(0.0, mt - 0.001))
        moving = self.pause_from is None
        joints = {}
        for name in machine_mod.JOINTS:
            j = self.joints.get(name)
            if not j:
                continue
            jammed = name in self.jams
            pos = pose[name]
            vel = (pos - before[name]) / 0.001 if moving and mt > 0 else 0.0
            cpm = j.get("counts_per_mm", 1000)
            direction = j.get("direction", 1)
            counts = round(direction * (pos - j.get("offset_mm", 0)) * cpm)
            joints[name] = {"node": j["node"], "position": _r(pos, 0.01), "velocity": _r(vel, 0.1),
                            "demand": _r(pos + (0 if jammed else vel * 0.002), 0.01),
                            "actual_counts": counts, "state": "fault" if jammed else "operation_enabled",
                            "mode": 8, "statusword": STATUS_FAULT if jammed else STATUS_ENABLED,
                            "fault": jammed, "torque": 0 if jammed else round(j.get("load", {}).get("hold_permille", 0))}
            if jammed:
                joints[name]["error_code"] = 0x8611
        tp = self._tool_point(pose)
        parts, holding, counters = self._parts(mt, tp)
        n, c = self._cycle(mt)
        closed = _CLOSE <= c < _OPEN and self.tool is not None
        width = self.size[self.axis] if n not in self.slipped else (self.tool or {}).get("closed_mm", 0)
        if closed:
            k = min(1.0, (c - _CLOSE) * self.period / self.stroke_s)
        else:
            k = 1.0 - min(1.0, max(0.0, (c - _OPEN) * self.period / self.stroke_s)) if c >= _OPEN else 0.0
        opening = self.open_mm - (self.open_mm - width) * k
        sensors = {s["name"]: self._sensor_on(s, parts, tp) for s in self.sensors}
        conveyors = {}
        for cv in self.conveyors:
            running = not (_CLOSE - 0.05 <= c < _UP_PICK[0])
            conveyors[cv["name"]] = {"running": running and moving,
                                     "travel": _r(math.fmod(cv.get("speed_mm_s", 100) * mt, 100000.0), 0.1)}
        fixtures = {}
        for i, f in enumerate(self.fixtures):
            filled = sum(1 for p in parts if p["state"] == "placed") if i == 0 else 0
            fixtures[f["name"]] = {"offset": [0, 0], "ready": True, "changing": False, "filled": filled}
        return {"name": self.m.get("name", ""), "kind": self.m.get("kind", "gantry_xyz"), "joints": joints,
                "tool": {"position": [_r(v, 0.01) for v in tp], "opening": _r(opening, 0.01), "closed": closed,
                         "holding": holding},
                "parts": parts, "sensors": sensors, "conveyors": conveyors, "fixtures": fixtures,
                "counters": counters, "faults": self.faults(),
                "t_us": int(math.floor(t_seconds * 1e6)), "seq": self.seq, "network": self.network,
                "step_us": 12.5, "step_max_us": 41.0}
