## ADDED Requirements

### Requirement: Linked PDOs between simulated devices
Simulated devices SHALL receive each other's PDOs on the simulated bus as real devices do, so a link whose producer and consumers are simulated SHALL carry data once the master has configured them. An object that a link consumer's RPDO writes SHALL count as written by the bus: a value source on it SHALL be refused naming the link, and expressions MAY read it. A simulated consumer with a heartbeat watch SHALL detect its producer's heartbeat stop or power off and react with its EDS error behaviour and EMCY 0x8130, as the device stack does for any heartbeat consumer.

#### Scenario: Value passes from producer to consumer
- **WHEN** simulated node 10 has a counter on its linked TPDO object, simulated node 20 consumes it on RPDO 2, and node 20's TPDO 1 object has the expression `[0x6411:1]`
- **THEN** the PLC reads the counter both from node 10's TPDO (when located) and, one PDO later, from node 20's TPDO 1

#### Scenario: Value source on a linked object
- **WHEN** the simulation file gives node 20's 0x6411:1 a sine
- **THEN** the source is refused, naming the link that writes 0x6411:1

#### Scenario: Producer powered off
- **WHEN** simulated node 20 watches node 10 and node 10 is powered off
- **THEN** node 20 sends EMCY 0x8130 within its watch timeout and enters the state its 0x1029 sub 1 gives
