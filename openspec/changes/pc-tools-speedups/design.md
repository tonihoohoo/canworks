# Design: pc-tools-speedups

## Context

Measured on Linux x86_64, tools 0.81.2 (details in the project research note `standalone-executables-2026-10-17.md`):

| Build | deploy --version | config to page | 200k-frame CSV convert |
|---|---|---|---|
| uv install (python-build-standalone 3.12) | 151 ms | ~210 ms | 4.8-5.0 s |
| uv install, first run without bytecode | 619 ms | | |
| PyInstaller folder | 195-225 ms | 270 ms | 6.0-7.1 s |
| PyInstaller single file | 849 ms | 923 ms | 7.8 s |
| Nuitka standalone (LTO) | 176 ms | 217 ms | 5.9 s |
| Portable Python bundle | 161 ms | 227 ms | 5.3 s |

The configurator already imports python-can, cantools, j1939, zeroconf and iroh lazily. What is left at start is ~150 ms of imports, of which `jsonschema` (with `attrs`, `referencing`, `rpds`) is ~55 ms.

## Goals / Non-Goals

**Goals:** faster first start after install and update; faster configurator and deploy tool start; faster trace CSV export; keep it that way with a test; one copy-paste line that installs or updates the PC tools, and one for the runtime plugin.

**Non-Goals:** standalone executables, installers or code signing (measured slower, and they would add release build jobs); a Python version change (3.14 was ~5 % faster on decoding but slower to start); a wider performance hunt in the trace decoder.

## Decisions

### Keep uv; no frozen executables

The uv install is the fastest measured form, needs no signing for our own files, and costs no extra CI. Frozen builds would add four release jobs and AV/Gatekeeper friction for a slower result. If people without internet at install time ever need the tools, the portable Python bundle (python.org's signed embeddable Python on Windows) is the form to revisit, not PyInstaller or Nuitka.

### `--compile-bytecode` in every documented uv install

`uv tool install --compile-bytecode` compiles all `.pyc` at install (a few seconds, once). It is added to the install and update commands in `install-pc.md`, the README, `tools/deploy/README.md`, `docs/deploy.md` and the release notes template, and to the `pc-tools.yml` install step so CI installs as the docs say. The "straight from GitHub" and "from its commit" commands get it too. A user who already installed without it gets bytecode on the next update.

### Lazy `jsonschema`

Each of the five modules that import `jsonschema` at the top gets the import inside the functions that validate. `contract.Validator`, today built at import time, becomes `contract.validator_class()`, which builds the extended validator once and caches it; its two callers (`contract.py`, `simfile.py`) use it. `best_match` is imported at its call sites. Alternative considered: a module `__getattr__` proxy; rejected as harder to read for the same effect.

A unit test starts a fresh interpreter (`sys.executable -c`), imports `canworks.configurator.server`, `canworks.cli` and `canworks.diag`, and fails when any of `jsonschema`, `can`, `cantools`, `j1939`, `zeroconf`, `iroh` is in `sys.modules`. It costs well under a second, so it fits the existing tools shards.

### CSV quoting with a regex

`_csv_cell` uses a module-level `re.compile(r'[,"\n\r]').search` and skips `str()` for strings. Same quoting rules, so existing CSV tests and output stay as they are; a test pins the quoting of a comma, a quote, CR and LF.

### One-line installers

**Where they live.** In `scripts/`, run from `https://raw.githubusercontent.com/tonihoohoo/canworks/main/scripts/<name>`. The script on `main` is only a bootstrap: what it installs is always a released version (the newest `deploy-v` release, or `--version`), never `main`'s code. The docs also show the pinned form (`.../deploy-v<version>/scripts/<name>`) and "download, read, then run" for people who don't pipe into a shell. Alternative considered: release assets (`releases/latest/download/install-pc.sh`); rejected because a fixed script per release adds assets the release-notes test must track and gives no benefit over a pinned raw URL.

**Finding the newest release without the API.** `https://github.com/tonihoohoo/canworks/releases/latest` redirects to `.../releases/tag/deploy-v<version>`; the scripts read the version from that redirect (curl `-w %{url_effective}`; PowerShell `HttpClient` with redirects off, reading `Location`). No API token and no API rate limit (60 requests per hour per IP unauthenticated, easily hit behind a company NAT). The automatic release already marks each new release as latest. The wheel URL is then `.../releases/download/deploy-v<v>/canworks-<v>-py3-none-any.whl`.

**install-pc.sh / install-pc.ps1.**
1. uv: use `uv` on PATH, else `~/.local/bin/uv` (`%USERPROFILE%\.local\bin\uv.exe`), else run uv's official installer and use it from that folder in the same session (the new PATH only reaches new terminals).
2. `uv tool install --force --compile-bytecode --python 3.12 <wheel URL or --wheel FILE>`; `--force` makes the same line an update.
3. `uv tool update-shell` when the bin folder is not on PATH, then print the installed version and "open a new terminal" when PATH changed.
4. `--uninstall` runs `uv tool uninstall canworks` and leaves uv and the settings folder (the docs already say settings survive).
Proxy: uv's own `UV_NATIVE_TLS`/system-certificate settings pass through; the docs keep the note. POSIX `sh` for the Unix script (it runs on macOS's sh and Debian's dash), PowerShell 5.1 compatible for Windows (the version every Windows 10/11 has).

**install-runtime.sh.** Needs bash and root (it says so and exits when not root). Resolves the release as above, downloads `archive/refs/tags/deploy-v<v>.tar.gz` into a temporary folder, verifies it unpacked a `scripts/install-stock.sh`, and runs it with every argument after the script's own options. `install-stock.sh` already detects native or managed Docker, rebuilds on re-run and keeps exactly one `plugins.conf` line, so update is "install the newer release". The temporary folder is removed afterwards; nothing about the release is kept except what `install-stock.sh` installs (it records the runtime commit already; the plugin version is in `canworks-sim --version`). It does not install OpenPLC Runtime itself: without a runtime, `install-stock.sh`'s existing message applies.

**Testing.** PR CI (tools shard): `shellcheck` on the two shell scripts and a test that runs each script with `--dry-run` against a fake release URL (a local HTTP server answering the redirect) and checks the version it resolves and the commands it would run. `pc-tools.yml` (version bumps only) installs through `install-pc.sh --wheel dist/*.whl` on Linux/macOS and `install-pc.ps1 -Wheel` on Windows, so the scripts run on all four systems before a release. The runtime script's real run is a hardware task on the Pi; the weekly integration workflow is not changed.

## Risks / Trade-offs

- Piping a script into a shell trusts whatever is on `main` at that moment. Mitigations: scripts are short and plain, install only released versions, and the docs show the pinned and download-first forms.
- The runtime one-liner still builds on the device (Lely, plugin), so it takes as long as today's install.
- The redirect trick depends on GitHub's `releases/latest` behaviour; if it ever fails, the scripts fall back to the API once and say which they used.

- A lazy import moves an `ImportError` from start to first use. The dependency is required by the package, so this only matters in a broken install; the smoke run still validates a config.
- `--compile-bytecode` makes install a few seconds longer. Acceptable for one-off installs.
- CI time: two small unit tests in the existing tools shards; `pc-tools.yml` runs only on version bumps. The PR states the CI wall and summed time against the baseline.
