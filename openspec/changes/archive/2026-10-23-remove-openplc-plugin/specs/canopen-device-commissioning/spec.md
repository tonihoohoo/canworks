## MODIFIED Requirements

### Requirement: Write a configuration to a device
The PC tools SHALL write a node's configuration to a live device over SDO from one of two sources: a node of a `canworks.json` (the writes the bridge makes to that node at boot, in the same order) or a CiA 306 DCF (every entry with access `rw`, `rwr` or `rww` that has a `ParameterValue`, with `$NODEID` resolved by the target node ID). They SHALL leave out, and list with the reason, 0x1010, 0x1011, 0x1F50 to 0x1F57, DOMAIN entries and DCF entries without an access type. It SHALL run on the PC over `sdo_read`, `sdo_write` and `nmt`, on a runtime and on a USB adapter, and SHALL need allow-changes.

#### Scenario: Configure from a config node over an adapter
- **WHEN** node 5 of a standalone config maps TPDO1 to two entries and has one startup SDO, and the user runs `canworks-diag --adapter slcan:COM5 --bitrate 250 --allow-changes configure 5 --config canworks.json --from-node 5 --yes` against a device at node 5
- **THEN** the device's 0x1A00 mapping, its 0x1800 parameters and the startup SDO entry hold the config's values, and the result says "verified"

#### Scenario: Configure from a DCF
- **WHEN** the user runs `configure 5 --dcf node5.dcf` with a DCF exported for node 5
- **THEN** each writable entry of the DCF that differs on the device is written, and 0x1010 is not written

#### Scenario: Without allow-changes
- **WHEN** `configure` runs on a connection without allow-changes
- **THEN** it is refused with "changes not allowed" and nothing is written
