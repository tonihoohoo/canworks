## Context

Inputs reach the PLC through the master's RPDOs: dcfgen gives the master one RPDO per node TPDO in the config, and `Network::HandleRpdoWrite` copies each received value into the process image. Lely calls `BasicMaster::OnRpdo(num, ec, p, n)` for every RPDO event, including errors; the plugin uses it only to arm the late check for synchronous PDOs and returns early on any `ec`. Supervision today covers the node (heartbeat or guarding, NMT state), not the data: a node whose heartbeat says OPERATIONAL is "up" even if one of its TPDOs has not been seen for an hour.

CiA 301 deadline monitoring: sub-index 5 of an RPDO communication object is its event timer; on the receiving side it is a deadline. Lely's `co_rpdo` starts the timer on each received PDO and reports an expiry. The existing `rx_pdos[].event_timer_ms` already sets this deadline on the *node's* RPDOs (outputs); this change sets it on the *master's* RPDOs (inputs).

## Goals / Non-Goals

**Goals:**
- Detect an input PDO that stops arriving while its node stays up, per PDO, without a plugin-chosen default.
- Tell the PLC program (bit), the operator (log, diagnostics, online view) and choose what the inputs show (hold or zero).
- Keep every existing config's behaviour unchanged.

**Non-Goals:**
- Changing what the node status bit or state byte mean, or treating a timeout as a lost node (no reboot, outputs keep going).
- Deadlines on slave networks' own RPDOs (the plugin as a slave), and gateway routes' own reaction.
- A per-node aggregate "inputs fresh" bit (the program can OR the PDO bits; could follow if asked).
- Changing the synchronous late PDO check; it stays as it is and runs alongside.

## Decisions

1. **Off unless the config asks; `"auto"` derives from the EDS.** A deadline has no EDS value of its own (it is the master's setting), so the only EDS-backed source is the node's own TPDO event timer: `event_timer_ms` from the config, else the EDS `DefaultValue` of 0x1800+n-1 sub 5. `"auto"` allows two event-timer periods, the smallest margin that does not trip on one late frame. A PDO with event timer 0 (pure change-of-state) has no period to derive from, so `"auto"` is refused there and the user picks a number that fits their process. Alternative considered: monitoring every PDO with a nonzero event timer by default. Rejected because it adds new warnings and timeouts to configs nobody touched, and because the margin would be a plugin-chosen value.

2. **Lely does the timing, through the master DCF.** The deadline is written as `ParameterValue` of sub 5 of the master RPDO whose COB-ID (sub 1) matches the node TPDO, in the same master DCF post-processing step that adds 0x1F26/0x1F27. A master NMT reset restores 0x1000-0x1FFF from the DCF, so a runtime write would be lost there. dcfgen's own `event_deadline` key is not used: dcfgen 2.4.2 fails on it without `event_timer` (see `emit_pdos`). Alternative: a plugin timestamp per PDO checked on the 100 ms supervision tick. Rejected as the main path because of its 100 ms resolution, but the tick still does the start check (decision 4).

3. **The timeout comes through `OnRpdoError`.** On the pinned Lely the deadline timer starts with the first received PDO and is one-shot; on expiry Lely calls the RPDO error callback with EEC 0x8250, which the C++ layer passes to `Node::OnRpdoError`, not to `OnRpdo`. A short PDO gives `OnRpdo` the length error and then `OnRpdoError` with 0x8210 (0x8220 too long). Lely's default `OnRpdoError` sends a master EMCY and sets the master's error register; the plugin overrides it without calling the base, so a node's quiet PDO does not raise an EMCY from the master. A PDO that never arrives starts no timer, so the supervision tick covers it. Both callbacks run with the master lock held, so they only set flags and defer the rest, like `OnRpdoWrite`.

4. **Start check on the supervision tick.** Lely's deadline timer starts at the first received PDO, so a TPDO that never arrives after the node starts would never time out. When a node becomes up, each of its PDOs with a deadline gets a "first PDO due by" time of node-up + `timeout_ms`; the 100 ms tick marks it timed out if nothing came. Any received PDO clears it.

5. **Timeout state is per PDO and only while the node is up.** While the node is not up its status bit already says so and its inputs hold; the timeout bit is FALSE then and the state is re-armed when the node comes back. This keeps one meaning per bit: status = node, timeout = data. The node status bit spec is unchanged.

6. **`on_timeout: "zero"`** writes 0 to every input binding of that PDO once, when it times out (in the deferred handler, then `commit_inputs`), and the next received PDO overwrites them. `"hold"` (default) matches what a lost node does today. Gateway routes fed by that PDO hold their last value in both cases (non-goal).

7. **Logging:** one warning per timeout period (`node 23 (valve) TPDO 2: no PDO for 500 ms (timeout_ms)`), one info when it is back with how long it was missing. No repetition while it stays timed out; the counter in diagnostics carries the rest.

## Risks / Trade-offs

- [A deadline shorter than the node's real sending rate gives false timeouts] → `"auto"` uses two periods; docs say to set at least two event-timer or SYNC periods; the Check warns when a number is below the effective event timer.
- [Synchronous PDOs with SYNC from the PLC cycle send at the PLC's rate, which the plugin does not know at config time] → no auto for them beyond the event timer rule; the user gives a number. The late check still covers them per SYNC.
- [Lely version differences in how the expiry is reported] → spike first (task 1.1), both paths handled, in-process test with a simulated device using the existing `tpdo_stop` fault.
- [Zeroing inputs can surprise a program that treats 0 as a valid value] → `"zero"` is opt-in; the default holds.

## Migration Plan

None: new optional fields within `schema_version` 1 and 2; configs without them behave exactly as before. Rollback is deleting the fields.

## Open Questions

- Should a later change add a node-level "all inputs fresh" bit? Left out until someone needs it.
