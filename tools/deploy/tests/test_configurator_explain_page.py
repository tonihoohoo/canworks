"""Frame explanations in a real browser (add-frame-inspector tasks 4.2-4.4):
the inspector under the Trace view's frame list, the Sequences tab and the
Frame lab. Needs Playwright, like test_configurator_page.py."""

import json

from .test_configurator_layout import FIT_CHECK
from .test_configurator_trace_page import TraceBase


class Inspector(TraceBase):
    def open_sample(self):
        pg = self.page
        self.open()
        self.trace_view()
        pg.set_input_files('input[data-trace="open-input"]', self.sample_file())
        pg.wait_for_selector("#trace-rows .trace-row")

    def box(self):
        return self.page.inner_text("[data-fx=box]")

    def test_point_keyboard_and_follow(self):
        pg = self.page
        self.open_sample()
        pg.click("#trace-rows .trace-row:has-text('pingpong_TPDO1')")
        pg.wait_for_selector("#trace-inspector [data-fx=inspector][data-kind=pdo]")
        self.assertIn("%ID300 = 1", pg.inner_text("#trace-inspector [data-fx=meaning]"))
        # Point at bit 2 of byte 0: the box names the bit of the PLC address,
        # the object and the wire bit, and the bit is lit in grid and wire.
        pg.hover('#trace-inspector [data-fx=grid] [data-ref="data.0.2"]')
        box = self.box()
        for text in ("Bit 2 = ", "bit 2 of %ID300", "4001h:00", "Wire bit"):
            self.assertIn(text, box)
        lit = pg.eval_on_selector_all('#trace-inspector [data-ref="data.0.2"].hl', "es => es.map(e => e.tagName)")
        self.assertEqual(sorted(lit), ["BUTTON", "g"])
        # Point at an identifier bit: the function code part.
        pg.hover('#trace-inspector [data-fx=identifier] [data-ref="id.8"]')
        self.assertIn("function code", self.box())
        # Keyboard: tab into the grid, move with the arrows.
        pg.focus('#trace-inspector [data-fx=grid] [data-ref="data.0.7"]')
        self.assertIn("CANopen bit\n7", self.box())
        pg.keyboard.press("ArrowRight")
        self.assertIn("CANopen bit\n6", self.box())
        pg.keyboard.press("ArrowDown")
        self.assertIn("CANopen bit\n14", self.box())
        # The wire strip: one tab stop, arrows walk through its bits.
        pg.focus("#trace-inspector [data-fx=wire]")
        self.assertIn("Wire bit 0: Start of frame", self.box())
        pg.keyboard.press("ArrowRight")
        self.assertIn("Identifier bit 10", self.box())
        # Up and down in the frame list move the inspector along.
        pg.focus("#trace-list")
        before = pg.inner_text("#trace-inspector [data-fx=meaning]")
        pg.keyboard.press("ArrowDown")
        pg.wait_for_function("t => (document.querySelector('#trace-inspector [data-fx=meaning]') || {}).innerText !== t", arg=before)
        self.assertEqual(len(pg.query_selector_all("#trace-rows .trace-row.selected")), 1)

    def test_sequences(self):
        pg = self.page
        self.open_sample()
        pg.click('[data-trace-tab="sequences"]')
        pg.wait_for_selector("[data-fx=sequences] table tbody tr")
        self.assertEqual(len(pg.query_selector_all("[data-fx=sequences] tbody tr")), 2)
        pg.select_option("[data-fx-filter=result]", "aborted")
        pg.wait_for_function("() => document.querySelectorAll('[data-fx=sequences] tbody tr').length === 1")
        pg.click("[data-fx=sequences] tbody tr")
        # From the conversation to the abort frame.
        pg.click("[data-fx=diagram] .fx-arrow.bad")
        pg.wait_for_selector("#fx-seq-inspector [data-fx=inspector][data-kind=sdo]")
        self.assertIn("attempt to write a read only object", pg.inner_text("#fx-seq-inspector [data-fx=meaning]"))
        # SYNC cycles: step and jump.
        pg.click("[data-fx-sub=sync]")
        pg.wait_for_selector("[data-fx=timeline]")
        self.assertIn("SYNC cycle 1,", pg.text_content("#fx-seq-detail h3"))
        pg.click("[data-fx-sync=next]")
        pg.wait_for_selector("#fx-seq-detail h3:has-text('SYNC cycle 2')")
        pg.click("[data-fx=timeline] .fx-mark.g-sync_pdo")
        pg.wait_for_selector("#fx-seq-inspector [data-fx=inspector][data-kind=pdo]")
        # From a frame in the list to its conversation.
        pg.click('[data-trace-tab="frames"]')
        pg.fill('[data-trace-filter="text"]', "abort")
        pg.press('[data-trace-filter="text"]', "Tab")
        self.wait_rows(1)
        pg.click("#trace-rows .trace-row")
        pg.click("[data-fx-go=sdo]")
        pg.wait_for_selector("[data-fx=sequences] tbody tr.selected")
        self.assertIn("aborted", pg.inner_text("[data-fx=sequences] tbody tr.selected"))


