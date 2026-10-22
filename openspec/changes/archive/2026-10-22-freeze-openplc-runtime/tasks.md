## 1. Pin

- [x] 1.1 `docker/local-runtime/runtime-version` → `v4.3.1`, `runtime-sha256` → `b00f00776c25fb264a78db64f15e8364ff33d9a5e63a8b2fca8319c718dbd7a8` (git archive of the tag, as the build-plugin action checks); new `bootloader-version` = `bootloader-v1.1.0`
- [x] 1.2 `plan.py`: `TESTED_RUNTIME = "v4.3.1"`, new `PINNED_BOOTLOADER`; `test_locked_versions.py` checks both against the files
- [x] 1.3 `.github/workflows/integration.yml` and `test/docker/run.sh`: pinned image instead of `:latest`
- [x] 1.4 Pin test (canopen-ci "One runtime pin"): scan `.github/`, `scripts/`, `test/`, `docker/` for literal `openplc-runtime(-bootloader)?:<tag>` and for upstream installer runs without the pins; fixtures allow-listed

## 2. Install scripts

- [x] 2.1 `install-runtime.sh`: download and unpack the release before the OpenPLC install; read both pins from it; run upstream's installer with `bash -s -- --runtime-version … --bootloader-version …`; `CANWORKS_RUNTIME_VERSION` / `CANWORKS_BOOTLOADER_VERSION` override for manual tests; dry run prints the pinned command
- [x] 2.2 `install-stock.sh --runtime-version vX`: `spec_tool version` (atomic, keeps other keys), `docker pull` first with the download message on failure, then the existing Docker path; refused on native; no-op when the spec already names vX
- [x] 2.3 `install-runtime.sh --pinned-runtime` (the release's pin to `install-stock.sh --runtime-version` on managed Docker, not on uninstall or native), over `--ssh` too; `install-runtime.ps1` help (options pass through)

## 3. Devices page

- [x] 3.1 `plan.py`: **Switch runtime to vP** main action for managed Docker with a version other than the pin (replaces **Rebuild for runtime vN** there); every managed-Docker plugin job passes `--pinned-runtime`
- [x] 3.2 Texts: runtime-row note for any other known version ("canworks runs on runtime v4.3.1; this device runs vN."), install confirmation names the version, switch confirmation

## 4. Tests

- [x] 4.1 `tools/deploy/tests/test_devices.py`, `test_configurator_devices_page.py`: switch action, older/newer notes, job arguments, confirmations
- [x] 4.2 `test/pc-tools/test_install_scripts.py`: release downloaded before the OpenPLC install, pinned arguments to upstream's installer, failed download installs nothing, pass-through of `--runtime-version` (also over `--ssh`)
- [x] 4.3 `test/docker/test_install_docker.py`: `--runtime-version` rewrites only the version, keeps the canworks entries, pull failure changes nothing, native refuses; v4.2.4 fixture strings updated where they mean the pin
- [x] 4.4 Full CI on v4.3.1; fix what fails on the runtime's behaviour changes (outputs zeroed on stop with one extra cycle, plugins initialised at power-on) and note each fix in the PR

## 5. Docs and release

- [x] 5.1 README and `docs/install-stock.md`, `docs/devices.md`: canworks runs on OpenPLC runtime v4.3.1; updates from the Editor turn CAN off until **Switch runtime**; `--runtime-version`; how to try another version by hand
- [x] 5.2 README "Safe stops": with runtime v4.3 the outputs go to 0 for one cycle before `on_plc_stop` is sent; same line in `docs/config.md` (PLC stop)
- [x] 5.3 `runtime-watch.yml` issue text names `bootloader-version` too
- [x] 5.4 Tools minor version bump (0.115.0)

## 6. Hardware

- [ ] 6.1 Linux device (managed Docker, v4.3.1): Devices page update with the new release passes the pin, runtime stays v4.3.1, node OPERATIONAL after upload
- [ ] 6.2 Same device: spec moved to another runtime version by hand (or from the Editor), page shows **Switch runtime to v4.3.1**; running it brings back v4.3.1 with the canworks entries, CAN works after an upload
- [ ] 6.3 PLC stop with a node on `on_plc_stop: keep`: the node's outputs go to 0 and stay there (records the v4.3 behaviour the docs describe)
- [ ] 6.4 Bootloader on the bench: `latest` image id equals `bootloader-v1.1.0`
