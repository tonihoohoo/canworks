## MODIFIED Requirements

### Requirement: CODESYS export options
With the CODESYS export the deploy tool SHALL take the plan's settings from the config's `codesys` objects and SHALL accept, overriding them, `--codesys-net NAME=N` (repeatable, a network's CODESYS network number), `--codesys-plc NAME` (the device to use instead of the project's active application's device), `--codesys-can NETWORK=OBJECT` (repeatable, the CAN interface object in that device that gets the network's bus) and `--codesys-no-variables`, and `--network NAME` (one network). A name that matches no network SHALL fail with a message naming it.

#### Scenario: Unknown network in an override
- **WHEN** `--codesys-net drives=1` names no network in the config
- **THEN** the tool exits non-zero naming `drives` and writes nothing

#### Scenario: Device override
- **WHEN** the config has `codesys.device` `HMI` and `--codesys-plc PLC` is given with `--export-codesys out`
- **THEN** the plan's `plc` is `PLC`

#### Scenario: Settings from the config
- **WHEN** the config has `codesys.device` `PLC` and network `field` has `codesys.interface` `CAN2`, and no flag is given
- **THEN** the plan's `plc` is `PLC` and the `field` network has interface `CAN2`

#### Scenario: CAN interface override
- **WHEN** `--codesys-can field=CAN2` is given with `--export-codesys out`
- **THEN** the plan's `field` network has interface `CAN2`

### Requirement: Import into a CODESYS project from the command line
`canworks-deploy --config FILE --codesys-import [PROJECT]` SHALL write the CODESYS export (into `--codesys-dir DIR` when given, else a temporary folder removed after a run without errors), set the plan to open PROJECT, else the config's `codesys.project`, or to create it when `--codesys-new TYPE:ID:VERSION` or `codesys.create` gives the PLC device, run CODESYS headless on the script, print the script's report, and exit non-zero when the report has an error. With no project given and none in the config it SHALL exit non-zero saying so.

#### Scenario: Existing project
- **WHEN** `canworks-deploy --config canworks.json --codesys-import "C:\Projects\Line 2\cell.project"` runs on a PC with CODESYS installed
- **THEN** CODESYS runs headless, the project gets the bus and is saved, and the report is printed

#### Scenario: Project from the config
- **WHEN** the config has `codesys.project` `C:\Projects\cell.project` and `canworks-deploy --config canworks.json --codesys-import` runs
- **THEN** that project gets the bus

#### Scenario: No project anywhere
- **WHEN** `--codesys-import` is given without a project and the config has no `codesys.project`
- **THEN** the tool exits non-zero saying which project to give, and runs no CODESYS
