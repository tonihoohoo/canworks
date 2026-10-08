## Why

The repository is about to carry a second CAN protocol (J1939, change `add-j1939-ecu`) next to CANopen. Both share the adapter handling, bit rate detection, raw frames, the bus trace and frame inspector, the diagnostics channel, the deploy tool, the configurator and the simulator runtime. Keeping one repository avoids keeping copies of that code in sync. The name `openplc-canopen` would then describe only half of it.

The new name is **opencan-plc**. The rename happens once, before the first J1939 code lands, so J1939 is never written against names that change a week later.

## What Changes

- **Repository**: `tonihoohoo/openplc-canopen` becomes `tonihoohoo/opencan-plc`. GitHub redirects the old URLs (web, git, API), so existing clones and links keep working. In-repo links, badges, the JSON Schema `$id`s and the image source label use the new URL.
- **PC tools package**: the distribution `openplc-canopen-deploy` becomes `opencan-plc`. The import package `openplc_canopen_deploy` becomes `opencan_plc`. The release wheel becomes `opencan_plc-<version>-py3-none-any.whl`. Release tags stay `deploy-v<version>` and the version line continues (next release 0.41.0).
- **Commands**: `opencan-deploy`, `opencan-config`, `opencan-diag`, `opencan-sim-runtime`. The old names `openplc-canopen-deploy`, `openplc-canopen-config`, `openplc-canopen-diag` and `openplc-canopen-sim-runtime` stay installed as aliases. Each prints one line to stderr naming the new command, then behaves exactly like it. The existing `openplc-canopen-runtime` alias keeps working the same way.
- **Environment variables**: every `OPENPLC_CANOPEN_*` variable the PC tools read gets an `OPENCAN_*` name. The new name wins when both are set, and the old one is still read.
- **Per-user settings folder**: `…/opencan-plc` instead of `…/openplc-canopen`. On first use, when only the old folder exists, its contents are copied (not moved), so an older tools version installed beside it keeps working.
- **Simulator runtime image and container**: the image becomes `ghcr.io/tonihoohoo/opencan-plc-sim-runtime` and the container `opencan-sim-runtime`. `start` and `update` take over an `openplc-canopen-sim-runtime` container on its data volume, as they already do for the 0.30 name. The old image name gets no new tags.
- **Docs and UI text**: README, docs, the configurator page title, generated HTML documentation and release notes use the new names. The README says what was renamed and how to upgrade.
- **Main specs**: the names in `openspec/specs/` follow the rename in the same PR. Archived changes are history and stay as they are.
- **Rename script**: `scripts/rename_to_opencan.py` applies the whole mapping (path moves and text replacements) and is idempotent. The PR's rename commit is that script's output, and in-flight branches run the same script before merging `main`.

**Not renamed** (they live on PLCs in the field, and changing them would need a migration without gain):
- the runtime plugin name `canopen` in `plugins.conf` and `libcanopen_plugin.so`
- the install path `/opt/openplc-canopen`
- the uploaded `conf/canopen.json` and the project folder `canopen/`
- the editor hook's module
- the diagnostics port and protocol
- the spec capability names `canopen-*`
- the private repository `openplc-canopen-private`

## Capabilities

### New Capabilities
- `toolkit-names`: the project, package, command, image, container, settings-folder and environment-variable names; the aliases and fallbacks that keep the old names working; the on-device names that stay unchanged.

### Modified Capabilities
- none (the main specs' old names are rewritten in place by the same mapping; no requirement's behaviour changes)

## Impact

- Every PC tools module (package directory move), `tools/deploy/pyproject.toml`, `tools/editor-hook/pyproject.toml` (dependency name), `tools/deploy/tests/`, `.github/workflows/` (wheel name, image name, package paths), `.github/scripts/test_shard.py` paths, `docker/local-runtime/Dockerfile` labels, `schema/*.json` `$id`, `scripts/install-stock.sh` (only the wheel/package it pip-installs; the on-device paths stay), README and `docs/`.
- No plugin (C++) behaviour change. No config format change. No change on an installed PLC beyond the newer tools version.
- **When it lands**: when no other pull request is open, or right after the open ones merge (today #39 and `propose/add-machine-sim`). Branches started later begin from the renamed `main`.
- **After the merge**, the owner renames the repository in GitHub Settings. Until then, the new URLs in the docs do not resolve.
- Licence stays Apache-2.0.
