"""The device error history panel (0x1003) of the online node page and the
node page's EMCY COB-ID field, in a real browser against a fake plugin
(add-emcy-history tasks 5.3 and 5.4), and the node settings a device's EDS
cannot back (eds-gated-node-settings). Needs Playwright, like
test_configurator_page.py."""

import os
import shutil

from .fake_diag import FakePlugin
from .helpers import PINGPONG, REPO, tree_node
from .test_configurator_online_page import OnlineBase
from .test_configurator_page import load

EMCY_EDS = os.path.join(REPO, "test", "fixtures", "eds", "emcy-slave.eds")


def use_eds(project, text):
    """Replaces the project's cpp-slave.eds with `text`."""
    with open(os.path.join(project, "canworks", "cpp-slave.eds"), "w", encoding="utf-8") as f:
        f.write(text)


def history(fp, *values):
    fp.objects[(2, 0x1003, 0)] = bytes([len(values)])
    for i, v in enumerate(values):
        fp.objects[(2, 0x1003, i + 1)] = v.to_bytes(4, "little")


class ErrorHistory(OnlineBase):
    def node(self, fp, allow=False):
        pg = self.page
        self.online(fp, allow=allow)
        pg.wait_for_selector("text=changes allowed" if allow else "text=read-only")
        pg.click('tr[data-online-node="2"]')
        pg.wait_for_selector('[data-online="error-field"]', state="attached")  # empty without a history
        pg.wait_for_function("() => !document.querySelector('[data-online=\"error-field\"]').textContent.includes('Loading')")

    def test_read(self):
        pg = self.page
        with FakePlugin() as fp:
            history(fp, 0x00004210, 0x00125000)
            self.node(fp)
            box = '[data-online="error-field"]'
            self.assertEqual(pg.inner_text(box + ' [data-online="error-field-count"]'), "Count 2 (newest first)")
            self.assertEqual(pg.inner_text(box + ' tr[data-error-field-row="1"]').split("\t"),
                             ["1", "0x4210", "temperature", "0x0000"])
            self.assertEqual(pg.inner_text(box + ' tr[data-error-field-row="2"]').split("\t"),
                             ["2", "0x5000", "device hardware", "0x0012"])
            # A new entry shows after Refresh.
            history(fp, 0x8130, 0x4210, 0x125000)
            pg.click('button[data-online="error-field-refresh"]')
            pg.wait_for_selector(box + ' [data-online="error-field-count"]:has-text("Count 3")')
            self.assertIn("communication", pg.inner_text(box + ' tr[data-error-field-row="1"]'))

    def test_no_history(self):
        pg = self.page
        with FakePlugin() as fp:
            self.node(fp)
            # A message bar at the top of the section, not text in the list's place.
            pg.wait_for_selector('fieldset:has([data-online="error-field"]) > .notice-slot .notice-info:has-text("Node 2 has no error history (0x1003).")')
            self.assertEqual(pg.inner_text('[data-online="error-field"]'), "")

    def test_clear_refused_read_only(self):
        pg = self.page
        with FakePlugin() as fp:
            history(fp, 0x4210)
            self.node(fp)
            self.assertTrue(pg.is_disabled('button[data-online="error-field-clear"]'))
            self.assertIn("not allowed", pg.get_attribute('button[data-online="error-field-clear"]', "title"))
            self.assertIn("not allowed", pg.inner_text('[data-online="error-field-no-changes"]'))

    def test_clear_forced(self):
        pg = self.page
        with FakePlugin(allow_changes=True) as fp:
            history(fp, 0x4210, 0x125000)
            fp.force_running = True  # node 2 is OPERATIONAL in the fake's status
            self.node(fp, allow=True)
            pg.click('button[data-online="error-field-clear"]')
            pg.wait_for_selector("#modal[open]")
            text = pg.inner_text("#modal-text")
            self.assertIn("node 2", text)
            self.assertIn("2 entries", text)
            # Cancel is the default.
            self.assertEqual(pg.evaluate("() => document.activeElement.dataset.value"), "cancel")
            pg.click('#modal button[data-value="cancel"]')
            self.assertEqual(fp.objects[(2, 0x1003, 0)], b"\x02")
            pg.click('button[data-online="error-field-clear"]')
            pg.click('#modal button[data-value="clear"]')
            pg.wait_for_selector("#modal-text:has-text('OPERATIONAL')")
            self.assertIn("Node 2", pg.inner_text("#modal-text"))
            self.assertEqual(fp.forced, [])
            pg.click('#modal button[data-value="force"]')
            pg.wait_for_selector('[data-online="error-field-count"]:has-text("Count 0")')
            self.assertEqual(fp.objects[(2, 0x1003, 0)], b"\x00")
            self.assertEqual(fp.forced, [("sdo_write", 2)])

    def test_plugin_refusal_asks_for_force(self):
        # The page's status says the node is not running; the plugin refuses.
        pg = self.page
        with FakePlugin(allow_changes=True) as fp:
            history(fp, 0x4210)
            for n in fp.status["nodes"]:
                n["state"] = 127
            self.node(fp, allow=True)
            orig = fp.answer

            def answer(req, conn=None):
                if req.get("op") == "sdo_write" and not req.get("force"):
                    return {"ok": False, "error": "node 2 is OPERATIONAL; an SDO write changes it while the program "
                                                  "drives it; force needed"}
                return orig(req, conn)

            fp.answer = answer
            pg.click('button[data-online="error-field-clear"]')
            self.assertIn("1 entry", pg.inner_text("#modal-text"))
            pg.click('#modal button[data-value="clear"]')
            pg.wait_for_selector("#modal-text:has-text('OPERATIONAL')")
            pg.click('#modal button[data-value="force"]')
            pg.wait_for_selector('[data-online="error-field-count"]:has-text("Count 0")')

    def test_emcy_cob_id_in_the_node_row(self):
        pg = self.page
        with FakePlugin() as fp:
            fp.status["nodes"][0]["emcy_cob_id"] = {"value": 0xC2, "source": "device", "valid": True}
            fp.status["nodes"][1]["emcy_cob_id"] = {"value": 0x97, "source": "default", "valid": False}
            self.online(fp)
            pg.wait_for_selector('[data-emcy-cob="2"]')
            self.assertEqual(pg.inner_text('[data-emcy-cob="2"]'), "EMCY COB-ID 0xC2 (device)")
            self.assertEqual(pg.inner_text('[data-emcy-cob="23"]'), "EMCY COB-ID 0x97 (default, off on the device)")
            self.assertIn("bad", pg.get_attribute('[data-emcy-cob="23"]', "class"))
            fp.status["nodes"][0]["emcy_cob_id"] = {"value": 0x82, "source": "default", "valid": True}
            pg.wait_for_function("() => !document.querySelector('[data-emcy-cob=\"2\"]')")


