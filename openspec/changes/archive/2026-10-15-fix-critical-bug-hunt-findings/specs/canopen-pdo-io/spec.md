## ADDED Requirements

### Requirement: Master outputs after a master NMT reset
When the master resets itself (for example after a mandatory node's loss with `reset_all_nodes`), every master TPDO SHALL be switched off again as at network start, and a node's outputs SHALL only be sent again through the node-up path, with the program's current values and subject to the outputs gate and a program stop. No DCF default or zero value SHALL be sent in place of the program's outputs.

#### Scenario: Mandatory node lost with reset_all_nodes
- **WHEN** node 3 is mandatory, `reset_all_nodes` is set, the program holds node 5's controlword at 0x000F, and node 3 is lost
- **THEN** no RPDO with controlword 0 reaches node 5; node 5's next RPDO carries 0x000F after it is up again

### Requirement: Scan watchdog across bus restarts
The scan watchdog SHALL keep watching the same scan counter across a bus session restart: a scan that was hung before the restart SHALL keep the outputs gate closed after it.

#### Scenario: Hung scan and a link drop
- **WHEN** the scan has stopped advancing, the outputs gate is closed, and the interface goes down and comes back
- **THEN** the outputs gate stays closed and no node gets output PDOs until the scan advances
