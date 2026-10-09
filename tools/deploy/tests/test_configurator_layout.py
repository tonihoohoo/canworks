"""The configurator page's layout in a real browser (fix-configurator-layout):
nothing clipped or scrolling sideways on any view, SDO variables and PDO
settings, the message bar, readable problems, the overlap override, narrow
windows and the theme. Every view also goes through axe-core (WCAG 2.1 A
and AA) and a contrast check (polish-configurator-ux): a critical or
serious finding fails the test, the rest is reported. Needs Playwright,
like test_configurator_page.py."""

import json
import os
import shutil
import threading

from canworks import diag
from canworks.configurator import server as srv

from .fake_diag import TOKEN, FakePlugin
from .helpers import REPO
from .test_configurator_online_page import OnlineBase
from .test_configurator_page import RTD

# Every visible field, dropdown and button whose text does not fit, and every
# view, pane or table that scrolls sideways. The text width comes from the
# element's own font, so it matches what the user sees.
FIT_CHECK = r"""() => {
  const out = [];
  const ctx = document.createElement("canvas").getContext("2d");
  const shown = (e) => e.offsetParent !== null;
  const name = (e) => e.dataset.path || e.getAttribute("aria-label") || e.textContent.trim() || e.tagName;
  for (const e of document.querySelectorAll("input[type=text], input:not([type]), select")) {
    if (!shown(e)) continue;
    const cs = getComputedStyle(e);
    ctx.font = cs.font;
    const text = e.tagName === "SELECT" ? ((e.selectedOptions[0] || {}).text || "") : (e.value || e.placeholder || "");
    const pad = parseFloat(cs.paddingLeft) + parseFloat(cs.paddingRight) + (e.tagName === "SELECT" ? 20 : 0);
    if (ctx.measureText(text).width + pad > e.clientWidth + 2) out.push(["clipped", name(e), text]);
  }
  for (const e of document.querySelectorAll("button, .file-button")) {
    if (!shown(e)) continue;
    if (e.scrollWidth > e.clientWidth + 1) out.push(["button clipped", name(e)]);
    if (e.getBoundingClientRect().height > 48 && !e.classList.contains("choice") && !e.closest("#problem-list")) out.push(["button wraps", name(e)]);
    if (e.getBoundingClientRect().right > document.documentElement.clientWidth + 1) out.push(["button off screen", name(e)]);
  }
  for (const id of ["view", "side", "problems"]) {
    const v = document.getElementById(id);
    if (v && shown(v) && v.scrollWidth > v.clientWidth + 1) out.push(["scrolls sideways", id]);
  }
  for (const e of document.querySelectorAll(".objects, table")) {
    if (shown(e) && e.scrollWidth > e.clientWidth + 1) out.push(["table scrolls sideways", e.className || e.tagName]);
  }
  if (document.documentElement.scrollWidth > document.documentElement.clientWidth + 1) out.push(["page scrolls sideways"]);
  return out;
}"""


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# axe-core, vendored for the tests (tests/data/axe/README.md).
AXE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "axe", "axe.min.js")
with open(AXE_PATH, encoding="utf-8") as _f:
    AXE = _f.read()
AXE_RUN = """async () => {
  const r = await axe.run(document, { runOnly: { type: "tag", values: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "best-practice"] } });
  return r.violations.map((v) => ({ id: v.id, impact: v.impact, help: v.help, n: v.nodes.length,
    nodes: v.nodes.slice(0, 4).map((n) => n.target.join(" ")) }));
}"""

