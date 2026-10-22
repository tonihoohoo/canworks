#!/usr/bin/env python3
"""Checks the library's J1939_GET_BITS, J1939_SET_BITS, J1939_NAME_MAKE and
J1939_NAME_SPLIT (spec j1939-plc-blocks, "J1939 ST functions").

    st_j1939.py <strucpp runtime include dir> <work dir>

Takes the C++ that strucpp generated for them from the committed
tools/deploy/canworks/library/canworks.stlib, compiles it with a harness and
compares it with the packing the plugin uses: little-endian signals in a
message of any length (plugin/src/j1939/j1939_signal.cpp) and the NAME
layout of J1939Name::value (plugin/src/j1939/j1939_config.cpp), computed
here in Python."""

import json
import pathlib
import random
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
LENGTH = 1785

HARNESS = r"""
#include <cstdio>
struct Get { unsigned start, length, is_signed; long long want; };
static const unsigned char message[%(n)d] = { %(message)s };
static const Get gets[] = {
%(gets)s
};
struct Name { unsigned long long value; unsigned id, mfr, ecu, fi, fn, vs, vsi, ig, aac; };
static const Name names[] = {
%(names)s
};
int main() {
  int bad = 0;
  Array1D<IEC_BYTE, 0, 1784> data;
  for (int i = 0; i < %(n)d; ++i) data[i] = message[i];
  for (const Get& g : gets) {
    long long got = J1939_GET_BITS(data, g.start, g.length, g.is_signed != 0);
    if (got != g.want) {
      ++bad;
      std::printf("get %%u/%%u: %%lld, want %%lld\n", g.start, g.length, got, g.want);
    }
  }
  // Set every signal into a blank message and read it back; a signed one as its raw bits.
  for (const Get& g : gets) {
    Array1D<IEC_BYTE, 0, 1784> out;
    for (int i = 0; i < %(n)d; ++i) out[i] = 0;
    if (!J1939_SET_BITS(out, g.start, g.length, g.want)) {
      ++bad;
      std::printf("set %%u/%%u refused\n", g.start, g.length);
      continue;
    }
    long long back = J1939_GET_BITS(out, g.start, g.length, g.is_signed != 0);
    if (back != g.want) {
      ++bad;
      std::printf("set %%u/%%u: read back %%lld, want %%lld\n", g.start, g.length, back, g.want);
    }
  }
  // Out of range: refused, nothing written.
  Array1D<IEC_BYTE, 0, 1784> edge;
  for (int i = 0; i < %(n)d; ++i) edge[i] = 0;
  if (J1939_SET_BITS(edge, 14279, 2, 3) || J1939_SET_BITS(edge, 0, 0, 1) || J1939_SET_BITS(edge, 0, 65, 1) ||
      (unsigned)edge[1784] != 0) {
    ++bad;
    std::printf("set out of range was not refused\n");
  }
  if (!J1939_SET_BITS(edge, 14279, 1, 1) || (unsigned)edge[1784] != 0x80) {
    ++bad;
    std::printf("set of the last bit failed\n");
  }
  for (const Name& n : names) {
    unsigned long long made = J1939_NAME_MAKE(n.id, n.mfr, n.ecu, n.fi, n.fn, n.vs, n.vsi, n.ig, n.aac != 0);
    if (made != n.value) {
      ++bad;
      std::printf("make NAME: %%016llX, want %%016llX\n", made, n.value);
    }
    J1939_NAME_SPLIT s;
    s.NAME = n.value;
    s();
    if ((unsigned)s.IDENTITY_NUMBER != n.id || (unsigned)s.MANUFACTURER_CODE != n.mfr ||
        (unsigned)s.ECU_INSTANCE != n.ecu || (unsigned)s.FUNCTION_INSTANCE != n.fi ||
        (unsigned)s.ECU_FUNCTION != n.fn || (unsigned)s.VEHICLE_SYSTEM != n.vs ||
        (unsigned)s.VEHICLE_SYSTEM_INSTANCE != n.vsi || (unsigned)s.INDUSTRY_GROUP != n.ig ||
        (bool)s.ARBITRARY_ADDRESS_CAPABLE != (n.aac != 0)) {
      ++bad;
      std::printf("split NAME %%016llX differs\n", n.value);
    }
  }
  std::printf("%%d failure(s)\n", bad);
  return bad != 0;
}
"""


