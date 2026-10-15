## ADDED Requirements

### Requirement: Boot count in the status
The status answer SHALL give, for each configured node, `boots`: how many times the node booted successfully since the plugin started. A reset and boot that both happen between two status requests SHALL still show as a higher count, though the node's state and boot result are the same as before.

#### Scenario: Reset between two status requests
- **WHEN** node 6 is OPERATIONAL with `boots` 1, a client resets it and the master boots it again within half a second
- **THEN** the next status answer shows node 6 OPERATIONAL with `boots` 2
