"""The bridge's Modbus requests in the Trace view in a real browser
(add-modbus-traffic-view task 4.3; canopen-configurator "Modbus requests in
the Trace view"): Capture… on a bridge project and elsewhere, Modbus rows
between the CAN rows, the inspector with hints and delays, the source filter
and By request. Needs Playwright, like test_configurator_page.py."""

import json
import os
import shutil
import time

from canworks import diag
from canworks.bustrace import formats
from canworks.bustrace.model import Frame, Trace
from canworks.bustrace.modbus import Record

from .fake_diag import TOKEN, FakePlugin
from .test_configurator_trace_page import TraceBase
from .test_modbus_trace import EXAMPLE, read4, write16


def bridge_trace():
    t = Trace()
    q, a = write16(1, [500])
    t.append(Frame(9_999_000, 0x206, bytes(6)))
    t.append_modbus(Record(10_000_000, "127.0.0.1", q, a, port=40000, conn=1))
    t.append(Frame(10_002_000, 0x206, bytes(6)))
    t.append(Frame(10_004_000, 0x206, bytes([0, 0, 0xF4, 0x01, 0, 0])))  # carries 500
    # An HMI reading 40001 in 4xxxx notation: exception 2.
    t.append_modbus(Record(10_500_000, "192.168.10.20", bytes([3, 0x9C, 0x41, 0, 1]), bytes([0x83, 2]), port=40001,
                           conn=2))
    t.append(Frame(20_000_000, 0x185, (77).to_bytes(2, "little") + bytes(6)))
    q, a = read4(0, [77])
    t.append_modbus(Record(20_007_000, "127.0.0.1", q, a, port=40000, conn=1))
    t.meta["modbus_port"] = 1502
    return t


class BridgeBase(TraceBase):
    def setUp(self):
        super().setUp()
        with open(EXAMPLE, encoding="utf-8") as f:
            self.cfg = json.load(f)
        self.cfg["bridge"]["connections"] = [{"kind": "plc", "name": "OpenPLC", "address": "127.0.0.1", "writes": True},
                                             {"kind": "plc", "name": "Line HMI", "address": "192.168.10.20"}]
        folder = os.path.dirname(EXAMPLE)
        for name in os.listdir(folder):
            if name.endswith(".eds"):
                shutil.copy(os.path.join(folder, name), os.path.join(self.project, "canworks"))
        self.write_config()

    def capture(self):
        if not self.page.evaluate("document.querySelector('[data-trace=capture]').open"):
            self.page.click("[data-trace=capture] > summary")


class Opened(BridgeBase):
    def test_rows_inspector_filter_and_by_request(self):
        pg = self.page
        self.open()
        self.trace_view()
        path = os.path.join(self.dir, "bridge.pcapng")
        with open(path, "wb") as f:
            f.write(written_pcapng(bridge_trace()))
        pg.set_input_files('input[data-trace="open-input"]', path)
        pg.wait_for_selector("#trace-source:has-text('File bridge.pcapng')")
        pg.wait_for_selector("[data-trace=stats]:has-text('3 Modbus requests')")
        # By identifier has By request: the HMI's 40001 read with its exception and hint.
        pg.wait_for_selector("[data-trace=by-request] table.modbus-requests")
        hmi = pg.inner_text('[data-modbus-request="192.168.10.20 3 40001"]')
        self.assertIn("Line HMI", hmi)
        self.assertIn("exception 0x02", hmi)
        self.assertIn("4xxxx notation", pg.get_attribute('[data-modbus-request="192.168.10.20 3 40001"]', "title"))
        write = pg.inner_text('[data-modbus-request="127.0.0.1 16 1"]')
        self.assertIn("4.0 / 4.0 / 4.0", write)  # the write's delay to the RPDO
        # Chronological: the Modbus rows between the CAN rows.
        self.chronological()
        self.wait_rows(7)
        kinds = pg.eval_on_selector_all("#trace-rows .trace-row", "rs => rs.map(r => r.dataset.kind || '')")
        self.assertEqual(kinds, ["", "modbus", "", "", "modbus", "", "modbus"])
        # The write in the inspector: its value by name and the delay with a link to the frame.
        pg.click('#trace-rows .trace-row[data-kind=modbus] >> nth=0')
        pg.wait_for_selector("[data-trace=modbus-inspector]")
        insp = pg.inner_text("[data-trace=modbus-inspector]")
        self.assertIn("modbus write from openplc", insp.lower())
        self.assertIn("%QW2", insp)
        self.assertIn("4.0 ms to", insp)
        pg.click("[data-trace=modbus-to-frame]")
        pg.wait_for_function("() => { const r = document.querySelector('#trace-rows .trace-row.selected');"
                             " return r && !r.dataset.kind && r.innerText.includes('206'); }")
        pg.wait_for_selector("#trace-inspector :text('Explain in Frame lab')")
        # The HMI's read: the hint.
        pg.click('#trace-rows .trace-row[data-kind=modbus] >> nth=1')
        pg.wait_for_selector("[data-trace=modbus-hint]:has-text('Holding registers start at 0 here')")
        # The source filter: Modbus only, and the statistics say how many show.
        self.filters()
        pg.select_option("[data-trace-filter=source]", "modbus")
        self.wait_rows(3)
        self.assertEqual(set(pg.eval_on_selector_all("#trace-rows .trace-row", "rs => rs.map(r => r.dataset.kind)")),
                         {"modbus"})
        pg.wait_for_selector("[data-trace=stats]:has-text('showing 3 of 7')")
        pg.select_option("[data-trace-filter=source]", "can")
        self.wait_rows(4)
        # A save as candump says it leaves the Modbus records out; pcapng keeps them.
        self.assertTrue(formats.left_out(bridge_trace(), "candump"))


