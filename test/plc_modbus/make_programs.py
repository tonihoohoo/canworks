#!/usr/bin/env python3
"""Writes the ST sources test/plc_modbus/run.sh compiles from canworks.json
here, through the deploy tool's openplcmodbus module:

    project.st   the canworks list as the editor compiles a global variable
                 list (a STRUCT type, one global, VAR_EXTERNAL in each POU
                 that uses it), canworks_in, a main with blocks,
                 canworks_out and the configuration with the three instances
                 in one task, as the editor writes them
    programs.st  canworks_in and canworks_out as function blocks without
                 locations, the list as their output and input, for the
                 conversion tests, and canworks_in_zero_fb, canworks_in
                 with "inputs_on_loss": "zero"
    other.st     the PLC link file --export-modbus-map OUT.st writes for
                 another Modbus PLC, its global variable list as a STRUCT
                 the way project.st has it, with main and a configuration
    example.st   examples/openplc-modbus: its list and programs with its
                 main.st, as project.st
    bits.st      the same example without mailboxes and with bit channels
                 on a TPDO and an RPDO entry, canworks_in and canworks_out
                 as function blocks as in programs.st

The raw signals have no REAL type, so four of them are declared REAL and
LREAL here to test those conversions.

    make_programs.py OUT_DIR
"""

import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "tools", "deploy"))

from canworks import editorproject, openplcmodbus  # noqa: E402

RETYPED = {"cab_In_real": "REAL", "cab_Wide_lreal": "LREAL", "cab_Out_real": "REAL", "cab_Wide_lreal_2": "LREAL"}

MAIN = """PROGRAM main
  VAR
    rd : CO_SDO_READ;
    live : CO_NODE_LIVE;
    name : CO_SDO_READ_STRING;
    send : CAN_SEND;
    rx : CAN_RECEIVE;
    frame : ARRAY[0..7] OF BYTE;
  END_VAR
  rd(EXECUTE := canworks.ok, NODE := 5, INDEX := 16#1018, SUBINDEX := 1, LINK := canworks.link);
  live(NETWORK := 0, NODE := 5, LINK := canworks.link);
  name(EXECUTE := canworks.ok, NODE := 5, INDEX := 16#1008, LINK := canworks.link);
  send(EXECUTE := canworks.ok, ID := 16#181, DLC := 8, DATA := frame, LINK := canworks.link);
  rx(ENABLE := canworks.ok, ID := 16#181, RX_DATA := frame, LINK := canworks.link);
  canworks.cab_Out_word := canworks.cab_In_word;
END_PROGRAM
"""


def struct(lst):
    lines = ["TYPE canworks_TYPE :", "STRUCT"]
    for v in lst["variables"]:
        lines.append("  %s : %s;" % (v["name"], v["type"]["value"]))  # an array's value is its whole type
    lines += ["END_STRUCT;", "END_TYPE", ""]
    return "\n".join(lines)


def with_external(st):
    """A program with the VAR_EXTERNAL the editor adds for the list."""
    head, rest = st.split("\n", 1)
    return "%s\n  VAR_EXTERNAL\n    canworks : canworks_TYPE;\n  END_VAR\n%s\n" % (head, rest)


def as_block(st, program, section):
    st = re.sub(r" AT %[IQ]W[0-9]+", "", st)
    st = st.replace("PROGRAM %s\n" % program,
                    "FUNCTION_BLOCK %s_fb\n  %s\n    canworks : canworks_TYPE;\n  END_VAR\n" % (program, section))
    return st.replace("END_PROGRAM", "END_FUNCTION_BLOCK") + "\n"


