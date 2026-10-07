# Installing the PC tools: configurator, deploy tool, diagnostics

`openplc-canopen-config`, `openplc-canopen-deploy` and `openplc-canopen-diag` run on the engineering PC (Windows, macOS or Linux). They come as one package. The recommended way installs them with [uv](https://docs.astral.sh/uv/), which brings its own Python: nothing else needs to be on the PC, and no admin rights are needed. Installing with pip into a Python you already have also works: see [With pip or pipx](#with-pip-or-pipx).

The tools call the editor's `openplc-cli` for **Build only** and **New editor project**; it comes with the OpenPLC Editor (`openplc-cli install-cli`, or set `OPENPLC_CLI` to it).

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

Download `openplc_canopen_deploy-<version>-py3-none-any.whl` from the repository's **Releases** page (the newest `deploy-v<version>` release; you need to be signed in to GitHub, or use `gh release download deploy-v<version>`). The same file is for every operating system. Then, in the folder you downloaded it to:

```sh
uv tool install --python 3.12 openplc_canopen_deploy-<version>-py3-none-any.whl
```

uv downloads Python 3.12 if the PC has none, puts the tools in their own environment, and links the three commands into its bin folder (`%USERPROFILE%\.local\bin` on Windows, `~/.local/bin` on macOS and Linux). If it warns that the folder is not on PATH, run `uv tool update-shell` and open a new terminal. Check:

```sh
openplc-canopen-deploy --version
openplc-canopen-config            # opens the configurator in the browser
```

The configurator prints its address with an access token and opens it in the default browser. On a machine without one (over SSH, WSL without a browser), open the printed address yourself; `--no-browser` skips the attempt.

Linux works with x86_64 and ARM64 (glibc distributions; uv's Python and the one compiled dependency come as wheels for both).

The first install needs internet access to github.com (Python) and pypi.org (the `jsonschema` package). Behind a company proxy that inspects TLS, add `--native-tls` (or set `UV_NATIVE_TLS=1`) so uv trusts the certificates installed in the operating system.

## Update and uninstall

```sh
uv tool install --force --python 3.12 openplc_canopen_deploy-<new version>-py3-none-any.whl
uv tool uninstall openplc-canopen-deploy
```

The configurator's own settings (theme, online access) live in the user's settings folder (`%APPDATA%\openplc-canopen` on Windows, `~/Library/Application Support/openplc-canopen` on macOS, `$XDG_CONFIG_HOME/openplc-canopen` or `~/.config/openplc-canopen` on Linux) and survive both.

## The editor on Linux

The OpenPLC Editor comes for Linux as an AppImage (x64 and ARM64) on its releases page. Make it executable (`chmod +x`) and start it once: like on Windows and macOS, the first run puts the `openplc-cli` command on PATH, here as a shim in `~/.local/bin` that points at the AppImage file. Keep the AppImage where it is, or after moving it run `./OpenPLC.Editor-<version>.AppImage --cli install-cli` to point the shim at the new place. The tools then find `openplc-cli` on PATH; `OPENPLC_CLI` overrides it. The `openplc_canopen` editor library goes into the editor's settings folder, `~/.config/open-plc-editor` (or under `$XDG_CONFIG_HOME`).

## CAN adapters

The PC tools never open a CAN interface on the PC. Everything online (scan, object dictionary, parameters, trace, LSS, simulated devices) goes to the plugin on the runtime over the network. A CAN adapter plugged into the PC is used only when the runtime itself runs on that PC: install the runtime and the plugin there ([install-stock.md](install-stock.md), native or Docker) and set the network's `adapter` (`socketcan`, or `slcan` for serial adapters; see [config.md](config.md)). A Linux PC can so carry the whole bench: editor, PC tools, runtime with the plugin, and `vcan0` with simulated devices ([simulator.md](simulator.md)).

## Switching from pipx or a venv

Remove the old install first so the old commands do not shadow the new ones: `pipx uninstall openplc-canopen-deploy`, or delete the venv (for example `~/.venvs/canopen`) and any PATH entry or alias pointing into it. Then follow the steps above.

## With pip or pipx

Python 3.8 or newer. From a checkout of this repository, or with the release wheel in place of `./tools/deploy`:

```sh
pipx install ./tools/deploy          # or: python3 -m pip install ./tools/deploy
openplc-canopen-deploy --help
```

Without installing: `PYTHONPATH=tools/deploy python3 -m openplc_canopen_deploy --help` (needs `python3 -m pip install jsonschema`).

Debian 12 and later, Ubuntu 23.04 and later and other distributions that mark their Python as externally managed (PEP 668) refuse a plain `pip install` with "externally-managed-environment". Use uv as above, pipx (`sudo apt install pipx`), or a virtual environment (`python3 -m venv ~/.venvs/canopen && ~/.venvs/canopen/bin/pip install ./tools/deploy`).

## Releases

Releases are automatic. Merging a change that raises the version in `tools/deploy/pyproject.toml` (and `openplc_canopen_deploy/__init__.py`, which must match) releases it: once CI and the PC tools run (Windows, macOS, Linux) pass on that commit on `main`, the **Release PC tools** workflow creates the tag `deploy-v<version>` there and a GitHub release of that name with the wheel and a list of the pull requests merged since the previous release. Commits that keep the version publish nothing, a failed check publishes nothing for that commit, and an existing release is never replaced.

Fallbacks: **Run workflow** on the Release PC tools workflow releases the current `main` if its version has no release yet (same checks), and pushing a tag `deploy-v<version>` by hand releases that commit; a hand-pushed tag that does not match the package version fails without publishing. The tools are tested installed with uv as above on Windows, macOS and Linux (x86_64 and ARM64) on version bumps on `main`, on release tags and on **Run workflow**; pull requests run the same tests on Linux in CI.
