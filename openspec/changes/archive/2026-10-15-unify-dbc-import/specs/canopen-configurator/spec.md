## MODIFIED Requirements

### Requirement: Import a DBC into CAN messages
The CAN messages page SHALL have an "Import DBC…" file button that opens the system's file picker directly, with no dialog before it, the same way as "Import DBC…" on a J1939 network and "+ Add node…". The chosen file SHALL be kept with the draft and written into the config folder on Save when a network names it in `raw.dbc` or `j1939.dbc`; a different file of the same name already in the folder or in the draft SHALL ask whether to replace it or keep both (keep both gives the new file a `-2` suffix). The page SHALL then open the message picker, which SHALL list the file's messages with identifier, DLC, cycle and signal count and set each to Receive, Send or Leave out (Send preselected for messages sent by a node named `PLC` or like the network; Send not offered on a listen-only network). A message the network already has in that direction (same identifier and extended flag) SHALL be marked as already there and start as Leave out. Messages the file has but the import cannot take SHALL be listed under "Left out of the import". "Add picked messages" SHALL add the chosen messages as receive or send messages with free PLC addresses. Imported messages SHALL keep the DBC's names, layouts, scale, offset, unit, limits and multiplexing (simple and extended); a cycle time from the DBC SHALL become `period_ms` for send and three times the cycle as `timeout_ms` for receive. A message with several switches but no `SG_MUL_VAL_` SHALL be listed with a note that its multiplexing cannot be read. The imported file's name SHALL be stored in `raw.dbc`.

The page SHALL show the network's DBC file as read-only text ("Messages come from <file>." or "No DBC file yet."), marked as missing when the file is neither in the config folder nor in the draft, and SHALL offer "Pick messages…" to open the picker again on that file. Importing a file other than the one `raw.dbc` names, on a network that has raw messages, SHALL ask first, naming both files. Removing the network's last raw message SHALL clear `raw.dbc`. The J1939 and CAN messages pages SHALL use the same picker, differing only in their columns.

#### Scenario: Import two messages
- **WHEN** the user clicks Import DBC…, picks a DBC with messages `Joystick` (cycle 100 ms) and `Lamps` in the system file picker, chooses Receive for `Joystick` and Send for `Lamps`, clicks Add picked messages and saves
- **THEN** no dialog appeared before the file picker, the file has `Joystick` in `raw.rx` with `timeout_ms` 300 and `Lamps` in `raw.tx` with every signal at a location, `raw.dbc` names the file, the DBC file is in the config folder, and Check reports no problems

#### Scenario: Import a multiplexed message
- **WHEN** the user imports `Status` with switch `Page` and signals on pages 1 and 2 as receive
- **THEN** the file has `Page` with `multiplexer: true` and each page's signals with their `mux.values`, and Check reports no problems

#### Scenario: Same name, different file
- **WHEN** the config folder has `machine.dbc` and the user imports a different file also named `machine.dbc` and answers Keep both
- **THEN** the picker opens on `machine-2.dbc`, `raw.dbc` becomes `machine-2.dbc` after the import, and Save writes `machine-2.dbc` next to the unchanged `machine.dbc`

#### Scenario: A second DBC file
- **WHEN** the network has messages imported from `a.dbc` and the user picks `b.dbc`
- **THEN** the page asks whether to keep `a.dbc` or use `b.dbc` before anything is uploaded, and Keep `a.dbc` changes nothing

#### Scenario: Pick more messages later
- **WHEN** a saved network names `machine.dbc` with `Joystick` received, and the user clicks Pick messages…
- **THEN** the picker lists the file's messages with `Joystick` marked as already in received messages and set to Leave out

#### Scenario: Missing DBC file
- **WHEN** the config's `raw.dbc` names `old.dbc` and the config folder has no such file
- **THEN** the DBC line says `old.dbc` is not in the config folder and Pick messages… is not offered

#### Scenario: DBC line is not a text field
- **WHEN** the user opens the CAN messages page
- **THEN** the DBC file is shown as text with Import DBC… beside it, and there is no field to type a file name into
