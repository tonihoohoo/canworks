## ADDED Requirements

### Requirement: Devices in the header and from other pages
The header's workspace switch SHALL read **Configure | Commission | Devices**, with Devices as described by the `device-install` capability. While a project is open, its devices SHALL also be reachable from the pages that need them: Online access's **Runtime host** SHALL show the state of the device with that host (for example `canworks 0.93.4, off`) with **Open in Devices**; the Modbus bridge page SHALL show where the bridge runs and its state, with **Install on device…** when no device runs it; Commission's connect panel, when it lists no runtime, SHALL offer **Install canworks on a device…**; the status bar SHALL list a running install job with **Show**. Commission a CANopen device (no config) SHALL show no Devices workspace.

#### Scenario: Host with an old plugin
- **WHEN** Online access's runtime host is a device of the project whose last probe found plugin 0.93.4 off
- **THEN** the field shows `canworks 0.93.4, off` and **Open in Devices** opens that device's page

#### Scenario: Bridge not installed
- **WHEN** a bridge project has no device running its bridge
- **THEN** the Modbus bridge page shows **Install on device…**, which opens Devices with Add device or the project's device selected
