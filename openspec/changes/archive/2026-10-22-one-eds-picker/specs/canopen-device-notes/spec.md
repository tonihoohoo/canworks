## ADDED Requirements

### Requirement: Notes come with a picked EDS
When the configurator takes an EDS from a folder (Browse… in the EDS dialog, the EDS library, the commissioning folder), it SHALL import `<eds file name>.notes.json` next to it with the EDS when the config has no notes for that EDS. When the config already has notes for it, they SHALL be kept and a message SHALL say the other notes file can be brought in with Import notes….

#### Scenario: Library EDS with notes
- **WHEN** the EDS library has `valve.eds` and `valve.eds.notes.json`, and the user adds a node with `valve.eds` from the library to a config without notes for it
- **THEN** the draft has the EDS and its notes, the node's Notes tab lists them under My notes, and Save writes both

#### Scenario: Config already has notes
- **WHEN** the config has `valve.eds.notes.json` and the user picks `valve.eds` from another folder that has its own notes file, choosing Replace
- **THEN** the config's notes are unchanged and the message says the other notes file can be brought in with Import notes…

### Requirement: Datasheet notes are not taken by themselves
A `<eds file name>.datasheet.notes.json` next to a picked EDS SHALL NOT be imported with it; the message SHALL point to Import notes…, whose preview shows the changes.

#### Scenario: Datasheet notes next to the EDS
- **WHEN** the picked folder has `valve.eds` and `valve.eds.datasheet.notes.json` only
- **THEN** no notes are imported and the message points to Import notes… for the datasheet notes
