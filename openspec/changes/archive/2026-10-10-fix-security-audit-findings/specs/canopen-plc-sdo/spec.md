## ADDED Requirements

### Requirement: Bounded wait for a booting node
A transfer waiting for a node's boot SHALL wait at most its `TIMEOUT` plus the time the master allows a node to answer before reporting it absent. A boot that ends with a boot error SHALL end every transfer waiting for that node with `ERROR_ID` 3 at once. Requests the network side never answers SHALL time out, so they free their slot.

#### Scenario: Node fails its identity check
- **WHEN** the program starts a read from node 5 while node 5 is booting, and node 5's boot fails its identity check
- **THEN** the block ends with `ERROR_ID` 3 when the boot fails, and its slot is free again
