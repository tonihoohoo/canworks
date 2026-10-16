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

## ADDED Requirements

### Requirement: Same network on another device
When another top-level device than the chosen one has a CANopen Manager on a CANbus with the same network number as a planned network, the report SHALL warn and name that device, and the script SHALL leave that device unchanged.

#### Scenario: Active device switched between runs
- **WHEN** the script ran with `PLC` active, the user makes `HMI` active and runs it again
- **THEN** `HMI` gets the bus, `PLC` keeps its manager and nodes, and the report warns that `PLC` has a manager on the same network number
