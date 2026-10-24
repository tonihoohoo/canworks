## MODIFIED Requirements

### Requirement: Connection kinds
Each kind SHALL have its own fields and download:
- `openplc`: `poll_ms` (5-1000, default 10), `mailbox_poll_ms`, `remote_device` (default `canworks`), `iec_base`; address `127.0.0.1`, `writes` true; files kept in sync by Save;
- `trust` and `plc`: `format` (`plcopen`, or `st` for `plc`), `library`, `bridge_host`, `blocks`; the PLCopen or ST PLC link export;
- `nodered`: `period_ms`, `bridge_host`, `blocks`; the Node-RED flow;
- `hmi`: `format` (`csv`, `json` or `st`); the register map or ST variables.

`blocks` SHALL be `none` (default), `sdo_send`, `receive` or `all`; for `trust` only `none` and `sdo_send`.

`mailbox_poll_ms` SHALL be a multiple of the connection's `poll_ms` and at most 250; unset, it SHALL be the smallest multiple of `poll_ms` that is at least 50. The check SHALL refuse other values, naming the field and saying the mailbox poll must be a multiple of the poll and at most 250 ms.

#### Scenario: Node-RED download
- **WHEN** the user presses Download on a Node-RED connection with `bridge_host` 192.168.10.5
- **THEN** the browser gets the same file `canworks-deploy --export-nodered` writes for that host and period

#### Scenario: Other PLC as ST
- **WHEN** an Other PLC connection has `format` `st`
- **THEN** its Download gives the same file `--export-modbus-map OUT.st` writes for the config

#### Scenario: truST with receiving blocks
- **WHEN** a truST connection has `blocks` `receive`
- **THEN** the check fails naming `bridge.connections[0].blocks` and saying truST moves one request each way, so only None or SDO and send fit

#### Scenario: Default mailbox poll
- **WHEN** an OpenPLC connection has `poll_ms` 15 and no `mailbox_poll_ms`
- **THEN** its mailbox poll is 60 ms

#### Scenario: Not a multiple
- **WHEN** an OpenPLC connection has `poll_ms` 20 and `mailbox_poll_ms` 50
- **THEN** the check fails naming `bridge.connections[0].mailbox_poll_ms`
