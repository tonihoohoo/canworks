## ADDED Requirements

### Requirement: Device EDS carried into a config
**Add to a config…** in Commission a device SHALL carry the node's EDS into the opened config when the node has one in Commission: from Add node from EDS…, picked on the node's page or in Trace, or the scan match. The EDS SHALL be added to the config as an unsaved EDS import, and the dialog SHALL NOT ask for the EDS file.

#### Scenario: Node added from an EDS
- **WHEN** the user adds node 23 with Add node from EDS… in Commission a device, presses Add to a config… on node 23's page and picks a standalone config folder without that EDS
- **THEN** the config opens with node 23 added as an unsaved node using that EDS, and no "only EDS files" error is shown

#### Scenario: Same EDS already in the config
- **WHEN** the config folder already holds the identical EDS file
- **THEN** node 23 uses that file and no second copy is added

#### Scenario: Different EDS with the same name
- **WHEN** the config folder holds a different file with the same name
- **THEN** the carried EDS is kept under a new name and node 23 uses it

### Requirement: EDS carry failure keeps Commission
When the node's EDS cannot be carried into the config, the config folder SHALL NOT open. The page SHALL stay in Commission a device with its connection and log, and the banner SHALL name the EDS and the reason.

#### Scenario: EDS cannot be read
- **WHEN** the node's EDS file was removed from the EDS library before Add to a config…
- **THEN** the page stays in Commission a device with the log and connection kept, and the banner names the EDS that could not be carried
