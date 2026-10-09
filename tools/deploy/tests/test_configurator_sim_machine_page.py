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
import unittest

from canworks import diag
from canworks.configurator import server as srv

from .fake_sim_machine import FakeMachine
from .fake_sim_page import TOKEN, FakeSim
from .helpers import REPO
from .test_configurator_layout import CONTRAST, FIT_CHECK, TARGETS, audit
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
        pg.click("#start-project")
        pg.fill("#browser-path", cls.project)
        pg.click("#browser-open")
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
                         ["Gripper close:0", "Part gripped:0", "infeed run:0", "part_at_pick:0", "pallet change:0", "pallet ready:0"])
        self.assertEqual(self.text('[data-machine-counter="placed"]'), "0")
        self.assertTrue(pg.is_disabled('[data-machine-fault="z:jam"]'))
        self.assertIn("offline", self.text('[data-machine="fault-reason"]'))
        # Machine is the fourth tab of Simulation, not a sidebar item.
        self.assertEqual(pg.eval_on_selector_all("button[data-sim-tab]", "els => els.map(e => e.innerText)"),
                         ["Live values", "Simulation file", "Scenarios", "Machine"])
        self.assertEqual(pg.locator('#side button[data-view="machine"], #nav-machine').count(), 0)


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
            pg.click('[data-theme-choice="%s"]' % theme)
            self.assertEqual(pg.evaluate(FIT_CHECK), [], theme)
            self.assertEqual(pg.evaluate(CONTRAST), [], theme)
            self.assertEqual(pg.evaluate(TARGETS), [], theme)
            audit(pg, "machine view, " + theme)
        pg.click('[data-theme-choice="auto"]')

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


if __name__ == "__main__":
    unittest.main()
