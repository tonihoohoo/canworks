## ADDED Requirements

### Requirement: Device error history
The command-line client and the configurator SHALL read a node's pre-defined error field (0x1003) with the manual SDO read: sub-index 0 for the number of entries, then sub-indices 1 up to that number (at most 254), sub-index 1 being the newest. Each entry SHALL be shown with its sub-index, the error code (the low 16 bits) with its CiA 301 error class in words, and the manufacturer-specific information (the high 16 bits) in hex. An abort 0x06020000 on sub-index 0 SHALL be shown as "no error history (0x1003)"; an abort on an entry SHALL end the list there and show the abort code with its text. Clearing SHALL write the UNSIGNED8 value 0 to sub-index 0 with the manual SDO write, so it SHALL need `allow_changes`, SHALL be refused on an OPERATIONAL node unless the request carries `force: true`, and SHALL be logged by the plugin like every manual write. Both SHALL work against a runtime and on a local adapter.

#### Scenario: Read the error history
- **WHEN** node 5's 0x1003 holds 2 entries, 0x00004210 at sub-index 1 and 0x00125000 at sub-index 2
- **THEN** the history lists 0x4210 "temperature" with information 0x0000 first, then 0x5000 "device hardware" with information 0x0012, and the count 2

#### Scenario: Device without error history
- **WHEN** node 5 aborts the read of 0x1003 sub-index 0 with 0x06020000
- **THEN** the history says node 5 has no error history (0x1003)

#### Scenario: Clear refused read-only
- **WHEN** `allow_changes` is false and a client asks to clear node 5's error history
- **THEN** the request is refused with "changes not allowed" and nothing is sent

#### Scenario: Clear a running node
- **WHEN** `allow_changes` is true, node 5 is OPERATIONAL and a client clears its error history without `force`
- **THEN** the request is refused saying node 5 is OPERATIONAL and force is needed; with `force` the write of 0 to 0x1003 sub-index 0 is sent, logged as forced, and a new read shows count 0

### Requirement: EMCY COB-ID in the status
For each configured node the status answer SHALL carry `emcy_cob_id` with the COB-ID the master listens on (`value`), where it came from (`source`: `default` for 0x80 + node ID, `eds`, `config` or `device`) and whether the device reports it valid (`valid`, false when the last read of 0x1014 had bit 31 set). The command-line client's `status` SHALL print it for a node only when it is not 0x80 + node ID or not valid. The raw-frame guard and the frame names SHALL use the COB-ID in use.

#### Scenario: Moved COB-ID in the status
- **WHEN** the master read 0xC5 from node 5's 0x1014
- **THEN** the status answer has `emcy_cob_id` value 197, source `device`, valid true, and `canworks-diag status` prints node 5's EMCY COB-ID 0xC5 (device)

#### Scenario: Guard on a moved COB-ID
- **WHEN** node 5's EMCY COB-ID in use is 0xC5 and a client sends a raw frame on 0xC5 without `force`
- **THEN** the request is refused naming 0xC5 as the EMCY of node 5 and saying force is needed

## MODIFIED Requirements

### Requirement: Command-line client
The deploy package SHALL install `canworks-diag`, which connects to `--runtime HOST[:PORT]` with a token given by `--token`, the `CANWORKS_TOKEN` environment variable, or prompted, and offers: `status` (table of master, bus and nodes), `emcy NODE`, `errors NODE [--clear] [--force]` (the device's error history from 0x1003, or clear it), `sdo-read NODE INDEX SUB [--type T]`, `sdo-write NODE INDEX SUB VALUE --type T`, `nmt NODE start|stop|preop|reset|reset-comm`, `scan`, and `hash-token` (prints the `token_sha256` for a token). `--json` SHALL print the raw answer. A refused or failed request SHALL exit non-zero with the reason.

#### Scenario: Status from the engineering PC
- **WHEN** `canworks-diag --runtime plc.local status` runs with the right token
- **THEN** it prints the bus state and one line per node with state, boot result and last EMCY

#### Scenario: Write without permission
- **WHEN** `canworks-diag --runtime plc.local nmt 5 stop` runs and the config has `allow_changes` false
- **THEN** it prints "changes not allowed" and exits non-zero

#### Scenario: Error history from the command line
- **WHEN** `canworks-diag --runtime plc.local errors 5` runs and node 5's 0x1003 holds 2 entries
- **THEN** it prints the count and one line per entry, newest first, with sub-index, code, class and manufacturer information

#### Scenario: Clear needs force on a running node
- **WHEN** `canworks-diag --runtime plc.local errors 5 --clear` runs with `allow_changes` true and node 5 OPERATIONAL
- **THEN** it prints that node 5 is OPERATIONAL and force is needed, and exits non-zero; with `--force` it clears and prints count 0
