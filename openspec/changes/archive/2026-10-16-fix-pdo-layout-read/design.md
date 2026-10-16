# Design: fix-pdo-layout-read

## What happens today

1. `POST /api/online/pdo_layout` calls `params.pdo_values`, which reads 0x1000, then for each PDO the communication object's sub 1 (COB-ID), sub 2, the mapping count and each entry. A read that fails returns `None` and is skipped.
2. The server lists a PDO as read when sub 1 answered with a valid COB-ID, whatever happened to the mapping.
3. `Workspace.add_device_read` hands the values to the decoder; `NodeLayouts.pdos` makes a layout only when the COB-ID, the count and every entry are there, so the PDO is dropped.
4. The panel's PDO layout column shows the source of the node's best layout, or "unknown" when there is none.

So any failed mapping read is invisible: the message claims success, the column says "unknown".

## Decisions

### The read result per PDO
`pdo_values` returns, next to the values, a list of failures: `{pdo: "TPDO3", index, sub, reason}` with `reason` either "no answer" or the abort code and its text (the same text the Parameters tab shows). The server's answer becomes:

```json
{"node": 49, "pdos": [{"name": "TPDO1", "cob_id": 433, "usable": true}, {"name": "TPDO3", "cob_id": 945, "usable": false, "reason": "0x1A02:1 not read (no answer)"}], "device_type": 401}
```

`usable` is decided by the same code that builds the layout (`NodeLayouts.pdos`, through `tracing.read_result`), so the message and the decoding never disagree. A mapping count of 0 or over 64 is named too.

### One retry on no answer
A mapping read that times out is tried once more. Aborts are not retried: the device answered.

### Kept per node
`Workspace` keeps the last read's per-PDO result with the device values (`device_reads`), so the Decoding panel shows it after a reload, after Refresh and for automatic reads, which show no message.

### Panel text
- All usable: "read from the device at 12.345 s" and the PDO names (as now).
- Some usable: the same, plus a muted line per unusable PDO with its reason.
- None usable: "not read: TPDO1 0x1A00:0 not read (abort 0x06020000, object does not exist)" and the other PDOs on muted lines; Read PDOs from device stays offered.
- Never read: "unknown" (as now).

## Finding the real cause

The reproduction used a device without mapping objects. Real CiA 301 devices have them, so the real failure is probably a timeout or an unusual answer. The trace recorded during the report holds node 49's SDO answers (identifier 0x5B1); a Chronological view of them, or the bench repeat in the tasks, shows which. If it is a fault on our side (for example an answer the SDO client or the trace decoder parses wrongly), it is fixed in this change with a unit test of that answer.
