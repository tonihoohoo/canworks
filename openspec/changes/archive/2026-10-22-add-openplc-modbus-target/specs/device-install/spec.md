## ADDED Requirements

### Requirement: OpenPLC project on a device
For an OpenPLC project (a config with `bridge.openplc`), the device page SHALL show the OpenPLC runtime row and the bridge row, and the main action SHALL be **Install OpenPLC Runtime and this project's bridge** (no runtime), **Install and start this project's bridge** (runtime, no bridge), **Update A → X** (bridge older than X), **Start this project's bridge** (bridge current, no instance with this project's saved config), or none with "Up to date". The runtime SHALL be the pinned version and SHALL get no canworks plugin (`install-runtime.sh --with-openplc --bridge`). A device that still has the canworks plugin SHALL show in its row that the plugin is no longer used for this project, with Uninstall. The instance SHALL be named after the project folder.

#### Scenario: Fresh device
- **WHEN** an OpenPLC project is open and the device has no runtime and no bridge, and the newest release is 0.120.0
- **THEN** the main action is **Install OpenPLC Runtime and this project's bridge** for 0.120.0, and after the job the device runs the pinned runtime with no canworks plugin and `canworks-bridge@<project>` with the project's config

#### Scenario: Device with the old plugin
- **WHEN** an OpenPLC project is open and the device has the runtime with the canworks plugin and no bridge
- **THEN** the main action is **Install and start this project's bridge**, and the plugin row says it is no longer used and offers Uninstall
