## MODIFIED Requirements

### Requirement: Explicit IEC location per PDO entry
Each PDO entry in the configuration SHALL name its object index, subindex, and data type, and SHALL give one explicit location in the bridge's byte image (byte-addressed, as "Bridge configs are byte-addressed" requires). Entries received from a slave (RPDO on the master) SHALL map to input locations (`%IB`, or `%IX` for a BOOLEAN). Entries sent to a slave (TPDO on the master) SHALL map to output locations (`%QB`, or `%QX` for a BOOLEAN). Addresses SHALL NOT be assigned automatically by the bridge; the configurator's "Pack for Modbus" assigns them before save.

#### Scenario: Entry mapped to a matching location
- **WHEN** a slave-to-master UNSIGNED16 entry is configured with `iec_location` `%IB100`
- **THEN** the value received in that PDO appears in input bytes 100 and 101 of the bridge image, in the bridge's byte order

#### Scenario: Direction or size mismatch
- **WHEN** an entry received from a slave is given an output location, or an entry's data type does not fit in the image from its location
- **THEN** the bridge rejects the configuration and names the node ID, the object, and the location

#### Scenario: Overlapping locations
- **WHEN** two PDO entries map to the same or overlapping bytes
- **THEN** the bridge rejects the configuration and names both entries

#### Scenario: Location outside the image
- **WHEN** an entry's location lies outside the bridge's image
- **THEN** the bridge rejects the configuration and names the entry and the location

#### Scenario: Word location from the plugin
- **WHEN** an entry has `iec_location` `%IW100`
- **THEN** the bridge rejects the configuration, naming the entry and saying locations are byte-addressed

### Requirement: Bit channels of a PDO entry
A PDO entry of an integer type (INTEGER8 to INTEGER64, UNSIGNED8 to UNSIGNED64) MAY list `bits`, each with a bit number `bit` and an optional `name`. Bit 0 SHALL be the least significant bit of the entry's value. Bit channels SHALL have no location of their own: they name bits of the entry's value, which the bridge serves at the entry's location, and the generated program side (`canworks_in`/`canworks_out`) or a Modbus client reads or sets them there. Bit names SHALL be unique within the node together with the entry names, ignoring case (checked by the PC tools). The bridge SHALL reject, naming the node, the PDO, the object and the bit: `bits` on a BOOLEAN, REAL32 or REAL64 entry, a bit number outside the type's size, a bit listed twice, and a bit channel with an `iec_location`.

#### Scenario: Input bits
- **WHEN** node 11's TPDO1 entry 0x6000:1 (UNSIGNED8) at `%IB140` has bits 0 and 3 named `door` and `lamp_ok`
- **THEN** the configuration is accepted, and an OpenPLC project gets BOOL variables `door` and `lamp_ok` from bits 0 and 3 of that byte

#### Scenario: Output entry with a location and bits
- **WHEN** an RPDO entry 0x6200:1 at `%QB40` has a bit with `iec_location` `%QX140.0`
- **THEN** the bridge rejects the configuration and names the node, the RPDO, the object and the bit

#### Scenario: Bit past the type
- **WHEN** an UNSIGNED8 entry lists bit 8
- **THEN** the bridge rejects the configuration and names the entry and bit 8

#### Scenario: Bits on a REAL
- **WHEN** a REAL32 entry lists bits
- **THEN** the bridge rejects the configuration and names the entry

#### Scenario: Overlap with another location
- **WHEN** a bit channel's entry is at `%IB10` and the same node's status byte is also `%IB10`
- **THEN** the bridge rejects the configuration and names both

## REMOVED Requirements

### Requirement: Exchange once per scan cycle
**Reason**: The plugin exchanged PDO data with the PLC image in the scan; the bridge exchanges it with its byte image and Modbus clients (modbus-bridge "Outputs without a scan", "Consistent requests").
**Migration**: None.

### Requirement: No blocking in the scan path
**Reason**: There is no PLC scan inside canworks any more.
**Migration**: None.

### Requirement: PDO timing with PLC-cycle SYNC
**Reason**: SYNC from the PLC cycle is removed.
**Migration**: Timer SYNC.

### Requirement: Scan watchdog
**Reason**: The scan watchdog watched the PLC scan from inside the runtime; the bridge's output watchdog and change 1's PLC link header take its place.
**Migration**: `bridge.watchdog_ms` and `on_client_loss`.

### Requirement: Scan watchdog across bus restarts
**Reason**: The scan watchdog is removed with the plugin.
**Migration**: `bridge.watchdog_ms` and `on_client_loss`.

### Requirement: Scan watchdog trip lasts until the scan moves
**Reason**: The scan watchdog is removed with the plugin.
**Migration**: `bridge.watchdog_ms` and `on_client_loss`.

### Requirement: Program frames obey the outputs gate
**Reason**: Program frames came from the plugin's frame blocks, which are removed; frames from change 3's mailboxes get their own rule there.
**Migration**: None.

### Requirement: Scan watchdog for every protocol
**Reason**: The scan watchdog is removed with the plugin; `scan_watchdog_ms` leaves the schema.
**Migration**: `bridge.watchdog_ms` and `on_client_loss`.

### Requirement: Bit channels exchanged with the scan
**Reason**: Bit channels had their own `%IX`/`%QX` locations only in plugin configs; on the bridge they are bits of the entry's value.
**Migration**: The generated `canworks_in`/`canworks_out` programs give each bit its BOOL variable.
