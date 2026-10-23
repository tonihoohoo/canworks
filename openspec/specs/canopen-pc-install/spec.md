# canopen-pc-install Specification

## Purpose
How the PC-side CANopen tools (configurator, deploy tool, diagnostics) reach a developer's Windows PC or Mac: a released wheel installed with uv, without a preinstalled Python, and tested on those systems.

## Requirements

### Requirement: Release wheel

Each release of the PC-side tools SHALL publish exactly one platform-independent wheel (`py3-none-any`) of the tools package as an asset of a GitHub release named and tagged `deploy-v<version>`, where `<version>` is the package version.

The release SHALL be created automatically, without a person pushing a tag, for a commit on `main` when all of these hold: the package version in `pyproject.toml` equals `__version__`; no release or tag `deploy-v<version>` exists yet; the `CI` workflow succeeded on that commit; and the PC tools workflow succeeded on that commit or did not run for it. The tag SHALL point at that commit. While a required run on the commit is still pending, nothing SHALL be published yet, and a later completion SHALL publish it. When a required run failed, nothing SHALL be published for that commit.

An existing release SHALL never be replaced, re-tagged or given a new asset by the automation; running it again for a released version SHALL do nothing and succeed. Removing old releases under the retention rule (Requirement: Release retention) is the only change the automation SHALL make to an existing release.

Pushing a tag `deploy-v<version>` by hand SHALL still publish a release, and SHALL fail without publishing anything when `<version>` differs from the package version.

Each release's notes SHALL be made as described in Requirement: Release notes.

#### Scenario: Version bump merged
- **WHEN** a pull request that changes the package version from 0.20.0 to 0.21.0 is merged to `main`, and `CI` and the PC tools workflow both succeed on the merge commit
- **THEN** a GitHub release `deploy-v0.21.0` exists, its tag points at the merge commit, and it has the asset `canworks-0.21.0-py3-none-any.whl`

#### Scenario: No version change
- **WHEN** a commit on `main` keeps the package version 0.21.0 and `deploy-v0.21.0` is already released
- **THEN** no release is created or changed

#### Scenario: Tests failed
- **WHEN** a version bump is merged and the PC tools workflow fails on that commit
- **THEN** no release `deploy-v<version>` is created for that commit

#### Scenario: Second workflow still running
- **WHEN** `CI` finishes green on a version-bump commit while the PC tools workflow on the same commit is still running
- **THEN** nothing is published until the PC tools workflow finishes, and the release is created then if it succeeded

#### Scenario: Older versions are not backfilled
- **WHEN** `main` carries version 0.21.0 and versions 0.18.0 and 0.19.0 were never released
- **THEN** only `deploy-v0.21.0` is released

#### Scenario: Tag matches the package version
- **WHEN** the tag `deploy-v0.16.0` is pushed by hand and the package version at that commit is 0.16.0
- **THEN** a GitHub release `deploy-v0.16.0` exists with the asset `canworks-0.16.0-py3-none-any.whl`

#### Scenario: Tag does not match
- **WHEN** the tag `deploy-v0.16.1` is pushed and the package version is 0.16.0
- **THEN** the release job fails, names both versions, and no release asset is published

### Requirement: Install on a PC without Python

The documentation SHALL give, for Windows, for macOS and for Linux, the commands that install the tools on a PC with no Python and no admin rights: install uv with its official installer, then install the release wheel with uv using a uv-managed Python. Every documented `uv tool install` command SHALL compile the package's bytecode at install time (`--compile-bytecode`), so the first start after an install is as fast as later ones. After these commands the user's shell SHALL find `canworks-config`, `canworks-deploy` and `canworks-diag`, and they SHALL behave as when installed with pip. The documentation SHALL name, per operating system, the folder uv links the commands into and the configurator's settings folder. It SHALL say that the tools reach the CAN bus through a runtime, or directly through a USB CAN adapter on the PC (canopen-local-bus), and SHALL give per operating system what an slcan adapter needs: no driver on Windows 10 and 11, macOS and Linux, and the port name pattern on each, plus on Linux the `dialout` group for serial ports.

