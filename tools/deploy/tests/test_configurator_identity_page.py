"""Device names without a scan, the standard object dictionary of a node
without an EDS and Change EDS… (name-nodes-and-standard-dictionary), in Commission
a device on python-can's virtual bus. Needs Playwright, like
test_configurator_page.py."""

import os
import struct
import unittest

from .helpers import REPO, back_to_nodes, browse_eds
from .test_configurator_localbus_page import AdapterPage

EDS = os.path.join(REPO, "config", "gateway", "cpp-slave.eds")
OTHER_EDS = os.path.join(REPO, "config", "slave", "openplc-slave.eds")


def u8(v):
    return bytes([v])


def u16(v):
    return struct.pack("<H", v)


def u32(v):
    return struct.pack("<I", v)


# What a small device has beside the identity: the sub-index 0 entries the
# standard asks for, a heartbeat and two TPDOs.
SMALL = {(0x1018, 0): u8(4), (0x1001, 0): u8(0), (0x1017, 0): u16(50), (0x1003, 0): u8(2),
         (0x1003, 1): u32(0x8130), (0x1003, 2): u32(0x5000),
         (0x1800, 0): u8(5), (0x1800, 1): u32(0x180 + 7), (0x1800, 2): u8(254), (0x1800, 3): u16(0), (0x1800, 5): u16(0),
         (0x1801, 0): u8(5), (0x1801, 1): u32(0x280 + 7), (0x1801, 2): u8(254), (0x1801, 3): u16(0), (0x1801, 5): u16(0),
         (0x1A00, 0): u8(1), (0x1A00, 1): u32(0x60000108), (0x1A01, 0): u8(0)}


