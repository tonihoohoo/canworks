## ADDED Requirements

### Requirement: Multiplexing in the schema
The version 2 config and simulation file schemas SHALL describe `multiplexer`, `mux`, raw `valid_location` and `pages`. Checks the schema cannot express (switch names, cycles, value ranges, per-page overlap and length, the page limit, switch locations per mode) SHALL be made by the plugin and the PC tools with the same messages, from shared test fixtures. Configs without these fields SHALL behave as before.

#### Scenario: Unknown switch name
- **WHEN** a raw signal has `mux.on` `Pgae` and the message has a switch `Page`
- **THEN** the PC tools and the plugin both reject the file naming the signal's path and the unknown switch