#### Scenario: Fresh Windows PC
- **WHEN** a Windows user with no Python installed runs the documented uv install command and then the documented `uv tool install` command on the downloaded wheel, and opens a new terminal
- **THEN** `canworks-deploy --version` prints the wheel's version and `canworks-config` opens the configurator in the browser

#### Scenario: Fresh Mac
- **WHEN** a macOS user with no Python installed runs the documented commands
- **THEN** the three commands are on PATH and `canworks-deploy --version` prints the wheel's version

#### Scenario: Fresh Linux desktop
- **WHEN** a Linux user (x86_64 or ARM64, glibc) runs the documented uv install command and the documented `uv tool install` command, and opens a new terminal
- **THEN** the three commands are in `~/.local/bin` and on PATH, `canworks-deploy --version` prints the wheel's version, and `canworks-config` opens the configurator in the default browser

#### Scenario: First start after install
- **WHEN** a user installs the wheel with the documented command and runs `canworks-config --version` for the first time
- **THEN** no module of the package is compiled at that start, because its bytecode was written at install

#### Scenario: Linux without a browser
- **WHEN** `canworks-config` starts on a Linux machine with no browser to open (for example over SSH)
- **THEN** it still serves the page and prints its URL with the access token, and `--no-browser` skips the attempt

#### Scenario: Editor CLI on Linux
- **WHEN** the OpenPLC Editor AppImage has run `openplc-cli install-cli` and the user runs the deploy tool's Build only or New editor project
- **THEN** the tools find `openplc-cli` on PATH and run it

#### Scenario: Corporate proxy
- **WHEN** the PC reaches the internet through a TLS-inspecting proxy
- **THEN** the documentation names the uv option that makes uv trust the operating system's certificate store

#### Scenario: USB adapter after install
- **WHEN** a user installed the tools with uv on Windows, macOS or Linux and plugs in a CANable with stock firmware
- **THEN** `canworks-diag adapters` lists it without any further install step (on Linux, after joining `dialout` when the docs say so)

### Requirement: Update and uninstall

The documentation SHALL give one command to replace an installed version with a newer wheel and one command to remove the tools, both working without Python on the PC. The update command SHALL compile bytecode at install time like the install command. The documentation SHALL also describe updating from the configurator (the update check, the Update button, `canworks-config --update`) and how to turn the check off. For a company proxy that inspects TLS, it SHALL name `UV_SYSTEM_CERTS=1`, the variable current uv reads, and the older `UV_NATIVE_TLS=1` for uv versions before it.

#### Scenario: Update
- **WHEN** the user runs the documented update command on a newer wheel
- **THEN** `canworks-deploy --version` prints the newer version and the configurator's saved settings are kept

#### Scenario: Update from the configurator
- **WHEN** the user presses Update in the configurator of a uv tool install
- **THEN** `canworks-deploy --version` prints the newer version and the configurator's saved settings are kept

#### Scenario: Uninstall
- **WHEN** the user runs the documented uninstall command
- **THEN** the three commands are no longer on PATH

### Requirement: Tested on Windows, macOS and Linux

CI SHALL install the wheel with uv on a Windows runner, a macOS runner, a Linux x86_64 runner and a Linux ARM64 runner, run the tools' test suite there in as many worker processes as the runner has CPUs (classes named in the workflow's serial list run alone afterwards), and run each of the three commands at least once (deploy tool: schema/EDS check, DCF export and DBC export of a shipped example config; configurator: start and answer its page with its access token; diagnostics: `--help`). The job SHALL run on pushes to `main` that change `tools/deploy/pyproject.toml` (where a version bump is released), on release tags, and when started by hand on any branch; it SHALL NOT run on pull requests, whose Linux run covers the same code. An automatic release SHALL wait for this job's run on the released commit. The README SHALL give the commands to run the same checks on a Windows PC, a Mac or a Linux PC. A test SHALL NOT be skipped on these runners unless it needs something the job does not install (a browser for page tests, the C++ parity binary, CAN hardware), and each such skip SHALL say why.

#### Scenario: Version bump merged
- **WHEN** a pull request that raises the version in `tools/deploy/pyproject.toml` is merged to `main`
- **THEN** the Windows, macOS and both Linux jobs run on the merge commit and the release waits for them

