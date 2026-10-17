## ADDED Requirements

### Requirement: ST calls for big-endian signals
The ST call generator SHALL refuse big-endian signals with a message instead of emitting little-endian bit access.

#### Scenario: Motorola signal
- **WHEN** a DBC signal is big-endian
- **THEN** the generator names the signal and emits no call for it
