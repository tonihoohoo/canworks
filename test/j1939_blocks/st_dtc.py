#!/usr/bin/env python3
"""Checks the library's J1939_DTC_SPLIT and J1939_DTC_MAKE (spec
j1939-plc-diagnostics, "Trouble code ST functions") against the shared DM
byte fixtures.

    st_dtc.py <strucpp runtime include dir> <work dir>

Takes the C++ that strucpp generated for them from the committed
tools/deploy/canworks/library/canworks.stlib, compiles it with a harness and
runs it on every code of test/fixtures/j1939-dm/cases.json: the split gives
the fixture's SPN, FMI, OC and CM, and the make (CM clear) its value."""

import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]

HARNESS = r"""
#include <cstdio>
struct Code { unsigned value, spn, fmi, oc, cm; };
static const Code codes[] = {
%(codes)s
};
int main() {
  int bad = 0;
  for (const Code& c : codes) {
    J1939_DTC_SPLIT s;
    s.DTC = c.value;
    s();
    if ((unsigned)s.SPN != c.spn || (unsigned)s.FMI != c.fmi || (unsigned)s.OC != c.oc || (bool)s.CM != (bool)c.cm) {
      ++bad;
      std::printf("split %%u: SPN %%u FMI %%u OC %%u CM %%d\n", c.value, (unsigned)s.SPN, (unsigned)s.FMI,
                  (unsigned)s.OC, (int)(bool)s.CM);
    }
    unsigned made = J1939_DTC_MAKE(c.spn, c.fmi, c.oc);
    unsigned want = c.value & 0x7FFFFFFFu;
    if (made != want) {
      ++bad;
      std::printf("make SPN %%u FMI %%u OC %%u: %%u, want %%u\n", c.spn, c.fmi, c.oc, made, want);
    }
  }
  // Each part is cut to its width.
  if (J1939_DTC_MAKE(0xFFFFFFFFu, 0xFF, 0xFF) != 0x7FFFFFFFu) {
    ++bad;
    std::printf("make does not cut the parts to their widths\n");
  }
  std::printf("%%d failure(s)\n", bad);
  return bad != 0;
}
"""


def main():
    include, work = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
    work.mkdir(parents=True, exist_ok=True)
    lib = json.loads((ROOT / "tools/deploy/canworks/library/canworks.stlib").read_text())
    chunks = {c["name"]: c for c in lib["chunks"]}
    src = ['#include "iec_std_lib.hpp"', "using namespace strucpp;", chunks["J1939_DTC_SPLIT"]["header"],
           chunks["J1939_DTC_SPLIT"]["cpp"], chunks["J1939_DTC_MAKE"]["cpp"]]
    cases = json.loads((ROOT / "test/fixtures/j1939-dm/cases.json").read_text())["cases"]
    rows = []
    for c in cases:
        if c["kind"] != "dm":
            continue
        for d in c["dtcs"]:
            rows.append("{%du,%du,%du,%du,%d}" % (d["value"], d["spn"], d["fmi"], d["oc"], 1 if d["cm"] else 0))
    src.append(HARNESS % {"codes": ",\n".join(rows)})
    (work / "st_dtc.cpp").write_text("\n".join(src))
    exe = work / "st_dtc"
    subprocess.run(["c++", "-std=c++17", "-O1", "-I", str(include), str(work / "st_dtc.cpp"), "-o", str(exe)],
                   check=True)
    return subprocess.run([str(exe)]).returncode


if __name__ == "__main__":
    sys.exit(main())
