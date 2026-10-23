## Context

Research: research/plcopen-xml-2026-10-22.md (project files). Read against main 01be7e6, change 1 (`propose/add-openplc-modbus-target`: `openplcmodbus.py` copy-code generator, PLC link header, map hash) and change 3 (`propose/add-bridge-mailboxes`: ST blocks over mailboxes, `library --format st`, `--export-modbus-map OUT.st` with copy programs for other PLCs).

Facts this design relies on:
- TC6 carries `types/pous` (functions, function blocks, programs; ST bodies as plain text), `types/dataTypes`, and global variables in `instances/configurations/.../resource/globalVars`. CODESYS-based tools keep named global variable lists as `addData` "globalVars" objects and import them as GVLs. Constant and non-constant globals can't share one list in CODESYS's PLCopen form.
- CODESYS imports PLCopen XML from its script engine (`import_xml` on the application or device object) as well as from the menu. Its Modbus TCP Master and Slave devices are device-tree objects whose channels (function code, offset, length, trigger) are device parameters; whether the script engine can set all channel fields and map a channel onto an array element range is a spike (task 1.1).
- truST (0.24.75, pinned) imports the "TC6 XML v2.0 ST-complete subset" (POUs with ST bodies, data types, standard and CODESYS-style globalVars, configurations/resources/tasks) from its CLI and VS Code. Its `modbus-tcp` I/O driver is configured in `io.toml`, by default FC 4 for `%I` and FC 16 for `%Q`, or with typed points (`u16`, `i16`, `u32`, `i32`, `f32`, `bool`) at byte offsets of a byte-addressed image (`%IW2` = bytes 2-3). It is open source, with Linux release binaries.
- The OpenPLC Editor's PLCopen import replaces the whole open project and drops remote devices, so OpenPLC stays on change 1's direct file writing.

## Goals / Non-Goals

Goals: one export gives a CODESYS-based or truST project everything the OpenPLC route gives (typed names, link code, function blocks, map hash guard); the per-target part is as small as possible; the file is checked in CI without a commercial tool.

Non-goals: TwinCAT, Siemens or B&R output; importing PLCopen XML into canworks; graphical languages; carrying any Modbus or CAN device settings in `addData`.

## Decisions

### 1. Channel arrays as the boundary

`canworks` gets `in_w : ARRAY[0..NI-1] OF WORD` and `out_w : ARRAY[0..NO-1] OF WORD`, where NI and NO are one more than the highest input and holding register the map uses (`openplcmodbus.channel_sizes`). Element k is register k. These are the names change 3's `--export-modbus-map OUT.st` copy programs already use, so the export reuses that generator (`openplcmodbus.programs(..., other=True)`) unchanged: the same conversions, `link` copies, `ok` rule and header writing, with the map hash in the programs' code.

Alternative: one located variable per register, as for OpenPLC. Rejected: addresses mean different things on each PLC (CODESYS assigns its own, truST is byte-addressed), and a transport fills an array range in one step.

### 2. Lists and names

- `canworks`: the typed values with change 1's names, `ok`, `link`, `in_w`, `out_w`. Access is `canworks.ok`, `canworks.<value>` as in the OpenPLC route, so the same user code works on every target. Every typed value carries a `documentation` text: network, node, PDO and object, unit, scale.
- No separate constant list: the hash and register counts stay in the generated programs, as in change 3's `.st` export, so the export is one list.
- `codesys`: a CODESYS `addData` globalVars object with `{attribute 'qualified_only'}`, imported as a GVL.
- `trust` and `generic`: standard TC6. truST 0.24 cannot assign to an indexed element of an array inside a namespace-style list (its lowering refuses `canworks.out_w[k] := ...`), so the values become a structure type `canworks_values` and one resource global `canworks : canworks_values`. `canworks.<name>` reads the same in user code.

### 3. Library in the same file

