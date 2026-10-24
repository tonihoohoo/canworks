## ADDED Requirements

### Requirement: Safe values on the Modbus bridge page
The Modbus bridge page's client-loss choice SHALL offer **Safe values** next to the other actions, with a one-line description of each. With Safe values picked, a **Safe values** table SHALL list every output value of the config that can have one: name, location, type, unit and the EDS's limits where it has them, with a safe value field whose blank means 0. A bit channel SHALL be listed under its entry. A value the check would refuse SHALL be marked at its field with the reason. The table's changes SHALL be one undo step each and SHALL mark connections whose Download carries the map as out of date. Problems SHALL warn when `safe_values` is set and the action is another, with **Use safe values** as its fix.

#### Scenario: Set a valve's safe value
- **WHEN** the user picks Safe values and types 500 for `dio.valve_cmd`
- **THEN** the saved config has `"on_client_loss": "safe"` and `"safe_values": { "%QW10": 500 }`, and the register map preview shows 500 in its safe value column

#### Scenario: Out of range in the table
- **WHEN** the user types 300 for an UNSIGNED8 output
- **THEN** the field is marked with "0-255" and Problems lists the error until it is fixed

#### Scenario: Safe values left behind
- **WHEN** a config has `safe_values` and the user switches the action to Stop
- **THEN** Problems warns that the safe values are not used, and Use safe values switches the action back