class FrameLab(TraceBase):
    def test_lab_without_a_runtime(self):
        pg = self.page
        requests = []
        pg.on("request", lambda r: requests.append(r.url))
        self.open()
        del requests[:]
        pg.click('button[data-view="framelab"]')
        self.assertIn("Nothing here is sent", pg.inner_text("[data-fx=nothing-sent]"))
        # A pasted frame.
        pg.fill("[data-fx=lab-frame]", "705#7F")
        pg.click("[data-fx=lab-explain]")
        pg.wait_for_selector("#fx-lab-inspector [data-fx=meaning]")
        self.assertIn("Node 5 is PRE-OPERATIONAL", pg.inner_text("#fx-lab-inspector [data-fx=meaning]"))
        self.assertIn("at 125 kbit/s", pg.inner_text("#fx-lab-inspector [data-fx=stats]"))
        pg.select_option("[data-fx=lab-bitrate]", "1000000")
        pg.wait_for_selector("#fx-lab-inspector [data-fx=stats]:has-text('1 Mbit/s')")
        pg.fill("[data-fx=lab-frame]", "705#123")
        pg.click("[data-fx=lab-explain]")
        pg.wait_for_selector("#fx-lab-error:has-text('whole bytes')")
        # The previous result does not stay under the error.
        self.assertEqual(pg.locator("#fx-lab-inspector [data-fx=inspector]").count(), 0)
        pg.fill("[data-fx=lab-frame]", "#00")
        pg.click("[data-fx=lab-explain]")
        pg.wait_for_selector("#fx-lab-error:has-text('the identifier is missing')")
        # Examples from the configuration, also unsaved: add a node first.
        pg.wait_for_selector("[data-fx=examples] .chip")
        self.assertIn("pingpong", pg.inner_text("[data-fx=examples]"))
        pg.click('[data-fx=examples] .chip:has-text("Heartbeat OPERATIONAL")')
        pg.wait_for_selector("#fx-lab-inspector [data-fx=meaning]:has-text('OPERATIONAL')")
        # The builder: an SDO write with its answer.
        pg.click("summary:has-text('Build a frame')")
        pg.fill("[data-fx-build=index]", "1017")
        pg.select_option("[data-fx-build=op]", "write")
        pg.fill("[data-fx-build=value]", "1000")
        pg.click("[data-fx-build=go]")
        pg.wait_for_selector("[data-fx=built] .chip")
        self.assertIn("602#2B171000E8030000", pg.input_value("[data-fx=lab-frame]"))
        pg.click("[data-fx=built] .chip:nth-of-type(2)")
        pg.wait_for_selector("#fx-lab-inspector [data-fx=meaning]:has-text('confirms')")
        # Arbitration: 0x183 against 0x185.
        pg.click("summary:has-text('Arbitration')")
        pg.fill("[data-fx-arb=arbA]", "185#2500EA00")
        pg.fill("[data-fx-arb=arbB]", "183#01")
        pg.click("[data-fx-arb=go]")
        pg.wait_for_selector("[data-fx=arb-result]")
        text = pg.inner_text("[data-fx=arb-result]")
        self.assertIn("up to identifier bit 2", text)
        self.assertIn("(0x183) wins", text)
        self.assertEqual(len(pg.query_selector_all("[data-fx=arbitration] .fx-arbcell.lost")), 1)
        bad = [u for u in requests if "/api/online" in u or "/api/trace" in u or "/api/sim" in u]
        self.assertEqual(bad, [])

    def test_builder_messages_and_network_switch(self):
        pg = self.page
        io = dict(self.cfg, name="io")
        io.pop("schema_version", None)
        line = {"name": "line", "adapter": {"type": "socketcan", "interface": "can1", "bitrate": 125000},
                "master": {"node_id": 1}, "nodes": [{"node_id": 3, "name": "other", "eds": "cpp-slave.eds"}]}
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump({"schema_version": 2, "networks": [io, line]}, f)
        self.open()
        pg.click('button[data-view="framelab"]')
        pg.click("summary:has-text('Build a frame')")
        pg.fill("[data-fx-build=index]", "zz")
        pg.click("[data-fx-build=go]")
        pg.wait_for_selector("#fx-build-error:has-text(\"index: 'zz' is not a hex number\")")
        pg.fill("[data-fx=lab-frame]", "702#05")
        pg.click("[data-fx=lab-explain]")
        pg.wait_for_selector("#fx-lab-inspector [data-fx=inspector]")
        # Another network: the frame and its result belonged to io.
        pg.click('.net-tab[data-net="1"]')
        pg.click('button[data-view="framelab"]')
        pg.wait_for_selector("[data-fx=examples] .chip")
        self.assertEqual(pg.input_value("[data-fx=lab-frame]"), "")
        self.assertEqual(pg.locator("#fx-lab-inspector [data-fx=inspector]").count(), 0)
        self.assertIn("node 3 (other)", pg.inner_text("[data-fx=examples]"))

    def test_examples_follow_the_unsaved_config(self):
        pg = self.page
        self.open()
        pg.evaluate("""() => { S.config.nodes.push({node_id: 7, name: "extra", eds: S.config.nodes[0].eds}); }""")
        pg.click('button[data-view="framelab"]')
        pg.wait_for_selector("[data-fx=examples] .chip")
        text = pg.inner_text("[data-fx=examples]")
        self.assertIn("node 7 (extra)", text)

    def test_phone_width_and_dark(self):
        pg = self.page
        self.open()
        pg.set_viewport_size({"width": 390, "height": 800})
        pg.click('button[data-view="framelab"]')
        pg.fill("[data-fx=lab-frame]", "185#2500EA00")
        pg.click("[data-fx=lab-explain]")
        pg.wait_for_selector("#fx-lab-inspector [data-fx=inspector]")
        pg.wait_for_timeout(300)
        self.assertEqual(pg.evaluate(FIT_CHECK), [])
        pg.evaluate("() => document.documentElement.setAttribute('data-theme', 'dark')")
        bg = pg.evaluate("() => getComputedStyle(document.querySelector('.fx-layer')).backgroundColor")
        self.assertEqual(bg, "rgb(31, 31, 29)")
