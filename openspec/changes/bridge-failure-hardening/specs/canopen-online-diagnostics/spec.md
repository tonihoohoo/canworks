## MODIFIED Requirements

### Requirement: Config upload to the bridge
The `put_config` operation SHALL carry a config and every file it names as one upload of at most 8 MB (file names relative to the config folder), and SHALL need `allow_changes` and `diagnostics.allow_config_upload`.
- The bridge SHALL check the new config in a staging folder and answer with every problem found.
- On a valid config, it SHALL stop its networks, put the files in place and restart with them.
- Each file SHALL replace the old one atomically: written under a temporary name in the config folder, written to disk (fsync), renamed over the old name, and the folder written to disk after the last rename. The backup of the previous files SHALL be made the same way. A file that cannot be written, written to disk or renamed SHALL put every file already replaced back, and the upload SHALL be answered as failed, naming the file and the reason.
- If the new config fails at start, it SHALL restore the previous files, restart with them, and report that.
- If the previous files do not start either, the bridge SHALL log both failures and exit with a non-zero status, so its service restarts it on the restored files.

canworks-bridge SHALL refuse `put_config` with a message saying its config comes with the program upload.

The bridge's status answer SHALL carry `last_stop` (`"clean"`, `"unclean"` or `"unknown"`, modbus-bridge "Unclean stop reported"), and `canworks-diag status` SHALL print it on the bridge line.

#### Scenario: Invalid upload
- **WHEN** a client uploads a config whose node names an EDS that is not in the upload
- **THEN** the answer lists the missing file, and the running networks were never stopped

#### Scenario: Upload not allowed
- **WHEN** `allow_config_upload` is not set and a client sends `put_config`
- **THEN** the request is refused with a message naming the setting

#### Scenario: Disk fills during an upload
- **WHEN** the config folder runs out of space while the uploaded files are put in place
- **THEN** the previous files are all in place and unchanged, the bridge runs them again, and the answer names the file that could not be written and that the disk is full

#### Scenario: Power loss during an upload
- **WHEN** the device loses power while the uploaded files are put in place
- **THEN** after the boot each file of the config folder is either its previous or its uploaded version, never a partly written one

#### Scenario: Neither config starts
- **WHEN** an uploaded config fails at start and the restored previous config fails too
- **THEN** the bridge logs both and exits non-zero, and systemd starts it again on the previous files

#### Scenario: Last stop in the status
- **WHEN** the bridge started after a power loss and `canworks-diag --runtime HOST status` is run
- **THEN** the bridge line shows that the last stop was unclean
