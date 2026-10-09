#!/usr/bin/env python3
"""Builds the editor's C/C++ block glue for the library blocks, for the tests.

    bridge.py <out_dir> <block.cpp>...

Writes c_blocks.h and c_blocks_code.cpp the way OpenPLC Editor 4.3.2 does for
a project using the blocks (src/backend/shared/utils/cpp/generateCBlocksHeader
and generateCBlocksCode): one `<NAME>_VARS` struct of pointers to strucpp
variables per block (a one-dimensional array as a pointer to its first
element), `#define <pin> (*(vars-><PIN>))` (`(vars-><PIN>)` for an array)
before the block's body, setup()/loop() renamed to `<name>_setup(vars)` /
`<name>_loop(vars)`, and `#undef` after it. For the tests it also writes
`<NAME>_INST`: storage for every variable, wired into a `<NAME>_VARS`, and
`<name>_call(inst)`, which runs setup() on the first call and loop() on
every call, as the ST glue does each scan.
"""

import pathlib
import re
import sys

TYPES = {
    "BOOL": "IEC_BOOL", "USINT": "IEC_USINT", "UINT": "IEC_UINT", "UDINT": "IEC_UDINT", "TIME": "IEC_TIME",
    "LWORD": "IEC_LWORD", "LREAL": "IEC_LREAL", "STRING": "IEC_STRING", "BYTE": "IEC_BYTE", "ULINT": "IEC_ULINT",
}
ARRAY = re.compile(r"ARRAY\s*\[\s*(\d+)\s*\.\.\s*(\d+)\s*\]\s+OF\s+(\w+)", re.I)


def parse(text):
    m = re.match(r"\s*FUNCTION_BLOCK\s+(\w+)", text)
    name = m.group(1)
    last = [x.end() for x in re.finditer(r"\bEND_VAR\b", text)][-1]
    header, body = text[:last], text[last:]
    body = re.sub(r"\s*\bEND_FUNCTION_BLOCK\b\s*$", "", body)
    pins = []
    for decl in re.finditer(r"^\s*(\w+)\s*:\s*([^;]+);", header, re.M):
        pname, ptype = decl.group(1), decl.group(2).strip()
        a = ARRAY.match(ptype)
        if a:
            pins.append((pname, TYPES[a.group(3).upper()], int(a.group(2)) - int(a.group(1)) + 1, int(a.group(1))))
        else:
            pins.append((pname, TYPES[ptype.upper()], 0, 0))
    return name, pins, body


def main():
    out = pathlib.Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    blocks = [parse(pathlib.Path(p).read_text()) for p in sys.argv[2:]]
    h = ["#ifndef C_BLOCKS_H", "#define C_BLOCKS_H", '#include "iec_std_lib.hpp"', ""]
    for name, pins, _ in blocks:
        h.append("typedef struct {")
        h += [f"  strucpp::{t} *{p.upper()};" for p, t, _, _ in pins]
        h.append(f"}} {name.upper()}_VARS;")
        h.append(f'void {name.lower()}_setup({name.upper()}_VARS *vars);')
        h.append(f'void {name.lower()}_loop({name.upper()}_VARS *vars);')
        # Test-only instance storage.
        h.append("struct %s_INST {" % name.upper())
        for p, t, n, _ in pins:
            h.append(f"  strucpp::{t} {p.upper()}" + (f"[{n}]" if n else "") + ";")
        h.append(f"  {name.upper()}_VARS vars;")
        h.append("  bool initialized = false;")
        h.append(f"  {name.upper()}_INST() {{")
        for p, t, n, lo in pins:
            h.append(f"    vars.{p.upper()} = " + (f"{p.upper()} - {lo};" if n else f"&{p.upper()};"))
        h.append("  }")
        h.append("};")
        h.append(f"inline void {name.lower()}_call({name.upper()}_INST* inst) {{")
        h.append(f"  if (!inst->initialized) {{ {name.lower()}_setup(&inst->vars); inst->initialized = true; }}")
        h.append(f"  {name.lower()}_loop(&inst->vars);")
        h.append("}")
        h.append("")
    h.append("#endif")
    (out / "c_blocks.h").write_text("\n".join(h) + "\n")

    c = ["#include <cstdint>", "#include <cstring>", '#include "c_blocks.h"', ""]
    for name, pins, body in blocks:
        for p, _, n, _ in pins:
            c.append(f"#define {p} (vars->{p.upper()})" if n else f"#define {p} (*(vars->{p.upper()}))")
        body = re.sub(r"void\s+setup\s*\(\s*\)", f'void {name.lower()}_setup({name.upper()}_VARS *vars)',
                      body)
        body = re.sub(r"void\s+loop\s*\(\s*\)", f'void {name.lower()}_loop({name.upper()}_VARS *vars)',
                      body)
        c.append(body)
        c += [f"#undef {p}" for p, _, _, _ in pins]
        c.append("")
    (out / "c_blocks_code.cpp").write_text("\n".join(c) + "\n")


if __name__ == "__main__":
    main()
