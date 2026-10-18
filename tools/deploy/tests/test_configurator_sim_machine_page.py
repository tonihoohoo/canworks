"""The configurator's Machine tab of the Simulation view in a real browser
without WebGL (add-machine-sim task 3.6): the scene built from the gantry example's machine
file (machine_scene.js, three.js builds geometry without a GL context), pose
from a snapshot, interpolation over uneven answers, the panel against the
fake runtime's machine, the no-WebGL message, fault buttons on a read-only
runtime and the offline preview. No test renders a frame: software WebGL
takes seconds per frame. One browser and one page load per class. Needs
Playwright, like test_configurator_page.py."""

import json
import os
import shutil
import tempfile
import threading
import time
import unittest

from canworks import diag
from canworks.configurator import server as srv

from .fake_sim_machine import FakeMachine
from .fake_sim_page import TOKEN, FakeSim
from .helpers import REPO
from .test_configurator_layout import CONTRAST, FIT_CHECK, TARGETS, audit, pick_theme
from .test_configurator_page import FIXTURE, REQUIRED, load, sync_playwright

EXAMPLE = os.path.join(REPO, "examples", "gantry-cell", "canworks")

# No WebGL in this browser: the view runs as on a PC with WebGL turned off.
NO_WEBGL = """(() => {
  const get = HTMLCanvasElement.prototype.getContext;
  HTMLCanvasElement.prototype.getContext = function (type, ...rest) {
    return /webgl/i.test(type) ? null : get.call(this, type, ...rest);
  };
})();"""


