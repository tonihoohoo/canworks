# j1939-plc-diagnostics Specification

## Purpose
TBD - created by archiving change add-j1939-diagnostics. Update Purpose after archive.

## Requirements

### Requirement: Trouble code function blocks
The editor library `canworks` SHALL provide `J1939_DM_READ` and `J1939_DM_CLEAR`. Both SHALL have `NETWORK : USINT` (the network's place in `networks`), `EXECUTE : BOOL`, `TIMEOUT : TIME` (`T#0s` meaning 1 s), and the outputs `BUSY`, `DONE`, `ERROR : BOOL` and `ERROR_ID : UINT`, with the handshake of `CAN_SEND`: a rising edge of `EXECUTE` starts one job with that call's inputs, edges while `BUSY` are ignored, and outputs stay while `EXECUTE` stays TRUE and for one call after.
- `J1939_DM_READ`: in `SOURCE : USINT`, `PREVIOUS : BOOL`; in-out `DTCS : ARRAY[0..31] OF UDINT`; out `LAMPS : BYTE`, `FLASH : BYTE`, `COUNT : UINT`, `AGE : TIME`. With `PREVIOUS` FALSE it SHALL return the latest DM1 the network received from `SOURCE` without sending anything, `AGE` being the time since it arrived. With `PREVIOUS` TRUE it SHALL send a Request for DM2 to `SOURCE` from the network's address and return the answer. `COUNT` SHALL be the number of codes in the message; the first 32 SHALL be in `DTCS` in the form of "Trouble code value in the PLC" and the rest of `DTCS` SHALL be 0.
- `J1939_DM_CLEAR`: in `DESTINATION : USINT` (0..253, or 255 global), `PREVIOUS_ONLY : BOOL`. It SHALL send a Request for DM3 (`PREVIOUS_ONLY` TRUE) or DM11 (FALSE) to `DESTINATION`. To an address it SHALL be `DONE` on that ECU's ACK; globally it SHALL be `DONE` once the request is on the bus.

#### Scenario: Read the engine's codes
- **WHEN** ECU 0 has sent a DM1 with two codes and the program calls `rd(EXECUTE := TRUE, NETWORK := 0, SOURCE := 0, DTCS := buf)`
- **THEN** within a few scans `rd.DONE` is TRUE, `rd.COUNT` is 2 and `buf[0]`, `buf[1]` hold the codes

#### Scenario: Read previously active codes
- **WHEN** the program calls the block with `PREVIOUS := TRUE` and ECU 0 answers the DM2 Request with one code
- **THEN** `DONE` is TRUE, `COUNT` is 1 and `DTCS[0]` holds that code

#### Scenario: Clear refused
- **WHEN** the program clears ECU 0 with `J1939_DM_CLEAR` and ECU 0 answers NACK
- **THEN** the block reports `ERROR` with `ERROR_ID` 12

### Requirement: Error IDs of the trouble code blocks
The trouble code blocks SHALL report `ERROR_ID`:
- 1: the plugin is not loaded, does not offer the J1939 block interface's version, or the network is not running
- 2: no such network
- 3: an input is invalid (`SOURCE` above 253, `DESTINATION` 254)
- 5: another read of DM2 or clear for the same address on this network is pending
- 6: no answer within `TIMEOUT`
- 7: the network is bus-off or its interface is down
- 8: cancelled by a PLC stop or a network restart
- 10: the network is not a J1939 network
- 11: the network holds no address (claiming or cannot claim)
- 12: the destination answered NACK
- 13: no DM1 has been received from `SOURCE`

#### Scenario: CANopen network
- **WHEN** `J1939_DM_READ` is called with the `NETWORK` of a CANopen network
- **THEN** it reports `ERROR_ID` 10 and sends nothing

#### Scenario: ECU never seen
- **WHEN** `J1939_DM_READ` with `PREVIOUS` FALSE asks for source 7 and no DM1 from 7 has arrived
- **THEN** it reports `ERROR_ID` 13

### Requirement: Trouble code blocks do not stall the scan
The trouble code blocks SHALL never wait for CAN traffic, allocate memory or write the log on the PLC scan thread, and SHALL work from several PLC tasks at once with each instance getting its own result. They SHALL reach the plugin as the frame blocks do and call `canworks_j1939_api(1)`, which returns the version 1 table or NULL; a plugin without it SHALL give `ERROR_ID` 1. A PLC stop SHALL end every pending job with `ERROR_ID` 8.

#### Scenario: Plugin without J1939
- **WHEN** a program using `J1939_DM_READ` runs with a plugin built without J1939
- **THEN** the block reports `ERROR_ID` 1 and the scan time does not change

### Requirement: Trouble code ST functions
The library SHALL provide the function block `J1939_DTC_SPLIT` (in `DTC : UDINT`; out `SPN : UDINT`, `FMI : USINT`, `OC : USINT`, `CM : BOOL`) and the function `J1939_DTC_MAKE(SPN : UDINT, FMI : USINT, OC : USINT) : UDINT`, needing no plugin, and their results SHALL equal the plugin's packing.

#### Scenario: Split a code
- **WHEN** a program splits 16#021FF000
- **THEN** it gets SPN 520192, FMI 3, OC 2 and CM FALSE
