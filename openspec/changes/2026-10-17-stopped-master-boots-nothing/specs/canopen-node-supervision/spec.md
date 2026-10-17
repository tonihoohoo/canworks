## ADDED Requirements

### Requirement: Node states while the master is stopped
While `stop_all_nodes` holds the master STOPPED for the run, a node's state SHALL read STOPPED (4) after the master's NMT STOP to it, until a heartbeat or boot-up from the node reports another state.

#### Scenario: Link bounce after the stop
- **WHEN** node 10 is mandatory and was lost, `stop_all_nodes` stopped the master and node 23, the CAN interface goes down and up, and node 10 sends its boot-up
- **THEN** the state bytes of nodes 10 and 23 read 4

### Requirement: A stopped master reports no absent nodes
While `stop_all_nodes` holds the master STOPPED for the run, a node that the master does not boot SHALL NOT be reported as not answering, and its boot error SHALL NOT become B. The plugin SHALL log once per bus session that the master boots no node until the plugin restarts, and SHALL NOT log that the master holds the network in PRE-OPERATIONAL.

#### Scenario: Silent log after a link bounce
- **WHEN** `stop_all_nodes` stopped the master and the CAN interface goes down and up
- **THEN** no node has boot error B, the log has no "not answering" or PRE-OPERATIONAL line, and it has one "boots no node" line
