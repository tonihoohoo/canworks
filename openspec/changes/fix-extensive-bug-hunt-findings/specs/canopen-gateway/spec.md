## ADDED Requirements

### Requirement: Routes are read at network start
When the field network's bus session starts, the gateway SHALL take every route's current value from the upper side before any field output is sent, and SHALL resynchronise the routes periodically.

#### Scenario: Field adapter replugged
- **WHEN** the upper master keeps sending 55 on a route and the field adapter is unplugged and plugged back
- **THEN** the field node gets 55, not 0, when it comes up

### Requirement: Hold keeps values through a gateway reset
With `on_upper_loss: "hold"`, the gateway SHALL forward a route only after the upper master wrote it. A reset of the gateway slave or a restart of its bus session SHALL NOT forward the EDS default values.

#### Scenario: Upper master resets the gateway
- **WHEN** the upper master is lost and sends RESET NODE to the gateway
- **THEN** the field outputs keep their last values
