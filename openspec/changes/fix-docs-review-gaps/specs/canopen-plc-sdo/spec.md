## MODIFIED Requirements

### Requirement: Error IDs
A block that ends with `ERROR` SHALL set `ERROR_ID` to: 1 the device or the SDO protocol aborted the transfer, with the CiA 301 abort code in `ABORT_CODE`; 2 no answer within `TIMEOUT`, with `ABORT_CODE` 16#05040000; 3 the node is not available; 4 CANopen is not running (no plugin loaded, its configuration rejected, the PLC stopping, or the plugin offers no matching API version); 5 too many program transfers in progress; 6 an input is invalid, including a `NETWORK` that is not a CANopen master network of the config (a network it does not have, a J1939 network, or a slave network); 7 the reply does not fit the block's output; 8 the transfer was cancelled (the PLC was stopped or CANopen restarted after it started, or its result was not collected in time). `ABORT_CODE` SHALL be 0 for every other ID. A block refused with 6 SHALL end in the call that started it, with nothing sent. The library documentation SHALL list these IDs.

#### Scenario: Device refuses a write
- **WHEN** node 5 aborts a write with 16#06090030 (value range exceeded)
- **THEN** the block ends with `ERROR`, `ERROR_ID` 1 and `ABORT_CODE` 16#06090030, and node 5 stays OPERATIONAL

#### Scenario: No answer
- **WHEN** node 40 does not exist and the program reads from it with `TIMEOUT := T#200ms`
- **THEN** the block ends about 200 ms later with `ERROR_ID` 2 and `ABORT_CODE` 16#05040000

#### Scenario: CANopen not running
- **WHEN** the project has no CANopen configuration and the program starts a read
- **THEN** the block ends with `ERROR_ID` 4 in the same call

#### Scenario: NETWORK names a J1939 network
- **WHEN** the config's network 0 is CANopen and network 1 is J1939, and the program starts a read with `NETWORK := 1`
- **THEN** the block ends with `ERROR_ID` 6 in the same call and no frame is sent on either network
