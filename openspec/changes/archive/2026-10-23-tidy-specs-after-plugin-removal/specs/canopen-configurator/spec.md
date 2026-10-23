## MODIFIED Requirements

### Requirement: Choose what to edit
Started without arguments, the configurator SHALL open a start page with one line saying what the tool is for (setting up CANopen and J1939 networks for a PLC, working on a CANopen device directly from the PC, and installing canworks on a Linux device), two buttons, **Open…** and **New config…**, two links, **Commission a device without a config** and **Install on a device**, and the **Recent** list as the page's main content. The page SHALL NOT show a folder browser of its own; Open… and New config… SHALL pick folders in the configurator's folder dialog.

Open… SHALL open the picked folder as an OpenPLC Editor project when it has `project.json` (editing its `canworks/` folder and checking addresses against its program), else as a config folder when it has `canworks.json`. A folder with neither SHALL get one question offering to start a new config there, which opens New config… with that folder filled in.

Each Recent entry SHALL show the folder's name, its path, a tag with the config's target (Modbus bridge or CODESYS, or "OpenPLC plugin (removed)" for a config of the removed plugin; none when the config cannot be read) and whether it is an editor project or a config folder, and when it was last opened when known. One click or Enter SHALL open it, and each entry SHALL have a Remove button that takes it off the list and leaves the folder alone. With nothing in Recent, the page SHALL show four short starting choices in its place, each in one sentence of plain words: open an OpenPLC project (Open…), start something new (New config…), talk to a device with a USB CAN adapter (Commission), and set up a Linux device (Install on a device). The start page SHALL NOT use the words "standalone", "canworks.json", "LSS" or "object dictionary", and SHALL NOT name a board brand.

A path given on the command line SHALL open directly, as a project when the folder has `project.json` and as a config folder otherwise. The current mode SHALL always be visible.

#### Scenario: Start page
- **WHEN** `canworks-config` runs without arguments in a 1280 px wide window and Recent has entries
- **THEN** the browser shows the purpose line, Open… and New config…, the Commission and Install on a device links and the Recent list, with no folder browser and no clipped text

#### Scenario: First run
- **WHEN** `canworks-config` runs with an empty Recent
- **THEN** the page shows the four starting choices instead of the list, and each runs the same action as Open…, New config…, the Commission link or the Install on a device link

#### Scenario: Open a project from the start page
- **WHEN** the user chooses Open… and picks `~/Documents/workspace/rtd-monitor`, which has `project.json` and `canworks/canworks.json`
- **THEN** the page shows that config with the mode "project rtd-monitor"

#### Scenario: Open a config folder
- **WHEN** the user chooses Open… and picks `~/canworks/rtd`, which has `canworks.json` and no `project.json`
- **THEN** the page shows that config as a config folder

#### Scenario: Project without a config
- **WHEN** the user opens an OpenPLC Editor project that has no `canworks/` folder
- **THEN** the page shows an empty config and the project folder is unchanged until the user saves

#### Scenario: Not an editor project
- **WHEN** the user chooses Open… and picks a folder with neither `project.json` nor `canworks.json`
- **THEN** the page asks whether to start a new config there, and Yes opens New config… with that folder

#### Scenario: Recent shows the target
- **WHEN** Recent holds a Modbus bridge config folder and a CODESYS config
- **THEN** their entries are tagged "Modbus bridge" and "CODESYS", and one click on either opens it

### Requirement: Import an EDS
Adding a node SHALL start from an EDS file the user picks. The configurator SHALL check that it is a CiA 306 EDS the deploy tool accepts, store it under `canworks/` as UTF-8 (converting from Latin-1/CP1252 when it is not valid UTF-8) and refer to it by a path relative to `canworks/`. A different file with the same name SHALL NOT be overwritten silently. When "keep both" gives the new EDS another name, it SHALL get its own notes file (see `canopen-device-notes`), and replacing an EDS SHALL keep its notes file.

At import, the configurator SHALL also run the checks the bridge runs before dcfgen, on the same prepared copy (see `canopen-master-bringup`, "Prepared EDS copy"): dcfgen's EDS read and lint, and Lely's EDS parse rules, sorting the lint findings as the bridge does (see `canopen-master-bringup`, "EDS lint scope") under the config's `eds_lint` setting. The import SHALL show:
- that the file is readable, when nothing below applies;
- the corrections made in the prepared copy (UTF-8 conversion, `$NODEID` rewrites, REAL rewrite, cleared OCTET_STRING values), as described below;
- findings that do not stop the bridge, as a collapsed list with each finding's object, saying they are accepted.