# Every visible text whose contrast against its background is under WCAG AA
# (4.5:1, 3:1 for large text), as [ratio, element, text].
CONTRAST = r"""() => {
  const lum = (c) => { const [r, g, b] = c.match(/\d+(\.\d+)?/g).map(Number).slice(0, 3).map((v) => { v /= 255; return v <= .03928 ? v / 12.92 : Math.pow((v + .055) / 1.055, 2.4); }); return .2126 * r + .7152 * g + .0722 * b; };
  const solid = (c) => c && !c.endsWith(", 0)") && c !== "rgba(0, 0, 0, 0)" && c !== "transparent";
  const bgOf = (e) => { while (e) { const c = getComputedStyle(e).backgroundColor; if (solid(c)) return c; e = e.parentElement; } return getComputedStyle(document.body).backgroundColor; };
  const out = [];
  const seen = new Set();
  for (const e of document.querySelectorAll("#view *, #side *, #problems *, header *, #banner *, #sim-banner")) {
    if (e.offsetParent === null || e.closest("[aria-hidden=true], .uplot")) continue;
    if (!/[A-Za-z0-9]/.test([...e.childNodes].filter((n) => n.nodeType === 3).map((n) => n.textContent).join(""))) continue;
    const cs = getComputedStyle(e);
    if (e.disabled || e.closest(":disabled") || cs.opacity !== "1" || cs.color.endsWith(", 0)")) continue;
    const fg = cs.color, bg = bgOf(e);
    const key = fg + "|" + bg + "|" + cs.fontSize + "|" + cs.fontWeight;
    if (seen.has(key)) continue;
    seen.add(key);
    const l1 = lum(fg), l2 = lum(bg);
    const ratio = (Math.max(l1, l2) + .05) / (Math.min(l1, l2) + .05);
    const large = parseFloat(cs.fontSize) >= 18.66 || (parseFloat(cs.fontSize) >= 14 && parseInt(cs.fontWeight, 10) >= 700);
    if (ratio < (large ? 3 : 4.5)) out.push([Number(ratio.toFixed(2)), e.tagName + "." + e.className, e.textContent.trim().slice(0, 40)]);
  }
  return out;
}"""

# Buttons, inputs and links under 24 px, as [element, width, height]. Boxes
# and radios are 20 px with a 2 px margin and a clickable label (WCAG 2.5.8
# spacing exception), so they pass at 20.
TARGETS = r"""() => {
  const out = [];
  for (const e of document.querySelectorAll("button, input, select, a[href], [role=button], summary")) {
    if (e.offsetParent === null || e.type === "hidden" || e.closest(".uplot")) continue;
    const r = e.getBoundingClientRect();
    const min = (e.type === "checkbox" || e.type === "radio") ? 20 : 24;
    if (r.height < min || r.width < min) out.push([e.tagName + "." + e.className + " " + (e.dataset.path || e.getAttribute("aria-label") || e.textContent.trim().slice(0, 20)), Math.round(r.width), Math.round(r.height)]);
  }
  return out;
}"""


def audit(page, where, report=None):
    """axe-core on the page as it is: critical and serious findings fail,
    the others are collected in `report` (a list) when given."""
    page.evaluate(AXE)
    found = page.evaluate(AXE_RUN)
    bad = [f for f in found if f["impact"] in ("critical", "serious")]
    if report is not None:
        report.extend(dict(f, where=where) for f in found if f["impact"] not in ("critical", "serious"))
    if bad:
        raise AssertionError("%s: accessibility %s" % (where, "; ".join(
            "%s (%s, %d): %s at %s" % (f["id"], f["impact"], f["n"], f["help"], ", ".join(f["nodes"])) for f in bad)))


