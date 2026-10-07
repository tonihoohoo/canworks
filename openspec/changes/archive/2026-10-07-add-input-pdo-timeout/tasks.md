# Tasks

## 1. Spike

- [x] 1.1 On the pinned Lely, find how an expired master RPDO deadline and a short PDO are reported (`OnRpdo` `ec`, the RPDO error callback with EEC 0x8250/0x8210, or both) and whether a deadline set through the master DCF's `ParameterValue` for 0x1400+m-1 sub 5 is active after start and after a master NMT reset. Verify: in-process test with one Lely slave that stops its TPDO; note the result here.
  Result: the expiry arrives only as `OnRpdoError` with EEC 0x8250 (one-shot timer, started by the first PDO); a short PDO gives `OnRpdo` a length error and `OnRpdoError` 0x8210. A deadline from the master DCF's `ParameterValue` is active after start and after a master NMT reset (read in the Lely source: the reset reloads 0x1000-0x1FFF from the DCF). The plugin overrides `OnRpdoError` so the master sends no EMCY.

## 2. Plugin configuration

- [x] 2.1 `config.h`/`config.cpp`: `timeout_ms` (1-65535 or `"auto"`), `on_timeout` (`hold`/`zero`), `timeout_location` (`%IX`) on `tx_pdos`; rejection rules from the spec with node, PDO and field in the message; `"auto"` resolved from `event_timer_ms` or the EDS 0x1800+n-1 sub 5 and logged at load; `timeout_location` in the location clash check. Verify: unit tests per rule and for an unchanged config.
- [x] 2.2 `dcf_gen.cpp`: master DCF post-processing writes sub 5 of the master RPDO whose COB-ID matches each monitored PDO (next to the 0x1F26/0x1F27 step). Verify: master DCF byte-identical for a config without `timeout_ms`; correct sub 5 for two nodes with several PDOs, including PDOs above 4 with `"cob_id": "auto"`.

## 3. Runtime behaviour

- [x] 3.1 `network.cpp`/`network.h`: per-PDO timeout state keyed by master RPDO number (alongside `sync_rpdos_`); `OnRpdo` (and the error callback per 1.1) only sets flags and defers; the deferred handler logs, counts, sets the bit, and for `"zero"` writes 0 to the PDO's inputs and commits.
- [x] 3.2 Start check on the supervision tick: when a node becomes up, each monitored PDO gets a due time; nothing received by then means timed out. Node down clears the state and the bit.
- [x] 3.3 Length error (EEC 0x8210) logged once per PDO until a good PDO arrives.
- [x] 3.4 `process_image`: timeout bits as inputs, updated in the same commit as the PDO's values.
- [x] 3.5 `network_diag.cpp`: per-node `pdo_timeouts` list in the status answer (number, timeout_ms, timed_out, count, since_ms).

## 4. Tests

- [x] 4.1 In-process simulation with a simulated device and the `tpdo_stop` fault: timeout after about `timeout_ms`, one warning, bit TRUE, status bit TRUE, inputs held; `sim_clear` brings it back, bit FALSE, "back" log line.
- [x] 4.2 Same with `"on_timeout": "zero"`: inputs read 0 while timed out and the next PDO's values after.
- [x] 4.3 PDO never sent after start: timed out within `timeout_ms` + one tick. Node power off: bit FALSE, no timeout logs while down.
- [x] 4.4 `"auto"` from config and from EDS event timer; rejected for event timer 0.
- [x] 4.5 Regression: all existing tests pass; master DCFs of the example configs unchanged.

## 5. Tools

- [x] 5.1 JSON Schema (shared PDO definition for v1 and v2) and `contract.py` with the same rules, parity test.
- [x] 5.2 Configurator TPDO settings: Timeout field with Auto and the resolved value, on-timeout choice, timeout bit address (suggestion and clash check), Check messages and the short-timeout warning; page tests for the configurator scenarios.
- [x] 5.3 Configurator online view and `openplc-canopen-diag status`: timed-out marks, counts, time since last PDO.
- [x] 5.4 Network docs: timeout in PDO details, timeout bit in the PLC I/O cross-reference; located variable declarations in the configurator include the timeout bit.
- [x] 5.5 Docs: docs/config.md (fields, how to pick a timeout, status vs timeout bit, example), docs/diagnostics.md, docs/configurator.md; README line under "Status to the PLC". Deploy tool minor version bump.

## 6. Hardware (runtime device, CAN adapter, one real node)

- [ ] 6.1 Set `timeout_ms` on the real node's event-driven input PDO with a `timeout_location`, then stop the PDO (map it to a COB-ID nobody listens to through the configurator's OD view, or disable it in 0x1800+n-1 sub 1). Verify: bit TRUE and one warning after about the timeout, node stays OPERATIONAL, bit FALSE after restoring the PDO. Put the template project back afterwards.
