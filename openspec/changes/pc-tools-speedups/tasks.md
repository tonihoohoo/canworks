# Tasks

## 1. Install with bytecode

- [ ] 1.1 Add `--compile-bytecode` to every remaining manual `uv tool install` command in `docs/install-pc.md` (install, update, from GitHub, from a commit), `docs/deploy.md`, `README.md` (install and the "same checks" line), `tools/deploy/README.md` and `tools/deploy/release-notes.md`; update `test/pc-tools/test_release_notes.py`.
- [ ] 1.2 `.github/workflows/pc-tools.yml`: install step uses `--compile-bytecode`.

## 2. Lazy jsonschema

- [ ] 2.1 Test: a fresh interpreter importing `canworks.configurator.server`, `canworks.cli` and `canworks.diag` has none of `jsonschema`, `can`, `cantools`, `j1939`, `zeroconf`, `iroh` in `sys.modules`. Fails on main (`jsonschema`).
- [ ] 2.2 Move the `jsonschema` imports in `contract.py`, `simfile.py`, `simmachine.py`, `notes.py` and `configurator/simulation.py` into the validating functions; `contract.Validator` becomes cached `contract.validator_class()`.
- [ ] 2.3 Measure `canworks-config --version` and time to first page before and after on Linux; note both in the PR.

## 3. CSV export

- [ ] 3.1 Test pinning `_csv_cell` quoting (comma, quote, CR, LF, plain text, numbers).
- [ ] 3.2 `_csv_cell` with a precompiled regex; measure the 200k-frame `canworks-diag convert ... .csv` before and after; output byte-identical.

## 4. One-line installers

- [ ] 4.1 Test: `--dry-run` of `install-pc.sh` and `install-runtime.sh` against a local fake release server resolves the newest version from the `releases/latest` redirect, builds the wheel/tarball URL, honours `--version`, `--wheel`, `--uninstall` and passes `install-stock.sh` options through; `shellcheck` on both shell scripts in the tools shard.
- [ ] 4.2 `scripts/install-pc.sh` (POSIX sh) and `scripts/install-pc.ps1` (PowerShell 5.1): find or install uv, install or update with `--force --compile-bytecode --python 3.12`, `update-shell`, `--version`, `--wheel`, `--uninstall`.
- [ ] 4.3 `scripts/install-runtime.sh`: root check, release lookup, download and unpack the tag's source, run its `install-stock.sh` with the passed options, clean up.
- [ ] 4.4 `pc-tools.yml` installs through the scripts with the built wheel on all four runners.
- [ ] 4.5 Docs: one-line routes first in `docs/install-pc.md` and `docs/install-stock.md` (pinned and download-first forms too), README install section, `tools/deploy/README.md`, `docs/deploy.md`, release notes template.

## 5. Hardware and PCs

- [ ] 5.1 Windows PC: run the PowerShell one-liner on a PC with the tools installed (update), then `--version` of an older release and back; `canworks-config` opens.
- [ ] 5.2 Mac: run the shell one-liner (update); `canworks-deploy --version` prints the release.
- [ ] 5.3 Pi: run the runtime one-liner on the existing install (update to the newest release), check `canworks-sim --version` and one `canworks` line in `plugins.conf`; clean PLC start afterwards.

## 6. Release

- [ ] 6.1 Minor bump of the tools package (`pyproject.toml` and `__version__`).
- [ ] 6.2 CI time: wall and summed job time against the baseline (median of the last 5 green `main` runs with code changes), stated in the PR.
