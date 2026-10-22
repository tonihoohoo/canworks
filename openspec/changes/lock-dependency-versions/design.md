# Design

## Lock format: `uv.lock` plus an exported constraints file per release

- `tools/deploy/uv.lock` is the single source. `uv lock` resolves universally: one file covers Windows, macOS and Linux, x86_64 and arm64, and every Python from the `requires-python` floor (3.11) up. That means one file serves the PC (3.14) and the Pi (the runtime image's 3.11).
- Dependabot's `uv` ecosystem updates `uv.lock` directly. A plain `requirements.txt` made by `uv pip compile --universal` was rejected because Dependabot rewrites pinned lines one at a time and can drop the platform markers.
- Installers can't read `uv.lock`: `uv tool install` takes no lock, and the device has no uv. So the release workflow runs
  `uv export --project tools/deploy --frozen --no-hashes --no-emit-project --no-dev --format requirements-txt`
  and attaches the result as `canworks-<version>-constraints.txt`. The release's commit and its constraints always match, because the export runs on the tagged commit with `--frozen`.
- Constraints, not requirements. `--constraints` only limits versions and installs nothing extra, so the platform markers in the export and the existing `pytest` override keep working.
- No hashes. A constraints file with hashes makes uv and pip demand hashes for everything, including the wheel itself. Exact versions are the goal here; hash-checking can come later.

## Where each install gets the file

| Install | Source of constraints |
|---|---|
| `install-pc.sh` / `.ps1` (release) | downloads `releases/download/deploy-v<X>/canworks-<X>-constraints.txt` into its temp folder |
| `install-pc.* --wheel FILE` | `--constraints FILE` if given, else unlocked with a note |
| Configurator updater | downloads the same asset as the installers (the "same arguments" test grows to cover `--constraints`) |
| `install-runtime.sh` / `.ps1` | downloads the asset, passes `--constraints` to `install-stock.sh` / `install-bridge.sh` |
| `install-stock.sh` / `install-bridge.sh` from a checkout | `--constraints FILE`; without it, when `uv` is on PATH they export from `tools/deploy/uv.lock`, else unlocked with a note |
| Bridge and local runtime images | the image workflows export from `uv.lock` into the build context and pass it to the scripts |

When the release has no constraints asset (a release from before this change, installed with `--version`), the PC installers and `install-runtime.sh` print one line, "this release does not lock its dependency versions", and install as today. A download error for an asset that exists fails the install. A missing file must not be confused with a network problem, so the scripts check the release's asset list (the same redirect check the scripts already use) before deciding.

## Skip check and self-update

The "already installed" skip compares only the canworks version and Python, as today. A lock update ships only with a version bump, so the same version always means the same locked set. `--force` reinstalls with the release's constraints.

## dcf-tools venv

`build-lely.sh` installs dcf-tools from the Lely source at `LELY_REF`. Its Python dependencies are pinned in `scripts/dcf-tools-constraints.txt` (exact versions, including `setuptools`, which replaces the inline `setuptools<81`). Dependabot does not cover that file, because the Lely commit and these versions move together and change rarely. The file names the Lely commit it was made for, and a test fails when `_lely_dcf/VERSION` changes without the file.

## CI

- A lint step `uv lock --check --project tools/deploy` runs in the light job only when `tools/deploy/pyproject.toml` or `uv.lock` changed (path filter). It adds about 5 s to those runs and nothing to others.
- Jobs that `pip install` the tools' dependencies install with `-c` from one exported file, made once per job by `uv export` (uv is already on the runners through `setup-uv`, or is a single static download). Test-only packages (Playwright, pytest) stay unlocked; they never ship.
- `ci-minutes-budget`: no new jobs. Dependabot adds about one CI run a month, plus rare security PRs.

## Dependabot

```yaml
- package-ecosystem: uv
  directory: /tools/deploy
  schedule: { interval: monthly }
  groups: { python: { patterns: ["*"] } }
```

Security updates use the repository's Dependabot security updates setting (Toni turns it on in the repository settings; this repository's token can't change it). Dependabot PRs follow the normal rules: CI must be green. Toni merges them, or the PC tools auto-merge rule covers them if he wants. A lock-only PR has no version bump, so it reaches users with the next release. For an urgent security fix, the PR gets a patch bump by hand.

## Tested runtime

- `canworks/tested_runtime.py` holds `TESTED_RUNTIME = "v4.2.4"`. A unit test keeps it equal to `docker/local-runtime/runtime-version`, so bumping one without the other fails CI.
- Devices page, runtime row: when the probe's runtime version is newer than `TESTED_RUNTIME`, show one muted line, "canworks is tested with runtime v4.2.4; this device runs v4.2.5." Actions are unchanged (Rebuild is still offered). An older or equal version, or an unknown one, shows nothing extra.
- The **Install OpenPLC Runtime and canworks** confirmation already names upstream's installer. It adds that the installer installs upstream's newest runtime.
- `runtime-watch.yml`: runs monthly and on manual dispatch. It reads the newest release tag of the upstream runtime repository from the GitHub API and compares it with `runtime-version`. When upstream is newer, it opens one issue titled "OpenPLC runtime vX is out (tested: vY)", or updates the open one with the label `runtime-update`. Permissions: `contents: read`, `issues: write`. It doesn't bump anything by itself, because a bump needs the archive's sha256 and a full CI run.

## Risks

- **A locked version gets yanked from PyPI.** uv and pip still install yanked versions when an exact pin asks for them, so old releases keep installing.
- **Platform gaps in the lock.** A universal lock can choose a version that has no wheel on a rare platform (for example Windows arm64). Today's open ranges have the same risk, and the PC tools job (Windows, macOS) installs from the lock on every tools change.
- **Lock drift between releases.** CI tests `main`'s lock, and each release exports the lock of its own commit, so a release always ships the lock CI tested on that commit.