#### Scenario: Suite in parallel
- **WHEN** the Windows job runs the tools' test suite on a 4-CPU runner
- **THEN** the tests run in 4 worker processes and every test runs once

#### Scenario: Linux job fails
- **WHEN** a version bump is merged and the installed-wheel job fails on the Linux ARM64 runner only
- **THEN** no release is created for that commit

#### Scenario: Change to the tools
- **WHEN** a pull request changes files under `tools/deploy/`
- **THEN** the installed-wheel jobs do not run unless started by hand on its branch; the Linux tests in CI still run

#### Scenario: Unrelated change
- **WHEN** a commit on `main` changes only bridge C++ code or docs
- **THEN** the installed-wheel jobs do not run

### Requirement: pip route kept

Installing the tools with pip or pipx into an existing Python 3.8+ SHALL keep working and stay documented as an alternative to uv. The documentation SHALL say that Linux distributions that mark their Python as externally managed (PEP 668) refuse a plain `pip install`, and SHALL point those users at uv, pipx or a virtual environment.

#### Scenario: pipx install from a checkout
- **WHEN** a user runs `pipx install ./tools/deploy` from a checkout
- **THEN** the same three commands are installed as with uv

#### Scenario: Externally managed Python
- **WHEN** a Debian or Ubuntu user follows the pip section and their distribution refuses `python3 -m pip install` with "externally-managed-environment"
- **THEN** the same section tells them to use uv, pipx or a virtual environment instead

### Requirement: Adapter libraries in the package
The tools package SHALL depend on python-can and pyserial, and every dependency SHALL install with uv from wheels or pure Python sources on Windows, macOS (Intel and Apple silicon) and Linux (x86_64 and ARM64) without a compiler. The PC tools CI job SHALL run the local backend's virtual-bus tests on each of its runners.

On Windows the package SHALL also bring everything a gs_usb adapter needs: python-can's gs_usb driver with pyusb, and a libusb DLL (the `libusb` package), which the tools SHALL find without the user putting it on the PATH. `canworks-diag adapters` SHALL then list a plugged-in gs_usb adapter, and `gs_usb:0` SHALL open, with nothing else installed.

#### Scenario: Fresh install on each runner
- **WHEN** the PC tools job installs the wheel with uv on its four runners
- **THEN** the install needs no compiler and the local backend's virtual-bus tests pass on each

#### Scenario: gs_usb adapter on Windows
- **WHEN** the wheel is installed with uv on a Windows PC with a gs_usb (candleLight) adapter plugged in and nothing else installed
- **THEN** `canworks-diag adapters` lists `gs_usb:0` and `canworks-diag --adapter gs_usb:0 --bitrate 500 scan` runs

### Requirement: Release notes

Each release's notes SHALL be generated from a template file in the repository, `tools/deploy/release-notes.md`, filled in with the version and repository owner. The template SHALL say what the release contains and how to install or use each part: the wheel (with the uv install command), `canworks.stlib`, and every container image the release publishes.

A test in CI SHALL fail when the template does not name every asset the release workflow attaches, every container image it publishes, and every command the tools package installs, so a change to what a release ships cannot merge without updating the description.

After the template text, the notes SHALL have a "What's new" section with one entry per pull request merged between the previous `deploy-v` release and the released commit, in merge order: the pull request title as a link, followed by the text of its "After:" paragraph when the pull request description has one, else the title alone. A commit in that range without a pull request SHALL be listed by its subject. The notes SHALL end with a link comparing the previous release tag with the new one. Without a previous release the "What's new" section and link SHALL be left out.

Before anything is published, the complete notes SHALL pass the banned-word check; when they do not, the release job SHALL fail without creating the tag or the release and SHALL name the pull request whose text matched, never the matched text.

#### Scenario: Notes describe the release
- **WHEN** `deploy-v0.64.0` is released after `deploy-v0.63.0`, and PR #101 merged in between has a description with an "After:" paragraph
- **THEN** the release notes contain the template text with 0.64.0 in the install command and image tags, and a "What's new" entry linking PR #101 followed by its "After:" text, and a compare link from `deploy-v0.63.0` to `deploy-v0.64.0`

