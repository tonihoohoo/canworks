## Context

`bustrace/decode.py` builds a `Decoder` per trace. With a configuration, `Decoder.from_config` takes PDO layouts from the DBC export's model, so configured PDOs decode with names and types. In Commission a device, `tracing.commission_decoder` gets `{node: EDS path}` from the page (the Nodes tab) and fills only `Decoder.eds` and `node_names`: SDO and EMCY use the EDS, PDOs fall through to the predefined-set branch that prints `node N` and the bytes.

The pieces needed already exist elsewhere:
- `pdotest.layout(get, eds, node_id)` turns PDO communication and mapping objects into a layout, from SDO reads (`from_device`) or from values (`from_values`), with names and types from an EDS.
- `eds.mapping_info(eds, index)` gives an EDS's default mapping; `_slave_config` in `decode.py` already builds layouts from EDS defaults for a slave network.
- `raw.decode.RawDecoder(messages=…)` matches DBC messages read by `raw.dbc.read_dbc()`, multiplexing included, but nothing passes it any.
- The Decoder already follows SDO transfers (expedited, segmented, block) to print them as one completed transfer.

Two related changes are in flight: `name-nodes-and-standard-dictionary` (identity reads per heard node, built-in standard dictionary, Change EDS… on the Nodes table) and `fix-trace-pause-and-about` (pause button, inspector state across live updates). This change builds on the first and does not touch what the second changes.

## Goals / Non-Goals

**Goals:**
- A PDO in Commission a device decodes to named, typed values without the user doing anything when the EDS or the bus says enough, and with one click otherwise.
- The user always knows whether a decoded value rests on fact (the bus, the device) or on a guess (EDS defaults).
- A DBC file can be added to any Trace and stays until removed.

**Non-Goals:**
- Changing how a configured project decodes its own PDOs.
- A DBC editor, or writing DBC content into the config (the raw-messages DBC import already does that for plain networks).
- Storing layouts or DBC files inside saved trace files.

## Decisions

### 1. One layout store per node, with versions in time

`Decoder` gets `layouts: {node: [LayoutVersion]}`, where a version is `{from_us, source, tpdos, rpdos}` and `source` is `bus`, `device`, `eds` or `config`. `_pdo` picks the PDO by COB-ID from the newest version with `from_us <= frame time`; configured PDOs (`self.pdos`) still win.

- **eds**: built once from the node's EDS (`mapping_info` defaults, communication COB-ID default with `$NODEID`), `from_us = 0`. PDOs marked invalid in the EDS (bit 31) are left out.
- **device**: built by the server from `/api/online/pdo_layout` reads (decision 3); applies from the time of the read to live frames only; frames recorded before it keep the older source.
- **bus**: learned while decoding (decision 2), from the frame's time.

Why versions and not "latest wins": a recorded boot sequence is the common case for a trace with another master. Frames before the master writes a new mapping are in the device's old layout; decoding them with the new one would show wrong values with confidence.

Alternative considered: decode PDOs only with the latest layout and re-decode on change. Rejected: wrong for the frames before the change, and the Chronological view decodes windows on demand, so "re-decode everything" is not cheap.

### 2. Learning layouts from SDO transfers on the bus

When `_sdo` completes a write (expedited, segmented done, or block done) or a read answer to an object in 0x1400-0x15FF, 0x1600-0x17FF, 0x1800-0x19FF or 0x1A00-0x1BFF, the Decoder updates a per-node working copy of those objects and, when the result is a usable PDO (COB-ID valid, mapping count > 0 and entries 1..count known), records a new `bus` version at that frame's time. Writing count 0 or setting bit 31 of the COB-ID removes the PDO in the new version (CiA 301 order: disable, clear count, write entries, set count, enable). Missing pieces fall back per object to the device or EDS version, so a master that writes only the mapping still decodes with the EDS COB-ID.

The windowed decode (`CONTEXT_KINDS`) re-decodes SDO frames before a window to rebuild transfer state; the layout learning instead runs in the session's full pass (`Session` already decodes every frame on open and as frames arrive) and stores versions in the Decoder, so window decodes read them without replaying. `clone()` shares the versions and copies only transfer state.

### 3. Reading the device

`/api/online/pdo_layout {node}` runs `pdotest.from_device` through the connection's manual SDO read (adapter or runtime), returns the layout and its read time, and the page posts it with the trace's decoding state. The page reads automatically:
- in Commission a device, on a live connection that can send;
- for each node heard on the bus, after its identity read (the queue of `name-nodes-and-standard-dictionary`, one node at a time);
- once per connection, again after the node's boot-up;
- not while the node is STOPPED (no SDO), and not at all while the connection bar reports another master.

