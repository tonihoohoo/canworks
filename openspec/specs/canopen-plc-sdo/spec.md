# canopen-plc-sdo Specification

## Purpose
SDO transfers the PLC program starts at run time: the `openplc_canopen` editor library's function blocks read or write any object of any node through the running CANopen plugin, without stalling the scan.

## Requirements

### Requirement: SDO function blocks
The editor library `openplc_canopen` SHALL provide the function blocks `CO_SDO_READ`, `CO_SDO_WRITE`, `CO_SDO_READ_REAL`, `CO_SDO_WRITE_REAL`, `CO_SDO_READ_STRING`, `CO_SDO_WRITE_STRING`, `CO_SDO_READ_BYTES` and `CO_SDO_WRITE_BYTES`. Every block SHALL have the inputs `EXECUTE : BOOL`, `NODE : USINT`, `INDEX : UINT`, `SUBINDEX : USINT` and `TIMEOUT : TIME` (`T#0s` meaning 1 s), and the outputs `BUSY : BOOL`, `DONE : BOOL`, `ERROR : BOOL`, `ERROR_ID : UINT` and `ABORT_CODE : UDINT`. The data pins SHALL be:
- `CO_SDO_READ`: out `DATA : LWORD`, `SIZE : UINT`; `CO_SDO_WRITE`: in `DATA : LWORD`, `SIZE : USINT`.
- `CO_SDO_READ_REAL`: out `VALUE : LREAL`; `CO_SDO_WRITE_REAL`: in `VALUE : LREAL`, `SIZE : USINT`.
- `CO_SDO_READ_STRING`: out `VALUE : STRING`; `CO_SDO_WRITE_STRING`: in `VALUE : STRING`.
- `CO_SDO_READ_BYTES` and `CO_SDO_WRITE_BYTES`: in-out `BUFFER : ARRAY[0..1023] OF BYTE`, and `SIZE : UINT` (out for the read, in for the write).
`NODE` SHALL accept any node ID 1 to 127, whether the configuration lists the node or not.

#### Scenario: Read a configured node's object
- **WHEN** the program calls `rd(EXECUTE := TRUE, NODE := 5, INDEX := 16#1018, SUBINDEX := 1)` with `rd : CO_SDO_READ` and node 5's vendor ID is 16#000000AB
- **THEN** within a few scans `rd.DONE` is TRUE, `rd.DATA` is 16#AB and `rd.SIZE` is 4

#### Scenario: Read a node that is not configured
- **WHEN** the program reads 0x1000 subindex 0 of node 40, which the configuration does not list but which is on the bus
- **THEN** the block finishes with `DONE` and the device type

#### Scenario: Node ID out of range
- **WHEN** `NODE` is 0 or 128 at the rising edge of `EXECUTE`
- **THEN** the block finishes with `ERROR`, `ERROR_ID` 6 and sends nothing

### Requirement: Block handshake
A rising edge of `EXECUTE` SHALL start a transfer with the inputs of that call, and `BUSY` SHALL be TRUE until it ends. Input changes and further edges while `BUSY` SHALL be ignored. When the transfer ends, exactly one of `DONE` and `ERROR` SHALL become TRUE and `BUSY` FALSE; the outputs SHALL stay as they are while `EXECUTE` stays TRUE, and SHALL stay for one call when `EXECUTE` was already FALSE when the transfer ended. A new rising edge SHALL clear `DONE`, `ERROR`, `ERROR_ID`, `ABORT_CODE` and the data outputs and start the next transfer. A read's data outputs SHALL change only when it ends with `DONE`.

#### Scenario: EXECUTE held
- **WHEN** the program holds `EXECUTE` TRUE through a read that succeeds
- **THEN** `BUSY` is TRUE until the answer, then `DONE` stays TRUE until the program sets `EXECUTE` FALSE

#### Scenario: Pulse on EXECUTE
- **WHEN** the program sets `EXECUTE` TRUE for one call and FALSE afterwards
- **THEN** the transfer runs to its end, and `DONE` or `ERROR` is TRUE for exactly one call after it ends

