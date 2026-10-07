## Context

The plugin runs only inside OpenPLC Runtime v4 on Linux. Users install it on a Linux device (native or the managed Docker install) with `scripts/install-stock.sh`. A simulated network (`adapter.simulate`) runs every node as a simulated device on an in-process virtual bus. It needs no CAN interface, no privileges and no vcan, and it works in the Docker install.

The OpenPLC editor's built-in Simulator board is an avr8js-emulated ATmega2560 running the Arduino ("Baremetal") build of the program. Its compile pipeline says it runs user logic only, with no network and no plugins. It cannot host the plugin, and changing the editor is ruled out (no fork). The upstream runtime ships official multi-arch images (`ghcr.io/autonomy-logic/openplc-runtime`, amd64, arm64, armv7) that listen on port 8443 for the editor.

So the "simulator" a user can have on a PC is the real runtime in a container, with the plugin built in and the network simulated. The PC tools already run on Windows, macOS and Linux with uv and need no Python (canopen-pc-install). The new pieces are an image and a command that runs it. The command must not depend on Docker Desktop: the owner does not use it, and it needs a paid licence in larger companies.

## Goals / Non-Goals

**Goals:**
- One command on Windows, macOS (Intel and M-series) or Linux starts a runtime with CANopen. The editor, deploy tool, configurator and diagnostics all reach it at `localhost`.
- The same project, unchanged, runs on the local simulator and on the real machine.
- It works with free container engines: Docker Engine (Linux, WSL2), Colima (macOS), Podman (all three). Docker Desktop works too but is not required.
- The plugin in the image always matches the PC tools' version.

**Non-Goals:**
- Running the plugin in the editor's Simulator board, or any editor change.
- Real CAN from inside the container on macOS or Windows (USB passthrough into a VM is out of scope). On Linux the existing install routes stay the way to use real adapters.
- Real-time behaviour: cycle times and jitter in a container on a PC VM are not representative.
- A native Windows (MSYS2) build of the plugin.
- Installing the container engine for the user. The docs give the commands; the tool detects and explains.

## Decisions

### 1. A derived image, built in our CI and published to GHCR
`docker/local-runtime/Dockerfile` does `FROM ghcr.io/autonomy-logic/openplc-runtime:<pinned>` and runs the same in-image build `install-stock.sh` already uses for `--docker-image` (`IN_IMAGE` path: Lely, dcfgen venv, plugin, simulator, editor hook) with prefix `/opt/openplc-canopen`. It sets `PYTHONPATH` for the editor hook and `CANOPEN_FORCE_SIMULATE=1`. The final stage also replaces upstream's certificate and key paths (`/workdir/webserver/certOPENPLC.pem`, `keyOPENPLC.pem`) with symlinks into the data volume, so the runtime generates its certificate there once and the pinned fingerprint survives `update` (a new container) as well as `stop`/`start`; the build fails if upstream starts shipping those files. The pinned upstream version lives in `docker/local-runtime/runtime-version`, one line, starting at the version the bench Pi runs.

The image is published as `ghcr.io/tonihoohoo/openplc-canopen-runtime:<tools version>` plus `:latest`, for `linux/amd64` and `linux/arm64`. arm64 is built on GitHub's native arm64 runners, which are free for public repositories, rather than under QEMU emulation, because Lely builds slowly there.

*Alternatives:* building the image on the user's PC from the repository (needs the source and minutes of compile on every PC). Binding a host-built `/opt/openplc-canopen` into the upstream image, as the Docker install does (needs sudo and a host path the container engine shares; macOS engines do not share `/opt` by default). Both are rejected for a first-run experience.

### 2. Image version = PC tools version
The release workflow pushes the image right after it publishes the `deploy-v<version>` wheel, with the same gates. `openplc-canopen-runtime start` uses `:<its own version>` by default (`--image` overrides it). Tools and plugin therefore always speak the same config contract and diagnostics protocol, and `update` means "the image for the tools you have", so upgrading the tools with uv and running `update` keeps them in step. If the image for the tools' version is missing (a release still in flight), `start` says so and names `--image ...:latest` as the way out.

