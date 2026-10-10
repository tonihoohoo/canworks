## 1. Lely behaviour checks (simulation, gate for 2-3)

- [x] 1.1 Sim test (`test/sim/sim_tests.cpp`): a `master.start: false` network with two nodes; send an NMT START with node ID 0 and one with the master's node ID onto the virtual bus from a second CAN socket; confirm the master's state byte stays 127 (records the "nothing starts it today" finding)
- [x] 1.2 Sim test: `Command(ENTER_PREOP, 0)` from the master: does Lely also change the master's own state? If yes, send the broadcast through the bus's raw send path instead (design open question 2); record the result in design.md
- [x] 1.3 Sim test: RESET NODE of a mandatory node from `ApplyNmtCommand` with `stop_all_nodes` and with `reset_all_nodes`: does Lely report the boot-up as an error control event? Record the result (open question 3) and decide whether the plugin must suppress the reaction
- [x] 1.4 Sim test: `Command(cs, 40)` for a node ID not in 0x1F81: the frame goes out and Lely keeps no state for it
- [x] 1.5 Sim test (found while building 3.4): the master entering PRE-OPERATIONAL makes Lely run its network start-up again (RESET COMMUNICATION to every node); `CO_NETWORK_STOP` therefore holds the master in the plugin (design.md, "Results of the simulation checks")

## 2. Plugin API

- [x] 2.1 `plugin/src/canopen/canopen_plc_nmt_api.h`: request, state and v1 table structs, ERROR_ID 9; `canopen_plc_nmt_api(version)` exported next to `canopen_plc_api`, logging once on an unknown version
- [x] 2.2 `PlcRequests`: 16 NMT slots under the same mutex with the same handle layout, `start_nmt`/`poll_nmt`/`take_nmt(network)`/`finish_nmt`; dropped by `open`/`close`; validation of network, node, command and node command
- [x] 2.3 `PlcRequests`: per-network state snapshot (128 nodes plus master, one atomic word each), `publish_node`/`publish_master`, lock-free `get_state`; cleared by `open`/`close`
- [x] 2.4 Unit tests (`test/unit/unit_tests.cpp`): NMT slots full (error 5), generations after close (error 8), invalid inputs (error 6), unknown version, snapshot packing and clear

## 3. Network

- [x] 3.1 `ServiceProgram` takes NMT requests before SDO requests; one node-command function shared by `CO_NMT` and `OperatorNmt`, with the source in the log; `NODE := 0` per task 1.2's result; unlisted nodes get the command only; START refused with 9 on a gateway-held node
- [x] 3.2 Publish to the snapshot from `SetState`, `SetMasterState`, `SetBootError`, `SendHold`, `ResetNode` and every hold change, including the command byte's
- [x] 3.3 `prog_start_` / `prog_stopped_` flags; `StartHeldMaster` gate `(start || prog_start_) && !prog_stopped_`; `CO_NETWORK_START` ends when the master is OPERATIONAL, keeps the request after its TIMEOUT, refuses a master STOPPED by `stop_all_nodes` with 9; restart of nodes held only by the network stop
- [x] 3.4 `CO_NETWORK_STOP`: TPDOs off, master ENTER PRE-OPERATIONAL, node command (0 from `on_plc_stop`, 2, 128, 255) to every up node and to nodes that boot meanwhile; supervision and retries keep running
- [x] 3.5 Mandatory nodes: a program hold or reset is not a loss (per task 1.3)
- [x] 3.6 Config load warning for `start: false` names `CO_NETWORK_START` (`plugin/src/can/config.cpp`)

## 4. Library

- [x] 4.1 `library/src/nmt_common.inc` (entry point lookup, request and state structs, no pin names) and the four blocks in `library/generate.py`, reusing `common.inc`'s handshake helpers; `--check` stays green
- [x] 4.2 Rebuild `canworks.stlib` (`library/build.sh`) and update the committed copy in the deploy package; bump the deploy package version
- [x] 4.3 Block test glue: a `CO_NMT_TEST_ENTRY` define like `CO_SDO_TEST_ENTRY` so `test/CMakeLists.txt` links the blocks against the in-process table
- [x] 4.4 Sim test `sim_plc_nmt_blocks` with the real blocks: stop/pre-op/start of a configured node and its state byte, hold after a power cycle, reset of an unlisted node, `NODE := 0`, byte vs block last-wins both ways, mandatory node reset with `stop_all_nodes`, `start: false` plus `CO_NETWORK_START` (with and without a missing mandatory node, TIMEOUT), `CO_NETWORK_STOP` with each node command and a node booting meanwhile, SDO read while stopped, `CO_GET_STATE` for master, configured and unlisted nodes, 17 commands at once, PLC stop while `BUSY`, holds gone after a PLC restart, NMT entry point missing (error 4 while SDO blocks work)
- [x] 4.5 Extend `plc_sdo_lookup` (`test/plc_sdo/lookup_check.cpp`) to find `canopen_plc_nmt_api` in a process that loaded the real plugin `RTLD_LOCAL`

