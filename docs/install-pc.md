# Installing the PC tools: configurator, deploy tool, diagnostics

`canworks-config`, `canworks-deploy`, `canworks-diag`, `canworks-sim-runtime` and `canworks-j1939-sim` run on the engineering PC (Windows, macOS or Linux). They come as one package. `canworks-sim-runtime` runs a [local simulator runtime](local-runtime.md) in a container and needs a container engine (Docker Engine, Podman or Colima); the other four need nothing else. `canworks-j1939-sim` simulates a J1939 ECU from a DBC file ([j1939.md](j1939.md#simulator)). The recommended way installs them with [uv](https://docs.astral.sh/uv/), which brings its own Python: nothing else needs to be on the PC, and no admin rights are needed. Installing with pip into a Python you already have also works: see [With pip or pipx](#with-pip-or-pipx).

The tools call the editor's `openplc-cli` for **Build only** and **New editor project**; it comes with the OpenPLC Editor (`openplc-cli install-cli`, or set `OPENPLC_CLI` to it).

## One line: install or update

This installs uv if the PC has none, then the newest release of the tools, and on a second run updates them. Windows (PowerShell):

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://raw.githubusercontent.com/tonihoohoo/canworks/main/scripts/install-pc.ps1 | iex"
```

macOS and Linux (Terminal):

```sh
curl -LsSf https://raw.githubusercontent.com/tonihoohoo/canworks/main/scripts/install-pc.sh | sh
```

It also adds the **canworks configurator** app shortcut, which starts the configurator with no terminal or console window: in the Start menu and on the desktop on Windows, in `~/Applications` on macOS (made on the Mac, so Gatekeeper lets it start), among the applications on Linux. Its uninstall removes the shortcut too.

Options: a given release (`--version 0.82.0`), uninstall (`--uninstall`), no shortcut (`--no-shortcut`), a local wheel (`--wheel FILE`), another Python (`--python PATH`). On macOS and Linux they follow `sh -s --` (`curl ... | sh -s -- --version 0.82.0`); on Windows run the script as a script block: `& ([scriptblock]::Create((irm https://raw.githubusercontent.com/tonihoohoo/canworks/main/scripts/install-pc.ps1))) -Version 0.82.0` (`-Uninstall`, `-NoShortcut`, `-Wheel FILE`, `-Python PATH`). The scripts only install released wheels, never the code on `main`, and find the newest release without the GitHub API. To pin the script to a release, put the tag in place of `main` (`.../canworks/deploy-v0.82.0/scripts/install-pc.sh`). To read it before running it, download it first (`curl -LsSfO .../install-pc.sh`, then `sh install-pc.sh`). Then check as in step 2 below. The manual steps follow.

## 1. Install uv (once per PC)

Windows (PowerShell):

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

macOS and Linux (Terminal):

```sh
curl -LsSf https://astral.sh/uv/install.sh | sh
```

`winget install astral-sh.uv`, `brew install uv` and a Linux distribution's own `uv` package (where it has one) work too. Open a new terminal afterwards so `uv` is on PATH.

## 2. Install the tools

Download `canworks-<version>-py3-none-any.whl` from the repository's **Releases** page (the newest `deploy-v<version>` release; or use `gh release download deploy-v<version>`). The same file is for every operating system. Then, in the folder you downloaded it to:

```sh
uv tool install --compile-bytecode --python 3.12 canworks-<version>-py3-none-any.whl
```

`--compile-bytecode` compiles the tools at install, so the first start is as fast as later ones.

Without a release file, uv installs the newest code straight from GitHub; this needs no git: `uv tool install --force --compile-bytecode "canworks @ https://github.com/tonihoohoo/canworks/archive/refs/heads/main.zip#subdirectory=tools/deploy"`. If uv cannot install its own Python on the PC (seen on a Windows IoT LTSC build), point `--python` at a Python 3.10 or newer that is already installed instead.

uv downloads Python 3.12 if the PC has none, puts the tools in their own environment, and links the five commands into its bin folder (`%USERPROFILE%\.local\bin` on Windows, `~/.local/bin` on macOS and Linux). If it warns that the folder is not on PATH, run `uv tool update-shell` and open a new terminal. Check:

```sh
canworks-deploy --version
canworks-config            # opens the configurator in the browser
```

The configurator runs in the background, opens in the default browser and stops when its last tab is closed; **Quit** in its header stops it too. After a manual install, `canworks-config --create-shortcut` adds the app shortcut that starts it without a terminal (`--remove-shortcut` removes it). Over SSH and on Linux without a desktop it stays in the terminal and prints its address with a one-time code: open it yourself; `--no-browser` skips the attempt, `--foreground` keeps it in the terminal anywhere. More in [configurator.md](configurator.md#start).

Linux works with x86_64 and ARM64 (glibc distributions; uv's Python and the compiled dependencies come as wheels for both).

The first install needs internet access to github.com (Python) and pypi.org (the Python packages the tools use: `jsonschema`, `python-can`, `pyserial`, `cantools`, `can-j1939`). Behind a company proxy that inspects TLS, add `--native-tls` (or set `UV_NATIVE_TLS=1`) so uv trusts the certificates installed in the operating system.

## Update and uninstall

The one-line installer above updates when run again (and uninstalls with `--uninstall`). By hand:

```sh
uv tool install --force --compile-bytecode --python 3.12 canworks-<new version>-py3-none-any.whl
canworks-config --remove-shortcut    # before uninstalling, when the shortcut was added
uv tool uninstall canworks
```

The shortcut runs the installed tools, so it keeps working after an update.

The configurator's own settings (theme, online access, its log `configurator.log`) and the local simulator runtime's credentials (`local-runtime.json`) live in the user's settings folder (`%APPDATA%\canworks` on Windows, `~/Library/Application Support/canworks` on macOS, `$XDG_CONFIG_HOME/canworks` or `~/.config/canworks` on Linux) and survive both. Uninstalling leaves a local simulator runtime container in place: run `canworks-sim-runtime remove --data` first to delete it. After an update, `canworks-sim-runtime update` moves the local runtime to the image of the new version.

## The editor on Linux

The OpenPLC Editor comes for Linux as an AppImage (x64 and ARM64) on its releases page. Make it executable (`chmod +x`) and start it once: like on Windows and macOS, the first run puts the `openplc-cli` command on PATH, here as a shim in `~/.local/bin` that points at the AppImage file. Keep the AppImage where it is, or after moving it run `./OpenPLC.Editor-<version>.AppImage --cli install-cli` to point the shim at the new place. The same command installs the shim on a machine without a desktop (over SSH, a server, WSL without a GUI); `openplc-cli` then runs headless, so New editor project and Build only work there too. The AppImage needs FUSE 2: if it does not start, install it (`sudo apt install libfuse2t64`, or `libfuse2` on older releases) or run it with `--appimage-extract-and-run`. The tools then find `openplc-cli` on PATH; `OPENPLC_CLI` overrides it. The `canworks` editor library goes into the editor's settings folder, `~/.config/open-plc-editor` (or under `$XDG_CONFIG_HOME`).

## CAN adapters

The PC tools reach the CAN bus in one of two ways. Through a runtime: everything online (scan, object dictionary, parameters, trace, LSS, simulated devices) goes to the plugin on the runtime over the network. Or directly through a USB CAN adapter plugged into the PC, with no runtime: scan, object dictionary, parameters, LSS and trace, as a guest on the bus ([pc-adapter.md](pc-adapter.md)). The tools bring what an adapter needs (python-can and pyserial); an slcan adapter such as a CANable with stock firmware needs no driver:

- **Windows 10 and 11:** the built-in USB serial driver; the adapter shows as `COM5` or similar (Device Manager, Ports).
- **macOS:** `/dev/tty.usbmodem14101` or similar.
- **Linux:** `/dev/ttyACM0` or similar; join the `dialout` group once to open serial ports (`sudo usermod -aG dialout $USER`, then log in again). SocketCAN interfaces (`can0`, `vcan0`) work too.

A gs_usb (candleLight) adapter works too: on Windows the tools bring its driver and libusb, so there is nothing to install; on macOS run `brew install libusb` once; on Linux it is a SocketCAN interface.

`canworks-diag adapters` lists the adapters it finds. `canworks-j1939-sim` takes the same `--adapter` values.

The adapter can also be in another Linux machine, at the bus, while the configurator stays on this PC ([pc-adapter.md](pc-adapter.md#an-adapter-on-another-machine)). Install the tools on that machine with the same one-line installer (over SSH too: `ssh user@benchbox` and the `curl ... | sh` line above), then run `canworks-diag adapter-serve --adapter socketcan:can0 --bitrate 500` there, or `sudo canworks-diag adapter-serve ... --install-service` for a service that starts with the machine. It prints a token once; on the PC, connect with `--adapter remote:benchbox` or **Adapter on another machine** in the connect panel.

To run the plugin on the PC itself, install the runtime and the plugin there ([install-stock.md](install-stock.md), native or Docker) and set the network's `adapter` (`socketcan`, or `slcan` for serial adapters; see [config.md](config.md)). A Linux PC can so carry the whole bench: editor, PC tools, runtime with the plugin, and `vcan0` with simulated devices ([simulator.md](simulator.md)).

## Switching from pipx or a venv

Remove the old install first so the old commands do not shadow the new ones: `pipx uninstall canworks`, or delete the venv (for example `~/.venvs/canworks`) and any PATH entry or alias pointing into it. Then follow the steps above.

## With pip or pipx

Python 3.10 or newer. From a checkout of this repository, or with the release wheel in place of `./tools/deploy`:

```sh
pipx install ./tools/deploy          # or: python3 -m pip install ./tools/deploy
canworks-deploy --help
```

Without installing: `PYTHONPATH=tools/deploy python3 -m canworks --help` (needs `python3 -m pip install jsonschema`).

Debian 12 and later, Ubuntu 23.04 and later and other distributions that mark their Python as externally managed (PEP 668) refuse a plain `pip install` with "externally-managed-environment". Use uv as above, pipx (`sudo apt install pipx`), or a virtual environment (`python3 -m venv ~/.venvs/canworks && ~/.venvs/canworks/bin/pip install ./tools/deploy`).

## Releases

Releases are automatic. Merging a change that raises the version in `tools/deploy/pyproject.toml` (and `canworks/__init__.py`, which must match) releases it: once CI and the PC tools run (Windows, macOS, Linux) pass on that commit on `main`, the **Release PC tools** workflow creates the tag `deploy-v<version>` there and a GitHub release of that name with the wheel and `canworks.stlib`, then publishes the local simulator runtime image `ghcr.io/tonihoohoo/canworks-sim-runtime:<version>` and the Modbus bridge image `ghcr.io/tonihoohoo/canworks-bridge:<version>` (both also `:latest`) for amd64 and arm64. `canworks-sim-runtime` uses the image of its own version. Commits that keep the version publish nothing, a failed check publishes nothing for that commit, and an existing release is never replaced.

Fallbacks: **Run workflow** on the Release PC tools workflow releases the current `main` if its version has no release yet (same checks), and pushing a tag `deploy-v<version>` by hand releases that commit; a hand-pushed tag that does not match the package version fails without publishing. The tools are tested installed with uv as above on Windows, macOS and Linux (x86_64 and ARM64) on version bumps on `main`, on release tags and on **Run workflow**; pull requests run the same tests on Linux in CI.

Release notes: the top of each release's description is `tools/deploy/release-notes.md` with the version filled in (what the release contains and how to install it). A test fails when the release starts attaching a file, publishing an image or installing a command that this template does not name, so update it in the same pull request. Below it, **What's new** lists every pull request merged since the previous release with the text of its "After:" paragraph (the title alone when the description has none), then a compare link. The finished notes pass the banned-word check before anything is published; on a finding the release fails and names the pull request, so fix that description and use **Run workflow**.

Old releases: only the newest four `deploy-v` releases (by version) are kept. After a release and its images are published, the **prune** job deletes older releases with their tags, and older `deploy-v` tags without a release. Releases and tags with other names, drafts and container images are never deleted. It deletes only while the repository variable `RELEASE_PRUNE` is `on` (Settings → Secrets and variables → Actions → Variables); otherwise it lists in the run summary what it would delete. **Run workflow** with **prune_only** runs only this job.

### Older versions

A version whose release was removed still installs from its commit, without a release file: `uv tool install --force --compile-bytecode "canworks @ https://github.com/tonihoohoo/canworks/archive/<commit>.zip#subdirectory=tools/deploy"`, where `<commit>` is the commit that raised the version (`git log -S 'version = "<version>"' -- tools/deploy/pyproject.toml`). Its container images stay on ghcr.io, so `canworks-sim-runtime` of that version still finds its image.
