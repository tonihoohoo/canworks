# canopen-docker-install Specification

## Purpose
Installing, running and removing the CANopen plugin on the managed Docker install of OpenPLC Runtime v4, where a bootloader container runs the stock runtime image and can change its version.

## Requirements

### Requirement: Install on the managed Docker runtime
When `scripts/install-stock.sh` finds the managed Docker install (the bootloader's runtime spec at `/var/lib/openplc-bootloader/runtime-spec.json`), it SHALL install in Docker mode. It SHALL build Lely, `dcfgen`, the plugin library and the editor hook inside the runtime image named by that spec (repository and version), placing the result under `/opt/openplc-canopen` on the host. It SHALL add to the spec a bind of `/opt/openplc-canopen` to the same path in the container, writable, and the environment entry that loads the editor hook, and SHALL then have the runtime container recreated so they take effect. It SHALL change no image, no runtime source file, and no spec entry other than its own. Running it again SHALL leave exactly one copy of each entry and rebuild.

#### Scenario: Fresh Docker install
- **WHEN** the script runs on a device with the managed Docker install and no CANopen install
- **THEN** `/opt/openplc-canopen/lib/` holds the plugin built in the runtime image, the runtime spec has the CANopen bind and environment entry and all its earlier entries unchanged, the runtime container has been recreated with them, and the runtime starts with a disabled `canopen` line in `plugins.conf`

#### Scenario: Re-run
- **WHEN** the script runs a second time
- **THEN** the runtime spec still has exactly one CANopen bind and one CANopen environment entry

#### Scenario: Interrupted spec write
- **WHEN** the script is interrupted while updating the runtime spec
- **THEN** the spec on disk is either the old one or the new one, never a partial file

#### Scenario: Stopping the PLC is announced
- **WHEN** the script is about to recreate the runtime container
- **THEN** it says, before doing it, that the PLC will stop and that the program has to be uploaded again, because a new container starts with the PLC empty

### Requirement: CANopen survives a new runtime container
The runtime recreates `plugins.conf` from its defaults whenever the bootloader creates a new runtime container. In Docker mode, at webserver start, the editor hook SHALL restore the `canopen` line as the last upload left it (enabled with its config path, or disabled), or add it disabled when no upload has set it yet. On a native install it SHALL leave `plugins.conf` alone.

#### Scenario: Container recreated after a CANopen upload
- **WHEN** a program was uploaded with a CANopen config and the runtime container is then recreated with the same runtime version
- **THEN** after the webserver starts, `plugins.conf` has `canopen` enabled with the same config path, and the next PLC start runs CANopen

#### Scenario: Container recreated with CANopen off
- **WHEN** the last upload disabled `canopen` and the container is recreated
- **THEN** `plugins.conf` has a disabled `canopen` line

### Requirement: Runtime version guard
The Docker-mode install SHALL record the runtime version it built against. When the runtime runs a different version (after a version change from the editor or the bootloader), the editor hook SHALL keep `canopen` disabled at webserver start and the plugin SHALL refuse to start, each logging one error that names both versions and says to re-run `scripts/install-stock.sh`. The PLC program SHALL run without CANopen. Re-running the script SHALL rebuild for the running version and clear the condition.

#### Scenario: Runtime updated from the editor
- **WHEN** CANopen was installed for runtime v4.2.4 and the editor moves the device to v4.2.5
- **THEN** the runtime starts, `canopen` is disabled, the log says the CANopen plugin was built for v4.2.4 but the runtime is v4.2.5 and to re-run the install script, and the PLC runs without CANopen

#### Scenario: Rebuild after the update
- **WHEN** the install script is re-run after that update
- **THEN** the plugin is rebuilt in the v4.2.5 image and the next upload with a CANopen config runs CANopen

#### Scenario: Deploy to a mismatched runtime
- **WHEN** `openplc-canopen-deploy` uploads a program with a CANopen config and the editor hook turns `canopen` off after the build because of the version guard
- **THEN** the deploy tool exits with an error that quotes the hook's message, and does not report the canopen plugin as enabled

### Requirement: CAN access in the container
In Docker mode the plugin SHALL use the same `adapter` settings as on a native install, with no Docker-specific config: SocketCAN interfaces by their host names, slcan adapters by their host serial device path, and link setup (bitrate, bring-up) as on native. The online diagnostics port SHALL be reachable at the device's address as on native.

#### Scenario: CANable on the managed install
- **WHEN** a config with an slcan adapter on `/dev/ttyACM0` is uploaded to a managed Docker install with the adapter plugged in
- **THEN** the plugin creates the CAN interface, the master boots its nodes, and `openplc-canopen-config` connects to the device on port 7531

### Requirement: Uninstall in Docker mode
`--uninstall` in Docker mode SHALL remove the CANopen bind and environment entry from the runtime spec, leaving every other entry, have the runtime container recreated, and remove the installed library and hook. `--purge` SHALL also remove the rest of `/opt/openplc-canopen`.

#### Scenario: Uninstall
- **WHEN** `--uninstall` runs on a managed Docker install with CANopen installed
- **THEN** the runtime spec equals the one before the install, the recreated runtime starts with no `canopen` line in `plugins.conf`, and `/opt/openplc-canopen/lib/` is gone

### Requirement: Hand-run runtime container
For a runtime container started by hand (without the bootloader), the script SHALL build for a given runtime image without touching any bootloader spec, and SHALL print the bind and environment flags the container needs. The container then behaves as in Docker mode.

#### Scenario: Build for a hand-run container
- **WHEN** the script runs with `--docker-image ghcr.io/autonomy-logic/openplc-runtime:v4.2.4`
- **THEN** it builds in that image, changes no bootloader spec and no container, and prints the `-v` and `-e` flags to add to `docker run`
