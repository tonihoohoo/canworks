## Why

The trace view lists every frame with a one-line decode, which is enough for someone who already knows CANopen. It does not show why a frame means what it means: how the identifier splits into a function code and a node ID, which bits of the data carry which value, how little-endian numbers are put together, what an SDO command byte encodes, or what the controller actually sends on the wire. People commissioning their first CANopen network, and anyone checking a PDO mapping bit by bit, have to work this out by hand from the CiA 301 tables.

The deploy package already knows every PDO bit layout, every object name and type and every PLC address of the configured networks, and the trace already records the frames. Putting the two together gives a bit-level explanation of any frame that is easy to read and teaches how CAN and CANopen messaging work, without new hardware and without touching the plugin.

## What Changes

- **New frame explanation model** (`canopen-frame-explain`), built on the PC from a frame and the configuration, in four layers:
  1. **Meaning**: one plain sentence, the raw frame, and a short text on what this message type is for.
  2. **Identifier**: the 11 (or 29) identifier bits, split into function code and node ID for CANopen identifiers, with the arithmetic and the message type.
  3. **Data bits**: every data bit assigned to a named field with its value, how the value is put together (little-endian working), an explanation, and for PDOs the object, data type, PLC address and PLC variable name. Fields exist for every CANopen protocol: NMT, SYNC, TIME, EMCY (code, each error register bit, manufacturer bytes), heartbeat and boot-up (state, toggle bit), SDO (command specifier, n, e, s, toggle, index, subindex, data, size, abort code with text, block transfer bits), LSS, PDOs, and SocketCAN error frames (each error class and detail bit).
  4. **On the wire**: the frame as a correct controller sends it, rebuilt from the identifier and data: start of frame, arbitration and control bits, data, CRC-15, delimiters, acknowledge slot, end of frame and intermission, with stuff bits inserted and marked, the bus level of every bit, and the frame's bit count, stuff bit count, CRC and time on the bus at the network's bit rate. Labelled as a reconstruction, since SocketCAN delivers finished frames.
- **Frame inspector in the Trace view**: selecting a frame opens a panel with the four layers. Every bit can be pointed at or focused for its explanation, and the same bit is highlighted in every layer it appears in.
- **Sequence views in the Trace view**: an SDO conversation as a sequence diagram (segmented and block transfers folded into one exchange, with step latencies), one SYNC cycle as a timeline (SYNC, synchronous TPDOs, RPDOs, with measured times and the transmission types that explain them), and a node's boot story (boot-up, the master's SDO configuration writes, NMT start, first heartbeat, first PDOs), each step opening the frame inspector.
- **Frame lab** (new configurator view, works without a runtime): type or paste a frame (also candump `123#11223344` syntax), pick example frames generated from the open configuration (each node's PDOs, heartbeat, boot-up, an SDO read of 1018h:01, an EMCY), or build a frame (SDO read or write of an object picked from a node's dictionary, a PDO with signal values, NMT, heartbeat), and see it in the frame inspector. An arbitration demo sends two chosen frames at once bit by bit and shows where the loser stops. Nothing is sent to the bus.
- **Command-line**: `openplc-canopen-diag explain FRAME... [--config FILE] [--network NAME] [--bitrate N] [--format text|json]` prints the four layers as text with a bit grid, or the model as JSON. Frames also from a trace file (`--trace FILE --index N`).
- **Network docs**: the PDO byte grid in the HTML network document explains each bit on hover and focus (field, object, PLC address, bit number), using the same field model.

## Capabilities

### New Capabilities
- `canopen-frame-explain`: the explanation model (four layers, field coverage per protocol, wire reconstruction, texts), the Frame lab content and the `explain` command.

### Modified Capabilities
- `canopen-bus-trace`: frame inspector and sequence views on recorded and opened traces.
- `canopen-configurator`: inspector panel in the Trace view, Frame lab view.
- `canopen-network-docs`: per-bit explanations in the PDO byte grid.

## Impact

- `tools/deploy/openplc_canopen_deploy/bustrace/`: new `explain.py` (field model per protocol, wire reconstruction, texts), `sequences.py` (SDO conversations, SYNC cycles, boot stories from decoded frames); `decode.py` keeps its text decode and shares the field model.
- Configurator: endpoints `POST /api/trace/explain`, `POST /api/trace/sequence`, `POST /api/explain`, `POST /api/explain/build`; new `static/explain.js` (inspector, sequence diagrams, Frame lab; HTML grid and inline SVG, no new library), changes in `trace.js`, `index.html`, `style.css`.
- `diag.py`: `explain` subcommand. `docwriter.py`: bit hover data in the PDO grid.
- No plugin, runtime, schema or config-format change; no new runtime dependency.
- Tests: golden explanations per frame kind, CRC-15 check value and wire golden bits, sequence detection on built traces, CLI tests, browser tests for the inspector, Frame lab and docs hover. Deploy tool minor version bump.
- Docs: new `docs/frame-inspector.md` (also a short CAN/CANopen primer built around the inspector), `docs/trace.md`, `docs/configurator.md`, `docs/diagnostics.md`, `docs/network-docs.md`, README.
