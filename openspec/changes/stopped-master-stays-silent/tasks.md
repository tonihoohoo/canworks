# Tasks

## 1. Stopped master

- [x] 1.1 `sim_stop_all_nodes_restart_node_back_in_session`: mandatory node lost, session restart, node back during the session. No reset of all nodes, no SYNC, no START; master STOPPED. Fails on main.
- [x] 1.2 Send hook allow list while `master_stopped`; `StartHeldMaster` and `HandleCommand` keep the master STOPPED; `master_op_` false.

## 2. Adapter refusal

- [x] 2.1 `test_running_node_and_other_master_both_named`; `_check_force` names the other master with the OPERATIONAL node.

## 3. Hardware

- [ ] 3.1 Repeat 9.1 on the Pi: simulated mandatory node powered off, slcan0 down and up. No `000#82..`, no SYNC, no START, no PDO in the trace; the master and node 23 stay STOPPED. Clean PLC start afterwards.
- [ ] 3.2 Repeat 9.2: the refusal names node 23 OPERATIONAL and the other master.
