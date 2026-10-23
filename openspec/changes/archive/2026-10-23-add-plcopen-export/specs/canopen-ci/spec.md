## ADDED Requirements

### Requirement: PLCopen export tests
The PLCopen export SHALL be tested in the existing tools test shard, selected by path (`tools/deploy/canworks/plcopen*.py`, `tools/deploy/canworks/codesys/script/import_canworks_modbus.py`, `library/`): golden files for the three targets, a check of each written file against the PLCopen TC6 schema, the CODESYS script's steps against a fake script engine, and an import-and-compile check of the truST output with a pinned truST release binary (version and SHA-256 in one file). Where the binary can't be fetched, the truST check SHALL skip with a message. No new pull request job SHALL be added.

#### Scenario: Export code change
- **WHEN** a pull request changes only `tools/deploy/canworks/plcopen.py`
- **THEN** the tools shard runs the PLCopen tests including the truST import, and the job list is the same as before

#### Scenario: Unrelated change
- **WHEN** a pull request changes only `plugin/src/canopen/network.cpp`
- **THEN** the truST binary is not fetched
