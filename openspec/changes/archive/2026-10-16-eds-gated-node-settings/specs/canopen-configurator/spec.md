## ADDED Requirements

### Requirement: EMCY section follows the EDS
When the node's EDS has no object 0x1014, the Emergency (EMCY) section SHALL stay in place with all its controls disabled, and SHALL say in hint text that the EDS has no EMCY COB-ID (0x1014), so the device sends no emergency messages. Such a node SHALL be saved without EMCY fields. A loaded node that still has one SHALL show the plugin's message and offer to remove the EMCY settings; saving SHALL be refused until they are removed.

#### Scenario: Device without EMCY
- **WHEN** the user opens the Supervision tab of a node whose EDS has no 0x1014
- **THEN** the EMCY fields, Suggest buttons and COB-ID choice are disabled, the section says the EDS has no 0x1014, and the saved node has no EMCY field

#### Scenario: Leftover EMCY mapping
- **WHEN** a loaded config gives `emcy_code_location` `%IW30` for a node whose EDS has no 0x1014
- **THEN** the section shows the problem in warning colour with "Remove the EMCY settings", and Save is refused until the user presses it

### Requirement: Heartbeat consumer choice follows the EDS
When the node's EDS has no object 0x1016 with a writable sub-index, "Watches the master heartbeat" SHALL show "EDS default", be disabled, and say in hint text that the EDS has no consumer heartbeat time (0x1016), so the device cannot watch the master's heartbeat. A loaded node that still has `heartbeat_consumer` SHALL show it as a problem with the plugin's message and offer to remove it; saving SHALL be refused until it is removed.

#### Scenario: Device without 0x1016
- **WHEN** the user opens Advanced node settings of a node whose EDS has no 0x1016
- **THEN** the choice is disabled on "EDS default" with the reason, and the saved node has no `heartbeat_consumer`

### Requirement: One look for EDS limits
The reason why a node setting is disabled because the node's EDS lacks what it needs (LSS, 0x1020, 0x1010, 0x1014, 0x1016) SHALL be shown as hint text, in the same colour and size as the other hints of the page. Warning colour SHALL be used only when the config still has a setting the EDS cannot back, together with a way to remove it.

#### Scenario: Same colour for LSS and configuration check
- **WHEN** a node's EDS has no LSS and no 0x1020, and its config has neither `lss` nor `config_check`
- **THEN** the LSS reason and the Configuration check reason have the same text colour, in light and dark theme

## MODIFIED Requirements

### Requirement: LSS node settings
For each node the configurator SHALL show an "Assign node ID by serial number (LSS)" checkbox, saved as `lss.assign`, and a "Store node ID in the device" checkbox, saved as `lss.store`, which SHALL be unticked for a new node and disabled while the first is unticked. Unticked boxes SHALL be left out of the saved node, and an `lss` object with nothing in it SHALL be left out. While "Assign" is ticked the node's serial number field SHALL be required, `reset_communication` SHALL not be selectable as off, and the page SHALL say that the master gives the device this node ID at every start. When the node's EDS does not say `LSS_Supported=1` (left out or 0), both checkboxes SHALL be disabled and unticked, with the reason next to them as hint text ("This device's EDS has no LSS (LSS_Supported=1 missing)", see "One look for EDS limits"). A loaded node that still has an `lss` object SHALL show it as a problem with the plugin's message in warning colour and offer to remove it. Saving SHALL be refused until it is removed or the node gets an EDS with LSS.

#### Scenario: Turn on LSS for a node
- **WHEN** the user ticks "Assign node ID by serial number (LSS)" for node 12, enters serial number 0x1234 and saves
- **THEN** node 12 has `"lss": {"assign": true}` and `"serial_number"` 0x1234 (kept as typed, like the other identity fields), and no `lss.store`

#### Scenario: Assign without a serial number
- **WHEN** "Assign" is ticked for node 12 and its serial number is empty
- **THEN** saving is refused and the serial number field says it is needed for LSS

#### Scenario: EDS without LSS
- **WHEN** the user adds a node whose EDS says `LSS_Supported=0`
- **THEN** both LSS checkboxes are disabled with the reason in hint text, and the saved node has no `lss`

#### Scenario: Leftover LSS settings
- **WHEN** a loaded config gives `"lss": {"assign": true}` for a node whose EDS says `LSS_Supported=0`
- **THEN** the reason is shown in warning colour with "Remove the LSS settings"