#### Scenario: Unreleased versions in between
- **WHEN** version 0.60.0 was never released and `deploy-v0.61.0` follows `deploy-v0.59.0`
- **THEN** "What's new" for 0.61.0 lists the pull requests merged for 0.60.0 as well

#### Scenario: Pull request without an After paragraph
- **WHEN** a pull request in the range has a description without an "After:" paragraph
- **THEN** its entry is the linked title alone and the release is still published

#### Scenario: New image without template update
- **WHEN** a pull request adds a container image to the release workflow and does not mention it in `tools/deploy/release-notes.md`
- **THEN** CI fails on that pull request and names the missing image

#### Scenario: Banned word in a pull request description
- **WHEN** a pull request description in the range was edited after merge to contain a banned word, and a version bump is then released
- **THEN** the release job fails naming that pull request number, and no tag or release `deploy-v<version>` is created

### Requirement: Release retention

After a release and its container images are published, the automation SHALL keep the newest 4 `deploy-v` releases, ordered by version, and SHALL delete every older `deploy-v` release together with its tag. It SHALL also delete `deploy-v` tags that have no release and are older than the oldest kept release. It SHALL NOT delete the release it just published, the release GitHub marks as latest, draft releases, tags or releases whose name does not start with `deploy-v`, or container images.

Deletion SHALL only happen while the repository variable `RELEASE_PRUNE` is `on`; otherwise the job SHALL only list, in the run summary, the releases and tags it would delete. Starting the workflow by hand with `prune_only` SHALL run only this step, with the same switch.

When publishing the release or its images fails, nothing SHALL be deleted.

#### Scenario: Fifth release
- **WHEN** `RELEASE_PRUNE` is `on`, releases 0.61.0, 0.61.1, 0.62.0 and 0.63.0 exist, and 0.64.0 is released with its images
- **THEN** releases 0.61.1, 0.62.0, 0.63.0 and 0.64.0 remain, and release and tag `deploy-v0.61.0` are gone

#### Scenario: Switch off
- **WHEN** `RELEASE_PRUNE` is not set and a release is made while 32 older releases exist
- **THEN** no release or tag is deleted, and the run summary lists the 29 releases and the orphan tags that would be

#### Scenario: Image publish failed
- **WHEN** `RELEASE_PRUNE` is `on` and the image job fails for a new release
- **THEN** no older release or tag is deleted

#### Scenario: Order by version, not date
- **WHEN** `deploy-v0.62.1` is pushed by hand after `deploy-v0.64.0` exists
- **THEN** the kept set is the four highest versions, and `deploy-v0.62.1` is deleted only if it is not among them

#### Scenario: Other tags untouched
- **WHEN** the repository has a tag `v1.0` and a release made from it
- **THEN** pruning never deletes them

### Requirement: Dependency floors without known vulnerabilities
The PC tools SHALL require Python 3.11 or newer and dependency versions without known advisories in the code paths they use, including, on Windows, `libusb>=1.0.30`. The PC tools SHALL NOT depend on `zeroconf`. The Python floor SHALL NOT be higher than the Python of the pinned runtime image, because the same package runs there.

#### Scenario: Fresh install
- **WHEN** the PC tools are installed into a new environment
- **THEN** `zeroconf` is not installed, and `ifaddr` is

#### Scenario: Run from a checkout on Windows
- **WHEN** a Windows user runs `uv run` on the deploy tool from a source checkout
- **THEN** uv resolves the dependencies, including `libusb`, without a Python version error

#### Scenario: Python 3.10
- **WHEN** a user installs the tools with pip on Python 3.10
- **THEN** pip refuses, saying the package needs Python 3.11 or newer

### Requirement: Fast start

The configurator and the deploy tool SHALL start without importing the libraries that only some of their work needs: `jsonschema` until a config, simulation file, machine file or notes file is validated, and `python-can`, `cantools`, `can-j1939`, `ifaddr` and `iroh` until an adapter, DBC, J1939, discovery or remote-link feature is used. A unit test in CI SHALL import the entry modules of `canworks-config`, `canworks-deploy` and `canworks-diag` in a fresh interpreter and fail when any of these libraries was imported.

