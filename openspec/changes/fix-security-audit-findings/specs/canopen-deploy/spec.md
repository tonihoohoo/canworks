## MODIFIED Requirements

### Requirement: Upload through the runtime API
The deploy tool SHALL log in with `POST /api/login`, read the PLC's state with `/api/status`, upload the zip with `POST /api/upload-file`, and follow `compilation-status` until the build ends, printing the runtime's build log. After a successful build it SHALL start the PLC with `/api/start-plc` and wait until `/api/status` reports it running when the PLC was running before the upload or had no program, or when the user passes `--start`; it SHALL leave the PLC stopped, saying so, when it was stopped before the upload, when the build log does not show whether the plugin was enabled, or when the user passes `--no-start`. It SHALL exit zero only when the runtime reports a successful build and the PLC is in the state the tool said it would leave it in. It SHALL read the password from an environment variable or an interactive prompt, never from the command line or the config, and SHALL verify the runtime's TLS certificate against a CA file or a pinned SHA-256 fingerprint unless the user passes an explicit `--insecure`.

#### Scenario: Successful deploy
- **WHEN** the user deploys the ping-pong program and config to a reachable runtime whose PLC is running, with valid credentials
- **THEN** the runtime compiles the program, its log shows the `canopen` plugin enabled, the PLC is started and running, and the tool exits zero

#### Scenario: PLC stopped for maintenance
- **WHEN** the PLC was stopped before the upload and the user deploys without `--start`
- **THEN** the build runs, the PLC stays stopped, and the tool says it left the PLC stopped and names `--start`

#### Scenario: Leave the PLC stopped
- **WHEN** the user deploys with `--no-start`
- **THEN** the tool does not start the PLC and says it is stopped

#### Scenario: Start refused
- **WHEN** the runtime refuses the start because the device's run/stop switch is at STOP
- **THEN** the tool exits non-zero after the build and says the switch is at STOP

#### Scenario: Wrong credentials
- **WHEN** login fails
- **THEN** the tool exits non-zero with the runtime's error and uploads nothing

#### Scenario: Compile fails
- **WHEN** the runtime reports a failed build
- **THEN** the tool prints the build log and exits non-zero

#### Scenario: Unknown certificate
- **WHEN** the runtime's certificate matches neither the CA file nor the pinned fingerprint and `--insecure` is not given
- **THEN** the tool exits non-zero before sending credentials

## ADDED Requirements

### Requirement: Paths safe for the editor's command on Windows
On Windows, the deploy tool SHALL refuse a project or editor path that contains `&`, `|`, `^`, `%`, `<`, `>` or `"` before running the editor's command-line tool, naming the character.

#### Scenario: Ampersand in a folder name
- **WHEN** the project is in `C:\R&D\pump` on Windows
- **THEN** the tool refuses, naming `&`, and runs nothing
