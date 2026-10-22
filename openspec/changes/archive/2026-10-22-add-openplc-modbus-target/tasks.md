## 1. Spikes (before the code)

- [ ] 1.1 Runtime v4.3.1 image + bridge on vcan0, hand-written `conf/modbus_master.json`: the master writes the header group first in each round, keeps one TCP connection, and its stop round reaches the bridge with zeroed outputs; record the order in design.md
- [ ] 1.2 OpenPLC Editor 4.3.2: a `devices/remote/canworks.json` written while the project is closed is loaded, shown with its aliases, and compiled into `conf/modbus_master.json`; what the editor does with the file when it was changed on disk while the project was open (reload, keep, or write back)
- [ ] 1.3 Same editor: does it keep `%ID` points written into the file (for a later improvement; not used by this change)
- [x] 1.4 STruC++ 0.7.0 library: a data type (`CW_LINK`) declared in the `.stlib` usable as a global variable type and as a block in-out in a project; task instances in one task run in their listed order
- [ ] 1.5 Editor version floor: the oldest editor release whose remote device groups carry `errorHandling`; record it for the docs

## 2. Bridge

- [x] 2.1 `config.cpp`: `bridge.openplc` (`poll_ms`, `remote_device`, `iec_base`), its defaults (listen 127.0.0.1:1502, writers 127.0.0.1, watchdog 5 × poll, at least 50), refusals (high_first word order, status not at input byte 4, locations in the header bytes)
- [x] 2.2 Map hash (CRC-32 over the canonical text of `modbus-bridge-map`); logged at start and printed by `--check-only`
- [x] 2.3 Header: input registers 0-1 hash; holding registers 0-2 outside the output image; link state ok/stopped/mismatch; writes dropped unless ok; stopped and mismatch enter outputs off before the write's values apply; status byte 0 = 4 on mismatch; one log line per state change
- [x] 2.4 `on_client_loss: "preop"` on every bridge config (NMT node 0 to every CANopen master network on enter, NMT start on leave)
- [x] 2.5 `test/bridge/`: header states, stop round with hold, mismatch, preop, hash test vectors shared with the Python tests

## 3. PC tools

- [x] 3.1 `modbusmap.py`: map hash (same vectors as 2.5), printed by `--export-modbus-map` and carried in every export format
- [x] 3.2 New `openplcmodbus.py`: remote device file (groups per range, merge rule, limits 125/123, aliases, `iec_base`, request count and warning above 40)
- [x] 3.3 `editorproject.py` and Save: `canworks` global variable list, `canworks_in` and `canworks_out` programs, task instances in order, library enabled; no `VAR` block in `main` for an OpenPLC Modbus project
- [x] 3.4 `targets.py` relevance table: `openplc` column (hides PLC-cycle SYNC, scan watchdog, `on_plc_stop`, CiA 402 axis, listen/writers/word order); config contract target rule
- [x] 3.5 Configurator: New config… OpenPLC writes `bridge.openplc`; Project target from `bridge.openplc`; plugin config message with **Switch to OpenPLC through Modbus** (one undo step); Project page (poll, port, hash, request count); Save writes the editor files with the changed-file confirm and the reopen message
- [x] 3.6 Devices: `plan.py` main actions for an OpenPLC project, plugin row "no longer used" with Uninstall; `install-runtime.sh --with-openplc --bridge` (pinned runtime, bridge, no plugin), also over `--ssh` and in `install-runtime.ps1` help
- [x] 3.7 Tests: `tools/deploy/tests/` for hash, remote device, generated programs, target switch, Save, Devices plan; page tests for the Project page and New config…

## 4. Library

- [x] 4.1 ST blocks `CO_SDO_READ`, `CO_SDO_WRITE`, `CO_NMT`, `CO_NODE_LIVE`, `LINK : ARRAY[0..88] OF WORD` (owner and queue words), ST helpers `CW_DWORD_TO_REAL`, `CW_REAL_TO_DWORD`, `CW_LWORD_TO_LREAL`, `CW_LREAL_TO_LWORD` (design 10)
- [x] 4.2 `library/generate.py` and `build.sh`: library contents as `plc-library` lists (plugin-calling blocks left out; CiA 402 ST blocks until change 2)
- [x] 4.3 Block tests on STruC++ against a scripted bridge register model: handshake, two instances in one scan, bridge not reachable (20), writes not allowed (21), timeout

## 5. CI

- [x] 5.1 `test/openplc_modbus/run.py` in the bridge-building CI job (design 10): the pinned runtime's own Modbus master plugin against the bridge example's simulated nodes, with the editor's `conf/modbus_master.json`: values both ways, SDO read, stop with hold keeps the last value, wrong hash leaves outputs off; `test/plc_modbus/run.sh` for the programs and blocks
- [ ] 5.2 CI time: wall and summed job time against the baseline (median of the last 5 green `main` code runs), both numbers in the PR

## 6. Docs and release

- [x] 6.1 README: OpenPLC runs canworks through the bridge and its own Modbus master; feature list and quick start
- [x] 6.2 `docs/modbus-bridge.md` (OpenPLC section, header, hash, preop), `docs/configurator.md` (targets, Project page, Save), `docs/plc-library.md` (blocks over the bridge, what moved out), `docs/devices.md`, `docs/deploy.md`; editor version floor from 1.5
- [x] 6.3 Example config `examples/openplc-modbus/` with a README (the editor project is generated by New config… and Save)
- [ ] 6.4 Tools minor version bump

## 7. Hardware (Linux device with the real node)

- [ ] 7.1 Devices page on an OpenPLC project: **Install the bridge X** next to the pinned runtime; the plugin is disabled by the next upload (no `conf/canworks.json`), the bridge owns the CAN interface, node OPERATIONAL
- [ ] 7.2 Editor project generated by the configurator, Build and upload from the stock editor: input and output values both ways, `canworks_ok` TRUE; `CO_SDO_READ` of 0x1018:1 and `CO_NMT` stop/start on the node
- [ ] 7.3 Measure with a 10 ms poll: input and output latency (mean and worst over 5 minutes), CPU of the runtime and the bridge; record in the PR
- [ ] 7.4 PLC stop with `on_client_loss: "hold"` and with `"preop"`: values held, node to PRE-OPERATIONAL and back on start; then a clean PLC start
