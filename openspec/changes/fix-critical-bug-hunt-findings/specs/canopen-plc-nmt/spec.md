## ADDED Requirements

### Requirement: Program NMT state lasts across bus restarts
A program start, a program stop with its node command, node holds and the NMT command counters already acted on SHALL last for the PLC run, not for one bus session. After a bus session restarts during the run (interface down and up, or a session error), the master and every node SHALL be brought back to what the program asked for, and no earlier command SHALL be sent again.

#### Scenario: Stopped network and a link drop
- **WHEN** the program ran `CO_NETWORK_STOP` with `NODE_COMMAND := 2`, and the CAN interface goes down and comes back
- **THEN** the master stays PRE-OPERATIONAL, each node is configured and sent STOP, and no output PDO is sent

#### Scenario: Started network and a link drop
- **WHEN** `master.start` is false, the program ran `CO_NETWORK_START`, and the CAN interface goes down and comes back
- **THEN** the master goes OPERATIONAL again once the mandatory nodes have booted

#### Scenario: Held node and a link drop
- **WHEN** the program held node 5 STOPPED with `CO_NMT` and the interface goes down and comes back
- **THEN** node 5 is configured and sent STOP, and the other nodes are started

#### Scenario: Reset command before the drop
- **WHEN** the program's command byte for node 5 asked for RESET NODE earlier in the run and the interface goes down and comes back
- **THEN** node 5 gets no RESET NODE because of that earlier command
