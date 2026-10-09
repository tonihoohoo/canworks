## ADDED Requirements

### Requirement: Bridge tests in existing jobs
The bridge's C++ tests SHALL run on the simulated bus inside the existing plugin test job, using a Modbus TCP client compiled into the tests and no extra package. The map export and Pack for Modbus tests SHALL run in the existing tools test shards. The area classifier SHALL count `plugin/src/bridge/**` and `scripts/install-bridge.sh` as `shared`. No new pull request job SHALL be added, and the container image SHALL be built only by the release workflow. The pull request SHALL state wall time and summed job time against the baseline.

#### Scenario: Bridge source change
- **WHEN** a pull request changes only `plugin/src/bridge/modbus_server.cpp`
- **THEN** the existing pull request jobs run the bridge tests, and no extra job appears
