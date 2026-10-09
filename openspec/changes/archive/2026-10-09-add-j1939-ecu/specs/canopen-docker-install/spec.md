## ADDED Requirements

### Requirement: J1939 in the runtime container
In Docker mode the plugin SHALL open J1939 sockets in the runtime container through the host's `can-j1939` module, with no Docker-specific J1939 config and no extra container capability beyond what CANopen uses.

#### Scenario: J1939 network on the managed install
- **WHEN** a config with a J1939 network on `can1` is uploaded to a managed Docker install where the host has loaded `can-j1939`
- **THEN** the J1939 network claims its address and exchanges PGNs as on a native install