## 5. Configurator

- [x] 5.1 Online view: "Copy as ST call" next to the NMT buttons (`CO_NMT` call, command name comment, network number and name with several networks), enabled without `allow_changes`
- [x] 5.2 Advanced master settings: corrected "Master goes operational" hint and a `CO_NETWORK_START` copy link
- [x] 5.3 Page tests for both (`tools/deploy/tests/`)

## 6. Docs

- [x] 6.1 New `docs/plc-nmt.md`: the four blocks, examples (autostart-off pattern, stop and restart a node, reset every node, state read), hold rules with the command byte and operator commands, mandatory nodes, PLC stop, error IDs
- [x] 6.2 `docs/config.md`: `start` row ("until the PLC program starts it with `CO_NETWORK_START`"), "NMT commands from the program" points to the blocks and the shared hold, `on_plc_stop` row mentions `CO_NETWORK_STOP`
- [x] 6.3 `docs/plc-sdo.md` (library block list, error ID 9 for the NMT family), `docs/configurator.md` (Copy as ST call for NMT), `README.md` ("From the program" line and the docs table)

## 7. CI

- [x] 7.1 Run `sim_plc_nmt_blocks`, the unit tests and the extended lookup check in the plugin job; `openspec validate --all --strict` passes

## 8. Hardware check (Pi bench, separate from CI)

- [x] 8.1 Build the library with the editor's compiler, install it in OpenPLC Editor 4.3.2, build a project calling all four blocks for OpenPLC Runtime v4 and run it on the Pi runtime (Docker)
- [x] 8.2 With real nodes: `start: false` plus `CO_NETWORK_START` (PDOs flow, state bytes and status bits), `CO_NETWORK_STOP` with node command 0 and 2, `CO_NMT` stop/pre-op/start/reset of a configured node, a broadcast pre-op, a reset of a node ID the config does not list
- [x] 8.3 Power-cycle a held node; unplug a mandatory node while the network is started from the program; stop the PLC while a `CO_NETWORK_START` is `BUSY`; check scan timing stays on time throughout
- [x] 8.4 Record the results (what passed, what was changed after) in design.md; resolve or carry over the open questions

Run on 2026-10-10 on the Pi bench (managed Docker runtime, main at 0a8ca26, tools 0.56.0) with its one real CANopen I/O node (node 23, 500 kbit/s). That node has no 0x1003, 0x1014, 0x1016 or 0x1029, so where a step needs them or a second device, simulated devices ran on the same real can0 bus next to it (the plugin's `simulate: true` nodes, or a standalone `canworks-sim --real-bus` in the runtime container).
- 8.1: the library 0.56.0 installed into the editor by `canworks-deploy --new-project ... --blocks`, a project with all
  four blocks and `CO_RECV_EMCY` compiled with the editor's `openplc-cli compile` for OpenPLC Runtime v4 and run on
  the Pi runtime. Commands came from a simulated device on a second, simulated network, results went to two others.
- 8.2: on the real node: `CO_NMT` stop (state 4, held 2), pre-op (127, held 128), start (5, held 0), reset node and
  reset communication (back OPERATIONAL); broadcast pre-op and start (every node, master unchanged); reset of node
  99, not in the config (sent, nothing kept); `NODE` = master ID answered `ERROR_ID` 6. `CO_NETWORK_STOP` with node
  command 0 (master and nodes 127, held 128) and 2 (nodes 4), `CO_NETWORK_START` after each (all 5 again).
  `start: false`: master 127, nodes booted, status bits FALSE, no RPDO from the master; `CO_NETWORK_START` DONE,
  master 5, status bits TRUE.
- 8.3: real node held STOPPED, then power-cycled: lost, booted, configured and held STOPPED again, master stayed
  OPERATIONAL. Real node mandatory, network started with `CO_NETWORK_START`, unplugged 10 s: lost and booted again
  when plugged back, master stayed OPERATIONAL. A mandatory node that never answers kept `CO_NETWORK_START` BUSY;
  a PLC stop (upload) during it stopped cleanly and the next start ran. SYNC interval stayed within 9.8-10.2 ms in
  steady state and the scan count matched the 10 ms task.
- One false alarm on the way: a test program read its command byte from a simulated CiA 401 device whose outputs
  carried the results; the simulated device copies outputs to inputs, so a DONE written back became the next
  command (`CO_NETWORK_START` right after every stop). Fixed in the test program (results on other devices); no
  change in the plugin or the blocks.
