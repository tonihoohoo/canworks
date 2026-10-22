## 1. Lock file

- [x] 1.1 `uv lock` in `tools/deploy` (universal, Python >=3.11); commit `tools/deploy/uv.lock`
- [x] 1.2 Lock check (`scripts/check-lock.py`, version bumps need no new lock) in the `changes` job, only when `pyproject.toml` or `uv.lock` changed
- [x] 1.3 CI jobs that install the tools' dependencies install the locked versions (`.github/actions/locked-versions`: `PIP_CONSTRAINT` and `tools/deploy/constraints.txt`; via `build-plugin` or directly); PC tools job with `--constraints` and `--with-requirements`; no new jobs

## 2. Release

- [x] 2.1 `release-deploy.yml`: `uv export --frozen --no-hashes --no-emit-project --no-dev` into `dist/canworks-<version>-constraints.txt`, attach it to the release
- [x] 2.2 Release workflow step checks the exported file (pins present, no `canworks`); release notes template names the asset (its coverage test)

## 3. PC installs

- [x] 3.1 `install-pc.sh` / `install-pc.ps1`: download the release's constraints, pass `--constraints`; one-line note and unlocked install when the release has none; fail when an existing asset can't be downloaded; `--constraints FILE` for `--wheel`
- [x] 3.2 Updater (`updater.py`, `configurator/update.py`): same download and arguments; extend the "same arguments" test
- [x] 3.3 Installer tests (sh and pwsh): with asset, without asset, failing download, `--wheel` with and without `--constraints`

## 4. Device installs

- [x] 4.1 `install-stock.sh` and `install-bridge.sh`: `--constraints FILE` -> `pip install -c`; uv export fallback from a checkout; one-line note otherwise
- [x] 4.2 `install-runtime.sh` / `.ps1`: download the release's constraints and pass them on (plugin and bridge)
- [x] 4.3 `build-lely.sh`: `scripts/dcf-tools-constraints.txt` (exact versions incl. setuptools, header naming the Lely commit); test ties it to `_lely_dcf/VERSION`
- [x] 4.4 Bridge and local runtime image workflows export constraints into the build context; Dockerfiles pass them to the scripts

## 5. Updates and runtime watch

- [x] 5.1 `.github/dependabot.yml`: `uv` entry for `/tools/deploy`, monthly, one group; update the file's comment
- [x] 5.2 `.github/workflows/runtime-watch.yml`: monthly + dispatch, upstream newest release vs `runtime-version`, open or update one `runtime-update` issue; least-privilege permissions
- [x] 5.3 Ask the owner to turn on Dependabot security updates in the repository settings (on 2026-10-22)

## 6. Tested runtime on the Devices page

- [x] 6.1 `TESTED_RUNTIME` in `canworks/devices/plan.py`; unit test against `docker/local-runtime/runtime-version`
- [x] 6.2 Devices page runtime row note for a newer runtime; install confirmation sentence about upstream's newest runtime
- [x] 6.3 Plan tests: a newer runtime gets the note and keeps Rebuild; the tested, an older or an unknown one gets none (the page renders the row's `hint` as a grey line)

## 7. Docs and version

- [x] 7.1 README install section, `docs/install-pc.md`, `docs/install-stock.md`, `docs/devices.md`: locked versions, how updates arrive, tested runtime note
- [x] 7.2 Tools minor version bump (0.108.0)
- [x] 7.3 CI wall and summed job time against the baseline, in the PR (main CI run: wall 10m02s -> 10m39s, summed job time 60.6 -> 56.8 min)

## 8. Hardware and desktop checks (after release)

- [x] 8.1 Windows (the owner's own PowerShell): one-line install of the new release; `uv pip list` in the tool env matches the constraints file (PASSED 2026-10-22: `uv pip install --dry-run -r` the release's constraints against the tool env resolved 40 packages and would only add pytest, pluggy, iniconfig and pygments, which the installer leaves out on purpose; nothing to change or remove)
- [x] 8.2 Mac: same, then a configurator self-update to the following release installs that release's locked versions (PASSED 2026-10-22 on macOS arm64 in an isolated tool dir: 0.108.0 install matches its constraints, 28 shared packages; self-update 0.108.0 -> 0.111.0 ran uv with --constraints and put three deliberately drifted packages back to their pins; an update that starts on a release before 0.108.0 runs the old updater, so it is not locked)
- [x] 8.3 Pi: `install-runtime.sh` of the new release; `pip freeze` in `/opt/canworks/venv` matches the constraints; clean PLC start, node OPERATIONAL (PASSED 2026-10-22 with 0.108.0 --with-link: 30 shared packages, 0 mismatches, absent ones are Windows/macOS-only; the install leaves the PLC without a program, so the project was deployed again, then RUNNING and the node OPERATIONAL)