class Layout(OnlineBase):
    def setUp(self):
        super().setUp()
        n = self.cfg["nodes"][0]
        n["sdo_variables"] = [
            {"index": "0x1017", "subindex": 0, "type": "UNSIGNED16", "direction": "read",
             "name": "producer_heartbeat_time", "iec_location": "%IW300", "period_ms": 1000,
             "trigger_location": "%QX300.0", "status_location": "%IB301", "abort_code_location": "%ID302"},
            {"index": "0x1017", "subindex": 0, "type": "UNSIGNED16", "direction": "write",
             "name": "heartbeat_setpoint", "iec_location": "%QW301"},
        ]
        canopen = os.path.join(self.project, "canworks")
        shutil.copy(os.path.join(REPO, "test", "fixtures", "eds", "fixed-io.eds"), canopen)
        shutil.copy(os.path.join(RTD, "rtd8.eds"), canopen)
        self.cfg["nodes"].append({"node_id": 23, "name": "valve", "eds": "fixed-io.eds", "rx_pdos": [
            {"entries": [{"index": "0x6200", "subindex": 1, "type": "UNSIGNED8", "iec_location": "%QB310"}]}]})
        rtd = load(os.path.join(RTD, "canopen_config.json"))["nodes"][0]
        rtd.update(eds="rtd8.eds", status_location="%IX330.0")
        for p in rtd.get("tx_pdos", []):
            for k, e in enumerate(p["entries"]):
                e["iec_location"] = "%%IW%d" % (320 + k)  # 16-bit: TPDO 2's UNSIGNED8 entries do not fit
        self.cfg["nodes"].append(rtd)
        self.write_config()
        self.page.set_viewport_size({"width": 1280, "height": 800})

    def fits(self, where):
        """Nothing clipped or sideways, no critical or serious accessibility
        finding, every text at WCAG AA contrast, every control 24 px."""
        self.page.wait_for_timeout(300)
        self.assertEqual(self.page.evaluate(FIT_CHECK), [], where)
        audit(self.page, where, self.axe_report)
        self.assertEqual(self.page.evaluate(CONTRAST), [], where + ": contrast")
        self.assertEqual(self.page.evaluate(TARGETS), [], where + ": target size")

    axe_report = []

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        if cls.axe_report and os.environ.get("CANWORKS_AXE_REPORT"):
            with open(os.environ["CANWORKS_AXE_REPORT"], "w", encoding="utf-8") as f:
                json.dump(cls.axe_report, f, indent=1)

    def node(self, k):
        self.page.click('#node-list [data-node="%d"]' % k)
        self.page.wait_for_selector('#view h2:has-text("Node")')
        self.page.evaluate("() => document.querySelectorAll('details.section, details[data-picker]').forEach((d) => { d.open = true; })")

    # -- nothing clipped, nothing sideways, accessible, in both themes --------
    def test_every_view_fits(self):
        pg = self.page
        with FakePlugin(allow_changes=True) as fp:
            self.write_config({"token_verifier": diag.token_verifier(TOKEN), "allow_changes": True})
            self.remember(fp.runtime)
            for width, scheme in ((1000, "light"), (1280, "dark"), (1440, "light")):
                pg.emulate_media(color_scheme=scheme)
                pg.set_viewport_size({"width": width, "height": 800})
                pg.goto(self.server.url)
                self.fits("start page at %d" % width)
                pg.click("#start-project")
                pg.fill("#browser-path", self.project)
                pg.click("#browser-open")
                pg.wait_for_selector("#editor:not([hidden])")
                pg.click('button[data-view="bus"]')
                self.fits("bus and master at %d" % width)
                for k in range(3):
                    self.node(k)
                    self.fits("node %d at %d" % (k, width))
                pg.click('button[data-view="declarations"]')
                self.fits("declarations at %d" % width)
                pg.click('button[data-view="online"]')
                pg.wait_for_selector("text=changes allowed")
                pg.click('tr[data-online-node="2"]')
                pg.wait_for_selector('button[data-online="write"]')
                self.fits("online at %d" % width)
                pg.click('button[data-view="scan"]')
                pg.click('button[data-online="scan"]')
                pg.wait_for_selector("tr[data-scan-node]")
                self.fits("scan at %d" % width)
                pg.click('button[data-view="trace"]')
                pg.wait_for_selector("#trace-source:not(:has-text('Loading'))")
                self.fits("trace at %d" % width)
                pg.click('button[data-view="framelab"]')
                self.fits("frame lab at %d" % width)
                pg.click('button[data-view="simulation"]')
                pg.wait_for_selector("#sim-body")
                self.fits("simulation at %d" % width)
                pg.evaluate("() => { document.querySelector('#menu-export').open = true; }")
                self.fits("export menu at %d" % width)
                pg.evaluate("() => { document.querySelector('#menu-export').open = false; }")
                pg.click("#btn-close")
                pg.wait_for_selector("#start:not([hidden])")

    def test_standalone_header_and_new_project_dialog(self):
        pg = self.page
        folder = os.path.join(self.dir, "standalone")
        os.makedirs(folder)
        shutil.copy(os.path.join(RTD, "rtd8.eds"), folder)
        shutil.copy(os.path.join(RTD, "canopen_config.json"), os.path.join(folder, "canworks.json"))
        for width in (1000, 1280, 1440):
            pg.set_viewport_size({"width": width, "height": 800})
            pg.goto(self.server.url)
            pg.click("#start-standalone")
            pg.fill("#browser-path", folder)
            pg.click("#browser-open")
            pg.wait_for_selector("#menu-project:not([hidden])")
            self.fits("standalone header at %d" % width)
            # The header's actions are on one line.
            tops = pg.eval_on_selector_all("#actions > *:not([hidden])", "es => es.map(e => Math.round(e.getBoundingClientRect().top))")
            self.assertEqual(len(set(tops)), 1, tops)
            pg.evaluate("() => { document.querySelector('#menu-project').open = true; }")
            self.fits("project menu at %d" % width)
            pg.click("#btn-new-project")
            pg.wait_for_selector("#modal[open]")
            self.fits("new project dialog at %d" % width)
            # The SDO blocks box sits on one line with its label.
            box = pg.locator('#modal-extra input[aria-label="Enable CANopen SDO blocks"]').bounding_box()
            label = pg.locator('#modal-extra label:has-text("Enable CANopen SDO blocks")').bounding_box()
            self.assertLess(abs((box["y"] + box["height"] / 2) - (label["y"] + label["height"] / 2)), 8)
            pg.click("#modal-buttons button[data-value=cancel]")
            pg.click("#btn-close")
            pg.wait_for_selector("#start:not([hidden])")

    def test_sdo_variables_at_1280(self):
        pg = self.page
        self.open()
        self.node(0)
        vp = "nodes[0].sdo_variables[0]"
        entry = pg.locator('.sdo-var[data-path="%s"]' % vp)
        entry.scroll_into_view_if_needed()
        self.assertEqual(pg.input_value('input[data-path="%s.name"]' % vp), "producer_heartbeat_time")
        self.assertEqual(pg.input_value('input[data-path="%s.trigger_location"]' % vp), "%QX300.0")
        view = pg.locator("#view").bounding_box()
        remove = entry.locator('button[title="Remove"]').bounding_box()
        self.assertLessEqual(remove["x"] + remove["width"], view["x"] + view["width"])
        self.fits("node 0 at 1280")
        # The plugin-object warning is on its own line under the entry.
        warn = '.sdo-var[data-path="nodes[0].sdo_variables[1]"] > .field-msg[data-for="nodes[0].sdo_variables[1]"]'
        pg.wait_for_selector(warn + ":has-text('configures itself')")
        self.assertEqual(pg.inner_text('.sdo-var[data-path="nodes[0].sdo_variables[1]"] code'), "0x1017:0")

    def test_pdo_settings(self):
        pg = self.page
        self.open()
        self.node(1)
        out = 'output[data-path="nodes[1].rx_pdos[0].transmission"]'
        self.assertEqual(pg.inner_text(out), "1: at SYNC, fixed by the EDS")
        self.assertTrue(pg.is_visible('[data-mapping="nodes[1].rx_pdos[0]"]'))
        self.node(0)
        tops = [pg.locator('.pdo[data-path="nodes[0].tx_pdos[0]"] .pdo-grid').first.locator("> *").nth(k)
                .bounding_box()["y"] for k in range(3)]
        self.assertEqual(len(set(round(t) for t in tops[:2])), 1, tops)
        self.assertIn("EDS default (1: every SYNC)",
                      pg.inner_text('select[data-path="nodes[0].tx_pdos[0].transmission"] option:checked'))

    # -- message bar -----------------------------------------------------------
    def test_message_bar(self):
        pg = self.page
        with FakePlugin(allow_changes=True) as fp:
            self.online(fp, allow=True)
            pg.wait_for_selector("text=changes allowed")
            pg.click('tr[data-online-node="2"]')
            pg.click('button[data-nmt="start"]')
            pg.wait_for_selector("#banner:has-text('Node 2: Start sent.')")
            pg.wait_for_selector("#banner", state="hidden", timeout=9000)
            # Leaving the view clears a message at once.
            pg.click('button[data-nmt="start"]')
            pg.wait_for_selector("#banner:has-text('Start sent')")
            pg.click('button[data-view="bus"]')
            self.assertTrue(pg.is_hidden("#banner"))
        # An error stays until closed.
        self.node(0)
        pg.evaluate("() => document.querySelectorAll('details.section').forEach((d) => { d.open = true; })")
        pg.fill('input[aria-label="SDO variable index"]', "zz")
        pg.click("button:has-text('Add variable')")
        pg.wait_for_selector("#banner.error:has-text('Give the index')")
        pg.wait_for_timeout(7000)
        self.assertTrue(pg.is_visible("#banner"))
        pg.click("#banner-close")
        self.assertTrue(pg.is_hidden("#banner"))

    # -- problems --------------------------------------------------------------
    def test_problems_readable(self):
        pg = self.page
        self.open()
        pg.wait_for_selector("#problem-list li.error")
        text = pg.inner_text("#problem-list")
        self.assertNotIn("nodes[", text)
        self.assertIn("Node 5 rtd, TPDO 2, 0x6150:1: type UNSIGNED8 (8 bit) does not fit location %IW320 (16 bit)", text)
        self.assertIn("5 problems", pg.inner_text("#problem-count"))
        pg.click("#problem-list li.error >> nth=0")
        self.assertEqual(pg.evaluate("document.activeElement.dataset.path"),
                         "nodes[2].tx_pdos[1].entries[0].iec_location")
        self.assertNotIn("nodes[", pg.inner_text(".field-msg[data-for='nodes[2].tx_pdos[1].entries[0].iec_location']"))

    def test_overlap_control(self):
        pg = self.page
        self.cfg["nodes"] = self.cfg["nodes"][:1]
        self.write_config()
        self.open()
        self.assertEqual(pg.locator("#top #allow-overlap").count(), 0)
        pg.wait_for_selector("#problem-count:has-text('1 problem')")  # the SDO variable warning
        self.assertTrue(pg.is_hidden("#overlap-box"))
        # %ID100 is the fixture project's EtherCAT input.
        self.node(0)
        self.fill_path("nodes[0].tx_pdos[0].entries[0].iec_location", "%ID100")
        pg.wait_for_selector("#problem-list li.error:has-text('ecat-bus.json')")
        pg.wait_for_selector("#overlap-box:not([hidden])")
        pg.check("#allow-overlap")
        pg.wait_for_selector("#btn-save:has-text('Save (overlaps allowed)')")
        self.assertTrue(pg.is_visible("#overlap-box"))
        pg.click("#btn-save")
        pg.wait_for_selector("#banner:has-text('Saved')")
        self.assertEqual(load(self.config_path)["nodes"][0]["tx_pdos"][0]["entries"][0]["iec_location"], "%ID100")

    def fill_path(self, path, value):
        self.page.fill('input[data-path="%s"]' % path, value)

    def test_narrow_window(self):
        pg = self.page
        pg.set_viewport_size({"width": 900, "height": 700})
        self.open()
        pg.wait_for_selector("#problem-count:has-text('5 problems')")
        box = pg.locator("#problem-count").bounding_box()
        self.assertLess(box["y"] + box["height"], 700)
        self.assertTrue(pg.is_hidden("#problem-list"))
        pg.click("#problems-box > summary")
        self.assertTrue(pg.is_visible("#problem-list li.error >> nth=0"))
        rtd = pg.locator('#node-list [data-node="2"]')
        name, count = rtd.bounding_box(), rtd.locator(".count").bounding_box()
        self.assertLess(count["x"] - (name["x"] + 40), 60)  # next to the name, not at the far edge
        self.fits("narrow node list")

    # -- theme -----------------------------------------------------------------
    def background(self):
        return self.page.evaluate("getComputedStyle(document.body).backgroundColor")

    def test_theme(self):
        pg = self.page
        pg.emulate_media(color_scheme="light")
        self.open()
        self.assertEqual(pg.get_attribute("html", "data-theme"), "auto")
        light = self.background()
        pg.click('[data-theme-choice="dark"]')
        self.assertEqual(pg.get_attribute("html", "data-theme"), "dark")
        dark = self.background()
        self.assertNotEqual(light, dark)
        self.assertEqual(pg.evaluate("getComputedStyle(document.documentElement).colorScheme"), "dark")
        self.assertEqual(pg.get_attribute('[data-theme-choice="dark"]', "aria-pressed"), "true")
        ui = os.path.join(self.cfg_dir, "ui.json")
        for _ in range(50):
            if os.path.exists(ui):
                break
            pg.wait_for_timeout(100)
        self.assertEqual(load(ui)["theme"], "dark")
        # A new configurator start (new port) opens dark.
        other = srv.Server()
        threading.Thread(target=other.serve_forever, daemon=True).start()
        self.addCleanup(other.server_close)
        self.addCleanup(other.shutdown)
        pg.goto(other.url)
        self.assertEqual(pg.get_attribute("html", "data-theme"), "dark")
        self.assertEqual(self.background(), dark)
        # Auto follows the OS as it changes.
        pg.click('[data-theme-choice="auto"]')
        self.assertEqual(self.background(), light)
        pg.emulate_media(color_scheme="dark")
        self.assertEqual(self.background(), dark)
        self.assertNotIn("theme", json.dumps(load(self.config_path)))

    # -- object dictionary with long names (improve-od-browser 2.1) ------------
    def test_object_dictionary_long_names(self):
        """Long names (Store_Parameters_Field_Highest_subindex_supported style)
        wrap; every row's Read and Edit buttons and Watch box stay inside the view."""
        import re
        from .test_parameters import NODE, FakeDevice
        pg = self.page
        with open(os.path.join(RTD, "rtd8.eds"), encoding="latin-1") as f:
            text = f.read()
        text = re.sub(r"(?m)^ParameterName=(\S+)\s*$", lambda m: "ParameterName=%s_Highest_subindex_supported_by_this_device"
                      % m.group(1).replace(" ", "_"), text)
        long_eds = os.path.join(self.project, "canworks", "long-names.eds")
        with open(long_eds, "w", encoding="latin-1") as f:
            f.write(text)
        self.cfg["nodes"][2]["eds"] = "long-names.eds"
        fp = FakeDevice(eds_path=long_eds)
        import copy
        from .fake_diag import status as fake_status
        node = copy.deepcopy(fake_status()["nodes"][0])
        node.update(node_id=NODE, name="rtd", booted=True, emcy={"code": 0, "error_register": 0, "count": 0}, sdo_variables=[])
        fp.status["nodes"].insert(0, node)
        with fp:
            self.write_config({"token_verifier": diag.token_verifier(TOKEN), "allow_changes": True})
            self.remember(fp.runtime)
            self.open()
            for width in (1000, 1280, 1440):
                pg.set_viewport_size({"width": width, "height": 800})
                pg.click('button[data-view="bus"]')
                pg.click('button[data-view="online"]')
                pg.wait_for_selector("text=changes allowed")
                pg.click('tr[data-online-node="%d"]' % NODE)
                pg.click('button[data-online-tab="od"]')
                pg.wait_for_selector('details[data-od-group="communication"]')
                pg.click('button[data-online="od-read-all"]')
                pg.wait_for_selector('[data-online="od-summary"]:has-text("read")')
                # Everything unfolded: every group and object.
                for g in pg.eval_on_selector_all("details[data-od-group]:not([open])", "ds => ds.map(d => d.dataset.odGroup)"):
                    pg.click('details[data-od-group="%s"] > summary' % g)
                pg.wait_for_timeout(100)
                pg.evaluate("() => { for (const b of document.querySelectorAll('tr.od-object button[aria-expanded=\"false\"]')) b.click(); }")
                pg.wait_for_timeout(200)
                outside = pg.evaluate("""() => {
                  const view = document.getElementById("view").getBoundingClientRect();
                  const out = [];
                  for (const e of document.querySelectorAll('[data-online="od"] tr button, [data-online="od"] tr input[type=checkbox]')) {
                    if (!e.offsetParent) continue;
                    const r = e.getBoundingClientRect();
                    if (r.right > view.right + 1 || r.left < view.left - 1) out.push(e.closest("tr").dataset.odKey || e.closest("tr").dataset.odObjectRow);
                  }
                  for (const s of document.querySelectorAll('[data-online="od"] .table-scroll'))
                    if (s.offsetParent && s.scrollWidth > s.clientWidth + 1) out.push("sideways");
                  return out;
                }""")
                self.assertEqual(outside, [], "at %d" % width)
                self.assertGreater(pg.locator('tr[data-od-key="%d:1"]' % 0x1018).bounding_box()["height"], 30)  # name wrapped
                self.fits("object dictionary at %d" % width)
