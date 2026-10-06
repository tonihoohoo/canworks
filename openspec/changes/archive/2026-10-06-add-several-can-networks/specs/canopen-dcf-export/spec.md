# Spec Delta

## ADDED Requirements

### Requirement: DCF files per network
With several networks, the export of all nodes SHALL write each network's DCF files into a folder named after the network (`<network>/node_<id>.dcf`), and a `--network NAME` option SHALL limit the export to one network, written without the folder. With one network, file names and places SHALL stay as they are. The DCF's commissioning bit rate SHALL be its own network's.

#### Scenario: Two networks
- **WHEN** a config has node 2 on `io` (125 kbit/s) and node 2 on `drives` (500 kbit/s) and the user exports all to `out/`
- **THEN** `out/io/node_2.dcf` and `out/drives/node_2.dcf` are written, with 125 and 500 kbit/s in their commissioning sections

#### Scenario: One network of two
- **WHEN** the user exports with `--network drives` to `out/`
- **THEN** only `out/node_2.dcf` from `drives` is written
