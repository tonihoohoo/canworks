## ADDED Requirements

### Requirement: CODESYS export from the command line
The deploy tool SHALL accept `--export-codesys DIR` as an alternative to `--bundle`, `--project` and `--into-project`. It SHALL run the checks before upload, write the folder `codesys-export` describes into DIR (created if missing, the files it writes replaced), print one line per written file and contact no runtime. On a failed check or DCF validation it SHALL exit non-zero, print every message and write nothing.

#### Scenario: Export
- **WHEN** `canworks-deploy --config canworks/canworks.json --export-codesys out` runs on a valid config with network `field`
- **THEN** it writes `out/field/node_<id>.dcf`, `out/canworks-codesys.json`, `out/import_canworks.py` and `out/README.txt` and exits 0

### Requirement: CODESYS export options
With the CODESYS export the deploy tool SHALL accept `--network NAME` (one network), `--codesys-net NAME=N` (repeatable, a network's CODESYS network number), `--codesys-plc NAME` (the PLC device to use) and `--codesys-no-variables`. A name that matches no network SHALL fail with a message naming it.

#### Scenario: Unknown network in an override
- **WHEN** `--codesys-net drives=1` names no network in the config
- **THEN** the tool exits non-zero naming `drives` and writes nothing

### Requirement: Import into a CODESYS project from the command line
`canworks-deploy --config FILE --codesys-import PROJECT` SHALL write the CODESYS export (into `--codesys-dir DIR` when given, else a temporary folder removed after a run without errors), set the plan to open PROJECT, or to create it when `--codesys-new TYPE:ID:VERSION` gives the PLC device, run CODESYS headless on the script, print the script's report, and exit non-zero when the report has an error.

#### Scenario: Existing project
- **WHEN** `canworks-deploy --config canworks.json --codesys-import "C:\Projects\Line 2\cell.project"` runs on a PC with CODESYS installed
- **THEN** CODESYS runs headless, the project gets the bus and is saved, and the report is printed

### Requirement: Finding CODESYS
For `--codesys-import`, CODESYS SHALL come from `--codesys-exe`, else the newest CODESYS install in the standard program folders, and the profile from `--codesys-profile`, else the newest profile of that install. When none is found the tool SHALL exit non-zero saying so.

#### Scenario: CODESYS missing
- **WHEN** no CODESYS install is found and `--codesys-exe` is not given
- **THEN** the tool exits non-zero saying so, after writing nothing outside the temporary folder
