## ADDED Requirements

### Requirement: Bridge image timing
The bridge SHALL have no PLC scan. Its loop SHALL publish the input image (with the bridge's own blocks: status, live lists, SDO response) every 1 ms, and each accepted Modbus write SHALL publish the output snapshot to the networks at once. Where a spec of a network kind says "by the next scan" or "at the next scan start" for an input, it SHALL mean within one 1 ms publication. Where it says "the last finished scan" or "the end of each scan" for an output, it SHALL mean the output snapshot of the last accepted write. "The PLC keeps scanning" SHALL mean that the bridge keeps serving Modbus clients. "The PLC scan" that a background service must not delay SHALL mean the bridge's loop and its Modbus server.

#### Scenario: Input published
- **WHEN** a TPDO with a new value arrives
- **THEN** a Modbus read 1 ms later returns the new value

#### Scenario: Output from a write
- **WHEN** a client writes a holding register mapped to an RPDO entry and no SYNC is configured
- **THEN** the master sends the RPDO with the new value within 1 ms of the write, with no wait for a cycle

## MODIFIED Requirements

### Requirement: Bridge installs locked dependency versions
`install-bridge.sh` SHALL take `--constraints FILE` and install the tools into the bridge's venv with it. A release install through `install-bridge.sh` (with or without `--with-openplc`) SHALL fetch and use that release's `canworks-<version>-constraints.txt`. The bridge image SHALL be built with the constraints exported from `uv.lock` of the commit it is built from.

#### Scenario: Bridge image
- **WHEN** the bridge image is built on `main`
- **THEN** its venv holds the dependency versions of that commit's `uv.lock`

### Requirement: PLC link header
In a config with the PLC link (`bridge.plc_link`, set by an OpenPLC connection), holding registers 0-2 SHALL be the PLC link header (running, map hash high word, map hash low word) and not part of the output image. A write covering register 0 SHALL set the link state: ok when running is 1 and the hash equals the bridge's, stopped when running is 0, mismatch otherwise. Stopped SHALL set status byte 0 to 5. Writes to other output registers SHALL be answered normally and applied only while the state is ok. Entering stopped SHALL enter outputs off at once with the `on_client_loss` action, using the output values from before that write. Entering mismatch SHALL enter outputs off, set status byte 0 to 4, and log once naming both hashes. A write with state ok SHALL end outputs off as an accepted write does. Until the first header write the state SHALL be stopped.

#### Scenario: PLC stops
- **WHEN** outputs run with `on_client_loss: "hold"`, then the runtime's stop round writes the header with running 0 followed by all-zero output registers
- **THEN** the outputs keep being sent with the values from before the stop round, and the zeros are not applied

#### Scenario: Program built for another map
- **WHEN** the program writes the header with running 1 and hash 0x11111111 while the bridge's hash is 0x22222222
- **THEN** output writes change nothing, status byte 0 reads 4, and the log names both hashes once

#### Scenario: PLC starts again
- **WHEN** after a stop the header is written with running 1 and the matching hash, followed by the outputs
- **THEN** outputs off ends and the new values are sent
