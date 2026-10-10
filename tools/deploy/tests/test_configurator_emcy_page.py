"""The device error history panel (0x1003) of the online node page and the
node page's EMCY COB-ID field, in a real browser against a fake plugin
(add-emcy-history tasks 5.3 and 5.4). Needs Playwright, like
test_configurator_page.py."""

from .fake_diag import FakePlugin
from .test_configurator_online_page import OnlineBase
from .test_configurator_page import load


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
        pg.wait_for_selector('[data-online="error-field"]')
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
            self.assertEqual(pg.inner_text('[data-online="error-field"]'), "Node 2 has no error history (0x1003).")

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
    def node_page(self):
        pg = self.page
        self.open()
        pg.click('#node-list [data-node="0"]')
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
        pg.click('#node-list [data-node="0"]')
        pg.wait_for_selector('select[data-emcy-cob="mode"]')
        self.assertEqual(pg.input_value('select[data-emcy-cob="mode"]'), "number")
        self.assertEqual(pg.input_value('input[data-emcy-cob="number"]'), "197")
