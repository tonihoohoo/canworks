## ADDED Requirements

### Requirement: Receivers do not leak bridge slots
After a reconnect and after a Deploy, the bridge node SHALL close every receiver slot that the previous connection opened and no current receiver owns, also when no records arrive. A receiver that gets ERROR_ID 5 SHALL try again once after that cleanup.

#### Scenario: Sixteen reconnects
- **WHEN** a flow with two quiet receivers loses and regains its connection 16 times
- **THEN** the bridge has 2 receivers open and both nodes still receive

#### Scenario: Four full Deploys
- **WHEN** a flow with an EMCY receiver and a CAN receiver is fully deployed four times
- **THEN** the bridge has 2 receivers open

### Requirement: Form value wins
A job node with a value set in its form SHALL use that value; `msg.payload` SHALL set the value only when the form leaves it empty.

#### Scenario: Inject triggers an SDO write
- **WHEN** an inject node with its default timestamp payload triggers an SDO write node whose form value is 10
- **THEN** the device gets 10

### Requirement: Cyclic jobs stop on close
Closing a cyclic node, changing it in a Deploy, or a reconnect SHALL stop or take over its job on the bridge, so the frame is never sent twice and a new set never fails for want of the old job's slot.

#### Scenario: Changed cyclic node with one job
- **WHEN** a config has `cyclic_jobs: 1` and a running cyclic node is changed and deployed
- **THEN** the bridge gets a cyclic stop for the old job, the new job starts, and only the new frame goes out

### Requirement: Outputs set during a silent outage
A value given to **canworks out** while the connection is dead but not yet detected SHALL be written to the bridge after the reconnect, not replaced by the bridge's old value.

#### Scenario: Bridge stalled
- **WHEN** the bridge stalls, the flow sets an output to 34, and the bridge then answers again
- **THEN** after the reconnect the bridge holds 34

### Requirement: Jobs end when writes are refused
While the bridge refuses Node-RED's writes, every job SHALL end at once with ERROR_ID 21 and the text "writes refused: add Node-RED's address to the bridge's writers".

#### Scenario: Not a writer
- **WHEN** Node-RED is not in the bridge's writers and an SDO node is triggered
- **THEN** it ends within one poll with ERROR_ID 21 and the writes refused text

### Requirement: Receive fetches go first
A fetch of a long receive record SHALL take the next free request mailbox ahead of waiting SDO, send and request jobs.

#### Scenario: Busy mailbox
- **WHEN** a long J1939 record arrives while an SDO job holds the only request mailbox and another waits
- **THEN** the fetch runs when the SDO job ends, before the waiting job, and the receiver is not closed

### Requirement: Map hash checked at connect
The bridge node SHALL read the bridge's map hash by device identification at connect. When it differs from the flow's, every write and job SHALL be refused with "map mismatch: export the flow again" and the node status SHALL say so. A bridge that does not answer device identification SHALL give a warning only.

#### Scenario: Flow from an older config
- **WHEN** a flow exported before a config change connects to the bridge running the changed config
- **THEN** canworks out writes nothing and the bridge node shows the map mismatch

### Requirement: Node checks
J1939 nodes in a config with no J1939 network SHALL end with ERROR_ID 10; a J1939 receive source SHALL be 0-253; the bridge config node's default port SHALL be 502; REAL outputs SHALL refuse NaN and infinity; mailbox SDO jobs SHALL use the network's SDO timeout from the layout.

#### Scenario: No J1939 network
- **WHEN** a J1939 send node runs against a config without a J1939 network
- **THEN** it ends with ERROR_ID 10 "the config has no J1939 network"