#### Scenario: Repeated read
- **WHEN** the program writes `rd(EXECUTE := NOT rd.BUSY AND NOT rd.DONE AND NOT rd.ERROR, ...)` every scan
- **THEN** the block reads the object again after each result, one transfer at a time

#### Scenario: Index changed during a transfer
- **WHEN** the program changes `INDEX` while `BUSY` is TRUE
- **THEN** the running transfer keeps the index from its start

### Requirement: Integer data
`CO_SDO_READ` SHALL put the received bytes, least significant first, into `DATA` with the unused high bytes 0, and the number of bytes into `SIZE`; a reply of more than 8 bytes SHALL end with `ERROR_ID` 7, `SIZE` set to the reply's size and `DATA` unchanged. `CO_SDO_WRITE` SHALL send the low `SIZE` bytes of `DATA`, least significant first; `SIZE` SHALL be 1 to 8, or 0 to take the size of the object's data type from the node's EDS. `SIZE` 0 for a node the configuration does not list, or for an object its EDS does not list, SHALL end with `ERROR_ID` 6 and send nothing.

#### Scenario: Signed value read
- **WHEN** an INTEGER16 object holds -2
- **THEN** `DATA` is 16#FFFE, `SIZE` is 2, and `LWORD_TO_INT(DATA)` is -2

#### Scenario: Write with the size from the EDS
- **WHEN** the program writes `DATA := 500, SIZE := 0` to node 5 object 0x2020 subindex 1, whose EDS type is UNSIGNED16
- **THEN** the master sends the two bytes 16#F4 16#01

#### Scenario: Size from the EDS for an unknown node
- **WHEN** the program writes with `SIZE := 0` to node 40, which the configuration does not list
- **THEN** the block ends with `ERROR_ID` 6 and nothing is sent

### Requirement: Real data
`CO_SDO_READ_REAL` SHALL turn a 4-byte reply into `VALUE` as an IEEE 754 single and an 8-byte reply as a double; a reply of any other size SHALL end with `ERROR_ID` 7 and `VALUE` unchanged. `CO_SDO_WRITE_REAL` SHALL send `VALUE` as a single when `SIZE` is 4 and as a double when it is 8; `SIZE` 0 SHALL take 4 or 8 from the EDS type (REAL32 or REAL64) of a configured node's object, and any other size, or an EDS type that is not REAL32 or REAL64, SHALL end with `ERROR_ID` 6.

#### Scenario: REAL32 setpoint
- **WHEN** the program writes `VALUE := 12.5, SIZE := 0` to an object whose EDS type is REAL32
- **THEN** the master sends the four bytes of 12.5 as a single

#### Scenario: Integer object read as REAL
- **WHEN** `CO_SDO_READ_REAL` reads a 2-byte object
- **THEN** the block ends with `ERROR_ID` 7 and `VALUE` keeps its old value

### Requirement: String data
`CO_SDO_READ_STRING` SHALL put the reply into `VALUE` up to its first NUL byte; a reply longer than 254 bytes up to that point SHALL end with `ERROR_ID` 7 and `VALUE` unchanged. `CO_SDO_WRITE_STRING` SHALL send the characters of `VALUE` without a terminating NUL; an empty `VALUE` SHALL send zero bytes. Transfers longer than 4 bytes SHALL use segmented SDO.

#### Scenario: Device name
- **WHEN** the program reads 0x1008 subindex 0 of a node whose name is `IO module 8DI`
- **THEN** `VALUE` is `'IO module 8DI'`

### Requirement: Byte data
`CO_SDO_READ_BYTES` SHALL copy the reply into `BUFFER` from element 0 and set `SIZE` to its length; a reply longer than 1024 bytes SHALL end with `ERROR_ID` 7, `SIZE` set to its length and `BUFFER` unchanged. `CO_SDO_WRITE_BYTES` SHALL send elements 0 to `SIZE`-1 of `BUFFER`; `SIZE` above 1024 SHALL end with `ERROR_ID` 6.

