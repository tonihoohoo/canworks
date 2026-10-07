## MODIFIED Requirements

### Requirement: PDO details
For each configured PDO the node sheet SHALL show its number and direction, COB-ID, transmission type (marked when taken from the EDS), inhibit time, event timer and SYNC start value where they apply, for a TPDO with `timeout_ms` the resolved receive timeout (marked "auto" when derived), `on_timeout` and the timeout bit's address, and whether the master writes the mapping or the device's mapping is kept. It SHALL show the mapping as a byte grid of the frame with each mapped object spanning its bits, and as a table with bit offset, length, object index and sub-index, the object's name from the EDS, data type, PLC address and, in editor-project mode, the PLC variable name. Mapped objects that no PLC address uses and dummy entries SHALL be shown as such.

#### Scenario: Device mapping kept
- **WHEN** a TPDO keeps the device's mapping and the config maps only one of its three objects
- **THEN** all three objects appear in the layout and two are shown as not used by the PLC

#### Scenario: PLC variable names
- **WHEN** the export runs on an editor project's `canopen/canopen.json` and `%IW100` is declared as `rtd_ch1`
- **THEN** the PDO table shows `rtd_ch1` next to `%IW100`

#### Scenario: Receive timeout shown
- **WHEN** a TPDO has `"timeout_ms": "auto"` resolving to 200 ms and `"timeout_location": "%IX20.0"`
- **THEN** its details show "timeout 200 ms (auto), hold" and `%IX20.0`, and `%IX20.0` appears in the PLC I/O cross-reference
