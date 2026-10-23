#!/usr/bin/env python3
"""The example's editor project as one ST file, the way the editor compiles it.

    project_st.py <project dir> <out.st>

The `canworks` global variable list of project.json as a structure, the
programs canworks_in, main and canworks_out with the VAR_EXTERNAL the editor
adds for the list, and the CONFIGURATION from project.json's task and
instances (test/plc_modbus/make_programs.py does the same for its config).
"""

import json
import sys

project, out = sys.argv[1], sys.argv[2]
with open(project + "/project.json", encoding="utf-8") as f:
    data = json.load(f)["data"]
lst = next(l for l in data["globalVariableLists"] if l["name"] == "canworks")
resource = data["configuration"]["resource"]
task = resource["tasks"][0]

parts = ["TYPE canworks_TYPE :", "STRUCT"]
parts += ["  %s : %s;" % (v["name"], v["type"]["value"]) for v in lst["variables"]]
parts += ["END_STRUCT;", "END_TYPE", ""]
for i in resource["instances"]:
    with open("%s/pous/programs/%s.st" % (project, i["program"]), encoding="utf-8") as f:
        head, rest = f.read().split("\n", 1)
    parts.append("%s\n  VAR_EXTERNAL\n    canworks : canworks_TYPE;\n  END_VAR\n%s" % (head, rest))
parts.append("CONFIGURATION config0\n  VAR_GLOBAL\n    canworks : canworks_TYPE;\n  END_VAR\n"
             "  RESOURCE res0 ON PLC\n    TASK %s(INTERVAL := %s, PRIORITY := 0);" % (task["name"], task["interval"]))
parts += ["    PROGRAM %s WITH %s : %s;" % (i["name"], i["task"], i["program"]) for i in resource["instances"]]
parts.append("  END_RESOURCE\nEND_CONFIGURATION\n")
with open(out, "w", encoding="utf-8") as f:
    f.write("\n".join(parts))
