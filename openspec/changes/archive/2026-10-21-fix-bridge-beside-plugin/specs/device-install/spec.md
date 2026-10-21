## ADDED Requirements

### Requirement: Bridge beside the plugin
The probe SHALL NOT report the `canworks-bridge` command in the plugin's own prefix (`/opt/canworks` with the plugin library) as a bridge when the bridge's template unit `canworks-bridge@.service` is not installed. The bridge object SHALL say whether that unit is installed. For a bridge project, a bridge without its unit SHALL get **Install and start this project's bridge**, and a bridge whose version is not a release version SHALL get **Update A → X**. The start job SHALL check for the unit first and, without it, end with a message that says to install the bridge.

#### Scenario: Plugin device, no bridge yet
- **WHEN** a device runs the canworks plugin under the managed Docker runtime, its `/opt/canworks/bin` has an old `canworks-bridge`, and no bridge unit is installed
- **THEN** the bridge row says not installed and the main action is **Install and start this project's bridge**
