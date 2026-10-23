## 1. Updater (canworks/updater.py)

- [ ] 1.1 Read the installed version first (`check_cmd`). When it is ≥ `to`, finish `already` ("Already on X"), install nothing, restart. Use it as `from` in messages.
- [ ] 1.2 Download the new wheel and constraints into the work folder (urllib, system proxy). A failure finishes `failed` with "could not be downloaded … Nothing was changed".
- [ ] 1.3 Install from `canworks @ file:///…whl`, with the installers' arguments unchanged.
- [ ] 1.4 Env backup: after the Windows lock probe, rename `<tool dir>/canworks` to `.canworks-update-backup`, retrying a few seconds. Delete a stale backup first, or restore it when `canworks` is missing. If the rename fails, fall back to the in-place install and say so in the log.
- [ ] 1.5 On failure: remove the partial env, rename the backup back, and confirm with `--version`. On success: delete the backup.
- [ ] 1.6 Results: `ok`, `already`, `failed` (still on X), `locked`, and `broken` only when `--version` fails after the restore. Drop `old_wheel` and `old_constraints`.

## 2. Configurator (configurator/update.py, server.py, page)

- [ ] 2.1 `update_target()` always re-checks `releases/latest`. When the version differs, update to the new one and say so. When offline, refuse with "nothing was changed". Do the same for Update when I quit and the CLI.
- [ ] 2.2 Start re-check when the stored result is older than 1 hour. Don't offer a `latest` that is ≤ the installed version.
- [ ] 2.3 Installed version from `canworks-*.dist-info` in the env. When it is newer than `__version__`, the badge says "X is installed; restart to use it" with Restart (same guard and hand-off, ends in `already`).
- [ ] 2.4 Message bar texts for the new results. `canworks-config --update` prints the installed version (not the process's).

## 3. Tests

- [ ] 3.1 test_update.py: a stale latest gets re-resolved; a 404 wheel leaves nothing changed; a newer install under an old configurator gives `already` with no uv call; a failing uv restores the backup with no old release; `broken` only when `--version` fails; stale backup restore.
- [ ] 3.2 test_configurator_update_page.py: the Restart badge, and the "updating to the newer X" text.
- [ ] 3.3 update_e2e.py: the fake release server has no old wheel (rollback must not need it), plus a step where releases/latest moves after the offer.
- [ ] 3.4 The installer argument test still passes, unchanged.

## 4. Docs and release

- [ ] 4.1 docs/install-pc.md "From the configurator": re-check, Restart, local rollback, and how to restore `.canworks-update-backup` by hand.
- [ ] 4.2 README update line if wording changes. Bump the tools version (minor).

## 5. Desktop checks (after release)

- [ ] 5.1 Mac: a configurator left running across a command-line reinstall shows Restart and comes back in the new version.
- [ ] 5.2 Windows: an update with a forced uv failure (e.g. a read-only wheel cache) restores the old env, and the Start menu shortcut still works.
