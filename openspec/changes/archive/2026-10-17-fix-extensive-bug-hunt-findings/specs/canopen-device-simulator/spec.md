## ADDED Requirements

### Requirement: Scenario passes never spin
A scenario pass that ends without waiting SHALL run at most once per simulator tick on CANopen and plain CAN networks alike, and `repeat` without `count` SHALL repeat forever on both.

#### Scenario: Repeat with no wait on plain CAN
- **WHEN** a plain CAN scenario repeats two steps with no `after_ms`
- **THEN** it runs once per tick and the I/O thread stays idle between ticks

### Requirement: SDO faults on mapped objects
`sdo_abort` and `refuse_write_operational` faults SHALL apply to SDO access of an object also when it is mapped into a PDO; PDO access SHALL stay unaffected.

#### Scenario: Abort on a mapped statusword
- **WHEN** an `sdo_abort` fault on read is set on an object in a TPDO
- **THEN** an SDO read of it gets the abort and the TPDO keeps running

### Requirement: Set on a powered-off device
`sim_set` and a scenario `set` on a powered-off device SHALL be refused with a message, and SHALL leave no hold behind.

#### Scenario: Set while off
- **WHEN** node 2 is powered off and `sim_set` writes 0x4001
- **THEN** the command fails with "powered off"

### Requirement: Expressions mean the same everywhere
The PC check and the plugin SHALL accept the same expression spellings (subindex as `0x` hex or decimal, no leading-zero device numbers) and give the same values, including on the first tick.

#### Scenario: Leading-zero device
- **WHEN** an expression uses `[05/0x7130:1]`
- **THEN** the configurator and the plugin both refuse it

#### Scenario: Offline check
- **WHEN** the expression editor checks an expression with no runtime connected
- **THEN** errors are shown

### Requirement: Stored node IDs on a real bus
A simulated device whose stored LSS node ID is in use on the real bus SHALL NOT boot with it, and the device's guard SHALL follow a node ID assigned by LSS.

#### Scenario: Stored ID now taken
- **WHEN** a spare device has stored node ID 70 and a real device answers as 70 during the listen
- **THEN** the simulated device does not boot as 70

### Requirement: Drive reset on NMT reset node
NMT reset node SHALL reset a simulated CiA 402 drive's state as a power-on does.

#### Scenario: Faulted drive reset
- **WHEN** a simulated drive is in Fault and gets RESET NODE
- **THEN** it boots in Switch on disabled