The whole library (change 3's ST blocks with their helpers, `CW_LINK_SERVICE`, the CAN and J1939 helper functions and the REAL word helpers) goes into the same file by default. `--no-library` leaves it out, for a project that already has it. `canworks-deploy library --format plcopen --out DIR` writes only the library as `canworks-library.xml`. The POUs come from the packaged library's sources (`plclibrary.archive()`), parsed by a small declaration parser (`plcopen.parse_st`), so the file always matches the installed library.

### 4. Tasks

- `generic` and `trust`: one configuration `canworks_config`, resource `canworks_res`, cyclic task `canworks_task` (interval = the bridge's watchdog / 5, at least 10 ms, in 5 ms steps), instances `canworks_in`, `main` (only with `--with-main`, which also writes an empty `main` program) and `canworks_out`. Without `--with-main` the user adds their program to the task.
- `codesys`: no configuration in the XML (CODESYS keeps tasks in its task configuration). The script puts `canworks_in` first and `canworks_out` last in the only task, or in the one task that calls `PLC_PRG`; otherwise it lists the calls to add by hand.

### 5. CODESYS transport

Folder: `canworks.xml`, the plan `canworks-codesys-modbus.json`, `import_canworks_modbus.py`, the existing `import_canworks.py` (the new script imports it as a module for the PLC lookup and the build; its own auto-run guard does not fire when imported) and `README.txt`. The plan holds the bridge host, port, unit ID, the suggested channels (from `modbusmap.suggest_channels`), the cycle, the map hash, and optional PLC and Ethernet device names. The bridge host is `--bridge-host`, else `listen` when it is neither wildcard nor loopback; otherwise the export is refused (a CODESYS PLC can't reach a loopback bridge).

The script (IronPython 2.7 and CPython 3):
1. finds the PLC with the rule of `codesys-export` ("Uses the project's PLC") from `import_canworks.py`;
2. imports `canworks.xml` into the PLC's application with a reporter that resolves conflicts as Replace;
3. reuses or adds an Ethernet adapter, a Modbus TCP Master and a Modbus TCP Slave `canworks_bridge`, found by their device catalogue names (not by type IDs, which differ between CODESYS versions), and sets the slave's IP address, port and unit ID by parameter name;
4. lists each channel (function, cycle, offset, length, target range) as "by hand" until the real API is checked on a CODESYS (spike 1.1);
5. orders the task calls (Decision 4), builds, writes `import_report.txt`, and does not save.

Each step that the script engine refuses becomes a "by hand" line, so the user always gets the full list of what is left.

### 6. truST transport

Folder: `canworks.xml`, `canworks_io.st`, `io.toml.part`, `README.txt`. Found with the pinned truST 0.24.75:
- Its PLCopen import drops every AT address, in POU interfaces and resource globals alike. The located process image therefore ships as `canworks_io.st` (`cw_in AT %IB0 : ARRAY OF BYTE`, `cw_out AT %QB0`), copied into the project's `src`.
- Its `modbus-tcp` driver reads the whole `%I` image from `input_start` with FC 4 and writes the whole `%Q` image with FC 16 every cycle (outputs always pending), so one request each way, at most 125 input and 123 holding registers. A map over that is refused with that reason. With mailboxes, the refusal names what fits: one request mailbox and no receive mailbox, network info or cyclic jobs (105 input and 88 holding registers for the example), so the SDO, NMT and send blocks work on truST and only the receive, info and cyclic blocks don't (Toni 2026-10-23 chose this over a typed-points driver setup; research/trust-mailboxes-2026-10-23.md). Writing every cycle keeps the bridge's watchdog fed.
- `canworks_in` first copies `cw_in` into `canworks.in_w`, `canworks_out` last copies `canworks.out_w` into `cw_out`, high byte first (Modbus order), with FOR loops.
- `io.toml.part` replaces the project's `[io]` tables: address, unit, `input_start`/`output_start` 0, `timeout_ms` half the watchdog (100-1000), `on_error = "warn"` so a bridge restart leaves the PLC running with `canworks.ok` FALSE.
- runtime.toml's `[resource] name` must be `canworks_res`, the imported resource; the README says so.
- The bridge host defaults to 127.0.0.1 on a wildcard `listen`, the usual case of truST on the bridge's own Linux device.

### 7. `bridge.plc_link`

Change 1 makes the PLC link header part of `bridge.openplc`. Here, `bridge.plc_link: true` gives any bridge config the same header (holding registers 0-2, link states ok/stopped/mismatch, status byte 0 values 4 and 5) and the hash at input registers 0-1, with the same placement rules (data packed after the header). `bridge.openplc` implies it, and `plc_link: false` with `openplc` is refused. The bridge code path is change 1's, switched by the flag instead of by `openplc`. `--export-plcopen` refuses a config without it and names **Pack for Modbus** with the link on as the fix. The configurator's export dialog offers to turn it on and repack in one undo step.

### 8. Configurator

Export ▾ → For the program: **For another PLC (PLCopen XML)…**, on Modbus bridge configs only (`tidy-targets-and-exports` puts every download in Export ▾; an OpenPLC config's program side is written by Save, and its only writer is OpenPLC). The dialog has the PLC ("CODESYS (Modbus client of the bridge)", truST, Other PLC with PLCopen XML), with one line under CODESYS: "CODESYS reads and writes the bridge's registers; canworks-bridge still runs the CAN networks. To let CODESYS run the CANopen master itself, switch the project target to CODESYS" with a link to the Project page. Then the bridge address as the PLC sees it (default as the CLI), include library (on), and for CODESYS optional PLC and Ethernet interface names. It downloads `<config>-<target>.zip`, equal to the CLI output. Problems warn on a bridge config with `plc_link` whose `listen` is a loopback address ("only a PLC on this device can reach it"), and when the dialog's PLC address is not covered by `writers`.

### 9. Validation in CI

- Golden files for the three targets from the OpenPLC Modbus example turned into a PLC link config (without the library, so a library change does not touch them; the library has its own tests).
- Each file is checked against the PLCopen TC6 2.01 XSD (vendored from the MIT-licensed `plcopen` package, with a README) when `lxml` or `xmllint` is there; the writer's namespace is `tc6_0200`, mapped to the 2.01 schema for the check.
- truST: `test/plcopen/fetch-trust.sh` fetches the pinned release binary (version and SHA-256 in that file) into `~/.cache/canworks/trust`. The test imports the `trust` output with the whole library into a temp project, adds `canworks_io.st` and a program that calls a block of each family, and builds it. It skips when `CANWORKS_TRUST` is not set, so local runs without network still pass.
- The CODESYS script runs in Python against the fake script engine of the existing CODESYS script tests, extended with application import, tasks and device catalogue names.
- In the existing tools shard, selected by path (a `plcopen` output of the change classifier), so other pull requests pay nothing.

### 10. One library for strict compilers

Toni (2026-10-23): the library should work everywhere. truST checks types the way IEC 61131-3 reads, stricter than STruC++ and CODESYS, so the library was made to build there unchanged:
- `NEW` and `ANY` are reserved words: the pins become `RECEIVED` (every receive block), `ALL_IDS` (`CAN_RECEIVE`) and `ALL_PGNS` (`J1939_RECEIVE`). A clean cut (not in use), with the docs, examples and generated calls (J1939 and raw CAN assistants) changed with them.
- Typed literals where a bit string is expected (`WORD#0`, `WORD#16#00FF`, `DWORD#16#...`, `BYTE#0`, `LWORD#0`), and bit tests as `(w AND WORD#16#0001) <> WORD#0`.
- Arithmetic on WORD values through integer conversions: a counter increments as `UDINT_TO_WORD(WORD_TO_UDINT(w) + 1)` and a 16-bit difference is `DINT_TO_WORD(WORD_TO_DINT(a) - WORD_TO_DINT(b))`. truST stops the PLC on an integer overflow, and both forms wrap by truncation instead.
- `SHL`/`SHR` only on bit strings (`WORD_TO_LWORD`, `UDINT_TO_DWORD` before shifting).
- TIME conversions through `TIME_TO_DWORD`/`DWORD_TO_TIME` in milliseconds, the only TIME conversions truST has, with the same meaning in STruC++.
- CODESYS (found building `--format st` in CODESYS V3.5) also refuses IL operators and types as names: locals `r` (R), `bit` (BIT) and `n` (N) became `rec`, `slot_bit`, `cnt` and `bits`, and a test checks every POU, pin and local against one reserved list. Instance names in tests and generated calls avoid `s` and `r`.
- `CW_CHAR`'s byte tables were one 127- and one 128-character STRING, longer than CODESYS's default STRING(80) (and bytes over 127 may count double there). They are now eight tables of 32 characters; every byte 1-255 round-trips (checked on truST).
STruC++ builds and runs the library's ST tests unchanged, and the truST import test builds the whole library.

## Risks / Trade-offs

- CODESYS channel scripting is unverified. If channels can't be set from the script, the script stops after the import and the device tree step and lists the channels to add by hand (still one file and a report). Spike 1.1 decides before the code.
- truST is pre-1.0 and changes fast. The pin and the CI check catch breaks, and the export targets the documented ST-complete subset only.
- Large `link` and channel arrays are copied every scan. That is negligible on PCs and Linux devices, and the docs state the sizes.
- Per-request consistency, as for every Modbus client: each suggested channel is one request, and a PDO is never split over two (the map's rule).

## Migration Plan

New feature. The pin rename (Decision 10) is a clean cut: programs using `.NEW`, `ANY :=` on the receive blocks change to `.RECEIVED`, `ALL_IDS :=` and `ALL_PGNS :=`.

## Open Questions

None for Toni (2026-10-22: own change after change 3, CODESYS and truST, no TwinCAT, no import; 2026-10-23: the library should work everywhere). The CODESYS channel API is checked on the Windows PC (spikes 1.1/1.2).
