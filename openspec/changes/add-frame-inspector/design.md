# Design

## Context

- `bustrace/decode.py` decodes each frame into a kind, node, name and one line of text, plus PDO signal values. It already holds each PDO's signal layout (start bit, length, sign, float kind, EDS name, PLC variable name), each node's object names and types, and uses the EMCY class and SDO abort texts from `diag.py`. For NMT, SDO, EMCY, heartbeat and LSS it builds text only, not bit fields.
- The Trace view (`static/trace.js`) lists frames, a per-identifier table, graphs and triggers. Selecting a row only offers "Show in graph".
- The HTML network document draws a static byte grid per PDO from `docexport`.
- A throwaway single-page prototype (outside the repo) showed the four layers on twelve example frames and confirmed the wire reconstruction: CRC-15 with polynomial 0x4599 gives the catalogue check value 0x059E for "123456789", and a 4-byte TPDO comes out at 76 bits plus 3 stuff bits.

## Goals / Non-Goals

**Goals:**
- Any frame, recorded or typed, explained down to every bit in words a newcomer understands.
- One explanation model in Python, used by the configurator, the CLI and the network document, so all three say the same thing and it is unit-tested.
- Works offline and without a runtime (Frame lab, opened trace files, CLI).

**Non-Goals:**
- Measuring the physical layer. SocketCAN adapters deliver finished frames; real bit timing, real stuff bits, waveforms and the position of an error flag are not available. A logic-analyzer import (for example sigrok) is a possible follow-up.
- CAN FD. The plugin runs classic CAN; frames longer than 8 bytes are explained as not supported.
- Sending frames to the bus from the Frame lab. Manual SDO and NMT stay in the online view.
- Translations. Texts are English like the rest of the tools.

## Decisions

### D1. One field model in `explain.py`
`explain(frame, decoder, bitrate=None) -> dict` returns `{meaning, story, raw, id: {bits, function_code, node, kind, text}, fields: [...], wire: {...}, notes}`. A field is `{name, start, length, value, how, text, color_group, bits?: [names], object?, iec?, variable?}` with `start` and `length` in CANopen bit numbering (bit 0 = least significant bit of byte 0). Fields cover every data bit; unused bits are a field of their own ("unused", "reserved" or "padding") so the grid never has unexplained bits. `decode.py` keeps its text output (the trace list and filters depend on it) but builds PDO and SDO values through the same helpers so the numbers cannot differ. Alternative: write the explanation in JavaScript as in the prototype; rejected because the CLI and the network document need it too, and Python is where the tests and the EDS knowledge live.

### D2. Texts in one table
All explanation texts (function codes, NMT commands and states, SDO command specifiers per direction and their bits, abort codes, EMCY classes and error register bits, LSS commands, SocketCAN error classes and details, wire fields) live in `explain_texts.py` as plain data, reusing `diag.py` tables where they exist. Short, plain sentences; CiA terms named once with a plain explanation.

### D3. SDO state across frames
An SDO segment frame cannot be explained alone (toggle bit, which transfer it belongs to). The explainer takes an optional context from the decoder's per-node SDO state (`Decoder.clone()` already exists for the trace), so a segment says "segment 3 of the upload of 1008h:00, toggle 0, 7 bytes". In the Frame lab and the CLI without a trace, a segment is explained on its own and says the transfer is unknown.

### D4. Wire reconstruction
Base and extended frames, data and remote frames: SOF, identifier (and SRR, IDE, extended identifier), RTR, IDE/r1, r0, DLC, data, CRC-15 over the unstuffed bits from SOF to the end of data, stuff bits after five equal bits from SOF to the end of the CRC sequence, CRC delimiter, ACK slot (shown dominant, as a received frame has it), ACK delimiter, 7 EOF bits and 3 intermission bits. Bit time from the network's bit rate (config, or trace metadata, or `--bitrate`, default 500 kbit/s marked as assumed). Each wire bit names its source (`id.10`, `data.0.7`, `stuff`, `crc.14`) so the UI can link it to the other layers. Error frames get no wire layer; they are explained from their SocketCAN class and detail bytes.

### D5. Sequences from the decoder
`sequences.py` works on the decoded trace in the recorder (server side, so 2 million frames are not sent to the browser):
- SDO conversation: from an initiate request to the final response or abort per node and SDO channel; segmented and block transfers collected; latency per step.
- SYNC cycle: frames between two SYNCs with their offsets from the SYNC, grouped by synchronous TPDO, other PDOs, SDO and the rest; each PDO's configured transmission type and the SYNC window shown next to it.
- Boot story: per node from a boot-up (or the master's reset command) to the first PDO after NMT start, with the master's SDO writes matched to the expected boot writes from `dcfexport.plugin_downloads` (same list the network document shows), so missing, extra or failed writes stand out.
Endpoint `POST /api/trace/sequence {kind, seq}` returns the sequence around a selected frame; the list of SDO conversations and boot stories is a filterable table.

### D6. Frame lab and builder
`POST /api/explain {id, ext, rtr, data, network}` explains a typed frame against the open config (saved or not, as the network docs export does). `POST /api/explain/build` builds frames: SDO expedited or segmented read/write of an object with a value typed in the object's data type, PDO with signal values (PLC variable names in project mode), NMT command, heartbeat state, EMCY code. Examples are generated from the config, not stored. The arbitration demo runs in the browser from two explained frames' wire bits: both senders' bits side by side, the bus level as wired-AND, and the bit where one sender reads a dominant level while sending recessive and stops.

### D7. Rendering without a library
`static/explain.js` renders the layers as an HTML bit grid and inline SVG (wire strip and level line, sequence diagrams), styled with the configurator's existing theme variables, light and dark. Bits are buttons, so keyboard focus explains them as well as pointing; a side box shows the explanation. The same renderer function draws the PDO grid hover in the network document, inlined by `docwriter.py`, so the document stays one offline file.

### D8. CLI output
`openplc-canopen-diag explain` takes frames in candump syntax (`185#2500EA00`, `705#05`, `123#R`, `18FF0017#...` for extended), or `--trace FILE --index N`. Text output: meaning, identifier split, a byte-by-bit grid with field letters and a legend, the field list with values and working, and the wire summary (bits, stuff bits, CRC, time) plus the wire bits with stuff bits marked. `--format json` prints the model. Without `--config` it explains with CANopen defaults (no PDO mapping, so PDOs show raw bytes).

## Risks / Trade-offs

- Explaining every frame on demand is cheap; the panel asks the server for one frame at a time, so a 2-million-frame trace costs nothing extra.
- Wire bits are reconstructed, not measured; the view says so every time, so nobody mistakes it for a scope.
- Texts can drift from CiA wording; they are written for understanding, with the CiA name next to each field, and covered by golden tests.

## Migration

None. New views and a new command only.
