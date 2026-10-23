## Context

The self-update (`pc-tools-self-update`, PR #207) works in two halves.
- `configurator/update.py` checks `releases/latest` once a day and stores the answer in `update.json`. It writes a run file and starts `canworks/updater.py` on the tools' base interpreter. The configurator then stops.
- The updater runs `uv tool install --force … canworks @ <release wheel URL>` and compares `canworks-deploy --version` with the run file's `from` and `to`. When the version is neither of them, it reinstalls `from` from *its* release.

The Mac failure on 2026-10-23 (update.log):
```
updating canworks 0.122.0 to 0.124.0
… deploy-v0.124.0/canworks-0.124.0-py3-none-any.whl: 404 Not Found
the install changed but is not 0.124.0 (0.128.3): installing 0.122.0 again
… deploy-v0.122.0/canworks-0.122.0-py3-none-any.whl: 404 Not Found
result: broken
```
- `update.json` had held `latest: 0.124.0` since 11:08Z, and that release had been pruned.
- 0.128.3 had been installed from the command line at 19:18, while a 0.122.0 configurator kept running.
- uv 0.11.32 leaves the tool environment untouched when the wheel download fails (checked here), so nothing was broken.

Constraints: the updater uses the standard library only and imports nothing of the tools. It never runs an install script. Its `uv tool install` arguments stay those of the installers (a test compares them). On Windows the file-lock probe runs before anything is changed.

## Goals / Non-Goals

**Goals:**
- Never offer or start an update to a version without an installable release.
- Never change the install before the new wheel is on disk.
- Roll back without needing any release on GitHub.
- Never downgrade, and never report "broken" while the tools run.
- A configurator older than the installed tools can get to the installed version in one click.

**Non-Goals:** changing release retention, or the installers.

## Decisions

### 1. Re-resolve before acting, and a shorter start re-check
- `server.update_target()` calls `updates.check()` every time, not only when the version differs from the stored one. It does this for Update now, Update when I quit (at the stop), and the CLI path.
- If the newest version is now another one, the update goes to that version. The page says "0.128.3 is the newest release now; updating to it". It doesn't refuse, because the user's intent was "update".
- If the check fails (offline), the update is refused with "Could not reach GitHub; nothing was changed".
- At start, a stored answer older than 1 hour triggers a background check. The 24 h limit stays for repeated checks *within* one configurator run, and the daily-check promise in the spec is unchanged for idle running.
- *Alternative:* HEAD the wheel URL of the stored version. Rejected because it still installs an outdated version when a newer one exists.

### 2. Download first, install from the local file
- The updater downloads `canworks-<v>-py3-none-any.whl` (and the constraints file, as today) into its temporary folder with urllib, which uses the system proxy settings.
- It installs `canworks @ file:///<tmp>/canworks-<v>-py3-none-any.whl`. A 404 or other download error ends with result `failed`: "The update to X could not be downloaded (HTTP 404). Nothing was changed."
- The installers' arguments are unchanged; only the spec's URL becomes a local file URL. The installer-match test compares arguments, not the spec, so it stays as it is.
- The receipt then records a `file://` requirement. Nothing reads it, because the installers always pass a URL again.

### 3. Roll back from a local copy of the environment
- After the Windows lock probe and the download, the updater renames `<uv tool dir>/canworks` to `<uv tool dir>/.canworks-update-backup`. A leftover backup from an earlier crash is deleted first.
- Rename works on all three systems once no tools process runs, which the configurator stop and the Windows probe guarantee. If the rename fails, the updater keeps the old env in place and falls back to today's in-place `--force` install with no local rollback. The result then says so if it fails.
- On success the backup is deleted.
- On failure the partial env is deleted and the backup is renamed back. The bin entries (`~/.local/bin/canworks-*` symlinks on macOS/Linux, uv's trampolines on Windows) point at the same env path, so they work again. The updater then runs `canworks-deploy --version` to confirm.
- *Alternative:* copy the env (`copytree`). Rejected because it is slower (~100 MB) and doubles disk use. Rename is atomic on one volume.
- *Alternative:* keep reinstalling the old wheel from GitHub. Rejected because that is the bug.

### 4. Compare with the installed version
- The updater's first step after the configurator has stopped is `canworks-deploy --version`. If that is ≥ `to`, the result is `already`: "Already on 0.128.3", nothing is installed, and the configurator restarts with `--resume`. The open tab therefore reloads into the installed version.
- The run file's `from` is then the installed version, not the process's.
- The configurator page learns the installed version without a subprocess. It globs `canworks-*.dist-info` in its own env's `site-packages` (the env is the same path after a reinstall). If that version is newer than `__version__`, the badge says "0.128.3 is installed; restart to use it" with **Restart**.
- Restart runs the same hand-off as Update with `to` = the installed version, so it ends in `already`. It uses the same guard (unsaved changes and so on).
- No update is offered for a stored `latest` that is ≤ the installed version.

### 5. Results
The result states:
- `ok`
- `already`
- `failed` (the old install is in place, checked by `--version`)
- `locked` (Windows)
- `broken`: only when `canworks-deploy --version` fails after the restore attempt.

`broken` keeps today's system message window and install command. The messages name the version actually installed.

## Risks / Trade-offs

- [Rename across volumes, e.g. a uv tool dir on a network drive] → the backup lives in the same parent folder, so it is never a cross-volume move.
- [A crash between rename and restore leaves no `canworks` env] → at the next run, the updater restores a leftover `.canworks-update-backup` when there is no `canworks` env. The configurator can't start in that state anyway; the user runs `canworks-config --update` or the installer.
- [Windows antivirus briefly holding a file during rename] → retry the rename for a few seconds, then fall back as in decision 3.
- [Re-check adds a network request to every Update press] → it is one redirect request (~200 ms), only on a user action.

## Migration Plan

Clean cut (not in real use). Old configurators keep their old updater for one more update. The first update to this version still runs the old updater code from the old install, so the fix takes effect from the update after that. Users who hit the old bug run the install command once, as the banner says.
