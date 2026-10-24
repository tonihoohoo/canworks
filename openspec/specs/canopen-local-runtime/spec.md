# canopen-local-runtime Specification

## Purpose
A local OpenPLC Runtime v4 with canworks-bridge next to it on the engineering PC (Windows, macOS, Linux), run in a container by `canworks-local-runtime` with every network simulated, so a CANopen project can be uploaded, debugged and diagnosed without a Linux device, CAN adapter or real devices. The editor's own simulator cannot run runtime plugins.

## Requirements

### Requirement: Simulator runtime image
The local runtime SHALL be built from two images, neither of which changes the OpenPLC runtime: upstream's runtime image at the version pinned in `docker/local-runtime/runtime-version`, unchanged, and the released bridge image `ghcr.io/tonihoohoo/canworks-bridge` of the PC tools' version. The bridge container SHALL share the runtime container's network namespace, so the runtime's Modbus master reaches it at `127.0.0.1:1502` as on a Linux device, and SHALL run with `CANWORKS_FORCE_SIMULATE=1`. The project SHALL NOT build or publish an image of its own for the local runtime.

#### Scenario: Editor upload into the image
- **WHEN** the local runtime runs with the virtual plant's bridge config on its bridge, and the editor's Build and Upload sends the example project to `localhost:8443`
- **THEN** the runtime's Modbus master connects to the bridge, the program's `canworks_ok` becomes TRUE and the values move, with no canworks file in the runtime container

#### Scenario: Apple M-series Mac
- **WHEN** the images are pulled on an arm64 Linux VM (Colima or Podman machine on an M-series Mac)
- **THEN** the engine selects the `linux/arm64` variants of both images and both start without emulation

### Requirement: Image versions follow the PC tools
`canworks-local-runtime` SHALL use the bridge image tagged with its own package version and the runtime image tagged with the pinned runtime version. Each PC tools release `deploy-v<version>` SHALL be followed by the bridge image tagged `<version>` (modbus-bridge), so every released tools version has its bridge image. An existing tag SHALL never be overwritten.

#### Scenario: Release of 0.30.0
- **WHEN** PC tools 0.30.0 run `canworks-local-runtime start`
- **THEN** the bridge container runs `ghcr.io/tonihoohoo/canworks-bridge:0.30.0` and the runtime container the pinned upstream runtime tag

#### Scenario: Re-run for a released version
- **WHEN** the release workflow runs again for 0.30.0
- **THEN** the `0.30.0` bridge image tag is left unchanged

### Requirement: Start the local runtime
`canworks-local-runtime start` SHALL run the two images with a container engine: the one given by `--engine`, else `$CANWORKS_ENGINE`, else the first of `docker` and `podman` whose `info` succeeds, and on Windows then `docker` and `podman` inside the default WSL distribution (`wsl -e ...`). When none is usable it SHALL fail with a message that names what was looked for and points to the setup docs, without changing anything. It SHALL create the container `canworks-local-runtime` from the runtime image, publishing the runtime's port 8443 (host port 8443, `--port` to change) and the bridge's diagnostics port 7531 (the same number on both sides, `--diag-port` to change) on `127.0.0.1` only, keeping runtime data in the named volume `canworks-local-runtime-data`, restarting unless stopped, and with the `SYS_NICE` and `SYS_RESOURCE` capabilities and an unlimited memlock limit for the runtime's real-time scheduling and memory locking. It SHALL then create the container `canworks-local-bridge` from the bridge image in the runtime container's network (`--network container:canworks-local-runtime`), with the volume `canworks-local-bridge-config` as `/etc/canworks-bridge`, restarting unless stopped; the bridge SHALL wait for a config when the volume has none. When the containers exist and are stopped it SHALL start them. When a container exists with another image than the default, it SHALL keep that image and say that `update` switches it; when `--image` (bridge image) names another image than the container's, it SHALL change nothing and name `update`. It SHALL NOT need administrator rights beyond what the engine itself needs.

#### Scenario: First start with Podman only
- **WHEN** a PC has `podman` working and no `docker`, and the user runs `canworks-local-runtime start`
- **THEN** both containers run under Podman, the runtime answers on `https://localhost:8443`, the bridge answers on the diagnostics port, and the command prints the editor connection settings and the `canworks-deploy --bridge local` line

#### Scenario: Windows with Docker Engine in WSL2
- **WHEN** a Windows PC has no `docker` or `podman` on its PATH and Docker Engine runs in the default WSL2 distribution, and the user runs `canworks-local-runtime start` in PowerShell
- **THEN** both containers run in WSL2 through `wsl -e docker`, and the editor on Windows reaches the runtime at `localhost:8443`

#### Scenario: No engine
- **WHEN** neither `docker info` nor `podman info` succeeds
- **THEN** the command exits non-zero, says that no container engine is running and refers to `docs/local-runtime.md`, and no container or file is created

#### Scenario: Port in use
- **WHEN** host port 8443 is taken
- **THEN** the command fails, says so and names `--port`, and leaves no half-created container

#### Scenario: Engine refuses the real-time capabilities
- **WHEN** the engine refuses the `SYS_NICE` and `SYS_RESOURCE` capabilities or the unlimited memlock limit
- **THEN** the command starts the containers without them and says that only timing is affected

