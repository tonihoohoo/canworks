# canopen-device-parameters Specification

## Purpose
Reading all parameters of a live CANopen node through the diagnostics channel, saving them as a CiA 306 DCF backup, comparing a device with a backup, the configuration or its EDS, and writing a backup back to a replacement device, with storing to non-volatile memory kept a separate explicit action.

## Requirements

### Requirement: Read all parameters of a node
The tools SHALL read every entry of a node's object dictionary that its EDS lists with access `ro`, `rw`, `rwr`, `rww` or `const`, one SDO read at a time per client, in ascending index and subindex order. DOMAIN entries SHALL be skipped. An entry that aborts SHALL be recorded with its abort code and the read SHALL go on. Read-all SHALL work with `allow_changes` false.

#### Scenario: Read-all of the RTD sensor
- **WHEN** a user reads all parameters of node 3, whose EDS lists 180 readable entries and 2 DOMAIN entries
- **THEN** 180 SDO reads are sent, one at a time, and no DOMAIN entry is read

#### Scenario: Entry the device does not have
- **WHEN** the EDS lists 0x2100 subindex 3 but the device aborts the read with 0x06090011
- **THEN** that entry is recorded as not read with abort code 0x06090011 and the next entry is read

#### Scenario: Read-only diagnostics
- **WHEN** the runtime's `allow_changes` is false and a user reads all parameters of node 3
- **THEN** the read completes and nothing is written to the node

### Requirement: Read-all stops on a silent node
A read-all SHALL stop when the node answers none of 3 reads in a row with data or an abort code, and SHALL report that the node does not answer (for example because it is STOPPED) together with the entries read so far. A user SHALL be able to cancel a running read-all.

#### Scenario: Node stopped
- **WHEN** node 23 is in STOPPED and a user reads all its parameters
- **THEN** the read stops after 3 timeouts and says that node 23 does not answer SDO and may be STOPPED

### Requirement: Backup file
A backup SHALL be a CiA 306 DCF: the node's EDS text with a `ParameterValue` for every entry read, encoded as its EDS data type, `[DeviceComissioning]` with the node ID, node name and bit rate, and a `[FileInfo]` description naming the tool, the runtime host and the time of the read. Entries not read SHALL keep no `ParameterValue` and SHALL be listed as comments with their abort code. The file SHALL pass the same CiA 306 lint as the DCF export.

#### Scenario: Backup of node 23
- **WHEN** a user backs up node 23 (a valve) and every readable entry answers
- **THEN** the DCF has the valve EDS's objects, a `ParameterValue` for each entry read, `NodeID=23` and the node's name in `[DeviceComissioning]`, and passes the lint

#### Scenario: String value
- **WHEN** 0x1008 of node 23 reads `VALVE`
- **THEN** the backup has `ParameterValue=VALVE` in section `[1008]`

### Requirement: Identity in the backup
A backup SHALL record the device's vendor ID, product code, revision number and serial number read from 0x1018. When 0x1018 subindex 1 or 2 cannot be read, the backup SHALL still be written and SHALL say that restore cannot check the identity.

#### Scenario: Identity recorded
- **WHEN** node 23 answers 0x1018 subindices 1 to 4
- **THEN** the backup's `ParameterValue` entries for 0x1018 hold those four values

### Requirement: Compare a device
The tools SHALL compare a node's live values with one reference: a backup DCF, the values the configuration writes to that node at boot (the same values as the DCF export), or the EDS `DefaultValue` with `$NODEID` resolved. By default only `rw`, `rwr`, `rww` and `const` entries SHALL be compared; `ro` entries SHALL be compared only when asked. Each entry SHALL be reported as equal, different (with both values decoded), not readable (with the abort code), or without a reference value.

#### Scenario: Replacement device against the old backup
- **WHEN** a user compares node 23 with a backup in which 0x2010 subindex 1 is 5 and the device now has 0
- **THEN** the result lists 0x2010 subindex 1 as different, backup 5, device 0

#### Scenario: Changed from factory defaults
- **WHEN** a user compares node 3 with its EDS defaults and the device has a different 0x6110 subindex 1
- **THEN** that entry is listed as different with the EDS default and the device value

#### Scenario: Measured values left out
- **WHEN** a user compares node 3 with a backup without asking for read-only entries
- **THEN** the RTD temperature inputs (access `ro`) are not compared

### Requirement: Restore scope
A restore SHALL write a backup's `ParameterValue` entries whose EDS access is `rw`, `rwr` or `rww` and whose index is 0x2000 to 0x9FFF. With "include communication objects" it SHALL also write such entries in 0x1000 to 0x1FFF. It SHALL never write 0x1010, 0x1011, 0x1400 to 0x1BFF, or 0x1F50 to 0x1F57, nor an entry that the configuration writes at boot or that a write SDO variable owns. Each left-out entry SHALL be listed with its reason.

