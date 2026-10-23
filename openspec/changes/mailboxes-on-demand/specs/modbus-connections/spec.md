## MODIFIED Requirements

### Requirement: Connection kinds
Each kind SHALL have its own fields and download:
- `openplc`: `poll_ms` (5-1000, default 10), `remote_device` (default `canworks`), `iec_base`; address `127.0.0.1`, `writes` true; files kept in sync by Save;
- `trust` and `plc`: `format` (`plcopen`, or `st` for `plc`), `library`, `bridge_host`, `blocks`; the PLCopen or ST PLC link export;
- `nodered`: `period_ms`, `bridge_host`, `blocks`; the Node-RED flow;
- `hmi`: `format` (`csv`, `json` or `st`); the register map or ST variables.

`blocks` SHALL be `none` (default), `sdo_send`, `receive` or `all`; for `trust` only `none` and `sdo_send`.

#### Scenario: Node-RED download
- **WHEN** the user presses Download on a Node-RED connection with `bridge_host` 192.168.10.5
- **THEN** the browser gets the same file `canworks-deploy --export-nodered` writes for that host and period

#### Scenario: Other PLC as ST
- **WHEN** an Other PLC connection has `format` `st`
- **THEN** its Download gives the same file `--export-modbus-map OUT.st` writes for the config

#### Scenario: truST with receiving blocks
- **WHEN** a truST connection has `blocks` `receive`
- **THEN** the check fails naming `bridge.connections[0].blocks` and saying truST moves one request each way, so only None or SDO and send fit

### Requirement: OpenPLC connection bridge settings
Adding an OpenPLC connection SHALL, in one undo step, set `plc_link` true, `word_order` `low_first`, `listen` `127.0.0.1:1502` when unset, `watchdog_ms` 5 × `poll_ms` (at least 50) when unset, add a live list for every CANopen master network and repack. It SHALL NOT turn the mailboxes on: the program's mailbox blocks do that through Problems (canopen-configurator "Mailbox blocks the OpenPLC program declares"). With an OpenPLC connection the check SHALL refuse `plc_link` false and `word_order` `high_first`.

#### Scenario: Add OpenPLC to a new bridge config
- **WHEN** the user adds an OpenPLC connection to a new Modbus bridge config with one network
- **THEN** the config has `plc_link` true, `listen` `127.0.0.1:1502`, `writers` `["127.0.0.1"]`, `watchdog_ms` 50 and a live list, no `bridge.mailboxes`, and the values start after the PLC link header

#### Scenario: High word first
- **WHEN** a config with an OpenPLC connection has `word_order` `high_first`
- **THEN** the check fails saying OpenPLC's Modbus master reads 32- and 64-bit values lowest word first

## ADDED Requirements

### Requirement: Canworks blocks choice of a connection
Each `trust`, `plc` and `nodered` connection row SHALL offer "canworks blocks": None, SDO and send (one request mailbox), SDO, send and receive (also the receive mailbox) or All (also 4 cyclic jobs and network info), and SHALL show the choice with the parts it needs. truST SHALL offer only None and SDO and send. Node-RED SHALL offer the choice only when the Node-RED package has block nodes.

#### Scenario: Row text
- **WHEN** an Other PLC connection has SDO and send
- **THEN** its row reads "canworks blocks: SDO and send (1 request mailbox)"

### Requirement: Mailboxes follow the connections
When a connection's canworks blocks choice changes, the configurator SHALL add the missing parts to `bridge.mailboxes` in the same undo step and place the areas, keep parts that are already on, and mark the connection Out of date.

#### Scenario: truST with SDO blocks
- **WHEN** a config without mailboxes has a truST connection and the user picks SDO and send
- **THEN** in one undo step `bridge.mailboxes` becomes one request mailbox with receive, network info and cyclic jobs off, the areas are placed, the row reads Out of date, and the PLCopen download is not refused

#### Scenario: Choice back to None
- **WHEN** the only connection that needed the mailboxes is set to None
- **THEN** the mailboxes stay as they are, and Problems shows the info that nothing needs them, with Turn off the mailboxes

### Requirement: One program owns the mailboxes
The mailboxes' request words, tickets and receivers assume one client. At most one connection SHALL have a canworks blocks choice other than None, and none when the config has an OpenPLC connection, whose program owns them. Problems SHALL show an error naming both connections otherwise.

#### Scenario: Second mailbox user
- **WHEN** a truST connection has SDO and send, and the user picks SDO, send and receive on a Node-RED connection
- **THEN** Problems shows an error naming both connections, saying only one program can use the mailboxes
