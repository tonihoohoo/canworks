## ADDED Requirements

### Requirement: Power off lasts across bus sessions
A simulated device that is powered off (by the user, a fault or a scenario) SHALL stay powered off when the bus session restarts, for example after the CAN interface went down and up. It SHALL power on only through `power on`, `clear`, a scenario step or a PLC restart.

#### Scenario: Link bounce while powered off
- **WHEN** simulated node 10 on a real interface is powered off and the interface goes down and up
- **THEN** node 10 sends no boot-up or heartbeat until `sim clear 10 all`, and then boots
