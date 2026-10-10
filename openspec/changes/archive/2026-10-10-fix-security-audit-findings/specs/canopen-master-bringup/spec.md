## ADDED Requirements

### Requirement: Helper programs run with limits
`dcfgen` and the EDS lint SHALL run as programs found once at start by absolute path, with Python in isolated mode, and SHALL be stopped after 60 s; a time-out or a failure to collect the program's exit status SHALL count as a failure of that step, logged with the reason, and SHALL NOT leave the PLC start waiting.

#### Scenario: Hung generator
- **WHEN** `dcfgen` does not finish within 60 s
- **THEN** it is stopped, the network does not start, the log says `dcfgen` timed out, and the runtime's start returns

### Requirement: Interface names are checked
An interface name SHALL have 1 to 15 characters from letters, digits, `_`, `.`, `:` and `-`, for every network kind; other names SHALL make the config refused at load, and the configurator's check SHALL refuse them too.

#### Scenario: Long name
- **WHEN** a network's interface is `can_machine_main_bus`
- **THEN** the config is refused naming the interface and the 15-character limit
