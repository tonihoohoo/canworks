## MODIFIED Requirements

### Requirement: Command names
The PC tools SHALL install `canworks-deploy`, `canworks-config`, `canworks-diag` and `canworks-local-runtime`, with the arguments and behaviour the `openplc-canopen-*` commands had, and SHALL NOT install any `openplc-canopen-*` command.

#### Scenario: Diagnostics command
- **WHEN** a user runs `canworks-diag --runtime plc.local status`
- **THEN** the output is what `openplc-canopen-diag --runtime plc.local status` printed with tools 0.40.0

#### Scenario: Old name gone
- **WHEN** a user installs tools 0.42.0 into a fresh environment and runs `openplc-canopen-diag`
- **THEN** the shell reports that the command is not found
