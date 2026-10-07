# Spec Delta

## ADDED Requirements

### Requirement: Variable names with several networks
With several networks, every declared variable name SHALL start with its network's name and an underscore, and each variable's description SHALL name the network. With one network, names and descriptions SHALL stay as they are.

#### Scenario: Same node name on two networks
- **WHEN** networks `io` and `drives` each have a node named `door` with a status location
- **THEN** main declares `io_door_ok` and `drives_door_ok`