#### Scenario: Configurator start
- **WHEN** a fresh Python process imports `canworks.configurator.server`
- **THEN** none of `jsonschema`, `can`, `cantools`, `j1939`, `ifaddr` or `iroh` is in `sys.modules`

#### Scenario: Validation still works
- **WHEN** the configurator then opens a project and checks its `canworks.json`
- **THEN** the config is validated against its schema exactly as before, with the same messages

### Requirement: One-line installer

The repository SHALL provide `scripts/install-pc.sh` (macOS and Linux, POSIX `sh`) and `scripts/install-pc.ps1` (Windows, PowerShell 5.1), and the documentation SHALL give, first among the install routes, the one line per operating system that runs them from the newest release's assets on GitHub (Requirement: Install scripts from the release): on macOS and Linux piped into `sh`, on Windows downloaded to a file and run from it (Requirement: Windows installers without download-and-run). Each script SHALL install uv when uv is not found (`install-pc.sh` with uv's official installer, `install-pc.ps1` from uv's release zip checked against its published SHA-256), use it in the same session, and install the wheel of the newest `deploy-v` release (or of `--version <version>`) from its release download URL with `uv tool install --force --compile-bytecode --python 3.14` (or the Python given with `--python` / `-Python`), so running the same line again updates to the newest release. When the uv found is older than the first uv release that knows the default Python (0.9.0 for 3.14), the script SHALL run `uv self update`, and when that fails SHALL exit non-zero saying to update uv with the tool that installed it. The script SHALL find the newest release from the `releases/latest` redirect without the GitHub API, SHALL install only released wheels (never the code on `main`), and with `--wheel <file>` SHALL install that local wheel instead. `--uninstall` SHALL remove the tools and leave uv and the settings folder. When uv's bin folder is not on PATH, the script SHALL add it (`uv tool update-shell`) and say to open a new terminal. The script SHALL print the installed version at the end and exit non-zero, saying why, when any step fails. The documentation SHALL also show the same scripts pinned to a release and how to download and read a script before running it.

CI SHALL run `shellcheck` on `install-pc.sh` and test both scripts' release lookup and argument handling without network access, and the PC tools job SHALL install through the scripts (with `--wheel`) on each of its runners.

#### Scenario: Fresh PC
- **WHEN** a Windows user with neither uv nor Python pastes the documented PowerShell line
- **THEN** uv is installed from its release zip into `%USERPROFILE%\.local\bin` without starting another PowerShell, the newest release's wheel is installed on Python 3.14, `canworks-deploy --version` in a new terminal prints that release's version, and `canworks-config` opens the configurator

#### Scenario: Update with the same line
- **WHEN** a Mac user who has 0.82.0 installed pastes the documented line after 0.83.0 was released
- **THEN** 0.83.0 is installed over it, uv is not reinstalled, and the configurator's saved settings are kept

#### Scenario: Old uv
- **WHEN** the PC has uv 0.8.0 from uv's own installer
- **THEN** the script updates uv before installing, and the tools are installed on Python 3.14

#### Scenario: Given version
- **WHEN** the user runs the script with `--version 0.82.0`
- **THEN** the wheel of `deploy-v0.82.0` is installed, also when a newer release exists

#### Scenario: Uninstall
- **WHEN** the user runs the script with `--uninstall`
- **THEN** the tools' commands are no longer on PATH and uv is still installed

#### Scenario: No release reachable
- **WHEN** the script cannot reach github.com
- **THEN** it exits non-zero, names the URL it could not reach and the proxy setting the docs describe, and changes nothing that was installed

### Requirement: Only runtime dependencies in the one-line install
The one-line installers SHALL NOT install test tools into the tools' environment. When a runtime dependency lists a test tool as a requirement that its code does not import (`can-j1939` lists `pytest`), the installers SHALL drop it with a uv override, and the tools that use that dependency SHALL be tested without the dropped requirement. `iroh` SHALL stay a runtime dependency on the platforms it publishes wheels for, because the remote link of the configurator and `canworks-diag` needs it. `docs/install-pc.md` SHALL say which dependencies a `pip` install gets in addition and why.

