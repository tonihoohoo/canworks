## 1. Installers

- [x] 1.1 `install-pc.sh` / `install-pc.ps1`: default Python 3.14 (usage text too) and a `UV_MIN` constant (0.9.0) next to it
- [x] 1.2 Both: when `uv --version` is older than `UV_MIN`, run `uv self update`; on failure exit non-zero saying to update uv with the tool that installed it
- [x] 1.3 Both: skip check reads `uv tool list --show-python`; skip only when version and (for a version `--python`) Python major.minor match
- [x] 1.4 `test/pc-tools/test_install_scripts.py`: default 3.14 in the expected commands; old fake uv gets `self update`; failed self update exits non-zero; same version on 3.12 reinstalls; same version on 3.14 skips; `--python /path` keeps the version-only check
- [x] 1.5 `tools/deploy/release-notes.md` and `test_release_notes.py`: `--python 3.14`; one line that an existing install moves to Python 3.14 on its next update

## 2. Package floor

- [x] 2.1 `tools/deploy/pyproject.toml`: `requires-python = ">=3.11"`, minor version bump
- [x] 2.2 `uv run` from the checkout resolves on all platforms: `uv lock --project tools/deploy --dry-run` step in the PC tools job (fails on the old `>=3.10` floor, passes on `>=3.11`)

## 3. CI

- [x] 3.1 `ci.yml`: `plugin`, `vcan`, `tools` on 3.11; `configurator-page` on 3.14
- [x] 3.2 `integration.yml` on 3.11; `browser.yml`, `local-runtime.yml` on 3.14
- [x] 3.3 `pc-tools.yml`: every `uv run --python 3.12` to 3.14
- [ ] 3.4 Compare CI wall time with the last main run: no growth

## 4. Docs

- [x] 4.1 README test commands and install text; `docs/install-pc.md` (3.14 commands, "Python 3.11 or newer" for pip); `docs/configurator.md`; `tools/deploy/README.md`; `docs/development.md` Python versions paragraph

## 5. Hardware and desktop checks

- [ ] 5.1 Windows: an existing 0.9x install on 3.12, run the one-line installer from a normal PowerShell (not a sandboxed shell): reinstalled on 3.14 (`uv tool list --show-python`), shortcut and configurator start work, second run skips
- [ ] 5.2 Mac: same as 5.1
- [ ] 5.3 Pi: deploy a config with `canworks-deploy` from the 3.14 install, clean PLC start, node 23 OPERATIONAL
