## ADDED Requirements

### Requirement: Export a Node-RED flow from the command line
`canworks-deploy --config FILE --export-nodered OUT` SHALL write the Node-RED flow of a bridge config without contacting any device. `--nodered-host HOST[:PORT]` SHALL set the bridge address the flow connects to (default: the bridge's listen address, `127.0.0.1` for an all-addresses listen) and `--nodered-poll-ms N` the poll period (default 100, kept between 10 and a third of `watchdog_ms`, with a note when changed). A config that is not a bridge config SHALL be refused with a message saying so, and the option SHALL not combine with an upload.

#### Scenario: Defaults
- **WHEN** `canworks-deploy --config examples/modbus-bridge/canworks.json --export-nodered flow.json` runs
- **THEN** `flow.json` connects to `127.0.0.1` on the bridge's port, polls every 100 ms, and the tool prints the number of signals in and out