#### Scenario: Configuration wins
- **WHEN** the configuration writes 0x2010 subindex 1 at boot and the backup also has a value for it
- **THEN** the restore does not write 0x2010 subindex 1 and lists it as "written by the configuration at boot"

#### Scenario: PDO objects left out
- **WHEN** a restore with communication objects included uses a backup that has values for 0x1600 and 0x1017
- **THEN** 0x1017 is written and 0x1600 is listed as "PDO object, set by the configuration or the device"

### Requirement: Restore preview and order
Before writing, a restore SHALL show the planned writes with backup value, current device value and whether they differ, and SHALL write only entries whose current value differs or could not be read. It SHALL write in ascending index order, and within an object the subindices from 1 upwards before subindex 0. A failed write SHALL be reported with its abort code and the restore SHALL continue; the result SHALL list written, unchanged, skipped and failed entries.

#### Scenario: Only differences written
- **WHEN** a backup has 40 restorable entries and the replacement device already matches 32 of them
- **THEN** the preview shows 8 writes and the restore sends 8 SDO writes

#### Scenario: Device refuses one value
- **WHEN** the device aborts one of the 8 writes with 0x06090030 (value range exceeded)
- **THEN** the other 7 are written and the result lists that entry as failed with the abort text

### Requirement: Restore checks the device
A restore SHALL need `allow_changes` on the runtime and SHALL be refused, sending nothing, when the device's vendor ID or product code differs from the backup's, unless the user explicitly overrides the identity check. A different revision number SHALL be shown as a warning; a different serial number SHALL be shown for information only.

#### Scenario: Wrong device
- **WHEN** a user restores a backup of a valve to a node whose product code differs
- **THEN** the restore is refused, naming product code with both values, and no SDO is written

#### Scenario: Read-only runtime
- **WHEN** `allow_changes` is false
- **THEN** restore is refused with "changes not allowed"

### Requirement: Hold in PRE-OPERATIONAL during restore
A restore SHALL offer to hold the node in PRE-OPERATIONAL while writing (off by default). With it, the node SHALL be put in PRE-OPERATIONAL as an operator hold before the first write and SHALL be started again after the last write, even when some writes failed or the restore was cancelled.

#### Scenario: Drive that only accepts changes in PRE-OPERATIONAL
- **WHEN** a user restores node 7 with the hold option
- **THEN** node 7 is held in PRE-OPERATIONAL, the writes are sent, and node 7 is started again afterwards

### Requirement: Store is a separate action
A restore SHALL NOT write 0x1010. Storing SHALL be a separate action that writes the "save" signature to one 0x1010 subindex chosen by the user (default 1, all parameters), only when the EDS lists that subindex, only with `allow_changes`, and only after the user confirms. The result SHALL say whether the device accepted it.

#### Scenario: Restore without store
- **WHEN** a restore of node 23 finishes
- **THEN** no write to 0x1010 was sent, and the result says the values are lost at power off until stored

#### Scenario: Store after restore
- **WHEN** the user then runs store for node 23 subindex 1 and confirms
- **THEN** exactly one write of `73 61 76 65` ("save") to 0x1010 subindex 1 is sent

#### Scenario: No 0x1010
- **WHEN** a node's EDS has no 0x1010
- **THEN** store is refused, saying the device has no store object

### Requirement: Parameter commands in the command-line client
`canworks-diag` SHALL offer `backup NODE [-o FILE]`, `compare NODE (--with FILE | --with-config | --with-eds-defaults) [--read-only]`, `restore NODE FILE [--include-comm] [--hold-preop] [--ignore-identity] [--dry-run] [--yes]` and `store NODE [--subindex N] [--yes]`. The node's EDS SHALL come from `--config canworks.json` (default `canworks/canworks.json` when present) or `--eds FILE`. Without `--yes`, `restore` and `store` SHALL show the plan and ask for confirmation. A failed entry SHALL make the command exit non-zero.

#### Scenario: Backup from the command line
- **WHEN** `canworks-diag --runtime plc.local backup 23 --config canworks/canworks.json` runs
- **THEN** it writes `node23-<name>-<date>-<time>.dcf` and prints how many entries were read and not read

#### Scenario: Dry run
- **WHEN** `restore 23 old.dcf --dry-run` runs
- **THEN** it prints the planned and skipped entries and writes nothing

#### Scenario: Store needs confirmation
- **WHEN** `store 23` runs without `--yes` and the user answers no
- **THEN** nothing is written and the command exits non-zero

### Requirement: Parameter commands on a network
`backup`, `compare`, `restore` and `store` SHALL take `--network NAME`, which picks both the network the SDOs go to and the node's EDS and configuration from that network in `--config`. With several networks in the runtime or the config, they SHALL fail without it, naming the networks.

#### Scenario: Back up a node on the second network
- **WHEN** the user runs `backup 2 --network drives` with a config that has node 2 on `io` and on `drives`
- **THEN** the node on `drives` is read, using `drives`' node 2 EDS, and the DCF carries `drives`' bit rate