#### Scenario: Write a block of bytes
- **WHEN** the program writes `SIZE := 20` bytes to an OCTET_STRING object
- **THEN** the master sends those 20 bytes in one segmented transfer and the block ends with `DONE`

### Requirement: Error IDs
A block that ends with `ERROR` SHALL set `ERROR_ID` to: 1 the device or the SDO protocol aborted the transfer, with the CiA 301 abort code in `ABORT_CODE`; 2 no answer within `TIMEOUT`, with `ABORT_CODE` 16#05040000; 3 the node is not available; 4 CANopen is not running (no plugin loaded, its configuration rejected, the PLC stopping, or the plugin offers no matching API version); 5 too many program transfers in progress; 6 an input is invalid; 7 the reply does not fit the block's output; 8 the transfer was cancelled (the PLC was stopped or CANopen restarted after it started, or its result was not collected in time). `ABORT_CODE` SHALL be 0 for every other ID. The library documentation SHALL list these IDs.

#### Scenario: Device refuses a write
- **WHEN** node 5 aborts a write with 16#06090030 (value range exceeded)
- **THEN** the block ends with `ERROR`, `ERROR_ID` 1 and `ABORT_CODE` 16#06090030, and node 5 stays OPERATIONAL

#### Scenario: No answer
- **WHEN** node 40 does not exist and the program reads from it with `TIMEOUT := T#200ms`
- **THEN** the block ends about 200 ms later with `ERROR_ID` 2 and `ABORT_CODE` 16#05040000

#### Scenario: CANopen not running
- **WHEN** the project has no CANopen configuration and the program starts a read
- **THEN** the block ends with `ERROR_ID` 4 in the same call

### Requirement: Node availability
For a node the configuration lists, a transfer SHALL be sent only while the node is available (booted and not lost, not STOPPED). A transfer started while the node is being booted or configured, or before the master has heard from it since CANopen started (its first boot is still to come), SHALL wait and be sent after the boot ends, with the wait counted in `TIMEOUT`. A transfer started while the node is lost, has not booted, or is STOPPED SHALL end at once with `ERROR_ID` 3. For a node the configuration does not list, the transfer SHALL be sent at once. Program transfers SHALL NOT change a node's NMT state, status bit or state byte.

#### Scenario: Node lost
- **WHEN** node 5 is lost and the program starts a read from it
- **THEN** the block ends with `ERROR_ID` 3 and nothing is sent

#### Scenario: Node booting
- **WHEN** node 5 is being configured after a reset and the program starts a read from it with the default timeout
- **THEN** the read is sent after node 5's boot ends and the block ends with `DONE`

#### Scenario: Read in the first scans
- **WHEN** the program starts a read from node 5 in its first scan after a PLC start, before node 5 has answered the restarted master, with `TIMEOUT := T#4s`
- **THEN** the read waits for node 5's boot and the block ends with `DONE`

### Requirement: Sharing the SDO channel
The master SHALL run at most one SDO transfer per node at a time across program transfers, SDO variables and the diagnostics channel, SHALL NOT start a program transfer while the node is being booted or configured, and SHALL send a node's program transfers in the order they were started. When both are due for the same node, a program transfer and an SDO variable transfer SHALL take turns, so neither waits for all of the other's. At most 64 program transfers SHALL be in progress or waiting at a time; a block started beyond that SHALL end at once with `ERROR_ID` 5. Transfers to different nodes SHALL run at the same time.

#### Scenario: Two blocks on one node
- **WHEN** two block instances start a read from node 5 in the same scan
- **THEN** both end with `DONE`, the second transfer starting after the first has ended

#### Scenario: Too many at once
- **WHEN** 65 block instances start transfers in the same scan and none has ended
- **THEN** 64 are `BUSY` and one ends with `ERROR_ID` 5

### Requirement: Blocks do not stall the scan
A block call SHALL return without waiting on CAN traffic, SHALL NOT allocate memory and SHALL NOT write to the log; it SHALL at most take a lock held only for copying a request or a result. A block's result SHALL be visible in the first call of that instance after the transfer ended. A result that no call collects within 10 s after the transfer ended SHALL be dropped, and a later call of that instance SHALL end with `ERROR_ID` 8.

