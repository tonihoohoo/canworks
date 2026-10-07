## MODIFIED Requirements
### Requirement: Simulator runtime image
The project SHALL publish a container image `ghcr.io/tonihoohoo/openplc-canopen-sim-runtime` for `linux/amd64` and `linux/arm64`, built from the upstream runtime image of the version pinned in `docker/local-runtime/runtime-version`, with the CANopen plugin, `dcfgen`, the device simulator and the editor hook installed under `/opt/openplc-canopen` exactly as the in-image build of `scripts/install-stock.sh` installs them. The image SHALL change nothing in the upstream image other than adding these files, the environment entries `PYTHONPATH` (editor hook) and `CANOPEN_FORCE_SIMULATE=1`, and links that keep the runtime's generated certificate and key in the data volume. The image SHALL carry the upstream runtime version and the PC tools version as labels.

#### Scenario: Editor upload into the image
- **WHEN** a container of the image runs and the editor's Build and Upload sends a project that has a `canopen/` folder
- **THEN** the runtime enables `canopen` with that config, as on a stock install with the editor hook

#### Scenario: Apple M-series Mac
- **WHEN** the image is pulled on an arm64 Linux VM (Colima or Podman machine on an M-series Mac)
- **THEN** the engine selects the `linux/arm64` variant and the runtime starts without emulation

### Requirement: Image versions follow the PC tools
Each PC tools release `deploy-v<version>` SHALL be followed by a push of the image tagged `<version>` and `latest`, built from the same commit, under the same conditions that allowed the wheel release. An existing `<version>` tag SHALL never be overwritten. A failed image build SHALL NOT remove or change the wheel release; the workflow SHALL fail visibly instead.

#### Scenario: Release of 0.30.0
- **WHEN** the wheel `deploy-v0.30.0` is released from a `main` commit
- **THEN** `ghcr.io/tonihoohoo/openplc-canopen-sim-runtime:0.30.0` exists for amd64 and arm64, built from that commit, and `latest` points at it

#### Scenario: Re-run for a released version
- **WHEN** the release workflow runs again for 0.30.0
- **THEN** the `0.30.0` image tag is left unchanged

### Requirement: Start the local runtime
`openplc-canopen-sim-runtime start` SHALL run the image with a container engine: the one given by `--engine`, else `$OPENPLC_CANOPEN_ENGINE`, else the first of `docker` and `podman` whose `info` succeeds, and on Windows then `docker` and `podman` inside the default WSL distribution (`wsl -e ...`). When none is usable it SHALL fail with a message that names what was looked for and points to the setup docs, without changing anything. By default it SHALL use the image tag equal to its own package version (`--image` overrides). It SHALL create a container named `openplc-canopen-sim-runtime` that publishes the runtime's port 8443 (host port 8443, `--port` to change) and the plugin's diagnostics port 7531 (the same number on both sides, `--diag-port` to change) on `127.0.0.1` only, keeps runtime data in the named volume `openplc-canopen-sim-runtime-data` (or the volume saved in `local-runtime.json` for a runtime taken over from the earlier name), and restarts unless stopped. When the container exists and is stopped it SHALL start it. When it exists with another image than the default, it SHALL keep that image and say that `update` switches it; when `--image` names another image than the container's, it SHALL change nothing and name `update`. It SHALL NOT need administrator rights beyond what the engine itself needs.

#### Scenario: First start with Podman only
- **WHEN** a PC has `podman` working and no `docker`, and the user runs `openplc-canopen-sim-runtime start`
- **THEN** the container runs under Podman, the runtime answers on `https://localhost:8443`, and the command prints the editor connection settings

#### Scenario: Windows with Docker Engine in WSL2
- **WHEN** a Windows PC has no `docker` or `podman` on its PATH and Docker Engine runs in the default WSL2 distribution, and the user runs `openplc-canopen-sim-runtime start` in PowerShell
- **THEN** the container runs in WSL2 through `wsl -e docker`, and the editor on Windows reaches the runtime at `localhost:8443`

#### Scenario: No engine
- **WHEN** neither `docker info` nor `podman info` succeeds
- **THEN** the command exits non-zero, says that no container engine is running and refers to `docs/local-runtime.md`, and no container or file is created

#### Scenario: Port in use
- **WHEN** host port 8443 is taken
- **THEN** the command fails, says so and names `--port`, and leaves no half-created container

#### Scenario: Engine refuses the real-time capabilities
- **WHEN** the engine refuses the `SYS_NICE` and `SYS_RESOURCE` capabilities
- **THEN** the command starts the container without them and says that only timing is affected

### Requirement: Local runtime credentials
On a start that finds the runtime without users, the command SHALL create a runtime user `openplc` with a random password of at least 20 characters through the runtime's user API, read the runtime's certificate fingerprint, and save URL, user, password, fingerprint, engine, image, port, diagnostics port and data volume name in `local-runtime.json` in the PC tools' configuration directory, readable by the PC user only where the file system supports it. Later starts SHALL reuse the saved file. When the runtime has users but the file is missing, the command SHALL say that the password cannot be recovered and name `remove --data` to reset. `status --show-password` SHALL print the saved password.

