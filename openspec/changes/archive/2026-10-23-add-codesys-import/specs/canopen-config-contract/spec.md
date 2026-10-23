## ADDED Requirements

### Requirement: CODESYS settings on nodes, PDOs, entries and startup SDOs
The version 2 schema SHALL allow an optional `codesys` object on a node (`device`: the CODESYS object name; `checks`: a list of `vendor`, `product`, `revision`), on a PDO (`by_manager`: boolean), on a PDO entry (`address`: an IEC address such as `%IB40`) and on a startup SDO (`abort_on_error`: boolean; `jump_to_line`: integer), and on a master network `managed` (the node IDs the CODESYS build manages). The relevance table SHALL mark them as used by CODESYS only.

#### Scenario: Imported config validates
- **WHEN** a CODESYS config has a node with `"codesys": {"device": "Valve_1", "checks": ["vendor"]}` and an entry with `"codesys": {"address": "%QW20"}`
- **THEN** it validates and the check gives no warning

#### Scenario: Bridge config with CODESYS settings
- **WHEN** a bridge config has a node with `"codesys": {"checks": ["vendor"]}`
- **THEN** the check warns that the bridge does not use it, naming its path
