# Tasks

## 1. No boot while stopped

- [ ] 1.1 Extend `sim_stop_all_nodes_restart_node_back_in_session`: after the restart and the mandatory node's boot-up, no SDO request to any node within 5 s (only NMT STOP, the master's heartbeat and boot-ups). Fails on main (`60A#40 00 10 00` every second).
- [ ] 1.2 Clear 0x1F81 bit 2 for every slave in `Start` while `master_stopped`. Check that Lely reads it at start-up and boot-up; otherwise use the fallback in design.md.

## 2. States and messages

- [ ] 2.1 Test: after the restart, every node's state byte reads 4, no boot error B, no "not answering" or PRE-OPERATIONAL log line, and one "boots no node" line.
- [ ] 2.2 Set the nodes STOPPED on the master's STOP to every node; skip the absent check while the stop holds; log the PRE-OPERATIONAL message only when the master is not stopped.

## 3. Simulated power off across sessions

- [ ] 3.1 Simulator test: power off a simulated node and restart the bus session. The node sends nothing until `power on`, `clear` also powers it on, and a PLC restart starts it powered on.
- [ ] 3.2 Keep the power state in the per-run simulator state.

## 4. Docs and release

- [ ] 4.1 `docs/config.md` (`stop_all_nodes`, Mandatory nodes) and `docs/simulator.md` (power off lasts across a link bounce). README if user-visible wording changes.
- [ ] 4.2 Release notes.

## 5. Hardware

- [ ] 5.1 Repeat 9.1 on the Pi: simulated mandatory node powered off, slcan0 down and up. After the bounce the trace shows only NMT STOP and the master's heartbeat (no SDO, reset, START, SYNC, TIME or PDO), and the simulated node stays silent. Status shows the master and both nodes STOPPED, with no boot error B. Then `sim clear 10 all`: node 10 boots, gets STOP, and nothing else changes. Clean PLC start afterwards.
