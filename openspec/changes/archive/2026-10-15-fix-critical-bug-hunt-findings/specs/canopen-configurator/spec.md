## ADDED Requirements

### Requirement: Saving a one-network config with a CiA 309-3 block
The configurator SHALL save a valid version 2 config with one network and a top-level `cia309` block without an error, writing the block where the saved schema version expects it.

#### Scenario: One network with the gateway on
- **WHEN** a version 2 config with one network and `cia309` at the top level is opened and saved without changes
- **THEN** the save succeeds and the saved file passes the check with the gateway settings unchanged
