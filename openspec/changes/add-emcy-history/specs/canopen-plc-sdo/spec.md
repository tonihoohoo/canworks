## ADDED Requirements

### Requirement: EMCY receive block
The editor library `canworks` SHALL provide the function block `CO_RECV_EMCY` with the inputs `ENABLE : BOOL`, `NETWORK : USINT`, `NODE : USINT` (0 for every node, 1 to 127 for one node) and `SKIP_OLD : BOOL`, the in-out `MSEF : ARRAY[0..4] OF BYTE`, and the outputs `ACTIVE : BOOL`, `NEW : BOOL`, `EMCY_NODE : USINT`, `ERROR_CODE : WORD`, `ERROR_REGISTER : BYTE`, `TIMESTAMP : ULINT`, `QUEUED : UINT`, `OVERFLOW : BOOL`, `LOST : UDINT`, `ERROR : BOOL` and `ERROR_ID : UINT`. While `ENABLE` is TRUE, each call SHALL take at most one emergency message of the network that matches `NODE`, oldest first: `NEW` TRUE with its node, error code, error register, the five manufacturer-specific bytes in `MSEF` and its receive time in UTC microseconds in `TIMESTAMP`, or `NEW` FALSE with the last message's outputs kept. `QUEUED` SHALL be the number of matching messages still waiting for this instance. An EMCY with error code 0x0000 SHALL be delivered like any other. A block call SHALL return without waiting, allocating or logging, as the SDO blocks do.

#### Scenario: Fault and reset within one scan
- **WHEN** node 3 sends EMCY 0x4210 with error register 0x09 and 2 ms later EMCY 0x0000, and the program's task interval is 10 ms
- **THEN** a `CO_RECV_EMCY` instance with `NODE := 0` delivers 0x4210 with register 0x09 and then 0x0000, in that order, while `emcy_code_location` reads 0 after that scan

#### Scenario: Drain in one scan
- **WHEN** five EMCYs are waiting and the program calls `rx(ENABLE := TRUE)` once and then again in a `WHILE rx.NEW DO` loop
- **THEN** all five are delivered in that scan and `QUEUED` is 0 after the last

#### Scenario: Same code twice
- **WHEN** node 3 sends EMCY 0x5000 twice in a row
- **THEN** the block delivers two messages with code 0x5000

#### Scenario: One node only
- **WHEN** `NODE` is 5 and nodes 3 and 5 send EMCYs
- **THEN** the block delivers only node 5's messages

#### Scenario: Invalid input
- **WHEN** `NODE` is 128, or `NETWORK` names a J1939 or slave network, at the rising edge of `ENABLE`
- **THEN** the block shows `ERROR` with `ERROR_ID` 6 and delivers nothing

#### Scenario: CANopen not running
- **WHEN** the project has no CANopen configuration and `ENABLE` is TRUE
- **THEN** the block shows `ERROR_ID` 4 and tries again on every call while `ENABLE` stays TRUE

### Requirement: Per-network EMCY queue
For each CANopen master network the plugin SHALL keep the last 64 emergency messages received from configured nodes since the CANopen session started, including messages whose log lines were suppressed by the log throttle, and each `CO_RECV_EMCY` instance SHALL read them from its own position, so that several instances each receive every matching message. At the rising edge of `ENABLE` an instance SHALL start at the oldest message still kept, or with `SKIP_OLD` TRUE at the next message received. When messages an instance has not read yet are overwritten, the instance SHALL add their number to `LOST` and set `OVERFLOW` until `ENABLE` goes FALSE; the docs SHALL say that with a node filter `LOST` also counts other nodes' messages. When a new CANopen session starts, the queue SHALL be emptied and an instance reading from the earlier session SHALL show `ERROR_ID` 8 for one call and then continue from the new session's oldest message without counting `LOST`. EMCYs of node IDs not in the configuration SHALL NOT be queued.

#### Scenario: Two readers
- **WHEN** two `CO_RECV_EMCY` instances on network 0 are enabled and node 3 sends one EMCY
- **THEN** both instances deliver it

#### Scenario: EMCY during the first boot
- **WHEN** node 3 sends an EMCY while the master boots it, before the program's first scan, and the program enables the block in its first scan
- **THEN** the block delivers that EMCY

#### Scenario: Reader falls behind
- **WHEN** an enabled instance is not called while 70 EMCYs arrive, and is called again
- **THEN** it delivers the newest 64 in order, `LOST` is 6 and `OVERFLOW` is TRUE

#### Scenario: Latest-EMCY inputs unchanged
- **WHEN** a configured node with `emcy_code_location` sends EMCYs while a `CO_RECV_EMCY` instance drains the queue
- **THEN** `emcy_code_location` and `error_register_location` read the latest EMCY exactly as without the block

### Requirement: EMCY interface version
The plugin's C entry point SHALL offer version 2 of its table, which SHALL begin with the fields of version 1 and add the EMCY read functions, and SHALL keep offering version 1. The SDO blocks SHALL ask for version 1 and `CO_RECV_EMCY` for version 2, so that the SDO blocks of a library built with this change keep working with a plugin that offers only version 1, while `CO_RECV_EMCY` ends with `ERROR_ID` 4 there.

#### Scenario: New library, older plugin
- **WHEN** a program built with this library calls `CO_SDO_READ` and `CO_RECV_EMCY` on a runtime whose plugin offers only version 1
- **THEN** the read ends with `DONE`, `CO_RECV_EMCY` shows `ERROR_ID` 4, and the plugin logs once that the program's CANopen library needs a newer plugin, naming both versions

## MODIFIED Requirements

### Requirement: Library delivery
The library SHALL be built from its editor library project in this repository into `canworks.stlib`. It SHALL hold the SDO blocks, the `CO_RECV_EMCY` block, the CiA 402 blocks and the CAN frame blocks and helper functions of `can-plc-frames`. Each `deploy-v` release SHALL carry that file, `canworks-deploy library --out DIR` SHALL write the copy that matches the installed tools into `DIR`, `canworks-deploy library --install` SHALL install that copy into OpenPLC Editor on the same computer as the editor's Library Manager does, and `canworks-deploy library --project DIR` SHALL enable it in an editor project. The library's version SHALL equal the deploy package version. Installing it once with the editor's Library Manager ("install from file") SHALL make the blocks appear in the editor's library tree for every project that enables it.

#### Scenario: Install in the editor
- **WHEN** the user runs `canworks-deploy library --out .` and installs the written file in OpenPLC Editor 4.3.2
- **THEN** the library tree lists `canworks` with the `CO_SDO_*`, `CO_RECV_EMCY`, `CO402_*` and `CAN_*` blocks, and a project that enables it and calls `CO_SDO_READ`, `CO_RECV_EMCY` and `CAN_RECEIVE` builds for OpenPLC Runtime v4

#### Scenario: Install from the command line
- **WHEN** the user runs `canworks-deploy library --install` on a PC where OpenPLC Editor has run, then restarts the editor
- **THEN** the editor's library list shows `canworks` with the tools' version, and libraries installed before are still listed
