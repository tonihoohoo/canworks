## ADDED Requirements

### Requirement: Tested runtime version
The PC tools SHALL know the OpenPLC runtime version that CI tests, equal to `docker/local-runtime/runtime-version`. When the probe reports a runtime newer than that version, the runtime row SHALL say in one muted line that canworks is tested with that version and name the device's version. The note SHALL NOT change the main action or block it. An equal, older or unknown runtime version SHALL show no note.

#### Scenario: Newer runtime
- **WHEN** the tested runtime is v4.2.4 and the device runs v4.2.5 with a plugin built for v4.2.4
- **THEN** the runtime row says "canworks is tested with runtime v4.2.4; this device runs v4.2.5", and the main action is still **Rebuild for runtime v4.2.5**

#### Scenario: Tested runtime
- **WHEN** the device runs v4.2.4
- **THEN** the runtime row has no tested-version note

### Requirement: Runtime install names its version source
The confirmation for **Install OpenPLC Runtime and canworks** SHALL say that upstream's installer installs its newest runtime, and a test SHALL fail when the PC tools' tested runtime version differs from `docker/local-runtime/runtime-version`.

#### Scenario: Install confirmation
- **WHEN** the user starts **Install OpenPLC Runtime and canworks**
- **THEN** the confirmation names upstream's installer and says it installs upstream's newest runtime
