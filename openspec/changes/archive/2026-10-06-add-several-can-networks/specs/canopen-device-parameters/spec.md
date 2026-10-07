# Spec Delta

## ADDED Requirements

### Requirement: Parameter commands on a network
`backup`, `compare`, `restore` and `store` SHALL take `--network NAME`, which picks both the network the SDOs go to and the node's EDS and configuration from that network in `--config`. With several networks in the runtime or the config, they SHALL fail without it, naming the networks.

#### Scenario: Back up a node on the second network
- **WHEN** the user runs `backup 2 --network drives` with a config that has node 2 on `io` and on `drives`
- **THEN** the node on `drives` is read, using `drives`' node 2 EDS, and the DCF carries `drives`' bit rate
