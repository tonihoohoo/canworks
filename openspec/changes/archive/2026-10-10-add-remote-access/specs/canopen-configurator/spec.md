## ADDED Requirements

### Requirement: Discovered and remembered runtimes in the connect box
The online view's connect box SHALL list runtimes found by discovery and remembered runtimes by name, next to typing an address. Choosing one SHALL connect by the automatic path choice; the user SHALL never have to choose between the local network and the link.

#### Scenario: Pick a discovered runtime
- **WHEN** the connect box opens on a LAN with one advertised runtime
- **THEN** the runtime is listed by name and address, and choosing it and entering the token connects

#### Scenario: Same runtime from home
- **WHEN** the user picks the same runtime later from another network and the PC is paired and internet access is on
- **THEN** the online view connects with the same steps and shows `internet direct` or `internet relayed`

### Requirement: Automatic pairing and paired PCs
After a successful direct login to a runtime that advertises a link ID, the configurator SHALL pair the PC with the same token in the background. The Online access section SHALL show **Reachable from other networks** (sets `remote_link.internet`), an optional relay URL list, and, on **Show paired PCs** when this PC knows the token and the runtime has a link ID, the paired PCs with **Remove**. When internet access is on and the PC has just been paired, the online view SHALL say once that this PC can now reach the runtime from other networks.

#### Scenario: Tick internet access
- **WHEN** the user ticks **Reachable from other networks**, saves and uploads
- **THEN** the config has `remote_link.internet` true and the runtime becomes reachable from other networks for paired PCs

#### Scenario: Remove a PC
- **WHEN** the user presses **Remove** next to a paired PC
- **THEN** that PC is removed and its open sessions end

### Requirement: Path and round trip in the online view
The online view SHALL show the path (`LAN`, `internet direct`, `internet relayed`) and the measured round trip, amber above 100 ms and red above 300 ms. LSS fast scan and a PDO test with a SYNC period SHALL ask for confirmation when the path is relayed or the round trip is above 100 ms.

#### Scenario: LSS on a relayed path
- **WHEN** the path is `internet relayed` and the user starts an LSS fast scan
- **THEN** a confirmation explains that the scan runs on the runtime but results and stop commands arrive late, and nothing is sent until the user confirms
