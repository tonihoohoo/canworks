## ADDED Requirements

### Requirement: PLC link on any bridge config
A bridge config SHALL accept `plc_link: true`. It SHALL give the config the PLC link header of an `openplc` config (holding registers 0-2: running, map hash high and low word, not part of the output image; link states ok, stopped and mismatch with their status byte 0 values) and the bridge's map hash at input registers 0-1, with the same refusals for values located in those registers and the same rule that output writes apply only while the link state is ok. `bridge.openplc` SHALL imply `plc_link`. Without `plc_link`, a non-`openplc` bridge config SHALL behave as before.

#### Scenario: CODESYS client with the header
- **WHEN** a config has `plc_link: true` without `openplc`, and a client writes the header with running 1 and the matching hash, then the outputs
- **THEN** the outputs are applied, and a header with another hash leaves outputs off and logs the mismatch once

#### Scenario: Old config
- **WHEN** a bridge config without `plc_link` and `openplc` has a value at holding register 0
- **THEN** it is accepted and works as before
