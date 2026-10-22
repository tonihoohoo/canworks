## Context

Research: research/plcopen-xml-2026-10-22.md (project files). Read against main 01be7e6, change 1 (`propose/add-openplc-modbus-target`: `openplcmodbus.py` copy-code generator, PLC link header, map hash) and change 3 (`propose/add-bridge-mailboxes`: ST blocks over mailboxes, `library --format st`, `--export-modbus-map OUT.st` with copy programs for other PLCs).

Facts this design relies on:
- TC6 carries `types/pous` (functions, function blocks, programs; ST bodies as plain text), `types/dataTypes`, and global variables in `instances/configurations/.../resource/globalVars`. CODESYS-based tools keep named global variable lists as `addData` "globalVars" objects and import them as GVLs. Constant and non-constant globals can't share one list in CODESYS's PLCopen form.
- CODESYS imports PLCopen XML from its script engine (`import_xml` on the application or device object) as well as from the menu. Its Modbus TCP Master and Slave devices are device-tree objects whose channels (function code, offset, length, trigger) are device parameters; whether the script engine can set all channel fields and map a channel onto an array element range is a spike (task 1.1).
- truST (0.24.x) imports the "TC6 XML v2.0 ST-complete subset" (POUs with ST bodies, data types, standard and CODESYS-style globalVars, configurations/resources/tasks) from its CLI and VS Code. Its `modbus-tcp` I/O driver is configured in `io.toml`, by default FC 4 for `%I` and FC 16 for `%Q`, or with typed points (`u16`, `i16`, `u32`, `i32`, `f32`, `bool`) at byte offsets of a byte-addressed image (`%IW2` = bytes 2-3). It is open source, with Linux release binaries.
- The OpenPLC Editor's PLCopen import replaces the whole open project and drops remote devices, so OpenPLC stays on change 1's direct file writing.

## Goals / Non-Goals

Goals: one export gives a CODESYS-based or truST project everything the OpenPLC route gives (typed names, link code, function blocks, map hash guard); the per-target part is as small as possible; the file is checked in CI without a commercial tool.

Non-goals: TwinCAT, Siemens or B&R output; importing PLCopen XML into canworks; graphical languages; carrying any Modbus or CAN device settings in `addData`.

## Decisions

### 1. Raw register arrays as the boundary

`canworks` gets `raw_in : ARRAY[0..NI-1] OF WORD` and `raw_out : ARRAY[0..NO-1] OF WORD`, where NI and NO are the bridge's input and holding register counts from the map (`image_sizes`). Element k is register k. The copy programs read `canworks.raw_in[k]` where the OpenPLC route reads its located word `i<k>`, and write `canworks.raw_out[k]` where it writes `q<k>`. Change 1's generator gets one hook: a function from (area, register) to the ST expression of that raw word. The OpenPLC route keeps located locals, and this export and change 3's `.st` export use the arrays.

Alternative: one located variable per register, as for OpenPLC. Rejected: addresses mean different things on each PLC (CODESYS assigns its own, truST is byte-addressed), and a transport fills an array range in one step.

### 2. Lists and names

- `canworks` (CODESYS: `{attribute 'qualified_only'}`): the typed values with change 1's names, `ok`, `link` (change 3's size), `raw_in`, `raw_out`. Access is `canworks.ok`, `canworks.<value>` as in the OpenPLC route, so the same user code works on every target.
- `canworks_const` (`VAR_GLOBAL CONSTANT`): `MAP_HASH : DWORD`, `INPUT_REGISTERS : UINT`, `HOLDING_REGISTERS : UINT`, `WORD_ORDER_LOW_FIRST : BOOL`. `canworks_in` compares the bridge's hash with `canworks_const.MAP_HASH`, and `canworks_out` writes it into the header.
- Dialect per target: `codesys` and `trust` write both lists as CODESYS `addData` globalVars objects (truST reads them). `generic` writes one standard resource with `globalVars` (and `globalVars constant="true"`) and no `addData`.
- Every typed value carries a `documentation` text: network, node, PDO and object, unit, scale.

### 3. Library in the same file

