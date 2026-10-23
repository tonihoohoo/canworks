## MODIFIED Requirements

### Requirement: Tests selected by protocol area
The change classification SHALL put each changed code file in the area `canopen`, `j1939` or `shared` by path rules kept in one file (`.github/ci/areas.txt`). Tests that exercise only one protocol SHALL run when their area or `shared` changed; every push to `main`, every workflow change and every unknown base SHALL run all areas. Adding J1939 tests SHALL NOT add a CI job, and the wall time of a full run SHALL NOT exceed the median of the last 5 green `main` runs before this change.

#### Scenario: CANopen-only change
- **WHEN** a pull request changes only `plugin/src/canopen/network.cpp`
- **THEN** the J1939 test steps report as skipped and all CANopen tests run

#### Scenario: J1939-only change
- **WHEN** a pull request changes only `plugin/src/j1939/j1939_network.cpp`
- **THEN** the J1939 tests run and the CANopen-only vcan and simulation tests report as skipped

#### Scenario: Push to main
- **WHEN** a J1939-only pull request merges to `main`
- **THEN** the run on `main` runs every area

### Requirement: OpenPLC through Modbus integration test
CI SHALL run the pinned runtime release's own Modbus master plugin (`core/src/drivers/plugins/python/modbus_master`, on an in-memory process image) against `canworks-bridge` running the shipped bridge example with an OpenPLC connection added and its simulated CANopen nodes, polling with the `conf/modbus_master.json` the editor's Build makes from the generated remote device. It SHALL check the map hash and status coming in, an output reaching a node and coming back as its input, an SDO read through the SDO registers, that a PLC stop as the runtime does it (outputs zeroed for one more round, then the master stops) with `on_client_loss: "hold"` keeps the last values from before the stop, and that a program with another map hash leaves outputs off. CI SHALL also run the generated `canworks_in` and `canworks_out` programs and the library's blocks on STruC++ against a bridge register model. Both SHALL run in the CI job that builds the bridge, adding under 30 s to it.

#### Scenario: Stop holds the real values
- **WHEN** the program drove an RPDO value to 0x5A and the PLC stops, writing one round of zeroed outputs
- **THEN** the simulated node keeps receiving 0x5A, never 0

### Requirement: PLCopen export tests
The PLCopen export SHALL be tested in the existing tools test shard, selected by the path rules in `.github/ci/plcopen-paths.txt` (the PLCopen writer and targets, the copy programs, the library, the PLCopen tests and their data): golden files for the two targets (`trust`, `generic`), a check of each written file against the PLCopen TC6 schema, the refusal of `--for codesys`, and an import-and-compile check of the truST output with a pinned truST release binary (version and SHA-256 in one file). Where the binary can't be fetched, the truST check SHALL skip with a message. No new pull request job SHALL be added.

#### Scenario: Export code change
- **WHEN** a pull request changes only `tools/deploy/canworks/plcopen.py`
- **THEN** the tools shard runs the PLCopen tests including the truST import, and the job list is the same as before

#### Scenario: Unrelated change
- **WHEN** a pull request changes only `plugin/src/canopen/network.cpp`
- **THEN** the truST binary is not fetched
