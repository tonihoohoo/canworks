## Why

A node can keep its heartbeat going while one of its input PDOs stops: someone changed its mapping, its firmware is stuck in one task, or an inhibit time or filter is wrong. The PLC then reads the last value forever and nothing tells the program. The plugin only checks synchronous PDOs (the late PDO count before each SYNC); for event-driven PDOs, which most I/O modules use, there is no check at all. CiA 301 has a standard tool for this, the deadline (event timer) of the master's own RPDO, and Lely already runs it and reports an expiry, but `Network::OnRpdo` (plugin/src/network.cpp:832) drops every error code. Inputs that freeze silently are the classic fieldbus failure the PLC program cannot see today.

## What Changes

- New optional field `timeout_ms` on each `tx_pdos` entry (PDOs the node sends, inputs to the PLC): a number of milliseconds (1-65535), or `"auto"`. Left out, nothing changes: no deadline is monitored, as today.
- `"auto"` takes the node's own event timer for that TPDO (the config's `event_timer_ms`, or else 0x1800+n-1 sub 5 from the EDS) and allows twice that. A PDO whose event timer is 0 or missing cannot use `"auto"`: the config is refused with a message that asks for a number. No plugin-chosen time is used anywhere.
- The deadline goes into the master's own RPDO for that PDO (0x1400+m-1 sub 5) in the generated master DCF, so Lely's CiA 301 deadline monitoring does the timing and it survives a master NMT reset.
- When the deadline expires the plugin marks the PDO as timed out: one warning in the log naming the node, the TPDO and the time, an optional `timeout_location` input bit (`%IX`) that is TRUE while it is timed out, and a timeout count for diagnostics. When the PDO arrives again, the bit goes FALSE and the log says it is back.
- A PDO that never arrives after its node is started counts as timed out too once `timeout_ms` has passed (Lely only starts its timer at the first PDO).
- Optional `on_timeout` per PDO: `"hold"` (default, the inputs keep the last value, like a lost node) or `"zero"` (the PDO's inputs read 0 while it is timed out).
- The node's status bit and state byte do not change meaning: they stay about the node's NMT state. The program combines `status` and the timeout bit when it needs "inputs are fresh".
- Lely's other RPDO error, a PDO shorter than its mapping, is logged once per PDO instead of being dropped.
- Diagnostics status: per node, its PDOs with a deadline, whether each is timed out and how many timeouts it had. The configurator's online view and `openplc-canopen-diag status` show them.
- Configurator: a "Timeout" field (empty = off, a number, or Auto showing the computed value) and the timeout bit's address in the TPDO settings; the Check gives the same messages as the plugin.
- JSON Schema, `contract.py` and its parity test; HTML network docs show the timeout in the PDO details; README and docs/config.md, docs/diagnostics.md, docs/configurator.md.

## Capabilities

### New Capabilities

### Modified Capabilities
- `canopen-pdo-io`: input PDO receive timeout (new requirements), `timeout_ms`/`on_timeout`/`timeout_location` fields.
- `canopen-online-diagnostics`: live status carries per-PDO timeout state and counts.
- `canopen-configurator`: timeout fields in the PDO settings, timeout state in the online view.
- `canopen-network-docs`: PDO details show the receive timeout.

## Impact

- Plugin: `config.h`/`config.cpp` (fields, checks), `dcf_gen.cpp` (master DCF post-processing for 0x1400 sub 5), `network.cpp`/`network.h` (`OnRpdo` error codes, per-PDO timeout state, start check on the supervision tick, inputs zeroed for `"zero"`), `process_image` (timeout bits), `network_diag.cpp` (status).
- Tools: JSON Schema (v1 and v2 share the PDO definition), `contract.py`, configurator PDO editor and online view, `diag.py` status output, network docs generator. Deploy tool minor version bump.
- Config format: three new optional fields within `schema_version` 1 and 2; existing configs load and behave unchanged.
- Not affected: node DCF export (the deadline is the master's setting, not the node's), DBC export, slave networks, gateway routes (a timed-out PDO's routed value holds, as with a lost node), CiA 402 axis blocks.
- README: one line under "Status to the PLC".
