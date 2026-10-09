## Why

The repository is about to carry a second CAN protocol (J1939, change `add-j1939-ecu`) next to CANopen. Both share the adapter handling, bit rate detection, raw frames, the bus trace and frame inspector, the diagnostics channel, the deploy tool, the configurator and the simulator runtime. Keeping one repository avoids keeping copies of that code in sync.

The name `openplc-canopen` would then describe only half of it, and it ties the project to one PLC. The tools already work with no PLC at all (a USB adapter on the PC), and CODESYS may become a second PLC target.

The new name is **canworks** (chosen 2026-10-09). It is neutral about protocol, PLC and vendor. The project is an open CAN toolkit to configure, commission, diagnose, trace and simulate CANopen and J1939 networks, with runtime plugins per PLC target (OpenPLC today).

The project is in active development and not in real use anywhere (2026-10-09). So the rename is a **clean cut**: every name changes, including the ones on the PLC, with no aliases, fallbacks or migration code. The one exception is a small cleanup in the install script so the development bench does not keep a stale plugin line.

## What Changes

- **Repository**: `tonihoohoo/openplc-canopen` becomes `tonihoohoo/canworks`. GitHub redirects the old URLs. In-repo links, the JSON Schema `$id`s and the image source label use the new URL.
- **PC tools**:
  - distribution and import package `canworks` (was `openplc-canopen-deploy` / `openplc_canopen_deploy`)
  - wheel `canworks-<version>-py3-none-any.whl`
  - commands `canworks-deploy`, `canworks-config`, `canworks-diag`, `canworks-sim-runtime`
  - settings folder `canworks`
  - environment variables `CANWORKS_*`

  The old command names, variables and folder are gone. Release tags stay `deploy-v<version>` and the version continues (0.41.0).
- **On the PLC**:
  - the plugin registers as `canworks` in `plugins.conf` with `libcanworks_plugin.so`
  - it installs under `/opt/canworks`
  - the uploaded config is `conf/canworks.json` with its files in `conf/canworks/`
  - the generated files go to `.canworks/`
  - the device simulator binary is `canworks-sim`
  - the editor hook module is `canworks_hook` and looks for the editor project folder `canworks/` (with `canworks/canworks.json`)
  - `CANOPEN_FORCE_SIMULATE` becomes `CANWORKS_FORCE_SIMULATE`
- **Unchanged on the PLC**: the diagnostics port 7531 and the diagnostics protocol version.
- **Schemas**: `schema/canworks.v1.schema.json`, `canworks.v2.schema.json`, `canworks-sim.v1/v2.schema.json`. The `schema_version` values inside configs stay 1 and 2, so the contract does not restart.
- **Simulator runtime image and container**: image `ghcr.io/tonihoohoo/canworks-sim-runtime`, container `canworks-sim-runtime`.
- **PLC library**: the SDO function block library file becomes `canworks.stlib`. The block names stay, because they are CANopen blocks.
- **Install cleanup**: `install-stock.sh` removes a leftover `canopen` plugin line, `/opt/openplc-canopen` and the old runtime-spec entries when it finds them, once, and says so.
- **Docs and UI text**: README (new title and tagline), docs, configurator page title, generated HTML documentation and release notes.
- **Main specs**: names in `openspec/specs/` follow the rename in the same PR. Archived changes stay as history. Spec capability names `canopen-*` stay, because they describe CANopen behaviour.
- **Rename script**: `scripts/rename_to_canworks.py` applies the mapping (path moves and text) and is idempotent. The PR's rename commit is its output, and in-flight branches run it before merging `main`. CI runs its `--check` so no old name comes back.

**Not renamed** (they describe CANopen itself):
- the `canopen-*` spec capabilities
- example folders and files under `config/` and `examples/` that hold CANopen configs
- the CANopen PLC block names

## Capabilities

### New Capabilities
- `toolkit-names`: the project, package, command, PLC-side, image and settings names, the install cleanup of an older install, and the CI check that no old name remains.

### Modified Capabilities
- none (main specs are rewritten in place by the same mapping; no behaviour other than names changes)

## Impact

- **Every area is touched**: PC tools (package move), plugin (library and plugin name, config file name, generated folder, simulator binary name), `scripts/install-stock.sh` and `scripts/docker_spec.py`, the editor hook, `.github/workflows/`, `.github/scripts/test_shard.py`, `docker/local-runtime/`, `schema/`, `library/`, tests, README and `docs/`.
- **Existing installs must be redeployed** after the merge: re-run `install-stock.sh` on the bench PLC, rename the template project's `canopen/` folder to `canworks/`, and reinstall the PC tools. Nothing else uses the project.
- **When it lands**: when no other pull request is open, or right after the open ones merge (today #39 and `propose/add-machine-sim`). Branches started later begin from the renamed `main`.
- **After the merge**, the owner renames the repository in GitHub Settings.
- Licence stays Apache-2.0.
