"""The mailbox blocks a program declares (mailboxes-on-demand): the scan
of ST text and of an editor project, and the parts they need."""

import json
import os
import re
import unittest

from canworks import mailboxuse

from .helpers import REPO, tmpdir


class Scan(unittest.TestCase):
    def test_declarations(self):
        found = mailboxuse.scan_text(
            "PROGRAM main\n  VAR\n    a, b : CAN_RECEIVE;\n    c : can_send;\n"
            "    jobs : ARRAY [0..3] OF CAN_SEND_CYCLIC;\n    rd : CO_SDO_READ;\n  END_VAR\nEND_PROGRAM\n")
        self.assertEqual(found, {"CAN_RECEIVE": {"main": 2}, "CAN_SEND": {"main": 1}, "CAN_SEND_CYCLIC": {"main": 4}})

    def test_comments_strings_and_assignments(self):
        found = mailboxuse.scan_text(
            "PROGRAM main\n  VAR\n    (* x : CAN_RECEIVE; *)\n    // y : CAN_SEND;\n"
            "    s : STRING := 'z : CO_RECV_EMCY';\n  END_VAR\n  n := CAN_BUS_INFO;\nEND_PROGRAM\n")
        self.assertEqual(found, {})

    def test_pou_names_and_generated(self):
        found = mailboxuse.scan_text(
            "FUNCTION_BLOCK pump\n  VAR\n    info : CAN_BUS_INFO;\n  END_VAR\nEND_FUNCTION_BLOCK\n"
            "PROGRAM canworks_in\n  VAR\n    s : CAN_SEND;\n  END_VAR\nEND_PROGRAM\n")
        self.assertEqual(found, {"CAN_BUS_INFO": {"pump": 1}})

    def test_arrays_namespaces_and_function_blocks(self):
        # canopen-configurator "Mailbox detection in programs": named and 2-D
        # bounds, canworks.X, blocks in a user FB once per instance.
        found = mailboxuse.scan_text(
            "FUNCTION_BLOCK Axis\n  VAR\n    job : canworks.CAN_SEND_CYCLIC;\n  END_VAR\nEND_FUNCTION_BLOCK\n"
            "PROGRAM main\n  VAR CONSTANT\n    N : INT := 3;\n  END_VAR\n  VAR\n"
            "    rx : ARRAY[1..N] OF CAN_RECEIVE;\n    cy : ARRAY[0..1, 0..1] OF CAN_SEND_CYCLIC;\n"
            "    a : ARRAY[0..7] OF Axis;\n  END_VAR\nEND_PROGRAM\n")
        self.assertEqual(found, {"CAN_RECEIVE": {"main": 3}, "CAN_SEND_CYCLIC": {"main": 4, "Axis": 8}})
        self.assertEqual(mailboxuse.parts_needed(found), {"request": 1, "receive": 1, "cyclic": 12})

    def test_nested_function_blocks_and_expressions(self):
        found = mailboxuse.scan_text(
            "VAR_GLOBAL CONSTANT\n  M : INT := 2;\nEND_VAR\n"
            "FUNCTION_BLOCK Inner\n  VAR\n    s : ARRAY[0..M-1] OF CAN_SEND_CYCLIC;\n  END_VAR\nEND_FUNCTION_BLOCK\n"
            "FUNCTION_BLOCK Outer\n  VAR\n    i1, i2 : Inner;\n  END_VAR\nEND_FUNCTION_BLOCK\n"
            "PROGRAM main\n  VAR\n    o : ARRAY[1..2] OF Outer;\n  END_VAR\nEND_PROGRAM\n")
        self.assertEqual(found, {"CAN_SEND_CYCLIC": {"Inner": 8}})

    def test_unknown_count(self):
        # A bound the scan cannot work out: the most for that part.
        found = mailboxuse.scan_text(
            "PROGRAM main\n  VAR\n    cy : ARRAY[0..SIZEOF(x)] OF CAN_SEND_CYCLIC;\n"
            "    rx : ARRAY[0..K] OF CAN_RECEIVE;\n  END_VAR\nEND_PROGRAM\n")
        self.assertEqual(found, {"CAN_SEND_CYCLIC": {"main": None}, "CAN_RECEIVE": {"main": None}})
        self.assertEqual(mailboxuse.parts_needed(found), {"request": 1, "receive": 1, "cyclic": 16})
        self.assertIn("main declares CAN_SEND_CYCLIC",
                      mailboxuse.describe("CAN_SEND_CYCLIC", found["CAN_SEND_CYCLIC"], ["cyclic"]))

    def test_other_pou_files(self):
        # Ladder, FBD and the editor's JSON POUs: the block names, count unknown.
        d = tmpdir(self)
        os.makedirs(os.path.join(d, "pous", "programs"))
        os.makedirs(os.path.join(d, "pous", "function-blocks"))
        with open(os.path.join(d, "pous", "programs", "main.json"), "w", encoding="utf-8") as f:
            json.dump({"name": "main", "body": {"rungs": [{"nodes": [
                {"type": "block", "data": {"variant": {"name": "CAN_RECEIVE"}}},
                {"type": "block", "data": {"variant": {"name": "Axis"}}}]}]}}, f)
        with open(os.path.join(d, "pous", "programs", "aux.fbd"), "w", encoding="utf-8") as f:
            f.write('<block typeName="canworks.CAN_BUS_INFO" instanceName="bi"/>\n')
        with open(os.path.join(d, "pous", "function-blocks", "Axis.st"), "w", encoding="utf-8") as f:
            f.write("FUNCTION_BLOCK Axis\nVAR\n job : CAN_SEND_CYCLIC;\nEND_VAR\nEND_FUNCTION_BLOCK\n")
        self.assertEqual(mailboxuse.scan_project(d), {"CAN_RECEIVE": {"main": None}, "CAN_BUS_INFO": {"aux": None},
                                                      "CAN_SEND_CYCLIC": {"Axis": None}})

    def test_constants_from_other_files(self):
        d = tmpdir(self)
        os.makedirs(os.path.join(d, "pous", "programs"))
        with open(os.path.join(d, "pous", "programs", "main.st"), "w", encoding="utf-8") as f:
            f.write("PROGRAM main\nVAR\n cy : ARRAY[1..JOBS] OF CAN_SEND_CYCLIC;\nEND_VAR\nEND_PROGRAM\n")
        with open(os.path.join(d, "project.json"), "w", encoding="utf-8") as f:
            json.dump({"data": {"globalVariableLists": [{"name": "g", "variables": [
                {"name": "JOBS", "class": "constant", "type": {"definition": "base-type", "value": "INT"},
                 "initialValue": "6"}]}]}}, f)
        self.assertEqual(mailboxuse.scan_project(d), {"CAN_SEND_CYCLIC": {"main": 6}})

    def test_project(self):
        d = tmpdir(self)
        os.makedirs(os.path.join(d, "pous", "programs"))
        os.makedirs(os.path.join(d, "pous", "function-blocks"))
        with open(os.path.join(d, "pous", "programs", "main.st"), "w", encoding="utf-8") as f:
            f.write("PROGRAM main\nVAR\n rx : CAN_RECEIVE;\nEND_VAR\nEND_PROGRAM\n")
        with open(os.path.join(d, "pous", "programs", "canworks_out.st"), "w", encoding="utf-8") as f:
            f.write("PROGRAM canworks_out\nVAR\n s : CAN_SEND;\nEND_VAR\nEND_PROGRAM\n")
        with open(os.path.join(d, "pous", "function-blocks", "pump.st"), "w", encoding="utf-8") as f:
            f.write("FUNCTION_BLOCK pump\nVAR\n e : CO_RECV_EMCY;\nEND_VAR\nEND_FUNCTION_BLOCK\n")
        with open(os.path.join(d, "project.json"), "w", encoding="utf-8") as f:
            json.dump({"data": {"globalVariableLists": [{"name": "g", "variables": [
                {"name": "info", "type": {"definition": "derived", "value": "J1939_ECU_INFO"}}]}]}}, f)
        self.assertEqual(mailboxuse.scan_project(d), {"CAN_RECEIVE": {"main": 1}, "CO_RECV_EMCY": {"pump": 1},
                                                      "J1939_ECU_INFO": {"g": 1}})

    def test_examples(self):
        self.assertEqual(mailboxuse.scan_project(os.path.join(REPO, "examples", "virtual-plant")), {})
        with open(os.path.join(REPO, "examples", "openplc-modbus", "main.st"), encoding="utf-8") as f:
            need = mailboxuse.parts_needed(mailboxuse.scan_text(f.read(), "main"))
        self.assertEqual(need, {"request": 1, "receive": 1, "cyclic": 4, "info": 1})
        with open(os.path.join(REPO, "examples", "openplc-modbus", "canworks.json"), encoding="utf-8") as f:
            self.assertEqual(mailboxuse.missing(json.load(f)["bridge"].get("mailboxes"), need), [])


