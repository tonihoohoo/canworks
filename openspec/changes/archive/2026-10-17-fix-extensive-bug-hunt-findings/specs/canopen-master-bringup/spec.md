## ADDED Requirements

### Requirement: EDS files load the same on the PC and the runtime
The PC tools' EDS check SHALL refuse every EDS the plugin's EDS load refuses and accept the forms it accepts: a bare `$NODEID` default (any case) SHALL be read as `$NODEID+0`, an empty `DefaultValue` SHALL be read as 0, an integer default on a REAL object SHALL be read as that number, and a `SupportedObjects` count above 0xFFFF SHALL be refused before any object is read.

#### Scenario: Bare $NODEID
- **WHEN** an object's `DefaultValue` is `$NODEID`
- **THEN** both the configurator and the plugin accept the EDS and read node ID plus 0

#### Scenario: Unsupported data type
- **WHEN** an object has `DataType=0x0040`
- **THEN** both refuse the EDS with the same message

#### Scenario: Empty default in 0x1016
- **WHEN** a heartbeat consumer sub-index has an empty `DefaultValue`
- **THEN** the plugin, the DCF export and the docs use the same sub-index for the heartbeat watch
