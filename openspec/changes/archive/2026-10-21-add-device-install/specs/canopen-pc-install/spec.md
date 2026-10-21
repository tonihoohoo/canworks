## ADDED Requirements

### Requirement: SSH library in the package
The PC tools SHALL depend on `paramiko` (and so on its `cryptography`, `bcrypt` and `pynacl` wheels) on every platform they ship for, at a floor without known vulnerabilities, because the configurator's Devices workspace connects to devices over SSH. The one-line installers SHALL install it with no compiler on the PC, and the fast-start and skip-reinstall requirements SHALL still hold.

#### Scenario: Fresh Windows install
- **WHEN** a user installs the PC tools with the one-line installer on Windows
- **THEN** the configurator's Devices workspace can connect to a device over SSH with nothing else installed
