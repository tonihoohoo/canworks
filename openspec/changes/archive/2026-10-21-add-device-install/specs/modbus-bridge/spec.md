## ADDED Requirements

### Requirement: Bridge installed version and steps
`install-bridge.sh` SHALL write the bridge's version to `<prefix>/VERSION` on every install and update and remove it on `--uninstall`, and SHALL print `::canworks-step N/M text` lines when each step starts (download, build tools, Lely, bridge, instance check and start, restart of running instances), with its other output unchanged.

#### Scenario: Bridge next to a Docker runtime
- **WHEN** release 0.98.0 of the bridge is installed into `/opt/canworks-bridge`
- **THEN** `/opt/canworks-bridge/VERSION` holds `0.98.0` and the output has step lines from `1/M` to `M/M`
