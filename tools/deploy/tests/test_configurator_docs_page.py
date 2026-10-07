"""The network documentation in a real browser (add-html-network-docs tasks
3.2, 3.3 and 4.2): the exported page offline, without script, at phone width,
in print and PDF, its sorting, filtering and deep links, and the
configurator's "Export documentation" action. Needs the Python Playwright
package and a Chromium it can launch; skipped without them, unless
CANOPEN_REQUIRE_BROWSER=1 (CI)."""

import datetime
import json
import os
import shutil
import threading
import unittest

from openplc_canopen_deploy import docexport
from openplc_canopen_deploy.configurator import server as srv

from .helpers import REPO, tmpdir

try:
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover
    sync_playwright = None

RTD = os.path.join(REPO, "config", "rtd-sensor")
FIXTURE = os.path.join(REPO, "test", "fixtures", "editor-project")
REQUIRED = os.environ.get("CANOPEN_REQUIRE_BROWSER") == "1"
NOW = datetime.datetime(2026, 1, 2, 3, 4)


def export_example(name, folder):
    path = os.path.join(REPO, "config", name, "canopen_config.json")
    with open(path, encoding="utf-8") as f:
        cfg = json.load(f)
    text, _ = docexport.export(cfg, path, now=NOW)
    out = os.path.join(folder, name + ".html")
    docexport.write_file(text, out)
    return "file://" + out


