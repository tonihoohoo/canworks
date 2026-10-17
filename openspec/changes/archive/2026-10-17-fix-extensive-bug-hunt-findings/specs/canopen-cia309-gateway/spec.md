## ADDED Requirements

### Requirement: Forwarder connection limit
The PC forwarders of `canworks-diag gateway --listen` and the link forwarder SHALL serve at most 4 local connections at a time on each local port.

#### Scenario: Fifth gateway connection
- **WHEN** four local clients are connected to `gateway --listen` and a fifth connects
- **THEN** the fifth gets one `ERROR: 102` line and is closed

#### Scenario: Fifth link forwarder connection
- **WHEN** four local clients are connected to a port of `link open` and a fifth connects
- **THEN** the fifth waits until one of the four ends (a browser opens several connections at once)