The correction report SHALL name the imported file, SHALL say that the file is kept as imported, and SHALL name who reads the corrected copy for the project's target: canworks-bridge, the Modbus bridge, or, for a node under a CODESYS target, the DCFs exported to CODESYS, which are built from it. A slave EDS import under a CODESYS target SHALL name canworks as the reader. Each kind of correction SHALL be listed on its own line with how many values it changed, in words that read correctly for one value and for several. Under a CODESYS target, a node import SHALL NOT list the REAL rewrite, since the exported DCFs write REAL values as decimals. The UTF-8 conversion, which changes the stored file, SHALL be reported on its own line as before.

The import SHALL be refused, showing the reason, and no node SHALL be added, when dcfgen or Lely cannot read the file even after the corrections, or when the lint has findings that would stop the bridge.

#### Scenario: Latin-1 vendor EDS
- **WHEN** the user imports `vendor.eds`, encoded in Latin-1 with `°C` in a ParameterName
- **THEN** on save `canworks/vendor.eds` is valid UTF-8 with the same text and the node's `eds` is `vendor.eds`

#### Scenario: Not an EDS
- **WHEN** the user picks a file without objects 0x1000 and 0x1018
- **THEN** the import is refused with the reason and no node is added

#### Scenario: Same name, different content
- **WHEN** an imported EDS has the same name as a different EDS already in `canworks/`
- **THEN** the user is asked to replace it or keep both under a new name, and nothing is overwritten without that choice

#### Scenario: Vendor EDS with findings in profile objects
- **WHEN** the user imports a drive EDS with signed limits written as unsigned hex in its profile objects
- **THEN** the node is added and the import shows its findings as accepted, listed collapsed with their objects

#### Scenario: Finding in a communication object
- **WHEN** the user imports an EDS whose 0x1A00 sub 0 has the data type UNSIGNED16, and `eds_lint` is unset
- **THEN** the import is refused, the finding in 0x1A00 sub 0 is shown, and no node is added

#### Scenario: Notes file for a new EDS
- **WHEN** the user imports `valve.eds`, which has no notes file, adds the node and saves
- **THEN** `canworks/valve.eds.notes.json` is written with the valve's identity and an entry for each manufacturer object

#### Scenario: $NODEID rewrite reported for OpenPLC
- **WHEN** the project target is Modbus bridge with an OpenPLC connection and the user adds a node from `valve.eds`, which has 8 values written `<number>+$NODEID`
- **THEN** the banner names `valve.eds`, says it is kept as imported and that canworks-bridge reads a corrected copy, and lists that 8 values written `<number>+$NODEID` are read as `$NODEID+<number>`

#### Scenario: One rewritten value
- **WHEN** the imported EDS has exactly one value written `<number>+$NODEID`
- **THEN** the line reads as one value ("1 value ... is read as"), not "1 values"

#### Scenario: $NODEID rewrite reported for CODESYS
- **WHEN** the project target is CODESYS and the user adds a node from the same `valve.eds`
- **THEN** the banner names `valve.eds`, says it is kept as imported and that the DCFs exported to CODESYS are built from a corrected copy, and lists the 8 rewritten values

#### Scenario: REAL rewrite only, CODESYS
- **WHEN** the project target is CODESYS and the only correction an imported EDS needs is decimal REAL values
- **THEN** no correction is listed, and the banner says the file is readable when nothing else applies

### Requirement: Node tabs
A node page in Configure SHALL show its heading, Export DCF and Remove node above a tab list, and SHALL show one tab at a time:
- **General**: node ID, name, EDS and Simulated, and the EDS error when the EDS cannot be read;
- **PDOs** (see "PDOs tab");
- **SDOs** (see "SDOs tab");
- **Supervision**: heartbeat or guarding, status bit, state byte, NMT command, boot error byte, EMCY code, error register and EMCY COB-ID;
- **Simulation**, shown only for a simulated node (see "Simulation tab of a node");
- **Notes** (see "Notes tab");
- **Advanced**.

The tabs SHALL follow the page's tab pattern. Opening another node SHALL keep the open tab when that node has it, and open General otherwise. The open tab SHALL come back after a page reload. A node just added SHALL open on PDOs when its default PDOs were mapped, else on General, whatever tab another node had open. Objects SHALL be mapped from within the PDO they go into ("Add entry…" per PDO, listing that direction's mappable objects), with "Map all" kept for device-mapped PDOs.

#### Scenario: Compare heartbeats across nodes
- **WHEN** the user is on node 5's Supervision tab and opens node 7 in the tree
- **THEN** node 7's Supervision tab is shown

#### Scenario: No CiA 402 tab for an I/O module
- **WHEN** the user opens a node whose EDS has neither 0x6040 nor 0x6041
- **THEN** the node has no CiA 402 tab