@unittest.skipIf(sync_playwright is None and not REQUIRED, "Playwright for Python is not installed")
class Browser(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pw = sync_playwright().start()
        exe = os.environ.get("CANOPEN_CHROMIUM")
        try:
            cls.browser = cls.pw.chromium.launch(**({"executable_path": exe} if exe else {}))
        except Exception as e:  # pragma: no cover
            cls.pw.stop()
            if REQUIRED:
                raise
            raise unittest.SkipTest("no Chromium for Playwright: %s" % e)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()

    def setUp(self):
        self.dir = tmpdir(self)
        self.errors = []

    def page(self, **kw):
        ctx = self.browser.new_context(**kw)
        self.addCleanup(ctx.close)
        pg = ctx.new_page()
        pg.set_default_timeout(10000)
        pg.on("pageerror", lambda e: self.errors.append(str(e)))
        return pg

    def tearDown(self):
        self.assertEqual(self.errors, [])


class Document(Browser):
    def test_offline_and_complete(self):
        url = export_example("cia402-drive", self.dir)
        pg = self.page()
        requests = []
        pg.on("request", lambda r: requests.append(r.url))
        pg.goto(url)
        self.assertEqual([u for u in requests if not u.startswith("file:")], [])
        self.assertTrue(pg.is_visible("#node-4"))
        self.assertTrue(pg.is_visible("svg.topo"))
        self.assertEqual(pg.evaluate("JSON.parse(document.getElementById('canopen-doc').textContent)"
                                     ".networks[0].nodes[0].node_id"), 4)

    def test_without_script(self):
        url = export_example("rtd-sensor", self.dir)
        pg = self.page(java_script_enabled=False)
        pg.goto(url)
        self.assertTrue(pg.is_visible("#node-5"))
        self.assertIn("0x185", pg.inner_text("#net-network"))
        self.assertIn("%IW100", pg.inner_text("#io"))

    def test_sort_and_filter(self):
        url = export_example("rtd-sensor", self.dir)
        pg = self.page()
        pg.goto(url)
        rows = "#net-network-frames-t tbody tr"
        first = lambda: pg.inner_text(rows + " >> nth=0").split("\t")[0].strip()  # noqa: E731
        self.assertEqual(first(), "0x000")
        pg.click("#net-network-frames-t thead th >> nth=0")
        self.assertEqual(first(), "0x000")
        pg.click("#net-network-frames-t thead th >> nth=0")
        self.assertEqual(first(), "0x705")
        pg.fill('input[data-filter="io-t"]', "%IB")
        visible = pg.evaluate("[...document.querySelectorAll('#io-t tbody tr')].filter(r => !r.hidden)"
                              ".map(r => r.cells[0].innerText)")
        self.assertEqual(visible, ["%IB100", "%IB101", "%IB102", "%IB103"])

    def test_deep_link(self):
        url = export_example("two-networks", self.dir)
        pg = self.page(viewport={"width": 1200, "height": 700})
        pg.goto(url + "#node-drives-2")
        pg.wait_for_function("() => { const r = document.getElementById('node-drives-2').getBoundingClientRect();"
                             " return r.top >= -2 && r.top < 100; }")

    def test_phone_width(self):
        url = export_example("cia402-drive", self.dir)
        pg = self.page(viewport={"width": 390, "height": 900})
        pg.goto(url)
        self.assertLessEqual(pg.evaluate("document.documentElement.scrollWidth"), 390)

    def test_theme(self):
        url = export_example("rtd-sensor", self.dir)
        bg = "getComputedStyle(document.body).backgroundColor"
        light = self.page(color_scheme="light")
        light.goto(url)
        dark = self.page(color_scheme="dark")
        dark.goto(url)
        self.assertNotEqual(light.evaluate(bg), dark.evaluate(bg))
        before = light.evaluate(bg)
        light.click("[data-theme-toggle]")
        self.assertEqual(light.evaluate("document.documentElement.dataset.theme"), "dark")
        self.assertNotEqual(light.evaluate(bg), before)

    def test_print(self):
        url = export_example("cia402-drive", self.dir)
        pg = self.page(viewport={"width": 794, "height": 1123})  # A4 at 96 dpi
        pg.goto(url)
        pg.emulate_media(media="print")
        self.assertFalse(pg.is_visible("nav.toc"))
        self.assertEqual(pg.evaluate("getComputedStyle(document.getElementById('node-4')).breakBefore"), "page")
        width = pg.evaluate("document.documentElement.clientWidth")
        wide = pg.evaluate("[...document.querySelectorAll('table')].filter(t => t.getBoundingClientRect().right > %d)"
                           ".length" % (width + 1))
        self.assertEqual(wide, 0)
        pdf = pg.pdf(format="A4")
        self.assertTrue(pdf.startswith(b"%PDF"))
        self.assertGreater(pdf.count(b"/Type /Page") + pdf.count(b"/Type/Page"), 2)


class Configurator(Browser):
    def setUp(self):
        super().setUp()
        os.environ["OPENPLC_CANOPEN_CONFIG_DIR"] = os.path.join(self.dir, "cfg")
        self.addCleanup(os.environ.pop, "OPENPLC_CANOPEN_CONFIG_DIR", None)
        self.server = srv.Server()
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.project = os.path.join(self.dir, "rtd-monitor")
        shutil.copytree(FIXTURE, self.project)

    def test_export_documentation(self):
        pg = self.page(accept_downloads=True)
        pg.goto(self.server.url)
        pg.click("#start-project")
        pg.fill("#browser-path", self.project)
        pg.click("#browser-open")
        pg.wait_for_selector("#editor:not([hidden])")
        pg.set_input_files("#eds-input", os.path.join(RTD, "rtd8.eds"))
        pg.wait_for_selector("text=Map an object")
        pg.fill('input[data-path="nodes[0].node_id"]', "5")
        pg.fill('input[data-path="nodes[0].name"]', "rtd")
        pg.wait_for_function("() => document.body.dataset.checking === '0'")
        with pg.expect_download() as dl:
            pg.click("#btn-export-html")
        self.assertEqual(dl.value.suggested_filename, "rtd-monitor.html")
        with open(dl.value.path(), encoding="utf-8") as f:
            text = f.read()
        self.assertIn('id="node-5"', text)
        self.assertFalse(os.path.exists(os.path.join(self.project, "canopen", "canopen.json")))
        pg.wait_for_selector("#banner:has-text('Exported rtd-monitor.html')")
        # A problem: nothing downloads, the Problems pane says why.
        pg.fill('input[data-path="nodes[0].node_id"]', "1")
        pg.wait_for_function("() => document.body.dataset.checking === '0'")
        downloads = []
        pg.on("download", lambda d: downloads.append(d))
        pg.click("#btn-export-html")
        pg.wait_for_selector("#banner.error:has-text('Documentation export stopped')")
        self.assertIn("master's node ID", pg.inner_text("#problem-list"))
        self.assertEqual(downloads, [])


if __name__ == "__main__":
    unittest.main()
