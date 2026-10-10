## ADDED Requirements

### Requirement: Diagnostics object in the J1939 config
The `j1939` object MAY have `diagnostics` as described by `j1939-diagnostics`. `schema/canworks.v2.schema.json` SHALL describe it. Its locations SHALL take part in every location check that `rx` and `tx` locations take part in (size, direction, overlap within the config and across networks and plugins). `examples/j1939/canworks.json` SHALL use it with proprietary SPNs (520192..524287) only.

#### Scenario: Diagnostics location clash
- **WHEN** a `diagnostics.rx` `lamps_location` and an `rx` signal both map `%IB221`
- **THEN** the file is rejected naming both paths

#### Scenario: Config without diagnostics
- **WHEN** a J1939 config written before this change is loaded
- **THEN** it loads and runs exactly as before
