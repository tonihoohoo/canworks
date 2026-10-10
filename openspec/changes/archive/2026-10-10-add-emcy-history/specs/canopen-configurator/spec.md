## ADDED Requirements

### Requirement: Device error history in the online view
A node's page in the online view SHALL show, under its EMCY history, an "Error history (0x1003)" section with the count and the entries as the diagnostics' device error history defines them, a Refresh button and a Clear button. Clear SHALL be disabled with the reason when the runtime or the local adapter session does not allow changes; otherwise it SHALL ask for confirmation naming the node and the number of entries, with Cancel as the default, and when the node is OPERATIONAL a second confirmation SHALL say that the node is running and offer to force the write. After a clear the section SHALL read the history again.

#### Scenario: History shown
- **WHEN** the user opens node 5 in the online view and node 5's 0x1003 holds 2 entries
- **THEN** the section shows count 2 and both entries, newest first, with code, class and manufacturer information

#### Scenario: Clear without changes allowed
- **WHEN** the runtime does not allow changes
- **THEN** the Clear button is disabled and says that changes are not allowed

#### Scenario: Clear a running node
- **WHEN** changes are allowed, node 5 is OPERATIONAL and the user clicks Clear and confirms
- **THEN** the page asks again, saying node 5 is OPERATIONAL; after the user confirms the forced write, the section shows count 0

### Requirement: EMCY COB-ID on the node page
The node page's Emergency (EMCY) section SHALL edit `emcy_cob_id`: Device (the default, saved as no field), EDS, or a COB-ID typed in hex or decimal. The Check SHALL give the plugin's messages for a COB-ID the plugin rejects. The online view's node row SHALL show the EMCY COB-ID in use, with its source, when it is not 0x80 + node ID, and SHALL mark it when the device reports its EMCY not valid.

#### Scenario: Default not saved
- **WHEN** the user leaves the EMCY COB-ID on Device and saves
- **THEN** the saved node has no `emcy_cob_id`

#### Scenario: Clashing COB-ID typed
- **WHEN** the user types node 6's TPDO 1 COB-ID as node 5's EMCY COB-ID
- **THEN** the Check reports node 5's `emcy_cob_id` clashing with node 6's TPDO 1
