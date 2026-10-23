## MODIFIED Requirements

### Requirement: Re-runnable
Running the script again SHALL update each remote device under the network's manager that has the node ID of a node in the plan in place: it SHALL change only the settings whose project value differs from the plan, and SHALL leave every other setting of that device, including settings canworks does not manage, as it is. A device whose PDO mapping layout or user startup SDO list differs in structure from the plan (an entry or row added, removed, reordered or of another length) SHALL be replaced from its DCF instead, and then get the plan's carried CODESYS settings. Devices with node IDs not in the plan SHALL be kept unless the plan lists them for removal. It SHALL NOT add a second CANbus or manager for a network that already has one. The report SHALL list updated settings per device, replaced devices with the reason, added, removed and kept devices.

#### Scenario: Run twice
- **WHEN** the script runs twice on the same project and plan
- **THEN** the project has one CANbus, one manager and one device per node, and the second report says every device was up to date

#### Scenario: Event timer changed
- **WHEN** only TPDO1's event timer of node `rtd` changed from 100 to 200 ms in the config
- **THEN** that value is the only change in the project, and a fixed I/O address set in CODESYS on another `rtd` channel is kept

#### Scenario: Mapping entry added
- **WHEN** an entry was added to TPDO1 of `dio` in the config
- **THEN** `dio` is replaced from its DCF, its carried settings are written back, and the report names `dio` with "PDO mapping changed"

#### Scenario: Device added by hand
- **WHEN** the user added a device with node ID 20 that is not in the plan
- **THEN** it stays and the report lists it as not managed by canworks

#### Scenario: Node removed in canworks
- **WHEN** node 7 was built by canworks earlier and is no longer in the config, and the plan lists it for removal
- **THEN** device 7 is removed and the report says so

### Requirement: Nodes from their DCF
For each node that is new in the project or replaced, the script SHALL install the node's DCF in CODESYS's device repository and add it under the manager before installing the next DCF, name the device after the node (or its carried CODESYS name), and apply the plan's device settings and carried CODESYS settings. PDO communication parameters, PDO mappings, heartbeat and guarding settings and startup SDOs of a new or replaced node SHALL come from the DCF.

#### Scenario: Three drives of one product
- **WHEN** nodes 4, 5 and 6 use the same EDS with different COB-IDs
- **THEN** each CODESYS device has its own node's COB-IDs and mapping

#### Scenario: Startup SDOs
- **WHEN** node 4 has startup SDOs 0x6065 = 20000 and 0x6098 = 21
- **THEN** the CODESYS device's SDO list writes both with those values

## ADDED Requirements

### Requirement: Carried CODESYS settings written back
The script SHALL write a node's carried CODESYS settings: the device name, "processed by the manager" per PDO, fixed I/O addresses and variable names per entry and abort-on-error / jump-to-line per user startup SDO. It SHALL set the identity-check ticks, and the manager's TIME producer when the master has a TIME COB-ID, when this CODESYS lets the script change them, and otherwise SHALL report which to set by hand.

#### Scenario: Identity checks
- **WHEN** node `dio` has `"codesys": {"checks": ["vendor", "revision"]}`
- **THEN** the CODESYS device checks vendor ID and revision at startup and not product code, or the report names the ticks to set

### Requirement: PDO COB-IDs follow the node ID
The script SHALL write each PDO COB-ID through CODESYS's generic COB-ID setting, as `$NODEID+16#…` when it equals the EDS's node-based default for that PDO and as the literal value otherwise, so a later node ID change in CODESYS moves default COB-IDs with it.

#### Scenario: Node ID changed in canworks
- **WHEN** node `rtd` moves from node ID 5 to 6 and its TPDO1 uses the default COB-ID
- **THEN** after the build its TPDO1 COB-ID is 0x186

### Requirement: DCF mapping as CODESYS reads it
The DCFs written for CODESYS SHALL set every PDO mapping sub-entry beyond the mapped count that has a non-zero default to 0, because CODESYS maps every sub-entry with a value regardless of the count.

#### Scenario: Shorter mapping than the EDS default
- **WHEN** a TPDO's EDS default maps 4 entries and the config maps 2
- **THEN** the DCF gives sub-entries 3 and 4 the value 0, and CODESYS shows 2 mapped entries
