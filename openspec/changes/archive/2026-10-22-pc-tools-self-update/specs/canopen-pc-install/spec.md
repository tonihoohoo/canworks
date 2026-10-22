## MODIFIED Requirements

### Requirement: Update and uninstall

The documentation SHALL give one command to replace an installed version with a newer wheel and one command to remove the tools, both working without Python on the PC. The update command SHALL compile bytecode at install time like the install command. The documentation SHALL also describe updating from the configurator (the update check, the Update button, `canworks-config --update`) and how to turn the check off. For a company proxy that inspects TLS, it SHALL name `UV_SYSTEM_CERTS=1`, the variable current uv reads, and the older `UV_NATIVE_TLS=1` for uv versions before it.

#### Scenario: Update
- **WHEN** the user runs the documented update command on a newer wheel
- **THEN** `canworks-deploy --version` prints the newer version and the configurator's saved settings are kept

#### Scenario: Update from the configurator
- **WHEN** the user presses Update in the configurator of a uv tool install
- **THEN** `canworks-deploy --version` prints the newer version and the configurator's saved settings are kept

#### Scenario: Uninstall
- **WHEN** the user runs the documented uninstall command
- **THEN** the three commands are no longer on PATH
