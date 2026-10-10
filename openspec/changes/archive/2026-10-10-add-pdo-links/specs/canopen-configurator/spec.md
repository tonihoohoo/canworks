## ADDED Requirements

### Requirement: Links table
Each CANopen master network SHALL have a Links page with one row per link: name, producer (node and one of its configured TPDOs, picked from lists), COB-ID (shown, taken from the producer), consumers, and on PLC stop (follow or keep). Adding a consumer SHALL offer the consumer node's RPDOs from its EDS that are not in its `rx_pdos` or another link, and SHALL fill its entries from the producer layout: objects of matching size from the consumer's RPDO-mappable objects to pick per position, or a dummy entry, or the device mapping when the consumer's mapping is fixed. The page SHALL show both layouts side by side as byte grids with each position's status. Each consumer row SHALL have a "watch producer" checkbox that adds or removes the producer in the consumer's `heartbeat_watch`, ticked by default when the producer has a heartbeat. On the producer's TPDO settings the configurator SHALL show which link it feeds and allow its entries without a PLC address.

#### Scenario: Add a link
- **WHEN** the user adds a link from node 10 TPDO 1 to node 20, picks RPDO 2 and 0x6411:1 for the first position and a dummy for the second
- **THEN** the saved config has the link with those entries, and node 20's `heartbeat_watch` lists node 10

#### Scenario: Size mismatch shown
- **WHEN** the user picks an 8-bit object for a 16-bit producer position
- **THEN** the position is marked, Problems names the link, the consumer and both sizes, and Save is disabled

#### Scenario: Producer removed
- **WHEN** the user deletes node 10's TPDO 1 that a link uses
- **THEN** the configurator asks to delete the link too, defaulting to cancel

### Requirement: Heartbeat watch setting
The node page's supervision section SHALL list the node's heartbeat watch entries (watched node from the network's nodes, timeout with the default shown when empty), and the check SHALL give the same messages as the plugin for them, including the 0x1016 capacity from the node's EDS.

#### Scenario: Default timeout shown
- **WHEN** node 20 watches node 10, which has `heartbeat_ms` 100, and the timeout field is empty
- **THEN** the field shows "default (300 ms)" and the saved entry has no `timeout_ms`

### Requirement: Links in the online view
With online access the Links page SHALL show for each link the NMT state of its producer and of each consumer from the live status, mark a link whose producer or any consumer is not OPERATIONAL, and show the producer TPDO's timeout state when it has `timeout_ms`.

#### Scenario: Consumer down
- **WHEN** the online view is open and node 20 of a link is lost
- **THEN** the link row is marked and node 20's cell shows no contact while node 10 stays OPERATIONAL
