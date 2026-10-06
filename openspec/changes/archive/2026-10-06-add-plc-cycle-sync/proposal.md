# Proposal

## Why

The master's SYNC is a free-running Lely timer (`sync_period_us`) that knows nothing about the PLC scan. The scan publishes its outputs at `cycle_end()` and the bus thread sends them at whatever SYNC comes next, so output latency wanders between almost zero and one full SYNC period, and the inputs a scan sees may be one SYNC older than the previous scan's. The two clocks also drift against each other, so now and then a SYNC falls on the "wrong" side of a scan and one cycle sees no new inputs or two cycles carry the same output.

That is fine for slow I/O, but it rules out deterministic I/O timing (sample, compute, actuate on a fixed grid) and the cyclic synchronous drive modes (CSP/CSV), where the drive interpolates between set-points sent on every SYNC and needs exactly one new set-point per SYNC period. CODESYS solves this with a "bus cycle task" whose cycle drives SYNC. The runtime already calls the plugin's `cycle_start()` on every PLC frame from its SCHED_FIFO dispatcher, on an absolute-deadline clock, so the plugin has a better clock than its own timer.

## What Changes

- New optional `master.sync_source`: `"timer"` (default, today's behavior, unchanged) or `"plc_cycle"`. With `"plc_cycle"` the master sends one SYNC per PLC frame (or every `master.sync_cycles` frames, 1-1000, default 1), triggered from `cycle_start()`, right after the inputs were copied to the PLC. The SYNC carries the outputs the previous scan published at its `cycle_end()`.
- Result on the bus, per PLC frame k: SYNC k goes out at the start of frame k; nodes sample their synchronous inputs at it and the scan of frame k+1 sees them (input age: one frame). The outputs scan k writes go out right after SYNC k+1 and synchronous nodes apply them at SYNC k+2. Both latencies are fixed instead of wandering, and the SYNC period equals the PLC frame period.
- With `"plc_cycle"` the plugin does not run Lely's SYNC timer: the master's 0x1006 stays 0 and the plugin sends the SYNC frame itself (COB-ID from 0x1005, counter per `sync_counter_overflow`), then runs Lely's synchronous PDO processing for it. `sync_period_us` is rejected together with `"plc_cycle"` (the period comes from the PLC task). `sync_window_us` and `sync_counter_overflow` work as with the timer. Synchronous PDOs are allowed (the master produces SYNC). Unset PDO settings still default to the EDS values.
- The cycle hook stays non-blocking: `cycle_start()` only bumps a counter and wakes the bus thread through a preallocated eventfd. In `"plc_cycle"` mode the bus thread asks for SCHED_FIFO priority so SYNC follows the frame closely; if the runtime does not allow it, the plugin logs a warning and runs at normal priority.
- SYNC health is visible: the plugin counts SYNCs, measures the interval between SYNCs (last, min, max since start or reset), counts frames whose SYNC was skipped because the bus thread was still busy with the previous one, and counts cyclic synchronous TPDOs from nodes that did not arrive before the next SYNC. These go into the diagnostics status answer and the configurator's online view; skips and late PDOs are logged, rate-limited.
- Configurator: a "SYNC source" choice (timer / PLC cycle) in the master settings; the SYNC period field is for the timer, the "every N PLC cycles" field for the PLC cycle. Check, DCF export and DBC export follow the new field (DBC: SYNC message present, no cycle time on synchronous PDOs since the period is the PLC task's).
- Deploy tool and JSON Schema: new fields, minor version bump. `schema_version` stays 1 (optional additions only).

## Capabilities

### New Capabilities
<!-- none -->

### Modified Capabilities
- `canopen-master-bringup`: new requirements "SYNC from the PLC cycle" and "SYNC statistics"; "Master without SYNC" says what counts as producing SYNC.
- `canopen-pdo-io`: "Synchronous PDOs need SYNC" names `sync_source` in its hint; new requirement "PDO timing with PLC-cycle SYNC".
- `canopen-online-diagnostics`: "Live status" adds the SYNC source and statistics, shown in the online view.
- `canopen-configurator`: "Master settings" adds the SYNC source choice.
- `canopen-dbc-export`: "Fixed CANopen frames" and "Comments and timing" handle a PLC-cycle SYNC.

## Impact

- Plugin: `config.cpp`/`config.h` (fields and checks), `dcf_gen.cpp` (master 0x1006 = 0, producer bit), `network.cpp`/`network.h` (SYNC send path, statistics, late-PDO check), `bus.cpp` (eventfd, thread priority), `canopen_plugin.cpp` (`cycle_start()` trigger), `process_image` unchanged, `network_diag.cpp` (status fields).
- Deploy tool: JSON Schema, `contract.py`, configurator page and server, `dcfexport.py`, `dbcexport.py`, docs (`docs/config.md`, `docs/diagnostics.md`).
- Tests: unit tests for the config rules, an in-process simulation test that drives `cycle_start()`/`cycle_end()` on a fixed period and checks the SYNC count, output and input timing, a vcan test, configurator and export tests.
- A parallel change proposes an EDS device simulator; both touch the JSON Schema and the configurator, so whichever lands second rebases.
- No change for existing configurations: without `sync_source` the master behaves exactly as today.
