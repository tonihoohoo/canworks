# Proposal: stopped-master-stays-silent

## Why

The hardware checks of fix-extensive-bug-hunt-findings (tasks 9.1 and 9.2, PR #138, plugin from main 1904b8b on the Pi) found two gaps.

9.1: a simulated mandatory node was powered off, and `stop_all_nodes` stopped the master and node 23 as specified. Then slcan0 went down for 3 s and came back. The plugin logged that the master stays STOPPED, but on the bus the new session's Lely start-up went ahead. The master sent its boot-up and `000#8200` (reset communication of every node). Node 23 left STOPPED and was configured over SDO, and SYNC ran again at 100 Hz until the end of the trace. Node 23 was stopped again about a second later, and the master stayed OPERATIONAL. No NMT START and no PDO went out. The cause: `Start` sends STOP before Lely's asynchronous start-up after its reset. That start-up resets the nodes, and once the mandatory node is back the master is started again (`StartHeldMaster` and Lely's own start ignore `master_stopped`).

9.2: with node 23 OPERATIONAL and the Pi's master sending SYNC, `sdo-write` and `nmt stop` from a PC adapter were refused without `--force` and sent nothing. But the message named only the OPERATIONAL node, not the other master the adapter had seen, which the canopen-local-bus spec asks for ("the refusal says which was seen").

## What Changes

- While `stop_all_nodes` holds the master STOPPED, the plugin's send hook passes only what a STOPPED master sends: NMT STOP, its own heartbeat and EMCY, SDO requests and LSS. Lely's reset of nodes, NMT START, SYNC, TIME and PDOs are dropped, with one log line per session.
- The master is not started again in that run: `StartHeldMaster` checks the stop, and a start or pre-operational entry from Lely's own start-up gets STOP again. The master reports STOPPED.
- The adapter refusal names both when a node was heard OPERATIONAL and another master is active.

No config, schema or PLC API change.

## Capabilities

### Modified Capabilities
- `canopen-plc-nmt`: a stopped master sends no reset, START, SYNC, TIME or PDO in later sessions of the run.
- `canopen-local-bus`: the refusal names every reason seen.

## Impact

- Code: `plugin/src/canopen/network.cpp` and `.h` (send hook, `HandleCommand`, `StartHeldMaster`, `ApplyMasterState`), `tools/deploy/canworks/localbus/client.py` (`_check_force`).
- Tests: `sim_stop_all_nodes_restart_node_back_in_session` (fails on main: reset of all nodes sent), `test_running_node_and_other_master_both_named`.
- Hardware: repeat 9.1 and 9.2 on the Pi.
