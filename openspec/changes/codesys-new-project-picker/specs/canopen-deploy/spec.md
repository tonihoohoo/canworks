## MODIFIED Requirements

### Requirement: Import into a CODESYS project from the command line
`canworks-deploy --config FILE --codesys-import [PROJECT]` SHALL write the CODESYS export (into `--codesys-dir DIR` when given, else a temporary folder removed after a run without errors), set the plan to open PROJECT, else the config's `codesys.project`, or to create it when `--codesys-new TYPE:ID:VERSION` or `codesys.create` gives the PLC device, run CODESYS headless on the script, print the script's report, and exit non-zero when the report has an error. A project path without an extension SHALL get `.project` before it is opened or created. With no project given and none in the config it SHALL exit non-zero saying so.

#### Scenario: Existing project
- **WHEN** `canworks-deploy --config canworks.json --codesys-import "C:\Projects\Line 2\cell.project"` runs on a PC with CODESYS installed
- **THEN** CODESYS runs headless, the project gets the bus and is saved, and the report is printed

#### Scenario: Project from the config
- **WHEN** the config has `codesys.project` `C:\Projects\cell.project` and `canworks-deploy --config canworks.json --codesys-import` runs
- **THEN** that project gets the bus

#### Scenario: Project without extension
- **WHEN** the config has `codesys.project` `C:\Projects\cell` and `codesys.create` set, and no `C:\Projects\cell.project` exists
- **THEN** CODESYS creates `C:\Projects\cell.project`

#### Scenario: No project anywhere
- **WHEN** `--codesys-import` is given without a project and the config has no `codesys.project`
- **THEN** the tool exits non-zero saying which project to give, and runs no CODESYS
