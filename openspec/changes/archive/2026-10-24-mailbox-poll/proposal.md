## Why

With the mailboxes on, OpenPLC's Modbus master reads and writes every mailbox register on every poll, whether a block is busy or not. On the Raspberry Pi 5 bench the OpenPLC runtime used about 9 % CPU without mailboxes and 31 % with the defaults (#278). The master converts each register in Python, so the cost follows the registers polled per second. The mailboxes are idle most of the time.

A true on/off switch at run time is not possible: the master's point list and cycle times are fixed in the editor project, and the PLC program cannot change them. What OpenPLC does allow is a cycle time per I/O group. In a cloud measurement of the real master plugin, the default mailboxes polled in their own groups every 50 ms cost 7.6 % against 10.6 % at 10 ms and 6.8 % without mailboxes. At 100 ms they cost 6.9 %.

The Node-RED package owns its poll loop, so it can skip the mailbox reads while nothing uses them.

Toni (2026-10-23): "explore activating mailbox dynamically in runtime when needed", then (2026-10-24) "Propose". Explore report: `research/dynamic-mailboxes-2026-10-23.md`.

## What Changes

- **Mailbox poll on the OpenPLC connection.** New field `mailbox_poll_ms`: a multiple of `poll_ms` up to 250. Unset, it is the smallest multiple of `poll_ms` that is at least 50 (50 ms at the default 10 ms poll).
  - The remote device file puts the mailbox blocks in their own I/O groups with that cycle time. The data, header, status, live list, SDO registers and control block stay in their groups at `poll_ms`.
  - The connection's Settings offer 10, 20, 50, 100 and 200 ms (the multiples of `poll_ms`). The hint says what the choice gives: the round trip of a mailbox block and how many frames per second the receive mailbox keeps up with.
  - The requests line says how many requests go out every poll and how many more every mailbox poll.
  - Hidden without mailboxes.
- **Node-RED reads the mailbox parts only while they are in use.** The config node reads the request mailboxes' responses only while a job holds one, the receive mailbox only while a receiver is open, and the cyclic table only while a cyclic job runs. Network info stays on every poll, because **canworks in** emits it. A part that becomes busy is read once before its first write, so the first request takes one poll longer.
- **Docs.** `docs/plc-library.md` gets a table of mailbox poll, round trip and receive rate, the new Pi numbers, and a line for other PLCs: put the mailbox range in its own channel with a slower cycle, if the driver allows it. `docs/modbus-bridge.md` and `docs/configurator.md` say the same in one line each. README: no change; it already links "Bridge or native CAN".

Not in real use, so this is a clean cut: editor projects get the split groups at the next Save, and nothing migrates.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `modbus-connections`: `mailbox_poll_ms` on the OpenPLC connection and its check.
- `modbus-bridge-map`: the OpenPLC remote device file puts the mailbox blocks in their own groups with the mailbox poll; requests are counted per poll and per mailbox poll.
- `canopen-configurator`: the OpenPLC connection's Settings show the mailbox poll and what it gives.
- `nodered-blocks`: the config node reads only the mailbox parts in use.

## Impact

- PC tools: `openplcmodbus.py` (group class for mailbox blocks, cycle time, request count), `bridgecheck.py` and both schema copies (`mailbox_poll_ms`), configurator `static/bridge.js` (Settings), Node-RED `nodered.py` (layout tags each read channel with its mailbox part) and `nodered_package/lib/bridge.js` (`_cycle`), tests.
- Generated files: `examples/openplc-modbus` and `examples/virtual-plant` editor files are regenerated.
- No change to the bridge, the mailbox protocol or the ST library. truST, Other PLC and HMI connections are unchanged.
- Tools minor version bump. Pi check of the CPU use with the new default.
