## ADDED Requirements

### Requirement: Forwarder connection limit
The PC forwarders of `canworks-diag gateway --listen` and the link forwarder SHALL accept at most 4 local connections at a time.

#### Scenario: Fifth connection
- **WHEN** four local clients are connected and a fifth connects
- **THEN** the fifth is closed with a message
