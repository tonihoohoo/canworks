## 1. Lock file

- [ ] 1.1 `uv lock` in `tools/deploy` (universal, Python >=3.11); commit `tools/deploy/uv.lock`
- [ ] 1.2 Light job: `uv lock --check --project tools/deploy`, path-filtered to `pyproject.toml` and `uv.lock`
- [ ] 1.3 CI jobs that install the tools' dependencies (`ci.yml` shards, `integration.yml`, `browser.yml`, `pc-tools.yml`, `local-runtime.yml`) install with `-c` from one `uv export` per job; no new jobs

## 2. Release

- [ ] 2.1 `release-deploy.yml`: `uv export --frozen --no-hashes --no-emit-project --no-dev` into `dist/canworks-<version>-constraints.txt`, attach it to the release
- [ ] 2.2 Release workflow test: the exported file pins every locked package except `canworks`

## 3. PC installs

- [ ] 3.1 `install-pc.sh` / `install-pc.ps1`: download the release's constraints, pass `--constraints`; one-line note and unlocked install when the release has none; fail when an existing asset can't be downloaded; `--constraints FILE` for `--wheel`
- [ ] 3.2 Updater (`updater.py`, `configurator/update.py`): same download and arguments; extend the "same arguments" test
- [ ] 3.3 Installer tests (sh and pwsh): with asset, without asset, failing download, `--wheel` with and without `--constraints`

## 4. Device installs

- [ ] 4.1 `install-stock.sh` and `install-bridge.sh`: `--constraints FILE` -> `pip install -c`; uv export fallback from a checkout; one-line note otherwise
- [ ] 4.2 `install-runtime.sh` / `.ps1`: download the release's constraints and pass them on (plugin and bridge)
- [ ] 4.3 `build-lely.sh`: `scripts/dcf-tools-constraints.txt` (exact versions incl. setuptools, header naming the Lely commit); test ties it to `_lely_dcf/VERSION`
- [ ] 4.4 Bridge and local runtime image workflows export constraints into the build context; Dockerfiles pass them to the scripts

## 5. Updates and runtime watch

- [ ] 5.1 `.github/dependabot.yml`: `uv` entry for `/tools/deploy`, monthly, one group; update the file's comment
- [ ] 5.2 `.github/workflows/runtime-watch.yml`: monthly + dispatch, upstream newest release vs `runtime-version`, open or update one `runtime-update` issue; least-privilege permissions
- [ ] 5.3 Ask Toni to turn on Dependabot security updates in the repository settings

## 6. Tested runtime on the Devices page

- [ ] 6.1 `canworks/tested_runtime.py` with `TESTED_RUNTIME`; unit test against `docker/local-runtime/runtime-version`
- [ ] 6.2 Devices page runtime row note for a newer runtime; install confirmation sentence about upstream's newest runtime
- [ ] 6.3 Page test: v4.2.5 device shows the note and keeps Rebuild; v4.2.4 shows none

## 7. Docs and version

- [ ] 7.1 README install section, `docs/install-pc.md`, `docs/install-stock.md`, `docs/devices.md`: locked versions, how updates arrive, tested runtime note
- [ ] 7.2 Tools minor version bump

## 8. Hardware and desktop checks (after release)

- [ ] 8.1 Windows (Toni's own PowerShell): one-line install of the new release; `uv pip list` in the tool env matches the constraints file
- [ ] 8.2 Mac: same, then a configurator self-update to the following release installs that release's locked versions
- [ ] 8.3 Pi: `install-runtime.sh` of the new release; `pip freeze` in `/opt/canworks/venv` matches the constraints; clean PLC start, node OPERATIONAL
