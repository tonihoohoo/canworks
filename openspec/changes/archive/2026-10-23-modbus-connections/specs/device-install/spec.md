## MODIFIED Requirements

### Requirement: OpenPLC project on a device
For an OpenPLC project (a config with an OpenPLC connection), the device page SHALL show the OpenPLC runtime row and the bridge row, and the main action SHALL follow "One main action". The runtime SHALL be the pinned version and SHALL get nothing of canworks. The instance SHALL be named after the project folder.

#### Scenario: Fresh device
- **WHEN** an OpenPLC project is open and the device has no runtime and no bridge, and the newest release is 0.120.0
- **THEN** the main action is **Install OpenPLC Runtime and the bridge 0.120.0**, and after the job the device runs the pinned runtime with nothing of canworks inside it and `canworks-bridge@<project>` with the project's config

#### Scenario: Device with the old plugin
- **WHEN** an OpenPLC project is open and the device has the runtime and no bridge
- **THEN** the main action is **Install the bridge X**, and the page says nothing about a plugin
