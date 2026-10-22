## MODIFIED Requirements

### Requirement: Install on the managed Docker runtime
When `scripts/install-stock.sh` finds the managed Docker install (the bootloader's runtime spec at `/var/lib/openplc-bootloader/runtime-spec.json`), it SHALL install in Docker mode. It SHALL build Lely, `dcfgen`, the plugin library and the editor hook inside the runtime image named by that spec (repository and version), placing the result under `/opt/canworks` on the host. It SHALL add to the spec a bind of `/opt/canworks` to the same path in the container, writable, and the environment entry that loads the editor hook, and SHALL then have the runtime container recreated so they take effect. It SHALL change no image, no runtime source file, and no spec entry other than its own. Running it again SHALL leave exactly one copy of each entry; it SHALL rebuild and recreate the container only when the version, the protocols or the runtime image changed, or with `--force` (canopen-stock-install, Requirement: Same-version re-run changes nothing).

#### Scenario: Fresh Docker install
- **WHEN** the script runs on a device with the managed Docker install and no CANopen install
- **THEN** `/opt/canworks/lib/` holds the plugin built in the runtime image, the runtime spec has the CANopen bind and environment entry and all its earlier entries unchanged, the runtime container has been recreated with them, and the runtime starts with a disabled `canopen` line in `plugins.conf`

#### Scenario: Re-run
- **WHEN** the script runs a second time
- **THEN** the runtime spec still has exactly one CANopen bind and one CANopen environment entry

#### Scenario: Re-run with nothing new
- **WHEN** the script runs a second time with the same version and protocols for the same runtime image
- **THEN** the runtime container is not recreated and the PLC keeps its program

#### Scenario: Interrupted spec write
- **WHEN** the script is interrupted while updating the runtime spec
- **THEN** the spec on disk is either the old one or the new one, never a partial file

#### Scenario: Stopping the PLC is announced
- **WHEN** the script is about to recreate the runtime container
- **THEN** it says, before doing it, that the PLC will stop and that the program has to be uploaded again, because a new container starts with the PLC empty