@unittest.skipIf(sync_playwright is None and not REQUIRED, "Playwright for Python is not installed")
class Base(unittest.TestCase):
    """The gantry-cell example as an editor project's canworks/ folder, the
    Machine tab open. fake: run the fake runtime with the example's machine;
    allow: its diagnostics allow changes."""

    fake = False
    allow = True

    @classmethod
    def setUpClass(cls):
        cls.machine = load(os.path.join(EXAMPLE, "machine.json"))
        cls.pw = sync_playwright().start()
        exe = os.environ.get("CANWORKS_CHROMIUM")
        try:
            cls.browser = cls.pw.chromium.launch(**({"executable_path": exe} if exe else {}))
        except Exception as e:  # pragma: no cover
            cls.pw.stop()
            if REQUIRED:
                raise
            raise unittest.SkipTest("no Chromium for Playwright: %s" % e)
        cls.dir = tempfile.mkdtemp(prefix="canopen-machine-page-")
        cls.cfg_dir = os.path.join(cls.dir, "cfg")
        os.makedirs(cls.cfg_dir)
        cls.env = os.environ.get("CANWORKS_CONFIG_DIR")
        os.environ["CANWORKS_CONFIG_DIR"] = cls.cfg_dir
        cls.project = os.path.join(cls.dir, "gantry")
        shutil.copytree(FIXTURE, cls.project)
        canopen = os.path.join(cls.project, "canworks")
        shutil.copytree(EXAMPLE, canopen)
        cfg = load(os.path.join(canopen, "canworks.json"))
        cfg["diagnostics"] = {"token_verifier": diag.token_verifier(TOKEN), "allow_changes": cls.allow}
        with open(os.path.join(canopen, "canworks.json"), "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
        cls.sim = None
        if cls.fake:
            cls.sim = FakeSim(allow_changes=cls.allow, simulated_network=True, interface="sim1",
                              machine=FakeMachine(cls.machine, "motion")).__enter__()
            cls.sim.clock = lambda: 3.0
            with open(os.path.join(cls.cfg_dir, "online.json"), "w") as f:
                json.dump({"projects": {cls.project: {"host": cls.sim.address, "token": TOKEN}}}, f)
        cls.server = srv.Server()
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.context = cls.browser.new_context(viewport={"width": 1400, "height": 900})
        cls.context.add_init_script(NO_WEBGL)
        cls.page = cls.context.new_page()
        cls.page.set_default_timeout(10000)
        cls.errors = []
        cls.page.on("pageerror", lambda e: cls.errors.append(str(e)))
        cls.console = []
        cls.page.on("console", lambda m: cls.console.append(m.text) if m.type == "error" else None)
        pg = cls.page
        pg.goto(cls.server.url)
        pg.click("#start-open")
        pg.fill("[data-folder=path]", cls.project)
        pg.click("[data-folder=dialog] [data-value=use]")
        pg.wait_for_selector("#editor:not([hidden])")
        pg.click('button[data-view="simulation"]')
        pg.click('button[data-sim-tab="machine"]')
        try:
            pg.wait_for_selector('[data-machine="state"]')
        except Exception:
            # Say what the page showed, and leave no browser running for the next class.
            shown = pg.evaluate("document.querySelector('#machine-view, #view')?.innerText || ''")
            cls.tearDownClass()
            raise AssertionError("the Machine tab did not open: %r; page errors: %s; console: %s"
                                 % (shown[:500], cls.errors, cls.console[:10]))

    @classmethod
    def tearDownClass(cls):
        cls.context.close()
        cls.browser.close()
        cls.pw.stop()
        cls.server.shutdown()
        cls.server.server_close()
        if cls.sim:
            cls.sim.__exit__(None, None, None)
        if cls.env is None:
            os.environ.pop("CANWORKS_CONFIG_DIR", None)
        else:
            os.environ["CANWORKS_CONFIG_DIR"] = cls.env
        shutil.rmtree(cls.dir, ignore_errors=True)

    def tearDown(self):
        self.assertEqual(self.errors, [])

    def scene(self, script, arg=None):
        """Runs script(S, machine, arg) in the page with machine_scene.js as S."""
        return self.page.evaluate("async ([m, arg]) => { const S = await import('/machine_scene.js');\n%s\n}" % script,
                                  [self.machine, arg])

    def text(self, sel):
        return self.page.inner_text(sel)

    def wait_state(self, state):
        self.page.wait_for_selector('#machine-view[data-machine-state="%s"]' % state)


class Offline(Base):
    """No runtime: the scene and the offline preview at home."""

    def test_scene_has_every_named_part(self):
        r = self.scene("""
          const ms = S.buildMachine(m);
          const node = (n) => { let o = ms.named[n]; while (o && !(o.userData && o.userData.node)) o = o.parent; return o ? o.userData.node : null; };
          const picks = new Set(ms.pickables.map((o) => { while (o && !(o.userData && o.userData.node)) o = o.parent; return o ? o.userData.node : null; }));
          return { names: Object.keys(ms.named), chains: ['chain:x', 'chain:y'].map((n) => { const c = ms.scene.getObjectByName(n); return c ? c.count : 0; }),
            nodes: ['motor:x', 'motor:y', 'motor:z', 'carriage:x', 'carriage:z'].map(node), picks: [...picks].sort(),
            anchors: ms.anchors.map((a) => a.key), lamps: Object.keys(ms.lamps.stack), drives: Object.keys(ms.lamps.drives),
            profiles: ms.named.frame.children.filter((o) => o.geometry && o.geometry.type === 'ExtrudeGeometry').length };""")
        names = set(r["names"])
        for n in ["frame", "table", "floor", "fence", "carriage:x", "carriage:y", "carriage:z", "motor:x", "motor:y", "motor:z",
                  "gripper", "finger:left", "finger:right", "tool_point", "conveyor:infeed", "belt:infeed",
                  "sensor:part_at_pick", "beam:part_at_pick", "fixture:pallet", "stack_light"]:
            self.assertIn(n, names)
        self.assertEqual(sorted(n for n in names if n.startswith("slot:")), ["slot:pallet:%d" % k for k in range(9)])
        self.assertTrue(all(c > 20 for c in r["chains"]), r["chains"])
        self.assertGreaterEqual(r["profiles"], 8)  # T-slot uprights and beams
        self.assertEqual(r["nodes"], [4, 5, 6, 4, 6])
        self.assertEqual(r["picks"], [4, 5, 6])
        self.assertEqual(r["anchors"], ["joint:x", "joint:y", "joint:z", "sensor:part_at_pick", "fixture:pallet"])
        self.assertEqual((r["lamps"], sorted(r["drives"])), (["green", "amber", "red"], ["x", "y", "z"]))

    def test_pose_puts_the_tool_where_the_joints_say(self):
        fm = FakeMachine(self.machine)
        moving = fm.snapshot(4.0)        # carrying a part to its slot
        fm.fault("z", {"jam": True}, 4.5)
        jammed = fm.snapshot(4.6)
        r = self.scene("""
          const ms = S.buildMachine(m);
          const out = [];
          for (const s of arg) {
            ms.pose(s);
            const f = (n) => { const v = new S.THREE.Vector3(); ms.named[n].getWorldPosition(v); return ms.toMachine(v); };
            const parts = {};
            ms.named.cell.getObjectByName('parts').children.forEach((p) => { const v = new S.THREE.Vector3(); p.getWorldPosition(v); parts[p.name] = ms.toMachine(v); });
            out.push({ tool: ms.toMachine(ms.toolWorld()), left: f('finger:left'), right: f('finger:right'), parts,
              belt: ms.named['belt:infeed'].material[2].map.offset.x, beam: ms.named['beam:part_at_pick'].userData.on,
              bend: ms.scene.getObjectByName('chain:x').userData.bend,
              stack: ['green', 'amber', 'red'].map((n) => ms.lamps.stack[n].userData.on),
              faultZ: ms.named['fault:z'].visible, ledZ: ms.lamps.drives.z.material.emissive.getHex() });
          }
          return out;""", [moving, jammed])
        for snap, got in zip([moving, jammed], r):
            j = snap["joints"]
            off = self.machine["tool"]["offset"]
            want = [off[0] + j["x"]["position"], off[1] + j["y"]["position"], off[2] - j["z"]["position"]]
            for a, b in zip(got["tool"], want):
                self.assertAlmostEqual(a, b, delta=0.01)
            for a, b in zip(snap["tool"]["position"], want):
                self.assertAlmostEqual(a, b, delta=0.02)
            self.assertAlmostEqual(got["right"][0] - got["left"][0], snap["tool"]["opening"], delta=0.01)
            for p in snap["parts"]:
                for a, b in zip(got["parts"]["part:%d" % p["id"]], p["position"]):
                    self.assertAlmostEqual(a, b, delta=0.01)
            travel = snap["conveyors"]["infeed"]["travel"]
            self.assertAlmostEqual(got["belt"], -((travel / 80) % 1), delta=1e-6)
            self.assertEqual(got["beam"], snap["sensors"]["part_at_pick"])
        held = [p for p in moving["parts"] if p["state"] == "held"]
        self.assertEqual(len(held), 1)
        self.assertEqual(r[0]["stack"], [True, False, False])
        self.assertFalse(r[0]["faultZ"])
        # Z jammed: its axis and lamp red, the stack light red.
        self.assertEqual(r[1]["stack"], [False, False, True])
        self.assertTrue(r[1]["faultZ"])
        self.assertEqual(r[1]["ledZ"], 0xff3b30)
        # The X energy chain's bend moves with the carriage (by half its travel).
        dx = (jammed["joints"]["x"]["position"] - moving["joints"]["x"]["position"]) / 1000
        self.assertAlmostEqual(r[1]["bend"] - r[0]["bend"], dx / 2, delta=1e-6)

    def test_scanner_fields_person_and_stack_light(self):
        fm = FakeMachine(self.machine)
        clear = fm.snapshot(1.0)
        fm.person([300, 1300], 1.0)
        warning = fm.snapshot(1.1)
        fm.person([300, 1000], 1.1)
        fm.snapshot(1.2)
        tripped = fm.snapshot(1.6)
        r = self.scene("""
          const ms = S.buildMachine(m);
          const out = { names: Object.keys(ms.named).filter((n) => /^(scanner|field|person)/.test(n)) };
          const v = new S.THREE.Vector3();
          ms.named['scanner:scanner'].getWorldPosition(v);
          out.scanner = ms.toMachine(v);
          out.poses = arg.map((s) => {
            ms.pose(s);
            ms.named.person.getWorldPosition(v);
            const f = (n) => ms.named[n].userData.on;
            return { person: ms.named.person.visible ? ms.toMachine(v).slice(0, 2) : null,
              warning: f('field:scanner:warning:0'), protective: f('field:scanner:protective:0'),
              opacity: [ms.named['field:scanner:warning:0'].material.opacity, ms.named['field:scanner:protective:0'].material.opacity],
              stack: ['green', 'amber', 'red'].map((n) => ms.lamps.stack[n].userData.on) };
          });
          // The floor under a ray straight down at machine (500, 1200).
          const ray = new S.THREE.Ray(ms.fromMachine(500, 1200, 3000), new S.THREE.Vector3(0, -1, 0));
          out.floor = ms.floorPoint(ray);
          out.sky = ms.floorPoint(new S.THREE.Ray(ms.fromMachine(0, 0, 3000), new S.THREE.Vector3(0, 1, 0)));
          return out;""", [clear, warning, tripped])
        self.assertEqual(sorted(r["names"]), sorted(
            ["scanner:scanner", "person", "person-footprint"] +
            ["field:scanner:%s:%d" % (f, i) for f in ("warning", "protective") for i in (0, 1)]))
        for a, b in zip(r["scanner"][:2], self.machine["safety"]["scanners"][0]["at"]):
            self.assertAlmostEqual(a, b, delta=0.01)
        c, w, t = r["poses"]
        self.assertEqual((c["person"], c["warning"], c["protective"]), (None, False, False))
        self.assertEqual((w["warning"], w["protective"]), (True, False))
        self.assertGreater(w["opacity"][0], c["opacity"][0])  # brighter while occupied
        for a, b in zip(w["person"], [300, 1300]):
            self.assertAlmostEqual(a, b, delta=0.01)
        self.assertEqual((t["warning"], t["protective"]), (True, True))
        self.assertEqual(c["stack"], [True, False, False])
        self.assertEqual(t["stack"], [False, False, True])  # red while the relay is open
        self.assertEqual(r["floor"], [500, 1200])
        self.assertIsNone(r["sky"])

    def test_interpolation_over_uneven_answers(self):
        # Answers 20 ms and 50 ms apart in turn, each 5-25 ms late; the tool
        # moves at 200 mm/s; drawn at 60 frames a second for 3 s.
        r = self.scene("""
          const spec = S.machineSpec(m);
          const home = S.homeSnapshot(spec);
          const snap = (t) => Object.assign({}, home, { t_us: Math.round(t * 1e6), joints: Object.assign({}, home.joints,
            { x: Object.assign({}, home.joints.x, { position: 200 * t, state: t < 1 ? 'operation_enabled' : 'fault' }) }),
            parts: [{ id: 1, kind: 'box', position: [100 * t, 480, 60], yaw: 0, state: t < 1.5 ? 'belt' : 'held' }] });
          const answers = [];
          let t = 0, i = 0;
          while (t < 3.2) { answers.push({ s: snap(t), at: (t + 0.005 + (i * 7919 % 21) / 1000) * 1000 }); t += i % 2 ? 0.05 : 0.02; i++; }
          const buf = new S.SnapshotBuffer();
          const out = [];
          let k = 0;
          for (let f = 0; f < 180; f++) {
            const now = 300 + f * 1000 / 60;
            while (k < answers.length && answers[k].at <= now) { buf.push(answers[k].s, answers[k].at); k++; }
            const s = buf.sample(now);
            out.push({ now, x: s.joints.x.position, t: s.t_us, state: s.joints.x.state, part: s.parts[0].position[0], pstate: s.parts[0].state });
          }
          // Parts by id and states at the snapshot that has them.
          const a = snap(1.4), b = snap(1.6);
          b.parts.push({ id: 2, kind: 'box', position: [0, 0, 0], yaw: 0, state: 'belt' });
          const mid = S.interpolate(a, b, 0.5);
          return { out, mid: { part: mid.parts.map((p) => [p.id, p.position[0], p.state]), state: mid.joints.x.state, x: mid.joints.x.position } };""")
        out = r["out"]
        steps = [b["x"] - a["x"] for a, b in zip(out, out[1:])]
        self.assertTrue(all(s >= 0 for s in steps), "the drawn tool stepped back")
        want = 200 / 60
        late = steps[45:]  # after the first 0.75 s
        self.assertTrue(all(0.6 * want < s < 1.4 * want for s in late), [round(s, 2) for s in late])
        # About the fixed delay behind the simulator time.
        lags = [(o["now"] / 1000 - o["t"] / 1e6) * 1000 for o in out[60:]]
        self.assertTrue(all(90 < lag < 160 for lag in lags), (min(lags), max(lags)))
        # Positions linear, state from the snapshot that has it.
        for o in out:
            self.assertAlmostEqual(o["x"], 200 * o["t"] / 1e6, delta=0.05)
            self.assertAlmostEqual(o["part"], 100 * o["t"] / 1e6, delta=0.05)
        fault_at = [o["t"] for o in out if o["state"] == "fault"]
        self.assertTrue(fault_at and min(fault_at) >= 1e6)
        self.assertEqual(r["mid"]["part"], [[1, 150, "belt"]])
        self.assertEqual((r["mid"]["state"], r["mid"]["x"]), ("fault", 300))

    def test_frame_rate_watch_and_saved_preset(self):
        r = self.page.evaluate("""async () => {
          const V = await import('/machine_view.js');
          const run = (fps, s) => { const w = new V.FrameRateWatch(); let said = null, at = null;
            for (let i = 0; i < fps * s; i++) { const r = w.frame(1 / fps); if (r && !said) { said = r; at = (i + 1) / fps; } } return [said, at]; };
          localStorage.setItem('canopen-machine-quality', 'low');
          const low = V.storedQuality();
          localStorage.removeItem('canopen-machine-quality');
          return { slow: run(20, 8), fast: run(30, 8), low, high: V.storedQuality() };
        }""")
        self.assertEqual(r["slow"][0], "low")
        self.assertAlmostEqual(r["slow"][1], 5.0, delta=0.1)  # 2 s warm-up, then 3 s under 28 fps
        self.assertEqual(r["fast"], [None, None])
        self.assertEqual((r["low"], r["high"]), ("low", "high"))

    def test_offline_preview_without_webgl(self):
        pg = self.page
        self.wait_state("offline")
        self.assertEqual(self.text('[data-machine="state"]'), "The machine is offline.")
        self.assertIn("Offline preview: the machine at its home positions from machine.json.", self.text('[data-machine="conn"]'))
        self.assertIn("The 3D view needs WebGL", self.text('[data-machine="nowebgl"]'))
        self.assertEqual(pg.locator('[data-machine="stage"] canvas').count(), 0)
        self.assertTrue(pg.is_hidden('[data-machine-quality="high"]'))
        for n, node in (("x", 4), ("y", 5), ("z", 6)):
            row = '[data-machine-axis="%s"]' % n
            self.assertIn("node %d" % node, self.text(row))
            self.assertIn("No drive", self.text(row + ' [data-k="state"]'))
            self.assertEqual(self.text(row + ' [data-k="position"]'), "0.00 mm · 0 counts")
        self.assertEqual(pg.eval_on_selector_all("[data-machine-io]", "els => els.map(e => e.dataset.machineIo + ':' + e.dataset.on)"),
                         ["Gripper close:0", "Part gripped:0", "infeed run:0", "part_at_pick:0", "pallet change:0", "pallet ready:0",
                          "Safety relay closed:0", "scanner warning:0"])
        self.assertEqual(self.text('[data-machine-counter="placed"]'), "0")
        self.assertTrue(pg.is_disabled('[data-machine-fault="z:jam"]'))
        self.assertIn("offline", self.text('[data-machine="fault-reason"]'))
        self.assertTrue(pg.is_disabled('[data-machine-button="estop"]'))
        self.assertEqual(self.text('[data-machine="panel-reason"]'), "The machine is offline: the panel needs the running machine.")
        self.assertEqual(self.text('[data-machine="relay"]'), "–")
        self.assertEqual(pg.locator("[data-machine-button]").count(), len(self.machine["panel"]["buttons"]))
        # Machine is the fourth tab of Simulation, not a sidebar item.
        self.assertEqual(pg.eval_on_selector_all("button[data-sim-tab]", "els => els.map(e => e.innerText)"),
                         ["Live values", "Simulation file", "Scenarios", "Machine"])
        self.assertEqual(pg.locator('#tree [data-view="machine"], #nav-machine').count(), 0)


class Live(Base):
    """The fake runtime runs the example's machine, changes allowed; its
    clock stands at 3 s unless a test moves it."""

    fake = True

    def test_a_panel_values(self):
        pg = self.page
        self.wait_state("live")
        self.assertIn("Live: the machine on network motion from the runtime, changes allowed.", self.text('[data-machine="conn"]'))
        want = FakeMachine(self.machine).snapshot(3.0)
        pg.wait_for_selector('[data-machine-axis="x"] [data-k="position"]:has-text("%.2f mm")' % want["joints"]["x"]["position"])
        for n in ("x", "y", "z"):
            j = want["joints"][n]
            row = '[data-machine-axis="%s"]' % n
            self.assertEqual(self.text(row + ' [data-k="position"]'), "%.2f mm · %d counts" % (j["position"], j["actual_counts"]))
            self.assertEqual(self.text(row + ' [data-k="state"]'), "Operation enabled")
            meta = self.text(row + ' [data-k="meta"]')
            # The window is the config's 0x6065 write: 20000 counts.
            self.assertIn("CSP · sw 0x0237 · FE %.3f of 20.000 mm" % (j["demand"] - j["position"]), meta)
        io = dict(pg.eval_on_selector_all("[data-machine-io]", "els => els.map(e => [e.dataset.machineIo, e.dataset.on])"))
        self.assertEqual(io["part_at_pick"], "1" if want["sensors"]["part_at_pick"] else "0")
        self.assertEqual(io["Gripper close"], "1" if want["tool"]["closed"] else "0")
        self.assertEqual(io["infeed run"], "1" if want["conveyors"]["infeed"]["running"] else "0")
        for k, v in want["counters"].items():
            self.assertEqual(self.text('[data-machine-counter="%s"]' % k), str(v))
        self.assertFalse(pg.is_disabled('[data-machine-fault="z:jam"]'))
        self.assertEqual(self.text('[data-machine="fault-reason"]'), "")

    def test_b_layout_and_accessibility(self):
        pg = self.page
        self.wait_state("live")
        for theme in ("light", "dark"):
            pick_theme(pg, theme)
            self.assertEqual(pg.evaluate(FIT_CHECK), [], theme)
            self.assertEqual(pg.evaluate(CONTRAST), [], theme)
            self.assertEqual(pg.evaluate(TARGETS), [], theme)
            audit(pg, "machine view, " + theme)
        pick_theme(pg, "auto")

    def test_jam_from_the_view(self):
        pg = self.page
        self.wait_state("live")
        pg.click('[data-machine-fault="z:jam"]')
        for _ in range(100):
            if "z" in self.sim.machine.jams:
                break
            pg.wait_for_timeout(20)
        self.assertIn("z", self.sim.machine.jams)
        self.sim.clock = lambda: 3.5
        pg.wait_for_selector('[data-machine-axis="z"].fault')
        self.assertEqual(self.text('[data-machine-axis="z"] [data-k="state"]'), "Fault · EMCY 0x8611")
        self.assertIn("Z axis, node 6: EMCY 0x8611", self.text('[data-machine="events"]'))
        self.assertIn("Active: z jam", self.text('[data-machine="active-faults"]'))
        pg.click('[data-machine-clear="z:jam"]')
        for _ in range(100):
            if not self.sim.machine.jams:
                break
            pg.wait_for_timeout(20)
        self.assertEqual(self.sim.machine.jams, {})
        self.sim.clock = lambda: 4.0
        pg.wait_for_selector('[data-machine-axis="z"]:not(.fault)')

    def test_y_no_data(self):
        pg = self.page
        self.wait_state("live")
        pos = self.text('[data-machine-axis="x"] [data-k="position"]')
        machine, self.sim.machine = self.sim.machine, None
        try:
            self.wait_state("nodata")
            self.assertTrue(pg.is_visible('[data-machine="nodata"]'))
            self.assertIn("No data: no answer for", self.text('[data-machine="conn"]'))
            self.assertEqual(self.text('[data-machine-axis="x"] [data-k="position"]'), pos)  # the last pose holds
            self.assertTrue(pg.is_disabled('[data-machine-fault="z:jam"]'))
        finally:
            self.sim.machine = machine
        self.wait_state("live")

    def test_z_open_node_from_the_panel(self):
        pg = self.page
        self.wait_state("live")
        pg.click('[data-machine-axis="y"]')
        pg.wait_for_function("() => S.view === 'online' && S.onlineNode === 5")
        self.assertTrue(pg.is_visible("#online-conn"))


class ReadOnly(Base):
    """The runtime's diagnostics does not allow changes."""

    fake = True
    allow = False

    def test_fault_buttons_disabled(self):
        pg = self.page
        self.wait_state("live")
        self.assertIn("read-only", self.text('[data-machine="conn"]'))
        reason = self.text('[data-machine="fault-reason"]')
        self.assertIn("changes are not allowed", reason)
        buttons = pg.eval_on_selector_all("[data-machine-fault], [data-machine-clear]", "els => els.map(e => [e.disabled, e.title])")
        self.assertGreater(len(buttons), 8)
        self.assertTrue(all(d and "changes are not allowed" in t for d, t in buttons), buttons)


class RunningClock(Base):
    """The fake's clock runs from 3 s, so every answer is a new snapshot and
    momentary presses let go 500 ms after the last repeat."""

    fake = True

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        start = time.monotonic()
        cls.sim.clock = lambda: 3.0 + time.monotonic() - start


class Panel(RunningClock):
    """add-gantry-manual-mode: the Panel block, keys on the stage, the
    emergency stop and relay, the Person tool."""

    def setUp(self):
        self.wait_state("live")
        self.blur()
        self.page.evaluate("() => window.machineView.releaseAll()")
        self.page.wait_for_timeout(100)

    def blur(self):
        self.page.click('[data-machine="panel"] h3')

    def focus_stage(self):
        self.page.click('[data-machine="stage"]', position={"x": 30, "y": 30})
        self.page.wait_for_selector('[data-machine="keyboard"]:visible')

    def presses(self, button, since=0):
        return [r["pressed"] for r in self.sim.sent("sim_panel")[since:] if r.get("button") == button]

    def wait_for(self, fn, ms=3000):
        for _ in range(ms // 20):
            if fn():
                return True
            self.page.wait_for_timeout(20)
        return fn()

    def test_a_block_from_the_machine_file(self):
        pg = self.page
        buttons = pg.eval_on_selector_all("[data-machine-button]", "els => els.map(e => [e.dataset.machineButton, e.dataset.kind, "
                                          "e.querySelector('.machine-btn-label').innerText, (e.querySelector('kbd') || {}).innerText || ''])")
        file_buttons = self.machine["panel"]["buttons"]
        self.assertEqual(sorted(b[0] for b in buttons), sorted(b["name"] for b in file_buttons))
        self.assertEqual(buttons[0], ["estop", "latching", "Emergency stop", "E"])  # first and large
        self.assertEqual(buttons[1], ["manual", "switch", "Manual", "M"])
        by = {b[0]: b for b in buttons}
        self.assertEqual(by["jog_x_plus"][2:], ["Jog X+", "→"])
        self.assertEqual(by["jog_z_up"][2:], ["Jog Z up", "Page Up"])
        self.assertEqual(by["enable"][3], "Space")
        self.assertIn("machine-estop", pg.get_attribute('[data-machine-button="estop"]', "class"))
        self.assertEqual(self.text('[data-machine-button="estop"] [data-k="state"]'), "Released")
        self.assertEqual(pg.eval_on_selector_all("[data-machine-lamp]", "els => els.map(e => e.dataset.machineLamp)"),
                         ["manual_lamp", "homed_lamp", "fault_lamp", "auto_lamp"])
        self.assertEqual(self.text('[data-machine="relay"]'), "Closed")
        self.assertEqual(self.text('[data-machine="panel-reason"]'), "")
        self.assertFalse(pg.is_disabled('[data-machine-button="jog_x_plus"]'))
        self.assertTrue(pg.is_hidden('[data-machine-tool="person"]'))  # no WebGL: no floor to click
        self.assertIn("Click the 3D view", self.text('[data-machine="keys-hint"]'))
        self.assertTrue(pg.is_hidden('[data-machine="keyboard"]'))

    def test_held_key_repeats_and_releases_on_blur(self):
        pg = self.page
        self.focus_stage()
        self.assertIn("kbd-on", pg.get_attribute('[data-machine="stage"]', "class"))
        n = len(self.sim.sent("sim_panel"))
        for _ in range(6):  # the browser's own repeat: ignored
            pg.keyboard.down("ArrowRight")
        pg.wait_for_timeout(900)
        got = self.presses("jog_x_plus", n)
        self.assertTrue(all(got), got)
        self.assertTrue(4 <= len(got) <= 7, got)  # at once, then every 200 ms
        self.assertTrue(self.sim.machine.buttons["jog_x_plus"])  # held past the 500 ms lease
        pg.wait_for_selector('[data-machine-button="jog_x_plus"].on')
        self.blur()
        self.assertTrue(pg.is_hidden('[data-machine="keyboard"]'))
        self.assertTrue(self.wait_for(lambda: self.presses("jog_x_plus", n)[-1:] == [False]))
        count = len(self.presses("jog_x_plus", n))
        pg.wait_for_timeout(450)
        self.assertEqual(len(self.presses("jog_x_plus", n)), count)  # no more repeats
        self.assertFalse(self.sim.machine.buttons["jog_x_plus"])
        pg.keyboard.up("ArrowRight")

    def test_key_up_and_page_hidden_release(self):
        pg = self.page
        self.focus_stage()
        n = len(self.sim.sent("sim_panel"))
        pg.keyboard.down("g")
        pg.wait_for_timeout(250)
        pg.keyboard.up("g")
        self.assertTrue(self.wait_for(lambda: self.presses("gripper", n)[-1:] == [False]))
        self.assertEqual(self.presses("gripper", n)[0], True)
        n = len(self.sim.sent("sim_panel"))
        pg.keyboard.down("Shift")
        pg.wait_for_timeout(250)
        pg.evaluate("() => { Object.defineProperty(document, 'hidden', { configurable: true, get: () => true });"
                    " document.dispatchEvent(new Event('visibilitychange')); }")
        try:
            self.assertTrue(self.wait_for(lambda: self.presses("fast", n)[-1:] == [False]))
            count = len(self.presses("fast", n))
            pg.wait_for_timeout(450)
            self.assertEqual(len(self.presses("fast", n)), count)
        finally:
            pg.evaluate("() => { delete document.hidden; document.dispatchEvent(new Event('visibilitychange')); }")
            pg.keyboard.up("Shift")
        self.wait_state("live")

    def test_keys_ignored_without_stage_focus(self):
        pg = self.page
        n = len(self.sim.sent("sim_panel"))
        for key in ("g", "ArrowRight", "m", "e", " "):
            pg.keyboard.press(key)
        pg.wait_for_timeout(300)
        self.assertEqual(self.sim.sent("sim_panel")[n:], [])

    def test_release_when_a_poll_fails(self):
        pg = self.page
        self.focus_stage()
        n = len(self.sim.sent("sim_panel"))
        pg.keyboard.down("ArrowUp")
        self.assertTrue(self.wait_for(lambda: self.presses("jog_y_plus", n)[:1] == [True]))
        machine, self.sim.machine = self.sim.machine, None
        try:
            self.assertTrue(self.wait_for(lambda: self.presses("jog_y_plus", n)[-1:] == [False]))
        finally:
            self.sim.machine = machine
            pg.keyboard.up("ArrowUp")
        self.wait_state("live")

    def test_mouse_hold(self):
        pg = self.page
        n = len(self.sim.sent("sim_panel"))
        box = pg.locator('[data-machine-button="jog_z_down"]').bounding_box()
        pg.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        pg.mouse.down()
        pg.wait_for_timeout(800)
        self.assertTrue(self.sim.machine.buttons["jog_z_down"])
        self.assertIn("on", pg.get_attribute('[data-machine-button="jog_z_down"]', "class"))
        pg.mouse.up()
        self.assertTrue(self.wait_for(lambda: self.presses("jog_z_down", n)[-1:] == [False]))
        self.assertFalse(self.sim.machine.buttons["jog_z_down"])
        got = self.presses("jog_z_down", n)
        self.assertTrue(len(got) >= 4 and all(got[:-1]), got)

    def test_switch_by_key_and_emergency_stop_with_the_relay(self):
        pg = self.page
        self.focus_stage()
        n = len(self.sim.sent("sim_panel"))
        y = pg.evaluate("() => document.scrollingElement.scrollTop")
        pg.keyboard.press("PageDown")  # a mapped key: the page does not scroll
        pg.keyboard.press(" ")
        self.assertEqual(pg.evaluate("() => document.scrollingElement.scrollTop"), y)
        pg.keyboard.press("m")
        self.assertTrue(self.wait_for(lambda: self.presses("manual", n) == [True]))
        pg.wait_for_selector('[data-machine-button="manual"][aria-pressed="true"]')
        pg.keyboard.press("m")
        self.assertTrue(self.wait_for(lambda: self.presses("manual", n) == [True, False]))
        pg.wait_for_selector('[data-machine-button="manual"][aria-pressed="false"]')
        self.blur()
        # The emergency stop: a click latches it, the relay stops and opens.
        pg.click('[data-machine-button="estop"]')
        pg.wait_for_selector('[data-machine-button="estop"][aria-pressed="true"]')
        self.assertEqual(self.presses("estop", n), [True])
        pg.wait_for_selector('[data-machine="relay"][data-relay="open"]')
        self.assertEqual(self.text('[data-machine="relay"]'), "Open")
        self.assertEqual(self.text('[data-machine-button="estop"] [data-k="state"]'), "Latched")
        pg.wait_for_selector('[data-machine-axis="x"] [data-k="state"]:has-text("Safe torque off")')
        pg.click('[data-machine-button="estop"]')
        pg.wait_for_selector('[data-machine="relay"][data-relay="reset"]')
        self.assertEqual(self.text('[data-machine="relay"]'), "Waiting for reset")
        pg.click('[data-machine-button="reset"]')
        pg.wait_for_selector('[data-machine="relay"][data-relay="closed"]')
        self.assertEqual(self.text('[data-machine="relay"]'), "Closed")

    def test_lamps_follow_the_machine(self):
        self.sim.machine.lamps["homed_lamp"] = True
        try:
            self.page.wait_for_selector('[data-machine-lamp="homed_lamp"][data-on="1"]')
            self.assertEqual(self.page.get_attribute('[data-machine-lamp="manual_lamp"]', "data-on"), "0")
        finally:
            self.sim.machine.lamps["homed_lamp"] = False

    def test_person_drag_is_throttled(self):
        pg = self.page
        n = len(self.sim.sent("sim_person"))
        pg.evaluate("""async () => {
          const v = window.machineView;
          v.togglePerson();
          for (let i = 0; i <= 50; i++) { v.movePerson([300, 1900 - i * 18]); await new Promise((r) => setTimeout(r, 10)); }
          v.endPerson();
        }""")
        self.assertTrue(self.wait_for(lambda: (self.sim.sent("sim_person")[n:][-1:] or [{}])[0].get("at") == [300, 1000]))
        ats = [r["at"] for r in self.sim.sent("sim_person")[n:]]
        self.assertEqual(ats[0], [300, 1900])
        self.assertTrue(4 <= len(ats) <= 9, ats)  # about every 100 ms over 0.6 s, plus the last one
        self.assertEqual(self.sim.machine.person_at, [300.0, 1000.0])
        self.assertEqual(pg.get_attribute('[data-machine-tool="person"]', "aria-pressed"), "true")
        pg.wait_for_selector('[data-machine="relay"][data-relay="open"]')  # in the protective field
        pg.evaluate("() => window.machineView.togglePerson()")
        self.assertTrue(self.wait_for(lambda: self.sim.sent("sim_person")[-1].get("at", 0) is None))
        self.assertIsNone(self.sim.machine.person_at)
        self.assertEqual(pg.get_attribute('[data-machine-tool="person"]', "aria-pressed"), "false")
        pg.wait_for_selector('[data-machine="relay"][data-relay="reset"]')
        pg.click('[data-machine-button="reset"]')
        pg.wait_for_selector('[data-machine="relay"][data-relay="closed"]')


class PanelReadOnly(RunningClock):
    """The panel without allow_changes: disabled with the reason, lamps live."""

    allow = False

    def test_buttons_disabled_and_keys_do_nothing(self):
        pg = self.page
        self.wait_state("live")
        self.assertIn("changes are not allowed", self.text('[data-machine="panel-reason"]'))
        buttons = pg.eval_on_selector_all("[data-machine-button], [data-machine-tool]", "els => els.map(e => [e.disabled, e.title])")
        self.assertEqual(len(buttons), len(self.machine["panel"]["buttons"]) + 1)
        self.assertTrue(all(d and "changes are not allowed" in t for d, t in buttons), buttons)
        pg.click('[data-machine="stage"]', position={"x": 30, "y": 30})
        pg.keyboard.press("g")
        pg.keyboard.press("e")
        pg.evaluate("() => window.machineView.press('jog_x_plus', 'pointer')")
        pg.wait_for_timeout(300)
        self.assertEqual(self.sim.sent("sim_panel"), [])
        self.sim.machine.lamps["manual_lamp"] = True
        pg.wait_for_selector('[data-machine-lamp="manual_lamp"][data-on="1"]')
        self.assertEqual(self.text('[data-machine="relay"]'), "Closed")


if __name__ == "__main__":
    unittest.main()