class Parts(unittest.TestCase):
    def test_needed(self):
        self.assertEqual(mailboxuse.parts_needed({"CO_SDO_READ_STRING": {"main": 1}}), {"request": 1})
        self.assertEqual(mailboxuse.parts_needed({"CAN_SEND_CYCLIC": {"main": 20}}), {"request": 1, "cyclic": 16})

    def test_missing_and_add(self):
        need = {"request": 1, "receive": 1}
        self.assertEqual(mailboxuse.missing(None, need), ["request", "receive"])
        current = {"requests": 1, "receive": False, "input_location": "%IB66", "output_location": "%QB32"}
        self.assertEqual(mailboxuse.missing(current, need), ["receive"])
        self.assertEqual(mailboxuse.mailboxes_for(need, current),
                         dict(current, receive=True))
        self.assertEqual(mailboxuse.mailboxes_for(need), {"requests": 1, "receive": True, "cyclic_jobs": 0,
                                                          "network_info": False})

    def test_opening_needs_a_request_mailbox(self):
        self.assertEqual(mailboxuse.mailboxes_for({"receive": 1}, {"requests": 0, "receive": False})["requests"], 1)
        self.assertEqual(mailboxuse.mailboxes_for({"cyclic": 4})["requests"], 1)

    def test_choices(self):
        self.assertEqual(mailboxuse.choice_parts("none"), {})
        self.assertEqual(mailboxuse.choice_parts("sdo_send"), {"request": 1})
        self.assertEqual(mailboxuse.choice_parts("all"), {"request": 1, "receive": 1, "cyclic": 4, "info": 1})

    def test_table_matches_the_library(self):
        # Every block of library/modbus that takes LINK and is not over the bridge's own registers.
        own = {"CO_SDO_READ", "CO_SDO_WRITE", "CO_NMT", "CO_NODE_LIVE"}
        lib = os.path.join(REPO, "library", "modbus")
        names = set()
        for name in os.listdir(lib):
            if not name.endswith(".st"):
                continue
            with open(os.path.join(lib, name), encoding="utf-8") as f:
                m = re.search(r"^\s*FUNCTION_BLOCK\s+(\w+)", f.read(), re.M)
            if m and not m.group(1).startswith("CW_") and m.group(1) not in own:
                names.add(m.group(1))
        self.assertEqual(names, set(mailboxuse.BLOCK_PARTS))


if __name__ == "__main__":
    unittest.main()
