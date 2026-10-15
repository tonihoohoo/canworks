## Why

In **Commission a CANopen device** the Trace decodes NMT, heartbeat, SDO and EMCY, but every PDO stays raw bytes: a row reads `TPDO1 node 32 00 00 00 00 00 00 00` and the user has to work out by hand which bytes are the status word and which the position. The decoder already has the EDS of each node on the Nodes tab, yet it uses it only for SDO object names, because the device's PDO layout "is not known without reading it". Nothing in the Trace reads it, guesses it or picks it up from the bus.

The second gap is DBC files. Many devices and machines come with a DBC, and the configurator writes one itself (Export DBC). The bus-trace spec already says a trace opened with a DBC file decodes with its messages, and the decoder can match DBC messages, but no part of the Trace view, the server or the command line lets a user give it a DBC. So a user with the right DBC on disk still sees raw bytes.

## What Changes

- **PDOs decode in Commission a device.** Each node's PDO layout (COB-ID and mapped objects) comes from the best source the configurator has, in this order:
  1. **Set on the bus in this trace**: SDO writes (by another master or by this page) to the node's PDO communication and mapping objects, and SDO reads of them that someone else made. A PDO frame decodes with the layout in force at its time, so a trace that holds a master's boot sequence decodes correctly before and after it.
  2. **Read from the device**: on a live connection the page reads the PDO communication and mapping objects of each node it hears, once per connection and again after the node boots up. Reads only, no Allow changes needed.
  3. **EDS defaults**: the default COB-IDs and mappings in the node's EDS.
  Signal names and types come from the node's EDS (its own, or the one picked on the Nodes tab), or from the built-in standard dictionary when there is none; a mapped object the EDS lacks shows as `0x6041:0` with its bit length as an unsigned value. Rows read like a configured PDO: `TPDO1 node 32 Statusword=0x0237, Position actual value=1200`.
- **Say where a layout came from.** The frame inspector names the source ("layout set by another master at 12.304 s", "read from the device", "EDS defaults: the device may differ"). Rows decoded from EDS defaults carry a muted "assumed" tag, since they are a guess.
- **No automatic reads beside another master.** When the connection bar reports another master, the page does not read PDO objects by itself (its SDO requests could collide with the master's); the Decoding panel offers **Read PDOs from device** instead and says why.
- **DBC files in the Trace.** A **Decoding** button in the Trace toolbar opens a panel with **Add DBC…** (one or more files) and the list of DBC files in use, each with its message count, problems and a remove button. DBC messages decode live recordings, opened files, the Chronological and By identifier views, graphs, triggers, the inspector and the decoded CSV export, with scale, offset, unit and multiplexing, exactly as raw messages do today. Works in every workspace and on every network kind.
- **Which decoding wins on an identifier.** The configuration's own PDOs and raw messages first; then the DBC files (the user chose them); then the inferred CANopen layouts; then the predefined connection set. NMT, SYNC, TIME, EMCY, SDO, heartbeat and LSS keep their CANopen decoding, and a DBC message on one of those identifiers adds its signals for graphs and triggers. DBC messages that lose to the configuration are listed in the panel as not used, with the reason.
- **Per-node view in the same panel.** For a CANopen network the Decoding panel lists each node heard or on the Nodes tab: device name, EDS (or "standard objects"), PDO layout source, and the actions **Pick EDS…** / **Change EDS…** (the Nodes table's own menu) and **Read PDOs from device**. A raw PDO row's inspector offers the same two actions, so the fix sits next to the problem.
- **Remembered.** The DBC files of a project folder, and of Commission a device, are remembered on this PC (outside the project's canworks folder, which travels with the PLC program) and come back on the next visit; a missing file is listed as missing.
- **Command line.** `canworks-diag trace`, `convert` and `explain` take `--dbc FILE` (repeatable) with the same precedence.
- Configurator tools version: next minor version after the changes in flight.

No config, contract, plugin or deploy change. Reads use the existing manual SDO read on both an adapter and a runtime connection.

## Default picked

- **Layout sources in the order above, automatic.** The bus is the truth, then the device, then the EDS as a labelled guess. There is no setting to turn inference off; a DBC overrides it for its identifiers.
- **Reuse the node's EDS.** The EDS a node already has on the Nodes tab (configured, matched or picked, including the pick and change of change `name-nodes-and-standard-dictionary`) is the one the Trace uses; the Trace does not keep its own EDS list.
- **Device reads only on a live connection.** An opened trace file decodes with what the trace itself shows, DBC files and EDS defaults, not with layouts read from whatever device is connected now.
- **DBC files are not copied into the project.** They stay where they are; the page remembers their paths (and, for files uploaded from another PC's browser, a copy in the user's configurator folder).

## Out of scope

- Inferred PDO layouts for nodes that are not in the configuration in a project's Trace (they keep the predefined connection set; the configuration is the source there).
- Embedding DBC files or layouts in saved trace files.
- J1939 networks keep their configured DBC; a Trace DBC only adds messages for identifiers that network does not decode.
- The pause button and inspector fixes of change `fix-trace-pause-and-about`.

## Capabilities

### New Capabilities
None.

### Modified Capabilities
- `canopen-bus-trace`: new requirements for PDO layouts without a configuration (sources, time-aware layouts, source in the inspector), DBC files in a trace and decoding precedence; "Raw message decoding" drops its DBC sentence in favour of the new requirement; `--dbc` on the trace commands.
- `canopen-configurator`: new requirement for the Trace's Decoding panel (DBC files, per-node EDS and layout source, Read PDOs from device, remembered files); modified "Trace toolbar and views" (Decoding button).

## Impact

- `tools/deploy/canworks/bustrace/decode.py`: `Decoder` gains a layout store per node with time-stamped versions and sources, learning from completed SDO transfers to 0x1400-0x1BFF; `PdoLayout` built from a mapping and an EDS (shared with `pdotest.layout`); DBC messages through `raw.decode.RawDecoder(messages=…)` with the precedence above.
- `tools/deploy/canworks/configurator/tracing.py`: `commission_decoder` takes device-read layouts and DBC files; `decoder_for` takes DBC files; layout learning runs in the session's decode pass so windows decode with the right version.
- `tools/deploy/canworks/configurator/server.py`: `/api/trace/decoding` (get and set DBC files, node rows), `/api/online/pdo_layout` (read one node's PDO objects through the manual SDO read); DBC paths remembered in the per-user configurator state.
- `tools/deploy/canworks/configurator/static/trace.js`, `trace_ids.js`, `explain.js` (Decoding button and panel, inspector source line and actions, "assumed" tag), `style.css`.
- `tools/deploy/canworks/diag.py`: `--dbc` on `trace`, `convert`, `explain`.
- Unit, page and browser tests; `docs/trace.md`, `docs/configurator.md`, `docs/diagnostics.md`; README (Trace paragraph).
