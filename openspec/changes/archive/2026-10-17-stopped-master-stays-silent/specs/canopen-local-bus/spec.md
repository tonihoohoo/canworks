## ADDED Requirements

### Requirement: The refusal names every reason seen
When an adapter refuses a change because the target node was heard OPERATIONAL and another master is also active, the refusal SHALL name both.

#### Scenario: Node running under a PLC master
- **WHEN** node 5 is heard OPERATIONAL, another master sends SYNC, and `nmt stop` to node 5 is run without `--force`
- **THEN** the refusal starts "node 5 is OPERATIONAL; another master is active on this bus (SYNC, last at …)"
