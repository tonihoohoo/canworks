#!/usr/bin/env python3
"""Writes the sources of the openplc_canopen editor library (spec canopen-plc-sdo).

    python3 library/generate.py            # write library/openplc_canopen/*.cpp
    python3 library/generate.py --check    # fail if they are out of date

Each block is a C++ function block as OpenPLC Editor 4.3 stores one: an ST
header (FUNCTION_BLOCK, the variable sections) followed by the C++ body with
setup() and loop(). The eight blocks share one pin layout and the code in
src/common.inc, which is copied into every body (behind an include guard)
because the editor grafts each block into one c_blocks_code.cpp.

library/build.sh turns the folder into openplc_canopen.stlib with strucpp.
"""

import argparse
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
OUT = HERE / "openplc_canopen"
COMMON = (HERE / "src" / "common.inc").read_text()

INPUTS = """\
  EXECUTE : BOOL;
  NETWORK : USINT;
  NODE : USINT;
  INDEX : UINT;
  SUBINDEX : USINT;
  TIMEOUT : TIME;
"""
OUTPUTS = """\
  BUSY : BOOL;
  DONE : BOOL;
  ERROR : BOOL;
  ERROR_ID : UINT;
  ABORT_CODE : UDINT;
"""
LOCALS = """\
  co_handle : UDINT;
  co_prev : BOOL;
  co_phase : USINT;
"""

# name: (kind, write, extra inputs, extra outputs, in-outs, reply buffer size,
#        code that clears the data outputs, code that fills the request,
#        code that reads a reply into the outputs and may set err)
BLOCKS = {
    "CO_SDO_READ": dict(
        kind="kind_int", write=False, inputs="", outputs="  DATA : LWORD;\n  SIZE : UINT;\n", inouts="",
        cap=9, clear="DATA = 0ULL;\n    SIZE = 0;",
        fill="",
        reply="""if (res.size > 8) {
          err = co_sdo::err_too_big;
          SIZE = static_cast<unsigned short>(res.size > 65535u ? 65535u : res.size);
        } else {
          DATA = co_sdo::get_le(reply, res.size);
          SIZE = static_cast<unsigned short>(res.size);
        }"""),
    "CO_SDO_WRITE": dict(
        kind="kind_int", write=True, inputs="  DATA : LWORD;\n  SIZE : USINT;\n", outputs="", inouts="",
        cap=1, clear="",
        fill="""unsigned char payload[8];
    co_sdo::put_le(payload, static_cast<unsigned long long>(DATA), 8);
    req.data = payload;
    req.length = 8;
    if (SIZE > 8) err = co_sdo::err_input;
    req.size = static_cast<unsigned char>(SIZE);""",
        reply=""),
    "CO_SDO_READ_REAL": dict(
        kind="kind_real", write=False, inputs="", outputs="  VALUE : LREAL;\n", inouts="",
        cap=9, clear="",
        fill="",
        reply="""if (res.size == 4) {
          unsigned int bits = static_cast<unsigned int>(co_sdo::get_le(reply, 4));
          float f;
          memcpy(&f, &bits, sizeof f);
          VALUE = static_cast<double>(f);
        } else if (res.size == 8) {
          unsigned long long bits = co_sdo::get_le(reply, 8);
          double d;
          memcpy(&d, &bits, sizeof d);
          VALUE = d;
        } else {
          err = co_sdo::err_too_big;
        }"""),
    "CO_SDO_WRITE_REAL": dict(
        kind="kind_real", write=True, inputs="  VALUE : LREAL;\n  SIZE : USINT;\n", outputs="", inouts="",
        cap=1, clear="",
        fill="""unsigned char payload[8];
    double d = VALUE;
    unsigned long long bits;
    memcpy(&bits, &d, sizeof bits);
    co_sdo::put_le(payload, bits, 8);
    req.data = payload;
    req.length = 8;
    if (SIZE != 0 && SIZE != 4 && SIZE != 8) err = co_sdo::err_input;
    req.size = static_cast<unsigned char>(SIZE);""",
        reply=""),
    "CO_SDO_READ_STRING": dict(
        kind="kind_string", write=False, inputs="", outputs="  VALUE : STRING;\n", inouts="",
        cap=1024, clear="",
        fill="",
        reply="""unsigned int kept = res.size < co_sdo::max_data ? res.size : co_sdo::max_data;
        unsigned int len = 0;
        while (len < kept && reply[len] != 0) ++len;
        if (len > 254 || (len == kept && res.size > kept)) {
          err = co_sdo::err_too_big;
        } else {
          char text[255];
          memcpy(text, reply, len);
          text[len] = 0;
          VALUE = text;
        }"""),
    "CO_SDO_WRITE_STRING": dict(
        kind="kind_string", write=True, inputs="  VALUE : STRING;\n", outputs="", inouts="",
        cap=1, clear="",
        fill="""unsigned char payload[254];
    unsigned int len = static_cast<unsigned int>(VALUE.length());
    if (len > 254) len = 254;
    memcpy(payload, VALUE.c_str(), len);
    req.data = payload;
    req.length = len;""",
        reply=""),
    "CO_SDO_READ_BYTES": dict(
        kind="kind_bytes", write=False, inputs="", outputs="  SIZE : UINT;\n",
        inouts="  BUFFER : ARRAY[0..1023] OF BYTE;\n",
        cap=1024, clear="SIZE = 0;",
        fill="",
        reply="""SIZE = static_cast<unsigned short>(res.size > 65535u ? 65535u : res.size);
        if (res.size > co_sdo::max_data) {
          err = co_sdo::err_too_big;
        } else {
          for (unsigned int i = 0; i < res.size; ++i) BUFFER[i] = reply[i];
        }"""),
    "CO_SDO_WRITE_BYTES": dict(
        kind="kind_bytes", write=True, inputs="  SIZE : UINT;\n", outputs="",
        inouts="  BUFFER : ARRAY[0..1023] OF BYTE;\n",
        cap=1, clear="",
        fill="""unsigned char payload[1024];
    unsigned int len = SIZE;
    if (len > co_sdo::max_data) {
      err = co_sdo::err_input;
      len = 0;
    }
    for (unsigned int i = 0; i < len; ++i) payload[i] = static_cast<unsigned char>(BUFFER[i]);
    req.data = payload;
    req.length = len;""",
        reply=""),
}

