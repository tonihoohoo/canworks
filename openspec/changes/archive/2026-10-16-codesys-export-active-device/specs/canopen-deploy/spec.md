## MODIFIED Requirements

### Requirement: CODESYS export options
With the CODESYS export the deploy tool SHALL accept `--network NAME` (one network), `--codesys-net NAME=N` (repeatable, a network's CODESYS network number), `--codesys-plc NAME` (the device to use instead of the project's active application's device), `--codesys-can NETWORK=OBJECT` (repeatable, the CAN interface object in that device that gets the network's bus) and `--codesys-no-variables`. A name that matches no network SHALL fail with a message naming it.

#### Scenario: Unknown network in an override
- **WHEN** `--codesys-net drives=1` names no network in the config
- **THEN** the tool exits non-zero naming `drives` and writes nothing

#### Scenario: Device override
- **WHEN** `--codesys-plc PLC` is given with `--export-codesys out`
- **THEN** the plan's `plc` is `PLC`

#### Scenario: CAN interface override
- **WHEN** `--codesys-can field=CAN2` is given with `--export-codesys out`
- **THEN** the plan's `field` network has interface `CAN2`
