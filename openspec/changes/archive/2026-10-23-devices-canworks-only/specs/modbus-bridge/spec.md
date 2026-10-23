## MODIFIED Requirements

### Requirement: Bridge installs locked dependency versions
`install-bridge.sh` SHALL take `--constraints FILE` and install the tools into the bridge's venv with it. A release install through `install-bridge.sh` SHALL fetch and use that release's `canworks-<version>-constraints.txt`. The bridge image SHALL be built with the constraints exported from `uv.lock` of the commit it is built from.

#### Scenario: Bridge image
- **WHEN** the bridge image is built on `main`
- **THEN** its venv holds the dependency versions of that commit's `uv.lock`

## ADDED Requirements

### Requirement: Installs canworks only
`install-bridge.sh` and `install-bridge.ps1` SHALL install, update and remove canworks parts only and SHALL NOT install, switch or remove the OpenPLC runtime, Docker or any other program. They SHALL have no `--with-openplc`, `--pinned-runtime`, `-WithOpenplc` or `-PinnedRuntime` option. `docs/modbus-bridge.md` SHALL point to upstream's installer for the runtime.

#### Scenario: Old option
- **WHEN** `install-bridge.sh --with-openplc --instance line1 --config DIR` runs
- **THEN** it ends non-zero naming the unknown option, and nothing is installed

#### Scenario: Device with a runtime
- **WHEN** `install-bridge.sh --instance line1 --config DIR` runs on a device with the managed Docker OpenPLC runtime
- **THEN** the bridge runs `line1`, and the runtime's containers and version are unchanged

## REMOVED Requirements

### Requirement: OpenPLC runtime installed with the bridge
**Reason**: canworks installs only its own parts (Toni, 2026-10-23); the OpenPLC runtime comes from upstream's installer.
**Migration**: Run upstream's installer (`https://runtime.getedge.me`) on the device, then `install-bridge.sh` without the option.
