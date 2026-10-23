## Why

With the Modbus-only plan, every PLC reaches canworks through `canworks-bridge`. OpenPLC gets its program side generated (change 1: typed `canworks` variables, `canworks_in`/`canworks_out`, the PLC link header with the map hash; change 3: the function blocks as ST). Any other Modbus PLC gets only a register map and, from change 3, plain `.st` files to paste in. Users of CODESYS-based tools and of truST would have to rebuild the variable list, the copy programs and the tasks by hand and set up the Modbus client from the map.

PLCopen XML (TC6, IEC 61131-10) carries POUs with ST bodies, data types, global variable lists, constants and tasks, and CODESYS-based tools and truST import it. It cannot carry a Modbus client setup: that is vendor device configuration (research/plcopen-xml-2026-10-22.md). So canworks can ship one portable file for the program side, plus a small per-target transport file that connects that program to the bridge.

This is change 4 of the Modbus-only plan. It follows `add-bridge-mailboxes` (change 3), which leaves out its planned PLCopen output so the XML writer is built once, here.

## What Changes

- **PLCopen XML export.** `canworks-deploy --config FILE --export-plcopen OUT --for codesys|trust|generic` writes one TC6 XML file with the canworks ST library (the blocks over the bridge, `CW_LINK_SERVICE`, the pure ST helpers), the global variable list `canworks` (typed values, `ok`, `link`, and the raw register arrays `raw_in` and `raw_out`), the constant list `canworks_const` (`MAP_HASH` and the register counts), and the programs `canworks_in` and `canworks_out`. These are the same copy code an OpenPLC project gets, but they read and write `canworks.raw_in[k]` and `canworks.raw_out[k]` (register k) instead of `%IW`/`%QW` words.
- **Raw arrays as the boundary.** The portable part ends at "input register k is in `canworks.raw_in[k]`, holding register k is taken from `canworks.raw_out[k]`". Each target's transport only moves registers in and out of those arrays.
- **CODESYS transport.** With `--for codesys`, a folder holds the XML, `canworks-codesys-modbus.json` and a script `import_canworks_modbus.py` for CODESYS's script engine. The script finds the PLC the same way the existing CODESYS script does, imports the XML, adds an Ethernet adapter (when there is none), a Modbus TCP Master and a Modbus TCP Slave device for the bridge with one read and one write channel per suggested range mapped onto `canworks.raw_in`/`raw_out`, and puts `canworks_in` first and `canworks_out` last in the PLC's task. It writes an import report, and is re-runnable.
- **truST transport.** With `--for trust`, a folder holds the XML (CODESYS-style lists, which truST imports) and an `io.toml` part with a `modbus-tcp` driver whose points fill the raw arrays, plus the import command line.
- **Generic.** `--for generic` writes standard TC6 global variables (resource `globalVars`, no vendor `addData`) and the register map as CSV, for any other tool that imports PLCopen XML.
- **PLC link header for any bridge config.** `bridge.plc_link: true` turns on change 1's PLC link header (holding registers 0-2: running, map hash) and the hash at input registers 0-1 on any bridge config, not only `bridge.openplc`. The export requires it; the configurator offers to turn it on and repack. A program built for another map then leaves outputs off on every PLC.
- **Configurator.** Export ▾ → For the program gets **For another PLC (PLCopen XML)…** on Modbus bridge configs only, following `tidy-targets-and-exports` (every download in Export ▾; not on OpenPLC configs, whose program side Save writes). The dialog asks for the PLC (CODESYS as a Modbus client of the bridge, truST, or Other) and the bridge address the PLC uses, and downloads the folder as a zip. It explains that CODESYS here only uses the bridge's registers, and links to switching the project target to CODESYS when CODESYS should run the CANopen master itself. Problems warn when `listen` is loopback-only or the PLC address is not in `writers`.
- **CI.** Golden-file tests, a TC6 schema check, and an import-and-compile check with the truST CLI (open source, pinned release binary) in the existing tools shard, path-filtered.
- **Docs.** New `docs/plcopen.md`; README, `docs/modbus-bridge.md`, `docs/plc-library.md` and `docs/codesys.md` link to it.

Not included (Toni 2026-10-22): TwinCAT, importing PLCopen XML into canworks, OpenPLC through PLCopen (change 1's direct file writing stays).

## Capabilities

### New Capabilities

- `plcopen-export`: the PLCopen XML file, the raw-array boundary, and the CODESYS, truST and generic transports.

### Modified Capabilities

- `modbus-bridge`: `bridge.plc_link` on any bridge config.
- `canopen-configurator`: For another PLC (PLCopen XML)… in Export ▾ on Modbus bridge configs.
- `canopen-ci`: PLCopen export tests and the truST import check.

## Impact

- PC tools: new `tools/deploy/canworks/plcopen.py` (TC6 writer), `tools/deploy/canworks/plcopen_targets.py` (CODESYS plan, truST `io.toml`); a new CODESYS script `tools/deploy/canworks/codesys/script/import_canworks_modbus.py` that shares the PLC lookup with `import_canworks.py`; `openplcmodbus.py` copy-code generator gains a raw-word naming hook (shared with change 3's `.st` export); `cli.py`, `modbusmap.py` (`plc_link`), configurator Export ▾ and server.
- Bridge: `plugin/src/can/config.cpp` and `plugin/src/bridge/` accept `plc_link` outside `openplc` (the header logic of change 1, unchanged).
- Schema: `bridge.plc_link`.
- CI: a pinned truST release binary fetched in the existing tools job only when the PLCopen files change.
- Depends on changes 1-3 and on `tidy-targets-and-exports` (Export ▾ groups) being merged and archived. Hardware and desktop: CODESYS on the Windows PC against the bridge on the Linux device; truST on the Linux device.