#### Scenario: No pytest after the one-line install
- **WHEN** the user installs the tools with the one-line installer
- **THEN** the tools' environment has no `pytest`, `canworks-j1939-sim` starts, and the remote link works where `iroh` has a wheel

### Requirement: Installer output over a non-login shell
When uv's bin folder is not on PATH, the one-line installers SHALL print only their own hint (open a new terminal, or the folder to add to PATH), not uv's PATH warning as well.

#### Scenario: Install over SSH
- **WHEN** the user runs the one-line Linux installer through a non-login SSH command, with uv's bin folder not on PATH
- **THEN** the output has the installer's hint to open a new terminal once, and no "is not on your PATH" warning from uv

### Requirement: Windows installers without download-and-run
The Windows install scripts (`install-pc.ps1`, `install-bridge.ps1`) and every documented Windows line that runs them SHALL NOT use `Invoke-Expression`/`iex`, `[scriptblock]::Create`, `-EncodedCommand` or `-ExecutionPolicy Bypass`, and no script SHALL start another `powershell` or `pwsh` process. CI SHALL fail, naming the file and line, when a `.ps1` script under `scripts/` or a documented Windows line uses one of these.

#### Scenario: Fresh Windows PC with Defender on
- **WHEN** a Windows user with Defender real-time protection on and no uv pastes the README's Windows line
- **THEN** the script runs from a file, the tools are installed, and the script starts no PowerShell process

#### Scenario: Pattern added back
- **WHEN** a pull request adds `| iex` to a Windows line in `docs/` or `Invoke-Expression` to `install-bridge.ps1`
- **THEN** CI fails naming that file and line

### Requirement: Install scripts from the release
Each `deploy-v` release SHALL attach the install scripts `install-pc` and `install-bridge`, each as `.sh` and `.ps1`, and the device probe `device-probe.sh`, from the released commit as assets. Every documented install line, on every system, SHALL fetch the script from `releases/latest/download/`. Windows lines SHALL save it to a file and run it with `powershell -NoProfile -ExecutionPolicy RemoteSigned -File`, on one line.

#### Scenario: Release assets
- **WHEN** release `deploy-v0.92.0` is created
- **THEN** it has the assets `install-pc.sh`, `install-pc.ps1`, `install-bridge.sh`, `install-bridge.ps1` and `device-probe.sh` from the released commit, and no `install-runtime` script

#### Scenario: macOS line
- **WHEN** a Mac user pastes the README's macOS and Linux line
- **THEN** `curl` fetches `install-pc.sh` from the newest release's assets, not from `main`, and pipes it into `sh`

#### Scenario: Options on Windows
- **WHEN** a user wants a given release or to uninstall
- **THEN** the documentation shows the same download line with `-Version 0.82.0` or `-Uninstall` after the file name, and no script block form
- **AND** a pinned line uses `releases/download/deploy-v0.82.0/`

### Requirement: uv from a checked zip on Windows
When `install-pc.ps1` installs uv, it SHALL download uv's Windows zip for the PC's architecture (x86_64 or ARM64) and its `.sha256` file from uv's GitHub release, compare the zip's SHA-256 with it before extracting anything, and put `uv.exe`, `uvx.exe` and `uvw.exe` into `%USERPROFILE%\.local\bin`. On a mismatch or a failed download it SHALL exit non-zero, name the URL, and add nothing to that folder.

#### Scenario: Tampered uv download
- **WHEN** the uv zip downloaded by `install-pc.ps1` does not match its `.sha256`
- **THEN** the script exits non-zero saying the uv download did not match its checksum, and no `uv.exe` was added to `%USERPROFILE%\.local\bin`

#### Scenario: Tested in CI
- **WHEN** a version bump is merged
- **THEN** the PC tools Windows job runs `install-pc.ps1` once with no uv on PATH, so the zip route runs for real

#### Scenario: ARM64 PC
- **WHEN** `install-pc.ps1` installs uv on Windows on ARM
- **THEN** it downloads `uv-aarch64-pc-windows-msvc.zip`

