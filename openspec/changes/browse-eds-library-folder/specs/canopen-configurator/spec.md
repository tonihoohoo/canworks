## ADDED Requirements

### Requirement: EDS library folder button
The Nodes tab of Commission a device SHALL show the EDS library folder as text ("None chosen" when unset) with a **Choose folder…** button and, when a folder is set, a **Clear** button, and SHALL NOT offer a text field for it. The folder SHALL be kept in the configurator's settings on this PC, not in a project. After a folder is chosen or cleared, the devices already scanned SHALL be matched against the new folder.

#### Scenario: Choose a folder
- **WHEN** the user presses Choose folder…, opens `eds` under the home folder and presses Use this folder
- **THEN** the row shows the folder's path and the scanned devices are matched against it

#### Scenario: Clear
- **WHEN** a library folder is set and the user presses Clear
- **THEN** the row shows "None chosen", Clear is hidden, and scanned devices show no library matches

### Requirement: Folder dialog
**Choose folder…** SHALL open a dialog that lists the PC's folders through the configurator's server, with the current path, **Up**, a path field with **Go** that accepts a typed or pasted path, the subfolders (hidden ones left out), **Cancel** and **Use this folder**. Each listed folder that directly holds EDS files SHALL show how many.

#### Scenario: EDS counts in the list
- **WHEN** the dialog lists a folder whose subfolder `eds` holds 12 EDS files
- **THEN** that subfolder's entry shows "12 EDS"

#### Scenario: Cancel changes nothing
- **WHEN** the user opens the dialog, moves to another folder and presses Cancel
- **THEN** the library folder is unchanged and no settings request is sent

#### Scenario: Pasted path
- **WHEN** the user pastes a path into the dialog's path field and presses Enter
- **THEN** the dialog lists that folder, or says in the dialog that it is not a folder

### Requirement: Folder dialog start and drives
The folder dialog SHALL open in the current library folder, else its nearest existing parent, else the home folder. On Windows, **Up** from a drive root SHALL list the PC's drives.

#### Scenario: Opens where the library is
- **WHEN** the library folder is set and the user presses Choose folder…
- **THEN** the dialog lists the library folder

#### Scenario: Another drive on Windows
- **WHEN** the dialog shows `C:\` and the user presses Up
- **THEN** the dialog lists the PC's drives, and opening `D:\` lists its folders

### Requirement: Folder dialog keyboard use
The folder dialog SHALL work with the keyboard alone: focus starts in the folder list, Enter opens the focused folder, Escape cancels, and focus returns to **Choose folder…** when the dialog closes.

#### Scenario: Keyboard only
- **WHEN** the user tabs to Choose folder…, presses Enter, moves to a folder with the arrow keys, presses Enter, then tabs to Use this folder and presses Enter
- **THEN** that folder is the library folder and focus is back on Choose folder…

### Requirement: EDS library contents shown
After a library folder is chosen, the row SHALL say how many EDS files the folder holds with its subfolders, or that it holds none. Counting SHALL stop after 5000 directory entries; above that the row SHALL say the folder is large and scans may be slow.

#### Scenario: Count shown
- **WHEN** the chosen folder holds 34 EDS files in it and its subfolders
- **THEN** the row says "34 EDS files"

#### Scenario: Folder without EDS files
- **WHEN** the user chooses a folder with no EDS files in it or its subfolders
- **THEN** the row says the folder has no EDS files, and the folder stays chosen

#### Scenario: Large folder
- **WHEN** the user chooses the home folder and it has more than 5000 entries below it
- **THEN** the row says the folder is large and scans may be slow, and the page stays responsive
