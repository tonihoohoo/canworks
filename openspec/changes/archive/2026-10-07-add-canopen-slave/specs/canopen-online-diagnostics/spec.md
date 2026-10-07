## ADDED Requirements

### Requirement: Slave network status
For a slave network the diagnostics status SHALL report the role, own node ID, NMT state, communication OK, SYNC count, the PDO mappings the master has set, and the last EMCY sent. Master-only requests (scan, LSS commissioning, node SDO and NMT) SHALL be answered with a message that the network is a slave.

#### Scenario: Online view of a slave
- **WHEN** the configurator's online view opens a slave network the master has started
- **THEN** it shows OPERATIONAL, communication OK and the TPDO and RPDO mappings in force

#### Scenario: Scan on a slave network
- **WHEN** a client asks for a bus scan on a slave network
- **THEN** the answer says scans need a master network

### Requirement: Own dictionary in the object dictionary view
For a slave network the object dictionary view SHALL read the slave's own dictionary locally, without SDO, and SHALL allow writes only with `allow_changes`, to objects the EDS lets the master write.

#### Scenario: Read own object
- **WHEN** the user reads 0x2100:1 in the object dictionary view of a slave network
- **THEN** it shows the value the last scan wrote
