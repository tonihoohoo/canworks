## MODIFIED Requirements

### Requirement: Uses the project's PLC
The script SHALL put the bus on one device of the project: the device the plan names; else the device that holds the project's active application; else the only top-level device. A project with several devices, no name in the plan and no active application SHALL stop the run with the list of devices and a message saying how to set an active application or name a device, and SHALL change nothing. The script SHALL NOT depend on a particular PLC type or CODESYS install path, and SHALL find the active application's device at any depth in the device tree.

#### Scenario: Two devices, one active
- **WHEN** the project has devices `PLC` and `HMI`, `HMI` holds the active application and the plan names none
- **THEN** the bus is added under `HMI`, `PLC` is unchanged and the report's device line names `HMI` as the active application's device

#### Scenario: Two PLCs
- **WHEN** the project has two devices, neither holds the active application and the plan names none
- **THEN** the script stops, names both, says to set an active application or name a device, and changes nothing

#### Scenario: Named device
- **WHEN** the plan names `PLC` and `HMI` holds the active application
- **THEN** the bus is added under `PLC` and the report warns that the build checked the active application on `HMI`

#### Scenario: One device
- **WHEN** the project has one device and no application
- **THEN** the bus is added under that device

#### Scenario: Nested device
- **WHEN** the active application belongs to a device below the project's top level
- **THEN** the bus is added under that device

### Requirement: Reuses the device's CAN interfaces
For each network the script SHALL use an existing CANbus anywhere under the PLC whose network number equals the plan's, and an existing CANopen Manager under it. Only when none exists SHALL it add one, in the highest version installed in that CODESYS or the version of a CANbus the PLC already has, under the network's CAN interface object: the object the plan names, else the device's only CAN interface object, else the one whose name ends in the network number, else the device itself. When the interface refuses a CANbus, the script SHALL add the CANopen Manager directly under it. It SHALL then set the bit rate and the manager settings from the plan.

#### Scenario: Device that ships its CAN interfaces
- **WHEN** the project's PLC already has CANbus objects with network numbers 0 and 1 and the plan's network has number 1
- **THEN** the script adds the manager and nodes under the existing CANbus with number 1 and adds no CANbus

#### Scenario: Plain PLC
- **WHEN** the PLC has no CANbus
- **THEN** the script adds a CANbus and a CANopen Manager in the highest installed versions and sets network number, bit rate and manager settings

#### Scenario: CODESYS as a slave on that interface
- **WHEN** the matching CANbus holds a CANopen device object instead of a manager
- **THEN** that network stops with a message naming the CANbus, and other networks continue

#### Scenario: CAN interface under Communication
- **WHEN** the device has `Communication/CAN`, refuses a CANbus at its root and has no CANbus
- **THEN** the script adds the CANbus (or, if `CAN` refuses that, the CANopen Manager) under `CAN` and the report names `CAN` as the interface

## ADDED Requirements

### Requirement: Choosing among several CAN interfaces
When the device has several CAN interface objects and the plan names none for a network, the script SHALL use the one whose name ends in the network number; when none or several match, that network SHALL stop with the list of interfaces and the option that names one, and other networks SHALL continue.

#### Scenario: Two interfaces
- **WHEN** the device has `CAN1` and `CAN2`, the network has number 2 and no interface is named
- **THEN** the bus goes under `CAN2`

### Requirement: Nowhere to add the bus
When neither a CANbus nor a CANopen Manager can be added under the chosen interface, the network SHALL stop with an error naming that object, its device type and CODESYS's message, and listing the device's other objects, instead of only CODESYS's exception.

#### Scenario: Refused everywhere
- **WHEN** CODESYS refuses both a CANbus and a manager under the chosen object
- **THEN** the report's error names the object and CODESYS's message and lists the device's objects

### Requirement: Same network on another device
When another top-level device than the chosen one has a CANopen Manager on a CANbus with the same network number as a planned network, the report SHALL warn and name that device, and the script SHALL leave that device unchanged.

#### Scenario: Active device switched between runs
- **WHEN** the script ran with `PLC` active, the user makes `HMI` active and runs it again
- **THEN** `HMI` gets the bus, `PLC` keeps its manager and nodes, and the report warns that `PLC` has a manager on the same network number
