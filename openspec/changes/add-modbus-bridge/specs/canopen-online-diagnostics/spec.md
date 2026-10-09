## ADDED Requirements

### Requirement: Diagnostics channel on the bridge
`canworks-bridge` SHALL serve the diagnostics channel with the same operations, access control and encryption as the plugin. Its hello SHALL name the host as `bridge`. Live status SHALL add a `bridge` part with the state, the outputs-off reason, the connected clients (address, requests, writer or not) and the watchdog time left.

#### Scenario: Status of a bridge
- **WHEN** `canworks-diag status` connects to a bridge with one writer client
- **THEN** it shows the networks as for a plugin, and a bridge line with state running, one client and its address

### Requirement: Config upload to the bridge
The `put_config` operation SHALL carry a config and every file it names as one archive of at most 8 MB, and SHALL need `allow_changes` and `diagnostics.allow_config_upload`.
- The bridge SHALL check the new config in a staging folder and answer with every problem found.
- On a valid config, it SHALL stop its networks, put the files in place and restart with them.
- If the new config fails at start, it SHALL restore the previous files, restart with them, and report that.

The OpenPLC plugin SHALL refuse `put_config` with a message saying its config comes with the program upload.

#### Scenario: Invalid upload
- **WHEN** a client uploads a config whose node names an EDS that is not in the archive
- **THEN** the answer lists the missing file, and the running networks were never stopped

#### Scenario: Upload not allowed
- **WHEN** `allow_config_upload` is not set and a client sends `put_config`
- **THEN** the request is refused with a message naming the setting
