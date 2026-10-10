## ADDED Requirements

### Requirement: Discovered and linked runtimes in the connect box
The online view's connect box SHALL list runtimes found by discovery and runtimes saved for the remote link, next to typing an address. Choosing a link runtime SHALL open the link from the configurator's server for as long as the online view is connected.

#### Scenario: Pick a discovered runtime
- **WHEN** the connect box opens on a LAN with one advertised runtime
- **THEN** the runtime is listed by name and address, and choosing it fills the address

#### Scenario: Pick a link runtime
- **WHEN** the user chooses a saved link runtime and enters the token
- **THEN** the online view connects over the link and shows `link direct` or `link relayed`

### Requirement: Path and round trip in the online view
The online view SHALL show the path (`LAN`, `link direct`, `link relayed`) and the measured round trip, amber above 100 ms and red above 300 ms. LSS fast scan and a PDO test with a SYNC period SHALL ask for confirmation when the path is relayed or the round trip is above 100 ms.

#### Scenario: LSS on a relayed path
- **WHEN** the path is `link relayed` and the user starts an LSS fast scan
- **THEN** a confirmation explains that the scan runs on the runtime but results and stop commands arrive late, and nothing is sent until the user confirms
