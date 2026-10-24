## ADDED Requirements

### Requirement: Network name from the bus object
Import from CODESYS SHALL take each network's name from its CAN bus object, and from its interface only when the object has the CODESYS default name.

#### Scenario: Round trip of one network
- **WHEN** a config with one network "field" is built into CODESYS and imported back
- **THEN** the imported network is named "field"

### Requirement: Clash reason in the import
When an imported network clashes with one in the open config, the import dialog SHALL say why (same name, or same CODESYS network number) and SHALL name both roles when a master would replace a slave network.

#### Scenario: Same network number
- **WHEN** imported master network host is CODESYS network 2 and the open config's slave network cell is network 2
- **THEN** the dialog says both are CODESYS network 2 and the replace button reads "Replace the slave network cell with the master host"
