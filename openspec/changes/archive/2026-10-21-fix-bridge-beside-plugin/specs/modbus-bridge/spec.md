## ADDED Requirements

### Requirement: Uninstall beside the canworks plugin
`install-bridge.sh --uninstall` SHALL keep `<prefix>/VERSION` when the prefix also holds the canworks plugin library, and SHALL keep the can-j1939 boot entry (`/etc/modules-load.d/canworks-j1939.conf`) while the plugin is installed. `install-stock.sh` SHALL likewise keep that entry, on uninstall and on an install without J1939, while the bridge's unit is installed.

#### Scenario: Bridge removed from a PLC device
- **WHEN** the bridge is uninstalled on a device whose canworks plugin uses J1939
- **THEN** can-j1939 still loads at boot and the plugin's version file stays