The library POUs (change 3's ST blocks, `CW_LINK_SERVICE`, the pure ST helpers and REAL word helpers) go into the same file by default. `--no-library` leaves them out, for a project that already has them. `canworks-deploy library --format plcopen --out FILE.xml` writes only the library. Change 3 removes its planned PLCopen output, so the writer exists only here.

### 4. Tasks

- `generic` and `trust`: one configuration `canworks_config`, resource `canworks_res`, cyclic task `canworks_task` (interval = the bridge's watchdog / 5, at least 10 ms, rounded to 5 ms), instances `canworks_in`, `main`, `canworks_out`. `main` is an empty program stub that says to put user code there, written only when `--with-main` is given; without it the instance is still listed and the user's own `main` fills it (truST reports an unresolved program otherwise; documented).
- `codesys`: no configuration in the XML (CODESYS keeps tasks in its task configuration). The script adds `canworks_in` as the first and `canworks_out` as the last call of the task that runs the application's main program, or of the only cyclic task; with several and no plan entry it stops and lists them (task 1.2 checks that the task's POU list can be ordered from the script).

### 5. CODESYS transport

Folder `canworks-codesys-modbus/`: `canworks.xml`, `canworks-codesys-modbus.json` (plan) and `import_canworks_modbus.py`. The plan holds the bridge host, port, unit ID, the suggested channels (from `modbusmap.suggest_channels`, never cutting a mailbox block), the cycle (watchdog / 5), the PLC device name (optional) and the Ethernet interface name (optional).

The script (IronPython 2.7 and CPython 3, like `import_canworks.py`):
1. finds the PLC with the same rule as `codesys-export` ("Uses the project's PLC"), sharing that code in a module both scripts load;
2. imports `canworks.xml` into the PLC's application, replacing objects of the same name that canworks wrote before;
3. reuses an Ethernet adapter under the PLC, or adds CODESYS's standard one (interface from the plan or left for the user, said in the report);
4. adds or reuses a `Modbus_TCP_Master` and under it a `Modbus_TCP_Slave` named `canworks_bridge` with the plan's address, port and unit ID;
5. replaces that slave's channels with the plan's: read input registers (FC 4) and write multiple registers (FC 16), cyclic at the plan's cycle, each mapped onto `canworks.raw_in[start..]`/`canworks.raw_out[start..]`;
6. orders the task calls (Decision 4), writes `import_report.txt` and does not save the project when run from the IDE, as `import_canworks.py` does.

The channel mapping may only be possible per register (one I/O channel per WORD). The script then maps each register's channel to `canworks.raw_in[k]`. Either way it is the same observable result (task 1.1).

### 6. truST transport

Folder `canworks-trust/`: `canworks.xml`, `io.toml.part` and `README.txt` with `trust import` (CLI) and the VS Code command. `io.toml.part` is one `modbus-tcp` driver entry for `io.drivers` with the bridge's address and unit, `input_points`/`output_points` of type `u16` per used register with the bridge's register addresses, at the process-image byte offsets of `raw_in`/`raw_out`. The lists in the XML declare `raw_in AT %IB<base>` and `raw_out AT %QB<base>` when truST accepts located arrays (task 1.3). Otherwise the copy programs read located words `%IW<base + 2k>` directly, and the export says which form it used. `base` defaults to 0 and is set with `--iec-base`.

Watchdog: the bridge's output watchdog needs a write within `watchdog_ms`. truST's worker writes the latest desired outputs; task 1.3 checks that it writes cyclically even when nothing changed. If not, the export sets the driver's cyclic write option, or the docs state the limit.

### 7. `bridge.plc_link`

Change 1 makes the PLC link header part of `bridge.openplc`. Here, `bridge.plc_link: true` gives any bridge config the same header (holding registers 0-2, link states ok/stopped/mismatch, status byte 0 values 4 and 5) and the hash at input registers 0-1, with the same placement rules (data packed after the header). `bridge.openplc` implies it. The bridge code path is change 1's, switched by the flag instead of by `openplc`. `--export-plcopen` refuses a config without it and names **Pack for Modbus** with the link on as the fix. The configurator's export dialog offers to turn it on and repack in one undo step.

### 8. Configurator

Bridge page: **Export for another PLC…** next to the map exports. The dialog has the target (CODESYS, truST, Other PLC with PLCopen XML), the bridge address as the PLC sees it (default: `listen` when it is not a wildcard or loopback address, else empty with a hint), include library (on), and for CODESYS optional PLC and Ethernet interface names. It downloads `<config>-<target>.zip`, equal to the CLI output. Problems warn on a bridge config with `plc_link` whose `listen` is a loopback address ("only a PLC on this device can reach it"), and when the dialog's PLC address is not covered by `writers`.

### 9. Validation in CI

- Golden files for the three targets from a shipped bridge example with mailboxes.
- The XML is checked against the PLCopen TC6 XSD (vendored, with its licence noted in the folder) with Python's standard library plus a small XSD subset checker. Where that is not enough, `xmllint` from the runner image.
- truST: the pinned release binary (version and SHA-256 in one file, like the runtime pin) imports the `trust` output into a temp project and compiles it; the test fails on any import diagnostic that is not a documented warning. Skipped with a message where the binary can't be fetched, so local runs without network still pass.
- The CODESYS script's plan logic is tested in Python with a fake script-engine object (as the existing CODESYS script tests do). The real run is a desktop task.
- All in the existing tools shard, selected by path (`plcopen*.py`, `codesys/script/import_canworks_modbus.py`, `library/`), so other pull requests pay nothing.

## Risks / Trade-offs

- CODESYS channel scripting is unverified. If channels can't be set from the script, the script stops after the import and the device tree step and lists the channels to add by hand (still one file and a report). Spike 1.1 decides before the code.
- truST is pre-1.0 and changes fast. The pin and the CI check catch breaks, and the export targets the documented ST-complete subset only.
- Large `link` and raw arrays are copied every scan. That is negligible on PCs and Linux devices, and the docs state the sizes.
- Per-request consistency, as for every Modbus client: each suggested channel is one request, and a PDO is never split over two (the map's rule).

## Migration Plan

New feature, nothing to migrate. Change 3's `.st` export switches to the raw arrays too, in the same PR (task 0.1).

## Open Questions

None for Toni (2026-10-22: own change after change 3, CODESYS and truST, no TwinCAT, no import).