The image's upstream runtime version only changes in a commit that edits `runtime-version`. The runtime version guard from the Docker install (canopen-docker-install) still applies inside the image and can never trip, because the image is built against the runtime it contains.

### 3. Forced simulation in the plugin, by environment variable
`CANOPEN_FORCE_SIMULATE=1` makes the plugin treat every network's `adapter.simulate` as true when it loads the config. Node `simulate` keeps its simulated-network meaning: a node is simulated unless it says `"simulate": false`, which makes it absent. The deploy tool, configurator and editor do not change the config, so the project's real adapter settings stay as they are. The plugin logs one warning per forced network at every start ("simulation forced by the runtime environment (CANOPEN_FORCE_SIMULATE=1): ..."), and the diagnostics status gets `simulation_forced: true`. The configurator and `diag status` show it next to `simulated_network`.

Only exactly `1` forces. Unset, empty or `0` leaves the config in charge, which is today's behaviour for every other install. The image sets it to `1`. Advanced Linux users can run the image with `-e CANOPEN_FORCE_SIMULATE=0` plus upstream's `--privileged --network host -v /dev:/dev` to drive a real adapter. That is documented, but the command does not offer it.

*Alternative:* the deploy tool rewrites `adapter.simulate` on upload to `local`. Rejected because the editor's own Build and Upload (the editor hook path) would bypass it, and that is the main path for editor users.

### 4. `openplc-canopen-runtime`: a thin wrapper over the engine CLI
A new console script in the tools package (module `localruntime.py`, standard library only). It shells out to `docker` or `podman` with an argument list (no shell). Engine choice: `--engine docker|podman|wsl-docker|wsl-podman`, else `$OPENPLC_CANOPEN_ENGINE`, else the first of `docker`, `podman` that answers `<engine> info`, and on Windows then `wsl -e docker` and `wsl -e podman` in the default WSL distribution. The WSL forms let a user who installed Docker Engine inside WSL2, with no Docker Desktop and so no `docker` on the Windows PATH, run the command from PowerShell; WSL2 forwards the published loopback port to Windows `localhost`. When none answers, it names what is missing per OS and points to `docs/local-runtime.md`. For example, on macOS it says that Colima is installed but not started (`colima start`), or that no engine was found.

`start` runs, idempotently:
```
<engine> run -d --name openplc-canopen-runtime
  -p 127.0.0.1:<port>:8443
  -p 127.0.0.1:<diag port>:<diag port>
  -v openplc-canopen-runtime-data:/var/run/runtime
  --cap-add SYS_NICE --cap-add SYS_RESOURCE
  --restart unless-stopped
  <image>
```
If the container already exists, `start` starts it instead. If it runs another image than the default (an older version, or one given with `--image` before), `start` keeps it and says that `update` switches it; only an explicit `--image` that differs from the container's image is refused, naming `update --image`. The data volume path follows upstream's documented `docker run`. The port is bound to loopback only, because the runtime then has a generated password but is otherwise an ordinary runtime. `--port` changes the host port. The plugin's diagnostics port (7531, `--diag-port` to change) is published as the same number on both sides, so the config's `master.diagnostics.port` and the published port agree without a mapping table.

First-start credentials: after the runtime answers on HTTPS, `start` reads the certificate fingerprint and creates a user `openplc` with a 24-character random password via `POST /api/create-user`, which the runtime accepts only while it has no users. It saves `{url, user, password, fingerprint, image, engine, port, diag_port}` to `local-runtime.json` in the tools' config directory (the same directory the configurator uses: `%APPDATA%\openplc-canopen`, `~/Library/Application Support/openplc-canopen`, `$XDG_CONFIG_HOME/openplc-canopen`), readable by the user only where the OS supports file modes. It then prints the editor settings (address `localhost:<port>`, user, password).

If the volume already has a user but the file is missing (the file was deleted, or a second PC account), `start` cannot recover the password. It says so and names `remove --data` as the reset. The certificate lives in the volume, so the pinned fingerprint survives `stop`/`start` and `update`.