def main():
    out = sys.argv[1]
    path = os.path.join(HERE, "canworks.json")
    with open(path, encoding="utf-8") as f:
        cfg = json.load(f)
    decls = editorproject.declarations(cfg, path)
    for d in decls:
        d["type"] = RETYPED.get(d["name"], d["type"])
    in_st, out_st = openplcmodbus.programs(cfg, decls)
    lst = openplcmodbus.global_list(decls)
    with open(os.path.join(out, "project.st"), "w", encoding="utf-8") as f:
        f.write(struct(lst))
        for st in (in_st, MAIN, out_st):
            f.write(with_external(st))
        f.write("CONFIGURATION config\n  VAR_GLOBAL\n    canworks : canworks_TYPE;\n  END_VAR\n"
                "  RESOURCE res ON PLC\n    TASK main_task(INTERVAL := T#20ms,PRIORITY := 1);\n")
        for i in openplcmodbus.instances({"tasks": [{"name": "main_task"}],
                                          "instances": [{"name": "main_instance", "task": "main_task",
                                                         "program": "main"}]}):
            f.write("    PROGRAM %s WITH %s : %s;\n" % (i["name"], i["task"], i["program"]))
        f.write("  END_RESOURCE\nEND_CONFIGURATION\n")
    with open(os.path.join(out, "programs.st"), "w", encoding="utf-8") as f:
        f.write(struct(lst))
        f.write(as_block(in_st, "canworks_in", "VAR_OUTPUT"))
        f.write(as_block(out_st, "canworks_out", "VAR_INPUT"))
        # "inputs_on_loss": "zero", for the loss tests.
        zero_in, _ = openplcmodbus.programs(cfg, decls, on_loss="zero")
        f.write(as_block(zero_in, "canworks_in", "VAR_OUTPUT").replace("canworks_in_fb", "canworks_in_zero_fb"))

    # Another PLC: its list's VAR_GLOBAL block becomes the STRUCT.
    text = openplcmodbus.other_plc_st(cfg, decls)
    head, rest = text.split("VAR_GLOBAL\n", 1)
    members, rest = rest.split("END_VAR\n", 1)
    programs = rest[rest.index("PROGRAM "):].split("\n\nPROGRAM ")
    with open(os.path.join(out, "other.st"), "w", encoding="utf-8") as f:
        f.write("TYPE canworks_TYPE :\nSTRUCT\n%sEND_STRUCT;\nEND_TYPE\n" % members)
        for st in (programs[0], MAIN, "PROGRAM " + programs[1]):
            f.write(with_external(st.strip()))
        f.write("CONFIGURATION config\n  VAR_GLOBAL\n    canworks : canworks_TYPE;\n  END_VAR\n"
                "  RESOURCE res ON PLC\n    TASK main_task(INTERVAL := T#20ms,PRIORITY := 1);\n"
                "    PROGRAM in_instance WITH main_task : canworks_in;\n"
                "    PROGRAM main_instance WITH main_task : main;\n"
                "    PROGRAM out_instance WITH main_task : canworks_out;\n"
                "  END_RESOURCE\nEND_CONFIGURATION\n")

    # The OpenPLC example's program against its own list.
    ex = os.path.join(HERE, "..", "..", "examples", "openplc-modbus")
    ex_path = os.path.join(ex, "canworks.json")
    with open(ex_path, encoding="utf-8") as f:
        ex_cfg = json.load(f)
    ex_decls = editorproject.declarations(ex_cfg, ex_path)
    ex_in, ex_out = openplcmodbus.programs(ex_cfg, ex_decls)
    with open(os.path.join(ex, "main.st"), encoding="utf-8") as f:
        ex_main = f.read()
    ex_main = ex_main[ex_main.index("PROGRAM main"):]
    with open(os.path.join(out, "example.st"), "w", encoding="utf-8") as f:
        f.write(struct(openplcmodbus.global_list(ex_decls)))
        for st in (ex_in, ex_main, ex_out):
            f.write(with_external(st.strip()))
        f.write("CONFIGURATION config\n  VAR_GLOBAL\n    canworks : canworks_TYPE;\n  END_VAR\n"
                "  RESOURCE res ON PLC\n    TASK main_task(INTERVAL := T#20ms,PRIORITY := 1);\n"
                "    PROGRAM in_instance WITH main_task : canworks_in;\n"
                "    PROGRAM main_instance WITH main_task : main;\n"
                "    PROGRAM out_instance WITH main_task : canworks_out;\n"
                "  END_RESOURCE\nEND_CONFIGURATION\n")

    # Bit channels on the bridge (canopen-pdo-io): BOOLs at their entry's bits.
    bits_cfg = json.loads(json.dumps(ex_cfg))
    del bits_cfg["bridge"]["mailboxes"]
    rtd, dio = bits_cfg["networks"][0]["nodes"][:2]
    rtd["tx_pdos"][0]["entries"][0]["bits"] = [{"bit": 9, "name": "hi"}]
    dio["tx_pdos"][0]["entries"][0]["bits"] = [{"bit": 0, "name": "first_bit"}, {"bit": 3}]
    dio["rx_pdos"][0]["entries"][0]["bits"] = [{"bit": 2, "name": "lamp"}]
    bits_decls = editorproject.declarations(bits_cfg, ex_path)
    bits_in, bits_out = openplcmodbus.programs(bits_cfg, bits_decls)
    with open(os.path.join(out, "bits.st"), "w", encoding="utf-8") as f:
        f.write(struct(openplcmodbus.global_list(bits_decls)))
        f.write(as_block(bits_in, "canworks_in", "VAR_OUTPUT"))
        f.write(as_block(bits_out, "canworks_out", "VAR_INPUT"))


if __name__ == "__main__":
    main()
