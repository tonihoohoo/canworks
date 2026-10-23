## 0. Order

- [ ] 0.1 Apply only after `add-openplc-modbus-target`, `remove-openplc-plugin`, `add-bridge-mailboxes` and `tidy-targets-and-exports` are merged and archived; rebase on main, check that change 3 left out its PLCopen output, switch change 3's `--export-modbus-map OUT.st` copy programs to the raw arrays (MODIFIED `modbus-bridge-map` requirement), and rewrite this change's deltas against the archived text where they touch the same requirements

## 1. Spikes (before the code)

- [ ] 1.1 CODESYS (Windows PC): from the script engine, import a PLCopen XML file into the application; add Ethernet adapter, Modbus TCP Master and Slave; set a channel's function, offset, length, trigger and cycle; map a channel onto `canworks.raw_in[k..]` (array range or one WORD per register); record the API in design.md
- [ ] 1.2 CODESYS: order the POU calls of a task from the script (first and last); find the task that runs the main program
- [ ] 1.3 truST (pinned release): import a TC6 file with CODESYS-style `canworks` and `canworks_const` lists and the ST library; located arrays `AT %IB0`; `modbus-tcp` points of type `u16` into them; cyclic writes when outputs don't change; record the form used
- [ ] 1.4 PLCopen TC6 XSD (official 2.01 and 10.0 schema): which one the three targets accept; vendor it with its licence

## 2. Bridge

- [ ] 2.1 `config.cpp`: `bridge.plc_link` (implied by `openplc`), same header refusals; schema field
- [ ] 2.2 `bridge_host.cpp` / `bridge_blocks`: header and hash switched by `plc_link`; tests for a non-`openplc` config with and without the flag

## 3. PC tools

- [ ] 3.1 `modbusmap.py`: `plc_link` in the map, hash, Pack for Modbus and checks
- [ ] 3.2 `openplcmodbus.py`: raw-word expression hook; OpenPLC output unchanged (golden files)
- [ ] 3.3 `plcopen.py`: TC6 writer (POUs with ST bodies, data types, CODESYS-style and standard globals, constants, documentation, tasks), deterministic output
- [ ] 3.4 Library POUs from `library/` into the writer; `library --format plcopen`; `--no-library`
- [ ] 3.5 `plcopen_targets.py`: CODESYS plan, truST `io.toml.part`, generic CSV and READMEs
- [ ] 3.6 `codesys/script/import_canworks_modbus.py` and the shared PLC lookup module (`import_canworks.py` uses it too, behaviour unchanged)
- [ ] 3.7 `cli.py`: `--export-plcopen OUT --for codesys|trust|generic`, `--with-main`, `--iec-base`, `--bridge-host`, `--codesys-plc`, `--codesys-ethernet`

## 4. Configurator

- [ ] 4.1 Export ▾ → For the program: For another PLC (PLCopen XML)… on Modbus bridge configs only; dialog (CODESYS as Modbus client with the line and link to the CODESYS target, truST, Other) and zip download (server endpoint reusing the CLI code)
- [ ] 4.2 Turn on the PLC link and repack, one undo step
- [ ] 4.3 Problems: loopback listen warning; dialog writers/address warnings

## 5. Tests and CI

- [ ] 5.1 Golden files for the three targets from a shipped example with mailboxes; schema check
- [ ] 5.2 CODESYS script against a fake script engine (first run, re-run, several tasks, no project)
- [ ] 5.3 truST pin file and import-and-compile test in the tools shard, path-selected, skips without the binary
- [ ] 5.4 Bridge tests for `plc_link`; page tests for the dialog
- [ ] 5.5 State CI wall time and summed job time against the baseline in the PR

## 6. Docs

- [ ] 6.1 `docs/plcopen.md`: what the file holds, the raw-array boundary, CODESYS, truST and other PLCs step by step, limits (sizes, consistency, watchdog)
- [ ] 6.2 README, `docs/modbus-bridge.md` (`plc_link`), `docs/plc-library.md`, `docs/codesys.md` (which CODESYS route to pick: CODESYS runs CANopen, or CODESYS as Modbus client of the bridge), `docs/configurator.md`, tour line

## 7. Hardware and desktop

- [ ] 7.1 CODESYS on the Windows PC (CODESYS Control Win in trial mode): run the script on a new project, build without errors, connect to the bridge on the Linux device with node 23; `canworks.ok` TRUE, a PDO value both ways, `CO_SDO_READ` of 0x1018:1
- [ ] 7.2 Same: change the config, re-export, run the script again; channels replaced, user POUs kept; a stale program (old hash) leaves outputs off
- [ ] 7.3 truST on the Linux device: import, merge `io.toml.part`, run against the local bridge; values both ways, `CAN_SEND` and `CO_SDO_READ`, PLC stop leaves outputs per `on_client_loss`
