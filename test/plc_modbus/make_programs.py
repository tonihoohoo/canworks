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
                 conversion tests

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
  END_VAR
  rd(EXECUTE := canworks.ok, NODE := 5, INDEX := 16#1018, SUBINDEX := 1, LINK := canworks.link);
  live(NETWORK := 0, NODE := 5, LINK := canworks.link);
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


if __name__ == "__main__":
    main()