### Requirement: Local runtime credentials
On a start that finds the runtime without users, the command SHALL create a runtime user `openplc` with a random password of at least 20 characters through the runtime's user API, read the runtime's certificate fingerprint, and save URL, user, password, fingerprint, engine, image, port, diagnostics port and data volume name in `local-runtime.json` in the PC tools' configuration directory, readable by the PC user only where the file system supports it. Later starts SHALL reuse the saved file. When the runtime has users but the file is missing, the command SHALL say that the password cannot be recovered and name `remove --data` to reset. `status --show-password` SHALL print the saved password.

#### Scenario: Restart keeps the certificate
- **WHEN** the user runs `stop` and then `start`, or `update`
- **THEN** the runtime's certificate fingerprint equals the saved one and the saved credentials still log in

#### Scenario: Credentials file deleted
- **WHEN** `local-runtime.json` was deleted and the volume still holds the runtime's user
- **THEN** `start` runs the container, reports that the credentials are lost and names `canworks-local-runtime remove --data`

### Requirement: Manage the local runtime
The command SHALL offer `stop` (stop both containers), `status` (engine, images, container states, the runtime's address, PLC state, the bridge's config and network states, and its last log lines), `logs` (the bridge's log, `--runtime` for the runtime's; `-f` to follow), `update` (pull both images for its version and pin, or use copies already on the PC when the pull fails, recreate both containers on the same volumes and ports with the same credentials, and say that the PLC program must be uploaded again) and `remove` (delete both containers; with `--data` also both volumes and `local-runtime.json`). Each subcommand SHALL say plainly when there is nothing to act on.

#### Scenario: Update after upgrading the tools
- **WHEN** the PC tools were upgraded from 0.30.0 to 0.31.0 and the user runs `update`
- **THEN** the bridge container runs image `0.31.0` with its config kept, the runtime container runs the pinned image on the same volume, and the saved credentials and fingerprint still work

#### Scenario: Remove with data
- **WHEN** the user runs `remove --data`
- **THEN** both containers, both volumes and `local-runtime.json` are gone, and a later `start` creates new credentials

### Requirement: Local runtime as a target
`canworks-deploy --bridge local` SHALL upload the config to the local bridge at `127.0.0.1` and the saved diagnostics port (7531 without a saved file), with the project's access token. Without the file it SHALL fail with a message naming `canworks-local-runtime start`. `canworks-diag --runtime local` and the configurator's online access host `local` (set by its "Local simulator runtime" button) SHALL connect there too. The editor SHALL reach the runtime at `localhost` and the saved port with the saved user.

#### Scenario: Deploy to the local runtime
- **WHEN** the user runs `canworks-deploy --config canworks/canworks.json --bridge local` after `start`
- **THEN** the local bridge restarts with the config and its networks run simulated

#### Scenario: Diagnostics of the local runtime
- **WHEN** the deployed config has diagnostics on port 7531 and the user runs `canworks-diag --runtime local --token ... status`
- **THEN** it connects through the published port and says that the bridge forces every network simulated

### Requirement: Local runtime documentation
`docs/local-runtime.md` SHALL describe installing a free container engine on Windows (Docker Engine or Podman in WSL2), macOS (Colima or Podman) and Linux (Docker Engine or Podman), with no step that requires Docker Desktop, then `start`, putting the project's bridge config on the local bridge, connecting the editor and uploading, the configurator, `update`, `remove`, and the limits: everything runs simulated, timing is not real-time, and real CAN adapters are not reachable from the containers on Windows and macOS.

#### Scenario: Mac without Docker Desktop
- **WHEN** a user follows the macOS section on an M-series Mac without Docker Desktop
- **THEN** the steps install Colima and the Docker CLI with Homebrew, and `canworks-local-runtime start` works afterwards

### Requirement: Local runtime tested in CI
CI SHALL run an end-to-end test of the command with Docker on changes to the bridge, its image, the command or the runtime pin, with the pinned upstream runtime image and the bridge image built in the job: start, the credentials file, `canworks-deploy --bridge local` of `config/pingpong` (real adapter in the config), the forced-simulation note, a PLC program compiled by STruC++ with its `conf/modbus_master.json` uploaded to the runtime, node 2 operational, diagnostics through the published port, values moving between the program and the bus, stop and start and update with the same fingerprint, and remove with data. CI SHALL also build the bridge image for arm64 and start it there.

#### Scenario: Broken image
- **WHEN** a change makes the bridge fail to start in its image
- **THEN** the local runtime CI job fails

### Requirement: Certificate changes are refused
The saved certificate fingerprint SHALL be replaced only by `canworks-local-runtime start` right after it created or recreated the container itself. Any other time the local runtime answers with a different certificate, the tools SHALL stop before sending credentials and name `canworks-local-runtime start`. The password SHALL be printed only by `status --show-password`.

#### Scenario: Another program on the port
- **WHEN** another program answers on the local runtime's port with its own certificate and `canworks-local-runtime status` runs
- **THEN** the tool stops before logging in and says the certificate changed
