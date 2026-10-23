#!/usr/bin/env python3
"""Checks the library's ST helper functions (spec can-plc-frames, "ST helper
functions") against the shared signal vectors.

    st_helpers.py <strucpp runtime include dir> <work dir>

Takes the C++ that strucpp generated for the CAN_* functions from the
committed tools/deploy/canworks/library/canworks.stlib, compiles it with a
harness and runs it: CAN_GET_BITS / CAN_SET_BITS on every case of
test/fixtures/can_signals.json, and the byte and J1939 helpers on fixed
cases."""

import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]

HARNESS = r"""
#include <cstdio>
struct Vec { int start, length, big, sign; unsigned char data[8]; long long value; unsigned char packed[8]; };
static const Vec vecs[] = {
%(vecs)s
};
static int bad = 0;
#define EXPECT(c) do { if (!(c)) { ++bad; std::printf("failed: %%s (line %%d)\n", #c, __LINE__); } } while (0)
static void load(Array1D<IEC_BYTE, 0, 7>& a, const unsigned char* d) { for (int i = 0; i < 8; ++i) a[i] = d[i]; }
int main() {
  for (const Vec& v : vecs) {
    Array1D<IEC_BYTE, 0, 7> a;
    load(a, v.data);
    long long got = CAN_GET_BITS(a, v.start, v.length, v.big, v.sign);
    if (got != v.value) { ++bad; std::printf("get start %%d length %%d: %%lld, want %%lld\n", v.start, v.length, got, v.value); }
    Array1D<IEC_BYTE, 0, 7> z;
    for (int i = 0; i < 8; ++i) z[i] = 0;
    EXPECT(CAN_SET_BITS(z, v.start, v.length, v.big, v.value));
    for (int i = 0; i < 8; ++i)
      if ((unsigned char)z[i] != v.packed[i]) { ++bad; std::printf("set start %%d length %%d byte %%d\n", v.start, v.length, i); break; }
  }
  Array1D<IEC_BYTE, 0, 7> a;
  const unsigned char d[8] = {0x12, 0x34, 0x56, 0x78, 0x9A, 0xBC, 0xDE, 0xF0};
  load(a, d);
  EXPECT(!CAN_SET_BITS(a, 60, 8, false, 1));
  EXPECT(CAN_GET_UINT16(a, 0, false) == 0x3412);
  EXPECT(CAN_GET_UINT16(a, 0, true) == 0x1234);
  EXPECT(CAN_GET_UINT32(a, 4, false) == 0xF0DEBC9Au);
  EXPECT(CAN_GET_UINT32(a, 5, false) == 0);
  EXPECT(CAN_SET_UINT16(a, 6, true, 0xBEEF));
  EXPECT((unsigned char)a[6] == 0xBE && (unsigned char)a[7] == 0xEF);
  EXPECT(CAN_SET_UINT32(a, 0, false, 0x11223344u));
  EXPECT((unsigned char)a[0] == 0x44 && (unsigned char)a[3] == 0x11);
  EXPECT(!CAN_SET_UINT32(a, 5, false, 1));
  EXPECT(CAN_J1939_ID(6, 65280, 128, 255) == 0x18FF0080u);
  EXPECT(CAN_J1939_ID(3, 0xEF00, 0x21, 0x05) == 0x0CEF0521u);
  EXPECT(CAN_J1939_PGN(0x0CEF0521u) == 0xEF00u);
  EXPECT(CAN_J1939_PGN(0x18FF0080u) == 65280u);
  EXPECT(CAN_J1939_SOURCE(0x18FF0080u) == 128);
  std::printf("%%d failure(s)\n", bad);
  return bad != 0;
}
"""


def main():
    include, work = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
    work.mkdir(parents=True, exist_ok=True)
    lib = json.loads((ROOT / "tools/deploy/canworks/library/canworks.stlib").read_text())
    funcs = [c["cpp"] for c in lib["chunks"] if c["kind"] == "function" and c["name"].startswith("CAN_")]
    cases = json.loads((ROOT / "test/fixtures/can_signals.json").read_text())["cases"]
    rows = []
    for c in cases:
        data, packed = bytes.fromhex(c["data"]), bytes.fromhex(c["packed"])
        rows.append("{%d,%d,%d,%d,{%s},%dLL,{%s}}" % (
            c["start_bit"], c["length"], c["big_endian"], c["signed"], ",".join(map(str, data)), c["value"],
            ",".join(map(str, packed))))
    src = ['#include "iec_std_lib.hpp"', '#include "iec_array.hpp"', "using namespace strucpp;"] + funcs
    src.append(HARNESS % {"vecs": ",\n".join(rows)})
    (work / "st_helpers.cpp").write_text("\n".join(src))
    exe = work / "st_helpers"
    subprocess.run(["c++", "-std=c++17", "-O1", "-I", str(include), str(work / "st_helpers.cpp"), "-o", str(exe)],
                   check=True)
    return subprocess.run([str(exe)]).returncode


if __name__ == "__main__":
    sys.exit(main())
