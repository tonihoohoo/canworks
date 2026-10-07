## Why

Trying a CANopen project today needs a Linux host running OpenPLC Runtime v4 with the plugin, usually a Raspberry Pi. The plugin's simulated network (`adapter.simulate`) already removes the need for CAN hardware and devices, but not for that host. The editor's own "OpenPLC Simulator" board cannot help: it is an emulated 8-bit microcontroller that runs user logic only, with no plugins (research: `openplc-simulator-2026-10-07`). A ready runtime with the plugin, started with one command on the user's own Windows, macOS or Linux PC, makes the whole project (PLC program, editor upload and debugger, configurator online and Simulation views, scenarios) testable without any hardware. It needs a container engine but not Docker Desktop.

## What Changes

- **Simulator runtime image** `ghcr.io/tonihoohoo/openplc-canopen-runtime:<version>` for `linux/amd64` and `linux/arm64` (Apple M-series Macs, ARM Windows laptops), built `FROM` the upstream runtime image of a pinned version. The plugin, `dcfgen`, the simulator and the editor hook are built in, with the same build `scripts/install-stock.sh` runs inside the runtime image today. Nothing in the upstream image is changed beyond adding them.
- **Forced simulation**: in this image every CANopen network runs as a simulated network, whatever `adapter.simulate` says in the uploaded config. So one project can be uploaded unchanged to the local simulator and to the real machine. The plugin logs it at every start and the diagnostics status reports it. An environment variable turns it off for advanced Linux use.
- **New command `openplc-canopen-runtime`** in the PC tools package:
  - `start` pulls the image matching the tools' own version and runs it with Docker or Podman (picked automatically, or `--engine`). The port is published on `127.0.0.1` only (default 8443) and runtime data goes in a named volume. On first start it creates a runtime user with a generated password, pins the certificate fingerprint and prints the editor connection settings.
  - Also `stop`, `status`, `logs`, `update` (newer image, same volume) and `remove` (`--data` also deletes the volume).
- **`--runtime local`** for `openplc-canopen-deploy`, `openplc-canopen-diag` and the configurator's online connection uses the address, user, password and fingerprint saved by `start`. Uploads to it skip the simulated-config question and say once that everything runs simulated.
- **Release**: the image is built and pushed by the release workflow with the same version as the PC tools wheel, so tools and plugin always match. CI builds the image and runs a smoke test on changes to the image or the plugin.
- **Docs**: a new `docs/local-runtime.md` covers the engine setup per OS without Docker Desktop (Colima or Podman on macOS, Docker Engine or Podman in WSL2 on Windows, Docker or Podman on Linux), plus README and simulator docs updates.

## Capabilities

### New Capabilities
- `canopen-local-runtime`: the simulator runtime image (contents, tags, platforms, forced simulation), the `openplc-canopen-runtime` command (engine choice, start, credentials, stop, status, logs, update, remove), the `local` runtime target in the PC tools, and the image's release and CI.

### Modified Capabilities
- `canopen-simulated-bus`: forced simulation of every network when the runtime sets it, and its visibility in the log and status.
- `canopen-deploy`: `--runtime local`, and no simulated-config question when uploading to the local simulator runtime.

## Impact

- New `docker/local-runtime/Dockerfile` (and its build context script), reusing `scripts/install-stock.sh`'s in-image build path.
- `plugin/src`: read `CANOPEN_FORCE_SIMULATE` when loading the config (networks run simulated), log line, `simulation_forced` in the diagnostics status.
- `tools/deploy`: new `localruntime.py` module and `openplc-canopen-runtime` entry point. The `local` target is resolved in the deploy CLI, diag and configurator. Deploy tool version bump.
- `.github/workflows/release-deploy.yml` (multi-arch image push to GHCR after the wheel release), `ci.yml` or `integration.yml` (image build and smoke test), `pc-tools.yml` unchanged (no container engine on its runners).
- Docs: `docs/local-runtime.md`, README, `docs/simulator.md`, `docs/install-pc.md`, `docs/deploy.md`, `docs/diagnostics.md`, `docs/configurator.md`.
- No change to the stock and Docker install routes or to the editor. The upstream image license applies to the derived image, as it does to the managed Docker install.
