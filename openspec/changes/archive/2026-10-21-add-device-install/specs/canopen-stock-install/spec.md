## ADDED Requirements

### Requirement: Installed version on the device
`install-stock.sh` SHALL write the plugin's version (the release version, or `git describe` of a checkout) to `<prefix>/VERSION` on every install and update, native and Docker mode, so the version can be read on the host without the runtime container. `--uninstall` SHALL remove it with `<prefix>/lib/`.

#### Scenario: Docker-mode device
- **WHEN** release 0.98.0 is installed on a managed Docker runtime
- **THEN** `/opt/canworks/VERSION` on the host holds `0.98.0`

### Requirement: Install step lines
`install-stock.sh` and `install-runtime.sh` SHALL print one line `::canworks-step N/M text` when each step starts (download, build tools, Lely, plugin and editor hook, runtime restart or container recreate, discovery and link), with M the number of steps this run takes (`?` in the lines `install-runtime.sh` prints before `install-stock.sh` runs, which does not know it yet), and SHALL keep their other output unchanged. The text SHALL be a short sentence for people.

#### Scenario: Steps of a Docker-mode update
- **WHEN** an update runs in Docker mode
- **THEN** the output has step lines from `1/M` to `M/M` in order, and the last names the runtime container restart

### Requirement: Install the OpenPLC runtime when none is found
`install-runtime.sh --with-openplc` SHALL, when no OpenPLC runtime is found (no `openplc-runtime` service and no bootloader runtime spec), run upstream's installer (`https://runtime.getedge.me`) as root, wait up to 10 minutes until the runtime answers on its local HTTPS port, and then install the plugin as without the option. When a runtime is found it SHALL install the plugin only. A failed upstream install SHALL end the script non-zero with the upstream output and SHALL NOT try the plugin. `--with-openplc` SHALL pass over `--ssh` like the other options, and `docs/install-stock.md` SHALL describe it.

#### Scenario: Fresh device
- **WHEN** `install-runtime.sh --with-openplc` runs on a Linux device without a runtime
- **THEN** upstream's managed Docker runtime is installed and answers, and the plugin is installed for its version

#### Scenario: Runtime present
- **WHEN** the same command runs on a device with a runtime
- **THEN** upstream's installer is not run

### Requirement: Device probe script
The PC tools package SHALL contain `canworks/devices/device-probe.sh`, a POSIX `sh` script that changes nothing, needs no root and no canworks on the device, and prints one JSON object describing the device as the `device-install` capability's probe requires. It SHALL also be one of each release's assets. A tool the device lacks SHALL give `null` for its values. CI SHALL run `shellcheck` on it and test its output on a fake root with no runtime, a native runtime with the plugin, a Docker-mode layout, a bridge with two instances and an install job log.

#### Scenario: Read-only
- **WHEN** the probe runs as a user without sudo rights
- **THEN** it exits 0, prints valid JSON, and no file on the device has changed
