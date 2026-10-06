# Installing the PC tools: configurator, deploy tool, diagnostics

`openplc-canopen-config`, `openplc-canopen-deploy` and `openplc-canopen-diag` run on the engineering PC (Windows, macOS or Linux). They come as one package. The recommended way installs them with [uv](https://docs.astral.sh/uv/), which brings its own Python: nothing else needs to be on the PC, and no admin rights are needed. Installing with pip into a Python you already have also works: see [With pip or pipx](#with-pip-or-pipx).

The tools call the editor's `openplc-cli` for **Build only** and **New editor project**; it comes with the OpenPLC Editor (`openplc-cli install-cli`, or set `OPENPLC_CLI` to it).

## 1. Install uv (once per PC)

Windows (PowerShell):

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

macOS (Terminal):

```sh
curl -LsSf https://astral.sh/uv/install.sh | sh
```

`winget install astral-sh.uv` and `brew install uv` work too. Open a new terminal afterwards so `uv` is on PATH.

## 2. Install the tools

Download `openplc_canopen_deploy-<version>-py3-none-any.whl` from the repository's **Releases** page (the newest `deploy-v<version>` release; you need to be signed in to GitHub, or use `gh release download deploy-v<version>`). The same file is for every operating system. Then, in the folder you downloaded it to:

```sh
uv tool install --python 3.12 openplc_canopen_deploy-<version>-py3-none-any.whl
```

uv downloads Python 3.12 if the PC has none, puts the tools in their own environment, and links the three commands into its bin folder (`%USERPROFILE%\.local\bin` on Windows, `~/.local/bin` on macOS). If it warns that the folder is not on PATH, run `uv tool update-shell` and open a new terminal. Check:

```sh
openplc-canopen-deploy --version
openplc-canopen-config            # opens the configurator in the browser
```

The first install needs internet access to github.com (Python) and pypi.org (the `jsonschema` package). Behind a company proxy that inspects TLS, add `--native-tls` (or set `UV_NATIVE_TLS=1`) so uv trusts the certificates installed in the operating system.

## Update and uninstall

```sh
uv tool install --force --python 3.12 openplc_canopen_deploy-<new version>-py3-none-any.whl
uv tool uninstall openplc-canopen-deploy
```

The configurator's own settings (theme, online access) live in the user's settings folder (`%APPDATA%\openplc-canopen`, `~/Library/Application Support/openplc-canopen`) and survive both.

## Switching from pipx or a venv

Remove the old install first so the old commands do not shadow the new ones: `pipx uninstall openplc-canopen-deploy`, or delete the venv (for example `~/.venvs/canopen`) and any PATH entry or alias pointing into it. Then follow the steps above.

## With pip or pipx

Python 3.8 or newer. From a checkout of this repository, or with the release wheel in place of `./tools/deploy`:

```sh
pipx install ./tools/deploy          # or: python3 -m pip install ./tools/deploy
openplc-canopen-deploy --help
```

Without installing: `PYTHONPATH=tools/deploy python3 -m openplc_canopen_deploy --help` (needs `python3 -m pip install jsonschema`).

## Releases

Releases are automatic. Merging a change that raises the version in `tools/deploy/pyproject.toml` (and `openplc_canopen_deploy/__init__.py`, which must match) releases it: once CI and the Windows/macOS PC tools run pass on that commit on `main`, the **Release PC tools** workflow creates the tag `deploy-v<version>` there and a GitHub release of that name with the wheel and a list of the pull requests merged since the previous release. Commits that keep the version publish nothing, a failed check publishes nothing for that commit, and an existing release is never replaced.

Fallbacks: **Run workflow** on the Release PC tools workflow releases the current `main` if its version has no release yet (same checks), and pushing a tag `deploy-v<version>` by hand releases that commit; a hand-pushed tag that does not match the package version fails without publishing. The tools are tested on Windows and macOS (installed with uv as above) whenever `tools/deploy/` changes.
