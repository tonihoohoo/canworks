## MODIFIED Requirements

### Requirement: Export a Node-RED flow from the command line
`canworks-deploy --config FILE --export-nodered OUT` SHALL write the Node-RED flow of a bridge config without contacting any device. `--nodered-host HOST[:PORT]` SHALL set the bridge address the flow connects to (default: the bridge's listen address, `127.0.0.1` for an all-addresses listen) and `--nodered-poll-ms N` the poll period (default 10, kept between 10 and a third of `watchdog_ms`, with a note when changed). The tool SHALL print the number of values in and out, the mailboxes the flow's block nodes can use, and that the flow needs the `node-red-canworks` package of this tools version. A config that is not a bridge config SHALL be refused with a message saying so, and the option SHALL not combine with an upload. `canworks-deploy --export-nodered-package OUT` SHALL write the package `.tgz` of the installed tools (nodered-blocks) and needs no config.

#### Scenario: Defaults
- **WHEN** `canworks-deploy --config examples/modbus-bridge/canworks.json --export-nodered flow.json` runs
- **THEN** `flow.json` connects to `127.0.0.1` on the bridge's port, polls every 10 ms, and the tool prints the number of values in and out and the package it needs

#### Scenario: Package
- **WHEN** `canworks-deploy --export-nodered-package node-red-canworks.tgz` runs with tools 0.120.0
- **THEN** the file is a package `node-red-canworks` version 0.120.0, the same bytes on every run
