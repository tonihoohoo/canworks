## MODIFIED Requirements

### Requirement: Map hash
The bridge SHALL compute a 32-bit map hash of its config as `modbus-bridge-map` defines it, log it at start, and, in a config with `plc_link` true, serve it at input registers 0 (high word) and 1 (low word).

#### Scenario: Hash served
- **WHEN** a bridge config with `plc_link` true and map hash 0x1234ABCD runs and a client reads input registers 0 and 1
- **THEN** it reads 0x1234 and 0xABCD

### Requirement: PLC link on any bridge config
A bridge config SHALL accept `plc_link: true`, the only switch for the PLC link: holding registers 0-2 are the PLC link header (Requirement: PLC link header), input registers 0-1 the map hash and input byte 4 the status block, and a value located in those bytes SHALL be refused. Without `plc_link` a bridge config SHALL have no header and no hash in its image.

#### Scenario: CODESYS client with the header
- **WHEN** a config has `plc_link: true` and a client writes the header with running 1 and the matching hash, then the outputs
- **THEN** the outputs are applied, and a header with another hash leaves outputs off and logs the mismatch once

#### Scenario: Old config
- **WHEN** a bridge config without `plc_link` has a value at holding register 0
- **THEN** it is accepted and applied as a plain output register

## ADDED Requirements

### Requirement: Connections ignored by the bridge
canworks-bridge SHALL accept `bridge.connections` as a list of objects and SHALL NOT read its entries, so a configurator-only field never stops a bridge. Anything else than a list SHALL be refused.

#### Scenario: Unknown kind
- **WHEN** a bridge config has `"connections": [{"kind": "future"}]`
- **THEN** the bridge starts and serves the registers as without it

### Requirement: Removed openplc field
canworks-bridge and the PC check SHALL refuse `bridge.openplc` with one message: the field was removed, OpenPLC is a connection on the Modbus bridge page, and the config must be opened in the configurator to add it.

#### Scenario: Old OpenPLC config
- **WHEN** `canworks-bridge --check-only` runs on a config with `"bridge": {"openplc": {}}`
- **THEN** it exits non-zero with that message, naming `bridge.openplc`

## REMOVED Requirements

### Requirement: OpenPLC section
**Reason**: OpenPLC is a connection (`modbus-connections`); the bridge needs only explicit settings and `plc_link`.
**Migration**: Adding an OpenPLC connection writes `plc_link`, `listen`, `writers`, `watchdog_ms` and `word_order`; the bridge refuses `openplc` (Requirement: Removed openplc field).
