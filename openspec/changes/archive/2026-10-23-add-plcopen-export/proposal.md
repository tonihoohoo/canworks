## Why

With the Modbus-only plan, every PLC reaches canworks through `canworks-bridge`. OpenPLC gets its program side generated (change 1: typed `canworks` variables, `canworks_in`/`canworks_out`, the PLC link header with the map hash; change 3: the function blocks as ST). Any other Modbus PLC gets only a register map and, from change 3, plain `.st` files to paste in. Users of CODESYS-based tools and of truST would have to rebuild the variable list, the copy programs and the tasks by hand and set up the Modbus client from the map.

PLCopen XML (TC6, IEC 61131-10) carries POUs with ST bodies, data types, global variable lists, constants and tasks, and CODESYS-based tools and truST import it. It cannot carry a Modbus client setup: that is vendor device configuration (research/plcopen-xml-2026-10-22.md). So canworks can ship one portable file for the program side, plus a small per-target transport file that connects that program to the bridge.

This is change 4 of the Modbus-only plan. It follows `add-bridge-mailboxes` (change 3), which leaves out its planned PLCopen output so the XML writer is built once, here.

## What Changes

- **PLCopen XML export.** `canworks-deploy --config FILE --export-plcopen OUT --for codesys|trust|generic` writes one TC6 XML file with the whole canworks ST library, the global variables `canworks` (typed values, `ok`, `link`, and the channel arrays `in_w` and `out_w`) and the programs `canworks_in` and `canworks_out`. These are the copy programs change 3's `--export-modbus-map OUT.st` writes for other PLCs: register k is `canworks.in_w[k]` / `canworks.out_w[k]`.
- **Channel arrays as the boundary.** The portable part ends at "input register k is in `canworks.in_w[k]`, holding register k is taken from `canworks.out_w[k]`". Each target's transport only moves registers in and out of those arrays.
- **CODESYS transport.** With `--for codesys`, a folder holds the XML, `canworks-codesys-modbus.json` and a script `import_canworks_modbus.py` for CODESYS's script engine. The script finds the PLC the same way the existing CODESYS script does, imports the XML, adds an Ethernet adapter (when there is none), a Modbus TCP Master and a Modbus TCP Slave device for the bridge with its address, and puts `canworks_in` first and `canworks_out` last in the PLC's task. What its script engine can't set (until checked on a real CODESYS: the channels) goes into the import report as steps by hand, with the values. It is re-runnable.
- **truST transport.** With `--for trust`, a folder holds the XML (standard TC6 with a structure for `canworks`, which truST imports), `canworks_io.st` with the located byte image (truST's import drops AT addresses), an `io.toml` part for its `modbus-tcp` driver and the import steps. truST's driver moves one request each way, so mailbox configs are refused for truST.
- **One library for strict compilers.** The whole library builds unchanged on truST, which checks IEC 61131-3 types strictly, as well as on STruC++ and CODESYS: typed literals, WORD arithmetic through conversions, and the reserved pin names `NEW` and `ANY` renamed to `RECEIVED`, `ALL_IDS` and `ALL_PGNS` (Toni 2026-10-23: "plcopen library should work everywhere"). `canworks-deploy library --format plcopen` writes the library alone.
- **Generic.** `--for generic` writes standard TC6 global variables (resource `globalVars`, no vendor `addData`) and the register map as CSV, for any other tool that imports PLCopen XML.
- **PLC link header for any bridge config.** `bridge.plc_link: true` turns on change 1's PLC link header (holding registers 0-2: running, map hash) and the hash at input registers 0-1 on any bridge config, not only `bridge.openplc`. The export requires it; the configurator offers to turn it on and repack. A program built for another map then leaves outputs off on every PLC.
- **Configurator.** Export ▾ → For the program gets **For another PLC (PLCopen XML)…** on Modbus bridge configs only, following `tidy-targets-and-exports` (every download in Export ▾; not on OpenPLC configs, whose program side Save writes). The dialog asks for the PLC (CODESYS as a Modbus client of the bridge, truST, or Other) and the bridge address the PLC uses, and downloads the folder as a zip. It explains that CODESYS here only uses the bridge's registers, and links to switching the project target to CODESYS when CODESYS should run the CANopen master itself. Problems warn when `listen` is loopback-only or the PLC address is not in `writers`.
- **CI.** Golden-file tests, a TC6 schema check, and an import-and-compile check with the truST CLI (open source, pinned release binary) in the existing tools shard, path-filtered.
- **Docs.** New `docs/plcopen.md`; README, `docs/modbus-bridge.md`, `docs/plc-library.md` and `docs/codesys.md` link to it.

Not included (Toni 2026-10-22): TwinCAT, importing PLCopen XML into canworks, OpenPLC through PLCopen (change 1's direct file writing stays).

## Capabilities

### New Capabilities

- `plcopen-export`: the PLCopen XML file, the channel-array boundary, and the CODESYS, truST and generic transports.

### Modified Capabilities

- `modbus-bridge`: `bridge.plc_link` on any bridge config.
- `canopen-configurator`: For another PLC (PLCopen XML)… in Export ▾ on Modbus bridge configs.
- `canopen-ci`: PLCopen export tests and the truST import check.
- `bridge-plc-blocks`: pins `RECEIVED`, `ALL_IDS`, `ALL_PGNS`.
- `plc-library`: builds on strict IEC tools; `library --format plcopen`.

## Impact

- PC tools: new `tools/deploy/canworks/plcopen.py` (TC6 writer), `tools/deploy/canworks/plcopen_targets.py` (CODESYS plan, truST files, generic CSV); a new CODESYS script `tools/deploy/canworks/codesys/script/import_canworks_modbus.py` that loads `import_canworks.py` for the PLC lookup; `openplcmodbus.py` copy code with typed literals; `library/modbus/*.st` strict typing and pin names; `cli.py`, `modbusmap.py` (`plc_link`), configurator Export ▾ and server.
- Bridge: `plugin/src/can/config.cpp` and `plugin/src/bridge/` accept `plc_link` outside `openplc` (the header logic of change 1, unchanged).
- Schema: `bridge.plc_link`.
- CI: a pinned truST release binary fetched in the existing tools job only when the PLCopen files change.
- Depends on changes 1-3 and on `tidy-targets-and-exports` (Export ▾ groups) being merged and archived. Hardware and desktop: CODESYS on the Windows PC against the bridge on the Linux device; truST on the Linux device.
