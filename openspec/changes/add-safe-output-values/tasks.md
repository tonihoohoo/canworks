## 1. Bridge

- [ ] 1.1 `can/config.{h,cpp}`: `on_client_loss` `"safe"`, `safe_values` parse; checks against the bindings (data outputs only, type ranges, REAL, bits, 64-bit strings; refuse bridge blocks, PLC link header, NMT command bytes, trigger and enable bits); warning when unused
- [ ] 1.2 `bridge/bridge_host.cpp`: safe image built at load (whole values, then bits); `enter_off` case `Safe` (write image, keep sending, log); start with the safe image; clean stop writes it and waits one SYNC (20-200 ms) and sends periodic J1939/raw once before `on_plc_stop`
- [ ] 1.3 C++ tests: each check's message; watchdog, idle, PLC link stopped and mismatch with `"safe"`; RPDO content with and without safe values; bit over word; reconnect write starts from safe values; start before the first write; clean stop order

## 2. PC tools

- [ ] 2.1 Both schema copies: `"safe"`, `"preop"` and `safe_values`
- [ ] 2.2 `bridgecheck.py`: the bridge's checks and warning with the same messages
- [ ] 2.3 `modbusmap.py` and exports: `safe_value` column (CSV, JSON), ST comment, HTML map column (`docexport.py`)
- [ ] 2.4 Configurator `static/bridge.js`: Safe values choice with descriptions, Safe values table (types, units, EDS limits, bit channels under entries, field errors), Problems warning with Use safe values, undo, connections out of date
- [ ] 2.5 Tests: check messages match the bridge's; map columns; page tests for the table, an out-of-range value, the leftover warning and undo

## 3. Docs

- [ ] 3.1 `docs/modbus-bridge.md`: `"safe"` and `safe_values` in the field table, a table of the five actions, safe values at start and clean stop, the "check it against the device manual" note
- [ ] 3.2 `docs/configurator.md` (Safe values table), `docs/config.md` if it lists bridge fields
- [ ] 3.3 README: Safe stops bullet names safe values
- [ ] 3.4 Version bump (minor) and release notes

## 4. Archive

- [ ] 4.1 `openspec archive add-safe-output-values --yes` on the branch; one PR with spec, code and archive; squash auto-merge

## 5. Hardware check (Pi)

- [ ] 5.1 Pi with node 23 on its OpenPLC connection, `"safe"` with a safe value on the valve output: stop the PLC through the runtime API; the trace shows the valve RPDO with the safe value on every SYNC, and the PLC's start resumes its own values
- [ ] 5.2 Same bench: `systemctl restart canworks-bridge@…`; the trace shows the safe value before the pre-operational command, and the safe value again from the start until OpenPLC writes