Other subcommands: `stop`, `status` (engine, image, container state, runtime address, PLC state, the last `[CANOPEN]` lines of the runtime log, `--show-password`; the diagnostics status would need the project's access token, which the command does not have), `logs [-f]` (container logs), `update` (pull the image for the tools' version, or use a copy already on the PC when the pull fails, recreate the container on the same volume, keep the credentials, and say that the PLC program must be uploaded again), and `remove [--data]`.

*Podman specifics:* rootless Podman accepts the same flags. The cap-adds are kept, and if the engine refuses them, `start` retries once without and says that real-time scheduling is off, which only affects timing. On macOS and Windows, Podman runs in `podman machine`, whose port forwarding maps `127.0.0.1`. Colima and WSL2 Docker forward localhost ports the same way. All of these are verified in hardware tasks, not in CI.

### 5. `local` as a runtime target
`--runtime local` in `openplc-canopen-deploy` loads `local-runtime.json` and fills in the URL, user, password and fingerprint unless the user gave them explicitly. In `openplc-canopen-diag` (and the configurator, whose online access gets a "Local simulator runtime" button that sets the host to `local`), `local` resolves to `127.0.0.1` and the saved diagnostics port; the access token still comes from the project, as for any runtime. A missing file gives "no local runtime; run openplc-canopen-runtime start". An upload to `local` skips the simulated-config confirmation, because nothing real can be driven there. It prints one line instead: "local simulator runtime: every network runs simulated".

### 6. CI and release
- New workflow `local-runtime.yml` (path-filtered to the image, the plugin, the install script, the editor hook, the command and the test; also weekly and by hand) builds the amd64 image and runs `test/local-runtime/run.sh`. That script runs `openplc-canopen-runtime start` with Docker against the freshly built image (`--image`), checks the credentials file, then deploys `config/pingpong` (its adapter a real `vcan0`, plus diagnostics) with `--runtime local` and a PLC program compiled from a small ST file with STruC++, the editor's compiler, through its API with debug tables, so the bundle is a real runtime v4 build. It checks the forced-simulation log line, node 2 operational, `diag --runtime local status` through the published port, the ping-pong value rising, then `stop`/`start` and `update` with the same fingerprint, and `remove --data`. The forced-simulation rules are also covered by the plugin's unit and lifecycle tests.
- An arm64 job on `ubuntu-24.04-arm` builds the arm64 image and checks that the plugin library resolves all its libraries.
- `release-deploy.yml`: after the wheel release succeeds, build both architectures, push them by digest, and create the multi-arch manifest `:<version>` and `:latest`. It uses `GITHUB_TOKEN` with `packages: write`. An existing `:<version>` tag is never overwritten, matching the wheel rule. The package is made public once by hand after the first push (a GHCR setting), which is listed as a task.

## Risks / Trade-offs

- **Upstream image changes** (paths, data volume, user API) could break the derived image → the version is pinned. Moving it is a deliberate commit that runs the smoke test.
- **Container engine differences** (Colima, Podman machine, WSL2 networking) → the wrapper uses only `run`, `start`, `stop`, `rm`, `logs`, `pull`, `inspect`, `volume rm`, `info`, which are common to Docker and Podman. Each OS and engine pair is a hardware task.
- **Image size** (upstream image plus Lely and the dcfgen venv) → multi-stage build. Only the install prefix is copied into the final stage, and build tools are not kept. The size is logged in the CI job (warn above 1.6 GB); the upstream image alone is about 1.4 GB uncompressed, and the plugin adds about 40 MB.
- **Someone runs the image against real hardware believing it simulates** → forced simulation is the image default, and turning it off is documented as a Linux-only advanced setting.
- **Credentials on disk** → the runtime listens on loopback only, and the file is user-readable only. The password is not a secret beyond the local PC.
- **Timing** is not real-time in a VM → documented. The Simulated network timing requirement already says simulated timing is not real bus timing.

## Migration Plan

Additive. Existing installs and configs are unaffected: the plugin's new variable is unset everywhere except in the image. After merge, the first release with this change publishes the image. Its GHCR package visibility is set to public once.

## Open Questions

- Whether to also publish an `armv7` image. Not planned: no PC uses it, and Pi users have the stock routes.
- Slave-role networks (add-canopen-slave, not merged yet) under forced simulation should follow whatever that change defines for `adapter.simulate`. This change adds no rule of its own.
