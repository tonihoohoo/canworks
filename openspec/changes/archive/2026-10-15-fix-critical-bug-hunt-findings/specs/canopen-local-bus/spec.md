## ADDED Requirements

### Requirement: Listen-only means listen-only
When the local bus opens an adapter listen-only, the adapter SHALL really be in listen-only mode; an adapter that cannot do it SHALL make the open fail with a message naming the adapter, instead of opening in normal mode. A network with `adapter.listen_only: true` SHALL connect listen-only and SHALL NOT send the probe frame.

#### Scenario: Adapter without listen-only support
- **WHEN** a USB adapter that lacks listen-only mode is opened listen-only
- **THEN** the open fails with "this adapter cannot listen only" and nothing is acknowledged on the bus

#### Scenario: Listen-only network
- **WHEN** a network with `adapter.listen_only: true` is connected on a silent bus
- **THEN** no probe frame is sent and the connection stays listen-only
