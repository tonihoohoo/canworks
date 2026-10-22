"""Each tool in one workspace, one network picker, the Project page and
Trace Start without a connection (one-place-navigation). Against a fake
plugin runtime; needs Playwright, like test_configurator_page.py."""

import json
import time

from canworks import diag
from canworks.bustrace.model import Frame

from .fake_diag import TOKEN, FakePlugin
from .helpers import tree_view
from .test_configurator_online_page import OnlineBase


def tabs(pg):
    return pg.eval_on_selector_all("#tool-tabs button[data-view]:visible", "bs => bs.map((b) => b.dataset.view)")


class Navigation(OnlineBase):
    def test_tools_per_workspace_and_links(self):
        pg = self.page
        self.open()
        self.assertEqual(tabs(pg), ["network", "declarations", "simfile"])
        pg.click('#ws [data-ws="commission"]')
        pg.wait_for_selector('#tool-tabs button[data-view="trace"]')
        self.assertEqual(tabs(pg)[1:], ["simulation", "trace", "framelab"])
        # Live Simulation links to the file in Configure, and back.
        pg.click('button[data-view="simulation"]')
        pg.wait_for_selector("#view h2:text-is('Simulation')")
        pg.click('[data-sim="edit-file"]')
        pg.wait_for_selector("#view h2:text-is('Simulation file')")
        self.assertEqual(pg.evaluate("workspace()"), "configure")
        pg.click('[data-sim="run-live"]')
        pg.wait_for_selector("#view h2:text-is('Simulation')")
        self.assertEqual(pg.evaluate("workspace()"), "commission")

    def test_project_page_from_the_header(self):
        pg = self.page
        self.open()
        self.assertEqual(pg.locator('#view select[data-target="1"]').count(), 0)
        pg.click('#ws [data-ws="commission"]')
        pg.click("#mode [data-open-project]")
        pg.wait_for_selector("#view h2:text-is('Project')")
        self.assertEqual(pg.evaluate("workspace()"), "configure")
        self.assertIn("selected", pg.get_attribute('#tree [data-key="project"]', "class"))
        self.assertEqual(pg.input_value('#view select[data-target="1"]'), "openplc")


class TwoNetworks(OnlineBase):
    def setUp(self):
        super().setUp()
        io = dict(self.cfg, name="io")
        io.pop("schema_version", None)
        line = {"name": "line", "adapter": {"type": "socketcan", "interface": "can1", "bitrate": 125000},
                "master": {"node_id": 1}, "nodes": [{"node_id": 3, "name": "other", "eds": "cpp-slave.eds"}]}
        self.cfg = {"schema_version": 2, "networks": [io, line]}
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(self.cfg, f, indent=2)

    def test_one_network_picker_while_unconnected(self):
        pg = self.page
        self.open()
        pg.click('#ws [data-ws="commission"]')
        pg.click('button[data-view="trace"]')
        pg.wait_for_selector("#trace-source")
        # The connection bar's picker is the only one, with the config's networks.
        self.assertEqual(pg.locator('select[data-online="network"]').count(), 1)
        self.assertEqual(pg.locator('#conn-bar select[data-online="network"]').count(), 1)
        self.assertEqual(pg.eval_on_selector_all('#conn-bar select[data-online="network"] option', "os => os.map((o) => o.textContent)"),
                         ["io", "line"])
        self.assertEqual(pg.locator("#tool-tabs [data-tool-net]").count(), 0)


class TraceStart(OnlineBase):
    def test_start_opens_the_panel_then_records(self):
        pg = self.page
        with FakePlugin() as fp:
            self.write_config({"token_verifier": diag.token_verifier(TOKEN)})
            self.open()
            pg.click('#ws [data-ws="commission"]')
            pg.click('button[data-view="trace"]')
            pg.wait_for_selector("#trace-source:not(:has-text('Loading'))")
            # Close leaves Trace as it was.
            pg.click("[data-trace=start-stop]")
            pg.wait_for_selector("#conn-dialog[open]")
            pg.click('[data-conn="close-panel"]')
            pg.wait_for_selector("#conn-dialog:not([open])", state="attached")
            self.assertNotIn("recording", pg.inner_text("#trace-source"))
            self.assertFalse(pg.is_visible("#banner.error"))
            # Connect with the token in the panel: the trace starts.
            pg.click("[data-trace=start-stop]")
            pg.wait_for_selector("#conn-dialog[open]")
            pg.fill('input[data-online="host"]', fp.runtime)
            pg.fill('input[data-online="runtime-token"]', TOKEN)
            pg.click('button[data-online="connect"]')
            pg.wait_for_selector("#trace-source:has-text('recording')")
            # Frames pushed before the fake's trace is set up are dropped: push until they show.
            for _ in range(20):
                now = int(time.time() * 1e6)
                fp.push([Frame(now + i * 1000, 0x182, bytes([i, 0, 0, 0])) for i in range(3)])
                try:
                    pg.wait_for_function("() => (T.st && T.st.frames) > 0", timeout=500)
                    break
                except Exception:
                    pass
            pg.wait_for_function("() => (T.st && T.st.frames) > 0")
