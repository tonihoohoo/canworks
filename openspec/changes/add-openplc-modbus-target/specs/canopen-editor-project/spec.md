## ADDED Requirements

### Requirement: Modbus I/O in an OpenPLC project
An editor project created for, or updated from, a config with `bridge.openplc` SHALL get:
- the remote device file of `modbus-bridge-map`;
- a global variable list `canworks` with one variable per located value, named as the declarations name it, typed from the value's CANopen or signal type (BOOL for bits, INT, UINT, DINT, UDINT, LINT, ULINT, REAL, LREAL, BYTE, WORD, DWORD), plus `canworks_ok : BOOL` and `canworks_link : CW_LINK`;
- a program `canworks_in` that converts the input words into those variables (32- and 64-bit values from two or four words, lowest word first; REAL and LREAL through the library's word helpers), fills `canworks_link` and sets `canworks_ok` while the bridge's status counter changed within 3 × `watchdog_ms` and the bridge's map hash equals the program's;
- a program `canworks_out` that converts the output variables and `canworks_link`'s requests into words and then writes the PLC link header with running 1 and the map hash;
- the instances `canworks_in`, the user's `main`, `canworks_out`, in that order, in the project's task, and the `canworks` library enabled.
The raw `%IW`/`%QW` words SHALL be declared only inside `canworks_in` and `canworks_out`. Updating SHALL rewrite only the list, the two programs, the remote device file and the task instances it added; the user's POUs SHALL NOT change. No `VAR` block of located variables SHALL be written into `main` for such a project.

#### Scenario: 32-bit value
- **WHEN** node `enc` maps an UNSIGNED32 position and the bridge serves 0x00012345
- **THEN** `canworks.enc_position` reads 74565 in the program after `canworks_in` ran

#### Scenario: Bridge down
- **WHEN** the bridge stops while the PLC runs
- **THEN** `canworks_ok` becomes FALSE within 3 × `watchdog_ms` plus one poll

#### Scenario: Build
- **WHEN** a project is created from the shipped OpenPLC example config and built with OpenPLC Editor 4.3.2's Build only
- **THEN** the build succeeds and its `conf/modbus_master.json` lists the canworks device
