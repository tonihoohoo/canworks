# Tasks

## 1. No boot while stopped

- [x] 1.1 `sim_stop_all_nodes_restart_boots_nothing` (next to `sim_stop_all_nodes_restart_node_back_in_session`): after the restart and the mandatory node's boot-up, no SDO request to any node within 5 s (only NMT STOP, the master's heartbeat and boot-ups). Fails on main: 3 SDO requests since the restart, node 2 state 0, "not answering" logged.
- [x] 1.2 Clear 0x1F81 bit 2 for every slave in `OnCommand` (master STOP, and a reset while the stop holds); put it back when the master leaves STOPPED on a command.

## 2. States and messages

- [x] 2.1 In the same test: after the restart, every node's state byte reads 4, no boot error B, no "not answering" or PRE-OPERATIONAL log line, and one "boots no node" line.
- [x] 2.2 Set the nodes STOPPED on the master's STOP to every node; skip the absent check while the stop holds; log the PRE-OPERATIONAL message only when the master is not stopped.

## 3. Simulated power off across sessions

- [x] 3.1 `sim_simulated_power_off_across_sessions`: power off a simulated node and restart the bus session. The node sends nothing in the new session until `clear` powers it on. (A PLC restart starts it on: `RunState` is new for each run.)
- [x] 3.2 Keep the power state in the per-run simulator state.

## 4. Docs and release

- [x] 4.1 `docs/config.md` (`stop_all_nodes`, Mandatory nodes) and `docs/simulator.md` (power off lasts across a link bounce), and `docs/plc-nmt.md`. README: no change (its line on `stop_all_nodes` stops still holds).
- [x] 4.2 Release notes: none needed (plugin only, no PC tools change; the plugin version comes from git).

## 5. Hardware

- [ ] 5.1 Repeat 9.1 on the Pi: simulated mandatory node powered off, slcan0 down and up. After the bounce the trace shows only NMT STOP and the master's heartbeat (no SDO, reset, START, SYNC, TIME or PDO), and the simulated node stays silent. Status shows the master and both nodes STOPPED, with no boot error B. Then `sim clear 10 all`: node 10 boots, gets STOP, and nothing else changes. Clean PLC start afterwards.
