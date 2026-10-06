# Spec Delta

## ADDED Requirements

### Requirement: A trace records one network
A trace SHALL record one network, picked in the trace view or by `--network NAME` on the trace command, and SHALL decode its frames with that network's nodes from the config. Saved traces SHALL record the network name with the interface and bit rate.

#### Scenario: Decode with the right nodes
- **WHEN** node 2 is an I/O module on `io` and a drive on `drives`, and the user traces `drives`
- **THEN** node 2's PDOs are decoded with the drive's mapping

#### Scenario: Trace command without a network
- **WHEN** the user runs the trace command without `--network` against two networks
- **THEN** it exits with status 1 naming `io` and `drives`
