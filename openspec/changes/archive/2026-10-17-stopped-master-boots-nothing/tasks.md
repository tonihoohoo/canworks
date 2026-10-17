# Tasks

## 1. No boot while stopped

- [x] 1.1 Extend `sim_stop_all_nodes_restart_node_back_in_session`: after the restart and the mandatory node's boot-up, no SDO request to any node within 5 s (only NMT STOP, the master's heartbeat and boot-ups). Fails on main (`60A#40 00 10 00` every second).
- [x] 1.2 Clear 0x1F81 bit 2 for every slave while `master_stopped`. Lely reads it at each boot attempt; it is cleared in the reset communication indication (after the DCF restore) and when the stop begins.

## 2. States and messages

- [x] 2.1 Test: after the restart, every node's state byte reads 4, no boot error B, no "not answering" or PRE-OPERATIONAL log line, and one "boots no node" line.
- [x] 2.2 Set the nodes STOPPED on the master's STOP to every node; skip the absent check while the stop holds; log the PRE-OPERATIONAL message only when the master is not stopped.

## 3. Simulated power off across sessions

- [x] 3.1 Simulator test: power off a simulated node and restart the bus session. The node sends nothing until `power on`, `clear` also powers it on, and a PLC restart starts it powered on (a new set per PLC run in `load_sim`).
- [x] 3.2 Keep the power state in the per-run simulator state.

## 4. Docs and release

- [x] 4.1 `docs/config.md` (`stop_all_nodes`, Mandatory nodes) and `docs/simulator.md` (power off lasts across a link bounce). README if user-visible wording changes.
- [x] 4.2 Release notes (generated from the PR by scripts/release_notes.py); tools version 0.81.2.

## 5. Hardware

- [x] 5.1 Repeat 9.1 on the Pi: simulated mandatory node powered off, slcan0 down and up. After the bounce the trace shows only NMT STOP and the master's heartbeat (no SDO, reset, START, SYNC, TIME or PDO), and the simulated node stays silent. Status shows the master and both nodes STOPPED, with no boot error B. Then `sim clear 10 all`: node 10 sends its boot-up and gets NMT STOP with no boot SDO, and nothing else changes. Clean PLC start afterwards. Passed 2026-10-17 on the Pi (plugin a98afb85, tools 0.81.2): after the bounce only NMT STOP, the master boot-up and heartbeats; no SDO, SYNC, TIME, PDO, reset or START; node 10 stayed powered off, then after `sim clear` sent its boot-up and got STOP; master and both nodes STOPPED, no boot error B; "boots no node" logged once.