def get_bits(message, start, length, signed):
    v = 0
    for i in range(length):
        pos = start + i
        if pos < 8 * len(message) and message[pos // 8] >> (pos % 8) & 1:
            v |= 1 << i
    if signed and v >> (length - 1) & 1:
        v -= 1 << length
    return v


def name_value(f):
    return ((f["id"] & 0x1FFFFF) | (f["mfr"] & 0x7FF) << 21 | (f["ecu"] & 7) << 32 | (f["fi"] & 0x1F) << 35 |
            (f["fn"] & 0xFF) << 40 | (f["vs"] & 0x7F) << 49 | (f["vsi"] & 0xF) << 56 | (f["ig"] & 7) << 60 |
            (1 if f["aac"] else 0) << 63)


def main():
    include, work = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
    work.mkdir(parents=True, exist_ok=True)
    lib = json.loads((ROOT / "tools/deploy/canworks/library/canworks.stlib").read_text())
    chunks = {c["name"]: c for c in lib["chunks"]}
    src = ['#include "iec_std_lib.hpp"', '#include "iec_array.hpp"', "using namespace strucpp;",
           chunks["J1939_NAME_SPLIT"]["header"],
           chunks["J1939_NAME_SPLIT"]["cpp"], chunks["J1939_GET_BITS"]["cpp"], chunks["J1939_SET_BITS"]["cpp"],
           chunks["J1939_NAME_MAKE"]["cpp"]]
    rnd = random.Random(1939)
    message = bytes(rnd.randrange(256) for _ in range(LENGTH))
    cases = [(0, 8, False), (200, 16, False), (203, 13, True), (8 * 1784, 8, False), (14270, 10, True),
             (7, 64, False), (64, 64, True), (1, 1, False), (100, 33, True)]
    for _ in range(40):
        length = rnd.randrange(1, 65)
        cases.append((rnd.randrange(0, 8 * LENGTH - length + 1), length, rnd.random() < 0.5))
    # LINT holds the 64 raw bits of an unsigned 64-bit signal as a negative number.
    lint = lambda v: v - (1 << 64) if v >= 1 << 63 else v
    gets = ["{%du,%du,%du,(long long)%dLL}" % (s, n, 1 if sg else 0, lint(get_bits(message, s, n, sg)))
            if lint(get_bits(message, s, n, sg)) != -(1 << 63) else "{%du,%du,%du,(-9223372036854775807LL-1)}" % (
                s, n, 1 if sg else 0) for s, n, sg in cases]
    fields = [dict(id=1234, mfr=0, ecu=0, fi=0, fn=0, vs=0, vsi=0, ig=0, aac=1),
              dict(id=0x1FFFFF, mfr=0x7FF, ecu=7, fi=0x1F, fn=0xFF, vs=0x7F, vsi=0xF, ig=7, aac=1),
              dict(id=77, mfr=345, ecu=2, fi=3, fn=130, vs=25, vsi=1, ig=2, aac=0)]
    names = ["{0x%016XULL,%du,%du,%du,%du,%du,%du,%du,%du,%du}" % (
        name_value(f), f["id"], f["mfr"], f["ecu"], f["fi"], f["fn"], f["vs"], f["vsi"], f["ig"], f["aac"])
        for f in fields]
    src.append(HARNESS % {"n": LENGTH, "message": ",".join(str(b) for b in message), "gets": ",\n".join(gets),
                          "names": ",\n".join(names)})
    (work / "st_j1939.cpp").write_text("\n".join(src))
    exe = work / "st_j1939"
    subprocess.run(["c++", "-std=c++17", "-O1", "-I", str(include), str(work / "st_j1939.cpp"), "-o", str(exe)],
                   check=True)
    return subprocess.run([str(exe)]).returncode


if __name__ == "__main__":
    sys.exit(main())
