## MODIFIED Requirements

### Requirement: J1939 in the command-line trace
`canworks-diag trace` and `explain` SHALL use the J1939 decoding for J1939 networks. When the network's DBC cannot be read, including when cantools is not installed, they SHALL warn "decoding without the DBC" with the reason and decode with the config's own messages and signals, never stopping with a traceback.

#### Scenario: Explain a claim
- **WHEN** the user runs `canworks-diag explain 18EEFF80#D204000000820000 --network machine`
- **THEN** the output names Address Claimed from 128 and the NAME fields

#### Scenario: cantools missing
- **WHEN** cantools is not installed and the user runs `canworks-diag explain 18FF0000#0102 --config examples/j1939/canworks.json`
- **THEN** the output warns that it decodes without `machine.dbc` because cantools is not installed, explains the frame as PGN 65280 `Pressures` from the config, and the command exits 0
