# Proposal: stopped-master-boots-nothing

## Why

The hardware rerun of stopped-master-stays-silent (9.1, plugin 786907ad on the Pi) passed. It also showed four things that are still wrong once `stop_all_nodes` has stopped the master and the bus session restarts (CAN interface down and up):

1. The master never stops trying to boot the lost mandatory node. On the bus it sends `60A#40 00 10 00…` (upload of 0x1000), then its own abort `60A#80 … 05 04 00 00`, once a second until the PLC restarts. The log shows "SDO abort code 05040000 … to node 0A" every 5 s. The node was sent NMT STOP, and a STOPPED node answers no SDO, so this boot can never succeed. It is Lely's own boot of the slave after the session's start-up, which `ScheduleRetry` does not control.
2. The log then says "node 10 (simio) is mandatory and not answering: the master holds the whole network in PRE-OPERATIONAL (no PDOs for any node) until it boots". The master is STOPPED, though, and it stays STOPPED when the node boots.
3. The diagnostics status shows node 10 PRE-OPERATIONAL, but the plugin log says "simulated node 10: STOPPED", and the master sent STOP to every node right after the node's boot-up. The node's heartbeat time is back at its EDS default (it was not configured in this session), so no heartbeat corrects the state. The state shown is the boot-up's.
4. Both nodes get boot error B, "No response received for upload request of object 1000". For node 23 there is no SDO request on the bus at all, and its heartbeat (`717#04`, STOPPED) arrives every second. The plugin's 3 s "not answering" check counts a node that was not booted in this session as absent.

A fifth issue was already noted in stopped-master-stays-silent. A simulated device that was powered off powers itself on again when the session restarts (`70A#00` right after the bounce), because the simulator is built per session. A power-off fault should last until it is cleared, as a real device's would.

## What Changes

- While `stop_all_nodes` holds the master STOPPED for the run, the master boots no node: no boot SDO and no boot retry, in this session or in later ones. SDO from the program, the diagnostics channel and the gateway still go out, as before.
- After the master's NMT STOP to every node, a node's state reads STOPPED (4) until a heartbeat or boot-up from it says otherwise. A boot-up gets STOP again, as now.
- A node that is not booted because the master is stopped is not reported as not answering: no boot error B and no "not answering" log. One log line per session says that the master boots no node until the plugin restarts. The PRE-OPERATIONAL message is used only when the master really holds the network in PRE-OPERATIONAL.
- A simulated device that was powered off stays off across a bus session restart. It comes back with `power on`, `clear`, a scenario step or a PLC restart.

No config, schema or PLC API change.

## Capabilities

### Modified Capabilities
- `canopen-plc-nmt`: a stopped master also boots no node in later sessions.
- `canopen-node-supervision`: node states and boot errors while the master is stopped.
- `canopen-device-simulator`: power off lasts across bus sessions.

## Impact

- Code: `plugin/src/canopen/network.cpp` and `.h` (session `Start`, `HandleBoot`, the `OnTick` absent check, the held-master message), and the simulated bus's per-session device set, which keeps each device's power state for the run.
- Tests: extend `sim_stop_all_nodes_restart_node_back_in_session` (no SDO to the stopped nodes after the restart, node states 4, no boot error B), and add a simulator test for power off across a session restart.
- Docs: `docs/config.md` (Mandatory nodes, `stop_all_nodes`) and `docs/simulator.md` (power off).
- Hardware: repeat 9.1 on the Pi.
