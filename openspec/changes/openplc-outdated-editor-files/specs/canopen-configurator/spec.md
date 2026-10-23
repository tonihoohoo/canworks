## MODIFIED Requirements

### Requirement: Busy states and the Save button
Save, every export, Move into project, New editor project and Add node from EDS SHALL disable their control and show what is running ("Saving…", "Exporting…", "Adding…") until the request completes, and a second click meanwhile SHALL do nothing. The Save button SHALL read "Save" and be enabled whenever the draft differs from the file, with or without errors, and also when the draft equals the file but an OpenPLC project's editor files are out of date ("Out-of-date OpenPLC editor files"). It SHALL read "Saved" and be disabled when the draft equals the file, nothing is out of date and there are no problems, and "Saved, N problems" (disabled) when it equals the file, nothing is out of date and there are problems. The error count SHALL be shown in the Problems pane.

#### Scenario: Double click on Save
- **WHEN** the user clicks Save twice while the first save is still running
- **THEN** one save request is made and the button reads "Saving…" until it returns

#### Scenario: Clean draft
- **WHEN** the file on disk equals the draft, the check has no problems and no editor file is out of date
- **THEN** the button reads "Saved" and is disabled

#### Scenario: Dirty draft with an error
- **WHEN** the draft has one error and differs from the file
- **THEN** the button reads "Save" and is enabled

## ADDED Requirements

### Requirement: Out-of-date OpenPLC editor files
For an OpenPLC project (target OpenPLC through Modbus, inside an editor project) the configurator SHALL compare the editor files Save writes for the saved config (the remote device file and the `canworks_in` and `canworks_out` programs) with the files on disk. A file SHALL count as out of date when it is missing, or when canworks wrote it last and Save would now write a different text. The `canworks` library SHALL count as out of date when the project enables an older version than the configurator's own. A file changed since canworks wrote it SHALL NOT count as out of date; Save keeps asking before writing it. When anything is out of date, the Project page SHALL list it under the editor files, Problems SHALL list one warning that opens the Project page, and Save SHALL be enabled with the title "The editor files are from an older canworks; Save writes them again". Saving then SHALL write the editor files and the library entry as a normal save does and SHALL leave `canworks.json` unchanged.

#### Scenario: Tools update changes canworks_in
- **WHEN** a project saved with an older canworks is opened in a configurator whose `canworks_in` code differs, and the user has made no change
- **THEN** the Project page lists `pous/programs/canworks_in.st` as out of date, Save is enabled, and pressing it rewrites `canworks_in.st` without changing `canworks.json`

#### Scenario: Nothing new
- **WHEN** the editor files on disk are what Save would write and the library version is current
- **THEN** nothing is listed and Save reads "Saved"

#### Scenario: Edited in the editor
- **WHEN** the user changed `canworks_in.st` in OpenPLC Editor and the config is unchanged
- **THEN** the file is not listed as out of date and Save stays disabled; a later save asks before writing it, as today