#### Scenario: Drive has the same tabs
- **WHEN** the user opens a node whose EDS has 0x6040 and 0x6041
- **THEN** it has the same tabs as any other node, and no tab for drive or axis settings

#### Scenario: Reload keeps the tab
- **WHEN** the user is on node 5's PDOs tab and reloads the page
- **THEN** node 5's PDOs tab is shown

#### Scenario: Add an entry from the PDO
- **WHEN** the user clicks "Add entry…" on TPDO 1 and picks 0x6150:1
- **THEN** 0x6150:1 is added to TPDO 1 with a suggested location, and the picker lists only input-direction objects

### Requirement: Saved config compared like the deploy tool writes it
The Commission workspace SHALL compare the bridge's config fingerprint with the saved `canworks.json` as `canworks-deploy --bridge` uploads it, with every node's and every slave's EDS path rewritten as the upload does. Right after an upload of the saved config, the workspace SHALL NOT say that the bridge runs a different configuration, also when the config has a slave network.

#### Scenario: Gateway config uploaded
- **WHEN** the virtual plant (a slave network `cell` with its own EDS) is uploaded with `canworks-deploy --bridge` and the configurator connects to that bridge
- **THEN** the Commission workspace shows no "different configuration" note

### Requirement: Bit channels in the PDOs tab
An integer entry in a PDO mapping table SHALL have **Bits…**, which unfolds a table of the entry's bits: bit number, the device note's bit name, a tick that maps the bit and the name (placeholder: the default name). A bit has no location of its own: it is a bit of the entry's value at the entry's location (see `canopen-pdo-io`, "Bit channels of a PDO entry"). **Bits…** SHALL show how many bits are mapped. **Map all bits** SHALL map every bit; **Unmap all** SHALL remove them. A newly mapped bit SHALL take its name from the device note's bit name, turned into an identifier, when there is one; renaming or removing a note SHALL NOT change a mapped bit's name. Unticked bits of an RPDO entry without a location SHALL read "sent as 0". Each change SHALL be one undo step, and problems SHALL name the node, the PDO, the object and the bit. In a CODESYS config the location column SHALL be hidden; in a Modbus bridge config it SHALL show the bit's coil or discrete input number, read-only.

#### Scenario: Names from the statusword note
- **WHEN** the user opens **Bits…** on a drive's 0x6041 entry and presses **Map all bits**
- **THEN** 16 bits are mapped, bit 0 named `ready_to_switch_on` from the built-in CiA 402 note, and each shows its discrete input number from the entry's location

#### Scenario: Rename a button
- **WHEN** the user maps bit 3 of node `panel`'s 0x6000:1 and types `jog_x_plus` as its name
- **THEN** the draft's entry has `{"bit": 3, "name": "jog_x_plus", "iec_location": ...}` and the located declarations show `panel_jog_x_plus`

#### Scenario: Output entry
- **WHEN** an RPDO entry 0x6200:1 has `%QB40` in a Modbus bridge config and the user ticks its bit 0
- **THEN** `%QB40` stays, and bit 0 shows its coil number from `%QB40`

### Requirement: Empty network is a warning
A CANopen master network without nodes SHALL be one warning in Problems, not an error. The tree and the network's Bus page SHALL show the empty state: "No nodes yet", with **Add node…** and a pointer to finding devices in Commission. The hand-off steps SHALL still refuse a network without nodes.

#### Scenario: Fresh config
- **WHEN** the user creates a new Modbus bridge config
- **THEN** Problems shows one warning about the empty network and no error, and Save is not blocked

### Requirement: Header target action
The header SHALL hold the target's hand-off action as one primary button with no menu: **Build into CODESYS project…** for CODESYS, **Install on device…** for Modbus bridge, with or without an OpenPLC connection. Download for CODESYS SHALL be in Export ▾ (see "Export menu groups").

At 1280 px and wider the header SHALL be one row for every target, also while the simulation chip is shown (see "Header menus stay inside the window").

Under 1500 px with a config open, Reload from disk, Close, Settings and Quit SHALL be in one "⋯" menu. With no config open (start page, Devices without a config) they SHALL stay buttons in the header.

#### Scenario: CODESYS at 1366 px
- **WHEN** a CODESYS config is open at 1366 px wide
- **THEN** the header is one row with one Build button and no ▾ next to it

#### Scenario: OpenPLC with simulated nodes at 1280 px
- **WHEN** a Modbus bridge config with an OpenPLC connection and simulated nodes is open at 1280 px wide
- **THEN** the header is one row with Install on device…

### Requirement: PDO headings per target
The PDOs tab headings and column titles SHALL use the target's words: "Inputs (TPDOs, device to Modbus registers)", "Outputs (RPDOs, Modbus registers to device)" and "Location" for the Modbus bridge, and "Inputs (TPDOs, device to CODESYS)" without a location column for CODESYS.

