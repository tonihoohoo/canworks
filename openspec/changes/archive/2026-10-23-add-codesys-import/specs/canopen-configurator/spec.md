## ADDED Requirements

### Requirement: Import from CODESYS
The start page and a CODESYS config's CODESYS page SHALL offer **Import from CODESYS…**. Its file dialog SHALL list CODESYS `.project` files only when CODESYS is found on this PC (otherwise it says to export PLCopenXML in CODESYS and lists `.xml` files only) and PLCopenXML `.xml` files; then it SHALL show the device list when the file has several devices with a CANopen Manager, then the import preview. Nothing SHALL be written before Create config or Add to this config.

#### Scenario: No CODESYS on this PC
- **WHEN** the user opens Import from CODESYS… on a Mac
- **THEN** the dialog says to export PLCopenXML in CODESYS and pick that file, and lists no `.project` files

### Requirement: Import preview
The preview SHALL show each network and node, each node's EDS state (in this config / from the library / from CODESYS on this PC / added / missing) and the not-carried list. **Add EDS…** on a node SHALL give every node of that CODESYS device type the EDS. Create config and Add to this config SHALL stay disabled while a node has no EDS.

#### Scenario: Missing EDS
- **WHEN** no EDS matches node `rtd`
- **THEN** its row says EDS missing with Add EDS…, and Create config is disabled until an EDS is added

#### Scenario: Cancel
- **WHEN** the user closes the preview
- **THEN** no file is written

### Requirement: Create config from an import
**Create config…** SHALL ask for a name and location and write a new CODESYS config with its EDS files, `codesys.project` set to the imported project (when it came from one) and `codesys.device` to the chosen device.

#### Scenario: Import a project
- **WHEN** the user imports `C:\Projects\line2.project`, picks `PLC` and presses Create config
- **THEN** a new CODESYS config opens with the project's networks and nodes, its CODESYS page names `line2.project` and device `PLC`, and Build into CODESYS project reports every device up to date

### Requirement: Add an import to this config
With a CODESYS config open, **Add to this config** SHALL add the imported networks to the draft, which Save writes. An imported network whose name or CODESYS network number the config uses already SHALL ask **Add it as a new network** (a new name and, when needed, a free network number) or **Replace** the config's network.

#### Scenario: Same network twice
- **WHEN** the user adds an import whose network `io` the config already has, and answers Add it as a new network
- **THEN** the draft has `io` and `io2` on different network numbers

### Requirement: Build asks before removing nodes
When a build would remove project nodes that canworks managed earlier (`codesys.managed`) and that are no longer in the config, Build SHALL list them by network and node ID and ask **Remove N nodes** or **Keep them**; Keep SHALL build without removing them. After a build each CANopen master network's `codesys.managed` SHALL be its node IDs, so kept nodes leave the list and the next build does not ask again.

#### Scenario: Node deleted in canworks
- **WHEN** node `new_io` (node 7) was deleted in the configurator and the user presses Build
- **THEN** the dialog names node 7 and asks before building

#### Scenario: Keep them
- **WHEN** the user answers Keep them
- **THEN** node 7 stays in the project and the saved config's `managed` list no longer has 7