TEMPLATE = """\
FUNCTION_BLOCK {name}
VAR_INPUT
{inputs}VAR_END_MARK
VAR_OUTPUT
{outputs}VAR_END_MARK
{inout_section}VAR
{locals}VAR_END_MARK
{common}
// {name}: {summary}
// Generated by library/generate.py; edit that file or src/common.inc.

void setup() {{
}}

void loop() {{
  bool prev = co_prev;
  unsigned char phase = co_phase;
  co_sdo::step s = co_sdo::begin(EXECUTE, prev, phase);
  co_prev = prev;
  co_phase = phase;
  if (s.clear) {{
    DONE = false;
    ERROR = false;
  }}
  if (s.start) {{
    DONE = false;
    ERROR = false;
    ERROR_ID = 0;
    ABORT_CODE = 0;
    {clear}
    unsigned short err = 0;
    co_sdo::request req = {{}};
    req.network = NETWORK;
    req.node = NODE;
    req.index = INDEX;
    req.subindex = SUBINDEX;
    req.write = {write};
    req.kind = co_sdo::{kind};
    req.timeout_ms = co_sdo::timeout_ms(TIMEOUT);
    {fill}
    unsigned int handle = err ? 0 : co_sdo::start(req, err);
    if (handle) {{
      co_handle = handle;
      BUSY = true;
      co_phase = co_sdo::phase_busy;
    }} else {{
      BUSY = false;
      ERROR = true;
      ERROR_ID = err;
      co_phase = co_sdo::phase_ended;
    }}
  }}
  if (co_phase == co_sdo::phase_busy) {{
    co_sdo::result res = {{}};
    unsigned char reply[{cap}];
    int st = co_sdo::poll(co_handle, res, reply, sizeof reply);
    if (st != 0) {{
      BUSY = false;
      co_handle = 0;
      co_phase = co_sdo::phase_ended;
      unsigned short err = st == 2 ? res.error_id : 0;
      if (!err) {{
        {reply}
      }}
      if (err) {{
        ERROR = true;
        ERROR_ID = err;
        ABORT_CODE = (err == 1 || err == 2) ? res.abort_code : 0u;
      }} else {{
        DONE = true;
      }}
    }}
  }}
}}
END_FUNCTION_BLOCK
"""

SUMMARIES = {
    "CO_SDO_READ": "reads an integer or bit string object (up to 8 bytes) into DATA",
    "CO_SDO_WRITE": "writes the low SIZE bytes of DATA (SIZE 0: size from the EDS)",
    "CO_SDO_READ_REAL": "reads a REAL32 or REAL64 object into VALUE",
    "CO_SDO_WRITE_REAL": "writes VALUE as REAL32 (SIZE 4) or REAL64 (SIZE 8; 0: from the EDS)",
    "CO_SDO_READ_STRING": "reads a VISIBLE_STRING object into VALUE",
    "CO_SDO_WRITE_STRING": "writes VALUE to a VISIBLE_STRING object",
    "CO_SDO_READ_BYTES": "reads any object (up to 1024 bytes) into BUFFER",
    "CO_SDO_WRITE_BYTES": "writes SIZE bytes of BUFFER",
}


def render(name):
    b = BLOCKS[name]
    inout = f"VAR_IN_OUT\n{b['inouts']}VAR_END_MARK\n" if b["inouts"] else ""
    text = TEMPLATE.format(
        name=name, summary=SUMMARIES[name], inputs=INPUTS + b["inputs"], outputs=OUTPUTS + b["outputs"],
        inout_section=inout, locals=LOCALS, common=COMMON.rstrip("\n"), clear=b["clear"],
        write="1" if b["write"] else "0", kind=b["kind"],
        fill=b["fill"], cap=b["cap"], reply=b["reply"])
    # The keyword is spelled out only here, so no C++ text can carry it.
    text = text.replace("VAR_END_MARK", "END" + "_VAR")
    # Empty code slots leave blank indented lines; drop them.
    return "\n".join(line for line in text.split("\n") if line.strip() or line == "") .replace("\n\n\n", "\n\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="fail if the sources are out of date")
    args = ap.parse_args()
    stale = []
    OUT.mkdir(exist_ok=True)
    wanted = {f"{name}.cpp": render(name) for name in BLOCKS}
    for fname, text in wanted.items():
        path = OUT / fname
        if path.exists() and path.read_text() == text:
            continue
        stale.append(fname)
        if not args.check:
            path.write_text(text)
    for path in OUT.glob("*.cpp"):
        if path.name not in wanted:
            stale.append(path.name)
            if not args.check:
                path.unlink()
    if args.check and stale:
        print("library sources out of date (run python3 library/generate.py): " + ", ".join(stale), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
