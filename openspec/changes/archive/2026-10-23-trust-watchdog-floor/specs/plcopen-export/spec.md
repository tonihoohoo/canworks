## MODIFIED Requirements

### Requirement: truST transport
`--for trust` SHALL also write `canworks_io.st` (the byte arrays `cw_in AT %IB0` and `cw_out AT %QB0`, because truST's PLCopen import drops AT addresses), `io.toml.part` (the `modbus-tcp` driver with the bridge's address and unit ID, reading the input registers from 0 and writing the holding registers from 0 every cycle, `on_error = "warn"`) and `README.txt` with the import command, the VS Code command, the copy and merge steps and the resource name `canworks_res`. `canworks_in` SHALL first copy `cw_in` into `canworks.in_w` and `canworks_out` SHALL last copy `canworks.out_w` into `cw_out`, high byte first. Because truST's driver moves one request each way, a map with more than 125 input or 123 holding registers SHALL be refused; for a config with mailboxes the refusal SHALL name the trimmed mailboxes that fit (one request mailbox, no receive mailbox, network info or cyclic jobs) and the blocks that then need the receive mailbox (`CAN_RECEIVE`, `J1939_RECEIVE`, `CO_RECV_EMCY`). Because a truST scan with the library takes about 100–125 ms, a bridge watchdog (the effective `watchdog_ms`, including OpenPLC's default of five polls) of more than 0 and less than 500 ms SHALL be refused, and the refusal SHALL name `"watchdog_ms": 500` or more as the fix. The truST documentation SHALL say which blocks work on truST and which do not, the scan time and the watchdog floor. The bridge host defaults to 127.0.0.1 when `listen` is a wildcard.

#### Scenario: Run on truST
- **WHEN** the folder is imported into a new truST project, `canworks_io.st` is copied, the driver is set and the runtime runs against a bridge with that config
- **THEN** `canworks.ok` is TRUE, input values follow the bridge, outputs written by `main` reach the bridge, and `CO_SDO_READ` reads 0x1018:1 of a node

#### Scenario: Default mailboxes on truST
- **WHEN** a config with the default mailboxes is exported with `--for trust`
- **THEN** nothing is written and the message says truST's driver moves one request each way and how to trim the mailboxes

#### Scenario: Trimmed mailboxes on truST
- **WHEN** a config with `"mailboxes": {"requests": 1, "receive": false, "network_info": false, "cyclic_jobs": 0}` is exported with `--for trust` and run against the bridge
- **THEN** the export is written, and `CO_SDO_READ_STRING` reads 0x1008 of a node through the request mailbox

#### Scenario: Watchdog too short for truST
- **WHEN** a config with `bridge.openplc` and no `watchdog_ms` (50 ms with the default 10 ms poll), or with `"watchdog_ms": 499`, is exported with `--for trust`
- **THEN** nothing is written and the message says a truST scan takes about 100–125 ms and to set `"watchdog_ms": 500` or more

#### Scenario: Watchdog long enough or off
- **WHEN** a config with `"watchdog_ms": 500`, with the PLC link's default of 1000 ms, or with `"watchdog_ms": 0` is exported with `--for trust`
- **THEN** the export is written

#### Scenario: Steady outputs on truST
- **WHEN** truST runs the export for 60 s against a bridge with `"watchdog_ms": 500`
- **THEN** the bridge log has no watchdog off and on lines while truST runs, and one outputs-off line when truST stops
