## Why

canworks is built and tested against one OpenPLC runtime release, but the runtime it ends up on is chosen in several places that each follow upstream on their own. CI and the local simulator runtime pin v4.2.4. The integration test pulls `openplc-runtime:latest`. The Devices page's **Install OpenPLC Runtime and canworks** runs upstream's installer with no version, so it installs whatever is newest that day, and the bootloader that manages the runtime always comes from `latest`. Bench devices already run v4.3.1, so CI no longer tests what users run.

Upstream's next release (v4.3.2, on its development branch now) sizes the I/O image from the program and would leave canworks inactive on ordinary projects (research/openplc-runtime-upstream-2026-10-22.md). A new install must not pick that up on the day it ships. Toni wants everything frozen: one runtime version that canworks installs, tests and keeps devices on. Updating stays possible, but only on purpose.

## What Changes

- **One pin, v4.3.1.** `docker/local-runtime/runtime-version` becomes `v4.3.1` (with its archive sha256). It stays the single source for CI, the local simulator runtime, the bridge build and the PC tools (`TESTED_RUNTIME`). A new `docker/local-runtime/bootloader-version` pins upstream's bootloader image (`bootloader-v1.1.0`).
- **CI follows the pin everywhere.** The integration job and `test/docker/run.sh` use the pinned image instead of `:latest`. A test fails when any workflow or script names an `openplc-runtime` image or `runtime.getedge.me` install without the pin.
- **Installs are pinned.** `install-runtime.sh --with-openplc` downloads the release first, then runs upstream's installer with `--runtime-version <pin> --bootloader-version <pin>` from that release, so a failed download changes nothing and the device gets exactly the tested runtime.
- **Back to the pinned runtime.** New `install-stock.sh --runtime-version vX` (Docker mode): it sets the bootloader spec's runtime version, keeps every other spec entry (the canworks bind and environment included), pulls that image, builds the plugin in it and recreates the container. The Devices page passes the release's pin on every plugin install, update and rebuild on a managed Docker runtime, so canworks' own actions always land on the tested runtime.
- **Devices page.** When a managed Docker device runs another runtime version than the pin (after an update from the OpenPLC Editor), the main action is **Switch runtime to v4.3.1** (confirms that the PLC stops and comes back without a program). It replaces **Rebuild for runtime vN** there. The runtime row says "canworks runs on runtime v4.3.1; this device runs vN" for any other version, newer or older. The install confirmation names the version it installs instead of "upstream's newest".
- **Runtime release watch** keeps opening its issue when upstream releases. Moving the pin stays a deliberate canworks change with a full CI run.
- **Docs.** README and `docs/install-stock.md`/`docs/devices.md`: canworks runs on OpenPLC runtime v4.3.1, how to stay there, what an update from the Editor does (CAN stays off with a clear message until the switch back), and the v4.3 runtime behaviour that outputs go to 0 for one cycle before `on_plc_stop` is sent.

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

- `device-install`: pinned runtime and bootloader on install; **Switch runtime to vP** main action; tested-version note for any other version; install confirmation names the version.
- `canopen-docker-install`: `--runtime-version` sets the spec's runtime version and builds for it.
- `canopen-ci`: one runtime pin for every CI job and script, checked by a test.

## Impact

- `docker/local-runtime/runtime-version`, `runtime-sha256`, new `bootloader-version`; `tools/deploy/canworks/devices/plan.py` (`TESTED_RUNTIME`, main action, texts) and the Devices page job arguments.
- `scripts/install-runtime.sh` (download first, pinned upstream install), `scripts/install-stock.sh` (`--runtime-version`, spec version edit in `spec_tool`), `install-runtime.ps1` help.
- `.github/workflows/integration.yml`, `test/docker/run.sh`; tests in `tools/deploy/tests/`, `test/pc-tools/test_install_scripts.py`, `test/docker/test_install_docker.py`.
- CI runs the whole suite on v4.3.1 for the first time; failures from upstream changes (outputs zeroed on stop, plugins initialised at power-on) are fixed in this change.
- Not in scope: native runtimes (a git checkout the user controls; the note still shows), hiding the Editor's update button (upstream), and v4.3.2 support (separate change before moving the pin).
