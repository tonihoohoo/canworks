# Design

## Context

How the runtime calls the plugin (upstream `core/src/plc_app/plc_state_manager.cpp`, branch `development`):

- One dispatcher thread (SCHED_FIFO, above every task thread) wakes on an absolute CLOCK_MONOTONIC deadline every base tick (`base_tick_ns`, the GCD of all task intervals, passed to plugins in `plugin_runtime_args_t`).
- On a tick where at least one task is due (a "frame"), it fires the previous frame's `cycle_end()` if still pending, then `cycle_start()`, then releases the due tasks. The previous frame's `cycle_end()` normally fires earlier, as soon as all its tasks finished, after the journal drain committed their outputs.
- So `cycle_start()` lands on the tick with only the dispatcher's wake-up jitter, while `cycle_end()` moves with the scan time.

Today the plugin copies inputs to the PLC in `cycle_start()` and reads outputs in `cycle_end()`, through lock-free triple buffers; the Lely loop runs on its own `canopen_bus` thread at normal priority, and SYNC comes from Lely's timer (master 0x1006 from `sync_period_us`). Without SYNC a 1 ms output timer sends event-driven outputs.

## Goals / Non-Goals

Goals: one SYNC per PLC frame (or every N frames) with fixed input and output latency; the scan never waits; existing configs behave exactly as before; health of the coupling is visible.

Non-goals: choosing a task other than the frame (the runtime gives plugins no per-task hook); CiA 402 interpolation settings on drives (0x60C2 and friends stay startup SDOs or device parameters); bus load planning; a PLC-visible SYNC status byte (possible later, see Open Questions).

## Decisions

### 1. Trigger at `cycle_start()`, not `cycle_end()`

The gap note suggested `cycle_end()` (smallest output latency). Rejected: `cycle_end()` moves with the scan time, so the SYNC period would jitter by the scan time's variation, which is exactly what CSP drives cannot take. `cycle_start()` is on the dispatcher's deadline. The cost is one frame of extra output latency (outputs of scan k go out after SYNC k+1, applied at SYNC k+2), which is the usual "outputs at the start of the next cycle" pattern and is constant.

Order inside `cycle_start()`: copy the newest input snapshot to the PLC (as today), then request the SYNC. The outputs that go with it are the snapshot the previous frame's `cycle_end()` published; the dispatcher always fires that `cycle_end()` before this `cycle_start()`, so the snapshot is complete.

### 2. The dispatcher thread only signals

`cycle_start()` must not block, allocate, log or take the Lely lock. It increments an atomic request counter and writes to an eventfd created at `start_loop()`; the eventfd is watched by the bus thread's poll loop. The bus thread, on wake-up: takes the latest output snapshot, writes it to the master's TPDO objects, sends SYNC, runs synchronous PDO processing, then services SDO-variable and NMT requests as `OnSync` does today. If the counter advanced by more than one since the last SYNC (bus thread too slow), it sends one SYNC and counts the others as skipped.

### 3. Sending SYNC without Lely's timer

With `"plc_cycle"` the master DCF keeps 0x1006 = 0, so Lely's SYNC service runs no timer, and 0x1005 keeps the producer bit (bit 30) and COB-ID (0x080 unless the EDS/DCF says otherwise). The plugin builds the SYNC frame itself (0 bytes, or 1 byte counter when 0x1019 > 1, counter 1..overflow) and sends it with `can_net_send()` under the master lock, then calls Lely's `co_nmt_on_sync()` with the same counter so the master's synchronous TPDOs go out and its synchronous RPDOs are taken over, the same path Lely uses after its own SYNC. Task 1.1 verifies this against Lely (dcfgen's handling of 0x1005 with `sync_period: 0`, and that `co_nmt_on_sync()` covers TPDO send and RPDO take-over); if dcfgen drops the producer bit, the plugin sets it in its DCF post-processing as it already does for 0x1F26/0x1F27.

