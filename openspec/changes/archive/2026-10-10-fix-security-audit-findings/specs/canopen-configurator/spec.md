## ADDED Requirements

### Requirement: Lone-device sweep guarded by the server
The configurator's server SHALL apply the same guards to a lone-device bit rate sweep as `canworks-diag` does on a USB adapter (allow changes on, no other master detected, frames from at most one node ID in the last 30 seconds), whatever the page sends, and SHALL refuse the sweep, sending nothing, when a guard fails.

#### Scenario: Two devices on the bench
- **WHEN** the adapter connection heard heartbeats of nodes 5 and 7 and the page requests a lone-device sweep
- **THEN** the server refuses it saying more than one node is on the bus, and nothing is sent

### Requirement: Changes are never sent twice
When a request to the runtime or the adapter gets no answer in time, the configurator SHALL send it again only for operations that only read. For any other operation it SHALL report that there was no answer and that the request may have been carried out, without sending it again.

#### Scenario: Slow answer to a reset
- **WHEN** the user sends RESET NODE to node 5 and the answer takes longer than the time limit
- **THEN** the configurator says there was no answer and the reset may have happened, and no second reset is sent

### Requirement: Confirm changes to a running node
The online view and the object dictionary view SHALL ask before an SDO write or an NMT command other than START to a node that is OPERATIONAL, naming the node, and SHALL send the request with `force` only after the user confirms.

#### Scenario: Write while running
- **WHEN** node 5 is OPERATIONAL and the user writes 0x2000:1 in the object dictionary view
- **THEN** a dialog says node 5 is running; on confirm the write is sent with `force`, on cancel nothing is sent

### Requirement: Session token never in a URL
The address the configurator opens in the browser SHALL carry a one-time code that the server swaps for its session cookie on first use and then forgets; the session token itself SHALL never be part of a URL.

#### Scenario: Opened link reused
- **WHEN** the start address is opened a second time
- **THEN** the server refuses the code and does not set a session cookie
