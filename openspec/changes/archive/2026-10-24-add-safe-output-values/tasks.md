## 1. Bridge

- [x] 1.1 `can/config.{h,cpp}`: `on_client_loss` `"safe"`, `safe_values` parse; checks against the bindings (data outputs only, type ranges, REAL, bits, 64-bit strings; refuse bridge blocks, PLC link header, NMT command bytes, trigger and enable bits); warning when unused
- [x] 1.2 `bridge/bridge_host.cpp`: safe image built at load (whole values, then bits); `enter_off` case `Safe` (write image, keep sending, log); start with the safe image; clean stop writes it and waits one SYNC (20-200 ms) before `on_plc_stop`
- [x] 1.3 C++ tests: the check messages (shared fixture cases); watchdog with `"safe"` (safe values from start, after the watchdog, a one-coil write keeping the others, the clean stop log); PLC link stopped with `"safe"`

## 2. PC tools

- [x] 2.1 Both schema copies: `"safe"`, `"preop"` and `safe_values`
- [x] 2.2 `bridgecheck.py`: the bridge's checks and warning with the same messages
- [x] 2.3 `modbusmap.py` and exports: `safe_value` column (CSV, JSON), ST comment, HTML map column (`docexport.py`)
- [x] 2.4 Configurator `static/bridge.js`: Safe values choice with descriptions, Safe values table (types, units, EDS limits, bit channels under entries, field errors), Problems warning with Use safe values, undo, connections out of date
- [x] 2.5 Tests: check messages match the bridge's; map columns; page tests for the table, an out-of-range value, the leftover warning and undo

## 3. Docs

- [x] 3.1 `docs/modbus-bridge.md`: `"safe"` and `safe_values` in the field table, a table of the five actions, safe values at start and clean stop, the "check it against the device manual" note
- [x] 3.2 `docs/configurator.md` (Safe values table), `docs/config.md` if it lists bridge fields
- [x] 3.3 README: Safe stops bullet names safe values
- [x] 3.4 Version bump (minor) and release notes

## 4. Archive

- [x] 4.1 `openspec archive add-safe-output-values --yes` on the branch; one PR with spec, code and archive; squash auto-merge

## 5. Hardware check (Pi)

- [x] 5.1 Pi with node 23 on its OpenPLC connection, `"safe"` with a safe value on the valve output: stop the PLC through the runtime API; the trace shows the valve RPDO with the safe value on every SYNC, and the PLC's start resumes its own values. Result (bridge 0.137.0): on the PLC's stop the valve RPDO 0x217 went to the safe value 01, and after the start back to the PLC's 00. The RPDO is event-driven, so the safe value is sent once when it changes, not on every SYNC
- [x] 5.2 Same bench: `systemctl restart canworks-bridge@…`; the trace shows the safe value before the pre-operational command, and the safe value again from the start until OpenPLC writes. Result: failed on 0.137.0 (the stop let OpenPLC write 00 after the safe value), fixed in #307; on 0.137.1, two restarts each sent 0x217=01 before NMT 80 17 with no 00 in between, then after NMT 01 17 0x217=01 within 0.2 ms, and 00 about 140 ms later when OpenPLC wrote