### Requirement: README install blocks per system
In the README, each install step SHALL give one fenced code block per system (Windows; macOS and Linux; the PLC or Linux device), labelled with the system, so that copying a whole block copies only lines for that system.

#### Scenario: Copying the README block
- **WHEN** a Windows user copies the whole Windows code block of the PC tools step in the README
- **THEN** the block holds only PowerShell lines, with no macOS or Linux command

### Requirement: Skip an up-to-date install

Before installing, the one-line PC installers SHALL read the installed version of the tools and the Python of their environment from uv (`uv tool list --show-python`). When the version equals the version they would install, the environment's Python has the same major and minor version as the Python they would install with (checked only when that Python is given as a version, not as a path), and neither `--force` (`-Force`) nor `--wheel` (`-Wheel`) is given, they SHALL say that this version is already installed and how to install it again, change nothing, and exit 0. Otherwise, including when the installed version or Python cannot be read, they SHALL install as before. `--force` SHALL install even the same version again and recreate the shortcut.

#### Scenario: Line run again
- **WHEN** a user with 0.92.0 installed on Python 3.14 runs the one-line installer while 0.92.0 is the newest release
- **THEN** it prints that canworks 0.92.0 is already installed and that `--force` installs it again, exits 0 within seconds, and the tools' environment is unchanged

#### Scenario: Newer release
- **WHEN** a user with 0.92.0 installed runs the line after 0.93.0 was released
- **THEN** 0.93.0 is installed as before

#### Scenario: Same version on an older Python
- **WHEN** a user who has 0.95.0 installed on Python 3.12 runs the installer and 0.95.0 is the newest release
- **THEN** it installs 0.95.0 again on Python 3.14 and recreates the shortcut

#### Scenario: Force
- **WHEN** a user runs the installer with `-Force` and the newest version is already installed
- **THEN** it installs that version again and recreates the shortcut

### Requirement: SSH library in the package
The PC tools SHALL depend on `paramiko` (and so on its `cryptography`, `bcrypt` and `pynacl` wheels) on every platform they ship for, at a floor without known vulnerabilities, because the configurator's Devices workspace connects to devices over SSH. The one-line installers SHALL install it with no compiler on the PC, and the fast-start and skip-reinstall requirements SHALL still hold.

#### Scenario: Fresh Windows install
- **WHEN** a user installs the PC tools with the one-line installer on Windows
- **THEN** the configurator's Devices workspace can connect to a device over SSH with nothing else installed

### Requirement: Locked dependency versions
The tools' dependencies SHALL be locked in `tools/deploy/uv.lock`, resolved for every supported system and for Python 3.11 and newer, while `pyproject.toml` keeps open minimum versions. Each release SHALL attach `canworks-<version>-constraints.txt`, the lock of the release's commit exported with exact versions and without hashes. The one-line installers SHALL install a release with that file as `uv tool install --constraints`.

#### Scenario: Same versions a month apart
- **WHEN** canworks 0.110.0 is installed with the one-line installer on two PCs a month apart, and `cantools` has had a new major release in between
- **THEN** both PCs have the `cantools` version in `canworks-0.110.0-constraints.txt`

#### Scenario: Release asset
- **WHEN** a version bump is released
- **THEN** the release has `canworks-<version>-constraints.txt`, and it pins every package in `uv.lock` of the tagged commit except `canworks` itself

### Requirement: Installs without a lock
When the release has no constraints file, the one-line installers SHALL say in one line that the release does not lock its dependency versions and install without constraints. When the file exists but cannot be downloaded, the install SHALL fail with a message and leave the installed tools unchanged. With `--wheel FILE` the installers SHALL take `--constraints FILE`, and without it install unlocked with the same one line.

#### Scenario: Release older than the lock
- **WHEN** the user installs a release that has no constraints asset with `--version`
- **THEN** the installer says the release does not lock its dependency versions and installs it as before

#### Scenario: Constraints download fails
- **WHEN** the release has a constraints asset and its download fails
- **THEN** the installer stops with a message naming the file, and the installed tools are unchanged
