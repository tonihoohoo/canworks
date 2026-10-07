## 1. Forced simulation in the plugin

- [x] 1.1 Read `CANOPEN_FORCE_SIMULATE` (exactly `1`) when the config is loaded and set every network's `adapter.simulate` in memory; verify with a sim test that the ping-pong config with a real `can0` adapter boots node 2 on the virtual bus and opens no interface.
- [x] 1.2 Log the forced-simulation warning at every PLC start and add `simulation_forced` to the diagnostics status; show it in `openplc-canopen-diag status` and the configurator's status banner; verify with unit tests of the status JSON and the diag output.
- [x] 1.3 Document the variable in `docs/simulator.md` (what it forces, that node `simulate: false` stays absent, that only `1` forces).

## 2. Image

- [x] 2.1 Add `docker/local-runtime/Dockerfile` (multi-stage: build with the in-image path of `scripts/install-stock.sh`, final stage = pinned upstream image + `/opt/openplc-canopen`, `PYTHONPATH`, `CANOPEN_FORCE_SIMULATE=1`, version labels) and `docker/local-runtime/runtime-version`; verify `docker build` for amd64 and that the plugin library resolves all its libraries in the final image.
- [x] 2.2 Check the image size and drop build-only files from the final stage; record the size in the CI log with a warning above 1.6 GB (the upstream image alone is about 1.4 GB).

## 3. `openplc-canopen-runtime` command

- [x] 3.1 Add `localruntime.py` and the `openplc-canopen-runtime` entry point: engine detection (`--engine`, `$OPENPLC_CANOPEN_ENGINE`, docker then podman, then on Windows `wsl -e docker` / `wsl -e podman`), argument-list calls only; verify with unit tests on a fake engine executable (the `.cmd` fake pattern on Windows from the PC tools tests).
- [x] 3.2 Implement `start` (create or start, loopback port, volume, restart policy, cap-add fallback for engines that refuse it, image-mismatch refusal, port-in-use message), the first-start user creation, fingerprint pinning and `local-runtime.json` (user-only file mode); verify with unit tests on the fake engine and a fake runtime HTTPS server.
- [x] 3.3 Implement `stop`, `status` (incl. `--show-password` and the last CANopen lines of the runtime log), `logs [-f]`, `update` and `remove [--data]`; verify with unit tests.
- [x] 3.4 Resolve `--runtime local` in `openplc-canopen-deploy` and `openplc-canopen-diag`, and add a "Local simulator runtime" button (host `local`) to the configurator's online access; skip the simulated-config question for `local` with the one-line notice; verify with unit tests of option resolution (explicit options win, missing file message) and of the deploy confirmation.
- [x] 3.5 Bump the PC tools version (next free minor after what `main` carries when this is applied).

## 4. CI and release

- [x] 4.1 Add `test/local-runtime/run.sh` (start with `--image` of the fresh build, credentials, deploy `config/pingpong` with `--runtime local` and a PLC program compiled by STruC++, forced-simulation log, node 2 operational, diagnostics through the published port, values moving, stop/start and update with the same fingerprint, remove `--data`) and a path-filtered workflow `local-runtime.yml` running it with Docker on `ubuntu-24.04`, plus an arm64 build-only job on `ubuntu-24.04-arm`; verify both green on the PR.
- [x] 4.2 Extend `release-deploy.yml`: after the wheel release, build amd64 and arm64 on native runners, push by digest, create the `:<version>` and `:latest` manifest with `GITHUB_TOKEN` (`packages: write`), never overwrite an existing `:<version>`; verify the build without push on the PR (`local-runtime.yml` builds both architectures with the same Dockerfile) and document the gates in the workflow header.
- [ ] 4.3 After the first release with this change: set the GHCR package `openplc-canopen-runtime` to public (one-time manual setting) and check an anonymous `docker pull`.

## 5. Docs

- [x] 5.1 Write `docs/local-runtime.md`: engine setup per OS without Docker Desktop (Windows: Docker Engine or Podman in WSL2, used from PowerShell through `wsl`; macOS: Colima via Homebrew or Podman; Linux: Docker Engine or Podman), `start`, editor connection, deploy and configurator with `local`, `update`, `remove`, troubleshooting (engine not running, port in use, lost credentials), and the limits (all simulated, no real-time timing, no real CAN adapters on Windows and macOS, the `CANOPEN_FORCE_SIMULATE=0` route for Linux experts).
- [x] 5.2 Update README (feature bullet "Try without hardware", PC tools list, Layout for `docker/local-runtime/` and `test/local-runtime/`), `docs/install-pc.md`, `docs/simulator.md`, `docs/deploy.md`, `docs/diagnostics.md` and `docs/configurator.md`.

## 6. Hardware and platform checks (manual)

- [ ] 6.1 macOS on an M-series Mac with Colima (no Docker Desktop): `start`, editor Build and Upload of a CANopen project to `localhost`, debugger shows moving values from simulated nodes, configurator online view and Simulation view with `local`, `update`, `remove --data`.
- [ ] 6.2 macOS with Podman machine: `start`, deploy with `--runtime local`, `status`.
- [ ] 6.3 Windows with Docker Engine in WSL2 (no Docker Desktop), tools and editor on Windows: `start` from PowerShell through `wsl -e docker`, editor Build and Upload to `localhost`, configurator with `local`.
- [ ] 6.4 Linux PC with rootless Podman: `start` (cap-add fallback message if it applies), deploy with `--runtime local`.
