## MODIFIED Requirements

### Requirement: PLCopen export tests
The PLCopen export SHALL be tested in the existing tools test shard, selected by the path rules in `.github/ci/plcopen-paths.txt` (the PLCopen writer and targets, the copy programs, the library, the PLCopen tests and their data): golden files for the `generic` target, a check of each written file against the PLCopen TC6 schema, the refusal of `--for codesys`, and an import-and-compile check of the generic output, with the whole library and all mailboxes, by a pinned truST release binary (version and SHA-256 in one file). Where the binary can't be fetched, the compile check SHALL skip with a message. No new pull request job SHALL be added.

#### Scenario: Export code change
- **WHEN** a pull request changes only `tools/deploy/canworks/plcopen.py`
- **THEN** the tools shard runs the PLCopen tests including the compile check, and the job list is the same as before

#### Scenario: Unrelated change
- **WHEN** a pull request changes only `plugin/src/canopen/network.cpp`
- **THEN** the truST binary is not fetched
