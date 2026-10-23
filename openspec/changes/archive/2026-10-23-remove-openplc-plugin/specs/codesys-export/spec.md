## REMOVED Requirements

### Requirement: Settings that do not carry over
**Reason**: It described the removed OpenPLC plugin; its scenarios change with the plugin gone.
**Migration**: Requirement: Settings that do not carry over to CODESYS.

## ADDED Requirements

### Requirement: Settings that do not carry over to CODESYS
Every set config value that the relevance table of `canopen-config-contract` marks as not used by CODESYS SHALL be in the plan's `not_carried` list with where it is set and the table's reason, the same text the check's warning gives.

#### Scenario: Bridge-only status location
- **WHEN** node `rtd` has `emcy_code_location` `%IW20`
- **THEN** `not_carried` lists `emcy_code_location` for `field/rtd` with the reason the check gives for it
