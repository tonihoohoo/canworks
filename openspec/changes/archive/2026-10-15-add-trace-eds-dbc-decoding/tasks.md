## 1. Layouts without a configuration (decoder)

- [x] 1.1 `bustrace/decode.py`: per-node layout store with versions `{from_us, source, tpdos, rpdos}`; `_pdo` picks by COB-ID from the newest version at the frame's time; configured PDOs still first
- [x] 1.2 EDS-default layouts from `eds.mapping_info` and the communication objects' defaults (`$NODEID`, invalid bit), sharing the entry/name/type code with `pdotest.layout`
- [x] 1.3 Learn from completed SDO writes and read answers to 0x1400-0x1BFF (expedited, segmented, block): working copy per node, new `bus` version when a PDO becomes usable, removal on invalid COB-ID or count 0, per-object fallback to device/EDS
- [x] 1.4 Names and types from the node's EDS, else the built-in CiA 301/401/402 names, else `0xIIII:S` UNSIGNEDn; signal keys `node<N>.<PDO>.<name>` for graphs and triggers
- [x] 1.5 `Decoded` carries the layout source and its time for the inspector; "assumed" for EDS defaults
- [x] 1.6 Unit tests: EDS defaults, a recorded boot sequence (before/after), partial writes, disable/enable, block transfer, no EDS with built-in names, nothing known stays as today

## 2. DBC files (decoder)

- [x] 2.1 `Decoder` takes DBC messages (`raw.dbc.read_dbc`) through `RawDecoder(messages=…)`, indexed by identifier; precedence: config raw + PDOs, DBC in list order, inferred layouts, predefined set
- [x] 2.2 Protocol identifiers (NMT, SYNC, TIME, EMCY, SDO, heartbeat, LSS) keep the CANopen text and add the DBC decoding next to it; J1939 networks: the network DBC first, trace DBCs only for identifiers it does not decode
- [x] 2.3 Report of unused DBC messages with what decodes their identifier
- [x] 2.4 Unit tests: vendor DBC over an inferred PDO, config wins, heartbeat in a DBC, two DBCs on one identifier, multiplexed DBC message, extended identifiers on a plain network

## 3. Server

- [x] 3.1 `tracing.py`: `commission_decoder` and `decoder_for` take DBC files and device layouts; layout learning in the session's full decode pass; `clone()` shares versions
- [x] 3.2 `/api/trace/decoding` GET/POST: DBC list (add by path or upload, remove, order), node rows (device name, EDS, layout source and time), unused-message report
- [x] 3.3 `/api/online/pdo_layout {node}`: `pdotest.from_device` through the connection's manual SDO read (adapter and runtime), PDO 5+ until the first missing communication object
- [x] 3.4 Remember DBC paths per project folder and for Commission a device in the per-user state; uploads copied to `config_dir()/dbc/`; never in the canworks folder; missing files reported
- [x] 3.5 Server tests for the routes, the remembered list and a missing file

## 4. Page

- [x] 4.1 Toolbar **Decoding** button with summary and warning mark; panel with DBC files (Add DBC…, remove, reorder by mouse and keyboard) and Nodes (Pick/Change EDS… reusing the Nodes table menu, Read PDOs from device with its disabled reason and the other-master question)
- [x] 4.2 Automatic layout reads in Commission a device: after identity reads, one node at a time, once per connection, again after boot-up, not when STOPPED, never beside another master
- [x] 4.3 Inspector Layout line with source and actions for raw PDOs; "assumed" tag and tooltip in By identifier and Chronological
- [x] 4.4 Decoded signals from inferred layouts and DBC files in the Graph and Trigger signal lists
- [x] 4.5 Browser tests: add a DBC and see rows change, remembered after reload, raw PDO fixed from the inspector, assumed tag, layout read on a simulated adapter bus, no automatic read beside another master; layout fit at 1000/1280/1440 px in both themes; wording test

## 5. Command line

- [x] 5.1 `canworks-diag trace|convert|explain --dbc FILE` (repeatable) with the same precedence; tests

## 6. Docs and version

- [x] 6.1 `docs/trace.md` (decoding sources, precedence, Decoding panel), `docs/configurator.md` (Commission a device trace), `docs/diagnostics.md` (`--dbc`)
- [x] 6.2 README Trace paragraph; configurator tools minor version bump (after the changes in flight)

## 7. Hardware

- [ ] 7.1 On a real bus through a USB adapter in Commission a device: a device whose EDS is picked shows its TPDOs decoded with EDS defaults and the "assumed" tag, then decoded "read from the device" after the automatic read
- [ ] 7.2 With the PLC as master on the same bus: the other-master notice stops automatic reads; a trace that holds the master's boot decodes PDOs from the layouts it set
- [ ] 7.3 A DBC exported by the configurator for that bus, added in the Trace, decodes the PDOs with the project's names