#### Scenario: Bridge headings
- **WHEN** a Modbus bridge config's node PDOs tab is open
- **THEN** no heading or column title says "PLC"

### Requirement: Defaults of a new network
Every network the configurator creates SHALL start with its protocol's default bit rate: 500 kbit/s for CANopen (master or slave), 250 kbit/s for J1939 and 500 kbit/s for plain CAN. A new CANopen master SHALL start with node ID 1 and no SYNC (no `sync_period_us`). This SHALL hold for New config…, Add network…, switching a network's protocol or switching a slave back to master. **Add network…** SHALL NOT copy another network's bit rate. Switching a network's protocol SHALL change its bit rate to the new protocol's default only when the rate is the old protocol's default, and SHALL keep any other rate. Existing configs SHALL keep their settings.

#### Scenario: New config
- **WHEN** the user creates a new Modbus bridge config
- **THEN** the saved config's network has `"bitrate": 500000` and its master is `{"node_id": 1}` with no SYNC keys

#### Scenario: Add a J1939 network next to a CANopen one
- **WHEN** a config's first network runs at 500 kbit/s and the user adds a J1939 network
- **THEN** the new network's bit rate is 250 kbit/s

#### Scenario: Add a CANopen network
- **WHEN** the user adds a CANopen network
- **THEN** it runs at 500 kbit/s and its bus page shows SYNC source Off

#### Scenario: Switch a default network to J1939
- **WHEN** a CANopen network at 500 kbit/s with no nodes is switched to J1939
- **THEN** its bit rate is 250 kbit/s

#### Scenario: Switch keeps a chosen rate
- **WHEN** a CANopen network at 125 kbit/s is switched to J1939
- **THEN** its bit rate stays 125 kbit/s

### Requirement: SYNC Off on the bus page
A CANopen master's bus page SHALL offer **SYNC source** with two choices: **Off** (no SYNC) and **Timer**. The choice SHALL follow the config: Timer when `sync_period_us` is above 0, else Off. Off SHALL show no period field and remove `sync_period_us`. A config with `"sync_source": "plc_cycle"` is an error in Problems (see `canopen-config-contract`); the page SHALL NOT offer PLC cycle. Picking Timer SHALL set the SYNC period to 10 ms; emptying the period SHALL make the choice Off.

#### Scenario: Turn SYNC on
- **WHEN** on a new network the user picks SYNC source Timer
- **THEN** the SYNC period field shows 10 and the config has `"sync_period_us": 10000`

#### Scenario: Clear the period
- **WHEN** SYNC source is Timer and the user empties the SYNC period
- **THEN** SYNC source shows Off and the config has no `sync_period_us`

#### Scenario: Turn SYNC off from the PLC cycle
- **WHEN** a config of the removed plugin whose master has `"sync_source": "plc_cycle"`, `"sync_cycles": 2` and no `sync_period_us` gets Use with canworks-bridge
- **THEN** the master has no `sync_source` or `sync_cycles`, and SYNC source shows Off

#### Scenario: No PLC cycle choice
- **WHEN** the user opens SYNC source on any target
- **THEN** it lists Off and Timer only

### Requirement: OpenPLC editor files on save
Saving a Modbus bridge config with an OpenPLC connection inside an editor project with no errors SHALL also write the editor files of `canopen-editor-project` (the remote device file, the `canworks_in` and `canworks_out` programs, the `canworks` variable list and the task instances) and SHALL touch no other editor file or POU, except that it SHALL enable the `canworks` library in the project when it is not enabled, and install the library into OpenPLC Editor when it is missing there or older, as New editor project does. A save with errors SHALL write none of them. When the remote device file or one of the two programs changed on disk since canworks last wrote it, Save SHALL ask before writing anything, naming those files; Cancel SHALL save nothing. After writing them the message SHALL say that an OpenPLC Editor with this project open must reopen it before Build. A standalone config folder with an OpenPLC connection SHALL write no editor files and SHALL say so on its Project page.

#### Scenario: Save writes the device
- **WHEN** the user adds a TPDO entry in a project with an OpenPLC connection and saves
- **THEN** `devices/remote/canworks.json` gains a read group for it, `canworks_in` reads it into a new `canworks` variable, and the user's `main` is unchanged

#### Scenario: Program edited in the editor
- **WHEN** the user changed `pous/programs/canworks_in.st` in OpenPLC Editor and then saves in the configurator
- **THEN** Save asks whether to write the files again, naming that file, and Cancel leaves the config and the editor files as they were

#### Scenario: Library enabled on save
- **WHEN** a switched plugin project without the `canworks` library is saved
- **THEN** the project lists the library as enabled and `canworks_in` builds without adding it by hand
