#!/usr/bin/env python3
"""The example's program as test/local-runtime/build_program.mjs can build it.

    ci_program.py <project dir> <out.st>

Writes pous/programs/main.st without the parts between "SDO blocks begin" and
"SDO blocks end" (the SDO blocks are C/C++ blocks, which only the editor's own
build composes) and with the CONFIGURATION the editor writes from
project.json (the task interval).
"""

import json
import re
import sys

project, out = sys.argv[1], sys.argv[2]
with open(project + "/pous/programs/main.st", encoding="utf-8") as f:
    program = f.read()
program, n = re.subn(r"[ \t]*\(\* SDO blocks begin.*?SDO blocks end \*\)\n", "", program, flags=re.S)
if n != 2 or re.search(r"\bCO_SDO_", program):
    sys.exit("ci_program.py: expected one SDO blocks section in VAR and one in the body (found %d)" % n)
with open(project + "/project.json", encoding="utf-8") as f:
    task = json.load(f)["data"]["configuration"]["resource"]["tasks"][0]
program += """
CONFIGURATION config0
  RESOURCE res0 ON PLC
    TASK %s(INTERVAL := %s, PRIORITY := 0);
    PROGRAM instance0 WITH %s : main;
  END_RESOURCE
END_CONFIGURATION
""" % (task["name"], task["interval"], task["name"])
with open(out, "w", encoding="utf-8") as f:
    f.write(program)
