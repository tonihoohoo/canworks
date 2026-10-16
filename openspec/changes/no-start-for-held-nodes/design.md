# Design: no-start-for-held-nodes

## Where the START comes from

Lely's `co_nmt_boot_con` (lely-core `src/co/nmt.c`) runs when the boot of a slave ends. It re-reads the slave's 0x1F81 entry and sends NMT START to that slave when:
- the boot succeeded (`es == 0`),
- the entry has bit 0 (in the network) and bit 2 (the master may start it),
- the master may start nodes (0x1F80 bit 3 clear), and
- it starts them one by one (0x1F80 bit 1 clear) or the master is already OPERATIONAL.

When the master enters OPERATIONAL with "start all nodes" (0x1F80 bit 1), Lely sends one START to node 0 if every slave in the network list is booted and has bit 2 clear in its cached assignment, and otherwise START to each booted slave whose bit 2 is set.

The plugin's hold is applied after this, in `OnBooted` → `SendHold` (`network.cpp`), so a held node gets START, then its hold.

## Decision: clear bit 2 of 0x1F81 while a node is held

The plugin writes the node's 0x1F81 sub-index in the master's own object dictionary with bit 2 cleared whenever a hold is set, and writes back the configured value when the hold ends. Lely then skips the node in both START paths above:
- `co_nmt_boot_con` reads 0x1F81 at the end of every boot, so a hold set any time before the boot ends is seen.
- The start-all loop uses the assignment cached at the end of the node's last boot. A hold set after that boot and before the master starts all nodes is covered by the existing `NmtState::START` handler, which sends the hold again (as today). That case needs a booted node to be held while the master is not yet OPERATIONAL, which `CO_NETWORK_STOP` avoids by keeping Lely's master OPERATIONAL.

This is a local write to the master's dictionary (`co_dev_set_val_u32`, no SDO, no network traffic) and is not stored: the DCF is the source on the next start.

Alternatives considered:
- Set 0x1F80 bit 3 ("do not start slaves") while any node is held. It would stop the master from starting the other nodes too.
- Send the hold from `OnConfig`'s last step, before Lely's START. The START still goes out after it, so the node ends up started.
- Override `BasicMaster::OnBoot` to send STOP first. `OnBoot` runs after `co_nmt_boot_con` has already queued the START.

## Plugin state

`HandleBoot` computes `node_op` without the hold today. With the hold, `node_op` is false and the state is the hold's state (STOPPED or PRE-OPERATIONAL), and `StartSent` is not called. The log line says the node is configured and held.

## Releasing

Each release path (START from `CO_NMT`, command byte change, diagnostics, `CO_NETWORK_START`, gateway upper master back) restores the configured 0x1F81 value before it starts the node. Those paths already send START themselves or let the master start the node when its boot ends; they keep doing so.

## Risks

- A reset of the master (`reset_all_nodes`) restores 0x1F81 from the DCF. The reset branch already re-applies per-run state; it re-applies the cleared bits for held nodes too.
- A node outside the configuration is not affected (no 0x1F81 entry, no hold).