#### Scenario: Slow device
- **WHEN** a node takes 500 ms to answer and the task interval is 10 ms
- **THEN** every scan meanwhile runs on time and the block shows `BUSY`

### Requirement: PLC stop and restart
When the PLC stops, the plugin SHALL stop sending program transfers, drop waiting ones and cancel those in flight, so the stop does not wait for their timeouts, and SHALL log once how many it cancelled. A block instance whose transfer started before a stop or a CANopen restart SHALL end with `ERROR_ID` 8 on its next call, never with the answer of another transfer.

#### Scenario: Stop during a transfer
- **WHEN** the PLC is stopped while a block is `BUSY` and started again
- **THEN** that block's next call ends with `ERROR_ID` 8, and its next rising edge starts a new transfer normally

### Requirement: Finding the plugin
The blocks SHALL reach the plugin the runtime has already loaded, by its library name, without loading a second copy and whatever install prefix it was installed under, and SHALL call it only through one exported C entry point that takes the API version the library was built for and returns a table of functions, or nothing when the plugin does not offer that version. A block that finds no plugin, or no matching API version, SHALL end with `ERROR_ID` 4 and SHALL look again on its next rising edge. The table SHALL carry a network number on every request, which this version accepts only as 0.

#### Scenario: Library newer than the plugin
- **WHEN** the library asks for an API version the installed plugin does not offer
- **THEN** every block ends with `ERROR_ID` 4, and the plugin logs once that the program's CANopen library needs a newer plugin, naming both versions

#### Scenario: Plugin installed under another prefix
- **WHEN** the plugin was installed with `install-stock.sh --prefix /usr/local/openplc-canopen`
- **THEN** the blocks find it and transfers work

### Requirement: Writes to objects the plugin configures
A program write to an object the plugin configures itself (0x1005-0x1007, 0x100C, 0x100D, 0x1014-0x1017, 0x1400-0x1BFF, 0x1F80) of a configured node SHALL be sent, and the plugin SHALL log a warning naming the node and the object the first time it happens in a run.

#### Scenario: Program changes a heartbeat period
- **WHEN** the program writes 0x1017 subindex 0 of node 5
- **THEN** the write is sent and the log warns once that the program overrides node 5's 0x1017

### Requirement: Logging program transfers
The plugin SHALL log an aborted or timed-out program transfer with the node, the object, read or write and the abort code in hex and words, and SHALL NOT log the same node, object and abort code again until a program transfer of that object succeeds. Successful transfers SHALL NOT be logged.

#### Scenario: Repeated abort
- **WHEN** the program reads a missing object ten times in a row and each read is aborted with 16#06020000
- **THEN** the log shows that abort once

### Requirement: Library delivery
The library SHALL be built from its editor library project in this repository into `openplc_canopen.stlib`. Each `deploy-v` release SHALL carry that file, `openplc-canopen-deploy library --out DIR` SHALL write the copy that matches the installed tools into `DIR`, `openplc-canopen-deploy library --install` SHALL install that copy into OpenPLC Editor on the same computer as the editor's Library Manager does, and `openplc-canopen-deploy library --project DIR` SHALL enable it in an editor project. The library's version SHALL equal the deploy package version. Installing it once with the editor's Library Manager ("install from file") SHALL make the blocks appear in the editor's library tree for every project that enables it.

#### Scenario: Install in the editor
- **WHEN** the user runs `openplc-canopen-deploy library --out .` and installs the written file in OpenPLC Editor 4.3.2
- **THEN** the library tree lists `openplc_canopen` with the eight blocks, and a project that enables it and calls `CO_SDO_READ` builds for OpenPLC Runtime v4

#### Scenario: Install from the command line
- **WHEN** the user runs `openplc-canopen-deploy library --install` on a PC where OpenPLC Editor has run, then restarts the editor
- **THEN** the editor's library list shows `openplc_canopen` with the tools' version, and libraries installed before are still listed
