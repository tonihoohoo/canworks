## ADDED Requirements

### Requirement: Import from CODESYS on the command line
`canworks-deploy --from-codesys FILE --out DIR` SHALL import a PLCopenXML file or a CODESYS project (the `codesys-import` capability) into a new config in DIR and print the import report. `--codesys-plc NAME` SHALL choose the device when the source has several, and `--eds-dir DIR` (repeatable) SHALL replace the configurator's EDS library as the place to find EDS files.

#### Scenario: Config already there
- **WHEN** DIR already holds a config and `--force` is not given
- **THEN** it stops and writes nothing

#### Scenario: Node without an EDS
- **WHEN** no EDS is found for node `rtd`
- **THEN** it writes nothing and names `rtd`

#### Scenario: XML file
- **WHEN** `canworks-deploy --from-codesys line2.xml --out line2` runs and every node's EDS is in the library
- **THEN** `line2/canworks.json` and the copied EDS files are written and the report is printed

#### Scenario: Several devices without a choice
- **WHEN** the source has two devices with a manager and no `--codesys-plc` is given
- **THEN** it stops and lists both devices

### Requirement: Removing nodes on the command line
`canworks-deploy --codesys-import` SHALL remove project nodes canworks managed earlier that are no longer in the config only with `--codesys-remove-nodes`, and otherwise SHALL keep them and list them in the report.

#### Scenario: Removed nodes kept by default
- **WHEN** `canworks-deploy --codesys-import` runs on a config whose network's `codesys.managed` has node 7 that is no longer in the config
- **THEN** node 7 stays in the project and the report says it was kept
