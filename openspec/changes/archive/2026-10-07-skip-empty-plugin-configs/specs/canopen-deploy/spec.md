## MODIFIED Requirements

### Requirement: Address clash check across plugins
Before uploading, the deploy tool SHALL collect the IEC locations used by every plugin config in the bundle's `conf/*.json` (CANopen `iec_location` and `status_location`, and `iec_location` fields in other plugins' configs), and compare their ranges. Since each size letter is a separate table in the OpenPLC image, only locations of the same area and size can overlap. Two plugins mapping overlapping input locations (`%I`) SHALL be an error, since both would write the same input. Two plugins mapping overlapping output locations (`%Q`) SHALL be a warning, since both only read it. An `--allow-clash` option SHALL turn the errors into warnings. A plugin config that is empty or holds only whitespace SHALL count as a config with no locations and SHALL be skipped without a warning; a config with other content that is not valid JSON SHALL be reported as a warning saying its locations are not checked.

#### Scenario: Input clash with EtherCAT
- **WHEN** `conf/ethercat.json` maps `%ID100` and `conf/canopen.json` maps `%ID100`
- **THEN** the tool exits non-zero naming both files, both JSON paths, and the overlapping location range, and uploads nothing

#### Scenario: Different sizes do not clash
- **WHEN** `conf/ethercat.json` maps `%IW100` and `conf/canopen.json` maps `%ID100`
- **THEN** the tool reports no clash, since they are different variables

#### Scenario: Output shared with Modbus master
- **WHEN** `conf/modbus_master.json` and `conf/canopen.json` both map `%QW10`
- **THEN** the tool prints a warning naming both entries and continues

#### Scenario: Clash allowed
- **WHEN** the input clash above is deployed with `--allow-clash`
- **THEN** the tool prints it as a warning and uploads

#### Scenario: Empty plugin config from the editor
- **WHEN** the editor's build contains a zero-byte `conf/ethercat.json`
- **THEN** the tool prints nothing about that file and checks the other configs as usual

#### Scenario: Broken plugin config
- **WHEN** `conf/ethercat.json` holds text that is not valid JSON
- **THEN** the tool prints a warning that the file is not readable JSON and its locations are not checked, and continues
