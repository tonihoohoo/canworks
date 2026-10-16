# Proposal: no-start-for-held-nodes

## Why

The hardware check of fix-critical-bug-hunt-findings (task 7.1, plugin 0.74.0) found that a node which boots while it is held still gets NMT START. The program had stopped the network with `CO_NETWORK_STOP`, `NODE_COMMAND := 2`, and the CAN link went down and up. The node booted again, was configured, and then the master sent START and, 33 µs later, STOP. No PDO went out and the node's heartbeat never showed OPERATIONAL, but for that moment the node was told to run while the program held it stopped. A drive or valve that acts on START faster than that would move.

The cause: Lely's master sends START to every slave whose boot ends well, when its 0x1F81 entry allows it (bit 2) and the master may start nodes. The plugin's hold is applied only afterwards (`OnBooted` → `SendHold`). The same happens for every kind of hold: the NMT command byte, `CO_NMT`, a diagnostics client, the gateway's upper-loss reaction and `CO_NETWORK_STOP`. It also happens when the master starts all nodes at once (`start_all_nodes`).

## What Changes

- A node held STOPPED or PRE-OPERATIONAL gets no NMT START from the master while it is held: not when its boot ends, and not when the master starts all nodes. After configuring it, the master sends only the hold's command.
- Releasing a hold (START from `CO_NMT`, the command byte, a diagnostics client, `CO_NETWORK_START`, the upper master returning) lets the master start the node again as before.
- The plugin checks every NMT START that Lely puts on the bus: a START to a held node is dropped, and a START to all nodes is sent to each configured node that is not held instead. The plugin's own STARTs release the hold first, so they pass. Nothing is written to any node, and nothing is stored.
- The plugin's view of a booted held node is its held state from the start (STOPPED or PRE-OPERATIONAL), never OPERATIONAL first.

No config, schema, PLC API or PC tool change.

## Capabilities

### Modified Capabilities
- `canopen-plc-nmt`: a held node is never sent START by the master.

## Impact

- Code: `plugin/src/canopen/network.cpp` (the send hook, `HandleBoot`, `ApplyMasterState`).
- Tests: simulator cases in `test/sim/sim_tests.cpp` that check the CAN frames, not only the log, with a simulated node that waits for START as real devices do (the test slave started itself before, so the simulator never showed the bug).
- Docs: a sentence in the NMT block documentation.
- Hardware: repeat the 7.1 link drop on the Pi.
