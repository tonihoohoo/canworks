"""Safe settings for new nodes and adapters, and the Problems for a bridge
stop and a bus-off (safe-node-defaults): a new output node watches the
master heartbeat and skips unchanged downloads, a new SocketCAN adapter
restarts after a bus-off, each in the edit's undo step and never again
after the user turned it off; loaded files stay as they are. Needs
Playwright, like test_configurator_page.py."""

import os
import shutil

from .helpers import REPO, add_node
from .test_configurator_online_page import OnlineBase

DIO = os.path.join(REPO, "examples", "modbus-bridge", "dio16.eds")
CONVEYOR = os.path.join(REPO, "examples", "virtual-plant", "canworks", "conveyor.eds")  # a default RPDO mapping
NOT_PROTECTED = "keeps its last outputs when the bridge crashes or loses power"
BUS_OFF = "after a bus-off the interface stays off"


class SafeDefaults(OnlineBase):
    def setUp(self):
        super().setUp()
        # The ping-pong node without the heartbeat settings, as a file written before them.
        net = self.cfg["networks"][0]
        net["master"].pop("heartbeat_ms", None)
        net["nodes"][0].pop("heartbeat_consumer", None)
        self.write_config()
        for eds in (DIO, CONVEYOR):
            shutil.copy(eds, os.path.join(self.project, "canworks"))

    def problems(self):
        return self.page.inner_text("#problem-list")

    def wait_problem(self, text, present=True):
        self.page.wait_for_function("([t, p]) => document.querySelector('#problem-list').textContent.includes(t) === p",
                                    arg=[text, present])

    def node(self, i):
        return self.page.evaluate("(i) => S.config.nodes[i]", i)

    def master(self):
        return self.page.evaluate("() => S.config.master")

    def test_new_output_node(self):
        pg = self.page
        self.open()
        add_node(pg, CONVEYOR, map_pdos=True, node_id=6, name="conveyor")
        n = self.node(1)
        self.assertTrue(n["rx_pdos"])
        self.assertTrue(n["config_check"])
        self.assertTrue(n["heartbeat_consumer"])
        self.assertEqual(self.master()["heartbeat_ms"], 100)
        # One undo takes the node and its settings together.
        pg.keyboard.press("Control+z")
        pg.wait_for_function("() => S.config.nodes.length === 1")
        self.assertNotIn("heartbeat_ms", self.master())

    def test_first_output_entry_and_turned_off(self):
        pg = self.page
        self.open()
        add_node(pg, DIO, node_id=6, name="dio")
        n = self.node(1)
        self.assertTrue(n["config_check"])
        self.assertNotIn("heartbeat_consumer", n)
        add_entry = """(loc) => {
          const n = S.config.nodes[1];
          n.rx_pdos = n.rx_pdos || [{ number: 1, entries: [] }];
          n.rx_pdos[0].entries.push({ index: "0x6200", subindex: 1, type: "UNSIGNED8", iec_location: loc });
          changed(true);
        }"""
        pg.evaluate(add_entry, "%QB310")
        self.assertTrue(self.node(1)["heartbeat_consumer"])
        self.assertEqual(self.master()["heartbeat_ms"], 100)
        # The heartbeat settings go with the entry in one undo step.
        pg.keyboard.press("Control+z")
        pg.wait_for_function("() => !S.config.nodes[1].rx_pdos")
        self.assertNotIn("heartbeat_consumer", self.node(1))
        self.assertNotIn("heartbeat_ms", self.master())
        pg.keyboard.press("Control+Shift+z")
        pg.wait_for_function("() => S.config.nodes[1].heartbeat_consumer === true")
        # Turned off by the user: another entry leaves it off.
        pg.evaluate("() => { S.config.nodes[1].heartbeat_consumer = false; changed(true); }")
        pg.evaluate(add_entry, "%QB311")
        self.assertIs(self.node(1)["heartbeat_consumer"], False)

    def test_fix_from_problems(self):
        pg = self.page
        self.open()
        self.wait_problem(NOT_PROTECTED)
        # Loaded as it is: nothing to save.
        self.assertFalse(pg.evaluate("() => S.dirty"))
        self.assertNotIn("heartbeat_consumer", self.node(0))
        pg.click('#problem-list [data-problem-fix="heartbeat-consumer"]')
        self.wait_problem(NOT_PROTECTED, False)
        self.assertTrue(self.node(0)["heartbeat_consumer"])
        self.assertEqual(self.master()["heartbeat_ms"], 100)
        pg.keyboard.press("Control+z")
        self.wait_problem(NOT_PROTECTED)
        self.assertNotIn("heartbeat_consumer", self.node(0))
        self.assertNotIn("heartbeat_ms", self.master())

    def test_bus_off_restart_fix(self):
        pg = self.page
        self.cfg["networks"][0]["adapter"]["interface"] = "can0"
        self.write_config()
        self.open()
        self.wait_problem(BUS_OFF)
        self.assertNotIn("restart_ms", pg.evaluate("() => S.config.adapter"))
        pg.click('#problem-list [data-problem-fix="restart-ms"]')
        self.wait_problem(BUS_OFF, False)
        self.assertEqual(pg.evaluate("() => S.config.adapter.restart_ms"), 100)
        pg.keyboard.press("Control+z")
        self.wait_problem(BUS_OFF)

    def test_new_adapters_restart_after_bus_off(self):
        pg = self.page
        self.open()
        self.assertEqual(pg.evaluate("() => newJ1939Network().adapter.restart_ms"), 100)
        pg.evaluate("() => { S.config.adapter.type = 'slcan'; S.config.adapter.device = '/dev/ttyACM0'; changed(true); }")
        pg.evaluate("() => switchAdapterType('socketcan')")
        self.assertEqual(pg.evaluate("() => S.config.adapter.restart_ms"), 100)
