## MODIFIED Requirements

### Requirement: Node-RED flow tests
The Node-RED tests SHALL run in the existing tools test shard and SHALL skip with a message where `node` is missing: the golden flow of the example configs, the package's `node --test` suite (built-in runner, a minimal Node-RED stub, a scripted model of the bridge's registers in place of the Modbus client, no npm packages), the value codec against images packed in Python, the generated layout check and the package `.tgz` contents. The engine job, which already builds the bridge and runs it with simulated nodes, SHALL also run the package's nodes on the minimal stub against it (`test/nodered/run.py`) for values in and out, short and long SDO reads, NMT, a CAN receive with acknowledgement, a cyclic job start and stop, and a bridge restart. No Node-RED installation and no new pull request job SHALL be added, and the PR SHALL report the CI time against the baseline.

#### Scenario: No new job
- **WHEN** a pull request changes only `tools/deploy/canworks/nodered_package/nodes/canworks.js`
- **THEN** the package tests run in the existing tools shard and the pull request's job list is the same as before

#### Scenario: Restart baseline against the real bridge
- **WHEN** the engine job's run restarts the bridge after a CAN send whose request is still in its holding registers, and the bridge node reconnects
- **THEN** no frame goes out and the client's next send ends done