Alternative considered: keep Lely's timer and re-phase it every frame. Rejected: Lely has no API to re-arm the SYNC timer from outside, and re-phasing would still drift between frames.

### 4. Bus thread priority

A normal-priority bus thread can be delayed by anything else on the CPU, which turns into SYNC jitter. In `"plc_cycle"` mode the plugin sets the `canopen_bus` thread to SCHED_FIFO at the priority of the runtime's highest task level, below the dispatcher. If `pthread_setschedparam` fails (no CAP_SYS_NICE, container limits) it logs one warning and continues. In `"timer"` mode nothing changes. Task 6.2 measures SYNC jitter on real hardware with and without this; if FIFO makes no measurable difference, it is dropped before archive.

### 5. Configuration rules

- `master.sync_source`: `"timer"` | `"plc_cycle"`, default `"timer"`.
- `master.sync_cycles`: 1-1000, default 1; only with `"plc_cycle"` (rejected otherwise).
- `"plc_cycle"` together with `sync_period_us` > 0 is rejected: the period comes from the PLC.
- "The master produces SYNC" now means `sync_period_us > 0` or `sync_source == "plc_cycle"`. Every existing check keyed on it (synchronous PDOs, `sync_start`, `sync_window_us`, `sync_counter_overflow`, the 1 ms output timer) uses that predicate.
- At start the plugin logs `SYNC every N PLC frame(s), base tick X µs`. When `base_tick_ns × sync_cycles` is below 1 ms it warns that the bus may not carry all PDOs in one period. When `base_tick_ns` is 0 (older runtime), it logs that the period is unknown and runs anyway.
- Frames are regular only when every task interval is a multiple of the fastest one. The plugin cannot see task intervals, so the docs say so and the measured min/max interval shows it.

### 6. Health counters

Kept on the bus thread, read by the diagnostics hub:
- `sync_count`, last/min/max interval between sent SYNCs in µs (CLOCK_MONOTONIC at send).
- `sync_skipped`: frames merged into one SYNC because the bus thread was still busy.
- `sync_late_pdos`: before sending SYNC n+1, each node TPDO with a cyclic synchronous type (1-240) that was due at SYNC n but has not arrived counts once; the log names node and PDO, at most once per 10 s per PDO.
- Reset with the diag channel's existing statistics reset (if none exists, on plugin start only).

The same counters exist in `"timer"` mode (interval and late PDOs are useful there too); `sync_skipped` stays 0.

### 7. Tools

Configurator master settings: "SYNC source" select; "SYNC period" visible for timer, "Every N PLC cycles" for PLC cycle. The Check, DCF export and DBC export use the shared "produces SYNC" predicate. DBC: SYNC message present; synchronous PDOs get no `GenMsgCycleTime` (the period is not in the config) and their comment says "every N PLC cycles". DCF export: master values as the plugin writes them (0x1006 = 0).

## Risks / Trade-offs

- PLC stops → SYNC stops. Nodes with SYNC supervision (0x1006 on the node, or a drive's interpolation watchdog) will fault when the PLC is stopped. Today the bus also stops with the PLC, so this is not new, but with `"plc_cycle"` a long task overrun no longer stops SYNC (the dispatcher keeps ticking) while outputs freeze. Documented.
- A first scan that takes long (runtime "first scan" handling) does not delay SYNC either; the first SYNCs carry zero outputs, as today.
- Sub-millisecond frames: allowed, warned. SocketCAN and slcan adapters will not keep up; the late-PDO counter shows it.
- slcan adapters add latency per frame; jitter numbers from task 6.2 are only valid for the adapter measured.
- Parallel EDS simulator change: both edit the JSON Schema and the configurator's master page. Expected conflicts are textual.

## Open Questions

- PLC-visible SYNC health (a `sync_status_location` byte: late PDOs this cycle, skipped SYNC)? Not in this change; easy to add later if wanted.
- Should `"plc_cycle"` also write the nominal period into the nodes' 0x1006 when the EDS has it? Left to startup SDOs for now, because the plugin only knows the base tick, not the frame period.