class EmcyCobField(OnlineBase):
    def setUp(self):
        super().setUp()
        # The EMCY section needs 0x1014 in the node's EDS.
        shutil.copy(EMCY_EDS, os.path.join(self.project, "canworks", "cpp-slave.eds"))

    def node_page(self):
        pg = self.page
        self.open()
        tree_node(pg, 0, "supervision")
        pg.wait_for_selector('select[data-emcy-cob="mode"]')

    def save(self):
        pg = self.page
        pg.wait_for_function("() => document.body.dataset.checking === '0'")
        pg.evaluate("() => banner('')")  # the last save's message
        pg.click("#btn-save")
        pg.wait_for_selector("#banner:has-text('Saved')")
        return load(self.config_path)["nodes"][0]

    def test_default_not_saved(self):
        pg = self.page
        self.node_page()
        self.assertEqual(pg.input_value('select[data-emcy-cob="mode"]'), "device")
        self.assertFalse(pg.is_visible('input[data-emcy-cob="number"]'))
        pg.select_option('select[data-emcy-cob="mode"]', "eds")
        self.assertEqual(self.save()["emcy_cob_id"], "eds")
        pg.select_option('select[data-emcy-cob="mode"]', "device")
        self.assertNotIn("emcy_cob_id", self.save())

    def test_number_and_clash(self):
        pg = self.page
        self.node_page()
        pg.select_option('select[data-emcy-cob="mode"]', "number")
        self.assertTrue(pg.is_visible('input[data-emcy-cob="number"]'))
        # Node 2's own TPDO 1 (0x182).
        pg.fill('input[data-emcy-cob="number"]', "0x182")
        msg = '.field-msg[data-for="nodes[0].emcy_cob_id"]'
        pg.wait_for_selector(msg + ':has-text("clashes with node 2 (pingpong) TPDO 1")')
        self.assertIn("emcy_cob_id 0x182 clashes with node 2 (pingpong) TPDO 1", pg.inner_text("#problem-list"))
        pg.fill('input[data-emcy-cob="number"]', "1537")
        pg.wait_for_selector(msg + ':has-text("emcy_cob_id 0x601 is a restricted CAN-ID (CiA 301)")')
        pg.fill('input[data-emcy-cob="number"]', "0xC2")
        pg.wait_for_function("(s) => !document.querySelector(s).textContent", arg=msg)
        self.assertEqual(self.save()["emcy_cob_id"], "0xC2")
        pg.fill('input[data-emcy-cob="number"]', "197")
        self.assertEqual(self.save()["emcy_cob_id"], 197)
        # Reopened: the number shows.
        pg.reload()  # the project opens again
        tree_node(pg, 0, "supervision")
        pg.wait_for_selector('select[data-emcy-cob="mode"]')
        self.assertEqual(pg.input_value('select[data-emcy-cob="mode"]'), "number")
        self.assertEqual(pg.input_value('input[data-emcy-cob="number"]'), "197")


