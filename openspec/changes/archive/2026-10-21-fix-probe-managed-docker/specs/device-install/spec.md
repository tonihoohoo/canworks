## MODIFIED Requirements

### Requirement: Device probe
Before any change, the configurator SHALL read the device's state with a read-only probe that needs no root and no canworks on the device: `device-probe.sh`, shipped in the PC tools and run on the device from the connection's standard input, printing one JSON object with the system, architecture, systemd, free disk, memory, internet access to the release host, sudo mode, the OpenPLC runtime (none, native, managed Docker or other Docker; version; whether its HTTPS port answers), the plugin (version, the runtime version it was built for, enabled in `plugins.conf` or not), the bridge (version, prefix, instances and their state), the remote link and discovery, CAN and vcan interfaces with state and bit rate, serial adapters, the `can-j1939` module and a running or last install job. When the SSH user cannot read the managed runtime's spec or use Docker and sudo needs no password, the probe SHALL read them through `sudo -n`, read-only. An installed native unit that is not running SHALL count only when nothing points to a managed or other Docker runtime. A value the device cannot give SHALL be `null`, never a failed probe. **Check again** SHALL probe again.

#### Scenario: Fresh device
- **WHEN** the probe runs on a Linux device with no OpenPLC runtime and no canworks
- **THEN** it succeeds and reports `runtime: none`, `plugin: null` and the device's CAN interfaces

#### Scenario: Runtime moved on
- **WHEN** the runtime is v4.2.5 and the plugin was built for v4.2.4
- **THEN** the plugin row says it is off because it was built for v4.2.4, and the main action is **Rebuild for runtime v4.2.5**

#### Scenario: Moved from native to managed Docker
- **WHEN** the device runs the managed Docker runtime v4.2.4, its old native unit is installed but stopped, and the SSH user can read neither the bootloader's folder nor Docker
- **THEN** the runtime row shows managed Docker v4.2.4 (read through password-less sudo, or with no version without it), the plugin's state comes from the Docker line, and no **Rebuild** is offered
