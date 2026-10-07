# Proposal

## Why

The PC tools (`openplc-canopen-config`, `openplc-canopen-deploy`, `openplc-canopen-diag`) already run on a Linux desktop: the release wheel is platform independent, the code has Linux paths (settings in `$XDG_CONFIG_HOME` or `~/.config/openplc-canopen`, the editor's userData in `~/.config/open-plc-editor`), and the OpenPLC Editor ships Linux AppImages (x64 and ARM64) whose `openplc-cli install-cli` puts a shim in `~/.local/bin`. Installing the 0.28.0 wheel with `uv tool install --python 3.12 --managed-python` on Linux x86_64 and running `test/pc-tools/smoke.py` passes.

What is missing is the promise and the proof:

- `docs/install-pc.md` gives the uv steps for Windows and macOS only, and its bin folder sentence leaves Linux out. `docs/configurator.md`, `docs/deploy.md`, `tools/deploy/README.md` and the README's "PC tools on Windows and macOS" say the same.
- The pip alternative says `python3 -m pip install ./tools/deploy`, which Debian 12 and later and Ubuntu 23.04 and later refuse (PEP 668, "externally-managed-environment").
- `pc-tools.yml`, the only job that tests the tools installed the way users install them (wheel + uv + uv-managed Python), has no Linux runner. CI runs the same tests on Linux, but with pip into the runner's Python.
- `install-pc.md` says the PC tools job runs "whenever `tools/deploy/` changes"; since the CI sharding change it runs only on version bumps on `main`, release tags and by hand.

The CAN adapter question needs no code: the PC tools never open a CAN interface. Every online function goes to the plugin on the runtime over the network, so a SocketCAN or slcan adapter on a Linux PC is only used when the runtime itself runs there, which the existing native and Docker install routes already support.

## What Changes

- `docs/install-pc.md`: Linux in step 1 (the official `install.sh`, or the distribution's package where it has one), `~/.local/bin` as the Linux bin folder, the Linux settings folder, the editor's AppImage and `openplc-cli install-cli` on Linux, a note that the PC tools reach the CAN bus only through the runtime, and the PEP 668 note in the pip section (use uv or pipx there). The release section's sentence about when the PC tools job runs is corrected.
- `docs/configurator.md`, `docs/deploy.md`, `tools/deploy/README.md`, README: "Windows, macOS and Linux" where they point at the install steps; the README's CI section becomes "PC tools on Windows, macOS and Linux".
- `.github/workflows/pc-tools.yml`: `ubuntu-24.04` and `ubuntu-24.04-arm` join `windows-latest` and `macos-14`, running the same steps (install the wheel with uv, test suite, release tag check, smoke). Its name becomes "PC tools (Windows, macOS, Linux)", and the release workflow's `workflow_run` list follows the new name so releases keep waiting for it. Triggers stay as they are (version bumps on `main`, release tags, by hand), so this adds two Linux jobs per release and nothing per pull request.
- No change to the tools' code or to the package version: the wheel and its contents are the same.

## Capabilities

### New Capabilities
<!-- none -->

### Modified Capabilities
- `canopen-pc-install`: install steps documented for Linux too, the pip route's PEP 668 note, and the installed-wheel test runs on Linux x86_64 and ARM64 as well as Windows and macOS.

## Impact

- `docs/install-pc.md`, `docs/configurator.md`, `docs/deploy.md`, `tools/deploy/README.md`, `README.md`.
- `.github/workflows/pc-tools.yml`, `.github/workflows/release-deploy.yml` (workflow name in `workflow_run`).
- Check names: `pc-tools (ubuntu-24.04)` and `pc-tools (ubuntu-24.04-arm)` are new. They are not pull request checks, so no ruleset changes.
- Not in scope: a PyInstaller binary or `.deb`/`.rpm` package (uv already gives a no-Python install), a desktop launcher, and a "local bus" mode where the PC tools open a CAN interface on the PC without a runtime.
