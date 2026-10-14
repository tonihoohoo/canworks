## MODIFIED Requirements

### Requirement: Boot commands are not parameter values
Writes that are commands rather than settings (0x1010 store and 0x1011 restore) SHALL NOT be written as ParameterValue. The DCF SHALL list each such step the plugin performs for the node in a leading `;` comment, in boot order.

#### Scenario: Store after configuration check
- **WHEN** a node has the configuration check with store enabled
- **THEN** the DCF has a ParameterValue on 0x1020 sub 1 and sub 2, none on 0x1010, and a comment line saying the plugin writes "save" to 0x1010 sub 1 after the configuration
