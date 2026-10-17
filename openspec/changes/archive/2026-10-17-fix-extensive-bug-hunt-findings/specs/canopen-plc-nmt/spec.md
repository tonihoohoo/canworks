## ADDED Requirements

### Requirement: Master stop by stop_all_nodes lasts for the run
When a lost mandatory node with `stop_all_nodes` stops the master and every node, that stop SHALL last until the PLC restarts, also across bus session restarts.

#### Scenario: Link bounce after the stop
- **WHEN** the master is STOPPED by `stop_all_nodes` and the CAN interface goes down and up
- **THEN** the master and the nodes stay STOPPED and no output PDO is sent

### Requirement: Network stop survives resets and gateway release
While `CO_NETWORK_STOP` is in force, a node that is reset or released by the gateway SHALL get the network stop's command after it boots, never NMT START.

#### Scenario: Reset during the stop
- **WHEN** the program ran `CO_NETWORK_STOP` with `NODE_COMMAND := 2` and then resets node 2
- **THEN** node 2 is configured and sent STOP

#### Scenario: Upper master back during the stop
- **WHEN** a gateway-held node is released while `CO_NETWORK_STOP` is in force
- **THEN** the node gets the network stop's command, not START

### Requirement: Gateway hold on every NMT path
A node held by the gateway's `stop_nodes` SHALL be refused the same way by `CO_NMT`, the command byte, operator and CiA 309-3 NMT and resets while the upper master is lost; diagnostics with `force` MAY override it. A held node that boots OPERATIONAL SHALL NOT be set up as running.

#### Scenario: Command byte start while held
- **WHEN** the upper master is lost and the program's command byte asks node 5 to start
- **THEN** node 5 stays STOPPED
