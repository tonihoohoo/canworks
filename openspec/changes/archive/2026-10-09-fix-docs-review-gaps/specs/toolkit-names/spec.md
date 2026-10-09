## MODIFIED Requirements

### Requirement: Settings and environment names
The PC tools SHALL keep per-user settings in a folder named `canworks` in the operating system's settings location. Every environment variable, CMake option or cache variable and Docker build argument that the plugin, the simulator, the PC tools, the install script, the build or the tests read SHALL have the prefix `CANWORKS_`; none SHALL have the prefix `CANOPEN_` or `OPENPLC_CANOPEN_`. Names only code sees (header guards, the C SDO API `CANOPEN_PLC_*`, Python constants) are not settings and MAY keep a CANopen name.

#### Scenario: Token from the environment
- **WHEN** `CANWORKS_TOKEN` is set and the user runs `canworks-diag status`
- **THEN** the client uses that token

#### Scenario: Slave state folder
- **WHEN** the plugin runs a slave network with `CANWORKS_STATE_DIR=/tmp/state`
- **THEN** a store to 0x1010 writes the state file under `/tmp/state`, and `CANOPEN_STATE_DIR` has no effect

#### Scenario: Build without tests
- **WHEN** a user configures the build with `-DCANWORKS_BUILD_TESTS=OFF`
- **THEN** `canopen_check`, the tests and the ping-pong slave are not built

### Requirement: No old names in the repository
The repository SHALL contain a rename script that applies the old-to-new mapping and can report, without changing anything, any old project-level name left outside archived changes and the CANopen-specific names, including the old `CANOPEN_` environment variable, CMake option and build argument names. CI SHALL fail when that report finds one.

#### Scenario: New file with an old import
- **WHEN** a pull request adds a file that imports `openplc_canopen_deploy`
- **THEN** CI fails and names the file and the old name

#### Scenario: Old variable name
- **WHEN** a pull request adds a test that reads `os.environ.get("CANOPEN_CHROMIUM")`
- **THEN** CI fails and names the file and `CANOPEN_CHROMIUM`
