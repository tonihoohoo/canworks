## REMOVED Requirements

### Requirement: Bridge builds against the pinned runtime
**Reason**: The engine no longer uses the OpenPLC runtime's headers, so the bridge build downloads no runtime archive.
**Migration**: Requirement: Bridge builds without runtime sources.

### Requirement: Uninstall beside the canworks plugin
**Reason**: There is no canworks plugin to share the prefix or the can-j1939 boot entry with.
**Migration**: None.

### Requirement: Bridge prefix next to a Docker runtime
**Reason**: `/opt/canworks` was taken by the plugin the managed Docker runtime mounted; with the plugin gone the bridge owns its default prefix.
**Migration**: The bench Linux device is cleaned by hand once (design decision 10).

## ADDED Requirements

### Requirement: Bridge builds without runtime sources
The engine, the bridge, the standalone simulator and their tests SHALL build from this repository, Lely CANopen and the system's libraries only. No build, install script, image or CI job SHALL download, check out or include any OpenPLC runtime source or header, and no canworks source SHALL include a runtime header.

#### Scenario: Offline build
- **WHEN** `install-bridge.sh` runs from a checkout on a Linux device whose only network access is to the Lely and Python package sources
- **THEN** the bridge builds and installs, and no OpenPLC runtime archive is fetched

#### Scenario: Runtime header added
- **WHEN** a change adds `#include "plugin_types.h"` to an engine source
- **THEN** a CI check fails naming the file

### Requirement: OpenPLC runtime installed with the bridge
`install-bridge.sh --with-openplc` (`-WithOpenplc` in `install-bridge.ps1`, passed over `--ssh` like the other options) SHALL, when no OpenPLC runtime is found on the device (no `openplc-runtime` service and no bootloader runtime spec), download the canworks release first, then run upstream's installer (`https://runtime.getedge.me`) as root with the release's pinned runtime and bootloader versions (`docker/local-runtime/runtime-version`, `bootloader-version`), wait up to 10 minutes until the runtime answers on its local HTTPS port, and then install the bridge as without the option. When a runtime is found it SHALL install the bridge only and leave the runtime alone. A failed upstream install SHALL end the script non-zero with the upstream output and SHALL NOT install the bridge. Nothing of canworks SHALL be put into the runtime or its container. `docs/modbus-bridge.md` and `docs/devices.md` SHALL describe it.

#### Scenario: Fresh device
- **WHEN** `install-bridge.sh --with-openplc --instance line1 --config DIR` runs on a Linux device without a runtime
- **THEN** upstream's managed Docker runtime is installed at the pinned version and answers, and `canworks-bridge@line1` runs next to it with the config

#### Scenario: Runtime present
- **WHEN** the same command runs on a device with a runtime
- **THEN** upstream's installer is not run and the runtime is unchanged

#### Scenario: Release download fails
- **WHEN** the canworks release cannot be downloaded
- **THEN** the script fails before upstream's installer runs, and no runtime or Docker is installed

### Requirement: Link and discovery with the bridge install
`install-bridge.sh` SHALL install the Avahi advertisement by default (skipped with `--without-discovery`) and, with `--with-link`, the link service: a Python virtual environment with the pinned `iroh` package under the install prefix, the `canworks-link` command, `canworks-link.service` (enabled and started, watching the instance's config), and `/etc/canworks-link/` with no paired PCs. No other step on the device SHALL be needed. `--uninstall` SHALL remove the service, the command and the Avahi file and keep `/etc/canworks-link/` unless `--purge` is given.

#### Scenario: Fresh install with the link
- **WHEN** `install-bridge.sh --with-link --instance line1 --config DIR` runs on a device with no internet route
- **THEN** the service starts, makes no outside connection, appears in discovery with its link ID, and the first PC that logs in with the right token on the LAN gets paired

### Requirement: dcf-tools pinned for the bridge
`build-lely.sh` SHALL install dcf-tools with the exact versions in `scripts/dcf-tools-constraints.txt`. That file SHALL name the Lely commit it was made for, and a test SHALL fail when the Lely commit changes without it.

#### Scenario: Lely commit bumped alone
- **WHEN** a change updates `_lely_dcf/VERSION` and not `scripts/dcf-tools-constraints.txt`
- **THEN** the test fails, naming both files
