## Why

On 2026-10-23 the configurator on a Mac offered "0.124.0 available", although GitHub had no such release any more. The update then ended with "the old version could not be installed again", and the install was healthy all along. The update log showed four defects in how the self-update works:

1. **Stale offer.** The daily check stores the newest version in `update.json` and the page offers it for 24 hours. 0.124.0 was the newest release for about 25 minutes. The release cleanup, which keeps the newest 4 `deploy-v` releases, deleted it a few hours later, and the page kept offering it. Update does not ask GitHub again before it installs.
2. **Version from the process, not the disk.** The configurator still running 0.122.0 had been open since the morning. The tools had since been reinstalled as 0.128.3 from the command line. The updater compared against the running process's version, so it misread the newer install as a half-finished change. It even tried to *downgrade* it to 0.122.0.
3. **Rollback from GitHub.** The rollback downloads the old version's release. That release is often gone (pruned) or never existed (a version superseded on main is not released).
4. **False "broken".** Both downloads returned 404 and uv changed nothing. The updater still reported a broken install and told the user to run the install command.

## What Changes

- **The offer is checked before acting.** Update now, Update when I quit and `canworks-config --update` ask `releases/latest` again right before they start. If a different version is now newest, the update goes to that version, and the page says so. A stored "latest" that is not newer than the *installed* version is not offered. The page re-checks at start when the stored answer is older than 1 hour, instead of 24.
- **Download first, then install.** The updater downloads the new release's wheel and constraints into its temporary folder before it touches the install. It installs from that local file. A download that fails ends with "Nothing was changed".
- **Roll back from a local copy.** Before uv runs, the updater moves the tools' environment aside (same folder, `.canworks-update-backup`). On failure it puts that copy back. The old version's release is no longer needed.
- **Compare with what is installed.** The updater reads the installed version (`canworks-deploy --version`) before it does anything. If that is already the target or newer, it installs nothing, says "Already on X", and restarts the configurator. The page shows "X is installed; restart to use it" with a **Restart** button when the installed tools are newer than the running configurator.
- **Honest result.** "Broken" (and the system message window with the install command) only appears when, after the restore, `canworks-deploy --version` does not run. A failure that left the old install in place says "The update failed: <reason>. Still on X."

## Capabilities

### New Capabilities
<!-- none -->

### Modified Capabilities
- `pc-tools-self-update`: the update check, update from the configurator, update never leaves a broken install, and update from the command line. Added: restart into a newer installed version.

## Non-goals

- The release cleanup (keep the newest 4) stays as it is. With these changes an update no longer depends on old releases.
- No change to the one-line installers.

## Impact

- `tools/deploy/canworks/updater.py`: pre-download, local wheel, env backup and restore, installed-version check, results.
- `tools/deploy/canworks/configurator/update.py` and `server.py`: re-check before update, the 1 h start re-check, installed version vs running, the Restart action, run-file fields (no `old_wheel`/`old_constraints`).
- Configurator page: the "installed is newer" badge and Restart button, and the message texts.
- Tests: `tools/deploy/tests/test_update.py`, `test_configurator_update_page.py`, and `test/pc-tools/update_e2e.py` (old release missing, stale latest, newer install under an old configurator).
- `docs/install-pc.md` (From the configurator) and README line on updates.
