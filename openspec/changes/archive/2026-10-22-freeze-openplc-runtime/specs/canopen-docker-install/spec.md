## ADDED Requirements

### Requirement: Runtime version switch
`install-stock.sh --runtime-version vX` on the managed Docker runtime SHALL set the bootloader spec's runtime version to vX, keeping every other spec entry, SHALL pull `<repository>:vX` first, and SHALL then build the plugin in that image and recreate the runtime container as a normal Docker-mode install does. When the image cannot be pulled, it SHALL stop with "the device cannot download OpenPLC runtime vX" and change nothing.

#### Scenario: Back from an Editor update
- **WHEN** the device's spec names v4.3.2 with the canworks bind and environment entries, and the script runs with `--runtime-version v4.3.1`
- **THEN** the spec names v4.3.1 with both canworks entries and every other entry unchanged, the plugin is built in the v4.3.1 image, the runtime container runs v4.3.1, and the version guard is clear

#### Scenario: Image not available
- **WHEN** the pull of the named version fails
- **THEN** the script exits with the download message, and the spec, the plugin and the running container are unchanged

#### Scenario: Already on the version
- **WHEN** the spec names v4.3.1, the stamp matches, and the script runs with `--runtime-version v4.3.1`
- **THEN** the same-version skip applies and the container is not recreated

### Requirement: Runtime version option scope
When the spec already names vX, `--runtime-version vX` SHALL change nothing by itself. On a native runtime the option SHALL stop with an error that names it as Docker-only, before changing anything. `install-runtime.sh` and `install-runtime.ps1` SHALL pass the option through.

#### Scenario: Native runtime
- **WHEN** the script runs with `--runtime-version v4.3.1` on a native runtime
- **THEN** it exits with "--runtime-version is for the managed Docker runtime" and changes nothing

#### Scenario: Over SSH from Windows
- **WHEN** `install-runtime.ps1 --ssh pi@host --runtime-version v4.3.1` runs
- **THEN** the device's `install-stock.sh` receives `--runtime-version v4.3.1`
