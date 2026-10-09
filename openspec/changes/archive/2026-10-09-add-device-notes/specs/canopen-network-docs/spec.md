## MODIFIED Requirements

### Requirement: Boot configuration
For each node the document SHALL list, in the order the master performs them, every SDO write of the node's boot configuration with object index and sub-index, the object's name, the value written (as a number and, when the object's merged note (see `canopen-device-notes`) has a meaning for it, that meaning; for COB-IDs, the COB-ID bits), the note's unit and `text` when it has them, the object's access and EDS default, and where the write comes from (PDO configuration, node settings, startup SDO, configuration check). It SHALL list the boot steps that are not settings (restore defaults, program download, store) in their place. The list SHALL match the DCF export's writes for the node.

#### Scenario: Startup SDO
- **WHEN** node 5 has a startup SDO writing 30 to 0x6110 sub 1
- **THEN** the boot list has that write with source "startup SDO" after the PDO configuration writes

#### Scenario: Same as DCF
- **WHEN** the DCF export gives node 4 thirty-nine writes
- **THEN** the boot list of node 4 has the same thirty-nine writes in the same order

#### Scenario: Startup SDO with a note
- **WHEN** node 7's notes give 0x2011:2 the text "What the valve does on a bus fault" and the value 1 "close", and a startup SDO writes 1 to it
- **THEN** the boot list shows the write as `1 (close)` with that text

### Requirement: PDO details
For each configured PDO the node sheet SHALL show its number and direction, COB-ID, transmission type (marked when taken from the EDS), inhibit time, event timer and SYNC start value where they apply, for a TPDO with `timeout_ms` the resolved receive timeout (marked "auto" when derived), `on_timeout` and the timeout bit's address, and whether the master writes the mapping or the device's mapping is kept. It SHALL show the mapping as a byte grid of the frame with each mapped object spanning its bits, and as a table with bit offset, length, object index and sub-index, the object's name from the EDS, its note `text` and unit when its merged note has them, data type, PLC address and, in editor-project mode, the PLC variable name. Mapped objects that no PLC address uses and dummy entries SHALL be shown as such.

#### Scenario: Device mapping kept
- **WHEN** a TPDO keeps the device's mapping and the config maps only one of its three objects
- **THEN** all three objects appear in the layout and two are shown as not used by the PLC

#### Scenario: PLC variable names
- **WHEN** the export runs on an editor project's `canworks/canworks.json` and `%IW100` is declared as `rtd_ch1`
- **THEN** the PDO table shows `rtd_ch1` next to `%IW100`

#### Scenario: Receive timeout shown
- **WHEN** a TPDO has `"timeout_ms": "auto"` resolving to 200 ms and `"timeout_location": "%IX20.0"`
- **THEN** its details show "timeout 200 ms (auto), hold" and `%IX20.0`, and `%IX20.0` appears in the PLC I/O cross-reference
