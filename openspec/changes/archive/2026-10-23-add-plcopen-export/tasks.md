## 0. Order

- [x] 0.1 Apply only after `add-openplc-modbus-target`, `remove-openplc-plugin`, `add-bridge-mailboxes` and `tidy-targets-and-exports` are merged and archived; rebase on main, check that change 3 left out its PLCopen output, reuse change 3's `--export-modbus-map OUT.st` copy programs and their `in_w`/`out_w` arrays, and rewrite this change's deltas against the archived text where they touch the same requirements

## 1. Spikes (before the code)

- [ ] 1.1 CODESYS (Windows PC): from the script engine, import a PLCopen XML file into the application; add Ethernet adapter, Modbus TCP Master and Slave; set a channel's function, offset, length, trigger and cycle; map a channel onto `canworks.in_w[k..]` (array range or one WORD per register); record the API in design.md
- [ ] 1.2 CODESYS: order the POU calls of a task from the script (first and last); find the task that runs the main program
- [x] 1.3 truST (pinned release): import a TC6 file with the `canworks` list and the ST library; located arrays; `modbus-tcp` driver; cyclic writes when outputs don't change; record the form used (design Decisions 2 and 6: structure global, `canworks_io.st`, one request each way)
- [x] 1.4 PLCopen TC6 XSD: 2.01 vendored from the MIT-licensed `plcopen` package with a README; files use the `tc6_0200` namespace, which CODESYS and truST read

## 2. Bridge

- [x] 2.1 `config.cpp`: `bridge.plc_link` (implied by `openplc`), same header refusals; schema field
- [x] 2.2 `bridge_host.cpp` / `bridge_blocks`: header and hash switched by `plc_link`; tests for a non-`openplc` config with and without the flag

## 3. PC tools

- [x] 3.1 `modbusmap.py`: `plc_link` in the map, hash, Pack for Modbus and checks
- [x] 3.2 `openplcmodbus.py`: typed literals in the copy programs (`WORD#`, `SEL`) for strict compilers; `channel_sizes`
- [x] 3.3 `plcopen.py`: TC6 writer (POUs with ST bodies, data types, CODESYS-style and standard globals, constants, documentation, tasks), deterministic output
- [x] 3.4 Library POUs from `library/` into the writer; `library --format plcopen`; `--no-library`
- [x] 3.5 `plcopen_targets.py`: CODESYS plan, truST `io.toml.part`, generic CSV and READMEs
- [x] 3.6 `codesys/script/import_canworks_modbus.py` and the shared PLC lookup module (`import_canworks.py` uses it too, behaviour unchanged)
- [x] 3.7 `cli.py`: `--export-plcopen OUT --for codesys|trust|generic`, `--with-main`, `--no-library`, `--bridge-host`, `--codesys-plc`, `--codesys-ethernet`
- [x] 3.8 `modbusmap.suggest_channels`: never cut a row (mailbox block or value) over two channels, as `modbus-bridge-map` already requires; with two request mailboxes the second was split at register 123, so a client could send its counter before its arguments (found by the truST mailboxes research)
- [x] 3.9 truST refusal names the trimmed mailboxes that fit (Toni 2026-10-23, instead of a points-mode follow-up); docs say which blocks work on truST; checked live against the bridge with simulated nodes: `CO_SDO_READ_STRING` through the request mailbox and `CO_SDO_READ`, 0 errors

## 4. Configurator

- [x] 4.1 Export ▾ → For the program: For another PLC (PLCopen XML)… on Modbus bridge configs only; dialog (CODESYS as Modbus client with the line and link to the CODESYS target, truST, Other) and zip download (server endpoint reusing the CLI code)
- [x] 4.2 Turn on the PLC link and repack, one undo step
- [x] 4.3 Problems: loopback listen warning; dialog writers/address warnings

## 5. Tests and CI

- [x] 5.1 Golden files for the three targets from a shipped example with mailboxes; schema check
- [x] 5.2 CODESYS script against a fake script engine (first run, re-run, several tasks, no project)
- [x] 5.3 truST pin file and import-and-compile test in the tools shard, path-selected, skips without the binary
- [x] 5.4 Bridge tests for `plc_link`; page tests for the dialog
- [ ] 5.5 State CI wall time and summed job time against the baseline in the PR

## 6. Docs

- [x] 6.1 `docs/plcopen.md`: what the file holds, the channel-array boundary, CODESYS, truST and other PLCs step by step, limits (sizes, consistency, watchdog)
- [x] 6.2 README, `docs/modbus-bridge.md` (`plc_link`), `docs/plc-library.md`, `docs/codesys.md` (which CODESYS route to pick: CODESYS runs CANopen, or CODESYS as Modbus client of the bridge), `docs/configurator.md`, tour line

## 7. Hardware and desktop

- [ ] 7.1 CODESYS on the Windows PC (CODESYS Control Win in trial mode): run the script on a new project, build without errors, connect to the bridge on the Linux device with node 23; `canworks.ok` TRUE, a PDO value both ways, `CO_SDO_READ` of 0x1018:1
- [ ] 7.2 Same: change the config, re-export, run the script again; channels replaced, user POUs kept; a stale program (old hash) leaves outputs off
- [ ] 7.3 truST on the Linux device: import, merge `io.toml.part`, run against the local bridge; values both ways and `CO_SDO_READ` (with the trimmed mailboxes of 3.9), PLC stop leaves outputs per `on_client_loss`

## 8. One library for strict compilers (Toni 2026-10-23)

- [x] 8.1 Pins `NEW` → `RECEIVED`, `ANY` → `ALL_IDS` (`CAN_RECEIVE`) and `ALL_PGNS` (`J1939_RECEIVE`) in the library, tests, example, J1939 and raw CAN call generators and docs
- [x] 8.2 Strict typing of every `library/modbus` block (typed literals, WORD arithmetic through conversions, bit-string shifts, `TIME_TO_DWORD`); 0 truST errors; STruC++ ST tests pass; `canworks.stlib` rebuilt
- [x] 8.3 truST export carries the whole library; the import test calls mailbox blocks too
- [x] 8.4 CODESYS names: locals `r`, `bit`, `n` renamed, test instance `s` renamed, `CW_CHAR` tables of 32 characters; reserved-name test over the whole library
- [x] 8.5 Build `library --format st` in CODESYS on the Windows PC with 0 errors (V3.5 SP22 P4, 2026-10-23: 44 sources, 48 POUs, 0 errors, 0 warnings, code generation passed)
