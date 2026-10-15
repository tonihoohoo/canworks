# Proposal: fix-critical-bug-hunt-findings

## Why

A critical bug hunt of main 0f7b829 (2026-10-15) looked for crashes, wrong or stale values on the bus, data loss, security holes and NMT store writes in the code added since the 2026-10-09 audit. It found 3 high, 6 medium and about a dozen low issues. Nothing crashes the runtime, nothing gives control of the bus without a login, nothing writes 0x1010 or 0x1011 by itself, and every fix from the 2026-10-09 audit is still in place.

The real problems are wrong values on the bus:
- **A config number with a leading zero means two things.** The PC tools read `"012"` as 12; the plugin reads it as octal 10. The configurator checks one network and the PLC runs another, with PDOs on the SYNC or EMCY identifiers.
- **A cyclic frame the program cannot stop.** `CAN_SEND_CYCLIC` reports an error for a bad `PERIOD` or `DLC` but the plugin keeps sending the old frame, and the block can no longer stop it.
- **Program network control forgotten after a link drop.** `CO_NETWORK_STOP`, `CO_NETWORK_START` and `CO_NMT` holds are lost when the CAN interface goes down and up, so stopped nodes are started again with the program's outputs.

The medium findings: a DM11 clear on a read-only diagnostics channel, master TPDOs sent with DCF defaults after `reset_all_nodes`, a J1939 Request reply that swallows an on-change message, a J1939 receiver that can stay "Opening", a CiA 309-3 gateway session that keeps running after HTTP lines, and a CODESYS export that breaks on string numbers. Details and evidence are in design.md.

## What Changes

**Config numbers**
- A number written as a string is decimal or `0x` hex in every tool and in the plugin. A leading zero (other than `"0"` itself) is refused with a message, in the schema, the PC tools and the plugin. A JSON object with the same key twice is refused by the PC tools and the plugin.

**CANopen runtime**
- Program network control (`CO_NETWORK_START`, `CO_NETWORK_STOP`, `CO_NMT` holds, the NMT-command reset counters) belongs to the PLC run, not to one bus session: after an interface drop and return the master and nodes are brought back to what the program asked for.
- A gateway's "upper master lost" behaviour is applied again when the network starts while the upper master is still missing.
- After a master NMT reset (`reset_all_nodes`), master TPDOs are switched off again and come back only through the normal node-up path, so no DCF default values reach the bus.
- The scan watchdog keeps its view of the scan across bus sessions.
- Modbus bridge NMT commands that arrive while the network is down are dropped with a log line instead of queued.

**PLC function blocks**
- A `CAN_SEND_CYCLIC` update with a bad `PERIOD` or `DLC` ends the running job, as the API header says; the block stops a job before it lets go of its handle.
- A `J1939_RECEIVE` opened while the bus thread updates its receivers always gets its queue.
- A long `J1939_SEND` is matched to its own kernel completion; a timed-out send's late result is never given to another send.

**J1939 and raw CAN**
- A Request reply to one requester does not count as the on-change send to the message's own destination.
- Requests are not answered before the first PLC scan.
- A raw paged message truncates its switch value to the switch's length before choosing the page, as J1939 already does.
- A J1939 DM1 code list in a Modbus bridge config uses 4-byte steps.

**Diagnostics and gateways**
- `j1939_dm_clear` needs `allow_changes` like every other bus write.
- The CiA 309-3 gateway closes a session whose first line is not a CiA 309-3 command (for example an HTTP request line), on both the plugin's plain port and the PC forwarder of `canworks-diag gateway --listen`. Idle plain sessions time out.

**PC tools**
- The CODESYS export accepts PDO numbers and node IDs written as strings.
- The configurator saves a one-network version 2 config with a top-level `cia309` block.
- The local bus refuses to call an adapter listen-only when the device cannot do it, and honours a network's `adapter.listen_only` (no probe frame).
- The link service limits unpaired connections, counts a pairing attempt before the login, and has a memory limit; discovery takes answers only from the queried address and never changes a paired runtime's link ID without asking.
- A gateway route whose object is also an RPDO entry without `iec_location` is refused at config load.

## Capabilities

### New Capabilities
None.

### Modified Capabilities
- `canopen-config-contract`: number strings, duplicate keys.
- `canopen-plc-nmt`: program state survives a bus session restart; reset counters.
- `canopen-gateway`: upper master loss re-applied at start; route plus unlocated RPDO entry refused.
- `canopen-pdo-io`: master TPDOs after a master NMT reset; scan watchdog across sessions.
- `modbus-bridge`: NMT commands while the network is down.
- `can-plc-frames`: cyclic job ends on an input error.
- `j1939-plc-blocks`: receiver open race, long send completions.
- `j1939-ecu`: Request replies and on-change messages, no reply before the first scan.
- `can-multiplexed-signals`: out-of-range switch values.
- `modbus-bridge-map`: DM1 code lists in bridge configs.
- `canopen-online-diagnostics`: `j1939_dm_clear` needs `allow_changes`.
- `canopen-cia309-gateway`: first-line check and idle timeout.
- `codesys-export`: string numbers.
- `canopen-configurator`: one-network v2 save with `cia309`.
- `canopen-local-bus`: listen-only honesty.
- `remote-link`: unpaired peer limits, discovery answers.

## Impact

- Plugin: `can/config.cpp`, `canopen/bus.cpp`, `canopen/network.cpp`/`.h`, `canopen/host_requests.cpp`, `can/raw/plc_frames.cpp`, `can/raw/engine.cpp`, `j1939/j1939_network.cpp`, `j1939/j1939_plc_msgs.cpp`, `j1939/j1939_config.h`, `can/diag.cpp`, `can/cia309_server.cpp`, `canopen/cia309_dispatch.cpp`.
- Library: `library/generate.py` and the regenerated `CAN_SEND_CYCLIC`; `canworks.stlib` rebuilt.
- PC tools: `contract.py`, the schema, `codesys/plan.py`, `configurator/server.py`, `localbus/adapter.py`, `localbus/core.py`, `diag.py`, `link/device.py`, `link/discovery.py`, `link/pc.py`, `scripts/install-link.sh`.
- Breaking (clean cut, nothing is in real use): configs with leading-zero number strings are refused instead of read as octal.
- Docs: `docs/config.md` (number format), `docs/diagnostics.md` (`j1939_dm_clear`), the CiA 309-3 gateway page, README where user-visible.