class EdsLimits(OnlineBase):
    """EMCY and the heartbeat consumer follow the EDS, and the reasons look
    like the other hints unless the file still has the setting
    (eds-gated-node-settings tasks 2.1-2.6)."""

    def color(self, selector):
        return self.page.eval_on_selector(selector, "(e) => getComputedStyle(e).color")

    def test_emcy_without_0x1014(self):
        pg = self.page
        self.open()  # the ping-pong EDS has no 0x1014
        tree_node(pg, 0, "supervision")
        pg.wait_for_selector('[data-emcy-section="unsupported"]')
        # One line, no controls (target-cleans-up).
        for c in ('input[data-path="nodes[0].emcy_code_location"]', 'input[data-path="nodes[0].error_register_location"]',
                  'select[data-emcy-cob="mode"]', 'button[data-suggest="emcy"]', 'button[data-suggest="errreg"]'):
            self.assertEqual(pg.locator(c).count(), 0, c)
        self.assertEqual(pg.locator('[data-emcy-section="unsupported"] > :not(legend)').count(), 1)
        limit = "[data-emcy-limit]"
        self.assertIn("no EMCY COB-ID (0x1014)", pg.inner_text(limit))
        self.assertEqual(pg.get_attribute(limit, "class"), "hint")
        status_hint = pg.locator('input[data-path="nodes[0].status_location"]').locator("xpath=ancestor::label[1]").locator(".hint")
        self.assertEqual(self.color(limit), status_hint.evaluate("(e) => getComputedStyle(e).color"))
        self.assertEqual(pg.locator("[data-emcy-remove]").count(), 0)

    def test_leftover_emcy_settings(self):
        pg = self.page
        self.cfg["nodes"][0].update(emcy_code_location="%IW30", emcy_cob_id="eds")
        self.write_config()
        self.open()
        tree_node(pg, 0, "supervision")
        pg.wait_for_selector("[data-emcy-remove]")
        # A warning bar at the top of the section, under its legend (consistent-message-bars).
        self.assertIn("notice-warning", pg.get_attribute("[data-emcy-limit]", "class"))
        self.assertTrue(pg.evaluate("() => document.querySelector('[data-emcy-limit]').previousElementSibling.tagName === 'LEGEND'"))
        pg.wait_for_function("() => document.body.dataset.checking === '0'")
        self.assertIn("'emcy_code_location' needs an EDS with the EMCY COB-ID (0x1014)", pg.inner_text("#problem-list"))
        self.assertTrue(pg.is_disabled("#btn-save"))
        pg.click("[data-emcy-remove]")
        self.assertEqual(pg.evaluate("() => ['emcy_code_location', 'emcy_cob_id'].filter((k) => k in S.config.nodes[0])"), [])
        self.assertEqual(pg.get_attribute("[data-emcy-limit]", "class"), "hint")
        self.assertEqual(pg.locator('input[data-path="nodes[0].emcy_code_location"]').count(), 0)

    def test_heartbeat_consumer_without_0x1016(self):
        pg = self.page
        with open(os.path.join(PINGPONG, "cpp-slave.eds"), encoding="utf-8") as f:
            text = f.read()
        # 0x1016 sub 1 read-only: no entry the setting can go to.
        start = text.index("[1016sub1]")
        use_eds(self.project, text[:start] + text[start:].replace("AccessType=rw", "AccessType=ro", 1))
        self.open()
        tree_node(pg, 0, "advanced")
        sel = 'select[data-path="nodes[0].heartbeat_consumer"]'
        pg.wait_for_selector(sel)
        self.assertTrue(pg.is_disabled(sel))
        self.assertEqual(pg.input_value(sel), "")
        self.assertIn("no consumer heartbeat time (0x1016)", pg.inner_text("[data-heartbeat-limit]"))
        self.assertEqual(pg.get_attribute("[data-heartbeat-limit]", "class"), "hint")
        # Left in the file: a problem, removed with one click.
        pg.evaluate("() => { S.config.nodes[0].heartbeat_consumer = false; render(); }")
        pg.wait_for_selector("[data-heartbeat-remove]")
        self.assertIn("warning", pg.get_attribute("[data-heartbeat-limit]", "class"))
        pg.click("[data-heartbeat-remove]")
        self.assertFalse(pg.evaluate("() => 'heartbeat_consumer' in S.config.nodes[0]"))
        # Nor can it watch other nodes' heartbeats.
        pg.evaluate("() => { S.config.nodes.push({node_id: 5, eds: 'cpp-slave.eds', heartbeat_ms: 100}); render(); }")
        tree_node(pg, 0, "supervision")
        # Nothing to choose and nothing set: no watch block at all (target-cleans-up).
        pg.wait_for_selector('[data-supervision="0"]')
        self.assertEqual(pg.locator(".heartbeat-watch").count(), 0)
        self.assertEqual(pg.locator('select[aria-label="Watch another node\'s heartbeat"]').count(), 0)
        pg.evaluate("() => { S.config.nodes[0].heartbeat_watch = [{node: 5}]; render(); }")
        pg.wait_for_selector("[data-watch-remove]")
        pg.click("[data-watch-remove]")
        self.assertFalse(pg.evaluate("() => 'heartbeat_watch' in S.config.nodes[0]"))

    def test_heartbeat_consumer_with_0x1016(self):
        pg = self.page
        self.open()
        tree_node(pg, 0, "advanced")
        sel = 'select[data-path="nodes[0].heartbeat_consumer"]'
        pg.wait_for_selector(sel)
        self.assertTrue(pg.is_enabled(sel))
        self.assertEqual(pg.locator("[data-heartbeat-limit]").count(), 0)
        # The watch list spans the section; its heading and hint each take a line.
        tree_node(pg, 0, "supervision")
        pg.wait_for_selector(".grid > .heartbeat-watch")
        self.assertEqual(pg.eval_on_selector(".heartbeat-watch", "(e) => e.offsetWidth === e.parentElement.clientWidth"), True)
        for c in (".heartbeat-watch > .row-head", ".heartbeat-watch > .hint"):
            self.assertEqual(pg.eval_on_selector(c, "(e) => getComputedStyle(e).display"), "block", c)

    def test_lss_and_config_check_reasons_look_alike(self):
        pg = self.page
        self.open()  # the ping-pong EDS has neither LSS nor 0x1020
        tree_node(pg, 0, "advanced")
        pg.wait_for_selector("[data-lss-warning]")
        check = pg.locator('input[data-path="nodes[0].config_check"]').locator("xpath=ancestor::div[1]").locator(".hint")
        self.assertIn("no 0x1020", check.inner_text())
        for theme in ("light", "dark"):
            pg.evaluate("(t) => { document.documentElement.dataset.theme = t; }", theme)
            self.assertEqual(self.color("[data-lss-warning]"), check.evaluate("(e) => getComputedStyle(e).color"), theme)
            self.assertEqual(pg.get_attribute("[data-lss-warning]", "class"), "hint")