#### Scenario: Restart keeps the certificate
- **WHEN** the user runs `stop` and then `start`, or `update`
- **THEN** the runtime's certificate fingerprint equals the saved one and the saved credentials still log in

#### Scenario: Credentials file deleted
- **WHEN** `local-runtime.json` was deleted and the volume still holds the runtime's user
- **THEN** `start` runs the container, reports that the credentials are lost and names `openplc-canopen-sim-runtime remove --data`

### Requirement: Manage the local runtime
The command SHALL offer `stop` (stop the container), `status` (engine, image, container state, the runtime's address, PLC state, and the last CANopen lines of the runtime log), `logs` (`-f` to follow), `update` (pull the image for its own version, or use a copy already on the PC when the pull fails, recreate the container on the same volume and ports with the same credentials, and say that the PLC program must be uploaded again) and `remove` (delete the container; with `--data` also the volume and `local-runtime.json`). Each subcommand SHALL say plainly when there is nothing to act on.

#### Scenario: Update after upgrading the tools
- **WHEN** the PC tools were upgraded from 0.30.0 to 0.31.0 and the user runs `update`
- **THEN** the container runs image `0.31.0` on the same volume, and the saved credentials and fingerprint still work

#### Scenario: Remove with data
- **WHEN** the user runs `remove --data`
- **THEN** the container, the volume and `local-runtime.json` are gone, and a later `start` creates new credentials

### Requirement: Local runtime as a target
`openplc-canopen-deploy --runtime local` SHALL take URL, user, password and fingerprint from `local-runtime.json`; options the user gives explicitly SHALL win. Without the file it SHALL fail with a message naming `openplc-canopen-sim-runtime start`. `openplc-canopen-diag --runtime local` and the configurator's online access host `local` (set by its "Local simulator runtime" button) SHALL connect to `127.0.0.1` at the saved diagnostics port (7531 without a saved file), with the project's access token as for any runtime.

#### Scenario: Deploy to the local runtime
- **WHEN** the user runs `openplc-canopen-deploy --runtime local` with an editor project after `start`
- **THEN** the bundle is uploaded to the local runtime with the saved credentials and pinned fingerprint, without asking for a password

#### Scenario: Diagnostics of the local runtime
- **WHEN** the deployed config has diagnostics on port 7531 and the user runs `openplc-canopen-diag --runtime local --token ... status`
- **THEN** it connects through the published port and says that the runtime forces every network simulated

### Requirement: Local runtime documentation
`docs/local-runtime.md` SHALL describe installing a free container engine on Windows (Docker Engine or Podman in WSL2), macOS (Colima or Podman) and Linux (Docker Engine or Podman), with no step that requires Docker Desktop, then `start`, connecting the editor, deploying, the configurator, `update`, `remove`, and the limits: everything runs simulated, timing is not real-time, and real CAN adapters are not reachable from the container on Windows and macOS.

#### Scenario: Mac without Docker Desktop
- **WHEN** a user follows the macOS section on an M-series Mac without Docker Desktop
- **THEN** the steps install Colima and the Docker CLI with Homebrew, and `openplc-canopen-sim-runtime start` works afterwards

## ADDED Requirements

### Requirement: Taking over a local runtime from the earlier name
When `start` or `update` finds no container named `openplc-canopen-sim-runtime` but one named `openplc-canopen-runtime` (created by PC tools 0.30.x), it SHALL stop and remove that container, create `openplc-canopen-sim-runtime` on the old container's data volume, save that volume's name in `local-runtime.json`, and say so in one line. The saved user, password and certificate fingerprint SHALL keep working. When both containers exist, the command SHALL use `openplc-canopen-sim-runtime`, leave the old container untouched and name the command that removes it.

#### Scenario: Update after upgrading from 0.30.1
- **WHEN** a local runtime was started with tools 0.30.1 and the user upgrades the tools and runs `openplc-canopen-sim-runtime update`
- **THEN** the container `openplc-canopen-runtime` is gone, `openplc-canopen-sim-runtime` runs the new image on the volume `openplc-canopen-runtime-data`, and the saved credentials log in with the same fingerprint

#### Scenario: Both containers exist
- **WHEN** containers `openplc-canopen-runtime` and `openplc-canopen-sim-runtime` both exist and the user runs `status`
- **THEN** it reports `openplc-canopen-sim-runtime` and names `docker rm -f openplc-canopen-runtime` (or the engine's equivalent) to remove the old one, without removing it

### Requirement: Earlier command name
For one release, the PC tools SHALL also install `openplc-canopen-runtime`, which SHALL print one line to stderr that the command is now `openplc-canopen-sim-runtime` and then behave exactly like it with the same arguments.

#### Scenario: Old command in a script
- **WHEN** a script runs `openplc-canopen-runtime status`
- **THEN** it gets the same output and exit status as `openplc-canopen-sim-runtime status`, plus the one rename line on stderr
