## MODIFIED Requirements

### Requirement: Reuses the device's CAN interfaces
For each network the script SHALL use an existing CANbus anywhere under the PLC whose network number equals the plan's, and an existing CANopen Manager under it. Only when none exists SHALL it add one under the network's CAN interface object, trying CANbus devices in this order and keeping the first one CODESYS accepts: the CANbus devices the project already has under an interface with the same device identification as the chosen one, then the project's other CANbus devices, then the CANbus devices installed in that CODESYS in their highest versions, with CODESYS's standard CANbus last. When the interface refuses every CANbus, it SHALL add the CANopen Manager directly under that object. A new manager SHALL use the manager identification found under a CANbus of the same identification in the project, else the version matching the CANbus, else the highest installed. It SHALL then set the bit rate and the manager settings from the plan, and the report SHALL name the added CANbus's id and version and where that choice came from.

#### Scenario: Device that ships its CAN interfaces
- **WHEN** the project's PLC already has CANbus objects with network numbers 0 and 1 and the plan's network has number 1
- **THEN** the script adds the manager and nodes under the existing CANbus with number 1 and adds no CANbus

#### Scenario: Plain PLC
- **WHEN** the PLC has no CANbus and the project and CODESYS have only the standard CANbus
- **THEN** the script adds a CANbus and a CANopen Manager in the highest installed versions and sets network number, bit rate and manager settings

#### Scenario: Interface that takes only its vendor's CANbus
- **WHEN** the active device's `Communication/CAN` has no CANbus, accepts only a vendor CANbus, and another device of the same type in the project has that vendor CANbus
- **THEN** the script adds the vendor CANbus (not the standard one) under `CAN`, a CANopen Manager under it and the nodes, and the report names the vendor CANbus and the device it was taken from

#### Scenario: Vendor CANbus installed but not in the project
- **WHEN** no device in the project has a CANbus and the interface accepts only a vendor CANbus that is installed in CODESYS
- **THEN** the script adds that installed vendor CANbus after the refused tries, which leave nothing in the project

#### Scenario: CODESYS as a slave on that interface
- **WHEN** the matching CANbus holds a CANopen device object instead of a manager
- **THEN** that network stops with a message naming the CANbus, and other networks continue

#### Scenario: CAN interface under Communication
- **WHEN** the device has `Communication/CAN`, refuses a CANbus at its root and has no CANbus
- **THEN** the script adds a CANbus (or, if `CAN` refuses every CANbus, the CANopen Manager) under `CAN` and the report names `CAN` as the interface

### Requirement: Nowhere to add the bus
When neither a CANbus nor a CANopen Manager can be added under the chosen interface, the network SHALL stop with an error naming that object, its device type and CODESYS's message, listing each CANbus device it tried with CODESYS's answer, and listing the device's other objects, instead of only CODESYS's exception.

#### Scenario: Refused everywhere
- **WHEN** CODESYS refuses every CANbus and a manager under the chosen object
- **THEN** the report's error names the object, the CANbus devices tried and CODESYS's messages, and lists the device's objects

### Requirement: Same network on another device
When other top-level devices than the chosen one have a CANopen Manager on a CANbus with the same network number as a planned network, the report SHALL give one warning for that network naming those devices (the first five, then how many more), and the script SHALL leave those devices unchanged.

#### Scenario: Active device switched between runs
- **WHEN** the script ran with `PLC` active, the user makes `HMI` active and runs it again
- **THEN** `HMI` gets the bus, `PLC` keeps its manager and nodes, and the report warns that `PLC` has a manager on the same network number

#### Scenario: Many variant devices
- **WHEN** the project has 23 devices, 22 of them not chosen and each with a CANopen Manager on network number 0
- **THEN** the report has one warning for network number 0 naming five of them and "and 17 more"
