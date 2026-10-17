## ADDED Requirements

### Requirement: Raw signal length errors
An empty or invalid raw signal length SHALL be reported as a field problem; the check SHALL NOT fail.

#### Scenario: Cleared length
- **WHEN** the user clears a raw signal's Length
- **THEN** Problems shows the length error and Save is disabled

### Requirement: References follow node and network changes
Changing a node ID SHALL update PDO links and heartbeat watches that name the node. Removing a node SHALL list the links, routes and watches that use it and offer to remove them. Renaming or removing a network SHALL update the Modbus bridge live lists.

#### Scenario: Node ID change
- **WHEN** a PDO link's producer is node 10 and its ID changes to 11
- **THEN** the link names node 11 and no problem is shown

#### Scenario: Network rename
- **WHEN** the network in a bridge live list is renamed
- **THEN** the live list follows the new name

### Requirement: Quiet status while the runtime is away
While the runtime does not answer, the online status SHALL be reported without an HTTP error on every poll.

#### Scenario: Runtime stopped
- **WHEN** the connected runtime stops answering
- **THEN** the page shows the connection state and the console has no repeated errors
