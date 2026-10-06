# Tasks

## 1. Spike

- [ ] 1.1 Check against Lely and dcfgen: master DCF with `sync_period: 0` keeps 0x1005 producer bit and COB-ID (else set it in DCF post-processing); a SYNC frame sent with `can_net_send()` followed by `co_nmt_on_sync()` sends the master's synchronous TPDOs and takes over its synchronous RPDOs; no Lely SYNC timer runs. Verify: in-process test with one Lely slave, ten hand-sent SYNCs, ten synchronous TPDO/RPDO exchanges.

## 2. Plugin configuration

- [ ] 2.1 `config.cpp`/`config.h`: `sync_source` (`timer`/`plc_cycle`), `sync_cycles` (1-1000), the three rejection rules, and one `produces_sync()` predicate used by every SYNC-dependent check (synchronous PDOs, `sync_start`, `sync_window_us`, `sync_counter_overflow`). Error texts as in the spec. Verify: unit tests for each rule and for an unchanged config.
- [ ] 2.2 `dcf_gen.cpp`: master `sync_period: 0` with `plc_cycle`, producer bit per 1.1. Verify: generated master DCF for an existing config is byte-identical to before.
- [ ] 2.3 Start-up log: source, `sync_cycles`, base tick; warning below 1 ms; note when the base tick is unknown.

## 3. SYNC path

- [ ] 3.1 `canopen_plugin.cpp`: `cycle_start()` copies inputs, then (with `plc_cycle`) counts frames and every `sync_cycles`-th frame bumps the request counter and writes the eventfd. No allocation, logging or locks.
- [ ] 3.2 `bus.cpp`: create the eventfd at start, watch it in the bus loop, SCHED_FIFO for the bus thread in `plc_cycle` mode with one warning on failure.
- [ ] 3.3 `network.cpp`: on request, write the latest outputs, send SYNC (COB-ID from 0x1005, counter per 0x1019), run `co_nmt_on_sync()`, then the same follow-up as `OnSync` (event-driven TPDOs, SDO variable and NMT requests). Merge multiple pending requests into one SYNC and count the skip. No 1 ms output timer in this mode.
- [ ] 3.4 Statistics: SYNC count, interval last/min/max, skipped, late cyclic synchronous node TPDOs (checked before each SYNC), rate-limited warnings; for both sources.
- [ ] 3.5 Diagnostics status: SYNC source and statistics in `network_diag.cpp` and the CLI client's status output.

## 4. Tests

- [ ] 4.1 In-process simulation: a fake dispatcher calls `cycle_start()`/`cycle_end()` every 10 ms for 10 s against a Lely slave whose TPDO 1 (type 1) carries a counter incremented per SYNC and whose RPDO 1 echoes an output. Verify: 1000 ± 1 SYNCs, the PLC sees the counter step by exactly 1 per cycle, the output appears after the next SYNC, zero skipped and late.
- [ ] 4.2 Same test with `sync_cycles: 2`, with a counter, and with a bus thread held busy for 25 ms once. Verify: SYNC every 20 ms; counter 1..overflow; skipped frames counted and logged once.
- [ ] 4.3 Late PDO: slave delays TPDO 1 past the next SYNC. Verify: late count rises, log names node and PDO, at most once per 10 s.
- [ ] 4.4 vcan test in CI with the real plugin build and a fake cycle driver. Verify: SYNC count and interval on `vcan0` via candump timestamps.
- [ ] 4.5 Regression: all existing timer and no-SYNC tests pass unchanged.

## 5. Tools

- [ ] 5.1 JSON Schema and `contract.py`: `sync_source`, `sync_cycles`, the same rules as the plugin (parity test).
- [ ] 5.2 Configurator master settings: SYNC source select, period / "every N PLC cycles" fields, Check uses the shared predicate; online view SYNC line. Page tests for the four configurator scenarios and the online line.
- [ ] 5.3 DBC export (SYNC message, no `GenMsgCycleTime`, comment) and DCF export (master 0x1006 = 0) with tests.
- [ ] 5.4 Docs: `docs/config.md` (fields, timing diagram in text, "task intervals should be multiples of the fastest", PLC stop stops SYNC), `docs/diagnostics.md` (SYNC line). Deploy tool minor version bump.

## 6. Hardware (runtime device, CAN adapter, one real node)

- [ ] 6.1 Run the template project with `"sync_source": "plc_cycle"` and a 10 ms task; record SYNC intervals in the configurator trace for 60 s. Verify: node stays OPERATIONAL, no late PDOs, report min/max interval.
- [ ] 6.2 Repeat with and without the bus thread's SCHED_FIFO (env switch for the test only) and compare jitter; drop the FIFO step if it makes no measurable difference.
- [ ] 6.3 Stop and start the PLC from the editor. Verify: SYNC stops with the PLC and resumes on start, the node recovers without a boot error.
