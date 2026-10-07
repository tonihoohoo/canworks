## Why

The local simulator runtime is published as `ghcr.io/tonihoohoo/openplc-canopen-runtime` and started with `openplc-canopen-runtime`. Both names read like a production runtime, although every CANopen network in that image is forced to run simulated. Someone who sees the image or the container next to a real runtime cannot tell that it never drives a CAN bus. The name should say "simulated".

## What Changes

- **New name `openplc-canopen-sim-runtime`** for the image (`ghcr.io/tonihoohoo/openplc-canopen-sim-runtime`), the command, the container and the data volume (`openplc-canopen-sim-runtime-data`). `openplc-canopen-sim` stays the device simulator command on the runtime host; the two do not share a name.
- **Old command kept for one release**: `openplc-canopen-runtime` still works, prints one line saying it is renamed, and runs the same subcommand. It is removed in the release after.
- **Taking over an existing local runtime**: `start` and `update` find a container from the old name, replace it with the new one on the same data volume, and keep the saved credentials and the certificate fingerprint. Nothing is lost and no `remove --data` is needed.
- **Release**: new versions are pushed only under the new image name. Tags already pushed under the old name stay where they are and are not updated.
- **Unchanged**: `--runtime local`, host `local` in the configurator, `local-runtime.json`, `docs/local-runtime.md`, `docker/local-runtime/`, the capability name `canopen-local-runtime`, and the "local simulator runtime" wording in the docs.
- PC tools version bump (next free minor).

## Capabilities

### New Capabilities

### Modified Capabilities
- `canopen-local-runtime`: the image, command, container and volume names, the one-release alias of the old command, and taking over a container started under the old name.

## Impact

- `tools/deploy/openplc_canopen_deploy/localruntime.py` (names, takeover of the old container), `pyproject.toml` (new entry point plus the old one as alias), messages in `cli.py`, `diag.py` and the configurator page, tests.
- `docker/local-runtime/Dockerfile` (image title label), `.github/workflows/release-deploy.yml` (image name), `local-runtime.yml` and `test/local-runtime/run.sh` (command name).
- Docs: `docs/local-runtime.md`, README, `docs/install-pc.md`, `docs/deploy.md`, `tools/deploy/README.md`.
- After merge: the GHCR package `openplc-canopen-sim-runtime` is new; if it is not pullable anonymously after the first release, its visibility is set to public once. The old package `openplc-canopen-runtime` can be deleted by hand once no one uses 0.30.x.