**Another master**: two SDO clients on the same server channel (0x600+n / 0x580+n) can mix their transfers; the device answers whichever request it saw last and both clients may take the wrong answer. A manual press of **Read PDOs from device** says this in its confirmation and goes ahead only on confirm. Most of the time the other master's own boot-time writes are in the trace and decision 2 already covers it.

Reads stop at the first PDO number whose communication object does not exist (0x06020000), from 5 onwards; 1-4 are always tried.

### 4. Names and types

Signals of an inferred PDO are named and typed from the node's EDS: `eds.object_name(index, sub)` gives "Parent / Name" or "Name", the data type gives the decoding (`signal_value` + type name, as for configured PDOs). Without an EDS the built-in CiA 301/401/402 notes (`builtin_notes/`) give the names (so 0x6041 reads "Statusword" on a CiA 402 drive). An object neither knows is `0x6041:0` with its bit length as UNSIGNEDn. Signal keys are `node<N>.<PDO>.<object name>`, so graphs and triggers can use them and they do not collide with config keys.

This does not wait for `name-nodes-and-standard-dictionary`; the two changes do not otherwise depend on each other.

### 5. DBC files and precedence

A DBC file is read with `raw.dbc.read_dbc()` (cantools, non-strict) into the Decoder's `RawDecoder(messages=…)`. Order on an identifier:

1. Configured raw messages and configured PDOs (the user's project is the truth).
2. DBC messages.
3. Inferred PDO layouts (bus, device, EDS).
4. The predefined connection set.

For identifiers of NMT, SYNC, TIME, EMCY, SDO, heartbeat and LSS the CANopen decoding stays and a matching DBC message's decoding is shown next to it, like a forced raw message today, with its signals going to graphs and triggers. Rationale: a CANopen DBC (including our own export) describes heartbeats and NMT as plain bytes; "node 32 OPERATIONAL" is more useful than "State=5".

A DBC message that loses to the configuration is reported once in the Decoding panel ("message `Drive_TPDO1` 0x1A0: the configuration's TPDO1 of node 32 decodes this identifier"). Two DBC files with the same identifier: the file listed first wins, the other is reported the same way. Order in the list can be changed by drag or by the keyboard.

### 6. Where the DBC choice lives

Per-user configurator state (the same store as UI settings, `config_dir()`), keyed by the project folder, and one list for Commission a device. Each entry is a full path; files that are uploaded through the browser (the page and server may be on different PCs when reached remotely) are copied to `config_dir()/dbc/` and listed by that copy. Never inside the project's canworks folder, which goes to the PLC with the program. A file missing on the next visit is listed as missing with Remove and Locate…, and decoding goes on without it.

### 7. The Decoding panel and inspector

- Toolbar: **Decoding** between Capture… and the time mode, with a short summary ("2 DBC", "3 nodes") and a warning mark when a DBC file is missing or has problems.
- Panel (a popover anchored to the button, keyboard and screen-reader usable like Capture…):
  - **DBC files**: rows with file name, messages used / total, problems; Add DBC…, remove, reorder.
  - **Nodes** (CANopen networks only): node, device name, EDS file or "none, built-in CiA names", layout source and time, actions **Pick EDS…** / **Change EDS…** (opens the Nodes table's menu for that node) and **Read PDOs from device** (disabled with a reason without a connection; asks first beside another master).
- Inspector, for a PDO frame: a "Layout" line naming the source; for a raw PDO the line says why and offers the same two actions.
- Rows decoded from EDS defaults: muted "assumed" tag after the name in both views; the tag's tooltip says the device may be mapped differently and how to make it certain.

### 8. Command line

`canworks-diag trace|convert|explain --dbc FILE` (repeatable), merged with `--config` decoding by decision 5. No inference from EDS on the command line: with a config the config is the truth, without one there is no EDS list to infer from.

## Risks / Trade-offs

- [EDS defaults are wrong for a device a master has remapped] → the "assumed" tag and inspector line; learning from the bus and device reads replace it as soon as either is available.
- [Automatic reads add SDO traffic on a live bus] → one node at a time, once per connection, reads only, off beside another master; the same rules as identity reads.
- [Large DBC files slow the decode] → `RawDecoder` matching is a list scan today; index DBC messages by identifier (standard and extended separately) when building the decoder.
- [Precedence surprises] → losers are listed in the panel with the winner named; the inspector shows the DBC decoding next to the protocol's on protocol identifiers.

## Migration Plan

None: new behaviour only. Existing traces, configs and settings keep working; a trace with no DBC and a configured project decodes as before.

## Open Questions

None blocking. Whether to also infer layouts for unconfigured nodes in a project's Trace can follow later if it is missed.