def written_pcapng(trace):
    import io
    buf = io.BytesIO()
    formats.write(trace, buf, "pcapng")
    return buf.getvalue()


class Capture(BridgeBase):
    def test_record_with_modbus_on(self):
        pg = self.page
        with FakePlugin() as fake:
            fake.modbus_bridge = True
            self.write_config({"token_verifier": diag.token_verifier(TOKEN)})
            self.remember(fake.runtime)
            self.open()
            self.trace_view()
            self.capture()
            self.assertTrue(pg.is_checked("[data-trace=modbus-on]"))
            self.assertTrue(pg.is_checked("[data-trace=modbus-changes]"))
            pg.uncheck("[data-trace=modbus-changes]")
            pg.select_option("[data-trace=modbus-client]", "192.168.10.20")
            pg.click("[data-trace=start-stop]")
            pg.wait_for_selector("#trace-source:has-text('recording')")
            end = time.time() + 5
            while time.time() < end and not fake.modbus_starts:
                time.sleep(0.05)
            self.assertEqual(fake.modbus_starts[-1]["changes_only"], False)
            self.assertEqual(fake.modbus_starts[-1]["clients"], ["192.168.10.20"])
            q, a = write16(1, [3])
            fake.push_modbus([Record(int(time.time() * 1e6), "192.168.10.20", q, a)])
            pg.wait_for_selector("[data-trace=stats]:has-text('1 Modbus requests')", timeout=8000)
            pg.click("[data-trace=start-stop]")
            pg.wait_for_selector("#trace-source:has-text('stopped')")


class NotABridge(TraceBase):
    def test_runtime_that_is_not_a_bridge(self):
        """Recording from a runtime that does not run canworks-bridge records
        the CAN frames and says why there are no Modbus requests."""
        pg = self.page
        with FakePlugin() as fake:
            self.write_config({"token_verifier": diag.token_verifier(TOKEN)})
            self.remember(fake.runtime)
            self.open()
            self.trace_view()
            pg.click("[data-trace=start-stop]")
            pg.wait_for_selector("#trace-source:has-text('recording')")
            pg.wait_for_selector("[data-trace=modbus-rec-note]:has-text('not a bridge')")
            pg.click("[data-trace=start-stop]")
            pg.wait_for_selector("#trace-source:has-text('stopped')")


def client(address, port, **kw):
    out = {"address": address, "port": port, "connection": port - 40000, "requests": 100, "writer": False,
           "connected_us": 0, "rate": 10.0, "functions": {"3": 100}, "exceptions": {}, "refused_writes": 0,
           "last_write": None}
    out.update(kw)
    return out


class ClientsPanel(BridgeBase):
    def test_connected_not_connected_and_unknown(self):
        from .helpers import tree_view
        pg = self.page
        with FakePlugin() as fake:
            fake.status["bridge"] = {
                "clients": [client("127.0.0.1", 40001, rate=100.0, writer=True,
                                   last_write={"time_us": 1, "function": 16, "table": "holding register", "start": 1,
                                               "count": 1}),
                            client("192.168.10.77", 40002, refused_writes=3, exceptions={"0x01": 3})],
                "closed_clients": [dict(client("10.0.0.5", 40003), reason="idle 60 s", ago_s=125, connected_s=60,
                                        closed_us=1)]}
            self.write_config({"token_verifier": diag.token_verifier(TOKEN)})
            self.remember(fake.runtime)
            self.open()
            tree_view(pg, "bus")
            tree_view(pg, "bridge")
            pg.wait_for_selector("[data-bridge-clients=offline]:has-text('Connect with Connect')")
            pg.click('button[data-view="online"]')
            pg.wait_for_selector("text=Connected to")
            pg.click('#ws [data-ws="configure"]')
            tree_view(pg, "bridge")
            pg.wait_for_selector('[data-bridge-client="127.0.0.1"][data-client-state=connected]')
            plc = pg.inner_text('[data-bridge-client="127.0.0.1"]')
            self.assertIn("OpenPLC", plc)
            self.assertIn("100.0", plc)
            pg.wait_for_function("() => document.querySelector('[data-bridge-client=\"127.0.0.1\"]').innerText.includes('HR 1: ')")
            hmi = pg.inner_text('[data-bridge-client="192.168.10.20"]')
            self.assertIn("Line HMI", hmi)
            self.assertIn("Not connected", hmi)
            unknown = pg.inner_text('[data-bridge-client="192.168.10.77"]')
            self.assertIn("Not in connections", unknown)
            self.assertIn("0x01: 3", unknown)
            self.assertIn("3", unknown)
            pg.click("[data-bridge=closed-clients] > summary")
            closed = pg.inner_text('[data-closed-client="10.0.0.5"]')
            self.assertIn("idle 60 s", closed)
            self.assertIn("2 min ago", closed)
            # Add connection from the unknown writer: the dialog with its address.
            pg.click('[data-bridge-client-add="192.168.10.77"]')
            pg.wait_for_selector("[data-conn-dialog]")
            self.assertEqual(pg.input_value("[data-conn-address]"), "192.168.10.77")
