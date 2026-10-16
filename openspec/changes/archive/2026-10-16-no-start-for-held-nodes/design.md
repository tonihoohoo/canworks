# Design: no-start-for-held-nodes

## Where the START comes from

Lely's `co_nmt_boot_con` (lely-core `src/co/nmt.c`) runs when the boot of a slave ends. It re-reads the slave's 0x1F81 entry and sends NMT START to that slave when:
- the boot succeeded (`es == 0`),
- the entry has bit 0 (in the network) and bit 2 (the master may start it),
- the master may start nodes (0x1F80 bit 3 clear), and
- it starts them one by one (0x1F80 bit 1 clear) or the master is already OPERATIONAL.

When the master enters OPERATIONAL with "start all nodes" (0x1F80 bit 1), Lely sends one START to node 0 if every slave in the network list is booted and has bit 2 clear in its cached assignment, and otherwise START to each booted slave whose bit 2 is set.

The plugin's hold is applied after this, in `OnBooted` → `SendHold` (`network.cpp`), so a held node gets START, then its hold.

## Decision: drop Lely's START to a held node at the send hook

Every frame Lely sends goes through the plugin's send hook (`Network::SendTapped`, already used by the simulated bus trace; now installed for every session). `FilterStart` looks at NMT frames (COB-ID 0x000, 11-bit, two bytes) with command 0x01:
- START to one node: dropped when the configuration lists the node and it is held. The log says `no NMT START while it is held`.
- START to all nodes (node ID 0) while any configured node is held: sent instead to each configured node that is not held, one frame each.
- Everything else passes unchanged.

The plugin's own STARTs (release from `CO_NMT`, the command byte, a diagnostics client, `CO_NETWORK_START`, the gateway's upper master returning) clear the hold before they send, so they pass. The hook runs on the bus thread, which owns the holds.

Alternatives considered:
- Clear bit 2 of the node's 0x1F81 entry while it is held (the proposal's first plan). Lely reads that bit when a boot starts too: without it Lely skips the whole boot-slave process, configuration included (`nmt_boot.c`). It would have to be cleared between the configuration and the end of the boot, and with `config_check` and an unchanged configuration the plugin gets no call in between.
- Set 0x1F80 bit 3 ("do not start slaves") while any node is held. Lely reads the startup value at its reset, and it would stop the master from starting the other nodes too.
- Send the hold from the last configuration step. Lely's START still goes out after it.

Lely itself still believes it sent the START. It does not act on that belief: a held node's heartbeat state is handled by the plugin (`OnState`), which already puts back a hold when the state does not match.

## Simulator

The test slave (`config/pingpong/cpp-slave.eds`) has no 0x1F80, so Lely's slave starts itself and the master never sends START: the bug did not show in the simulator. The new tests use the same slave with 0x1F80 = 4 (wait for the master's START), as real devices do, and count the NMT frames on the bus.

## Plugin state

`HandleBoot` computed `node_op` without the hold. With a hold, `node_op` is false, the state is the hold's (STOPPED or PRE-OPERATIONAL) and `StartSent` is not called. A node that started itself (`es == 'L'`) is still counted as running until the hold's command takes it out, as before. The master's start of all nodes (`ApplyMasterState`) skips held nodes the same way.

## Releasing

Unchanged: each release path clears the hold and then sends START itself to a booted node, or lets the master start the node when its boot ends.

## Risks

- A START to all nodes while one is held becomes one frame per configured node. A device on the bus that the configuration does not list gets no START then; without a hold nothing changes.
- A raw START frame from the program's own CAN blocks does not go through Lely and is not filtered.
