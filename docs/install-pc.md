# Installing the PC tools: configurator, deploy tool, diagnostics

`canworks-config`, `canworks-deploy`, `canworks-diag`, `canworks-sim-runtime` and `canworks-j1939-sim` run on the engineering PC (Windows, macOS or Linux). They come as one package. `canworks-sim-runtime` runs a [local simulator runtime](local-runtime.md) in a container and needs a container engine (Docker Engine, Podman or Colima); the other four need nothing else. `canworks-j1939-sim` simulates a J1939 ECU from a DBC file ([j1939.md](j1939.md#simulator)). The recommended way installs them with [uv](https://docs.astral.sh/uv/), which brings its own Python: nothing else needs to be on the PC, and no admin rights are needed. Installing with pip into a Python you already have also works: see [With pip or pipx](#with-pip-or-pipx).

The tools call the editor's `openplc-cli` for **Build only** and **New editor project**; it comes with the OpenPLC Editor (`openplc-cli install-cli`, or set `OPENPLC_CLI` to it).

## One line: install or update

This installs uv if the PC has none, then the newest release of the tools. Run again, it updates them when there is a newer release, and otherwise says the newest version is already installed and changes nothing (`--force`, `-Force` on Windows, installs it again and recreates the shortcut). Windows (PowerShell):

```powershell
$f = "$env:TEMP\install-pc.ps1"; irm https://github.com/tonihoohoo/canworks/releases/latest/download/install-pc.ps1 -OutFile $f; powershell -NoProfile -ExecutionPolicy RemoteSigned -File $f
```

macOS and Linux (Terminal):

```sh
curl -LsSf https://github.com/tonihoohoo/canworks/releases/latest/download/install-pc.sh | sh
```

It installs the exact dependency versions the release was tested with: each release carries `canworks-<version>-constraints.txt` (made from `tools/deploy/uv.lock`), and the installer passes it to `uv tool install --constraints`. An install made today and one made months later get the same libraries, even after a library has a new major release. A release from before 0.108.0 has no such file; the installer then says that its versions are not locked and lets uv pick the newest ones the tools allow, as before. See [Dependency versions](#dependency-versions).

It installs only what the tools need to run: `can-j1939` (the J1939 simulator and trouble-code tools) lists `pytest` as a requirement although it never imports it, so the installer drops it with a uv override (`pytest; sys_platform == 'never'` passed to `uv tool install --overrides`). `iroh` is installed on purpose: it is the remote link of the configurator and `canworks-diag` to runtimes ([remote-access.md](remote-access.md)), and its wheels need nothing else. When uv's bin folder is not on PATH (a new install, or a non-login SSH shell), the installer prints its own hint to open a new terminal once, and uv's PATH warning stays quiet.

It also adds the **canworks configurator** app shortcut, which starts the configurator with no terminal or console window: in the Start menu and on the desktop on Windows, in `~/Applications` on macOS (made on the Mac, so Gatekeeper lets it start), among the applications on Linux. Its uninstall removes the shortcut too.

Both scripts come from the newest release's files on GitHub, so you run released code, never what is on `main`. The Windows line saves the script to a file and runs that file: it pipes nothing into `iex`, and when uv is missing the script downloads uv's own release zip and checks it against uv's published SHA-256 instead of running uv's install script, so it starts no other PowerShell. If an antivirus still stops it, use the manual steps below.

Options: a given release (`--version 0.82.0`), install again (`--force`), uninstall (`--uninstall`), no shortcut (`--no-shortcut`), a local wheel (`--wheel FILE`, with `--constraints FILE` for its locked versions), another Python (`--python 3.15` or `--python PATH`; the default is 3.14). On macOS and Linux they follow `sh -s --` (`curl ... | sh -s -- --version 0.82.0`); on Windows they follow the file name (`... -File $f -Version 0.82.0`; `-Force`, `-Uninstall`, `-NoShortcut`, `-Wheel FILE`, `-Constraints FILE`, `-Python PATH`). Run again, the line does nothing when the newest version is already installed on the chosen Python, and installs it again when the tools are on an older Python (so a PC moves to 3.14 on its next update). A uv older than 0.9.0 does not know Python 3.14: the scripts update it with `uv self update`, or, when another tool installed uv (Homebrew, winget), stop and say to update it there. The scripts only install released wheels and find the newest release without the GitHub API. To pin the script to a release, put `download/deploy-v<version>` in place of `latest/download` (`https://github.com/tonihoohoo/canworks/releases/download/deploy-v0.92.0/install-pc.sh`; releases from 0.92.0 on carry the scripts, and a newer script installs older versions with `--version`). To read the script before running it, download it first (`curl -LsSfO https://github.com/tonihoohoo/canworks/releases/latest/download/install-pc.sh`, then `sh install-pc.sh`; on Windows open `$f` before the `powershell` part). Then check as in step 2 below. The manual steps follow.

## 1. Install uv (once per PC)

Windows (PowerShell):

```powershell
winget install --id astral-sh.uv -e
```

Without winget (some LTSC and IoT builds): download `uv-x86_64-pc-windows-msvc.zip` (`uv-aarch64-pc-windows-msvc.zip` on ARM) from uv's GitHub releases and put `uv.exe` in `%USERPROFILE%\.local\bin`, or use uv's own installer from [docs.astral.sh/uv](https://docs.astral.sh/uv/getting-started/installation/).

macOS and Linux (Terminal):

```sh
curl -LsSf https://astral.sh/uv/install.sh | sh
```

`brew install uv` and a Linux distribution's own `uv` package (where it has one) work too. Open a new terminal afterwards so `uv` is on PATH.

## 2. Install the tools

Download `canworks-<version>-py3-none-any.whl` and `canworks-<version>-constraints.txt` from the repository's **Releases** page (the newest `deploy-v<version>` release; or use `gh release download deploy-v<version>`). The same files are for every operating system. Then, in the folder you downloaded them to:

```sh
uv tool install --compile-bytecode --python 3.14 --constraints canworks-<version>-constraints.txt canworks-<version>-py3-none-any.whl
```

Without `--constraints` uv picks the newest dependency versions the tools allow instead of the tested ones.

`--compile-bytecode` compiles the tools at install, so the first start is as fast as later ones.

Without a release file, uv installs the newest code straight from GitHub; this needs no git: `uv tool install --force --compile-bytecode "canworks @ https://github.com/tonihoohoo/canworks/archive/refs/heads/main.zip#subdirectory=tools/deploy"`. If uv cannot install its own Python on the PC (seen on a Windows IoT LTSC build), point `--python` at a Python 3.11 or newer that is already installed instead.

uv downloads Python 3.14 if the PC has none, puts the tools in their own environment, and links the five commands into its bin folder (`%USERPROFILE%\.local\bin` on Windows, `~/.local/bin` on macOS and Linux). If it warns that the folder is not on PATH, run `uv tool update-shell` and open a new terminal. Check:

```sh
canworks-deploy --version
canworks-config            # opens the configurator in the browser
```

The configurator runs in the background, opens in the default browser and stops when its last tab is closed; **Quit** in its header stops it too. After a manual install, `canworks-config --create-shortcut` adds the app shortcut that starts it without a terminal (`--remove-shortcut` removes it). Over SSH and on Linux without a desktop it stays in the terminal and prints its address with a one-time code: open it yourself; `--no-browser` skips the attempt, `--foreground` keeps it in the terminal anywhere. More in [configurator.md](configurator.md#start).

Linux works with x86_64 and ARM64 (glibc distributions; uv's Python and the compiled dependencies come as wheels for both).

The first install needs internet access to github.com (Python) and pypi.org (the Python packages the tools use: `jsonschema`, `python-can`, `pyserial`, `cantools`, `can-j1939`). Behind a company proxy that inspects TLS, set `UV_SYSTEM_CERTS=1` (uv 0.11 and newer; older uv reads `UV_NATIVE_TLS=1`) so uv trusts the certificates installed in the operating system. The setting also applies to updates from the configurator.

### Windows asks to allow Python

Windows Defender Firewall may show "Windows Defender Firewall has blocked some features of Python" the first time the configurator or `canworks-diag` pairs with a runtime for the [remote link](remote-access.md), and again after the tools move to a new Python version (the question is per program, and uv keeps each Python version in a folder of its own). Pressing **Cancel** is fine: online access, deploy, the Devices workspace and the remote link keep working, because the PC always starts the connection. Finding runtimes on the local network never asks: it listens on no port ([remote-access.md](remote-access.md#same-network)).

## Update and uninstall

### From the configurator

Once a day the configurator asks GitHub which release is the newest (one request to `github.com/tonihoohoo/canworks/releases/latest`, which only redirects to the newest release; nothing else is sent). When a newer one exists, a chip **Update: 0.x.0** shows in the header. It opens a dialog with a link to what's new and four choices:

- **Update now** stops the configurator, installs the new version with uv (the same `uv tool install` as the one-line installer, with the new release's locked dependency versions) and starts it again. The open tab comes back by itself in about a minute, and a message says how it went. It is refused while there are unsaved changes, an online connection, a trace, a simulator or a job on the bus: finish or save first, or pick the next choice.
- **Update when I quit** installs it after Quit or after the last tab closes. The configurator does not start again; the next start shows the result.
- **Skip this version** hides the chip until a newer release comes out. **Not now** leaves it.

**Settings → Updates** has the **Check for updates** switch (on by default), **Check now** and the time of the last check. `CANWORKS_NO_UPDATE_CHECK=1` in the environment turns the check off as well.

From a terminal, `canworks-config --update` prints the installed and the newest version and updates after a yes (`--yes` does not ask). With a configurator running, that configurator updates and comes back. Without one, the update runs in the terminal on macOS and Linux; on Windows it runs in the background, because a running program's files cannot be replaced there, and `update.log` shows its progress.

What happens on each system:

- The update needs the tools as the one-line installer put them (a uv tool). A copy installed another way (pip, a checkout) shows the newer version and the install command to copy instead of an Update button.
- On Windows, another canworks program still running from the same install (`canworks-diag` in a terminal, a simulator) keeps its files in use. The update then changes nothing, the configurator starts again and says to close the other program first.
- On Windows, tools installed from inside another app (its PowerShell runs in that app's private folder, `%LOCALAPPDATA%\Packages\...`) cannot update the real install: run the install command from your own PowerShell window instead.
- If uv fails after it started replacing the tools, the old version is installed again from its release. If even that fails, a message window shows the install command.
- The update keeps uv and the Python the tools run on; the one-line installer still updates those. The macOS app and Linux menu entry are refreshed; the Windows shortcuts point at paths an update keeps.
- `update.log` in the settings folder (next to `configurator.log`) has every step and uv's output.

### With the installer or by hand

The one-line installer above updates when run again (and uninstalls with `--uninstall`). By hand:

```sh
uv tool install --force --compile-bytecode --python 3.14 --constraints canworks-<new version>-constraints.txt canworks-<new version>-py3-none-any.whl
canworks-config --remove-shortcut    # before uninstalling, when the shortcut was added
uv tool uninstall canworks
```

The shortcut runs the installed tools, so it keeps working after an update.

The configurator's own settings (theme, online access, the update check, its logs `configurator.log` and `update.log`) and the local simulator runtime's credentials (`local-runtime.json`) live in the user's settings folder (`%APPDATA%\canworks` on Windows, `~/Library/Application Support/canworks` on macOS, `$XDG_CONFIG_HOME/canworks` or `~/.config/canworks` on Linux) and survive both. Uninstalling leaves a local simulator runtime container in place: run `canworks-sim-runtime remove --data` first to delete it. After an update, `canworks-sim-runtime update` moves the local runtime to the image of the new version.

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

Python 3.11 or newer. From a checkout of this repository, or with the release wheel in place of `./tools/deploy`:

```sh
pipx install ./tools/deploy          # or: python3 -m pip install ./tools/deploy
canworks-deploy --help
```

A pip, pipx or manual `uv tool install` also gets `pytest`, which `can-j1939` lists as a requirement (the tools never use it); add `--overrides` with a file holding `pytest; sys_platform == 'never'` to `uv tool install` to leave it out, as the one-line installer does.

pip picks the newest dependency versions the tools allow. For the tested ones add `-c canworks-<version>-constraints.txt` (from the release) or, in a checkout, `-c` with the output of `uv export --project tools/deploy --frozen --no-hashes --no-emit-project --no-dev --format requirements-txt`.

Without installing: `PYTHONPATH=tools/deploy python3 -m canworks --help` (needs `python3 -m pip install jsonschema`).

Debian 12 and later, Ubuntu 23.04 and later and other distributions that mark their Python as externally managed (PEP 668) refuse a plain `pip install` with "externally-managed-environment". Use uv as above, pipx (`sudo apt install pipx`), or a virtual environment (`python3 -m venv ~/.venvs/canworks && ~/.venvs/canworks/bin/pip install ./tools/deploy`).

## Dependency versions

`tools/deploy/pyproject.toml` gives each dependency only a lowest version, so the package stays easy to install next to other software. The versions that are tested and shipped are locked in `tools/deploy/uv.lock`, for every supported system and Python 3.11 and newer. CI installs those versions, each release exports them to `canworks-<version>-constraints.txt`, and every install uses that file: the one-line installers, the configurator's update, `install-runtime.sh` and `install-bridge.sh` on a device, and the container images. A CI check (`scripts/check-lock.py`) fails when `uv.lock` no longer matches `pyproject.toml`; run `uv lock --project tools/deploy` after changing a dependency. A version bump alone needs no new lock.

New versions arrive on purpose. Dependabot opens one pull request a month that updates `uv.lock`, plus a security update when an advisory names a locked version. CI tests it like any other change, and it reaches users with the next release. The dcf-tools on a device (dcfgen) have exact versions too, in `scripts/dcf-tools-constraints.txt`, which goes with the pinned Lely commit.

## Releases

Releases are automatic. Merging a change that raises the version in `tools/deploy/pyproject.toml` (and `canworks/__init__.py`, which must match) releases it: once CI and the PC tools run (Windows, macOS, Linux) pass on that commit on `main`, the **Release PC tools** workflow creates the tag `deploy-v<version>` there and a GitHub release of that name with the wheel, its locked dependency versions (`canworks-<version>-constraints.txt`) and `canworks.stlib`, then publishes the local simulator runtime image `ghcr.io/tonihoohoo/canworks-sim-runtime:<version>` and the Modbus bridge image `ghcr.io/tonihoohoo/canworks-bridge:<version>` (both also `:latest`) for amd64 and arm64. `canworks-sim-runtime` uses the image of its own version. Commits that keep the version publish nothing, a failed check publishes nothing for that commit, and an existing release is never replaced.

Fallbacks: **Run workflow** on the Release PC tools workflow releases the current `main` if its version has no release yet (same checks), and pushing a tag `deploy-v<version>` by hand releases that commit; a hand-pushed tag that does not match the package version fails without publishing. The tools are tested installed with uv as above on Windows, macOS and Linux (x86_64 and ARM64) on version bumps on `main`, on release tags and on **Run workflow**; pull requests run the same tests on Linux in CI.

Release notes: the top of each release's description is `tools/deploy/release-notes.md` with the version filled in (what the release contains and how to install it). A test fails when the release starts attaching a file, publishing an image or installing a command that this template does not name, so update it in the same pull request. Below it, **What's new** lists every pull request merged since the previous release with the text of its "After:" paragraph (the title alone when the description has none), then a compare link. The finished notes pass the banned-word check before anything is published; on a finding the release fails and names the pull request, so fix that description and use **Run workflow**.

Old releases: only the newest four `deploy-v` releases (by version) are kept. After a release and its images are published, the **prune** job deletes older releases with their tags, and older `deploy-v` tags without a release. Releases and tags with other names, drafts and container images are never deleted. It deletes only while the repository variable `RELEASE_PRUNE` is `on` (Settings → Secrets and variables → Actions → Variables); otherwise it lists in the run summary what it would delete. **Run workflow** with **prune_only** runs only this job.

### Older versions

A version whose release was removed still installs from its commit, without a release file: `uv tool install --force --compile-bytecode "canworks @ https://github.com/tonihoohoo/canworks/archive/<commit>.zip#subdirectory=tools/deploy"`, where `<commit>` is the commit that raised the version (`git log -S 'version = "<version>"' -- tools/deploy/pyproject.toml`). Its container images stay on ghcr.io, so `canworks-sim-runtime` of that version still finds its image.
