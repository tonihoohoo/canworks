## Context

`BridgeHost::enter_off()` runs one of four actions when outputs go off (watchdog, idle command, PLC link stopped or mismatch): `stop` turns transmission off and clears the output image without sending, `zero` clears it, sends it once and then stops, `hold` keeps sending, `preop` stops and sends NMT pre-operational. `clear_outputs()` writes zeros over every data output (`data_outputs_`, the image ranges bound to outputs). Before the first writer's write the bridge is already in outputs off (by the watchdog from start, or by the PLC link header being stopped).

Bindings that can sit on an output location: RPDO entries (with bit channels), J1939 `tx` signals, raw `tx` signals and their trigger and enable bits, NMT command bytes, SDO variable values and triggers, and the bridge's own control block, SDO request and mailbox output areas.

## Goals / Non-Goals

**Goals:**
- A per-output value that the devices keep getting while no client controls the outputs.
- The same values whatever turned the outputs off (watchdog, idle, PLC stopped, wrong map).
- Checked against the binding's type at load, so a wrong safe value never reaches the bus.

**Non-Goals:**
- No per-output timeout (one watchdog for all, as now).
- No safe values for the PLC program's mailbox operations, cyclic frame jobs or SDO variables: those end when outputs go off, as now.
- No change to `master.on_plc_stop` or to node-side error behaviour (0x1029, RPDO event timers).

## Decisions

**1. A fifth action instead of a flag on `zero`.** `"safe"` keeps sending, like `hold`, because the point is that the device stays commanded: a node with an RPDO event timer would otherwise see the RPDO stop and go to its own error value, overriding the safe value. `zero` keeps its meaning (zeros once, then stop). A `safe` without any `safe_values` sends zeros continuously, which is a valid choice of its own.

**2. Keyed by location, in the `bridge` object.** `safe_values` maps a location string to a value. Every output kind gets a safe value the same way, the config needs no new field on PDO entries, J1939 or raw signals, and the bridge applies them by writing a prepared safe image over `data_outputs_`. Alternative considered: a `safe_value` field on each output entry. Rejected because it would need the same field in five places of the schema and the configurator. A per-location table on one page is also easier to review.

**3. Checks at load, in the bridge and the PC tools.** The location must be an output location covered by a data binding. Bridge blocks (control, SDO request, mailboxes, PLC link header), NMT command bytes and the trigger bits of SDO variables and raw messages are refused, because a safe value there would send a command. The value must fit the binding: the binding's integer range, a finite number for REAL32/REAL64, `true`/`false`/0/1 for a bit, and a decimal string for a 64-bit integer beyond 2^53. A bit location inside a bound byte or word sets only that bit over the word's own safe value. Bits apply after whole values.

**4. Safe values from the start.** Outputs are off from the bridge's start until the first writer's write (or the first running header with the PLC link). With `"safe"` the safe image is in place and sent from the start. This is the behaviour the action promises, and it also covers a PLC that never comes up. Alternative considered: send nothing until the first write, then use safe values only after a loss. Rejected because a PLC that crashed before the bridge restarted would then leave the outputs to the devices again.

**5. Clean stop sends them once more.** With `"safe"`, a clean stop writes the safe image and waits one SYNC period of each CANopen master network (at least 20 ms, at most 200 ms) so the RPDOs carry it, sends safe periodic J1939 and raw messages once, then runs `master.on_plc_stop`. A crash sends nothing. That is unchanged and documented with the node settings that cover it.

**6. The next write starts from the safe values.** Like `stop`'s cleared image, the safe image stays in the output image after outputs on again, so a client that writes one coil after a loss sends that coil and the safe values for the rest. The docs keep the advice that a reconnecting controller writes all its outputs at once.

## Risks / Trade-offs

- [A safe value is not safe on the real machine] → it is the user's value. The docs say to check it against the device manual. The configurator shows the unit and the EDS's limits next to each field.
- [Sending from the start drives outputs before the PLC is there] → that is what "safe" means. The table says so, and an empty table sends zeros as `zero` would, but keeps sending them.
- [A bit channel's safe value against the word's] → bits apply after whole values. Both show in the map and in the table.

## Open Questions

- Safe values from the bridge's start (decision 4): Toni to confirm, or prefer nothing until the first write.
