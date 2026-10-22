## ADDED Requirements

### Requirement: One EDS list
Configure SHALL pick an EDS for the config from one list, in the Add node dialog and in the slave's EDS dialog. The list SHALL group the files, show each file's product name, file name and how many nodes use it, include the EDS library's files when a library is set, and have **Browse…**, which imports a new file into the draft and selects it. A library file SHALL be imported when the dialog's main button is pressed.

#### Scenario: Same list on both pages
- **WHEN** the config has `dio16.eds` used by node 6 and an EDS library is set, and the user opens Add node… on a master network and Choose EDS… on a slave network
- **THEN** both lists show `dio16.eds` with its product name and "used by 1 node", and both show the library's files under EDS library

#### Scenario: Browse with a name clash
- **WHEN** the user presses Browse… in either dialog and picks a file named like an EDS already in the config but with other content
- **THEN** the page asks to replace it or keep both, and the kept file is selected in the list

### Requirement: Keyboard in the EDS list
Enter or a double-click on an entry of the EDS list SHALL press the dialog's main button. The dialog SHALL open with focus in the list, or on **Browse…** when the list is empty.

#### Scenario: Pick with Enter
- **WHEN** the user moves to an entry in either dialog's list with the arrow keys and presses Enter
- **THEN** the dialog acts as if its main button (Add, Use) was pressed

## MODIFIED Requirements

### Requirement: Slave device page
The slave device page SHALL edit node ID (or LSS), the EDS (choose a file, or build one), the bound objects with their PLC locations, `inputs_on_loss` and the status and EMCY locations. Object rows SHALL come from the EDS, show the direction from its access type, and offer only matching PLC areas.

The EDS field SHALL show the slave's EDS as text, product name and file name, or that there is none yet, with **Choose EDS…** and **Export EDS** beside it. It SHALL NOT be a dropdown, and the page SHALL NOT show a browser file input. **Choose EDS…** SHALL open a dialog "Choose the slave's EDS" with the list of "One EDS list" and **Use** and **Cancel**. The list SHALL have the groups **Built here** (EDS files generated for a slave of this config), **In this project** (the folder's other EDS files) and **EDS library**, with the slave's current EDS selected. **Browse…** SHALL import with the slave's EDS lint. **Use** SHALL make the selected file the slave's EDS; **Cancel** or Escape SHALL change nothing. Focus SHALL return to **Choose EDS…** when the dialog closes.

#### Scenario: Bind an object
- **WHEN** the user adds 0x2100:1 (access `ro`, UNSIGNED16) from the EDS
- **THEN** the row suggests a free `%QW` location and refuses an `%I` one

#### Scenario: Choose an EDS from the library
- **WHEN** the slave has no EDS, an EDS library is set, and the user presses Choose EDS…, picks a library file and presses Use
- **THEN** the file is imported into the draft with the slave's EDS lint, the EDS field shows its product name and file name, and the object list offers its objects

#### Scenario: Generated EDS comes first
- **WHEN** the config has a generated `openplc-slave.eds` and two node EDS files, and the user opens Choose EDS…
- **THEN** `openplc-slave.eds` is under Built here, above In this project, and is selected when it is the slave's EDS

#### Scenario: Cancel keeps the EDS
- **WHEN** the user opens Choose EDS…, selects another file and presses Cancel
- **THEN** the slave's EDS is unchanged, the draft is not marked changed, and focus is on Choose EDS…

### Requirement: Add node dialog
**Add node…** SHALL open a dialog with:
- the device description: the list of "One EDS list", with the config's EDS files (product name, file name, nodes using it), the EDS library's files, and **Browse…**;
- the node ID: the lowest free ID, checked as typed;
- the name: from the EDS product name, unique in the network;
- **Map the EDS's default PDOs**, ticked.

**Add** SHALL add the node to that network. Cancel SHALL add nothing.

#### Scenario: Second node of a known type
- **WHEN** the virtual plant's `io` network has node 6 with `dio16.eds` and the user opens Add node…, picks dio16.eds from the list, and presses Add
- **THEN** a node with the lowest free ID and a unique name is added with `dio16.eds`, and no file picker was opened

#### Scenario: Taken node ID
- **WHEN** the user types 6 as the node ID in the dialog on `io`
- **THEN** the field says node 6 is already used and Add is disabled with that reason

#### Scenario: Double-click adds
- **WHEN** the node ID and name are valid and the user double-clicks `dio16.eds` in the list
- **THEN** the node is added as if Add was pressed