class IdentityPage(AdapterPage):
    def connected(self, *devices):
        pg = self.page
        self.commission()
        self.connect_adapter()
        for d in devices:
            pg.wait_for_selector('tr[data-online-node="%d"]' % d)
        return pg

    def test_heard_nodes_get_their_names(self):
        self.device(7, heartbeat_s=0.05, name="pump seven")
        self.device(8, heartbeat_s=0.05, name="", device_type=0x00020191)
        self.device(9, heartbeat_s=0.05, nmt_state=4)
        pg = self.connected(7, 8, 9)
        # No scan: the heartbeat is enough for the name.
        pg.wait_for_selector('tr[data-online-node="7"] [data-device="7"]:has-text("pump seven")', timeout=20000)
        self.assertIn("vendor 0x00000360", pg.inner_text('tr[data-online-node="7"] [data-device="7"]'))
        # No 0x1008 name: the profile from 0x1000.
        pg.wait_for_selector('tr[data-online-node="8"] [data-device="8"]:has-text("CiA 401 I/O device")', timeout=20000)
        # STOPPED does not answer SDO: the read waits.
        pg.wait_for_selector('tr[data-online-node="9"] [data-device="9"]:has-text("leave Stopped")')
        self.assertIn("No scan has run", pg.inner_text("#view"))
        # The node's heading and Status tab say what the device is.
        pg.click('button[data-open-node="7"]')
        pg.wait_for_selector('[data-online="node-heading"]:has-text("Node 7 pump seven")')
        pg.wait_for_selector('[data-online="node-device"]:has-text("serial number 0x00001234")')

    def test_no_answer_and_read_again(self):
        d = self.device(7, heartbeat_s=0.05, name="late one")
        d.sdo_mute = True
        pg = self.connected(7)
        pg.wait_for_selector('tr[data-online-node="7"] [data-device="7"]:has-text("No SDO answer")', timeout=20000)
        d.sdo_mute = False
        pg.click('tr[data-online-node="7"] button[data-device-again="7"]')
        pg.wait_for_selector('tr[data-online-node="7"] [data-device="7"]:has-text("late one")', timeout=20000)

    def test_standard_dictionary_without_an_eds(self):
        self.device(7, heartbeat_s=0.05, name="drive", device_type=0x00020192, od=dict(SMALL))
        pg = self.connected(7)
        pg.wait_for_selector('[data-device="7"]:has-text("drive")', timeout=20000)
        pg.click('button[data-open-node="7"]')
        # The SDO panel's picker lists the standard objects.
        pg.fill('[data-online="node-status"] ~ fieldset input[aria-label="Filter objects"], input[aria-label="Filter objects"]',
                "heartbeat")
        pg.wait_for_selector('select[data-online="object"] option[value="0x1017:0"]', state="attached")
        pg.select_option('select[data-online="object"]', "0x1017:0")
        self.assertEqual(pg.input_value('input[data-online="index"]'), "0x1017")
        self.assertEqual(pg.input_value('select[data-online="type"]'), "UNSIGNED16")
        # The object dictionary tab: CiA 301 and, from 0x1000, CiA 402.
        pg.click('button[data-online-tab="od"]')
        pg.wait_for_selector('[data-online="od-standard"]:has-text("CiA 402")')
        pg.wait_for_selector('tr[data-od-key="%d:0"]' % 0x6040, state="attached")
        pg.wait_for_selector('tr[data-od-key="%d:0"]' % 0x1017, state="attached")
        # An ARRAY shows sub-indices 0 and 1 until its sub-index 0 is read.
        self.assertEqual(len(pg.query_selector_all('tr[data-od-object="%d"]' % 0x1003)), 2)
        pg.click('[data-online="od-read-all"]')
        pg.wait_for_selector('[data-online="od-summary"]:has-text("not on this device")', timeout=60000)
        # 0x1003 says 2 errors: sub-indices 0-2.
        self.assertEqual(len(pg.query_selector_all('tr[data-od-object="%d"]' % 0x1003)), 3)
        # What the device lacks is hidden; TPDO 3 and 4 too.
        self.assertTrue(pg.is_checked('input[data-od-filter="lacking"]'))
        self.assertFalse(pg.is_visible('tr[data-od-object-row="%d"]' % 0x1802))
        self.assertFalse(pg.is_visible('tr[data-od-key="%d:0"]' % 0x1013))
        pg.uncheck('input[data-od-filter="lacking"]')
        # Read all unfolded the communication group (commission-master-detail).
        if not pg.locator('details[data-od-group="communication"]').evaluate("d => d.open"):
            pg.click('details[data-od-group="communication"] > summary')
        pg.wait_for_selector('tr[data-od-key="%d:0"]:has-text("Not on this device")' % 0x1013)
        # The device's EDS replaces the standard objects.
        pg.click('[data-eds-choices="od"] button[data-eds-choose]')
        browse_eds(pg, EDS)
        pg.wait_for_selector('[data-online="od-standard"]', state="detached")
        pg.wait_for_selector('[data-online="od"] tr[data-od-key]', state="attached")
        back_to_nodes(pg)
        pg.wait_for_selector('tr[data-online-node="7"] [data-node-eds="7"]:has-text("cpp-slave.eds")')

    def test_more_pdos_than_listed(self):
        od = dict(SMALL)
        for n in range(4, 6):  # RPDO 5 and 6
            od.update({(0x1400 + n, 0): u8(2), (0x1400 + n, 1): u32(0x80000000), (0x1400 + n, 2): u8(254),
                       (0x1600 + n, 0): u8(0)})
        for n in range(4):
            od.update({(0x1400 + n, 0): u8(2), (0x1400 + n, 1): u32(0x80000000), (0x1400 + n, 2): u8(254),
                       (0x1600 + n, 0): u8(0)})
        self.device(7, heartbeat_s=0.05, name="io", od=od)
        pg = self.connected(7)
        pg.click('button[data-open-node="7"]')
        pg.click('button[data-online-tab="od"]')
        pg.wait_for_selector('[data-online="od-standard"]')
        pg.click('[data-online="od-read-all"]')
        pg.wait_for_selector('tr[data-od-object-row="%d"]' % 0x1405, state="attached", timeout=60000)
        self.assertEqual(pg.query_selector_all('tr[data-od-object-row="%d"]' % 0x1406), [])

    def test_change_and_clear_the_eds(self):
        self.device(7, heartbeat_s=0.05, name="valve")
        pg = self.connected(7)
        pg.click('tr[data-online-node="7"] button[data-eds-pick="7"]')
        browse_eds(pg, EDS)
        pg.wait_for_selector('[data-online="node-header"]')
        back_to_nodes(pg)
        pg.wait_for_selector('tr[data-online-node="7"] [data-node-eds="7"]:has-text("cpp-slave.eds")')
        # The EDS column shows the file, not the device's name.
        self.assertNotIn("valve", pg.inner_text('tr[data-online-node="7"] [data-node-eds="7"]'))
        pg.click('tr[data-online-node="7"] button[data-change-eds="7"]')
        browse_eds(pg, OTHER_EDS)
        pg.wait_for_selector('[data-online="node-header"]')
        back_to_nodes(pg)
        pg.wait_for_selector('tr[data-online-node="7"] [data-node-eds="7"]:has-text("openplc-slave.eds")')
        self.assertTrue(pg.evaluate("S.commLog.some((e) => e.what.includes('cpp-slave.eds → openplc-slave.eds'))"))
        # Clear: back to the EDS choices and the standard objects.
        pg.click('tr[data-online-node="7"] button[data-change-eds="7"]')
        pg.click('[data-eds="dialog"] button[data-eds-action="clear"]')
        pg.wait_for_selector('tr[data-online-node="7"] button[data-eds-pick="7"]')
        pg.click('button[data-open-node="7"]')
        pg.click('button[data-online-tab="od"]')
        pg.wait_for_selector('[data-online="od-standard"]')
        # A node only added from an EDS is removed instead.
        back_to_nodes(pg)
        pg.click('button[data-online="add-eds"]')
        browse_eds(pg, EDS)
        pg.fill('input[data-online="add-node-id"]', "40")
        pg.click('[data-eds="use"]')
        pg.wait_for_selector('[data-online="node-heading"]:has-text("40")')
        back_to_nodes(pg)
        pg.wait_for_selector('tr[data-online-node="40"]')
        pg.click('tr[data-online-node="40"] button[data-change-eds="40"]')
        self.assertEqual(pg.query_selector_all('[data-eds="dialog"] button[data-eds-action="clear"]'), [])
        pg.click('[data-eds="dialog"] button[data-eds-action="remove"]')
        pg.wait_for_selector('tr[data-online-node="40"]', state="detached")

    def test_parameters_without_an_eds(self):
        self.device(7, heartbeat_s=0.05)
        pg = self.connected(7)
        pg.click('button[data-open-node="7"]')
        pg.click('button[data-online-tab="params"]')
        pg.wait_for_selector('[data-online="no-eds"]:has-text("need the device\'s EDS")')
        pg.wait_for_selector('[data-eds-choices="params"] button[data-eds-choose]')


if __name__ == "__main__":
    unittest.main()
