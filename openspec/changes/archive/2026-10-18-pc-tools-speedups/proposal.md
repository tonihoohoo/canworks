# Proposal: pc-tools-speedups (with one-line installers)

## Why

The standalone-executables explore (2026-10-17) built and timed PyInstaller (folder and single file), Nuitka and a portable Python bundle against today's uv install. None was faster: the uv install already runs the fastest interpreter measured (python-build-standalone, statically linked, PGO + LTO). Frozen builds started 30-70 ms slower (single file 0.65 s slower on every start) and ran CPU work 15-45 % slower. So the PC tools stay on uv, and no standalone executables are built.

The same measurements found three cheap speedups that apply to the uv install:

- **First start after install is 3x slower** (about 620 ms instead of 200 ms for `canworks-config --version` on Linux), because `uv tool install` does not compile bytecode unless asked, so the first run of every module compiles it.
- **`jsonschema` is a third of the configurator's start-up imports** (about 55 of 150 ms): five modules import it at the top, although nothing validates until a config is opened or checked.
- **Trace CSV export spends most of its time quoting cells**: `_csv_cell` runs a generator per cell. A precompiled regex made exporting 200 000 frames 15-20 % faster with byte-identical output.

Toni also asked (2026-10-18) for an install script users can run by copy-pasting one line, which installs or updates, for the PC tools and for the runtime plugin alike. Today the PC tools need three steps (install uv, download the wheel from the Releases page, run `uv tool install` on it) and the plugin needs a `git clone` on the device before `install-stock.sh`.

## What Changes

- **One-line PC tools installer**: `scripts/install-pc.sh` (macOS, Linux) and `scripts/install-pc.ps1` (Windows), run straight from GitHub (`curl -LsSf <raw URL> | sh`, `irm <raw URL> | iex`). They install uv when it is missing, find the newest `deploy-v` release, and install its wheel from its release URL with `uv tool install --force --compile-bytecode --python 3.12`. Running the line again updates. Options: `--version X` (a given release), `--uninstall`, `--wheel FILE` (a local wheel; used by CI). Becomes the first install route in the docs and the release notes; the manual steps stay.
- **One-line runtime plugin installer**: `scripts/install-runtime.sh`, run as `curl -LsSf <raw URL> | sudo bash`, downloads the source of the newest `deploy-v` release (not `main`) and runs its `install-stock.sh` with the options given after `-s --` (for example `--with-link`, `--uninstall`). No git checkout on the device. Running it again updates (re-runs the install of the newer release). `--version X` picks a release. The same install runs from a Windows, macOS or Linux PC onto the remote device over SSH (Toni, 2026-10-18): `install-runtime.sh --ssh USER@HOST` on macOS/Linux and `scripts/install-runtime.ps1 -Ssh USER@HOST` on Windows, using the system's own `ssh` (built into Windows 10/11); nothing else is needed on the PC.

- Documented install and update commands, the release notes template, the README and the PC tools CI job use `uv tool install --compile-bytecode`. The pip route gets nothing new (pip already compiles).
- `jsonschema` is imported when the first validation runs, not at module import. `canworks-config`, `canworks-deploy --version`/`--help` and `canworks-diag --help` start without importing `jsonschema`, `python-can`, `cantools`, `j1939`, `zeroconf` or `iroh`; a unit test keeps it that way.
- Trace CSV export quotes cells with a precompiled regex; the output is unchanged.
- The decision to keep uv and not ship frozen executables is recorded in the design, with the measurements.

No config, schema, page or command-line change.

## Capabilities

### Modified Capabilities
- `canopen-pc-install`: one-line installer for install and update; the documented install and update commands compile bytecode, and CI installs the same way; the tools start without importing their heavy libraries.
- `canopen-stock-install`: one-line install and update of the plugin from the newest release, without a git checkout, on the device or from a PC over SSH.

## Impact

- New scripts: `scripts/install-pc.sh`, `scripts/install-pc.ps1`, `scripts/install-runtime.sh`, `scripts/install-runtime.ps1`.
- Docs: `docs/install-stock.md` (one-line install first, git checkout kept), `docs/install-pc.md`, `docs/deploy.md`, `README.md`, `tools/deploy/README.md`, `tools/deploy/release-notes.md` (and `test/pc-tools/test_release_notes.py`, which checks the install line).
- CI: `.github/workflows/pc-tools.yml` installs through `install-pc.sh`/`install-pc.ps1 --wheel` (runs only on version bumps; adds a few seconds there). PR CI gets two small unit tests, `shellcheck` of the two shell scripts and a dry-run test of their release lookup and argument handling (well under a second each).
- Code: `tools/deploy/canworks/contract.py`, `simfile.py`, `simmachine.py`, `notes.py`, `configurator/simulation.py` (lazy `jsonschema`), `bustrace/formats.py` (`_csv_cell`).
- Version: minor bump of the tools package (new install route).
- Hardware/PC tasks: the PC one-liner on the Windows PC and the Mac (install, then update), the runtime one-liner from the Windows PC over SSH onto the Pi (update an existing install, then a clean PLC start).
