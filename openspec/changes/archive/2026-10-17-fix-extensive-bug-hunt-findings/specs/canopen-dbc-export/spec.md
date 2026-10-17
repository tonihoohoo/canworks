## ADDED Requirements

### Requirement: EMCY identifier from the EDS
The DBC export SHALL use a node's EMCY COB-ID as the plugin listens on it, including the EDS default.

#### Scenario: Moved EMCY in the EDS
- **WHEN** the EDS sets 0x1014 to 0x0C2 for node 2
- **THEN** the DBC's EMCY message for node 2 uses 0x0C2
